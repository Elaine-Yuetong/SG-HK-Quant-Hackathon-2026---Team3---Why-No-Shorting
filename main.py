"""
main.py
Main trading bot loop. Integrates all modules:
- strategies.py (signal generation)
- per_coin_config.py (coin strategy config)
- qubo_optimizer.py (QUBO portfolio optimization)
- risk_manager.py (risk controls)
- bot_executor.py (execution layer)

Runs on a loop, fetches data, generates signals, optimizes portfolio, executes trades.
"""

import time
import json
import os
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import pandas as pd
import numpy as np
from pathlib import Path

from loguru import logger
# At top of main.py
import threading
from dashboard import start_dashboard

# Import our modules
from strategies import (
    get_signal, apply_time_filter, get_signal_with_regime,
    detect_market_regime, calculate_rsi, calculate_macd, calculate_adx
)
from per_coin_config import (
    COIN_STRATEGY_CONFIG, AVOID_COINS, get_strategy_params,
    is_valid_coin, get_all_tradable_coins, CANDIDATE_COINS,
    TARGET_N_COINS, TARGET_CASH, get_expected_return
)
from qubo_optimizer import (
    QUBOPortfolioOptimizer, run_qubo_optimization, simple_portfolio_selection
)
from risk_manager import RiskManager, calculate_position_size, calculate_volatility
from bot_executor import (
    get_current_prices, get_current_portfolio, place_order,
    TradingExecutor, get_signal_for_coin_simple, get_all_signals
)

# ============================================================
# Configuration
# ============================================================

REBALANCE_INTERVAL_SECONDS = 3600  # Rebalance every hour
MIN_DATA_POINTS = 50               # Minimum data points for strategy
STATE_FILE = "state.json"          # File to save state for recovery
DATA_DIR = "historical_data"       # Directory with historical data
HISTORY_DAYS = 30                  # Days of data to load

# Risk parameters
INITIAL_CAPITAL = 50000        # Starting capital
MAX_POSITION_PCT = 0.20            # Max 20% per coin
MIN_POSITION_PCT = 0.05            # Min 5% per coin


# ============================================================
# State Management
# ============================================================

