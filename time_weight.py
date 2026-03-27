"""
time_weight.py
Dynamic time weight module
Combines 90-day long-term data and 7-day short-term data to dynamically calculate optimal position weight for each hour
"""

import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta
from loguru import logger

DATA_DIR = "historical_data"
LONG_DAYS = 90      # Long-term data days
SHORT_DAYS = 7      # Short-term data days


def load_hourly_pnl(coin: str, days: int = LONG_DAYS) -> pd.Series:
    """
     
    Load 1-minute data for a coin over the past N days and calculate hourly returns.
    
    Returns:
        Series with hour (0-23) as index and return percentage as value
    
    """
    clean_coin = coin.replace('/', '').replace('-', '').replace('USD', '')
    
    # Try to match filename
    # Only keep last N days
    # Calculate hourly return
    possible_files = [
        Path(DATA_DIR) / f"{clean_coin}USDT_1m.csv",
        Path(DATA_DIR) / f"{clean_coin}_1m.csv",
    ]
    
    df = None
    for file_path in possible_files:
        if file_path.exists():
            df = pd.read_csv(file_path)
            break
    
    if df is None or df.empty:
        logger.warning(f"No data for {coin}")
        return pd.Series()
    
    df['open_time'] = pd.to_datetime(df['open_time'])
    
    # only take latest n days
    cutoff = df['open_time'].max() - timedelta(days=days)
    df = df[df['open_time'] >= cutoff]
    
    if df.empty:
        logger.warning(f"Insufficient data for {coin} (need {days} days)")
        return pd.Series()
    
    # calculate interest rate per hour
    df['hour'] = df['open_time'].dt.hour
    hourly_close = df.groupby('hour')['close'].last()
    hourly_return = hourly_close.pct_change().fillna(0)
    
    return hourly_return


def calculate_dynamic_ratio(short_ret: float, long_ret: float, short_vol: float) -> float:
    """
    Dynamically calculate short-term weight
    High short-term volatility → lower short-term weight
    Stable and profitable short-term → higher short-term weight
    
    Args:
        short_ret: Short-term average return
        long_ret: Long-term average return
        short_vol: Short-term return volatility
    
    Returns:
        Short-term weight (0-1)
    """
    # If short-term volatility is too high, reduce weight
    if short_vol > 0.05:
        return 0.2
    # If short-term is stable and profitable, increase weight
    elif short_vol < 0.02 and short_ret > 0:
        return 0.7
    # Short-term profitable but moderate volatility
    elif short_ret > 0:
        return 0.5
    #Short-term losing
    elif short_ret < 0:
        return 0.3
    else:
        return 0.4


def calculate_hourly_weight(coins: list) -> dict:
    """
    Calculate average weight for each hour
    Combine long-term (90-day) and short-term (7-day) data, dynamically calculate weights
    
    Returns: {0: 0.2, 1: 0.3, ...} hour -> weight (0-1)
    """
    all_long_returns = []
    all_short_returns = []
    
    logger.info(f"Loading hourly returns for {len(coins)} coins...")
    
    for coin in coins:
        long_ret = load_hourly_pnl(coin, days=LONG_DAYS)
        short_ret = load_hourly_pnl(coin, days=SHORT_DAYS)
        
        if not long_ret.empty:
            all_long_returns.append(long_ret)
        if not short_ret.empty:
            all_short_returns.append(short_ret)
    
    if not all_long_returns:
        logger.warning("No long-term data for any coin, using default weights")
        return {h: 0.5 for h in range(24)}
    
    # Calculate average return across all coins (by hour)
    long_avg = pd.concat(all_long_returns, axis=1).mean(axis=1)
    
    weights = {}
    
    if all_short_returns:
        short_avg = pd.concat(all_short_returns, axis=1).mean(axis=1)
        
        # Calculate short-term volatility (by hour)
        short_vol = pd.concat(all_short_returns, axis=1).std(axis=1).fillna(0.03)
        
        # Independently calculate dynamic weight for each hour
        for hour in range(24):
            short_ret = short_avg.get(hour, 0.0)
            long_ret = long_avg.get(hour, 0.0)
            vol = short_vol.get(hour, 0.03)
            
            # Calculate dynamic ratio
            ratio = calculate_dynamic_ratio(short_ret, long_ret, vol)
            
            # Combine long-term and short-term
            combined = ratio * short_ret + (1 - ratio) * long_ret
            
            # Convert return to weight (1% return = full position)
            if combined > 0:
                weight = min(1.0, combined / 0.01)
            else:
                weight = 0.0
            
            weights[hour] = weight
    else:
        # No short-term data, use only long-term
        for hour, ret in long_avg.items():
            if ret > 0:
                weights[hour] = min(1.0, ret / 0.01)
            else:
                weights[hour] = 0.0
    
    logger.info(f"Hourly weights calculated: {weights}")
    return weights


def get_dynamic_time_filter(weights: dict):
    """
    Return a dynamic time filter function
    """
    def dynamic_filter(signal: int, hour: int = None) -> float:
        if hour is None:
            hour = datetime.now().hour
        weight = weights.get(hour, 0.0)
        return signal * weight
    
    return dynamic_filter


# ============================================================
# simple test
# ============================================================
if __name__ == "__main__":
    test_coins = [
        'XPL/USD', 'PENGU/USD', 'PUMP/USD', 'STO/USD', 'VIRTUAL/USD',
        'TAO/USD', 'ZEC/USD', 'TRX/USD', 'BTC/USD', 'PAXG/USD',
        'FLOKI/USD', 'ETH/USD', 'BNB/USD', 'HBAR/USD',
        '1000CHEEMS/USD', 'WIF/USD', 'EIGEN/USD'
    ]
    
    weights = calculate_hourly_weight(test_coins)
    print("\n=== Final Weights ===")
    for hour in range(24):
        print(f"Hour {hour:2d}: {weights.get(hour, 0):.3f}")
