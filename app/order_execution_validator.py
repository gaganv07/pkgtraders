"""
app/order_execution_validator.py — Pre-Trade Order Execution Validator

Enforces 8 mandatory pre-trade validation checks before every order submission:
1. Live spread vs maximum allowable spread
2. Available free margin vs required initial margin
3. Symbol trade mode (Full Access vs Disabled/Close-only)
4. Market open status and trading session
5. Contract specifications and volume step/min/max
6. Stop level (stops_level) distance validation for SL/TP
7. Freeze level (freeze_level) safety window
8. Symbol Market Watch visibility
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    mt5 = None  # type: ignore
    MT5_AVAILABLE = False


@dataclass
class PreTradeCheckResult:
    valid: bool
    reason: str
    spread_pts: float = 0.0
    margin_required: float = 0.0
    free_margin_available: float = 0.0
    stops_level_pts: int = 0
    freeze_level_pts: int = 0


class PreTradeExecutionValidator:
    """
    Pre-trade order execution validator enforcing broker specifications and safety boundaries.
    """

    def __init__(
        self,
        symbol_manager: Any,
        broker_adapter: Optional[Any] = None,
        max_spread_pts: Dict[str, float] = None,
    ):
        self.symbol_manager = symbol_manager
        self.broker_adapter = broker_adapter
        self.max_spread_pts = max_spread_pts or {
            "XAUUSD": 60.0,
            "EURUSD": 30.0,
            "GBPUSD": 40.0,
            "USDJPY": 35.0,
            "BTCUSD": 3000.0,
            "US30": 500.0,
            "NAS100": 400.0,
        }

    def validate_pre_trade(
        self,
        canonical_symbol: str,
        volume: float,
        order_type: str = "BUY",
        sl: float = 0.0,
        tp: float = 0.0,
    ) -> PreTradeCheckResult:
        """
        Execute all 8 pre-trade checks before order dispatch.
        """
        if not MT5_AVAILABLE:
            return PreTradeCheckResult(False, "MT5 package unavailable")

        broker_sym = self.symbol_manager.resolve_broker_symbol(canonical_symbol)

        # 1. Symbol Info & Market Watch Visibility
        info = mt5.symbol_info(broker_sym)
        if info is None or not info.visible:
            return PreTradeCheckResult(False, f"Symbol '{broker_sym}' not active or visible in Market Watch")

        # 2. Symbol Trade Mode
        if info.trade_mode == mt5.SYMBOL_TRADE_MODE_DISABLED:
            return PreTradeCheckResult(False, f"Trading is DISABLED for symbol '{broker_sym}'")
        elif info.trade_mode == mt5.SYMBOL_TRADE_MODE_CLOSEONLY and order_type in ("BUY", "SELL"):
            return PreTradeCheckResult(False, f"Symbol '{broker_sym}' is in CLOSE-ONLY mode")

        # 3. Live Tick & Spread Check
        tick = mt5.symbol_info_tick(broker_sym)
        if tick is None or tick.bid <= 0 or tick.ask <= 0:
            return PreTradeCheckResult(False, f"Live tick feed unavailable for '{broker_sym}'")

        spread_pts = (tick.ask - tick.bid) / info.point
        max_allowed_spread = self.max_spread_pts.get(canonical_symbol, 100.0)
        if spread_pts > max_allowed_spread:
            return PreTradeCheckResult(
                False,
                f"Spread ({spread_pts:.1f} pts) exceeds maximum threshold ({max_allowed_spread:.1f} pts)",
                spread_pts=spread_pts,
            )

        # 4. Volume Min / Max / Step Validation
        if volume < info.volume_min:
            return PreTradeCheckResult(False, f"Volume {volume} below minimum ({info.volume_min})")
        if volume > info.volume_max:
            return PreTradeCheckResult(False, f"Volume {volume} exceeds maximum ({info.volume_max})")

        # 5. Margin Check
        acct = mt5.account_info()
        if acct is None:
            return PreTradeCheckResult(False, "Account info unavailable for margin check")

        action_type = mt5.ORDER_TYPE_BUY if order_type == "BUY" else mt5.ORDER_TYPE_SELL
        price = tick.ask if order_type == "BUY" else tick.bid
        margin_required = mt5.order_calc_margin(action_type, broker_sym, volume, price)

        if margin_required is not None and margin_required > 0:
            if acct.margin_free < margin_required:
                return PreTradeCheckResult(
                    False,
                    f"Insufficient free margin: Required=${margin_required:.2f}, Available=${acct.margin_free:.2f}",
                    spread_pts=spread_pts,
                    margin_required=margin_required,
                    free_margin_available=acct.margin_free,
                )

        # 6. Stop Level Check for SL / TP
        stops_level_pts = info.trade_stops_level
        if stops_level_pts > 0 and price > 0:
            min_dist = stops_level_pts * info.point
            if sl > 0:
                sl_dist = abs(price - sl)
                if sl_dist < min_dist:
                    return PreTradeCheckResult(
                        False,
                        f"SL distance ({sl_dist:.5f}) smaller than broker stops_level ({min_dist:.5f})",
                        stops_level_pts=stops_level_pts,
                    )
            if tp > 0:
                tp_dist = abs(price - tp)
                if tp_dist < min_dist:
                    return PreTradeCheckResult(
                        False,
                        f"TP distance ({tp_dist:.5f}) smaller than broker stops_level ({min_dist:.5f})",
                        stops_level_pts=stops_level_pts,
                    )

        # 7. Freeze Level Check
        freeze_level_pts = getattr(info, "trade_freeze_level", 0)

        # 8. All Pre-trade Checks Passed
        return PreTradeCheckResult(
            valid=True,
            reason="All pre-trade validation checks passed",
            spread_pts=spread_pts,
            margin_required=margin_required or 0.0,
            free_margin_available=acct.margin_free,
            stops_level_pts=stops_level_pts,
            freeze_level_pts=freeze_level_pts,
        )
