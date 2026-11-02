"""Optional read-only publisher for the VORTEXT AI live trades dashboard.

Reads only broker-confirmed MT5 account/positions/deals. It does not submit,
modify, or close orders. Publishing is disabled unless explicitly configured.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import math
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Optional

import aiohttp

logger = logging.getLogger(__name__)

try:
    import MetaTrader5 as _mt5  # type: ignore
except ImportError:
    _mt5 = None


def _get(value: Any, key: str, default: Any = None) -> Any:
    return value.get(key, default) if isinstance(value, Mapping) else getattr(value, key, default)


def _num(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return parsed if math.isfinite(parsed) else default


def _iso(value: Any) -> Optional[str]:
    try:
        if isinstance(value, datetime):
            parsed = value
        else:
            epoch = float(value)
            if not math.isfinite(epoch) or epoch <= 0:
                return None
            parsed = datetime.fromtimestamp(epoch, tz=timezone.utc)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _deal_entry(value: Any) -> str:
    if _mt5 is None:
        return "other"
    mapping = (
        (_mt5.DEAL_ENTRY_IN, "in"),
        (_mt5.DEAL_ENTRY_OUT, "out"),
        (_mt5.DEAL_ENTRY_INOUT, "inout"),
        (_mt5.DEAL_ENTRY_OUT_BY, "out_by"),
    )
    return next((name for code, name in mapping if value == code), "other")


def build_snapshot(client: Any, bot_id: str = "vortext-main", now: Optional[datetime] = None) -> dict[str, Any]:
    """Collect one complete sanitized snapshot from a connected, real MT5 client."""
    if client is None or not getattr(client, "connected", False):
        raise RuntimeError("MT5 client is not connected")
    if getattr(client, "_sim_mode", False):
        raise RuntimeError("Refusing to publish simulated account or trade data")
    if _mt5 is None:
        raise RuntimeError("MetaTrader5 API is not installed")

    account_raw = client.get_account()
    if not account_raw:
        raise RuntimeError("MT5 account state is unavailable")

    positions_raw = client.get_positions()
    if positions_raw is None:
        raise RuntimeError("MT5 position read failed; refusing partial snapshot")

    now_utc = now or datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    else:
        now_utc = now_utc.astimezone(timezone.utc)

    start = now_utc - timedelta(days=7)
    # MT5 Python API expects UTC datetimes.
    deals_raw = _mt5.history_deals_get(start, now_utc)
    if deals_raw is None:
        raise RuntimeError("MT5 deal-history read failed; refusing partial snapshot")

    positions = []
    for item in positions_raw:
        direction = str(_get(item, "direction", "")).lower()
        if direction not in ("buy", "sell"):
            continue
        positions.append({
            "ticket": str(_get(item, "ticket", ""))[:40],
            "symbol": str(_get(item, "symbol", ""))[:32],
            "side": direction,
            "volume": _num(_get(item, "volume")),
            "entry_price": _num(_get(item, "open_price")),
            "current_price": _num(_get(item, "current_price")),
            "sl": _num(_get(item, "sl")),
            "tp": _num(_get(item, "tp")),
            "profit": _num(_get(item, "profit")),
            "swap": _num(_get(item, "swap")),
            "opened_at": _iso(_get(item, "open_time")),
            "magic": str(_get(item, "magic", ""))[:32],
        })
    positions.sort(key=lambda row: row.get("opened_at") or "", reverse=True)

    # Filter history to the bot's configured magic number, not the entire manual account history.
    magic = _get(_get(client, "_cfg", {}), "magic", None)
    deals = []
    for item in deals_raw:
        if magic is not None and _get(item, "magic") != magic:
            continue
        deal_type = _get(item, "type")
        if deal_type == _mt5.DEAL_TYPE_BUY:
            side = "buy"
        elif deal_type == _mt5.DEAL_TYPE_SELL:
            side = "sell"
        else:
            continue
        profit = _num(_get(item, "profit"))
        commission = _num(_get(item, "commission"))
        swap = _num(_get(item, "swap"))
        fee = _num(_get(item, "fee"))
        deals.append({
            "ticket": str(_get(item, "ticket", ""))[:40],
            "position_id": str(_get(item, "position_id", _get(item, "order", "")))[:40],
            "symbol": str(_get(item, "symbol", ""))[:32],
            "side": side,
            "entry": _deal_entry(_get(item, "entry")),
            "volume": _num(_get(item, "volume")),
            "price": _num(_get(item, "price")),
            "profit": profit,
            "commission": commission,
            "swap": swap,
            "fee": fee,
            "net_profit": profit + commission + swap + fee,
            "time": _iso(_get(item, "time")),
            "reason": str(_get(item, "reason", ""))[:24],
        })
    deals.sort(key=lambda row: row.get("time") or "", reverse=True)

    mode = _get(account_raw, "trade_mode")
    mode_map = {0: "DEMO", 1: "CONTEST", 2: "REAL"}
    return {
        "bot_id": str(bot_id)[:64],
        "captured_at": now_utc.isoformat(),
        "account": {
            "server": str(_get(account_raw, "server", ""))[:100],
            "currency": str(_get(account_raw, "currency", ""))[:12],
            "balance": _num(_get(account_raw, "balance")),
            "equity": _num(_get(account_raw, "equity")),
            "margin": _num(_get(account_raw, "margin")),
            "free_margin": _num(_get(account_raw, "free_margin")),
            "leverage": int(max(0, _num(_get(account_raw, "leverage")))),
            "trade_mode": mode_map.get(mode, "UNKNOWN"),
        },
        "positions": positions[:500],
        "deals": deals[:100],
        "bot_status": "running",
    }


def make_signature(secret: str, timestamp: str, body: bytes) -> str:
    """Sign the exact request bytes and timestamp with HMAC-SHA256."""
    return hmac.new(
        secret.encode("utf-8"),
        timestamp.encode("ascii") + b"." + body,
        hashlib.sha256,
    ).hexdigest()


class VortextDashboardPublisher:
    """Background publisher. Disabled by default and never executes trades."""

    def __init__(self, mt5_client: Any = None) -> None:
        self.mt5_client = mt5_client
        self.endpoint = os.getenv("VORTEXT_DASHBOARD_INGEST_URL", "").strip()
        self.secret = os.getenv("VORTEXT_BOT_HMAC_SECRET", "").strip()
        self.bot_id = os.getenv("VORTEXT_BOT_ID", "vortext-main").strip() or "vortext-main"
        requested = os.getenv("VORTEXT_DASHBOARD_SYNC_ENABLED", "false").strip().lower() in {
            "1", "true", "yes", "on"
        }
        try:
            self.interval_seconds = max(3.0, min(60.0, float(os.getenv("VORTEXT_PUBLISH_INTERVAL_SECONDS", "5"))))
        except ValueError:
            self.interval_seconds = 5.0
        self.enabled = bool(
            requested
            and self.endpoint.startswith("https://")
            and len(self.secret) >= 32
            and self.mt5_client is not None
        )
        if requested and not self.enabled:
            logger.warning("VORTEXT live-feed requested with incomplete configuration; publisher disabled")

    def snapshot(self) -> dict[str, Any]:
        return build_snapshot(self.mt5_client, bot_id=self.bot_id)

    async def publish_once(self, session: aiohttp.ClientSession, snapshot: dict[str, Any]) -> bool:
        body = json.dumps(snapshot, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("utf-8")
        timestamp = str(int(time.time()))
        headers = {
            "Content-Type": "application/json",
            "X-Vortext-Timestamp": timestamp,
            "X-Vortext-Signature": make_signature(self.secret, timestamp, body),
        }
        try:
            timeout = aiohttp.ClientTimeout(total=7)
            async with session.post(self.endpoint, data=body, headers=headers, timeout=timeout) as response:
                if response.status not in (200, 201):
                    logger.warning("VORTEXT trade-feed rejected snapshot (HTTP %s)", response.status)
                    return False
                return True
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            logger.warning("VORTEXT trade-feed unavailable (%s)", type(exc).__name__)
            return False

    async def run(self) -> None:
        if not self.enabled:
            logger.info("VORTEXT live-feed publisher disabled; trading behavior unchanged")
            return
        timeout = aiohttp.ClientTimeout(total=7)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            while True:
                try:
                    snapshot = await asyncio.to_thread(self.snapshot)
                    await self.publish_once(session, snapshot)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.warning("VORTEXT trade snapshot skipped (%s)", type(exc).__name__)
                await asyncio.sleep(self.interval_seconds)
