#!/usr/bin/env python3
"""
download_history.py
STANDALONE PROGRAM — run independently to download Binance
kline data for every Roostoo-listed token that exists on
Binance spot.

Usage:
    python download_history.py
    python download_history.py --interval 5m --days 7
    python download_history.py --pairs BTC/USD ETH/USD
"""

import os
import sys
import time
import argparse
from datetime import datetime, timedelta, timezone
from typing import Dict, List

import requests
import pandas as pd
from loguru import logger

# ── configure loguru for this standalone script ──
logger.remove()
logger.add(
    sys.stderr,
    level="INFO",
    format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> "
           "[<cyan>downloader</cyan>] "
           "<level>{level}</level>: {message}",
)
logger.add(
    "logs/download_{time:YYYY-MM-DD}.log",
    rotation="1 day",
    retention="30 days",
    level="DEBUG",
)

from config import (
    BINANCE_REST_URL,
    KLINE_INTERVAL,
    KLINE_LIMIT_PER_REQUEST,
    HISTORY_DAYS,
    DATA_DIR,
)
from roostoo_client import RoostooClient
from binance_symbols import validate_pairs


# ──────────────────────────────────────────────
# Kline columns
# ──────────────────────────────────────────────
KLINE_COLUMNS = [
    "open_time", "open", "high", "low", "close", "volume",
    "close_time", "quote_volume", "num_trades",
    "taker_buy_base_vol", "taker_buy_quote_vol", "ignore",
]


def fetch_klines(
    symbol: str,
    interval: str,
    start_ms: int,
    end_ms: int,
    limit: int = KLINE_LIMIT_PER_REQUEST,
) -> list:
    """Single paginated request to Binance GET /api/v3/klines."""
    url = f"{BINANCE_REST_URL}/api/v3/klines"
    params = {
        "symbol": symbol,
        "interval": interval,
        "startTime": start_ms,
        "endTime": end_ms,
        "limit": limit,
    }
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


def download_symbol(
    symbol: str,
    interval: str = KLINE_INTERVAL,
    days: int = HISTORY_DAYS,
) -> pd.DataFrame:
    """
    Paginate through Binance klines for `symbol` covering the
    last `days` days at the given `interval`.
    """
    now = datetime.now(timezone.utc)
    start_dt = now - timedelta(days=days)
    start_ms = int(start_dt.timestamp() * 1000)
    end_ms = int(now.timestamp() * 1000)

    logger.info(
        "Downloading {} | interval={} | {} → {}",
        symbol, interval,
        start_dt.strftime("%Y-%m-%d %H:%M"),
        now.strftime("%Y-%m-%d %H:%M"),
    )

    all_candles: list = []
    current_start = start_ms
    request_count = 0

    while current_start < end_ms:
        try:
            batch = fetch_klines(symbol, interval, current_start, end_ms)
        except requests.exceptions.HTTPError as e:
            logger.error("HTTP error for {}: {}", symbol, e)
            break
        except requests.exceptions.RequestException as e:
            logger.error("Request error for {}: {}", symbol, e)
            break

        if not batch:
            break

        all_candles.extend(batch)
        current_start = batch[-1][0] + 1  # 1ms after last open_time
        request_count += 1

        if request_count % 50 == 0:
            logger.debug(
                "  {} — {} requests, {} candles so far",
                symbol, request_count, len(all_candles),
            )

        # Binance weight limit: ~1200/min for /klines (weight=2 each)
        # 0.2s sleep → ~300 req/min → 600 weight/min — safe margin
        time.sleep(0.2)

    if not all_candles:
        logger.warning("No kline data returned for {}", symbol)
        return pd.DataFrame(columns=[c for c in KLINE_COLUMNS if c != "ignore"])

    df = pd.DataFrame(all_candles, columns=KLINE_COLUMNS)

    # Type conversions
    numeric_cols = [
        "open", "high", "low", "close", "volume",
        "quote_volume", "taker_buy_base_vol", "taker_buy_quote_vol",
    ]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df["close_time"] = pd.to_datetime(df["close_time"], unit="ms", utc=True)
    df.drop(columns=["ignore"], inplace=True)
    df.drop_duplicates(subset=["open_time"], inplace=True)
    df.sort_values("open_time", inplace=True)
    df.reset_index(drop=True, inplace=True)

    logger.info(
        "  {} → {} candles | {} → {}",
        symbol, len(df),
        df["open_time"].iloc[0].strftime("%Y-%m-%d %H:%M"),
        df["open_time"].iloc[-1].strftime("%Y-%m-%d %H:%M"),
    )
    return df


def save_csv(df: pd.DataFrame, symbol: str, interval: str) -> str:
    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(DATA_DIR, f"{symbol}_{interval}.csv")
    df.to_csv(path, index=False)
    logger.info("Saved {} ({} rows)", path, len(df))
    return path


def run(
    pairs: List[str] = None,
    interval: str = KLINE_INTERVAL,
    days: int = HISTORY_DAYS,
):
    """
    Main download pipeline:
      1. Fetch listed pairs from Roostoo
      2. Validate against Binance spot
      3. Download & save klines for each valid symbol
    """
    # Step 1: get pairs from Roostoo (or use provided list)
    if pairs is None:
        client = RoostooClient()
        pairs = client.get_listed_pairs()

    logger.info("Roostoo returned {} pairs", len(pairs))

    # Step 2: validate against Binance
    valid_map, skipped = validate_pairs(pairs)

    if not valid_map:
        logger.error("No valid Binance symbols found. Exiting.")
        return {}

    # Step 3: download each
    results: Dict[str, str] = {}  # binance_symbol → csv_path
    total = len(valid_map)
    for idx, (roostoo_pair, binance_sym) in enumerate(valid_map.items(), 1):
        logger.info(
            "━━━ [{}/{}] {} → {} ━━━",
            idx, total, roostoo_pair, binance_sym,
        )
        try:
            df = download_symbol(binance_sym, interval=interval, days=days)
            if not df.empty:
                path = save_csv(df, binance_sym, interval)
                results[binance_sym] = path
        except Exception as e:
            logger.exception("Failed to download {}: {}", binance_sym, e)

    # Summary
    logger.info("━━━ DOWNLOAD COMPLETE ━━━")
    logger.info("  Downloaded: {}/{}", len(results), total)
    logger.info("  Skipped (no Binance match): {}", len(skipped))
    for pair in skipped:
        logger.info("    ✗ {}", pair)

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Download Binance kline history for Roostoo-listed tokens."
    )
    parser.add_argument(
        "--interval", default=KLINE_INTERVAL,
        help=f"Kline interval (default: {KLINE_INTERVAL})",
    )
    parser.add_argument(
        "--days", type=int, default=HISTORY_DAYS,
        help=f"Number of days of history (default: {HISTORY_DAYS})",
    )
    parser.add_argument(
        "--pairs", nargs="+", default=None,
        help="Specific Roostoo pairs to download (e.g. BTC/USD ETH/USD). "
             "If omitted, fetches all listed pairs from Roostoo.",
    )
    args = parser.parse_args()
    run(pairs=args.pairs, interval=args.interval, days=args.days)


if __name__ == "__main__":
    main()