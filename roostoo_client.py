"""
roostoo_client.py
Complete Roostoo API wrapper with HMAC-SHA256 signing.
"""

import time
import hmac
import hashlib
from typing import Optional, Dict, Any, List

import requests
from loguru import logger

from config import ROOSTOO_BASE_URL, ROOSTOO_API_KEY, ROOSTOO_SECRET_KEY


class RoostooClient:

    def __init__(
        self,
        base_url: str = ROOSTOO_BASE_URL,
        api_key: str = ROOSTOO_API_KEY,
        secret_key: str = ROOSTOO_SECRET_KEY,
        timeout: int = 10,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.secret_key = secret_key
        self.timeout = timeout
        self._session = requests.Session()

    # ──────────── helpers ────────────

    @staticmethod
    def _timestamp_ms() -> str:
        return str(int(time.time() * 1000))

    def _sign(self, payload: dict) -> tuple[dict, str]:
        payload["timestamp"] = self._timestamp_ms()
        sorted_keys = sorted(payload.keys())
        total_params = "&".join(f"{k}={payload[k]}" for k in sorted_keys)
        signature = hmac.new(
            self.secret_key.encode("utf-8"),
            total_params.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        headers = {
            "RST-API-KEY": self.api_key,
            "MSG-SIGNATURE": signature,
        }
        return headers, total_params

    def _get_public(self, path: str, params: dict = None) -> dict:
        url = f"{self.base_url}{path}"
        resp = self._session.get(url, params=params, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def _get_ts(self, path: str, extra: dict = None) -> dict:
        params = {"timestamp": self._timestamp_ms()}
        if extra:
            params.update(extra)
        url = f"{self.base_url}{path}"
        resp = self._session.get(url, params=params, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def _get_signed(self, path: str, payload: dict = None) -> dict:
        payload = payload or {}
        headers, total_params = self._sign(payload)
        url = f"{self.base_url}{path}"
        resp = self._session.get(
            url, headers=headers, params=payload, timeout=self.timeout
        )
        resp.raise_for_status()
        return resp.json()

    def _post_signed(self, path: str, payload: dict) -> dict:
        headers, total_params = self._sign(payload)
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        url = f"{self.base_url}{path}"
        resp = self._session.post(
            url, headers=headers, data=total_params, timeout=self.timeout
        )
        resp.raise_for_status()
        return resp.json()

    # ──────────── Public Endpoints ────────────

    def server_time(self) -> dict:
        return self._get_public("/v3/serverTime")

    def exchange_info(self) -> dict:
        return self._get_public("/v3/exchangeInfo")

    def get_listed_pairs(self) -> List[str]:
        info = self.exchange_info()
        pairs = [
            pair
            for pair, meta in info.get("TradePairs", {}).items()
            if meta.get("CanTrade", False)
        ]
        logger.info("Listed tradeable pairs: {} total", len(pairs))
        return pairs

    def get_trade_pair_meta(self) -> dict:
        """Return the full TradePairs dict for downstream use."""
        info = self.exchange_info()
        return info.get("TradePairs", {})

    def ticker(self, pair: Optional[str] = None) -> dict:
        extra = {"pair": pair} if pair else {}
        return self._get_ts("/v3/ticker", extra)

    # ──────────── Signed Endpoints ────────────

    def balance(self) -> dict:
        return self._get_signed("/v3/balance")

    def pending_count(self) -> dict:
        return self._get_signed("/v3/pending_count")

    def place_order(
        self,
        pair: str,
        side: str,
        quantity: float,
        order_type: str = "MARKET",
        price: Optional[float] = None,
    ) -> dict:
        if "/" not in pair:
            pair = f"{pair}/USD"
        if order_type.upper() == "LIMIT" and price is None:
            raise ValueError("LIMIT orders require a price.")
        payload: Dict[str, Any] = {
            "pair": pair,
            "side": side.upper(),
            "type": order_type.upper(),
            "quantity": str(quantity),
        }
        if price is not None:
            payload["price"] = str(price)
        return self._post_signed("/v3/place_order", payload)

    def query_order(
        self,
        order_id: Optional[int] = None,
        pair: Optional[str] = None,
        offset: Optional[int] = None,
        limit: Optional[int] = None,
        pending_only: Optional[bool] = None,
    ) -> dict:
        payload: Dict[str, Any] = {}
        if order_id is not None:
            payload["order_id"] = str(order_id)
        else:
            if pair:
                payload["pair"] = pair
            if offset is not None:
                payload["offset"] = str(offset)
            if limit is not None:
                payload["limit"] = str(limit)
            if pending_only is not None:
                payload["pending_only"] = "TRUE" if pending_only else "FALSE"
        return self._post_signed("/v3/query_order", payload)

    def cancel_order(
        self,
        order_id: Optional[int] = None,
        pair: Optional[str] = None,
    ) -> dict:
        payload: Dict[str, Any] = {}
        if order_id is not None:
            payload["order_id"] = str(order_id)
        elif pair is not None:
            payload["pair"] = pair
        return self._post_signed("/v3/cancel_order", payload)
