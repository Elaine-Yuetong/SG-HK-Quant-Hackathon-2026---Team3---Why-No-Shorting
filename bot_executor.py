"""
bot_executor.py
Trading execution layer for Roostoo API.
Integrates with:
- strategies.py (signal generation)
- per_coin_config.py (coin strategy config)
- qubo_optimizer.py (portfolio selection)
- risk_manager.py (risk controls)

Uses HMAC-SHA256 signature from Roostoo API spec.
"""

import time
import hmac
import hashlib
import requests
from typing import Dict, List, Tuple, Optional, Any
from datetime import datetime, timedelta
import json
import os

from loguru import logger
import pandas as pd
import numpy as np
# 精度缓存
_PRECISION_CACHE = {}

def _get_precision(pair: str) -> int:
    """获取币的精度，缓存结果"""
    global _PRECISION_CACHE
    if pair in _PRECISION_CACHE:
        return _PRECISION_CACHE[pair]
    
    try:
        payload = {'timestamp': _get_timestamp_ms()}
        response = requests.get(f"{ROOSTOO_BASE_URL}/v3/exchangeInfo", params=payload)
        data = response.json()
        if data.get('TradePairs') and pair in data['TradePairs']:
            precision = data['TradePairs'][pair]['AmountPrecision']
            _PRECISION_CACHE[pair] = precision
            return precision
    except Exception as e:
        logger.warning(f"Failed to get precision for {pair}: {e}")
    
    return 6  # 默认6位

# Import our modules
from config import ROOSTOO_BASE_URL, ROOSTOO_API_KEY, ROOSTOO_SECRET_KEY
from strategies import (
    get_signal, apply_time_filter, get_signal_with_regime,
    detect_market_regime, STRATEGY_FUNCTIONS
)
from per_coin_config import (
    COIN_STRATEGY_CONFIG, AVOID_COINS, get_strategy_params,
    is_valid_coin, get_all_tradable_coins
)
from risk_manager import RiskManager, calculate_position_size, calculate_volatility


# ============================================================
# API Helpers (based on Roostoo spec)
# ============================================================

def _get_timestamp_ms() -> str:
    """Return 13-digit millisecond timestamp."""
    return str(int(time.time() * 1000))


