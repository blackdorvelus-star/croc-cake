"""Does the one positive walk-forward result actually replicate?

run_walk_forward_validation.py found exactly one out-of-sample win in 4
(strategy x fold) comparisons: ICT2022Strategy with the HTF daily-bias
filter alone (no take-profit, no ADX gate) turned a losing 2018-2024 test
window (baseline profit_factor 0.93) into a winning one (profit_factor
1.18). That is one data point -- with only 4 comparisons total, a single
positive is exactly what pure chance would produce even with zero real
edge.

This script does NOT re-select or re-tune anything: the two
configurations below (ICT2022Strategy baseline vs. +HTF-bias, and
ICTKillzoneStrategy baseline vs. +ADX<25, the other fold-1 selection) are
fixed a priori from the previous run and replayed unmodified across 5
independent, non-overlapping ~4-year windows spanning the full 20-year
dataset. If HTF-bias-filtered ICT2022Strategy is a real effect, it should
beat its own baseline in most windows, not just the one it was already
seen to win in. If it doesn't, the original result was very likely noise.

Run with:
    python -m backtesting_engine.examples.run_replication_check
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from backtesting_engine.examples.real_data import load_eurusd_h1_2004_2024
from backtesting_engine.examples.run_walk_forward_validation import (
    RISK_PER_TRADE_PCT,
    Config,
    compute_performance_report,
    run_pipeline,
)


@dataclass
class Window:
    name: str
    start: str
    end: str


WINDOWS = [
    Window("2004-2007", "2004-01-01", "2007-12-31"),
    Window("2008-2011", "2008-01-01", "2011-12-31"),
    Window("2012-2015", "2012-01-01", "2015-12-31"),
    Window("2016-2019", "2016-01-01", "2019-12-31"),
    Window("2020-2024", "2020-01-01", "2024-03-29"),
]

BASELINE: Config = (None, None, None)
ICT2022_HTF_BIAS_ONLY: Config = (50, None, None)
KILLZONE_ADX_ONLY: Config = (None, None, 25.0)


def _run(strategy_name: str, symbol_data, config: Config):
    portfolio = run_pipeline(strategy_name, symbol_data, config)
    return compute_performance_report(portfolio, risk_per_trade_pct=RISK_PER_TRADE_PCT)


def check_replication(strategy_name: str, config: Config, config_label: str, symbol_data) -> None:
    print(f"\n=== {strategy_name}: baseline vs. {config_label} across 5 independent windows ===")
    wins_for_filter = 0
    comparable_windows = 0
    for window in WINDOWS:
        data = symbol_data.loc[window.start : window.end]
        baseline = _run(strategy_name, data, BASELINE)
        filtered = _run(strategy_name, data, config)

        print(f"\n--- {window.name} ---")
        print(f"  baseline: {baseline}")
        print(f"  {config_label}: {filtered}")

        if baseline.num_trades == 0 and filtered.num_trades == 0:
            continue
        comparable_windows += 1
        if filtered.total_pnl > baseline.total_pnl:
            wins_for_filter += 1

    print(
        f"\n{config_label} beat its own baseline in {wins_for_filter}/{comparable_windows} "
        f"independent windows."
    )
    if wins_for_filter <= comparable_windows / 2:
        print(
            "-> Does not replicate: winning in half the windows or fewer is consistent with "
            "no real effect. The original positive fold was very likely noise."
        )
    else:
        print(
            "-> Replicates more often than not, but 5 windows is still a small sample -- "
            "suggestive, not confirmed."
        )


def main() -> None:
    logging.basicConfig(level=logging.ERROR, format="%(asctime)s %(levelname)s %(message)s")
    symbol_data = load_eurusd_h1_2004_2024()
    print(f"Loaded {len(symbol_data)} bars: {symbol_data.index[0]} -> {symbol_data.index[-1]}")

    check_replication("2022", ICT2022_HTF_BIAS_ONLY, "HTF-bias-only", symbol_data)
    check_replication("killzone", KILLZONE_ADX_ONLY, "ADX<25-only", symbol_data)


if __name__ == "__main__":
    main()
