#!/usr/bin/env python3
"""
Cointegration discovery and long-only pair strategy backtest on Binance CSV data.

Long-only constraint:
- Never short either leg.
- When spread indicates leg A is cheap, hold A only.
- When spread indicates leg B is cheap, hold B only.
- Otherwise stay in cash.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Dict, List, Sequence

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import coint


@dataclass
class PairStat:
    symbol_x: str
    symbol_y: str
    corr: float
    pvalue: float
    beta: float
    half_life_bars: float


def load_close_matrix(data_dir: Path, interval: str, min_bars: int) -> pd.DataFrame:
    """Load all *_1m.csv files and return aligned close matrix at given interval."""
    files = sorted([p for p in data_dir.glob("*_1m.csv") if ":Zone.Identifier" not in p.name])
    if not files:
        raise RuntimeError(f"No CSV files found in {data_dir}")

    series_map: Dict[str, pd.Series] = {}
    for file_path in files:
        symbol = file_path.name.replace("_1m.csv", "")
        df = pd.read_csv(file_path, usecols=["open_time", "close"])
        df["open_time"] = pd.to_datetime(df["open_time"], utc=True, errors="coerce")
        df["close"] = pd.to_numeric(df["close"], errors="coerce")
        df = df.dropna(subset=["open_time", "close"]).drop_duplicates(subset=["open_time"])
        df = df.sort_values("open_time")
        close = df.set_index("open_time")["close"].resample(interval).last().dropna()
        if len(close) >= min_bars:
            series_map[symbol] = close

    if not series_map:
        raise RuntimeError("No symbols with enough history after resampling")

    close_df = pd.concat(series_map, axis=1, sort=True)
    close_df = close_df.sort_index()
    return close_df


def estimate_half_life(spread: pd.Series) -> float:
    """Estimate OU half-life in bars from spread mean reversion speed."""
    lag = spread.shift(1).dropna()
    delta = spread.diff().dropna()
    idx = lag.index.intersection(delta.index)
    if len(idx) < 100:
        return np.nan

    lag = lag.loc[idx]
    delta = delta.loc[idx]
    b1 = np.polyfit(lag.values, delta.values, 1)[0]
    if b1 >= 0:
        return np.nan
    return float(-np.log(2) / b1)


def find_cointegrated_pairs(
    close_df: pd.DataFrame,
    corr_threshold: float = 0.75,
    pvalue_threshold: float = 0.05,
    min_half_life: float = 6,
    max_half_life: float = 300,
) -> List[PairStat]:
    """Find cointegrated pairs with correlation and half-life filters."""
    coverage = close_df.notna().mean()
    filtered = close_df[coverage[coverage >= 0.8].index].copy()
    filtered = filtered.ffill().dropna()

    results: List[PairStat] = []
    symbols = filtered.columns.tolist()

    for sx, sy in combinations(symbols, 2):
        x = filtered[sx]
        y = filtered[sy]

        corr = x.corr(y)
        if pd.isna(corr) or float(corr) < corr_threshold:
            continue

        lx = np.log(x)
        ly = np.log(y)

        try:
            _, pvalue, _ = coint(lx, ly)
        except Exception:
            continue

        if not np.isfinite(pvalue) or float(pvalue) >= pvalue_threshold:
            continue

        beta = float(np.polyfit(lx.values, ly.values, 1)[0])
        spread = ly - beta * lx
        half_life = estimate_half_life(spread)
        if not np.isfinite(half_life):
            continue
        if not (min_half_life <= half_life <= max_half_life):
            continue

        results.append(
            PairStat(
                symbol_x=sx,
                symbol_y=sy,
                corr=float(corr),
                pvalue=float(pvalue),
                beta=beta,
                half_life_bars=float(half_life),
            )
        )

    results.sort(key=lambda r: (r.pvalue, -r.corr))
    return results


def select_top_pairs(pair_stats: Sequence[PairStat], n_pairs: int = 5, unique_symbols: bool = True) -> List[PairStat]:
    """Select top pairs, optionally preventing symbol overlap."""
    if not unique_symbols:
        return list(pair_stats[:n_pairs])

    selected: List[PairStat] = []
    used = set()
    for p in pair_stats:
        if p.symbol_x in used or p.symbol_y in used:
            continue
        selected.append(p)
        used.add(p.symbol_x)
        used.add(p.symbol_y)
        if len(selected) >= n_pairs:
            break
    return selected


def build_pair_positions(
    close_x: pd.Series,
    close_y: pd.Series,
    beta: float,
    z_window: int,
    entry_z: float,
    exit_z: float,
) -> pd.DataFrame:
    """
    Build long-only positions for one pair.

    state:
    - +1: long x
    - -1: long y
    - 0: cash
    """
    lx = np.log(close_x)
    ly = np.log(close_y)
    spread = ly - beta * lx

    mu = spread.rolling(z_window).mean()
    sd = spread.rolling(z_window).std(ddof=0)
    z = ((spread - mu) / sd).replace([np.inf, -np.inf], np.nan).fillna(0.0)

    state = pd.Series(0, index=spread.index, dtype=int)

    for i in range(1, len(z)):
        prev_state = state.iloc[i - 1]
        curr_z = z.iloc[i]

        if prev_state == 0:
            if curr_z >= entry_z:
                state.iloc[i] = 1  # y rich, x cheap -> long x
            elif curr_z <= -entry_z:
                state.iloc[i] = -1  # y cheap -> long y
            else:
                state.iloc[i] = 0
        elif prev_state == 1:
            state.iloc[i] = 0 if curr_z <= exit_z else 1
        else:
            state.iloc[i] = 0 if curr_z >= -exit_z else -1

    w_x = (state == 1).astype(float)
    w_y = (state == -1).astype(float)

    return pd.DataFrame(
        {
            "w_x": w_x,
            "w_y": w_y,
            "zscore": z,
            "state": state,
        }
    )


def run_long_only_cointegration_backtest(
    close_df: pd.DataFrame,
    selected_pairs: Sequence[PairStat],
    z_window: int,
    entry_z: float,
    exit_z: float,
    fee_bps: float,
) -> tuple[pd.DataFrame, Dict]:
    """Backtest equal-risk buckets across selected cointegrated pairs."""
    if not selected_pairs:
        raise RuntimeError("No selected pairs for backtest")

    ret_df = close_df.pct_change(fill_method=None).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    all_symbols = close_df.columns.tolist()
    weights = pd.DataFrame(0.0, index=close_df.index, columns=all_symbols)

    pair_debug = {}
    bucket = 1.0 / len(selected_pairs)

    for p in selected_pairs:
        if p.symbol_x not in close_df.columns or p.symbol_y not in close_df.columns:
            continue

        pair_pos = build_pair_positions(
            close_df[p.symbol_x],
            close_df[p.symbol_y],
            beta=p.beta,
            z_window=z_window,
            entry_z=entry_z,
            exit_z=exit_z,
        )

        weights[p.symbol_x] += pair_pos["w_x"] * bucket
        weights[p.symbol_y] += pair_pos["w_y"] * bucket
        pair_debug[f"{p.symbol_x}-{p.symbol_y}"] = pair_pos

    weights = weights.clip(lower=0.0)

    gross_turnover = weights.diff().abs().sum(axis=1).fillna(0.0)
    fee = gross_turnover * (fee_bps / 10000.0)

    port_ret = (weights.shift(1).fillna(0.0) * ret_df).sum(axis=1) - fee
    equity = (1.0 + port_ret).cumprod()

    drawdown = equity / equity.cummax() - 1.0
    mdd = float(drawdown.min())

    periods_per_year = 365 * 24 * 4  # 15min bars default assumption for annualization
    sharpe = 0.0
    if port_ret.std() > 0:
        sharpe = float(port_ret.mean() / port_ret.std() * np.sqrt(periods_per_year))

    metrics = {
        "pairs": [f"{p.symbol_x}-{p.symbol_y}" for p in selected_pairs],
        "bars": int(len(equity)),
        "total_return_pct": float((equity.iloc[-1] - 1.0) * 100.0),
        "max_drawdown_pct": float(mdd * 100.0),
        "sharpe": sharpe,
        "avg_gross_exposure": float(weights.sum(axis=1).mean()),
        "total_turnover": float(gross_turnover.sum()),
        "fee_bps": fee_bps,
    }

    out = pd.DataFrame(
        {
            "equity": equity,
            "drawdown": drawdown,
            "portfolio_return": port_ret,
            "gross_exposure": weights.sum(axis=1),
        }
    )

    return out, metrics


def save_outputs(
    out_df: pd.DataFrame,
    metrics: Dict,
    pair_stats: Sequence[PairStat],
    selected_pairs: Sequence[PairStat],
    output_dir: Path,
) -> None:
    """Save tables, chart, and summary json."""
    output_dir.mkdir(parents=True, exist_ok=True)

    out_df.to_csv(output_dir / "cointegration_backtest_timeseries.csv")

    with open(output_dir / "cointegration_backtest_metrics.json", "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)

    pair_rows = [
        {
            "symbol_x": p.symbol_x,
            "symbol_y": p.symbol_y,
            "corr": p.corr,
            "pvalue": p.pvalue,
            "beta": p.beta,
            "half_life_bars": p.half_life_bars,
            "selected": any((p.symbol_x == s.symbol_x and p.symbol_y == s.symbol_y) for s in selected_pairs),
        }
        for p in pair_stats
    ]
    pd.DataFrame(pair_rows).to_csv(output_dir / "cointegrated_pairs.csv", index=False)

    fig, axes = plt.subplots(2, 1, figsize=(13, 9), sharex=True)
    axes[0].plot(out_df.index, out_df["equity"], linewidth=1.5, label="Cointegration Long-Only")
    axes[0].set_title("Cointegration Long-Only Equity")
    axes[0].grid(alpha=0.25)
    axes[0].legend(loc="upper left")

    axes[1].fill_between(out_df.index, out_df["drawdown"], 0.0, color="#d9534f", alpha=0.35)
    axes[1].set_title("Drawdown")
    axes[1].grid(alpha=0.25)

    summary = (
        f"Return: {metrics['total_return_pct']:.2f}% | "
        f"MDD: {metrics['max_drawdown_pct']:.2f}% | "
        f"Sharpe: {metrics['sharpe']:.2f} | "
        f"Avg Exposure: {metrics['avg_gross_exposure']:.2f}"
    )
    fig.suptitle(summary, fontsize=11)
    fig.tight_layout(rect=[0, 0.02, 1, 0.97])
    fig.savefig(output_dir / "cointegration_backtest.png", dpi=150)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description="Cointegration scan + long-only pair backtest")
    parser.add_argument("--data-dir", default="historical_data/historical_data", help="Folder containing *_1m.csv")
    parser.add_argument("--interval", default="15min", help="Resample interval")
    parser.add_argument("--days", type=int, default=10, help="Lookback days (<=0 for all)")
    parser.add_argument("--min-bars", type=int, default=1500, help="Minimum bars per symbol after resample")
    parser.add_argument("--corr", type=float, default=0.75, help="Minimum correlation for pair screening")
    parser.add_argument("--pvalue", type=float, default=0.05, help="Maximum coint p-value")
    parser.add_argument("--top-pairs", type=int, default=5, help="Number of selected pairs")
    parser.add_argument("--allow-overlap", action="store_true", help="Allow symbol overlap across selected pairs")
    parser.add_argument("--z-window", type=int, default=96, help="Rolling bars for z-score")
    parser.add_argument("--entry-z", type=float, default=1.8, help="Entry threshold on z-score")
    parser.add_argument("--exit-z", type=float, default=0.4, help="Exit threshold on z-score")
    parser.add_argument("--fee-bps", type=float, default=5.0, help="Transaction fee (bps per turnover)")
    parser.add_argument("--output-dir", default="outputs/cointegration", help="Output directory")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    output_dir = Path(args.output_dir)

    close_df = load_close_matrix(data_dir, interval=args.interval, min_bars=args.min_bars)

    if args.days > 0:
        cutoff = close_df.index.max() - pd.Timedelta(days=args.days)
        close_df = close_df[close_df.index >= cutoff]

    pair_stats = find_cointegrated_pairs(
        close_df,
        corr_threshold=args.corr,
        pvalue_threshold=args.pvalue,
    )

    selected_pairs = select_top_pairs(
        pair_stats,
        n_pairs=args.top_pairs,
        unique_symbols=not args.allow_overlap,
    )

    if not selected_pairs:
        raise RuntimeError("No pair selected. Try lower corr threshold or higher p-value threshold.")

    out_df, metrics = run_long_only_cointegration_backtest(
        close_df,
        selected_pairs=selected_pairs,
        z_window=args.z_window,
        entry_z=args.entry_z,
        exit_z=args.exit_z,
        fee_bps=args.fee_bps,
    )

    save_outputs(out_df, metrics, pair_stats, selected_pairs, output_dir)

    print("Top selected pairs:")
    for p in selected_pairs:
        print(
            f"- {p.symbol_x}-{p.symbol_y} "
            f"corr={p.corr:.3f} p={p.pvalue:.6f} beta={p.beta:.3f} hl={p.half_life_bars:.1f}"
        )

    print(json.dumps(metrics, indent=2))
    print(f"Saved outputs to: {output_dir}")


if __name__ == "__main__":
    main()
