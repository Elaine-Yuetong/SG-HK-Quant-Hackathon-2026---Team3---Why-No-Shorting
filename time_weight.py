"""
time_weight.py
动态时间权重模块
结合90天长期数据和7天短期数据，动态计算每个小时的最佳仓位权重
"""

import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta
from loguru import logger

DATA_DIR = "historical_data"
LONG_DAYS = 90      # 长期数据天数
SHORT_DAYS = 7      # 短期数据天数


def load_hourly_pnl(coin: str, days: int = LONG_DAYS) -> pd.Series:
    """
    加载某个币过去N天的1分钟数据，计算每小时收益率
    返回: Series, index=小时(0-23), value=收益率
    """
    clean_coin = coin.replace('/', '').replace('-', '').replace('USD', '')
    
    # 尝试匹配文件名
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
    
    # 只取最近N天
    cutoff = df['open_time'].max() - timedelta(days=days)
    df = df[df['open_time'] >= cutoff]
    
    if df.empty:
        logger.warning(f"Insufficient data for {coin} (need {days} days)")
        return pd.Series()
    
    # 计算每小时收益率
    df['hour'] = df['open_time'].dt.hour
    hourly_close = df.groupby('hour')['close'].last()
    hourly_return = hourly_close.pct_change().fillna(0)
    
    return hourly_return


def calculate_dynamic_ratio(short_ret: float, long_ret: float, short_vol: float) -> float:
    """
    动态计算短期权重
    短期波动大 → 降低短期权重
    短期表现稳定且好 → 提高短期权重
    
    Args:
        short_ret: 短期平均收益率
        long_ret: 长期平均收益率
        short_vol: 短期收益率波动率
    
    Returns:
        短期权重 (0-1)
    """
    # 如果短期波动太大，降低权重
    if short_vol > 0.05:
        return 0.2
    # 如果短期稳定且赚钱，提高权重
    elif short_vol < 0.02 and short_ret > 0:
        return 0.7
    # 短期赚钱但波动中等
    elif short_ret > 0:
        return 0.5
    # 短期亏钱
    elif short_ret < 0:
        return 0.3
    else:
        return 0.4


def calculate_hourly_weight(coins: list) -> dict:
    """
    计算每个小时的平均权重
    结合长期(90天)和短期(7天)数据，动态计算权重
    
    返回: {0: 0.2, 1: 0.3, ...} 小时 -> 权重 (0-1)
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
    
    # 计算所有币的平均收益率（按小时）
    long_avg = pd.concat(all_long_returns, axis=1).mean(axis=1)
    
    weights = {}
    
    if all_short_returns:
        short_avg = pd.concat(all_short_returns, axis=1).mean(axis=1)
        
        # 计算短期波动率（按小时）
        short_vol = pd.concat(all_short_returns, axis=1).std(axis=1).fillna(0.03)
        
        # 每个小时独立计算动态权重
        for hour in range(24):
            short_ret = short_avg.get(hour, 0.0)
            long_ret = long_avg.get(hour, 0.0)
            vol = short_vol.get(hour, 0.03)
            
            # 计算动态比例
            ratio = calculate_dynamic_ratio(short_ret, long_ret, vol)
            
            # 结合长期和短期
            combined = ratio * short_ret + (1 - ratio) * long_ret
            
            # 将收益率转换为权重 (1%收益 = 满仓)
            if combined > 0:
                weight = min(1.0, combined / 0.01)
            else:
                weight = 0.0
            
            weights[hour] = weight
    else:
        # 没有短期数据，只用长期
        for hour, ret in long_avg.items():
            if ret > 0:
                weights[hour] = min(1.0, ret / 0.01)
            else:
                weights[hour] = 0.0
    
    logger.info(f"Hourly weights calculated: {weights}")
    return weights


def get_dynamic_time_filter(weights: dict):
    """
    返回一个动态时间过滤函数
    """
    def dynamic_filter(signal: int, hour: int = None) -> float:
        if hour is None:
            hour = datetime.now().hour
        weight = weights.get(hour, 0.0)
        return signal * weight
    
    return dynamic_filter


# ============================================================
# 简单测试
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