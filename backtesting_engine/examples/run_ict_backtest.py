"""End-to-end demo of the ICT killzone strategy on synthetic EUR/USD data.

Run with:
    python -m backtesting_engine.examples.run_ict_backtest

Generates several days of 1-minute synthetic bars (so every killzone gets
exercised many times) and runs the full event-driven pipeline: DataHandler
-> ICTKillzoneStrategy -> Portfolio -> RiskManager -> ExecutionHandler,
using FX-specific cost and position-sizing models (ForexCommissionModel,
ForexSlippageModel, ForexPositionSizer) instead of the generic
equity-style ones used by the ML demo.
"""
from __future__ import annotations

import logging
import queue
import random

import pandas as pd

from backtesting_engine import (
    Backtest,
    ForexCommissionModel,
    ForexPositionSizer,
    ForexSlippageModel,
    HistoricCSVDataHandler,
    ICTKillzoneStrategy,
    Portfolio,
    RiskManager,
    SimulatedExecutionHandler,
)

PIP_VALUE = 0.0001  # EUR/USD is not a JPY pair


def make_synthetic_intraday_ohlcv(n_days: int = 5, start_price: float = 1.0850, seed: int = 11) -> pd.DataFrame:
    """Multi-day, 1-minute synthetic EUR/USD-like OHLCV series with
    exaggerated noise so that liquidity-sweep-like wicks occur often enough
    to exercise the strategy in a short demo run."""
    rng = random.Random(seed)
    periods = n_days * 24 * 60
    dates = pd.date_range("2024-01-01", periods=periods, freq="min")

    rows = []
    price = start_price
    for _ in range(periods):
        drift = rng.uniform(-0.0006, 0.0006)
        price = max(price * (1 + drift), 0.0001)
        wick_up = price * rng.uniform(0.0002, 0.0015)
        wick_down = price * rng.uniform(0.0002, 0.0015)
        high = price + wick_up
        low = max(price - wick_down, 0.0001)
        volume = rng.uniform(500, 5_000)  # tick volume, not real FX turnover
        rows.append({"open": price, "high": high, "low": low, "close": price, "volume": volume})
    return pd.DataFrame(rows, index=dates)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    symbol = "EURUSD"
    event_queue: "queue.Queue" = queue.Queue()

    symbol_data = {symbol: make_synthetic_intraday_ohlcv(n_days=5)}
    data_handler = HistoricCSVDataHandler(event_queue, symbol_data)

    strategy = ICTKillzoneStrategy(
        symbol_list=[symbol],
        event_queue=event_queue,
        swing_lookback=10,
        mss_confirmation_bars=5,
        pip_value=PIP_VALUE,
    )
    position_sizer = ForexPositionSizer(risk_per_trade_pct=0.01, pip_value_per_standard_lot=10.0)
    portfolio = Portfolio(
        symbol_list=[symbol],
        initial_capital=100_000.0,
        position_sizer=position_sizer,
        fixed_order_quantity=1_000,  # fallback only, used if stop_loss_pips is ever missing
    )
    risk_manager = RiskManager(portfolio=portfolio, max_orders_per_minute=20, max_drawdown_pct=0.02)
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
        heartbeat_timeout_seconds=30.0,
    )
    backtest.run()

    print(f"Final equity: {portfolio.current_equity:.2f}")
    print(f"Trading halted by RiskManager: {risk_manager.trading_halted} ({risk_manager.halt_reason})")


if __name__ == "__main__":
    main()
