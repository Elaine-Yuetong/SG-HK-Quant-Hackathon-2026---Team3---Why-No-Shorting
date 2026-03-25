"""
strategies.py
5 Base Strategies: Dual MA, MACD, RSI, Bollinger Bands, Volume MA
Each function returns: 1 (buy), -1 (sell), 0 (hold)
"""

import pandas as pd
import numpy as np
from datetime import datetime
from typing import Tuple, Optional


# ============================================================
# Helper Functions
# ============================================================

def calculate_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Calculate RSI indicator"""
    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


def calculate_macd(
    close: pd.Series, 
    fast: int = 12, 
    slow: int = 26, 
    signal: int = 9
) -> Tuple[pd.Series, pd.Series]:
    """Calculate MACD and signal line"""
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd = ema_fast - ema_slow
    signal_line = macd.ewm(span=signal, adjust=False).mean()
    return macd, signal_line


def calculate_adx(
    high: pd.Series, 
    low: pd.Series, 
    close: pd.Series, 
    period: int = 14
) -> pd.Series:
    """Calculate ADX for trend strength"""
    # True Range
    tr1 = high - low
    tr2 = abs(high - close.shift())
    tr3 = abs(low - close.shift())
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=period).mean()
    
    # Directional Movement
    up_move = high - high.shift()
    down_move = low.shift() - low
    
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0)
    
    plus_di = 100 * (pd.Series(plus_dm).rolling(window=period).mean() / atr)
    minus_di = 100 * (pd.Series(minus_dm).rolling(window=period).mean() / atr)
    
    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
    adx = dx.rolling(window=period).mean()
    
    return adx


# ============================================================
# Strategy 1: Dual Moving Average Crossover
# ============================================================

def dual_ma_signal(
    df: pd.DataFrame, 
    fast: int = 10, 
    slow: int = 20
) -> int:
    """
    Dual Moving Average Crossover Strategy with adaptive periods
    """
    if len(df) < slow:
        return 0
    
    close = df['close']
    
    # calculate volatility (recent 20 Kline)
    returns = close.pct_change().dropna()
    if len(returns) < 20:
        vol = 0.01  # default volatility
    else:
        vol = returns.tail(20).std()
    
    # adjust periotic according to volitility
    if vol > 0.02:      # high（>2%）
        fast_adj = fast * 2
        slow_adj = slow * 2
    elif vol < 0.005:   # low（<0.5%）
        fast_adj = max(5, fast // 2)
        slow_adj = max(10, slow // 2)
    else:               # normal
        fast_adj = fast
        slow_adj = slow
    
    # calculate moving average
    ma_fast = close.rolling(window=fast_adj).mean()
    ma_slow = close.rolling(window=slow_adj).mean()
    
    if pd.isna(ma_fast.iloc[-1]) or pd.isna(ma_slow.iloc[-1]):
        return 0
    
    if ma_fast.iloc[-1] > ma_slow.iloc[-1]:
        return 1
    elif ma_fast.iloc[-1] < ma_slow.iloc[-1]:
        return -1
    else:
        return 0

# ============================================================
# Strategy 2: RSI Oversold/Overbought
# ============================================================

def rsi_signal(
    df: pd.DataFrame, 
    period: int = 14, 
    oversold: int = 30, 
    overbought: int = 70
) -> int:
    """
    RSI Strategy
    
    Returns:
        1: Buy (RSI < oversold)
        -1: Sell (RSI > overbought)
        0: Hold (neutral zone)
    """
    if len(df) < period + 1:
        return 0
    
    close = df['close']
    rsi = calculate_rsi(close, period)
    
    if pd.isna(rsi.iloc[-1]):
        return 0
    
    if rsi.iloc[-1] < oversold:
        return 1
    elif rsi.iloc[-1] > overbought:
        return -1
    else:
        return 0


# ============================================================
# Strategy 3: MACD Crossover
# ============================================================

def macd_signal(
    df: pd.DataFrame, 
    fast: int = 12, 
    slow: int = 26, 
    signal_period: int = 9
) -> int:
    """
    MACD Strategy
    
    Returns:
        1: Buy (MACD crosses above signal line)
        -1: Sell (MACD crosses below signal line)
        0: Hold (no crossover)
    """
    if len(df) < slow + signal_period:
        return 0
    
    close = df['close']
    macd, signal_line = calculate_macd(close, fast, slow, signal_period)
    
    if pd.isna(macd.iloc[-1]) or pd.isna(signal_line.iloc[-1]):
        return 0
    if len(macd) < 2:
        return 0
    
    # Current and previous values
    curr_macd = macd.iloc[-1]
    prev_macd = macd.iloc[-2]
    curr_signal = signal_line.iloc[-1]
    prev_signal = signal_line.iloc[-2]
    
    # Buy signal: MACD crosses above signal line
    if prev_macd <= prev_signal and curr_macd > curr_signal:
        return 1
    # Sell signal: MACD crosses below signal line
    elif prev_macd >= prev_signal and curr_macd < curr_signal:
        return -1
    else:
        return 0


# ============================================================
# Strategy 4: Bollinger Bands
# ============================================================

def bollinger_signal(
    df: pd.DataFrame, 
    period: int = 20, 
    std_dev: float = 2.0
) -> int:
    """
    Bollinger Bands Strategy
    
    Returns:
        1: Buy (price touches lower band)
        -1: Sell (price touches upper band)
        0: Hold (inside bands)
    """
    if len(df) < period:
        return 0
    
    close = df['close']
    middle = close.rolling(window=period).mean()
    std = close.rolling(window=period).std()
    upper = middle + std_dev * std
    lower = middle - std_dev * std
    
    if pd.isna(close.iloc[-1]) or pd.isna(lower.iloc[-1]) or pd.isna(upper.iloc[-1]):
        return 0
    
    curr_close = close.iloc[-1]
    
    if curr_close <= lower.iloc[-1]:
        return 1
    elif curr_close >= upper.iloc[-1]:
        return -1
    else:
        return 0


# ============================================================
# Strategy 5: Volume-Confirmed Moving Average
# ============================================================

def volume_ma_signal(
    df: pd.DataFrame, 
    ma_period: int = 20, 
    volume_multiplier: float = 1.5
) -> int:
    """
    Volume-Confirmed Moving Average Strategy
    
    Returns:
        1: Buy (price > MA AND volume > volume_multiplier * avg volume)
        -1: Sell (price < MA AND volume > volume_multiplier * avg volume)
        0: Hold (no volume confirmation)
    """
    if len(df) < ma_period:
        return 0
    
    close = df['close']
    volume = df['volume']
    
    ma = close.rolling(window=ma_period).mean()
    vol_ma = volume.rolling(window=ma_period).mean()
    
    if pd.isna(close.iloc[-1]) or pd.isna(ma.iloc[-1]) or pd.isna(vol_ma.iloc[-1]):
        return 0
    
    curr_close = close.iloc[-1]
    curr_volume = volume.iloc[-1]
    
    # Buy signal: price above MA with high volume
    if curr_close > ma.iloc[-1] and curr_volume > vol_ma.iloc[-1] * volume_multiplier:
        return 1
    # Sell signal: price below MA with high volume
    elif curr_close < ma.iloc[-1] and curr_volume > vol_ma.iloc[-1] * volume_multiplier:
        return -1
    else:
        return 0


# ============================================================
# Strategy Dispatcher
# ============================================================

STRATEGY_FUNCTIONS = {
    'dual_ma': dual_ma_signal,
    'macd': macd_signal,
    'rsi': rsi_signal,
    'bollinger': bollinger_signal,
    'volume_ma': volume_ma_signal,
}


def get_signal(
    df: pd.DataFrame, 
    strategy_name: str, 
    params: list
) -> int:
    """
    Generic function to get signal from any strategy
    
    Args:
        df: DataFrame with OHLCV data
        strategy_name: 'dual_ma', 'macd', 'rsi', 'bollinger', 'volume_ma'
        params: List of parameters for the strategy
    
    Returns:
        1: Buy, -1: Sell, 0: Hold
    """
    if strategy_name not in STRATEGY_FUNCTIONS:
        raise ValueError(f"Unknown strategy: {strategy_name}")
    
    strategy_func = STRATEGY_FUNCTIONS[strategy_name]
    
    # Call with appropriate number of arguments
    if strategy_name == 'dual_ma':
        return strategy_func(df, params[0], params[1])
    elif strategy_name == 'macd':
        return strategy_func(df, params[0], params[1], params[2])
    elif strategy_name == 'rsi':
        return strategy_func(df, params[0], params[1], params[2])
    elif strategy_name == 'bollinger':
        return strategy_func(df, params[0], params[1])
    elif strategy_name == 'volume_ma':
        return strategy_func(df, params[0], params[1])
    else:
        return 0




# ============================================================
# Dynamic Time Filter (Layer 3) - 动态权重
# ============================================================

from time_weight import get_dynamic_time_filter

# 全局动态过滤器（需要在 main.py 初始化时设置）
_dynamic_filter = None

def set_dynamic_filter(weights: dict):
    global _dynamic_filter
    _dynamic_filter = get_dynamic_time_filter(weights)

# ============================================================
# Time Filter (Layer 3) - 静态版本（fallback）
# ============================================================

def apply_time_filter(signal: int, hour: Optional[int] = None) -> float:
    if _dynamic_filter is not None:
        return _dynamic_filter(signal, hour)
    
    # fallback: 原来的静态逻辑
    if hour is None:
        hour = datetime.now().hour
    
    if 13 <= hour <= 22:
        return float(signal)
    elif 1 <= hour <= 8:
        return signal * 0.5
    else:
        return 0.0



# ============================================================
# Market Regime Detection (for adaptive filtering)
# ============================================================

def detect_market_regime(
    df: pd.DataFrame, 
    adx_period: int = 14, 
    adx_threshold: int = 25
) -> str:
    """
    Detect market regime using ADX
    
    Returns:
        'TRENDING': ADX > threshold (strong trend)
        'RANGING': ADX <= threshold (sideways)
        'UNKNOWN': insufficient data
    """
    if len(df) < adx_period + 10:
        return 'UNKNOWN'
    
    adx = calculate_adx(df['high'], df['low'], df['close'], adx_period)
    
    if pd.isna(adx.iloc[-1]):
        return 'UNKNOWN'
    
    if adx.iloc[-1] > adx_threshold:
        return 'TRENDING'
    else:
        return 'RANGING'


def get_signal_with_regime(
    df: pd.DataFrame,
    strategy_name: str,
    params: list,
    adx_threshold: int = 25
) -> int:
    """
    Get signal with market regime awareness
    - Trending market: use base signal
    - Ranging market: reduce signal (wait for clearer signals)
    """
    # Get base signal
    signal = get_signal(df, strategy_name, params)
    
    if signal == 0:
        return 0
    
    # Detect regime
    regime = detect_market_regime(df, adx_period=14, adx_threshold=adx_threshold)
    
    if regime == 'RANGING':
        # In ranging markets, reduce position size by half
        if signal == 1:
            return 0.5
        elif signal == -1:
            return -0.5
        return 0
    
    return signal
