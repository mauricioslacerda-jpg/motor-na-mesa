"""Coletor do painel "Motor na Mesa" — dados públicos, motor real, HTML estático.

Roda a cada 10 min no GitHub Actions durante o pregão. Sem credencial, sem
custo por ciclo, sem tocar em conta nenhuma. Fontes:
  1. Yahoo Finance ^BVSP 15m (público, atraso ~15 min declarado no painel)
  2. RSS do InfoMoney (manchetes com hora e link)
Roda o motor pessimista vendorizado em motor/ (mesmo código de
chalal/daytrade-win/src/domain) e regenera docs/index.html.

Uso: python coletor.py [--forcar]
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from motor.backtest import SLIPPAGE_TICKS, rodar
from motor.entidades import Candle
from motor.estrategias import EstrategiaCruzamentoEMA, ema

TZ = ZoneInfo("America/Sao_Paulo")
SIMBOLO = "^BVSP"
CUSTO_TICKS = 0.5          # emolumentos B3 ~R$0,50 round-trip (finds.md 2026-07-31)
STOP_TICKS, ALVO_TICKS = 40, 80
EMA_RAPIDA, EMA_LENTA = 10, 50
RSS_INFOMONEY = "https://www.infomoney.com.br/feed/"
INICIO_PROJETO = date(2026, 7, 26)   # dia 1 do projeto; o painel conta a mesma
                                     # história que o artefato, sem janela móvel
SGS_CDI = 12               # Banco Central, série 12: CDI diário (% a.d.)
CAPITAL_REF = 5000.0       # banca de teste declarada em claude.md (< R$ 5.000)
IR_DAYTRADE, IR_CDB = 0.20, 0.225
MAX_MANCHETES = 10
ABRE, FECHA = time(8, 0), time(18, 5)
RAIZ = Path(__file__).parent
SAIDA = RAIZ / "docs" / "index.html"
UA = {"User-Agent": "Mozilla/5.0 (motor-na-mesa; painel publico)"}


# ---------------------------------------------------------------- guardas
def dentro_da_janela(agora: datetime, forcar: bool) -> tuple[bool, str]:
    """O cron do GitHub é impreciso e não sabe feriado: a guarda fica aqui."""
    if forcar:
        return True, "execucao forcada"
    if agora.weekday() >= 5:
        return False, "fim de semana"
    if not (ABRE <= agora.time() <= FECHA):
        return False, "fora da janela 08:00-18:05 BRT"
    return True, "pregao"


def prazo_encerrado(hoje: date) -> tuple[bool, str]:
    """DATA_FIM (YYYY-MM-DD) vem do workflow. Passou dela, o painel sela e para."""
    bruto = os.environ.get("DATA_FIM", "").strip()
    if not bruto:
        return False, ""
    try:
        fim = date.fromisoformat(bruto)
    except ValueError:
        return False, ""
    return (hoje > fim), fim.strftime("%d/%m")


# ---------------------------------------------------------------- coleta
def baixar_candles() -> list[Candle]:
    """Série de 15 min desde o dia 1 do projeto. O Yahoo entrega no máximo ~60
    dias nesse intervalo; passando disso, cai para a janela móvel de 2 meses."""
    inicio = datetime.combine(INICIO_PROJETO, time(0, 0), TZ)
    if (datetime.now(TZ) - inicio).days <= 55:
        janela = f"period1={int(inicio.timestamp())}&period2={int(datetime.now(TZ).timestamp())}"
    else:
        janela = "range=2mo"
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/"
           f"{urllib.request.quote(SIMBOLO)}?interval=15m&{janela}")
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as resposta:
        d = json.load(resposta)
    r = d["chart"]["result"][0]
    q = r["indicators"]["quote"][0]
    candles: list[Candle] = []
    for ts, o, h, l, c, v in zip(r["timestamp"], q["open"], q["high"],
                                 q["low"], q["close"], q["volume"]):
        if None in (o, h, l, c):
            continue
        candles.append(Candle(ts=datetime.fromtimestamp(ts, TZ).replace(tzinfo=None),
                              abertura=o, maxima=h, minima=l, fechamento=c,
                              volume_qtd=int(v or 0), contrato="BVSP-PAINEL"))
    return candles


_MESES = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}


def hora_rss(pub: str) -> str:
    """'Thu, 28 Aug 2026 14:32:00 -0300' -> '14:32' em BRT. Vazio se nao parsear."""
    m = re.search(r"(\d{1,2}) (\w{3}) (\d{4}) (\d{2}):(\d{2}):(\d{2}) ([+-]\d{4})", pub)
    if not m or m.group(2) not in _MESES:
        return ""
    dia, mes, ano, hh, mm, ss, off = m.groups()
    quando = datetime(int(ano), _MESES[mes], int(dia), int(hh), int(mm), int(ss))
    sinal = 1 if off[0] == "+" else -1
    quando -= sinal * timedelta(hours=int(off[1:3]), minutes=int(off[3:5]))
    return quando.replace(tzinfo=ZoneInfo("UTC")).astimezone(TZ).strftime("%H:%M")


def baixar_manchetes() -> list[dict]:
    """RSS do InfoMoney. Falha de rede nao derruba o painel — devolve lista vazia."""
    try:
        req = urllib.request.Request(RSS_INFOMONEY, headers=UA)
        with urllib.request.urlopen(req, timeout=20) as resposta:
            raiz = ET.fromstring(resposta.read())
    except Exception as erro:              # noqa: BLE001 — fonte externa, best effort
        print(f"[aviso] RSS indisponivel: {erro}", file=sys.stderr)
        return []
    itens = []
    for item in list(raiz.iterfind(".//item"))[:MAX_MANCHETES]:
        pub = (item.findtext("pubDate") or "").strip()
        itens.append({
            "titulo": (item.findtext("title") or "").strip(),
            "link": (item.findtext("link") or "").strip(),
            "hora": hora_rss(pub),
            "publicado_em": pub,
        })
    return itens


def baixar_cdi(desde: date) -> dict | None:
    """CDI acumulado desde a data dada (API pública do Banco Central).

    Serve ao Nulo 1 do Benchmark Triplo (custo de oportunidade). Falha de rede
    não derruba o painel: devolve None e o cartão some.
    """
    hoje = datetime.now(TZ).date()
    url = (f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{SGS_CDI}/dados"
           f"?formato=json&dataInicial={desde:%d/%m/%Y}&dataFinal={hoje:%d/%m/%Y}")
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=20) as resposta:
            serie = json.load(resposta)
    except Exception as erro:              # noqa: BLE001 — fonte externa, best effort
        print(f"[aviso] CDI indisponivel: {erro}", file=sys.stderr)
        return None
    if not serie:
        return None
    acum = 1.0
    for dia in serie:
        acum *= 1 + float(dia["valor"]) / 100
    pct = (acum - 1) * 100
    return {"pct": round(pct, 4), "dias_uteis": len(serie),
            "ate": serie[-1]["data"], "desde": f"{desde:%d/%m/%Y}",
            "reais_bruto": round(CAPITAL_REF * pct / 100, 2),
            "reais_liquido": round(CAPITAL_REF * pct / 100 * (1 - IR_CDB), 2),
            "capital_ref": CAPITAL_REF}


# ---------------------------------------------------------------- motor
def classificar_saida(resultado_ticks: float, ultimo_do_dia: bool) -> str:
    if abs(resultado_ticks - (ALVO_TICKS - CUSTO_TICKS)) < 1e-6:
        return "alvo"
    if abs(resultado_ticks - (-STOP_TICKS - SLIPPAGE_TICKS - CUSTO_TICKS)) < 1e-6:
        return "stop"
    return "zeragem" if ultimo_do_dia else "gap"


def montar_dados(candles: list[Candle], manchetes: list[dict], cdi: dict | None,
                 agora: datetime, motivo: str, selo: str) -> dict:
    estrategia = EstrategiaCruzamentoEMA(EMA_RAPIDA, EMA_LENTA,
                                         stop_ticks=STOP_TICKS, alvo_ticks=ALVO_TICKS)
    resultado = rodar(estrategia, candles, CUSTO_TICKS)
    fechamentos = [c.fechamento for c in candles]
    ultimo_ts_por_dia: dict[date, datetime] = {}
    for c in candles:
        ultimo_ts_por_dia[c.ts.date()] = c.ts

    hoje = candles[-1].ts.date()
    trades = []
    for t in resultado.trades:
        fim_de_sessao = ultimo_ts_por_dia.get(t.saida_ts.date()) == t.saida_ts
        trades.append({
            "entrada_ts": t.entrada_ts.isoformat(),
            "saida_ts": t.saida_ts.isoformat(),
            "lado": t.lado.value,
            "ticks": round(t.resultado_ticks, 2),
            "saida_por": classificar_saida(t.resultado_ticks, fim_de_sessao),
            "hoje": t.entrada_ts.date() == hoje,
        })

    do_dia = [t for t in trades if t["hoje"]]
    abertura_dia = next((c.abertura for c in candles if c.ts.date() == hoje), None)
    ultimo = candles[-1]
    variacao = ((ultimo.fechamento / abertura_dia) - 1) * 100 if abertura_dia else None

    return {
        "gerado_em": agora.isoformat(timespec="seconds"),
        "atualizado": agora.strftime("%H:%M"),
        "data_pregao": hoje.strftime("%d/%m/%Y"),
        "motivo": motivo,
        "selo": selo,
        "simbolo": SIMBOLO,
        "estrategia": estrategia.nome,
        "parametros": {"stop_ticks": STOP_TICKS, "alvo_ticks": ALVO_TICKS,
                       "custo_ticks": CUSTO_TICKS, "slippage_ticks": SLIPPAGE_TICKS},
        "ultimo_preco": round(ultimo.fechamento, 0),
        "variacao_dia_pct": round(variacao, 2) if variacao is not None else None,
        "candles": [{"ts": c.ts.isoformat(), "o": round(c.abertura, 1),
                     "h": round(c.maxima, 1), "l": round(c.minima, 1),
                     "c": round(c.fechamento, 1)} for c in candles],
        "ema_rapida": [round(v, 1) for v in ema(fechamentos, EMA_RAPIDA)],
        "ema_lenta": [round(v, 1) for v in ema(fechamentos, EMA_LENTA)],
        "trades": trades,
        "manchetes": manchetes,
        "cdi": cdi,
        "resultado_janela_reais": round(sum(t["ticks"] for t in trades), 2),
        "resultado_janela_liquido": round(
            sum(t["ticks"] for t in trades) * (1 - IR_DAYTRADE), 2),
        "metricas_janela": {
            "total": resultado.total,
            "acertos": sum(1 for t in resultado.trades if t.resultado_ticks > 0),
            "expectancia_ticks": round(resultado.expectancia_ticks, 2),
            "fator_de_lucro": (round(resultado.fator_de_lucro, 2)
                               if resultado.fator_de_lucro != float("inf") else None),
            "max_drawdown_ticks": round(resultado.max_drawdown_ticks, 1),
        },
        "metricas_dia": {
            "total": len(do_dia),
            "acertos": sum(1 for t in do_dia if t["ticks"] > 0),
            "resultado_ticks": round(sum(t["ticks"] for t in do_dia), 2),
        },
    }


# ---------------------------------------------------------------- saida
def publicar(dados: dict) -> None:
    template = (RAIZ / "template.html").read_text(encoding="utf-8")
    html = template.replace("/*{{DADOS}}*/null",
                            json.dumps(dados, ensure_ascii=False, separators=(",", ":")))
    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    SAIDA.write_text(html, encoding="utf-8")
    m, d = dados["metricas_janela"], dados["metricas_dia"]
    print(f"publicado {SAIDA} | candles={len(dados['candles'])} | "
          f"janela: {m['total']} trades exp={m['expectancia_ticks']}t | "
          f"hoje: {d['total']} trades {d['resultado_ticks']:+}t | "
          f"manchetes={len(dados['manchetes'])}")


def main() -> int:
    forcar = "--forcar" in sys.argv
    agora = datetime.now(TZ).replace(tzinfo=None)

    encerrado, fim = prazo_encerrado(agora.date())
    ok, motivo = dentro_da_janela(agora, forcar)
    if not ok and not encerrado:
        print(f"sem publicar: {motivo}")
        return 0

    candles = baixar_candles()
    if not candles:
        print("sem publicar: Yahoo nao devolveu candle")
        return 0

    selo = ""
    if encerrado:
        selo = f"monitoramento encerrado em {fim}"
    elif not any(c.ts.date() == agora.date() for c in candles):
        selo = "pregao fechado hoje"

    manchetes = [] if encerrado else baixar_manchetes()
    cdi = baixar_cdi(candles[0].ts.date())
    publicar(montar_dados(candles, manchetes, cdi, agora, motivo, selo))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
