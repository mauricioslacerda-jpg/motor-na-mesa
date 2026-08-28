"""Estratégias concretas — regras SE-ENTÃO promulgadas (progresso.md F1).

Setup de estreia (promulgado 2026-08-05): cruzamento de médias exponenciais
rápida×lenta (Matsura cap. 8, p.111-112). COMPRA quando a rápida cruza a lenta
de baixo para cima; VENDA (short) no cruzamento inverso. Stop e alvo fixos em
ticks vêm do Sinal; o motor aplica slippage, custos e a zeragem de fim de sessão.
"""
from __future__ import annotations

from .entidades import Candle, Lado, Sinal


def ema(valores: list[float], periodo: int) -> list[float]:
    """Média móvel exponencial clássica (seed = primeiro valor)."""
    if not valores:
        return []
    k = 2.0 / (periodo + 1)
    serie = [valores[0]]
    for v in valores[1:]:
        serie.append(v * k + serie[-1] * (1 - k))
    return serie


class EstrategiaCruzamentoEMA:
    """Cruzamento de EMAs sobre fechamentos. Nunca olha o futuro:

    o sinal usa apenas o histórico recebido; a entrada ocorre na abertura
    do candle SEGUINTE (regra do motor).
    """

    def __init__(self, rapida: int = 10, lenta: int = 50,
                 stop_ticks: int = 40, alvo_ticks: int = 80):
        self.nome = f"cruzamento-ema-{rapida}x{lenta}"
        self._rapida = rapida
        self._lenta = lenta
        self._stop = stop_ticks
        self._alvo = alvo_ticks

    def avaliar(self, historico: list[Candle]) -> Sinal | None:
        if len(historico) < self._lenta + 1:
            return None
        fechamentos = [c.fechamento for c in historico]
        r = ema(fechamentos, self._rapida)
        l = ema(fechamentos, self._lenta)
        cruzou_para_cima = r[-2] <= l[-2] and r[-1] > l[-1]
        cruzou_para_baixo = r[-2] >= l[-2] and r[-1] < l[-1]
        if not (cruzou_para_cima or cruzou_para_baixo):
            return None
        lado = Lado.COMPRA if cruzou_para_cima else Lado.VENDA
        return Sinal(ts=historico[-1].ts, lado=lado,
                     stop_ticks=self._stop, alvo_ticks=self._alvo)