class StateManager:
    """Save and load bot state for recovery after crashes."""
    
    def __init__(self, state_file: str = STATE_FILE):
        self.state_file = state_file
        self.state = {
            'last_run': None,
            'portfolio': {},
            'cash': 0,
            'last_prices': {},
            'last_signals': {},
            'iteration_count': 0,
            'total_trades': 0
        }
        self._load()
    
    def _load(self):
        """Load state from file if exists."""
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, 'r') as f:
                    loaded = json.load(f)
                    self.state.update(loaded)
                    logger.info(f"Loaded state from {self.state_file}")
                    logger.info(f"  Last run: {self.state.get('last_run')}")
                    logger.info(f"  Iteration: {self.state.get('iteration_count', 0)}")
            except Exception as e:
                logger.warning(f"Failed to load state: {e}")
    
    def save(self):
        """Save current state to file."""
        self.state['last_save'] = datetime.now().isoformat()
        try:
            with open(self.state_file, 'w') as f:
                json.dump(self.state, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Failed to save state: {e}")
    
    def update_portfolio(self, holdings: Dict[str, float], cash: float, prices: Dict[str, float]):
        """Update portfolio state."""
        self.state['portfolio'] = holdings
        self.state['cash'] = cash
        self.state['last_prices'] = prices
        self.state['last_update'] = datetime.now().isoformat()
    
    def update_signals(self, signals: Dict[str, Tuple[int, float]]):
        """Update signals state."""
        # Convert tuple to list for JSON serialization
        serializable = {}
        for coin, (signal, mult) in signals.items():
            serializable[coin] = [signal, mult]
        self.state['last_signals'] = serializable
    
    def increment_iteration(self):
        self.state['iteration_count'] = self.state.get('iteration_count', 0) + 1
        self.state['last_run'] = datetime.now().isoformat()
    
    def increment_trades(self, n: int = 1):
        self.state['total_trades'] = self.state.get('total_trades', 0) + n


# ============================================================
# Data Loading
# ============================================================

def load_coin_data(coin: str, lookback_days: int = HISTORY_DAYS) -> Optional[pd.DataFrame]:
    """
    Load historical data for a coin from CSV.
    """
    # Coin may be like 'BTCUSDT' from Binance or 'BTC' from config
    clean_coin = coin.replace('/', '').replace('-', '').replace('USD', '')
    
    # Try different filename patterns
    possible_files = [
        Path(DATA_DIR) / f"{clean_coin}_1m.csv",
        Path(DATA_DIR) / f"{clean_coin}USDT_1m.csv",
        Path(DATA_DIR) / f"{clean_coin}_1m.csv",
        Path(DATA_DIR) / f"{coin}_1m.csv",
    ]
    
    for file_path in possible_files:
        if file_path.exists():
            try:
                df = pd.read_csv(file_path)
                df['open_time'] = pd.to_datetime(df['open_time'])
                # Keep only last lookback_days
                cutoff = df['open_time'].max() - timedelta(days=lookback_days)
                df = df[df['open_time'] >= cutoff]
                if len(df) >= MIN_DATA_POINTS:
                    logger.debug(f"Loaded {clean_coin}: {len(df)} rows")
                    return df
            except Exception as e:
                logger.warning(f"Failed to load {file_path}: {e}")
    
    logger.warning(f"No data found for {coin}")
    return None


def load_all_coin_data(coins: List[str], lookback_days: int = HISTORY_DAYS) -> Dict[str, pd.DataFrame]:
    """
    Load historical data for all coins.
    """
    data = {}
    for coin in coins:
        df = load_coin_data(coin, lookback_days)
        if df is not None:
            data[coin] = df
    logger.info(f"Loaded data for {len(data)}/{len(coins)} coins")
    return data


# ============================================================
# Signal Generation
# ============================================================

def generate_signals_for_coins(
    data: Dict[str, pd.DataFrame],
    risk_manager: RiskManager
) -> Dict[str, Tuple[int, float]]:
    """
    Generate trading signals for all coins with data.
    Returns: {coin: (signal, position_multiplier)}
    """
    signals = {}
    
    for coin, df in data.items():
        if not is_valid_coin(coin):
            continue
        
        # Get signal using bot_executor's function
        signal, multiplier = get_signal_for_coin_simple(coin, df, risk_manager)
        
        if signal != 0:
            logger.debug(f"{coin}: signal={signal}, multiplier={multiplier}")
        
        signals[coin] = (signal, multiplier)
    
    return signals


def aggregate_signals_to_targets(
    signals: Dict[str, Tuple[int, float]],
    current_prices: Dict[str, float],
    total_capital: float
) -> Dict[str, float]:
    # Get all coins with BUY signals AND get their signal strength
    buy_coins_with_strength = []
    total_strength = 0.0
    
    for coin, (signal, multiplier) in signals.items():
        # signal 现在可能是 0.094（经过时间过滤后的值）
        if signal > 0 and multiplier > 0:
            strength = signal * multiplier  # 信号强度
            buy_coins_with_strength.append((coin, strength))
            total_strength += strength
    
    if not buy_coins_with_strength:
        logger.info("No BUY signals, holding cash")
        return {}
    
    # 按信号强度分配权重
    targets = {}
    for coin, strength in buy_coins_with_strength:
        weight = (1 - TARGET_CASH) * (strength / total_strength)
        # Cap individual weight
        weight = min(weight, MAX_POSITION_PCT)
        weight = max(weight, MIN_POSITION_PCT)
        
        if coin in current_prices:
            targets[coin] = weight
    
    # Add cash
    targets['cash'] = TARGET_CASH
    
    # Normalize weights
    total_weight = sum(targets.values())
    if total_weight > 0:
        for coin in targets:
            targets[coin] = targets[coin] / total_weight
    
    return targets


# ============================================================
# QUBO Portfolio Optimization
# ============================================================

def optimize_portfolio_with_qubo(
    candidates: List[str],
    price_data: pd.DataFrame,
    expected_returns: Dict[str, float],
    target_coins: int = TARGET_N_COINS
) -> List[str]:
    """
    Use QUBO to select optimal coin combination.
    """
    if len(candidates) <= target_coins:
        return candidates
    
    try:
        selected, metrics = run_qubo_optimization(
            candidate_coins=candidates,
            expected_returns=expected_returns,
            price_data=price_data,
            target_coins=target_coins,
            risk_aversion=1.3
        )
        logger.info(f"QUBO selected {len(selected)} coins: {selected}")
        logger.info(f"  Expected return: {metrics.get('expected_return', 0):.2f}%")
        logger.info(f"  Diversification: {metrics.get('diversification', 0):.2f}")
        return selected
    except Exception as e:
        logger.error(f"QUBO optimization failed: {e}, using greedy fallback")
        return simple_portfolio_selection(candidates, expected_returns, target_coins)


# ============================================================
# Main Bot Loop
# ============================================================

class TradingBot:
    """Main trading bot class."""
    
    def __init__(self):
        self.risk_manager = RiskManager(initial_capital=INITIAL_CAPITAL)
        self.executor = TradingExecutor(initial_capital=INITIAL_CAPITAL)
        self.state = StateManager()
        self.iteration = 0
        
        # Track portfolio value over time
        self.portfolio_history = []

        # ========== 动态时间权重初始化 ==========
        from time_weight import calculate_hourly_weight
        from strategies import set_dynamic_filter
        try:
            logger.info("Calculating dynamic time weights...")
            weights = calculate_hourly_weight(get_all_tradable_coins())
            set_dynamic_filter(weights)
            logger.info("✅ Dynamic time filter enabled")
        except Exception as e:
            logger.warning(f"⚠️ Failed to set dynamic filter: {e}, using static fallback")
        # =========================================

        # ========== 添加这段 ==========
        # Start dashboard in background thread
        self._start_dashboard()
        # ============================
        
        logger.info("="*60)
        logger.info("🚀 Trading Bot Initialized")
        logger.info(f"  Initial Capital: ${INITIAL_CAPITAL:,.2f}")
        logger.info(f"  Rebalance Interval: {REBALANCE_INTERVAL_SECONDS/3600:.1f} hours")
        logger.info(f"  Tradable Coins: {len(get_all_tradable_coins())}")
        logger.info("="*60)
    
    def run_once(self) -> bool:
        """
        Run one trading cycle.
        Returns: True if successful, False otherwise.
        """
        self.iteration += 1
        self.state.increment_iteration()
        
        cycle_start = time.time()
        logger.info(f"\n{'='*60}")
        logger.info(f"🔄 Trading Cycle #{self.iteration}")
        logger.info(f"  Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"{'='*60}")
        
        try:
            # Step 1: Check kill switch
            current_capital = self._get_current_capital()
            killed, reason = self.risk_manager.check_kill_switch(current_capital)
            if killed:
                logger.warning(f"🛑 Kill switch active: {reason}")
                logger.info("Waiting 1 hour before retry...")
                time.sleep(3600)
                return False
            
            # Step 2: Get current portfolio
            holdings, cash = get_current_portfolio()
            logger.info(f"💰 Current portfolio: {len(holdings)} assets, cash=${cash:,.2f}")
            
            
            # Step 3: Get current prices
            all_coins = list(holdings.keys()) + get_all_tradable_coins()
            prices = get_current_prices(all_coins)
            logger.info(f"📊 Fetched prices for {len(prices)} coins")

            #addddddddddd
            logger.info(f"Holdings: {holdings}")
            logger.info(f"Prices sample: {list(prices.keys())[:5]}")
            
            # Step 4: Load historical data for tradable coins
            tradable_coins = get_all_tradable_coins()
            historical_data = load_all_coin_data(tradable_coins, HISTORY_DAYS)
            
            # Step 5: Generate signals
            signals = generate_signals_for_coins(historical_data, self.risk_manager)
            self.state.update_signals(signals)
            
            # Count buy signals
            buy_signals = sum(1 for s, m in signals.values() if s > 0 and m > 0)
            logger.info(f"📈 Signals: {buy_signals} BUY, {len(signals) - buy_signals} HOLD/SELL")
            
            # Step 6: Convert signals to target weights
            total_value = cash
            for coin, qty in holdings.items():
                pair = f"{coin}/USD"
                if pair in prices:
                    total_value += qty * prices[pair]
            
            targets = aggregate_signals_to_targets(signals, prices, total_value)
            
            # Step 7: Apply QUBO optimization to select coins
            if len([c for c in targets.keys() if c != 'cash']) > TARGET_N_COINS:
                # Prepare expected returns from signals
                expected_returns = {}
                for coin, (signal, mult) in signals.items():
                    if signal > 0:
                        expected_returns[coin] = get_expected_return(coin) * mult
                
                # Get price data for correlation
                price_df = self._build_price_dataframe(historical_data)
                
                # Run QUBO
                selected = optimize_portfolio_with_qubo(
                    list(expected_returns.keys()),
                    price_df,
                    expected_returns,
                    TARGET_N_COINS
                )
                
                # Filter targets to only selected coins
                targets = {c: w for c, w in targets.items() if c == 'cash' or c in selected}
            
            # Step 8: Execute rebalance
            if targets:
                logger.info(f"🎯 Target weights: {targets}")
                result = self.executor.rebalance(targets, holdings, cash, prices)
                if result.get('success'):
                    self.state.increment_trades(len(result.get('trades', [])))
                    logger.info(f"✅ Rebalance complete: {len(result.get('trades', []))} trades")
            else:
                logger.info("No target weights, holding cash")
            
            # Step 9: Save state
            self.state.update_portfolio(holdings, cash, prices)
            self.state.save()
            
            # Step 10: Record portfolio value
            total_value = self._get_current_capital()
            self.portfolio_history.append({
                'timestamp': datetime.now(),
                'value': total_value,
                'iteration': self.iteration
            })
            
            cycle_time = time.time() - cycle_start
            logger.info(f"✅ Cycle completed in {cycle_time:.1f}s")
            logger.info(f"  Current capital: ${total_value:,.2f}")
            logger.info(f"  Return: {(total_value - INITIAL_CAPITAL)/INITIAL_CAPITAL*100:+.2f}%")
            
            return True
            
        except Exception as e:
            logger.exception(f"❌ Cycle failed: {e}")
            return False
    
    def _get_current_capital(self) -> float:
        """Get current total capital."""
        holdings, cash = get_current_portfolio()
        prices = get_current_prices(list(holdings.keys()))
        total = cash
        for coin, qty in holdings.items():
            pair = f"{coin}/USD"
            if pair in prices:
                total += qty * prices[pair]
        return total
    
    def _build_price_dataframe(self, historical_data: Dict[str, pd.DataFrame]) -> pd.DataFrame:
        """Build price DataFrame for correlation calculation."""
        prices = {}
        for coin, df in historical_data.items():
            if len(df) > 0:
                # Use last close as reference
                prices[coin] = df['close'].values[-min(100, len(df)):]
        
        if prices:
            min_len = min(len(v) for v in prices.values())
            for coin in prices:
                prices[coin] = prices[coin][-min_len:]
            return pd.DataFrame(prices)
        return pd.DataFrame()
    
    def run(self):
        """Main loop."""
        logger.info("🏁 Starting main trading loop")
        
        while True:
            try:
                success = self.run_once()
                
                # Sleep until next cycle
                if success:
                    sleep_time = REBALANCE_INTERVAL_SECONDS
                else:
                    sleep_time = 300  # 5 minutes on failure
                
                logger.info(f"💤 Sleeping for {sleep_time/60:.0f} minutes...")
                time.sleep(sleep_time)
                
            except KeyboardInterrupt:
                logger.info("🛑 Bot stopped by user")
                break
            except Exception as e:
                logger.exception(f"💥 Fatal error: {e}")
                time.sleep(60)
        
        # Final state save
        self.state.save()
        logger.info("Bot terminated")
    def _start_dashboard(self):
        """Start Flask dashboard in background thread"""
        try:
            from dashboard import start_dashboard
            import threading
            dashboard_thread = threading.Thread(
                target=start_dashboard,
                args=(self, self.risk_manager, self.state, self.executor),
                kwargs={'host': '0.0.0.0', 'port': 8050},
                daemon=True
            )
            dashboard_thread.start()
            logger.info("📊 Dashboard started on http://0.0.0.0:8050")
        except Exception as e:
            logger.warning(f"Failed to start dashboard: {e}")


# ============================================================
# Entry Point
# ============================================================

if __name__ == "__main__":
    bot = TradingBot()
    bot.run()
