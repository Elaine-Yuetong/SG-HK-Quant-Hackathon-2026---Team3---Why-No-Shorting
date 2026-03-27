"""
risk_manager.py
Risk management: stop loss, kill switch, position sizing, drawdown protection.
"""

from datetime import datetime, date, timedelta
from typing import Dict, Optional, Tuple
import json
import os
import numpy as np
from loguru import logger


class RiskManager:
    """
    Multi-layer risk management system.
    
    Layers:
        1. Per-coin stop loss (加权平均成本)
        2. Daily loss limit (kill switch)
        3. Total loss limit (kill switch)
        4. Drawdown protection (reduce positions)
        5. Trade cooldown after losses
    """
    
    def __init__(
        self,
        initial_capital: float = 1_000_000,
        daily_loss_limit: float = 0.05,      # 5% daily loss = stop trading
        total_loss_limit: float = 0.15,      # 15% total loss = stop all
        per_coin_stop_loss: float = 0.10,    # 10% loss = sell that coin
        drawdown_reduce_threshold: float = 0.10,  # 10% drawdown = half positions
        cooldown_hours: int = 2,             # Cooldown after loss
        state_file: str = "state.json"
    ):
        self.initial_capital = initial_capital
        self.daily_loss_limit = daily_loss_limit
        self.total_loss_limit = total_loss_limit
        self.per_coin_stop_loss = per_coin_stop_loss
        self.drawdown_reduce_threshold = drawdown_reduce_threshold
        self.cooldown_hours = cooldown_hours
        self.state_file = state_file
        
        # Runtime state
        self.peak_capital = initial_capital
        self.day_start_capital = initial_capital
        self.current_day = None
        self.cooldown_until = None
        self.is_killed = False
        self.kill_reason = None
        
        # Track per-coin entry prices (加权平均成本)
        self.entry_prices: Dict[str, float] = {}
        # Track per-coin quantities
        self.entry_quantities: Dict[str, float] = {}
        self.highest_prices: Dict[str, float] = {}  # trailing stop: track highest price
        
        # Load previous state if exists
        self._load_state()
    
    def _load_state(self):
        """Load risk state from file for recovery after restart"""
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, 'r') as f:
                    data = json.load(f)
                    self.peak_capital = data.get('peak_capital', self.initial_capital)
                    self.is_killed = data.get('is_killed', False)
                    self.kill_reason = data.get('kill_reason', None)
                    # 加载持仓数据
                    self.entry_prices = data.get('entry_prices', {})
                    self.entry_quantities = data.get('entry_quantities', {})
                    logger.info(f"Loaded risk state: peak={self.peak_capital}, killed={self.is_killed}")
                    if self.entry_prices:
                        logger.info(f"  Active positions: {len(self.entry_prices)}")
            except Exception as e:
                logger.warning(f"Failed to load risk state: {e}")
    
    def _save_state(self):
        """Save risk state for recovery"""
        try:
            data = {
                'peak_capital': self.peak_capital,
                'is_killed': self.is_killed,
                'kill_reason': self.kill_reason,
                'entry_prices': self.entry_prices,
                'entry_quantities': self.entry_quantities,
                'timestamp': datetime.now().isoformat()
            }
            with open(self.state_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save risk state: {e}")
    
    def _reset_daily(self, current_capital: float):
        """Reset daily counters at start of new day"""
        today = date.today()
        if self.current_day != today:
            self.current_day = today
            self.day_start_capital = current_capital if current_capital > 1.0 else self.initial_capital
            logger.info(f"New day started. Daily start capital: ${self.day_start_capital:,.2f}")
    
    def check_per_coin_stop(
        self, 
        coin: str, 
        current_price: float, 
        entry_price: float = None
    ) -> bool:
        """
        Check if a coin should be sold due to stop loss.
        
        Args:
            coin: Coin symbol
            current_price: Current market price
            entry_price: Entry price (uses stored weighted avg if not provided)
        
        Returns:
            True if should sell, False otherwise
        """
        if entry_price is None:
            entry_price = self.entry_prices.get(coin)
        
        if entry_price is None or entry_price <= 0:
            return False
        
        loss_pct = (entry_price - current_price) / entry_price
        
        if loss_pct >= self.per_coin_stop_loss:
            logger.warning(f"🔴 STOP LOSS: {coin} down {loss_pct:.2%} (limit {self.per_coin_stop_loss:.2%}), entry={entry_price:.4f}, current={current_price:.4f}")
            return True
        
        return False

    def check_trailing_stop(self, coin: str, current_price: float, trail_percent: float = 0.10) -> bool:
        """
        Trailing stop loss: sell if price drops X% from peak.
    
        Args:
            coin: Coin symbol
            current_price: Current market price
            trail_percent: Trailing stop percentage (default 10%)
    
        Returns:
            True if should sell, False otherwise
        """
        highest = self.highest_prices.get(coin, current_price)
    
        # Update highest price
        if current_price > highest:
            self.highest_prices[coin] = current_price
            highest = current_price
    
        # Check drawdown from peak
        drawdown = (highest - current_price) / highest
    
        if drawdown >= trail_percent:
            logger.warning(f"🔴 TRAILING STOP: {coin} down {drawdown:.2%} from peak {highest:.4f}")
            return True
    
        return False
    
    def record_entry(self, coin: str, price: float, quantity: float = 1.0):
        """
        Record entry price for stop loss tracking (加权平均成本).
        
        Args:
            coin: Coin symbol
            price: Entry price
            quantity: Quantity bought (default 1.0)
        """
        if coin in self.entry_prices:
            # 已有持仓，计算加权平均
            old_price = self.entry_prices[coin]
            old_qty = self.entry_quantities.get(coin, 0)
            total_qty = old_qty + quantity
            avg_price = (old_price * old_qty + price * quantity) / total_qty
            self.entry_prices[coin] = avg_price
            self.entry_quantities[coin] = total_qty
            logger.debug(f"Updated avg entry for {coin}: {avg_price:.4f} (qty={total_qty:.4f})")
            if price > self.highest_prices.get(coin, 0):
                self.highest_prices[coin] = price
        else:
            self.entry_prices[coin] = price
            self.entry_quantities[coin] = quantity
            logger.debug(f"Recorded entry for {coin} @ ${price:.4f}, qty={quantity:.4f}")
            self.highest_prices[coin] = price
    
    def record_exit(self, coin: str, quantity: float = None):
        """
        Remove coin or update quantity after selling.
        
        Args:
            coin: Coin symbol
            quantity: Quantity sold (if None, sell all)
        """
        if coin not in self.entry_prices:
            return
        
        if quantity is None or quantity >= self.entry_quantities.get(coin, 0):
            # Full exit, delete all records
            del self.entry_prices[coin]
            if coin in self.entry_quantities:
                del self.entry_quantities[coin]
            if coin in self.highest_prices:
                del self.highest_prices[coin]
            logger.debug(f"Removed entry for {coin} (full exit)")
        else:
            # Partial exit, reduce quantity only
            old_qty = self.entry_quantities.get(coin, 0)
            new_qty = old_qty - quantity
            self.entry_quantities[coin] = new_qty
            logger.debug(f"Updated {coin}: remaining qty={new_qty:.4f}")
    
    def check_kill_switch(
        self, 
        current_capital: float
    ) -> Tuple[bool, str]:
        """
        Check if kill switch should be activated.
        
        Returns:
            (should_stop, reason)
        """
        # Already killed
        if self.is_killed:
            return True, self.kill_reason or "Kill switch already active"
        
        # Reset daily tracking if needed
        self._reset_daily(current_capital)
        
        # Check cooldown
        if self.cooldown_until and datetime.now() < self.cooldown_until:
            remaining = (self.cooldown_until - datetime.now()).total_seconds() / 3600
            return True, f"Cooldown active for {remaining:.1f} more hours"
        
        # 1. Daily loss limit
        if self.day_start_capital > 1.0:  # 确保至少 $1
            daily_loss = (self.day_start_capital - current_capital) / self.day_start_capital
            if daily_loss > self.daily_loss_limit:
                self.is_killed = True
                self.kill_reason = f"Daily loss {daily_loss:.2%} > limit {self.daily_loss_limit:.2%}"
                self.cooldown_until = datetime.now() + timedelta(hours=self.cooldown_hours)
                self._save_state()
                return True, self.kill_reason
        else:
        # 如果 day_start_capital 不合理，重置为当前资本
            self.day_start_capital = current_capital
        
        # 2. Total loss limit
        if self.initial_capital > 0:
            total_loss = (self.initial_capital - current_capital) / self.initial_capital
            if total_loss > self.total_loss_limit:
                self.is_killed = True
                self.kill_reason = f"Total loss {total_loss:.2%} > limit {self.total_loss_limit:.2%}"
                self._save_state()
                return True, self.kill_reason
        
        return False, "OK"
    
    def check_drawdown(self, current_capital: float) -> str:
        """
        Check drawdown and return action.
        
        Returns:
            'REDUCE_HALF', 'NORMAL', or 'STOP'
        """
        # Update peak
        if current_capital > self.peak_capital:
            self.peak_capital = current_capital
            self._save_state()
        
        if self.peak_capital > 0:
            drawdown = (self.peak_capital - current_capital) / self.peak_capital
        else:
            drawdown = 0
        
        if drawdown > self.drawdown_reduce_threshold:
            logger.warning(f"📉 Drawdown {drawdown:.2%} > {self.drawdown_reduce_threshold:.2%} - reducing positions")
            return "REDUCE_HALF"
        
        return "NORMAL"
    
    def get_position_multiplier(self, current_capital: float) -> float:
        """
        Get position size multiplier based on current risk state.
        
        Returns:
            1.0 = normal
            0.5 = half positions
            0.0 = no trading
        """
        # Check kill switch first
        killed, _ = self.check_kill_switch(current_capital)
        if killed:
            return 0.0
        
        # Check drawdown
        action = self.check_drawdown(current_capital)
        if action == "REDUCE_HALF":
            return 0.5
        
        return 1.0
    
    def reset_kill_switch(self):
        """Manually reset kill switch (use with caution)"""
        self.is_killed = False
        self.kill_reason = None
        self.cooldown_until = None
        self._save_state()
        logger.info("Kill switch manually reset")
    
    def get_status(self) -> Dict:
        """Get current risk status for dashboard"""
        return {
            'initial_capital': self.initial_capital,
            'peak_capital': self.peak_capital,
            'is_killed': self.is_killed,
            'kill_reason': self.kill_reason,
            'cooldown_until': self.cooldown_until.isoformat() if self.cooldown_until else None,
            'active_positions': len(self.entry_prices),
        }


# ============================================================
# Position Sizing (Volatility-Based)
# ============================================================

def calculate_position_size(
    capital: float,
    current_price: float,
    volatility: float,
    target_risk: float = 0.02,      # 2% portfolio risk per trade
    min_pct: float = 0.05,          # Minimum 5% of capital
    max_pct: float = 0.20           # Maximum 20% of capital
) -> float:
    """
    Calculate position size based on volatility (Kelly-inspired).
    
    Args:
        capital: Total capital
        current_price: Current coin price
        volatility: Annualized volatility (can be hourly * sqrt(365*24))
        target_risk: Target risk per trade (default 2%)
        min_pct: Minimum % of capital to allocate
        max_pct: Maximum % of capital to allocate
    
    Returns:
        Quantity to buy
    """
    if volatility <= 0:
        position_pct = min_pct
    else:
        # Higher volatility = smaller position
        base_pct = target_risk / volatility
        position_pct = max(min_pct, min(base_pct, max_pct))
    
    position_value = capital * position_pct
    quantity = position_value / current_price
    
    logger.debug(f"Position size: {position_pct:.1%} of capital = ${position_value:,.2f}")
    return quantity


def calculate_volatility(price_series, lookback: int = 24, annualize: bool = True):
    """
    Calculate volatility from price series.
    
    Args:
        price_series: List or Series of prices
        lookback: Number of periods to use
        annualize: If True, convert to annualized volatility
    
    Returns:
        Volatility (decimal, not percentage)
    """
    if len(price_series) < lookback:
        return 0.5  # Default high volatility
    
    returns = np.diff(price_series[-lookback:]) / price_series[-lookback-1:-1]
    vol = np.std(returns)
    
    if annualize and vol > 0:
        # Annualize: multiply by sqrt(periods per year)
        # Assuming hourly data: 365 * 24 = 8760 periods per year
        vol = vol * np.sqrt(8760)
    
    return min(vol, 2.0)  # Cap at 200% volatility


# ============================================================
# Trade Cost Calculator
# ============================================================

class TradeCostCalculator:
    """Calculate trading costs for decision making"""
    
    def __init__(self, taker_fee: float = 0.001, maker_fee: float = 0.0005):
        self.taker_fee = taker_fee
        self.maker_fee = maker_fee
    
    def round_trip_cost(self, value: float, use_maker: bool = False) -> float:
        """Calculate round trip cost (buy + sell)"""
        fee = self.maker_fee if use_maker else self.taker_fee
        return value * fee * 2
    
    def should_trade(self, gross_return: float, trade_count: int, avg_trade_value: float) -> bool:
        """
        Check if trading is worthwhile after fees.
        
        Args:
            gross_return: Expected gross return (%)
            trade_count: Expected number of trades
            avg_trade_value: Average trade value
        
        Returns:
            True if net return > 0
        """
        total_fees = trade_count * avg_trade_value * self.taker_fee * 2
        net_return = gross_return - (total_fees / avg_trade_value)
        return net_return > 0
