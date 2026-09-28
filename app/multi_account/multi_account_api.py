"""
app/multi_account/multi_account_api.py — Multi-Account Fleet Management API Endpoints

Provides RESTful FastAPI endpoints for inspecting and controlling multiple MT5 accounts:
- GET  /api/accounts                   -> List all registered accounts with telemetry
- GET  /api/accounts/summary           -> Fleet-level aggregated metrics
- GET  /api/accounts/{account_id}      -> Detailed account context & state
- POST /api/accounts/{account_id}/toggle -> Toggle account or trading enabled/disabled
- POST /api/accounts/{account_id}/close-all -> Emergency close all positions for one account
- POST /api/accounts/emergency-stop    -> Trigger global emergency kill-switch
- POST /api/accounts/emergency-stop/reset -> Reset global emergency kill-switch
- POST /api/accounts/toggle-bot        -> Toggle global bot trading enabled/disabled
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel

from app.multi_account.account_context import AccountStatus
from app.multi_account.account_manager import MT5AccountManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/accounts", tags=["Multi-Account Fleet"])

# Module-level reference to the active MT5AccountManager
_manager_instance: Optional[MT5AccountManager] = None


def set_api_account_manager(manager: MT5AccountManager) -> None:
    """Inject the active MT5AccountManager singleton into the API router."""
    global _manager_instance
    _manager_instance = manager


def get_account_manager() -> MT5AccountManager:
    """Retrieve injected account manager or auto-initialize from accounts.json / env."""
    global _manager_instance
    if _manager_instance is None:
        try:
            import os
            from app.multi_account.account_registry import AccountRegistry
            reg = AccountRegistry()
            accounts_file = os.getenv("ACCOUNTS_CONFIG_PATH", "accounts.json")
            loaded = 0
            if os.path.exists(accounts_file):
                try:
                    loaded = reg.load_from_file(accounts_file)
                except Exception as ex:
                    logger.warning(f"Error loading {accounts_file}: {ex}")
            if loaded == 0:
                reg.load_default_from_env()
            mgr = MT5AccountManager(registry=reg)
            for cfg in reg.get_all():
                mgr.add_account(cfg)
            _manager_instance = mgr
            logger.info(f"[API] Auto-initialized AccountManager with {len(reg)} accounts")
        except Exception as e:
            logger.error(f"[API] Failed to auto-initialize AccountManager: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Multi-account manager is not initialized: {e}",
            )
    return _manager_instance



# ── Schemas ───────────────────────────────────────────────────────────────────

class ToggleRequest(BaseModel):
    trading_only: bool = False
    enabled: Optional[bool] = None


class EmergencyStopRequest(BaseModel):
    close_positions: bool = False
    reason: str = "Operator manual emergency stop"


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("", response_model=List[Dict[str, Any]])
async def list_accounts():
    """
    List all registered accounts with current operational status and risk metrics.
    All sensitive credentials (passwords, tokens) are strictly masked.
    """
    mgr = get_account_manager()
    accounts = []
    for ctx in mgr.get_all_contexts():
        accounts.append(ctx.summary())
    return accounts


@router.get("/summary")
async def fleet_summary():
    """
    Return high-level aggregated fleet metrics:
    - total equity across all accounts
    - total today P/L
    - count of connected/trading/disabled/error accounts
    - total open positions fleet-wide
    - emergency stop and bot enabled flags
    """
    mgr = get_account_manager()
    return mgr.get_telemetry()


@router.get("/{account_id}")
async def get_account_details(account_id: str):
    """
    Fetch comprehensive diagnostic details for a specific account,
    including open positions, risk states, and execution statistics.
    """
    mgr = get_account_manager()
    ctx = mgr.get_account(account_id)
    if not ctx:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Account '{account_id}' not found.",
        )
    
    summary = ctx.summary()
    with ctx._lock:
        summary["positions"] = list(ctx.exec_state.open_positions.values())
        summary["processed_signals_count"] = len(ctx.exec_state.processed_signals)
        summary["reconnect_attempts"] = ctx.exec_state.reconnect_attempts
        summary["last_error"] = ctx.exec_state.last_error
        summary["last_rejection_reason"] = ctx.exec_state.last_rejection_reason

    return summary


@router.post("/{account_id}/toggle")
async def toggle_account(account_id: str, req: ToggleRequest = ToggleRequest()):
    """
    Toggle administrative or trading enablement for a specific account.
    - If `trading_only=True`: toggles `trading_enabled` (orders blocked, connection stays up).
    - If `trading_only=False`: toggles overall `enabled` state.
    """
    mgr = get_account_manager()
    ctx = mgr.get_account(account_id)
    if not ctx:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Account '{account_id}' not found.",
        )

    with ctx._lock:
        if req.trading_only:
            new_val = not ctx.config.trading_enabled if req.enabled is None else req.enabled
            ctx.config.trading_enabled = new_val
            target_field = "trading_enabled"
        else:
            new_val = not ctx.config.enabled if req.enabled is None else req.enabled
            ctx.config.enabled = new_val
            target_field = "enabled"
            if not new_val:
                ctx.status = AccountStatus.DISABLED

    logger.info(f"[{account_id}] Admin toggled {target_field} -> {new_val}")
    return {
        "account_id": account_id,
        "field": target_field,
        "new_value": new_val,
        "status": ctx.status.value,
    }


@router.post("/{account_id}/close-all")
async def close_all_account_positions(
    account_id: str, reason: str = Query("Manual API operator close")
):
    """
    Emergency close all open positions on a single account without affecting others.
    """
    mgr = get_account_manager()
    ctx = mgr.get_account(account_id)
    if not ctx:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Account '{account_id}' not found.",
        )

    if not ctx.session:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Account '{account_id}' has no active session.",
        )

    closed_count = ctx.session.close_all(reason=reason)
    with ctx._lock:
        ctx.exec_state.open_positions.clear()

    logger.warning(f"[{account_id}] Closed {closed_count} positions via API request: {reason}")
    return {
        "account_id": account_id,
        "closed_positions_count": closed_count,
        "reason": reason,
    }


@router.post("/emergency-stop")
async def trigger_emergency_stop(req: EmergencyStopRequest = EmergencyStopRequest()):
    """
    Activate global emergency kill-switch.
    Halts all signal fan-out instantly across the entire fleet.
    If `close_positions=True`, simultaneously closes all open trades across all accounts.
    """
    mgr = get_account_manager()
    mgr.global_emergency_stop = True
    logger.critical(f"[API] GLOBAL EMERGENCY STOP ACTIVATED: {req.reason}")

    closed_summary = {}
    if req.close_positions:
        closed_summary = await mgr.emergency_close_all(reason=req.reason)

    return {
        "global_emergency_stop": True,
        "positions_closed": req.close_positions,
        "closed_summary": closed_summary,
        "reason": req.reason,
    }


@router.post("/emergency-stop/reset")
async def reset_emergency_stop():
    """
    Reset global emergency kill-switch, allowing signal execution to resume.
    """
    mgr = get_account_manager()
    mgr.global_emergency_stop = False
    logger.info("[API] Global emergency stop reset by operator")
    return {
        "global_emergency_stop": False,
        "message": "Emergency stop cleared. Signal fan-out resumed.",
    }


@router.post("/toggle-bot")
async def toggle_bot_trading(enabled: Optional[bool] = None):
    """
    Toggle global bot trading enable flag (`bot_enabled`).
    """
    mgr = get_account_manager()
    mgr.bot_enabled = not mgr.bot_enabled if enabled is None else enabled
    logger.info(f"[API] Bot trading enabled set to: {mgr.bot_enabled}")
    return {
        "bot_enabled": mgr.bot_enabled,
        "message": f"Fleet trading {'enabled' if mgr.bot_enabled else 'paused'}.",
    }
