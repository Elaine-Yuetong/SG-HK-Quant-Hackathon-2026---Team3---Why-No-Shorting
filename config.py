"""
config.py
Central configuration for the trading infrastructure.
"""

import sys
from loguru import logger

# ──────────────────────────────────────────────
# Logging (loguru)
# ──────────────────────────────────────────────
logger.remove()  # remove default stderr handler
logger.add(
    sys.stderr,
    level="INFO",
    format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> "
           "[<cyan>{name}</cyan>] "
           "<level>{level}</level>: {message}",
)
logger.add(
    "logs/trading_{time:YYYY-MM-DD}.log",
    rotation="1 day",
    retention="30 days",
    level="DEBUG",
    format="{time:YYYY-MM-DD HH:mm:ss.SSS} [{name}] {level}: {message}",
)

# ──────────────────────────────────────────────
# Roostoo API
# ──────────────────────────────────────────────
ROOSTOO_BASE_URL = "https://mock-api.roostoo.com"
ROOSTOO_API_KEY = "6U96yXYBuLfEqhVV59JC7zfJUxSJBGOxSXu7rwtmAI0AhMoNb5tngGYaaHv7MLX1"
ROOSTOO_SECRET_KEY = "dfXy4hs3yIW8PKzCpIyl4cV9vforiNLrO7heqOccw0kUgSFJOBLyJqNnvDBmhlld"

# ──────────────────────────────────────────────
# Binance Public API
# ──────────────────────────────────────────────
BINANCE_REST_URL = "https://api.binance.com"
BINANCE_WS_URL = "wss://stream.binance.com:9443"

# ──────────────────────────────────────────────
# Data Settings
# ──────────────────────────────────────────────
KLINE_INTERVAL = "1m"
KLINE_LIMIT_PER_REQUEST = 1000
HISTORY_DAYS = 30

# ──────────────────────────────────────────────
# Roostoo quote → Binance quote mapping
# ──────────────────────────────────────────────
UNIT_MAP = {
    "USD": "USDT",
}

# ──────────────────────────────────────────────
# Manual overrides for tokens whose Binance symbol
# doesn't follow the naive BASE+QUOTE pattern.
# Maps roostoo_pair → binance_symbol.
# Set value to None to explicitly skip a pair.
# ──────────────────────────────────────────────
PAIR_OVERRIDES = {
    # "S/USD": "SUSDT",           # Sonic — uncomment if Binance lists it
    # "1000CHEEMS/USD": "1000CHEEMSUSDT",
}

# ──────────────────────────────────────────────
# WebSocket Settings
# ──────────────────────────────────────────────
WS_KLINE_INTERVAL = "1m"
WS_RECONNECT_DELAY = 5
WS_PING_INTERVAL = 20

# ──────────────────────────────────────────────
# Paths
# ──────────────────────────────────────────────
DATA_DIR = "historical_data"