def _generate_signature(payload: Dict[str, Any], secret_key: str) -> str:
    """
    Generate HMAC-SHA256 signature as per Roostoo API spec.
    Sorted params, concatenated with '=', joined with '&'.
    """
    sorted_keys = sorted(payload.keys())
    total_params = "&".join(f"{k}={payload[k]}" for k in sorted_keys)
    signature = hmac.new(
        secret_key.encode('utf-8'),
        total_params.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    return signature


def _get_signed_headers(payload: Dict[str, Any]) -> Tuple[Dict[str, str], Dict[str, Any], str]:
    """
    Add timestamp, generate signature, return headers and total_params.
    """
    payload['timestamp'] = _get_timestamp_ms()
    sorted_keys = sorted(payload.keys())
    total_params = "&".join(f"{k}={payload[k]}" for k in sorted_keys)
    signature = _generate_signature(payload, ROOSTOO_SECRET_KEY)
    headers = {
        'RST-API-KEY': ROOSTOO_API_KEY,
        'MSG-SIGNATURE': signature
    }
    return headers, payload, total_params


# ============================================================
# Price & Balance Fetching
# ============================================================

def get_current_prices(pairs: List[str]) -> Dict[str, float]:
    """
    Get current prices for given pairs.
    pairs: list like ['BTC/USD', 'ETH/USD'] or ['BTC', 'ETH']
    Returns: dict like {'BTC/USD': 12345.67, ...}
    """
    prices = {}
    url = f"{ROOSTOO_BASE_URL}/v3/ticker"
    
    # Convert to full pair format if needed
    full_pairs = []
    for p in pairs:
        if '/' not in p:
            full_pairs.append(f"{p}/USD")
        else:
            full_pairs.append(p)
    
    # Fetch all tickers at once if possible
    payload = {'timestamp': _get_timestamp_ms()}
    try:
        response = requests.get(url, params=payload, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if data.get('Success') and data.get('Data'):
            for pair in full_pairs:
                if pair in data['Data']:
                    prices[pair] = float(data['Data'][pair]['LastPrice'])
                else:
                    logger.warning(f"Pair {pair} not found in ticker response")
        else:
            logger.error(f"Failed to get ticker: {data.get('ErrMsg', 'Unknown error')}")
            
    except Exception as e:
        logger.error(f"Error fetching prices: {e}")
    
    return prices


def get_current_portfolio() -> Tuple[Dict[str, float], float]:
    """
    Get current wallet balances.
    Returns: (holdings, cash_balance)
    holdings: dict like {'BTC': 0.5, 'ETH': 2.0} (coin symbols without /USD)
    cash_balance: USD balance (float)
    """
    url = f"{ROOSTOO_BASE_URL}/v3/balance"
    headers, payload, _ = _get_signed_headers({})
    
    try:
        response = requests.get(url, headers=headers, params=payload, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if data.get('Success'):
            wallet = data.get('SpotWallet', {})
            holdings = {}
            cash_balance = 0.0
            
            for asset, balance in wallet.items():
                free = float(balance.get('Free', 0))
                locked = float(balance.get('Lock', 0))
                total = free + locked
                
                if asset == 'USD':
                    cash_balance = total
                elif total > 0.000001:
                    holdings[asset] = total
            
            logger.info(f"Portfolio: {len(holdings)} assets, cash=${cash_balance:.2f}")
            return holdings, cash_balance
        else:
            logger.error(f"Failed to get balance: {data.get('ErrMsg', 'Unknown error')}")
            return {}, 0.0
            
    except Exception as e:
        logger.error(f"Error fetching portfolio: {e}")
        return {}, 0.0


# ============================================================
# Order Placement
# ============================================================

def place_order(
    coin: str,
    side: str,
    quantity: float,
    order_type: str = "MARKET",
    price: Optional[float] = None
) -> Optional[Dict]:
    """
    Place an order on Roostoo.
    coin: e.g., 'BTC' or 'BTC/USD'
    side: 'BUY' or 'SELL'
    quantity: amount to trade
    order_type: 'MARKET' or 'LIMIT'
    price: required for LIMIT orders
    """
    # Ensure pair format
    if '/' not in coin:
        pair = f"{coin}/USD"
    else:
        pair = coin
    
    # Round quantity to appropriate precision (from exchangeInfo)
    # For now, use a simple rounding (will be improved later)
        # getting precision and get the integer
    precision = _get_precision(pair)
    quantity = round(quantity, precision)
    if precision == 0:
        quantity = int(quantity)
    if quantity <= 0:
        logger.error(f"Invalid quantity: {quantity}")
        return None
    
    payload = {
        'pair': pair,
        'side': side.upper(),
        'type': order_type.upper(),
        'quantity': str(quantity)
    }
    if order_type.upper() == 'LIMIT' and price is not None:
        payload['price'] = str(price)
    
    headers, _, total_params = _get_signed_headers(payload)
    headers['Content-Type'] = 'application/x-www-form-urlencoded'
    
    url = f"{ROOSTOO_BASE_URL}/v3/place_order"
    
    try:
        response = requests.post(url, headers=headers, data=total_params, timeout=15)
        response.raise_for_status()
        result = response.json()
        
        if result.get('Success'):
            order_detail = result.get('OrderDetail', {})
            logger.info(f"✅ {side} {quantity} {pair} @ {order_detail.get('FilledAverPrice', 'MARKET')}")
            return result
        else:
            logger.error(f"Order failed: {result.get('ErrMsg', 'Unknown error')}")
            return None
            
    except Exception as e:
        logger.error(f"Error placing order: {e}")
        return None


# ============================================================
# Core Trading Logic
# ============================================================

class TradingExecutor:
    """
    Main trading executor that integrates all modules.
    """
    
    def __init__(self, initial_capital: float = 1_000_000):
        self.initial_capital = initial_capital
        self.risk_manager = RiskManager(initial_capital=initial_capital)
        self.price_history: Dict[str, list] = {}  # Store recent prices for volatility calc
        
    def get_signal_for_coin(self, coin: str, df: pd.DataFrame) -> Tuple[int, float]:
        """
        Get signal for a single coin using its configured strategy.
        Returns: (signal, position_multiplier)
        """
        if not is_valid_coin(coin):
            return 0, 0.0
        
        strategy, params = get_strategy_params(coin)
        if strategy is None:
            return 0, 0.0
        
        # Get base signal
        try:
            signal = get_signal(df, strategy, params)
        except Exception as e:
            logger.error(f"Error getting signal for {coin}: {e}")
            return 0, 0.0
        
        # Apply time filter (Layer 3)
        signal = apply_time_filter(signal)
        
        # Apply market regime filter (Layer 3)
        regime = detect_market_regime(df)
        if regime == 'RANGING':
            # Reduce position in ranging markets
            signal = signal * 0.5 if signal != 0 else 0
        
        # Get risk multiplier
        position_multiplier = self.risk_manager.get_position_multiplier(
            self._get_current_capital()
        )
        
        return signal, position_multiplier
    
    def _get_current_capital(self) -> float:
        """Get current total capital from portfolio"""
        logger.info("=== INSIDE _get_current_capital ===")
        holdings, cash = get_current_portfolio()
        total = cash
        prices = get_current_prices(list(holdings.keys()))
    
        # 调试
        logger.info(f"Holdings: {holdings}")
        logger.info(f"Prices keys: {list(prices.keys())}")
    
        for coin, qty in holdings.items():
            pair = f"{coin}/USD"
            if pair in prices:
                value = qty * prices[pair]
                total += value
                logger.info(f"{coin}: {qty} * {prices[pair]} = {value}")
            else:
                logger.warning(f"Price not found for {pair}")
    
        return total
    
    def execute_trade(
        self,
        coin: str,
        target_quantity: float,
        current_quantity: float,
        current_price: float
    ):
        """
        Execute trade to reach target quantity.
        """
        diff = target_quantity - current_quantity
        if abs(diff) < 0.000001:
            return
        
        if diff > 0:
            # Buy
            logger.info(f"📈 BUY {diff:.6f} {coin} @ ${current_price:.2f}")
            result = place_order(coin, 'BUY', diff)
            if result and result.get('Success'):
                self.risk_manager.record_entry(coin, current_price)
        else:
            # Sell
            logger.info(f"📉 SELL {-diff:.6f} {coin} @ ${current_price:.2f}")
            result = place_order(coin, 'SELL', -diff)
            if result and result.get('Success'):
                self.risk_manager.record_exit(coin)
    
    def rebalance(
        self,
        target_weights: Dict[str, float],
        current_holdings: Dict[str, float],
        cash_balance: float,
        price_data: Dict[str, float]
    ) -> Dict:
        """
        Execute rebalance to match target weights.
        """
        results = {
            'success': False,
            'trades': [],
            'errors': []
        }
        
        # Calculate total portfolio value
        total_value = cash_balance
        for coin, qty in current_holdings.items():
            pair = f"{coin}/USD"
            if pair in price_data:
                total_value += qty * price_data[pair]
        
        if total_value <= 0:
            results['errors'].append("Total portfolio value is zero")
            return results
        
        # Check kill switch
        current_capital = total_value
        killed, reason = self.risk_manager.check_kill_switch(current_capital)
        if killed:
            logger.warning(f"Kill switch active: {reason}")
            results['errors'].append(f"Kill switch: {reason}")
            return results
        
        # Calculate target quantities
        target_quantities = {}
        for coin, weight in target_weights.items():
            coin_symbol = coin.replace('/USD', '')
            target_value = total_value * weight
            if coin_symbol in price_data:
                target_quantities[coin_symbol] = target_value / price_data[coin_symbol]
            else:
                pair = f"{coin_symbol}/USD"
                if pair in price_data:
                    target_quantities[coin_symbol] = target_value / price_data[pair]
        
        # Execute trades
        for coin, target_qty in target_quantities.items():
            current_qty = current_holdings.get(coin, 0)
            pair = f"{coin}/USD"
            if pair in price_data:
                self.execute_trade(coin, target_qty, current_qty, price_data[pair])
                results['trades'].append({
                    'coin': coin,
                    'target': target_qty,
                    'current': current_qty,
                    'price': price_data[pair]
                })
        
        results['success'] = True
        return results


# ============================================================
# Simplified entry point for main.py
# ============================================================

def get_signal_for_coin_simple(
    coin: str,
    df: pd.DataFrame,
    risk_manager: RiskManager
) -> Tuple[int, float]:
    """
    Simplified signal function for main.py to use.
    Returns: (signal, position_size_multiplier)
    """
    if not is_valid_coin(coin):
        return 0, 0.0
    
    strategy, params = get_strategy_params(coin)
    if strategy is None:
        return 0, 0.0
    
    try:
        signal = get_signal(df, strategy, params)
    except Exception as e:
        logger.error(f"Error getting signal for {coin}: {e}")
        return 0, 0.0
    
    # Apply time filter
    signal = apply_time_filter(signal)
    
    # Get risk multiplier
    current_capital = risk_manager.initial_capital  # placeholder
    multiplier = risk_manager.get_position_multiplier(current_capital)
    
    return signal, multiplier


def get_all_signals(
    price_data: Dict[str, pd.DataFrame],
    risk_manager: RiskManager
) -> Dict[str, Tuple[int, float]]:
    """
    Get signals for all tradable coins.
    Returns: dict {coin: (signal, multiplier)}
    """
    signals = {}
    for coin in get_all_tradable_coins():
        if coin in price_data:
            signal, mult = get_signal_for_coin_simple(coin, price_data[coin], risk_manager)
            signals[coin] = (signal, mult)
    return signals