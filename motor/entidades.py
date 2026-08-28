"""Domínio puro — sem imports de infraestrutura.

Unidade canônica: TICKS (1 tick WIN = 5 pontos = R$ 1,00/contrato).
Conversão para reais só na borda (relatórios).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

PONTOS_POR_TICK = 5
REAIS_POR_TICK = 1.0  # WIN: 5 pontos × R$0,20


class Lado(Enum):
    COMPRA = "compra"
    VENDA = "venda"


@dataclass(frozen=True)
class Candle:
    ts: datetime
    abertura: float
    maxima: float
    minima: float
    fechamento: float
    volume_qtd: int
    contrato: str  # ex.: WINQ26; "CONT" na série contínua ajustada


@dataclass(frozen=True)
class Sinal:
    ts: datetime
    lado: Lado
    stop_ticks: int
    alvo_ticks: int


@dataclass(frozen=True)
class Trade:
    entrada_ts: datetime
    saida_ts: datetime
    lado: Lado
    resultado_ticks: float  # líquido de custos
    conta: str  # "backtest" | "simulado" | "real"
    estrategia: str


@dataclass(frozen=True)
class RegrasDeRisco:
    """Kill criteria — espelho do Gerenciador de Risco do Profit (constitution)."""

    perda_maxima_dia_reais: float = 200.0
    meta_dia_reais: float = 400.0
    drawdown_dia_reais: float = 200.0
    perdas_consecutivas_max: int = 5
    trades_dia_max: int = 10
    hora_limite: int = 13  # sem ordens novas a partir daqui

    def pode_operar(
        self,
        pnl_dia_reais: float,
        pico_dia_reais: float,
        perdas_seguidas: int,
        trades_no_dia: int,
        hora: int,
    ) -> bool:
        if pnl_dia_reais <= -self.perda_maxima_dia_reais:
            return False
        if pnl_dia_reais >= self.meta_dia_reais:
            return False
        if pico_dia_reais - pnl_dia_reais >= self.drawdown_dia_reais:
            return False
        if perdas_seguidas >= self.perdas_consecutivas_max:
            return False
        if trades_no_dia >= self.trades_dia_max:
            return False
        if hora >= self.hora_limite:
            return False
        return True
