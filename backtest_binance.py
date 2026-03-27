#!/usr/bin/env python3
"""
Offline backtest on Binance CSV data for configured coins.

This script does not place real orders. It reads local historical CSV files,
generates per-coin signals from configured strategies, builds an equal-weight
long-only portfolio on positive signals, and saves performance charts.
"""

import argparse
import json
from pathlib import Path
from typing import Dict, Tuple

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from per_coin_config import COIN_STRATEGY_CONFIG, AVOID_COINS
from strategies import calculate_macd, calculate_rsi


def coin_to_symbol(coin: str) -> str:
    """Convert BTC/USD -> BTCUSDT."""
    base = coin.split("/")[0]
    return f"{base}USDT"


def load_close_series(data_dir: Path, coin: str) -> pd.Series:
    """Load close series from symbol CSV with open_time index."""
    symbol = coin_to_symbol(coin)
    file_path = data_dir / f"{symbol}_1m.csv"
    if not file_path.exists():
        return pd.Series(dtype=float)

    df = pd.read_csv(file_path, usecols=["open_time", "close"])
    df["open_time"] = pd.to_datetime(df["open_time"], utc=True, errors="coerce")
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df = df.dropna(subset=["open_time", "close"]).drop_duplicates(subset=["open_time"])
    df = df.sort_values("open_time")
    return df.set_index("open_time")["close"]


def apply_time_filter_series(raw_signal: pd.Series) -> pd.Series:
    """Apply hour-based filter from strategies.py rules."""
    hours = raw_signal.index.hour
    us_mask = (hours >= 13) & (hours <= 22)
    asia_mask = (hours >= 1) & (hours <= 8)

    out = pd.Series(0.0, index=raw_signal.index)
    out[us_mask] = raw_signal[us_mask]
    out[asia_mask] = raw_signal[asia_mask] * 0.5
    return out


def strategy_signal(close: pd.Series, strategy: str, params: list) -> pd.Series:
    """Vectorized signal series: 1 buy, -1 sell, 0 hold."""
    signal = pd.Series(0.0, index=close.index)

    if strategy == "dual_ma":
        fast, slow = params
        ma_fast = close.rolling(window=fast).mean()
        ma_slow = close.rolling(window=slow).mean()
        signal = pd.Series(np.where(ma_fast > ma_slow, 1.0, np.where(ma_fast < ma_slow, -1.0, 0.0)), index=close.index)

    elif strategy == "rsi":
        period, oversold, overbought = params
        rsi = calculate_rsi(close, period)
        signal = pd.Series(np.where(rsi < oversold, 1.0, np.where(rsi > overbought, -1.0, 0.0)), index=close.index)

    elif strategy == "macd":
        fast, slow, sig = params
        macd, signal_line = calculate_macd(close, fast, slow, sig)
        prev_macd = macd.shift(1)
        prev_sig = signal_line.shift(1)
        buy = (prev_macd <= prev_sig) & (macd > signal_line)
        sell = (prev_macd >= prev_sig) & (macd < signal_line)
        signal = pd.Series(np.where(buy, 1.0, np.where(sell, -1.0, 0.0)), index=close.index)

    signal = signal.fillna(0.0)
    return apply_time_filter_series(signal)


def max_drawdown(equity: pd.Series) -> float:
    peak = equity.cummax()
    dd = equity / peak - 1.0
    return float(dd.min())


