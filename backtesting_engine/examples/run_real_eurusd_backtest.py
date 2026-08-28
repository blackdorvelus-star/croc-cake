"""Runs an ICT strategy against *real* historical EUR/USD data.

Unlike every other example in this package (which generates synthetic
OHLCV), this one loads real hourly bid OHLC bars for EUR/USD, 2020-01-02
through 2020-04-24 (bundled at backtesting_engine/data/EURUSD_H1_2020.csv;
see README.md for provenance and limitations -- notably H1 granularity,
~4 months, bid side only, source timezone unverified).

Run with:
    python -m backtesting_engine.examples.run_real_eurusd_backtest
    python -m backtesting_engine.examples.run_real_eurusd_backtest --strategy killzone
"""
from __future__ import annotations

import argparse
import logging
import queue
from pathlib import Path

import pandas as pd

from backtesting_engine import (
    Backtest,
    ForexCommissionModel,
    ForexPositionSizer,
    ForexSlippageModel,
    HistoricCSVDataHandler,
    ICT2022Strategy,
    ICTKillzoneStrategy,
    Portfolio,
    RiskManager,
    SimulatedExecutionHandler,
)

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "EURUSD_H1_2020.csv"
PIP_VALUE = 0.0001

# The source timestamps' timezone is not documented by the data's origin
# (see README.md). Assumed UTC here -- localizing explicitly (rather than
# leaving bars timezone-naive) lets KillzoneFilter convert to New York
# time with correct DST handling via `reference_timezone`, instead of a
# fixed-hour-offset guess that would silently drift across the March 2020
# US DST change this dataset spans.
SOURCE_TIMEZONE_ASSUMPTION = "UTC"
KILLZONE_REFERENCE_TIMEZONE = "America/New_York"


def load_real_eurusd_h1(path: Path = DATA_PATH) -> pd.DataFrame:
    """Loads the bundled real historical EUR/USD H1 bid OHLC data into the
    open/high/low/close/volume shape HistoricCSVDataHandler expects."""
    df = pd.read_csv(path, parse_dates=["date"], index_col="date")
    df.index = df.index.tz_localize(SOURCE_TIMEZONE_ASSUMPTION)
    df = df.rename(
        columns={"bidopen": "open", "bidhigh": "high", "bidlow": "low", "bidclose": "close", "tickqty": "volume"}
    )
    return df[["open", "high", "low", "close", "volume"]]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strategy", choices=["killzone", "2022"], default="2022")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    symbol = "EURUSD"
    event_queue: "queue.Queue" = queue.Queue()

    real_data = load_real_eurusd_h1()
    logger = logging.getLogger(__name__)
    logger.info(
        "Loaded %d real EUR/USD H1 bars: %s -> %s (source timezone assumed %s)",
        len(real_data), real_data.index[0], real_data.index[-1], SOURCE_TIMEZONE_ASSUMPTION,
    )

    data_handler = HistoricCSVDataHandler(event_queue, {symbol: real_data})

    if args.strategy == "killzone":
        strategy = ICTKillzoneStrategy(
            symbol_list=[symbol],
            event_queue=event_queue,
            swing_lookback=10,
            mss_confirmation_bars=5,
            pip_value=PIP_VALUE,
            reference_timezone=KILLZONE_REFERENCE_TIMEZONE,
        )
    else:
        strategy = ICT2022Strategy(
            symbol_list=[symbol],
            event_queue=event_queue,
            max_bars_awaiting_mss=15,
            max_bars_awaiting_fvg=10,
            pip_value=PIP_VALUE,
            reference_timezone=KILLZONE_REFERENCE_TIMEZONE,
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

    total_return_pct = (portfolio.current_equity / portfolio.initial_capital - 1) * 100
    print(f"Strategy: {args.strategy}")
    print(f"Bars processed: {len(real_data)}")
    print(f"Final equity: {portfolio.current_equity:.2f} ({total_return_pct:+.2f}%)")
    print(f"Trading halted by RiskManager: {risk_manager.trading_halted} ({risk_manager.halt_reason})")


if __name__ == "__main__":
    main()
