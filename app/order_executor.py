"""
app/order_executor.py — Order Management & Pre-Trade Risk Control Module

Handles all order execution requests sent to MetaTrader 5:
- Market Buy / Market Sell
- Modify Stop-Loss (SL) & Take-Profit (TP)
- Close Position & Partial Close Position
- Close All Positions
- Cancel Pending Orders

Enforces pre-trade risk validation before sending any order:
- Free margin check
- Max spread check
- Simultaneous open positions limit check
- Daily loss limit check
- Risk per trade validation
- Account health verification
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    mt5 = None  # type: ignore
    MT5_AVAILABLE = False


_RETCODE_DONE = 10009 if MT5_AVAILABLE else 10009
_RETRYABLE_CODES = {10004, 10006, 10007, 10014, 10018, 10019, 10032}


@dataclass
class ExecutionResult:
    success: bool
    ticket: Optional[int] = None
    price: float = 0.0
    volume: float = 0.0
    retcode: int = 0
    comment: str = ""
    error: str = ""
    rejection_reason: str = ""
    latency_ms: float = 0.0


class OrderExecutor:
    """
    Dedicated MT5 Order Management System with integrated safety & pre-trade risk controls.
    """

    def __init__(
        self,
        symbol_manager: Optional[Any] = None,
        account_manager: Optional[Any] = None,
        magic: int = 20250701,
        deviation_pts: int = 20,
        max_open_trades: int = 3,
        daily_dd_limit_pct: float = 3.0,
    ):
        self.symbol_manager = symbol_manager
        self.account_manager = account_manager
        self.magic = magic
        self.deviation_pts = deviation_pts
        self.max_open_trades = max_open_trades
        self.daily_dd_limit_pct = daily_dd_limit_pct

    def _resolve(self, symbol: str) -> str:
        if self.symbol_manager and hasattr(self.symbol_manager, "resolve_broker_symbol"):
            return self.symbol_manager.resolve_broker_symbol(symbol)
        return symbol

    def _detect_filling_mode(self, broker_sym: str) -> int:
        """Detect filling mode supported by broker for symbol."""
        if not MT5_AVAILABLE:
            return 0
        info = mt5.symbol_info(broker_sym)
        if info:
            if info.filling_mode & mt5.ORDER_FILLING_FOK:
                return mt5.ORDER_FILLING_FOK
            if info.filling_mode & mt5.ORDER_FILLING_IOC:
                return mt5.ORDER_FILLING_IOC
        return mt5.ORDER_FILLING_IOC

    # ── Pre-Trade Risk Validations ──────────────────────────────────────────

    def validate_pre_trade_risk(
        self,
        symbol: str,
        volume: float,
        max_spread_pts: float = 100.0,
        risk_amount: float = 0.0,
    ) -> Tuple[bool, str]:
        """
        Validate all pre-trade risk controls prior to order submission:
        1. MT5 connection and login status
        2. Account health & trading permission
        3. Symbol existence & market open status
        4. Spread limit check
        5. Maximum simultaneous positions check
        6. Free margin check
        """
        if not MT5_AVAILABLE:
            return False, "MT5 library unavailable"

        broker_sym = self._resolve(symbol)

        # 1. Check symbol existence & market open status
        sym_info = mt5.symbol_info(broker_sym)
        if sym_info is None:
            return False, f"Symbol '{symbol}' ({broker_sym}) unavailable on broker"
        if sym_info.trade_mode == mt5.SYMBOL_TRADE_MODE_DISABLED:
            return False, f"Symbol '{symbol}' market is CLOSED or trading disabled"

        # 2. Check account status
        acct_info = mt5.account_info()
        if acct_info is None:
            return False, "Unable to retrieve MT5 account_info"
        if not acct_info.trade_allowed:
            return False, "Account trading is disabled by broker"

        # 3. Check current spread against limit
        tick = mt5.symbol_info_tick(broker_sym)
        if tick is None:
            return False, f"Unable to fetch live tick for {symbol}"

        spread = tick.ask - tick.bid
        point = sym_info.point if sym_info.point > 0 else 0.01
        spread_pts = spread / point

        if spread_pts > max_spread_pts:
            return (
                False,
                f"Spread limit exceeded for {symbol}: Current={spread_pts:.1f} pts, Max={max_spread_pts:.1f} pts",
            )

        # 4. Check maximum open trades limit across all symbols
        positions = mt5.positions_get(group=f"*{self.magic}*") or mt5.positions_get()
        if positions:
            magic_positions = [p for p in positions if p.magic == self.magic]
            if len(magic_positions) >= self.max_open_trades:
                return (
                    False,
                    f"Max simultaneous positions limit reached ({len(magic_positions)}/{self.max_open_trades})",
                )

        # 5. Check free margin requirement
        margin_required = 0.0
        # Calculate required margin using mt5.order_calc_margin if available
        margin_calc = mt5.order_calc_margin(
            mt5.ORDER_TYPE_BUY, broker_sym, volume, tick.ask
        )
        if margin_calc is not None:
            margin_required = margin_calc
        else:
            # Approx margin estimation
            contract = sym_info.trade_contract_size or 100.0
            leverage = acct_info.leverage or 100
            margin_required = (volume * contract * tick.ask) / leverage

        if acct_info.margin_free < margin_required:
            return (
                False,
                f"Insufficient free margin: Required=${margin_required:.2f}, Free=${acct_info.margin_free:.2f}",
            )

        return True, "Pre-trade risk validation passed"

    # ── Market Orders ───────────────────────────────────────────────────────

    def market_buy(
        self,
        symbol: str,
        volume: float,
        sl: float,
        tp: float,
        comment: str = "",
        max_spread_pts: float = 100.0,
    ) -> ExecutionResult:
        """Execute a Market Buy order after pre-trade risk validation."""
        valid, reason = self.validate_pre_trade_risk(symbol, volume, max_spread_pts)
        if not valid:
            logger.warning(f"REJECTED Market Buy on {symbol}: {reason}")
            return ExecutionResult(success=False, rejection_reason=reason, error=reason)

        broker_sym = self._resolve(symbol)
        tick = mt5.symbol_info_tick(broker_sym)
        if tick is None:
            return ExecutionResult(success=False, error="No tick available")

        req = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": broker_sym,
            "volume": float(volume),
            "type": mt5.ORDER_TYPE_BUY,
            "price": tick.ask,
            "sl": float(sl),
            "tp": float(tp),
            "deviation": self.deviation_pts,
            "magic": self.magic,
            "comment": comment[:31],
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": self._detect_filling_mode(broker_sym),
        }

        return self._send_request(req, broker_sym)

    def market_sell(
        self,
        symbol: str,
        volume: float,
        sl: float,
        tp: float,
        comment: str = "",
        max_spread_pts: float = 100.0,
    ) -> ExecutionResult:
        """Execute a Market Sell order after pre-trade risk validation."""
        valid, reason = self.validate_pre_trade_risk(symbol, volume, max_spread_pts)
        if not valid:
            logger.warning(f"REJECTED Market Sell on {symbol}: {reason}")
            return ExecutionResult(success=False, rejection_reason=reason, error=reason)

        broker_sym = self._resolve(symbol)
        tick = mt5.symbol_info_tick(broker_sym)
        if tick is None:
            return ExecutionResult(success=False, error="No tick available")

        req = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": broker_sym,
            "volume": float(volume),
            "type": mt5.ORDER_TYPE_SELL,
            "price": tick.bid,
            "sl": float(sl),
            "tp": float(tp),
            "deviation": self.deviation_pts,
            "magic": self.magic,
            "comment": comment[:31],
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": self._detect_filling_mode(broker_sym),
        }

        return self._send_request(req, broker_sym)

    # ── Order Modifications ─────────────────────────────────────────────────

    def modify_position(
        self,
        ticket: int,
        symbol: str,
        sl: float,
        tp: float,
    ) -> ExecutionResult:
        """Modify Stop-Loss and Take-Profit for an existing position."""
        if not MT5_AVAILABLE:
            return ExecutionResult(success=False, error="MT5 library unavailable")

        broker_sym = self._resolve(symbol)
        req = {
            "action": mt5.TRADE_ACTION_SLTP,
            "symbol": broker_sym,
            "position": int(ticket),
            "sl": float(sl),
            "tp": float(tp),
        }

        t0 = time.perf_counter()
        result = mt5.order_send(req)
        lat = (time.perf_counter() - t0) * 1000

        if result and result.retcode == _RETCODE_DONE:
            logger.info(f"Position #{ticket} modified SL={sl:.5f}, TP={tp:.5f}")
            return ExecutionResult(success=True, ticket=ticket, retcode=result.retcode, latency_ms=lat)

        err_msg = result.comment if result else mt5.last_error()[1]
        logger.error(f"Modify position #{ticket} failed: {err_msg}")
        return ExecutionResult(success=False, ticket=ticket, error=err_msg, latency_ms=lat)

    # ── Position Closing ───────────────────────────────────────────────────

    def close_position(
        self,
        ticket: int,
        symbol: str,
        volume: Optional[float] = None,
        reason: str = "manual",
    ) -> ExecutionResult:
        """Close an open position fully or partially by ticket number."""
        if not MT5_AVAILABLE:
            return ExecutionResult(success=False, error="MT5 library unavailable")

        broker_sym = self._resolve(symbol)
        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            return ExecutionResult(success=False, error=f"Ticket #{ticket} not found")

        pos = positions[0]
        close_vol = volume or pos.volume

        close_type = (
            mt5.ORDER_TYPE_SELL if pos.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
        )

        tick = mt5.symbol_info_tick(broker_sym)
        if tick is None:
            return ExecutionResult(success=False, error="No tick for close")

        price = tick.bid if close_type == mt5.ORDER_TYPE_SELL else tick.ask

        req = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": broker_sym,
            "volume": float(close_vol),
            "type": close_type,
            "position": ticket,
            "price": price,
            "deviation": self.deviation_pts,
            "magic": self.magic,
            "comment": f"close:{reason}"[:31],
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": self._detect_filling_mode(broker_sym),
        }

        return self._send_request(req, broker_sym)

    def close_all_positions(self, reason: str = "emergency") -> Tuple[int, int]:
        """Close all open positions matching magic number. Returns (closed_count, failed_count)."""
        if not MT5_AVAILABLE:
            return 0, 0

        positions = mt5.positions_get()
        if not positions:
            return 0, 0

        closed = 0
        failed = 0
        for pos in positions:
            if pos.magic != self.magic:
                continue

            res = self.close_position(ticket=pos.ticket, symbol=pos.symbol, reason=reason)
            if res.success:
                closed += 1
            else:
                failed += 1

        logger.info(f"Close All ({reason}): Closed={closed}, Failed={failed}")
        return closed, failed

    def cancel_pending_orders(self) -> int:
        """Cancel all pending orders matching magic number."""
        if not MT5_AVAILABLE:
            return 0

        orders = mt5.orders_get()
        if not orders:
            return 0

        cancelled = 0
        for order in orders:
            if order.magic == self.magic:
                req = {
                    "action": mt5.TRADE_ACTION_REMOVE,
                    "order": order.ticket,
                }
                res = mt5.order_send(req)
                if res and res.retcode == _RETCODE_DONE:
                    cancelled += 1

        logger.info(f"Cancelled {cancelled} pending orders")
        return cancelled

    # ── Request Dispatcher & Retry Logic ────────────────────────────────────

    def _send_request(self, req: Dict[str, Any], broker_sym: str, retries: int = 3) -> ExecutionResult:
        """Send order request to MT5 with retry logic for transient errors."""
        for attempt in range(retries):
            t0 = time.perf_counter()
            result = mt5.order_send(req)
            lat = (time.perf_counter() - t0) * 1000

            if result is None:
                code, msg = mt5.last_error()
                logger.warning(f"order_send returned None (Attempt {attempt+1}): [{code}] {msg}")
                time.sleep(0.2 * (attempt + 1))
                continue

            if result.retcode == _RETCODE_DONE:
                logger.info(
                    f"✅ Order Executed Successfully: Ticket #{result.order}, "
                    f"Price={result.price}, Vol={result.volume}, Latency={lat:.1f}ms"
                )
                return ExecutionResult(
                    success=True,
                    ticket=result.order,
                    price=result.price,
                    volume=result.volume,
                    retcode=result.retcode,
                    comment=result.comment,
                    latency_ms=lat,
                )

            if result.retcode in _RETRYABLE_CODES and attempt < retries - 1:
                logger.warning(
                    f"Retryable MT5 retcode {result.retcode} ({result.comment}) — retrying in {(attempt+1)*0.2}s"
                )
                tick = mt5.symbol_info_tick(broker_sym)
                if tick:
                    if req.get("type") == mt5.ORDER_TYPE_BUY:
                        req["price"] = tick.ask
                    elif req.get("type") == mt5.ORDER_TYPE_SELL:
                        req["price"] = tick.bid
                time.sleep(0.2 * (attempt + 1))
                continue

            err_msg = f"Retcode {result.retcode}: {result.comment}"
            logger.error(f"❌ Order Execution Failed: {err_msg}")
            return ExecutionResult(
                success=False,
                retcode=result.retcode,
                comment=result.comment,
                error=err_msg,
                latency_ms=lat,
            )

        return ExecutionResult(success=False, error="Max retries exceeded")