def run_backtest(data_dir: Path, interval: str, lookback_days: int) -> Tuple[pd.DataFrame, Dict]:
    valid_coins = [c for c in COIN_STRATEGY_CONFIG.keys() if c not in AVOID_COINS]

    close_map = {}
    strat_map = {}

    for coin in valid_coins:
        close_1m = load_close_series(data_dir, coin)
        if close_1m.empty:
            continue

        if lookback_days > 0:
            cutoff = close_1m.index.max() - pd.Timedelta(days=lookback_days)
            close_1m = close_1m[close_1m.index >= cutoff]

        close = close_1m.resample(interval).last().dropna()
        if len(close) < 200:
            continue

        close_map[coin] = close
        strat_map[coin] = COIN_STRATEGY_CONFIG[coin]

    if not close_map:
        raise RuntimeError("No valid CSV data loaded for configured coins.")

    close_df = pd.concat(close_map, axis=1).sort_index().dropna(how="all")

    if close_df.shape[1] == 0:
        raise RuntimeError("No data available after alignment.")

    # Keep coins with enough data coverage, then forward-fill gaps per coin.
    coverage = close_df.notna().mean()
    keep_cols = coverage[coverage >= 0.5].index.tolist()
    close_df = close_df[keep_cols].copy()
    close_df = close_df.ffill()

    # Keep periods where at least one coin is tradable.
    close_df = close_df.dropna(how="all")
    if close_df.empty:
        raise RuntimeError("No usable data after coverage filtering.")

    signal_df = pd.DataFrame(0.0, index=close_df.index, columns=close_df.columns)

    for coin in close_df.columns:
        cfg = strat_map[coin]
        coin_close = close_df[coin].dropna()
        if coin_close.empty:
            continue
        coin_signal = strategy_signal(coin_close, cfg["strategy"], cfg["params"])
        signal_df[coin] = coin_signal.reindex(close_df.index).fillna(0.0)

    ret_df = close_df.pct_change(fill_method=None).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    long_mask = (signal_df > 0).astype(float)
    n_pos = long_mask.sum(axis=1)

    weights = long_mask.div(n_pos.replace(0, np.nan), axis=0).fillna(0.0)
    port_ret = (weights.shift(1).fillna(0.0) * ret_df).sum(axis=1)

    equity = (1.0 + port_ret).cumprod()

    btc_col = "BTC/USD"
    if btc_col in close_df.columns:
        bench_ret = close_df[btc_col].pct_change().fillna(0.0)
        bench_equity = (1.0 + bench_ret).cumprod()
    else:
        bench_equity = pd.Series(1.0, index=equity.index)

    dd_series = equity / equity.cummax() - 1.0

    periods_per_day = int(pd.Timedelta("1D") / pd.Timedelta(interval))
    annual_factor = np.sqrt(periods_per_day * 365)
    sharpe = 0.0
    if port_ret.std() > 0:
        sharpe = float(port_ret.mean() / port_ret.std() * annual_factor)

    turnover = weights.diff().abs().sum(axis=1).fillna(0.0).sum() / 2.0

    metrics = {
        "start": str(equity.index.min()),
        "end": str(equity.index.max()),
        "bars": int(len(equity)),
        "coins": int(close_df.shape[1]),
        "interval": interval,
        "total_return_pct": float((equity.iloc[-1] - 1.0) * 100),
        "benchmark_btc_return_pct": float((bench_equity.iloc[-1] - 1.0) * 100),
        "max_drawdown_pct": float(max_drawdown(equity) * 100),
        "sharpe": sharpe,
        "avg_positions": float(n_pos.mean()),
        "turnover": float(turnover),
    }

    out_df = pd.DataFrame(
        {
            "equity": equity,
            "benchmark_btc": bench_equity,
            "drawdown": dd_series,
            "positions": n_pos,
            "portfolio_return": port_ret,
        }
    )

    return out_df, metrics


def save_plots(result_df: pd.DataFrame, metrics: Dict, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    fig, axes = plt.subplots(3, 1, figsize=(14, 12), sharex=True)

    axes[0].plot(result_df.index, result_df["equity"], label="Strategy Equity", linewidth=1.6)
    axes[0].plot(result_df.index, result_df["benchmark_btc"], label="BTC Buy&Hold", linewidth=1.2, alpha=0.85)
    axes[0].set_title("Equity Curve")
    axes[0].legend(loc="upper left")
    axes[0].grid(alpha=0.25)

    axes[1].fill_between(result_df.index, result_df["drawdown"], 0, color="#d9534f", alpha=0.35)
    axes[1].set_title("Drawdown")
    axes[1].grid(alpha=0.25)

    axes[2].plot(result_df.index, result_df["positions"], color="#2a9d8f", linewidth=1.2)
    axes[2].set_title("Number of Active Positions")
    axes[2].grid(alpha=0.25)

    summary = (
        f"Return: {metrics['total_return_pct']:.2f}% | "
        f"BTC: {metrics['benchmark_btc_return_pct']:.2f}% | "
        f"MDD: {metrics['max_drawdown_pct']:.2f}% | "
        f"Sharpe: {metrics['sharpe']:.2f} | "
        f"AvgPos: {metrics['avg_positions']:.2f}"
    )
    fig.suptitle(summary, fontsize=11)
    fig.tight_layout(rect=[0, 0.02, 1, 0.97])

    chart_path = output_dir / "backtest_result.png"
    fig.savefig(chart_path, dpi=150)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline Binance CSV backtest")
    parser.add_argument("--data-dir", default="historical_data", help="CSV folder path")
    parser.add_argument("--interval", default="15min", help="Resample interval, e.g. 5min/15min/1H")
    parser.add_argument("--days", type=int, default=10, help="Lookback days, <=0 means all")
    parser.add_argument("--output-dir", default="outputs", help="Output directory")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    output_dir = Path(args.output_dir)

    result_df, metrics = run_backtest(data_dir, args.interval, args.days)
    save_plots(result_df, metrics, output_dir)

    output_dir.mkdir(parents=True, exist_ok=True)
    result_df.to_csv(output_dir / "backtest_timeseries.csv")
    with open(output_dir / "backtest_metrics.json", "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)

    print(json.dumps(metrics, indent=2))
    print(f"Saved chart: {output_dir / 'backtest_result.png'}")


if __name__ == "__main__":
    main()
