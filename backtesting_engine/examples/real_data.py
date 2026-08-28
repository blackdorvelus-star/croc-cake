"""Loaders for the real historical EUR/USD datasets bundled under data/.

Kept in one module so every example/script that needs real data shares the
same loading and cleaning logic instead of duplicating it. See README.md
for full provenance notes and caveats on each file -- summarized briefly
in each loader's docstring below.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

OHLCV_COLUMNS = ["open", "high", "low", "close", "volume"]


def load_eurusd_h1_2020_covid(path: Path = DATA_DIR / "EURUSD_H1_2020.csv") -> pd.DataFrame:
    """~4 months of real EUR/USD H1 bid OHLC bars, 2020-01-02 to
    2020-04-24 (spans the March 2020 COVID crash). FXCM/ForexConnect-style
    export; timestamps assumed UTC (undocumented at the source)."""
    df = pd.read_csv(path, parse_dates=["date"], index_col="date")
    df.index = df.index.tz_localize("UTC")
    df = df.rename(
        columns={"bidopen": "open", "bidhigh": "high", "bidlow": "low", "bidclose": "close", "tickqty": "volume"}
    )
    return df[OHLCV_COLUMNS]


def load_eurusd_h1_2020_2023(path: Path = DATA_DIR / "EURUSD_H1_2020_2023.csv") -> pd.DataFrame:
    """~3 years of real EUR/USD H1 OHLC bars, 2020-07-01 to 2023-07-14
    (Dukascopy Historical Data Feed export, "Gmt time" column -> already
    UTC). Genuinely gapped over weekends/holidays -- no cleaning needed.
    """
    df = pd.read_csv(path)
    df["Gmt time"] = pd.to_datetime(df["Gmt time"], format="%d.%m.%Y %H:%M:%S.%f", utc=True)
    df = df.set_index("Gmt time")
    df.columns = [column.lower() for column in df.columns]
    return df[OHLCV_COLUMNS]


def load_eurusd_h1_2004_2024(path: Path = DATA_DIR / "EURUSD_H1_2004_2024_raw.csv") -> pd.DataFrame:
    """~20 years of real EUR/USD H1 OHLC bars, 2004-01-01 to 2024-03-30
    (Dukascopy export, "Local time" column at a fixed GMT+0800 offset --
    verified constant across the whole file, no DST, so a flat -8h shift
    to UTC is correct here).

    Unlike the 2020-2023 file above, this export was padded to a
    continuous 24/7 hourly grid: closed-market hours (Saturdays, most of
    Sunday, holidays) appear as flat OHLC / zero-volume filler rows
    instead of being absent -- about 29% of the raw file. Those rows carry
    no real price information and are dropped here (`volume > 0`).
    """
    df = pd.read_csv(path)
    naive_utc = pd.to_datetime(
        df["Local time"].str.replace(" GMT+0800", "", regex=False), format="%d.%m.%Y %H:%M:%S.%f"
    ) - pd.Timedelta(hours=8)
    df.index = naive_utc.dt.tz_localize("UTC")
    df.columns = [column.lower() for column in df.columns]
    df = df[df["volume"] > 0]
    return df[OHLCV_COLUMNS]
