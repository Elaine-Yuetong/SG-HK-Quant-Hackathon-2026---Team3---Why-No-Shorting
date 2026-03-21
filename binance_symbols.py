"""
binance_symbols.py
Fetches Binance's live exchange info and validates/maps
Roostoo pairs to actual Binance spot symbols.
"""

from typing import Dict, List, Tuple, Set

import requests
from loguru import logger

from config import BINANCE_REST_URL, UNIT_MAP, PAIR_OVERRIDES


def fetch_binance_spot_symbols() -> Set[str]:
    """
    Pull every TRADING spot symbol from Binance /api/v3/exchangeInfo.
    Returns a set of uppercase symbols like {'BTCUSDT', 'ETHUSDT', ...}.
    """
    url = f"{BINANCE_REST_URL}/api/v3/exchangeInfo"
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    symbols = set()
    for s in data.get("symbols", []):
        if s.get("status") == "TRADING":
            symbols.add(s["symbol"].upper())
    logger.info("Fetched {} active Binance spot symbols", len(symbols))
    return symbols


def roostoo_pair_to_binance(pair: str) -> str:
    """
    Naive conversion: 'BTC/USD' → 'BTCUSDT'.
    Applies PAIR_OVERRIDES first.
    """
    if pair in PAIR_OVERRIDES:
        return PAIR_OVERRIDES[pair]
    base, quote = pair.split("/")
    binance_quote = UNIT_MAP.get(quote, quote)
    return f"{base}{binance_quote}".upper()


def validate_pairs(
    roostoo_pairs: List[str],
) -> Tuple[Dict[str, str], List[str]]:
    """
    Validate Roostoo pairs against live Binance spot symbols.

    Returns
    -------
    valid : dict
        {roostoo_pair: binance_symbol} for symbols that exist on Binance.
    skipped : list
        Roostoo pairs that have NO Binance spot equivalent.
    """
    binance_symbols = fetch_binance_spot_symbols()
    valid: Dict[str, str] = {}
    skipped: List[str] = []

    for pair in roostoo_pairs:
        # Check override first; None means explicitly skip
        if pair in PAIR_OVERRIDES:
            override = PAIR_OVERRIDES[pair]
            if override is None:
                logger.debug("Pair {} explicitly skipped via override", pair)
                skipped.append(pair)
                continue
            if override.upper() in binance_symbols:
                valid[pair] = override.upper()
                continue
            else:
                logger.warning(
                    "Override {} for {} not found on Binance spot", override, pair
                )
                skipped.append(pair)
                continue

        candidate = roostoo_pair_to_binance(pair)
        if candidate in binance_symbols:
            valid[pair] = candidate
        else:
            skipped.append(pair)

    logger.info(
        "Validation complete: {} valid, {} skipped", len(valid), len(skipped)
    )
    if skipped:
        logger.warning("Skipped (no Binance spot match): {}", skipped)

    return valid, skipped