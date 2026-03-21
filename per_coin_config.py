"""
per_coin_config.py
Configuration for each coin's best strategy based on 90-day backtest results.

Each coin uses its proven best strategy with optimized parameters.
This is the result of exhaustive backtesting across 66 coins and 5 strategies.
"""

# ============================================================
# Strategy Configuration per Coin
# ============================================================

COIN_STRATEGY_CONFIG = {
    # ============================================================
    # DUAL MA GROUP - Best for most coins (85% beat hold)
    # ============================================================
    'XPL/USD': {
        'strategy': 'dual_ma',
        'params': [10, 20],           # fast=10, slow=20
        'expected_return': 125.03,    # 90-day return (%)
        'trades_90d': 7250,
        'risk_level': 'high'
    },
    'PENGU/USD': {
        'strategy': 'dual_ma',
        'params': [10, 20],
        'expected_return': 124.51,
        'trades_90d': 7148,
        'risk_level': 'high'
    },
    'PUMP/USD': {
        'strategy': 'dual_ma',
        'params': [10, 20],
        'expected_return': 106.07,
        'trades_90d': 7224,
        'risk_level': 'high'
    },
    'STO/USD': {
        'strategy': 'dual_ma',
        'params': [25, 30],
        'expected_return': 66.22,
        'trades_90d': 6587,
        'risk_level': 'medium'
    },
    'VIRTUAL/USD': {
        'strategy': 'dual_ma',
        'params': [10, 20],
        'expected_return': 38.28,
        'trades_90d': 7258,
        'risk_level': 'medium'
    },
    'TAO/USD': {
        'strategy': 'dual_ma',
        'params': [40, 150],
        'expected_return': 37.28,
        'trades_90d': 1095,
        'risk_level': 'medium'
    },
    'ZEC/USD': {
        'strategy': 'dual_ma',
        'params': [25, 120],
        'expected_return': 37.12,
        'trades_90d': 1478,
        'risk_level': 'medium'
    },
    'TRX/USD': {
        'strategy': 'dual_ma',
        'params': [40, 200],
        'expected_return': 26.06,
        'trades_90d': 859,
        'risk_level': 'low'
    },
    'BTC/USD': {
        'strategy': 'dual_ma',
        'params': [40, 120],
        'expected_return': 2.35,
        'trades_90d': 1296,
        'risk_level': 'low'
    },
    'PAXG/USD': {
        'strategy': 'dual_ma',
        'params': [5, 40],
        'expected_return': 25.07,
        'trades_90d': 5132,
        'risk_level': 'low'
    },
    
    # ============================================================
    # MACD GROUP - Explosive returns on specific coins
    # ============================================================
    'FLOKI/USD': {
        'strategy': 'macd',
        'params': [5, 20, 12],        # fast=5, slow=20, signal=12
        'expected_return': 566.49,
        'trades_90d': 13520,
        'risk_level': 'high'
    },
    'ETH/USD': {
        'strategy': 'macd',
        'params': [5, 30, 10],         # fast=5, slow=30, signal=10
        'expected_return': 69.39,
        'trades_90d': 13702,
        'risk_level': 'medium'
    },
    'BNB/USD': {
        'strategy': 'macd',
        'params': [15, 20, 9],         # fast=15, slow=20, signal=9
        'expected_return': 111.27,
        'trades_90d': 9922,
        'risk_level': 'medium'
    },
    'HBAR/USD': {
        'strategy': 'macd',
        'params': [10, 20, 15],        # fast=10, slow=20, signal=15
        'expected_return': 133.66,
        'trades_90d': 9683,
        'risk_level': 'medium'
    },
    
    # ============================================================
    # RSI GROUP - Extreme returns on specific coins
    # ============================================================
    '1000CHEEMS/USD': {
        'strategy': 'rsi',
        'params': [7, 30, 70],         # period=7, oversold=30, overbought=70
        'expected_return': 122.51,
        'trades_90d': 3425,
        'risk_level': 'high'
    },
    'WIF/USD': {
        'strategy': 'rsi',
        'params': [7, 30, 70],
        'expected_return': 1796.59,
        'trades_90d': 2943,
        'risk_level': 'extreme'
    },
    'EIGEN/USD': {
        'strategy': 'rsi',
        'params': [7, 30, 70],
        'expected_return': 2833.22,
        'trades_90d': 2428,
        'risk_level': 'extreme'
    },
}


# ============================================================
# Coins to AVOID (All strategies underperform or lose money)
# ============================================================

AVOID_COINS = [
    'PEPE/USD',      # All strategies lose
    'BIO/USD',       # All strategies lose
    'HEMI/USD',      # All strategies lose
    'ASTER/USD',     # All strategies lose
    'BMT/USD',       # All strategies lose
    'TUT/USD',       # All strategies lose
    'LINEA/USD',     # All strategies lose
]


# ============================================================
# Risk Level Mapping
# ============================================================

RISK_WEIGHTS = {
    'low': 0.05,      # 5% of portfolio per coin
    'medium': 0.06,   # 6% of portfolio per coin
    'high': 0.08,     # 8% of portfolio per coin
    'extreme': 0.05,  # 5% but capped (too volatile)
}


# ============================================================
# Expected Returns for QUBO Optimization
# ============================================================

def get_expected_return(coin: str) -> float:
    """Get expected return for a coin (for QUBO optimization)"""
    if coin in COIN_STRATEGY_CONFIG:
        return COIN_STRATEGY_CONFIG[coin]['expected_return']
    return 0.0


def get_trades_90d(coin: str) -> int:
    """Get 90-day trade count for a coin"""
    if coin in COIN_STRATEGY_CONFIG:
        return COIN_STRATEGY_CONFIG[coin]['trades_90d']
    return 9999


def get_risk_level(coin: str) -> str:
    """Get risk level for a coin"""
    if coin in COIN_STRATEGY_CONFIG:
        return COIN_STRATEGY_CONFIG[coin]['risk_level']
    return 'medium'


# ============================================================
# Initial Portfolio Candidates (Pre-QUBO)
# ============================================================

# All coins that passed the filter (positive expected return, not in AVOID list)
CANDIDATE_COINS = [
    'XPL/USD', 'PENGU/USD', 'PUMP/USD', 'STO/USD', 'VIRTUAL/USD',
    'TAO/USD', 'ZEC/USD', 'TRX/USD', 'BTC/USD', 'PAXG/USD',
    'FLOKI/USD', 'ETH/USD', 'BNB/USD', 'HBAR/USD',
    '1000CHEEMS/USD', 'WIF/USD', 'EIGEN/USD'
]

# Target number of coins after QUBO optimization
TARGET_N_COINS = 8

# Target cash reserve (10%)
TARGET_CASH = 0.10


# ============================================================
# Helper Functions
# ============================================================

def get_strategy_params(coin: str):
    """Get strategy and parameters for a coin"""
    if coin in COIN_STRATEGY_CONFIG:
        config = COIN_STRATEGY_CONFIG[coin]
        return config['strategy'], config['params']
    return None, None


def is_valid_coin(coin: str) -> bool:
    """Check if coin should be traded"""
    return coin in COIN_STRATEGY_CONFIG and coin not in AVOID_COINS


def get_all_tradable_coins() -> list:
    """Get all coins with valid strategies"""
    return [coin for coin in COIN_STRATEGY_CONFIG.keys() if coin not in AVOID_COINS]