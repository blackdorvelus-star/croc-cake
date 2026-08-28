"""Smoke tests for the bundled real EUR/USD data loaders.

These load actual CSV files under data/ (no network access), so they
mainly guard against the loaders silently breaking (wrong columns, wrong
index type) and against the raw files no longer matching the shape the
cleaning logic assumes.
"""
from __future__ import annotations

import unittest

from backtesting_engine.examples.real_data import (
    OHLCV_COLUMNS,
    load_eurusd_h1_2004_2024,
    load_eurusd_h1_2020_2023,
    load_eurusd_h1_2020_covid,
)


class RealDataLoaderTests(unittest.TestCase):
    def _assert_well_formed(self, df) -> None:
        self.assertListEqual(list(df.columns), OHLCV_COLUMNS)
        self.assertTrue(df.index.is_monotonic_increasing)
        self.assertIsNotNone(df.index.tz)
        self.assertGreater(len(df), 0)
        self.assertFalse(df[OHLCV_COLUMNS].isna().any().any())

    def test_covid_2020_dataset(self) -> None:
        df = load_eurusd_h1_2020_covid()
        self._assert_well_formed(df)
        self.assertGreater(len(df), 1_500)
        self.assertLess(len(df), 2_500)
        # Real FX calendar: closed all Saturday.
        self.assertNotIn("Saturday", set(df.index.day_name()))

    def test_2020_2023_dataset(self) -> None:
        df = load_eurusd_h1_2020_2023()
        self._assert_well_formed(df)
        self.assertGreater(len(df), 15_000)
        self.assertNotIn("Saturday", set(df.index.day_name()))

    def test_2004_2024_dataset_drops_weekend_padding(self) -> None:
        df = load_eurusd_h1_2004_2024()
        self._assert_well_formed(df)
        self.assertGreater(len(df), 100_000)
        # The raw file pads Saturdays with flat/zero-volume filler rows;
        # the loader must drop all of them (volume > 0 filter).
        self.assertNotIn("Saturday", set(df.index.day_name()))
        self.assertTrue((df["volume"] > 0).all())


if __name__ == "__main__":
    unittest.main()
