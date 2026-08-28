"""End-to-end demo of the ICT "2022 Model" strategy on synthetic EUR/USD data.

Run with:
    python -m backtesting_engine.examples.run_ict_2022_backtest

Same pipeline and FX cost/sizing models as run_ict_backtest.py, but driven
by ICT2022Strategy's stricter sweep -> MSS -> FVG -> time-boxed-entry state
machine instead of the simpler sweep+MSS-only ICTKillzoneStrategy.
"""
from __future__ import annotations

import logging
import queue

from backtesting_engine import (
    Backtest,
    ForexCommissionModel,
    ForexPositionSizer,
    ForexSlippageModel,
    HistoricCSVDataHandler,
    ICT2022Strategy,
    Portfolio,
    RiskManager,
    SimulatedExecutionHandler,
)
from backtesting_engine.examples.run_ict_backtest import make_synthetic_intraday_ohlcv

PIP_VALUE = 0.0001  # EUR/USD is not a JPY pair


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    symbol = "EURUSD"
    event_queue: "queue.Queue" = queue.Queue()

    symbol_data = {symbol: make_synthetic_intraday_ohlcv(n_days=10)}
    data_handler = HistoricCSVDataHandler(event_queue, symbol_data)

    strategy = ICT2022Strategy(
        symbol_list=[symbol],
        event_queue=event_queue,
        max_bars_awaiting_mss=15,
        max_bars_awaiting_fvg=10,
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
