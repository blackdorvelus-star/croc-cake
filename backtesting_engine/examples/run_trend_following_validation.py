"""Validates the Donchian/Turtle trend-following strategy on real EUR/USD
data, using textbook parameters -- not tuned on this data at all.

The original Turtle system counts lookbacks in trading *days* (System 1:
20-day entry / 10-day exit; System 2: 55-day entry / 20-day exit; ATR
period 20 days), designed for markets trading roughly one session a day.
FX trades close to 24 hours across 5 weekdays, so "N days" is converted
here to "N * 24" H1 bars -- a literal, non-fitted unit conversion, not a
parameter search. Both systems are run unmodified across the full 20-year
dataset and across 5 independent ~4-year windows (see
run_replication_check.py for why independent windows matter more than a
single full-sample number).

Run with:
    python -m backtesting_engine.examples.run_trend_following_validation
"""
from __future__ import annotations

import logging
import queue
from dataclasses import dataclass

from backtesting_engine import (
    Backtest,
    DonchianTrendStrategy,
    ForexCommissionModel,
    ForexPositionSizer,
    ForexSlippageModel,
    HistoricCSVDataHandler,
    Portfolio,
    RiskManager,
    SimulatedExecutionHandler,
    compute_performance_report,
)
from backtesting_engine.examples.real_data import load_eurusd_h1_2004_2024
from backtesting_engine.examples.run_replication_check import WINDOWS

SYMBOL = "EURUSD"
PIP_VALUE = 0.0001
RISK_PER_TRADE_PCT = 0.01
INITIAL_CAPITAL = 100_000.0

BARS_PER_DAY = 24  # FX trades ~24h across weekdays; a literal unit conversion, not a fit


@dataclass
class TurtleSystem:
    name: str
    entry_days: int
    exit_days: int
    atr_days: int
    atr_stop_multiple: float = 2.0


SYSTEMS = [
    TurtleSystem("System 1 (20d entry / 10d exit)", entry_days=20, exit_days=10, atr_days=20),
    TurtleSystem("System 2 (55d entry / 20d exit)", entry_days=55, exit_days=20, atr_days=20),
]


def run_pipeline(system: TurtleSystem, symbol_data):
    event_queue: "queue.Queue" = queue.Queue()
    data_handler = HistoricCSVDataHandler(event_queue, {SYMBOL: symbol_data})
    strategy = DonchianTrendStrategy(
        symbol_list=[SYMBOL],
        event_queue=event_queue,
        entry_lookback=system.entry_days * BARS_PER_DAY,
        exit_lookback=system.exit_days * BARS_PER_DAY,
        atr_period=system.atr_days * BARS_PER_DAY,
        atr_stop_multiple=system.atr_stop_multiple,
        pip_value=PIP_VALUE,
    )
    position_sizer = ForexPositionSizer(risk_per_trade_pct=RISK_PER_TRADE_PCT, pip_value_per_standard_lot=10.0)
    portfolio = Portfolio(
        symbol_list=[SYMBOL], initial_capital=INITIAL_CAPITAL, position_sizer=position_sizer, fixed_order_quantity=1_000
    )
    risk_manager = RiskManager(portfolio=portfolio, max_orders_per_minute=1_000_000, max_drawdown_pct=0.02)
    execution_handler = SimulatedExecutionHandler(
        event_queue,
        commission_model=ForexCommissionModel(commission_per_standard_lot=3.0),
        slippage_model=ForexSlippageModel(slippage_pips=0.5, is_jpy_pair=False),
    )
    backtest = Backtest(
        data_handler=data_handler,
        strategy=strategy,
        portfolio=portfolio,
        risk_manager=risk_manager,
        execution_handler=execution_handler,
        heartbeat_timeout_seconds=120.0,
    )
    backtest.run()
    return portfolio, risk_manager


def main() -> None:
    logging.basicConfig(level=logging.ERROR, format="%(asctime)s %(levelname)s %(message)s")
    symbol_data = load_eurusd_h1_2004_2024()
    print(f"Loaded {len(symbol_data)} bars: {symbol_data.index[0]} -> {symbol_data.index[-1]}")

    for system in SYSTEMS:
        print(f"\n{'=' * 78}\n{system.name}\n{'=' * 78}")

        portfolio, risk_manager = run_pipeline(system, symbol_data)
        report = compute_performance_report(portfolio, risk_per_trade_pct=RISK_PER_TRADE_PCT)
        print(f"Full 20-year sample: {report}")
        if risk_manager.trading_halted:
            print(f"  (RiskManager halted trading: {risk_manager.halt_reason})")

        print("\nIndependent ~4-year windows:")
        window_pnls = []
        for window in WINDOWS:
            data = symbol_data.loc[window.start : window.end]
            window_portfolio, window_risk_manager = run_pipeline(system, data)
            window_report = compute_performance_report(window_portfolio, risk_per_trade_pct=RISK_PER_TRADE_PCT)
            halted_note = " [drawdown halt]" if window_risk_manager.trading_halted else ""
            print(f"  {window.name}: {window_report}{halted_note}")
            window_pnls.append(window_report.total_pnl)

        positive_windows = sum(1 for pnl in window_pnls if pnl > 0)
        print(f"\nPositive in {positive_windows}/{len(WINDOWS)} independent windows.")


if __name__ == "__main__":
    main()
