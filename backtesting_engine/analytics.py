"""Post-hoc performance analytics.

Deliberately kept separate from Portfolio/RiskManager/ExecutionHandler:
nothing here feeds back into a trading decision, it only summarizes what
already happened (Single Responsibility). Used to answer one question --
does a strategy's entry signal show any edge at all, net of realistic
costs -- rather than to size or manage risk in real time.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional

from .portfolio import EquityPoint, Portfolio, TradeRecord


@dataclass
class PerformanceReport:
    num_trades: int
    win_rate: Optional[float]
    total_pnl: float
    average_pnl_per_trade: Optional[float]
    profit_factor: Optional[float]
    max_drawdown_pct: float
    final_equity: float
    average_r: Optional[float] = None  # only set when a risk_per_trade_pct is supplied

    def __str__(self) -> str:  # pragma: no cover - formatting only
        r_part = f", avg_R={self.average_r:+.2f}" if self.average_r is not None else ""
        return (
            f"trades={self.num_trades} win_rate={self._fmt_pct(self.win_rate)} "
            f"profit_factor={self._fmt(self.profit_factor)} total_pnl={self.total_pnl:+.2f} "
            f"avg_pnl/trade={self._fmt(self.average_pnl_per_trade)}{r_part} "
            f"max_dd={self.max_drawdown_pct:.2%} final_equity={self.final_equity:.2f}"
        )

    @staticmethod
    def _fmt(value: Optional[float]) -> str:
        return "n/a" if value is None or math.isnan(value) or math.isinf(value) else f"{value:.4f}"

    @staticmethod
    def _fmt_pct(value: Optional[float]) -> str:
        return "n/a" if value is None else f"{value:.1%}"


def _max_drawdown_pct(equity_curve: List[EquityPoint]) -> float:
    peak = float("-inf")
    max_dd = 0.0
    for point in equity_curve:
        peak = max(peak, point.equity)
        if peak > 0:
            max_dd = max(max_dd, (peak - point.equity) / peak)
    return max_dd


def compute_performance_report(
    portfolio: Portfolio,
    risk_per_trade_pct: Optional[float] = None,
) -> PerformanceReport:
    """Summarize a finished backtest's closed trades and equity curve.

    `risk_per_trade_pct` is optional and purely descriptive: when given, it
    approximates the dollar amount risked per trade as
    `initial_capital * risk_per_trade_pct` (the fixed-fractional sizing
    convention used by `ForexPositionSizer`) to express average P&L in R
    multiples. Portfolio itself is never told about this percentage --
    keeping "how much was risked" a sizing concern and "how did it turn
    out" an analytics concern.
    """
    trades: List[TradeRecord] = portfolio.closed_trades
    num_trades = len(trades)

    if num_trades == 0:
        return PerformanceReport(
            num_trades=0,
            win_rate=None,
            total_pnl=0.0,
            average_pnl_per_trade=None,
            profit_factor=None,
            max_drawdown_pct=_max_drawdown_pct(portfolio.equity_curve),
            final_equity=portfolio.current_equity,
        )

    wins = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl <= 0]
    total_pnl = sum(t.pnl for t in trades)
    gross_profit = sum(t.pnl for t in wins)
    gross_loss = -sum(t.pnl for t in losses)

    if gross_loss > 0:
        profit_factor = gross_profit / gross_loss
    elif gross_profit > 0:
        profit_factor = float("inf")
    else:
        profit_factor = float("nan")

    average_r = None
    if risk_per_trade_pct is not None and risk_per_trade_pct > 0:
        risk_amount = portfolio.initial_capital * risk_per_trade_pct
        if risk_amount > 0:
            average_r = (total_pnl / num_trades) / risk_amount

    return PerformanceReport(
        num_trades=num_trades,
        win_rate=len(wins) / num_trades,
        total_pnl=total_pnl,
        average_pnl_per_trade=total_pnl / num_trades,
        profit_factor=profit_factor,
        max_drawdown_pct=_max_drawdown_pct(portfolio.equity_curve),
        final_equity=portfolio.current_equity,
        average_r=average_r,
    )
