"""Data handling layer for the event-driven backtesting engine.

DataHandler is the *only* component allowed to read market data. It never
computes signals or executes trades: on each iteration of the main loop it
pushes exactly one MarketEvent per symbol (the next unseen bar) onto the
shared event queue. Swap the concrete implementation for one backed by a
live broker/websocket feed to move from backtest to production without
touching Strategy, Portfolio, RiskManager or ExecutionHandler at all
(Open/Closed + Dependency Inversion).
"""
from __future__ import annotations

import abc
import queue
from typing import Dict, Iterator, List

import pandas as pd

from .event import MarketEvent


class DataHandler(abc.ABC):
    """Abstract base class all data handlers must implement."""

    continue_backtest: bool = True

    @abc.abstractmethod
    def get_latest_bars(self, symbol: str, n: int = 1) -> List[dict]:
        """Return up to the last n bars received so far for a symbol (oldest first)."""

    @abc.abstractmethod
    def update_bars(self) -> None:
        """Push the next bar for every symbol as a MarketEvent onto the queue."""


class HistoricCSVDataHandler(DataHandler):
    """Feeds historical OHLCV bars from in-memory pandas DataFrames.

    Each symbol maps to a DataFrame indexed by a monotonically increasing
    DatetimeIndex with columns ['open', 'high', 'low', 'close', 'volume'].
    The name is kept as `HistoricCSV...` because in practice these frames
    are typically produced by `pd.read_csv(...)`; loading from disk is
    intentionally left to the caller so this class stays trivially testable
    with synthetic data.
    """

    def __init__(self, event_queue: "queue.Queue", symbol_data: Dict[str, pd.DataFrame]) -> None:
        if not symbol_data:
            raise ValueError("symbol_data must contain at least one symbol")

        self.event_queue = event_queue
        self.symbol_list = list(symbol_data.keys())
        self._latest_bars: Dict[str, List[dict]] = {symbol: [] for symbol in self.symbol_list}
        self._iterators: Dict[str, Iterator[dict]] = {
            symbol: self._row_iterator(df) for symbol, df in symbol_data.items()
        }
        self.continue_backtest = True

    @staticmethod
    def _row_iterator(df: pd.DataFrame) -> Iterator[dict]:
        required_columns = {"open", "high", "low", "close", "volume"}
        missing = required_columns - set(df.columns)
        if missing:
            raise ValueError(f"DataFrame is missing required columns: {missing}")

        for ts, row in df.iterrows():
            yield {
                "timestamp": ts,
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row["volume"]),
            }

    def get_latest_bars(self, symbol: str, n: int = 1) -> List[dict]:
        bars = self._latest_bars.get(symbol, [])
        return bars[-n:]

    def update_bars(self) -> None:
        exhausted_count = 0
        for symbol in self.symbol_list:
            try:
                bar = next(self._iterators[symbol])
            except StopIteration:
                exhausted_count += 1
                continue
            self._latest_bars[symbol].append(bar)
            self.event_queue.put(MarketEvent(symbol=symbol, bar=bar))

        if exhausted_count == len(self.symbol_list):
            self.continue_backtest = False
