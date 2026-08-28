"""End-to-end demo: wires every component together on synthetic OHLCV data.

Run with:
    python -m backtesting_engine.examples.run_backtest

A synthetic price shock is injected mid-run to exercise the RiskManager's
hard drawdown kill switch and LiquidateEvent flow.
"""
from __future__ import annotations

import logging
import queue
import random
from typing import Optional

import pandas as pd

from backtesting_engine import (
    Backtest,
    FillEvent,
    HistoricCSVDataHandler,
    MarketEvent,
    MLMomentumStrategy,
    OrderDirection,
    OrderEvent,
    OrderType,
    Portfolio,
    RiskManager,
    SimulatedExecutionHandler,
)


def make_synthetic_ohlcv(
    n_bars: int = 300,
    start_price: float = 100.0,
    seed: int = 7,
    crash_at: Optional[int] = None,
) -> pd.DataFrame:
    """Generate a synthetic OHLCV series with an optional injected shock,
    used purely to exercise the engine without needing a real data feed."""
    rng = random.Random(seed)
    dates = pd.date_range("2024-01-01", periods=n_bars, freq="min")
    rows = []
    price = start_price
    for i in range(n_bars):
        drift = rng.uniform(-0.002, 0.0025)
        if crash_at is not None and i == crash_at:
            drift = -0.05  # simulate a shock to trigger the drawdown kill switch
        price = max(price * (1 + drift), 0.01)
        high = price * (1 + rng.uniform(0, 0.001))
        low = price * (1 - rng.uniform(0, 0.001))
        volume = rng.uniform(5_000, 20_000)
        rows.append({"open": price, "high": high, "low": low, "close": price, "volume": volume})
    return pd.DataFrame(rows, index=dates)


def demonstrate_risk_kill_switch() -> None:
    """Deterministic, standalone illustration of the RiskManager's hard
    drawdown kill switch and the resulting LiquidateEvent.

    Kept separate from the ML backtest above: whether that run happens to
    breach the drawdown limit depends on the (stochastic) dummy model's
    positioning at the moment of the injected shock, so this function
    exercises the kill switch directly and predictably instead.
    """
    print("\n--- RiskManager hard drawdown kill switch (deterministic demo) ---")
    symbol = "DEMO"
    portfolio = Portfolio(symbol_list=[symbol], initial_capital=100_000.0, fixed_order_quantity=500)
    risk_manager = RiskManager(portfolio=portfolio, max_drawdown_pct=0.02)

    # Open a long position via a realistic FillEvent (debits cash + commission).
    opening_fill = FillEvent(symbol, 500, OrderDirection.BUY, fill_price=100.0, commission=25.0, slippage=0.0)
    portfolio.update_fill(opening_fill)
    portfolio.update_timeindex(MarketEvent(symbol, {"close": 100.0, "volume": 10_000}))
    print(f"Equity after opening position: {portfolio.current_equity:.2f}")

    # Shock: price drops 10% against the open long position.
    portfolio.update_timeindex(MarketEvent(symbol, {"close": 90.0, "volume": 10_000}))
    print(f"Equity after shock: {portfolio.current_equity:.2f}")

    liquidate_event = risk_manager.evaluate_portfolio_risk()
    print(f"RiskManager.trading_halted: {risk_manager.trading_halted}")
    print(f"LiquidateEvent emitted: {liquidate_event}")

    rejected = risk_manager.process_order(
        OrderEvent(symbol, OrderType.MARKET, 100, OrderDirection.BUY)
    )
    print(f"New order after halt accepted: {rejected is not None}")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    symbol = "DEMO"
    event_queue: "queue.Queue" = queue.Queue()

    symbol_data = {symbol: make_synthetic_ohlcv(n_bars=300, crash_at=150)}
    data_handler = HistoricCSVDataHandler(event_queue, symbol_data)

    strategy = MLMomentumStrategy(
        symbol_list=[symbol],
        event_queue=event_queue,
        lookback=20,
        inference_every_n_bars=3,
    )
    portfolio = Portfolio(symbol_list=[symbol], initial_capital=100_000.0, fixed_order_quantity=100)
    risk_manager = RiskManager(portfolio=portfolio, max_orders_per_minute=10, max_drawdown_pct=0.02)
    execution_handler = SimulatedExecutionHandler(event_queue)

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

    demonstrate_risk_kill_switch()


if __name__ == "__main__":
    main()
