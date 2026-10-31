"""Read-only publisher for the VORTEXT AI live trades and multi-account fleet dashboard.

Reads only broker-confirmed MT5 account/positions/deals across single or multiple
accounts. It does not submit, modify, or close orders. Publishing is disabled
unless explicitly configured.
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
from typing import Any, Dict, List, Mapping, Optional, Sequence

import aiohttp

logger = logging.getLogger(__name__)

try:
    import MetaTrader5 as _mt5  # type: ignore
except ImportError:
    _mt5 = None


def _get(value: Any, key: str, default: Any = None) -> Any:
    """Safe lookup in dict or object attribute."""
    if value is None:
        return default
    if isinstance(value, Mapping):
        return value.get(key, default)
    return getattr(value, key, default)


def _num(value: Any, default: float = 0.0) -> float:
    """Convert value to float, ensuring finite number."""
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return parsed if math.isfinite(parsed) else default


def _iso(value: Any) -> Optional[str]:
    """Convert timestamp or datetime to ISO 8601 UTC string."""
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
    """Convert MT5 deal entry int code to lowercase string."""
    if isinstance(value, str):
        return value.lower()
    if _mt5 is None:
        entry_map = {0: "in", 1: "out", 2: "inout", 3: "out_by"}
        return entry_map.get(value, "other")
    mapping = (
        (_mt5.DEAL_ENTRY_IN, "in"),
        (_mt5.DEAL_ENTRY_OUT, "out"),
        (_mt5.DEAL_ENTRY_INOUT, "inout"),
        (_mt5.DEAL_ENTRY_OUT_BY, "out_by"),
    )
    return next((name for code, name in mapping if value == code), "other")


def make_signature(secret: str, timestamp: str, body: bytes) -> str:
    """Sign the exact request bytes and timestamp with HMAC-SHA256."""
    return hmac.new(
        secret.encode("utf-8"),
        timestamp.encode("ascii") + b"." + body,
        hashlib.sha256,
    ).hexdigest()


def _format_position(item: Any, account_id: str = "", login: int = 0, server: str = "") -> Optional[Dict[str, Any]]:
    """Sanitize and format an open position."""
    direction = str(_get(item, "direction", "")).lower()
    if direction not in ("buy", "sell", "long", "short"):
        return None
    side = "buy" if direction in ("buy", "long") else "sell"
    return {
        "ticket": str(_get(item, "ticket", ""))[:40],
        "symbol": str(_get(item, "symbol", ""))[:32],
        "side": side,
        "volume": _num(_get(item, "volume")),
        "entry_price": _num(_get(item, "open_price")),
        "current_price": _num(_get(item, "current_price")),
        "sl": _num(_get(item, "sl")),
        "tp": _num(_get(item, "tp")),
        "profit": _num(_get(item, "profit")),
        "swap": _num(_get(item, "swap")),
        "opened_at": _iso(_get(item, "open_time")),
        "magic": str(_get(item, "magic", ""))[:32],
        "account_id": str(account_id)[:40],
        "login": int(login) if login else 0,
        "server": str(server)[:100],
    }


def _format_deal(item: Any, magic: Optional[int] = None, account_id: str = "", login: int = 0, server: str = "") -> Optional[Dict[str, Any]]:
    """Sanitize and format a closed deal history item."""
    item_magic = _get(item, "magic")
    if magic is not None and item_magic is not None and item_magic != magic:
        return None

    raw_type = _get(item, "type")
    side = None
    if _mt5 is not None:
        if raw_type == _mt5.DEAL_TYPE_BUY:
            side = "buy"
        elif raw_type == _mt5.DEAL_TYPE_SELL:
            side = "sell"
    else:
        if raw_type == 0:
            side = "buy"
        elif raw_type == 1:
            side = "sell"

    if side is None:
        raw_side = str(_get(item, "side", "")).lower()
        if raw_side in ("buy", "sell"):
            side = raw_side
        else:
            return None

    profit = _num(_get(item, "profit"))
    commission = _num(_get(item, "commission"))
    swap = _num(_get(item, "swap"))
    fee = _num(_get(item, "fee"))
    return {
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
        "magic": str(item_magic) if item_magic is not None else "",
        "account_id": str(account_id)[:40],
        "login": int(login) if login else 0,
        "server": str(server)[:100],
    }


def build_snapshot(source: Any, bot_id: str = "vortext-fleet", now: Optional[datetime] = None) -> Dict[str, Any]:
    """Collect a complete sanitized snapshot from connected real MT5 sessions.

    Supports either:
    1. MT5AccountManager (multi-account fleet)
    2. Single MT5Client (legacy fallback)
    """
    if source is None:
        raise RuntimeError("Trade feed source is not provided")

    now_utc = now or datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    else:
        now_utc = now_utc.astimezone(timezone.utc)

    mode_map = {0: "DEMO", 1: "CONTEST", 2: "REAL"}

    # ── CASE 1: Multi-Account Manager ──────────────────────────────────────────
    contexts_dict = getattr(source, "_contexts", None)
    if contexts_dict is not None and isinstance(contexts_dict, dict):
        accounts_list: List[Dict[str, Any]] = []
        all_positions: List[Dict[str, Any]] = []
        all_deals: List[Dict[str, Any]] = []

        total_balance = 0.0
        total_equity = 0.0
        total_margin = 0.0
        total_free_margin = 0.0

        for account_id, ctx in contexts_dict.items():
            cfg = getattr(ctx, "config", None)
            if not cfg or not getattr(cfg, "enabled", False):
                continue
            if getattr(cfg, "dry_run", False):
                # Refuse simulated account data in live feed
                continue

            session = getattr(ctx, "session", getattr(ctx, "mt5_session", None))
            if session is None:
                continue
            is_conn = session.is_connected() if hasattr(session, "is_connected") else True
            if not is_conn:
                continue

            info = session.get_account_info()
            if not info:
                continue

            trade_mode_val = _get(info, "trade_mode", 0)
            trade_mode_str = mode_map.get(trade_mode_val, "DEMO" if isinstance(trade_mode_val, int) and trade_mode_val == 0 else "UNKNOWN")

            acct_balance = _num(_get(info, "balance"))
            acct_equity = _num(_get(info, "equity"))
            acct_margin = _num(_get(info, "margin"))
            acct_free_margin = _num(_get(info, "free_margin", _get(info, "margin_free")))
            acct_leverage = int(max(0, _num(_get(info, "leverage", 100))))
            acct_server = str(_get(info, "server", cfg.server))[:100]
            acct_currency = str(_get(info, "currency", "USD"))[:12]

            # Fetch account positions (filtered by magic number)
            positions_raw = session.get_positions(all_magic=False) or []
            acct_positions: List[Dict[str, Any]] = []
            for p in positions_raw:
                formatted = _format_position(p, account_id=account_id, login=cfg.login, server=acct_server)
                if formatted:
                    acct_positions.append(formatted)

            # Fetch account deal history (filtered by magic number, 7 days)
            deals_raw = session.get_history_deals(days=7, all_magic=False) or []
            acct_deals: List[Dict[str, Any]] = []
            for d in deals_raw:
                formatted = _format_deal(d, magic=cfg.magic_number, account_id=account_id, login=cfg.login, server=acct_server)
                if formatted:
                    acct_deals.append(formatted)

            acct_positions.sort(key=lambda row: row.get("opened_at") or "", reverse=True)
            acct_deals.sort(key=lambda row: row.get("time") or "", reverse=True)

            accounts_list.append({
                "account_id": account_id,
                "login": cfg.login,
                "server": acct_server,
                "currency": acct_currency,
                "balance": acct_balance,
                "equity": acct_equity,
                "margin": acct_margin,
                "free_margin": acct_free_margin,
                "leverage": acct_leverage,
                "trade_mode": trade_mode_str,
                "enabled": bool(cfg.enabled),
                "trading_enabled": bool(cfg.trading_enabled),
                "positions_count": len(acct_positions),
                "deals_count": len(acct_deals),
            })

            total_balance += acct_balance
            total_equity += acct_equity
            total_margin += acct_margin
            total_free_margin += acct_free_margin

            all_positions.extend(acct_positions)
            all_deals.extend(acct_deals)

        if not accounts_list:
            raise RuntimeError("No active real MT5 accounts connected in account manager")

        all_positions.sort(key=lambda row: row.get("opened_at") or "", reverse=True)
        all_deals.sort(key=lambda row: row.get("time") or "", reverse=True)

        primary_acct = accounts_list[0]
        total_floating_pnl = sum(p["profit"] + p["swap"] for p in all_positions)

        summary_account = {
            "server": primary_acct["server"] if len(accounts_list) == 1 else f"Fleet ({len(accounts_list)} accounts)",
            "currency": primary_acct["currency"],
            "balance": round(total_balance, 2),
            "equity": round(total_equity, 2),
            "margin": round(total_margin, 2),
            "free_margin": round(total_free_margin, 2),
            "leverage": primary_acct["leverage"],
            "trade_mode": primary_acct["trade_mode"],
            "total_accounts": len(accounts_list),
        }

        return {
            "bot_id": str(bot_id)[:64],
            "captured_at": now_utc.isoformat(),
            "account": summary_account,
            "accounts": accounts_list,
            "positions": all_positions[:500],
            "deals": all_deals[:100],
            "fleet_summary": {
                "total_accounts": len(accounts_list),
                "total_balance": round(total_balance, 2),
                "total_equity": round(total_equity, 2),
                "total_floating_pnl": round(total_floating_pnl, 2),
                "total_positions": len(all_positions),
                "total_recent_deals": len(all_deals),
            },
            "bot_status": "running",
        }

    # ── CASE 2: Single MT5 Client (Legacy Fallback) ───────────────────────────
    client = source
    if not getattr(client, "connected", False):
        raise RuntimeError("MT5 client is not connected")
    if getattr(client, "_sim_mode", False):
        raise RuntimeError("Refusing to publish simulated account or trade data")

    account_raw = client.get_account()
    if not account_raw:
        raise RuntimeError("MT5 account state is unavailable")

    positions_raw = client.get_positions()
    if positions_raw is None:
        raise RuntimeError("MT5 position read failed; refusing partial snapshot")

    magic = _get(_get(client, "_cfg", {}), "magic", None)
    positions = []
    for item in positions_raw:
        formatted = _format_position(item, account_id="primary", login=_get(account_raw, "login", 0), server=str(_get(account_raw, "server", "")))
        if formatted:
            positions.append(formatted)
    positions.sort(key=lambda row: row.get("opened_at") or "", reverse=True)

    start_dt = now_utc - timedelta(days=7)
    deals_raw = None
    if hasattr(client, "get_history"):
        try:
            deals_raw = client.get_history(start_dt, now_utc)
        except Exception:
            deals_raw = None

    if deals_raw is None and _mt5 is not None:
        try:
            deals_raw = _mt5.history_deals_get(start_dt, now_utc)
        except Exception:
            deals_raw = None

    if deals_raw is None:
        deals_raw = []

    deals = []
    for item in deals_raw:
        formatted = _format_deal(item, magic=magic, account_id="primary", login=_get(account_raw, "login", 0), server=str(_get(account_raw, "server", "")))
        if formatted:
            deals.append(formatted)
    deals.sort(key=lambda row: row.get("time") or "", reverse=True)

    mode = _get(account_raw, "trade_mode")
    single_account = {
        "server": str(_get(account_raw, "server", ""))[:100],
        "currency": str(_get(account_raw, "currency", ""))[:12],
        "balance": _num(_get(account_raw, "balance")),
        "equity": _num(_get(account_raw, "equity")),
        "margin": _num(_get(account_raw, "margin")),
        "free_margin": _num(_get(account_raw, "free_margin", _get(account_raw, "margin_free"))),
        "leverage": int(max(0, _num(_get(account_raw, "leverage")))),
        "trade_mode": mode_map.get(mode, "UNKNOWN"),
    }

    accounts_list = [{
        "account_id": "primary",
        "login": _get(account_raw, "login", 0),
        "server": single_account["server"],
        "currency": single_account["currency"],
        "balance": single_account["balance"],
        "equity": single_account["equity"],
        "margin": single_account["margin"],
        "free_margin": single_account["free_margin"],
        "leverage": single_account["leverage"],
        "trade_mode": single_account["trade_mode"],
        "enabled": True,
        "trading_enabled": True,
        "positions_count": len(positions),
        "deals_count": len(deals),
    }]

    return {
        "bot_id": str(bot_id)[:64],
        "captured_at": now_utc.isoformat(),
        "account": single_account,
        "accounts": accounts_list,
        "positions": positions[:500],
        "deals": deals[:100],
        "fleet_summary": {
            "total_accounts": 1,
            "total_balance": single_account["balance"],
            "total_equity": single_account["equity"],
            "total_floating_pnl": round(sum(p["profit"] + p["swap"] for p in positions), 2),
            "total_positions": len(positions),
            "total_recent_deals": len(deals),
        },
        "bot_status": "running",
    }


class VortextDashboardPublisher:
    """Background publisher for VORTEXT live trades feed.

    Disabled by default and strictly read-only: never places, modifies, or cancels trades.
    """

    def __init__(self, account_manager: Any = None, mt5_client: Any = None) -> None:
        self.account_manager = account_manager
        self.mt5_client = mt5_client
        self.endpoint = os.getenv("VORTEXT_DASHBOARD_INGEST_URL", "").strip()
        self.secret = os.getenv("VORTEXT_BOT_HMAC_SECRET", "").strip()
        self.bot_id = os.getenv("VORTEXT_BOT_ID", "vortext-fleet").strip() or "vortext-fleet"

        requested = os.getenv("VORTEXT_DASHBOARD_SYNC_ENABLED", "false").strip().lower() in {
            "1", "true", "yes", "on"
        }
        try:
            self.interval_seconds = max(3.0, min(60.0, float(os.getenv("VORTEXT_PUBLISH_INTERVAL_SECONDS", "5"))))
        except ValueError:
            self.interval_seconds = 5.0

        has_source = (self.account_manager is not None) or (self.mt5_client is not None)
        self.enabled = bool(
            requested
            and self.endpoint.startswith("https://")
            and len(self.secret) >= 32
            and has_source
        )
        if requested and not self.enabled:
            logger.warning("VORTEXT live-feed requested with incomplete configuration; publisher disabled")

    @property
    def source(self) -> Any:
        return self.account_manager if self.account_manager is not None else self.mt5_client

    def snapshot(self) -> Dict[str, Any]:
        return build_snapshot(self.source, bot_id=self.bot_id)

    async def publish_once(self, session: aiohttp.ClientSession, snapshot: Dict[str, Any]) -> bool:
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
        except (aiohttp.ClientError, asyncio.TimeoutError, Exception) as exc:
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
