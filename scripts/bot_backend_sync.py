"""
scripts/bot_backend_sync.py — Outbound MT5 Bot to Web Backend Sync Service

Runs on the Windows Trading Bot PC.
Periodically queries live MT5 account sessions (balance, equity, margin, open positions, recent closed deals)
and sends an authenticated HMAC-SHA256 signed HTTPS payload to the Central Web Backend API.

Safety Guarantee:
- Outbound push only. No inbound ports required on the Trading PC.
- Credentials (MT5 passwords) are NEVER sent in the payload.
- All requests are signed with HMAC-SHA256 and include an epoch timestamp window to prevent replay attacks.
"""

from __future__ import annotations

import hmac
import hashlib
import json
import logging
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

# Ensure workspace root is in python path
sys.path.insert(0, os.getcwd())

from app.multi_account.account_registry import AccountRegistry
from app.multi_account.mt5_session import MT5DirectSession

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] [BOT_SYNC] %(message)s'
)
logger = logging.getLogger("bot_backend_sync")

BACKEND_API_URL = os.getenv("BACKEND_API_URL", "http://localhost:4000")
BOT_HMAC_SECRET = os.getenv("BOT_HMAC_SECRET", "dev_bot_hmac_secret_64bytes_minimum_key_for_pkgtraders!")
BOT_API_KEY = os.getenv("BOT_API_KEY", "pkg_bot_live_api_key_v1")
SYNC_INTERVAL_SECONDS = int(os.getenv("BOT_SYNC_INTERVAL_SECONDS", "30"))


def generate_hmac_signature(payload_json: str, timestamp_str: str) -> str:
    """Generate HMAC-SHA256 signature for body payload + timestamp."""
    msg = f"{timestamp_str}.{payload_json}".encode('utf-8')
    return hmac.new(BOT_HMAC_SECRET.encode('utf-8'), msg, hashlib.sha256).hexdigest()


def collect_bot_snapshot(registry: AccountRegistry) -> Dict[str, Any]:
    """Collect current snapshot of all active MT5 accounts, open positions, and recent trades."""
    accounts_snapshot = []
    
    for acc in registry.get_enabled():
        sess = MT5DirectSession(acc)
        if sess.connect():
            info = sess.get_account_info() or {}
            
            # Open positions
            positions = sess.get_positions() or []
            pos_list = []
            for p in positions:
                pos_list.append({
                    "position_ticket": int(getattr(p, 'ticket', 0)),
                    "symbol": str(getattr(p, 'symbol', '')),
                    "direction": "BUY" if getattr(p, 'type', 0) == 0 else "SELL",
                    "volume": float(getattr(p, 'volume', 0.0)),
                    "entry_price": float(getattr(p, 'price_open', 0.0)),
                    "current_price": float(getattr(p, 'price_current', getattr(p, 'price_open', 0.0))),
                    "stop_loss": float(getattr(p, 'sl', 0.0)),
                    "take_profit": float(getattr(p, 'tp', 0.0)),
                    "unrealized_pnl": float(getattr(p, 'profit', 0.0)),
                    "opened_at": datetime.fromtimestamp(getattr(p, 'time', time.time()), tz=timezone.utc).isoformat()
                })
                
            # Recent closed trades via MT5
            recent_trades = []
            try:
                import MetaTrader5 as mt5
                deals = mt5.history_deals_get(datetime.now() - timedelta(days=7), datetime.now())
                if deals:
                    for d in deals:
                        if d.magic == acc.magic_number or acc.magic_number == 0:
                            if d.entry in (0, 1): # IN / OUT deals
                                recent_trades.append({
                                    "deal_ticket": int(d.ticket),
                                    "order_ticket": int(d.order),
                                    "symbol": str(d.symbol),
                                    "direction": "BUY" if d.type == 0 else "SELL",
                                    "volume": float(d.volume),
                                    "entry_price": float(d.price),
                                    "realized_pnl": float(d.profit),
                                    "commission": float(d.commission),
                                    "swap": float(d.swap),
                                    "executed_at": datetime.fromtimestamp(d.time, tz=timezone.utc).isoformat(),
                                    "comment": str(d.comment)
                                })
            except Exception as e:
                logger.warning(f"Error fetching MT5 deals for account #{acc.login}: {e}")

            accounts_snapshot.append({
                "account_id": acc.account_id,
                "mt5_login": int(acc.login),
                "server": str(acc.server),
                "magic_number": int(acc.magic_number),
                "balance": float(info.get('balance', 0.0)),
                "equity": float(info.get('equity', 0.0)),
                "margin": float(info.get('margin', 0.0)),
                "free_margin": float(info.get('free_margin', 0.0)),
                "margin_level": float(info.get('margin_level', 0.0)),
                "open_positions": pos_list,
                "recent_trades": recent_trades
            })
            
            sess.disconnect()

    return {
        "instance_name": os.getenv("BOT_INSTANCE_NAME", "TRADING_BOT_PC_01"),
        "pc_hostname": os.getenv("COMPUTERNAME", "WINDOWSPC"),
        "bot_version": "2.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "accounts": accounts_snapshot
    }


def send_snapshot_to_backend(snapshot: Dict[str, Any]) -> bool:
    """Send HMAC signed snapshot payload to Web Backend."""
    payload_json = json.dumps(snapshot, sort_keys=True)
    timestamp_str = str(int(time.time()))
    signature = generate_hmac_signature(payload_json, timestamp_str)
    
    url = f"{BACKEND_API_URL.rstrip('/')}/api/v1/bot/sync"
    headers = {
        "Content-Type": "application/json",
        "X-Bot-Api-Key": BOT_API_KEY,
        "X-Bot-Timestamp": timestamp_str,
        "X-Bot-Signature": signature
    }
    
    req = urllib.request.Request(
        url,
        data=payload_json.encode('utf-8'),
        headers=headers,
        method="POST"
    )
    
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status in (200, 201):
                logger.info(f"Successfully pushed telemetry snapshot ({len(snapshot['accounts'])} accounts) to backend.")
                return True
            else:
                logger.error(f"Backend returned HTTP {resp.status}")
                return False
    except urllib.error.HTTPError as e:
        logger.error(f"HTTP Error pushing to backend: {e.code} - {e.read().decode('utf-8', 'ignore')}")
        return False
    except Exception as e:
        logger.warning(f"Backend sync connection failed: {e}")
        return False


def main_loop():
    logger.info(f"Starting Bot Outbound Sync Worker -> Backend ({BACKEND_API_URL})")
    config_path = os.path.join(os.getcwd(), 'accounts.json')
    registry = AccountRegistry()
    registry.load_from_file(config_path)
    
    snapshot = collect_bot_snapshot(registry)
    logger.info(f"Snapshot prepared for {len(snapshot['accounts'])} accounts: {[a['mt5_login'] for a in snapshot['accounts']]}")
    send_snapshot_to_backend(snapshot)


if __name__ == '__main__':
    main_loop()
