"""Motor de backtest — regras pessimistas (finds.md 2026-07-26; emendas Akita 2026-07-26).

- Gap de abertura atravessando o stop → preenche NA ABERTURA (perda real, não o stop nominal).
- Stop e alvo no mesmo candle → stop bateu primeiro.
- Entrada a mercado e saída por stop pagam SLIPPAGE_TICKS; alvo (ordem limite) não paga.
- Daytrade estrito: posição nunca cruza a fronteira da sessão — fecha à força no
  fechamento do último candle do dia.
- Custo por round-trip descontado em cada trade, nunca agregado.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Protocol

from .entidades import PONTOS_POR_TICK, Candle, Lado, Sinal, Trade

SLIPPAGE_TICKS = 1


class Estrategia(Protocol):
    nome: str

    def avaliar(self, historico: list[Candle]) -> Sinal | None:
        """Retorna um sinal para o PRÓXIMO candle, ou None. Nunca olha o futuro."""
        ...


@dataclass(frozen=True)
class ResultadoBacktest:
    trades: list[Trade]
    custo_ticks_por_trade: float

    @property
    def total(self) -> int:
        return len(self.trades)

    @property
    def lucro_bruto_ticks(self) -> float:
        return sum(t.resultado_ticks for t in self.trades if t.resultado_ticks > 0)

    @property
    def prejuizo_bruto_ticks(self) -> float:
        return abs(sum(t.resultado_ticks for t in self.trades if t.resultado_ticks < 0))

    @property
    def fator_de_lucro(self) -> float:
        if self.prejuizo_bruto_ticks == 0:
            return float("inf") if self.lucro_bruto_ticks > 0 else 0.0
        return self.lucro_bruto_ticks / self.prejuizo_bruto_ticks

    @property
    def expectancia_ticks(self) -> float:
        if not self.trades:
            return 0.0
        return sum(t.resultado_ticks for t in self.trades) / len(self.trades)

    @property
    def max_drawdown_ticks(self) -> float:
        """Máximo recuo pico→vale da curva acumulada de resultado (em ticks, ≥0)."""
        acumulado = 0.0
        pico = 0.0
        max_dd = 0.0
        for t in self.trades:
            acumulado += t.resultado_ticks
            pico = max(pico, acumulado)
            max_dd = max(max_dd, pico - acumulado)
        return max_dd


def _fecha(
    entrada_ts, saida_ts, lado: Lado, resultado_ticks: float, estrategia: str
) -> Trade:
    return Trade(
        entrada_ts=entrada_ts, saida_ts=saida_ts, lado=lado,
        resultado_ticks=resultado_ticks, conta="backtest", estrategia=estrategia,
    )


def _executa_sinal(
    sinal: Sinal, candles_sessao: list[Candle], custo_ticks: float, estrategia: str
) -> Trade | None:
    """Simula 1 trade dentro de UMA sessão (daytrade estrito). Pessimista."""
    if not candles_sessao:
        return None
    entrada_candle = candles_sessao[0]
    pt = PONTOS_POR_TICK
    compra = sinal.lado is Lado.COMPRA
    if compra:
        entrada = entrada_candle.abertura + SLIPPAGE_TICKS * pt
        stop = entrada - sinal.stop_ticks * pt
        alvo = entrada + sinal.alvo_ticks * pt
    else:
        entrada = entrada_candle.abertura - SLIPPAGE_TICKS * pt
        stop = entrada + sinal.stop_ticks * pt
        alvo = entrada - sinal.alvo_ticks * pt

    def ticks(preco_saida: float) -> float:
        delta = preco_saida - entrada if compra else entrada - preco_saida
        return delta / pt

    for idx, candle in enumerate(candles_sessao):
        # 1) Gap: a abertura já violou o stop → preenche na abertura, pior que o stop
        #    (no candle de entrada idx==0 isso é impossível por construção)
        if idx > 0:
            gap_stop = candle.abertura <= stop if compra else candle.abertura >= stop
            if gap_stop:
                return _fecha(entrada_candle.ts, candle.ts, sinal.lado,
                              ticks(candle.abertura) - SLIPPAGE_TICKS - custo_ticks,
                              estrategia)
            gap_alvo = candle.abertura >= alvo if compra else candle.abertura <= alvo
            if gap_alvo:  # limite preenchida na abertura (preço melhor ou igual)
                return _fecha(entrada_candle.ts, candle.ts, sinal.lado,
                              ticks(candle.abertura) - custo_ticks, estrategia)
        # 2) Intrabar pessimista: stop antes do alvo
        bateu_stop = candle.minima <= stop if compra else candle.maxima >= stop
        if bateu_stop:
            return _fecha(entrada_candle.ts, candle.ts, sinal.lado,
                          -sinal.stop_ticks - SLIPPAGE_TICKS - custo_ticks, estrategia)
        bateu_alvo = candle.maxima >= alvo if compra else candle.minima <= alvo
        if bateu_alvo:
            return _fecha(entrada_candle.ts, candle.ts, sinal.lado,
                          sinal.alvo_ticks - custo_ticks, estrategia)

    # 3) Fim da sessão: fechamento forçado no último candle (daytrade estrito)
    ultimo = candles_sessao[-1]
    return _fecha(entrada_candle.ts, ultimo.ts, sinal.lado,
                  ticks(ultimo.fechamento) - SLIPPAGE_TICKS - custo_ticks, estrategia)


def rodar(
    estrategia: Estrategia, candles: Iterable[Candle], custo_ticks_por_trade: float
) -> ResultadoBacktest:
    serie = list(candles)
    trades: list[Trade] = []
    i = 0
    while i < len(serie) - 1:
        sinal = estrategia.avaliar(serie[: i + 1])
        if sinal is None:
            i += 1
            continue
        # sessão = candles contíguos do MESMO dia a partir da entrada
        dia = serie[i + 1].ts.date()
        sessao: list[Candle] = []
        for candle in serie[i + 1 :]:
            if candle.ts.date() != dia:
                break
            sessao.append(candle)
        trade = _executa_sinal(sinal, sessao, custo_ticks_por_trade, estrategia.nome)
        if trade is None:
            break
        trades.append(trade)
        # avança para depois do candle de saída; progresso garantido mesmo com ts duplicado
        novo_i = i + 1
        while novo_i < len(serie) and serie[novo_i].ts <= trade.saida_ts:
            novo_i += 1
        i = max(novo_i, i + 1)
    return ResultadoBacktest(trades=trades, custo_ticks_por_trade=custo_ticks_por_trade)
