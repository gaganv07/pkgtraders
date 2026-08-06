"""
app/risk_manager.py — Universal Risk Management Engine

Enforces:
  - Dynamic balance-based position sizing (compounding)
      lot = RiskAmount / (SL_points × tick_value)
      Recalculated fresh from the live account balance before every trade.
  - Daily / weekly / account drawdown limits (3 / 6 / 10%)
  - Max simultaneous trades (3 — multi-symbol)
  - Max total open risk exposure (3%)
  - Circuit breaker on loss streak or exec failures
  - Cooldown period after losses
  - Weekly automatic reset
  - Consecutive loss protection

Public API
----------
calculate_lot_size(...)
    Pure, stateless function — the SINGLE canonical sizing implementation.
    Imported and used by both TradeEngine (live) and backtesting scripts.
    Delegates internally to PositionSizer.size() for CSV logging.
    No external dependencies; safe to call without MT5.

RiskManager.calculate_volume(...)
    Thin wrapper around calculate_lot_size() that reads risk_pct from
    settings automatically.  Used by the live TradeEngine.

RiskManager.approve_with_exposure(risk_pct)
    Gate check that also validates total open risk stays ≤ max_risk_exposure.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional, Tuple

from app.config import settings

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# Correlation groups — used by the correlation cap feature
# Symbols that react similarly to USD macro events must share a group.
# Prevents cascade stop-outs when a single macro catalyst hits multiple positions.
# ═══════════════════════════════════════════════════════════════════════════════

# Correlation groups (forensics: USDJPY + XAUUSD caused 85.7% of all losses)
_CORR_GROUPS: Dict[str, set] = {
    "usd_sensitive": {"USDJPY", "XAUUSD", "EURUSD", "GBPUSD", "XAUEUR"},
    "equity":        {"NAS100", "US30", "GER40", "UK100"},
    "crypto":        {"BTCUSD", "ETHUSD", "LTCUSD"},
}


def _corr_group_for(symbol: str) -> Optional[str]:
    """Return the correlation group name for a symbol, or None if ungrouped."""
    for group, members in _CORR_GROUPS.items():
        # Match with broker suffix variants (e.g. XAUUSDm, USDJPY+)
        clean = symbol.rstrip('m+.a').upper()
        for m in members:
            if clean.startswith(m) or m.startswith(clean):
                return group
    return None


# ══════════════════════════════════════════════════════════════════════════════
# Canonical lot-sizing function (backward-compatible wrapper)
# ══════════════════════════════════════════════════════════════════════════════

def calculate_lot_size(
    balance:       float,
    entry_price:   float,
    stop_loss:     float,
    risk_pct:      float,
    contract_size: float = 100.0,
    vol_min:       float = 0.01,
    vol_max:       float = 50.0,
    vol_step:      float = 0.01,
    tick_size:     float = 0.01,
    tick_value:    float = 0.01,
    tp_price:      Optional[float] = None,
    symbol:        str   = "UNKNOWN",
    strategy:      str   = "backtest",
    write_csv:     bool  = False,   # Off by default in backtest to avoid noise
) -> Tuple[float, float]:
    """
    Single canonical position-sizing function.

    Used by both the live TradeEngine and all backtesting scripts.
    Delegates to PositionSizer for the core math and optional CSV logging.

    Returns
    -------
    (final_lot, expected_loss_usd)
    Returns (0.0, 0.0) on invalid inputs.
    """
    from app.position_sizer import PositionSizer, BrokerSpec
    spec = BrokerSpec(
        symbol=symbol,
        vol_min=vol_min, vol_max=vol_max, vol_step=vol_step,
        tick_size=tick_size, tick_value=tick_value,
        contract_size=contract_size,
    )
    result = PositionSizer.size(
        balance=balance, entry=entry_price, stop_loss=stop_loss,
        spec=spec, risk_pct=risk_pct, tp_price=tp_price,
        strategy=strategy, symbol=symbol, write_csv=write_csv,
    )
    return result.final_lot, result.expected_loss


# ══════════════════════════════════════════════════════════════════════════════
# Drawdown state
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class DrawdownState:
    account_start:  float = 0.0
    daily_start:    float = 0.0
    weekly_start:   float = 0.0
    peak_equity:    float = 0.0
    current_equity: float = 0.0

    daily_dd_pct:   float = 0.0
    weekly_dd_pct:  float = 0.0
    account_dd_pct: float = 0.0

    daily_hit:      bool  = False
    weekly_hit:     bool  = False
    account_hit:    bool  = False

    consecutive_losses:  int   = 0
    daily_trades:        int   = 0
    daily_pnl:           float = 0.0
    total_pnl:           float = 0.0

    # Open risk tracking (sum of risk_pct of all open positions)
    open_risk_pct:       float = 0.0

    _day_key:  str = ""
    _week_key: str = ""

    @property
    def any_hit(self) -> bool:
        return self.daily_hit or self.weekly_hit or self.account_hit


# ══════════════════════════════════════════════════════════════════════════════
# Risk Manager
# ══════════════════════════════════════════════════════════════════════════════

class RiskManager:
    """
    Universal trade approval gate and real-time drawdown monitor.

    Works for every symbol and every strategy — multi-asset capable.
    Must call initialize() once on startup with current balance.

    Position sizing is delegated to calculate_lot_size() / PositionSizer
    so the identical algorithm runs in live and backtest modes.
    """

    def __init__(self):
        self._cfg = settings.risk
        self._dd  = DrawdownState()
        self._ready            = False
        self._circuit_broken   = False
        self._exec_fails       = 0
        self._open_count       = 0
        self._last_loss_time:  Optional[datetime] = None
        self._cooldown_until:  Optional[datetime] = None
        # Tracks symbol of every open position for correlation-cap enforcement
        self._open_symbols:    list = []   # list[str] — one entry per open trade

    # ── Init & resets ──────────────────────────────────────────────────────────

    def initialize(self, balance: float) -> None:
        today = self._day()
        week  = self._week()
        self._dd.account_start  = balance
        self._dd.daily_start    = balance
        self._dd.weekly_start   = balance
        self._dd.peak_equity    = balance
        self._dd.current_equity = balance
        self._dd._day_key  = today
        self._dd._week_key = week
        self._ready = True
        logger.info(f"RiskManager initialized: ${balance:,.2f} | MaxTrades={self._cfg.max_open_trades} | MaxExposure={self._cfg.max_risk_exposure}%")

    def _day(self)  -> str: return datetime.now(timezone.utc).strftime("%Y-%m-%d")
    def _week(self) -> str:
        n = datetime.now(timezone.utc)
        return f"{n.year}-W{n.strftime('%W')}"

    def _maybe_reset(self, balance: float) -> None:
        today = self._day()
        week  = self._week()

        if self._dd._day_key != today:
            logger.info(f"Daily reset @ ${balance:,.2f}")
            self._dd.daily_start  = balance
            self._dd.daily_trades = 0
            self._dd.daily_pnl    = 0.0
            self._dd.daily_hit    = False
            self._dd._day_key     = today
            # Auto-reset circuit breaker each day
            self._circuit_broken = False
            self._exec_fails     = 0
            self._dd.consecutive_losses = 0
            self._cooldown_until = None

        if self._dd._week_key != week:
            logger.info(f"Weekly reset @ ${balance:,.2f}")
            self._dd.weekly_start = balance
            self._dd.weekly_hit   = False
            self._dd._week_key    = week

    # ── Account update ────────────────────────────────────────────────────────

    def update_equity(self, balance: float, equity: float) -> DrawdownState:
        if not self._ready:
            self.initialize(balance)
            return self._dd

        self._maybe_reset(balance)
        self._dd.current_equity = equity
        self._dd.peak_equity    = max(self._dd.peak_equity, equity)

        if self._dd.daily_start > 0:
            self._dd.daily_dd_pct = (
                (self._dd.daily_start - equity) / self._dd.daily_start * 100
            )
        if self._dd.weekly_start > 0:
            self._dd.weekly_dd_pct = (
                (self._dd.weekly_start - equity) / self._dd.weekly_start * 100
            )
        if self._dd.account_start > 0:
            self._dd.account_dd_pct = (
                (self._dd.account_start - equity) / self._dd.account_start * 100
            )

        self._dd.daily_hit   = self._dd.daily_dd_pct   >= self._cfg.daily_dd_limit
        self._dd.weekly_hit  = self._dd.weekly_dd_pct  >= self._cfg.weekly_dd_limit
        self._dd.account_hit = self._dd.account_dd_pct >= self._cfg.account_dd_limit

        if self._dd.daily_hit:
            logger.warning(f"Daily DD limit: {self._dd.daily_dd_pct:.2f}%")
        if self._dd.account_hit:
            logger.critical(f"Account DD limit: {self._dd.account_dd_pct:.2f}%")

        return self._dd

    # ── Position sizing ───────────────────────────────────────────────────────

    def calculate_volume(
        self,
        balance:       float,
        entry:         float,
        stop_loss:     float,
        contract_size: float = 100.0,
        vol_min:       float = 0.01,
        vol_max:       float = 50.0,
        vol_step:      float = 0.01,
        tick_size:     float = 0.01,
        tick_value:    float = 0.01,
        tp_price:      Optional[float] = None,
        symbol:        str   = "UNKNOWN",
        strategy:      str   = "live",
        write_csv:     bool  = True,
    ) -> Tuple[float, float]:
        """
        Live-trading wrapper: reads risk_pct from settings,
        delegates to calculate_lot_size(), auto-writes to CSV.
        Returns (volume, expected_loss_usd).
        """
        # Apply loss-streak risk reduction if configured
        risk_pct = self._cfg.risk_per_trade_pct
        if (self._cfg.loss_streak_reduce_risk
                and self._dd.consecutive_losses >= self._cfg.loss_streak_threshold):
            risk_pct *= self._cfg.loss_streak_risk_factor
            logger.info(
                f"[RISK] Loss streak={self._dd.consecutive_losses} — "
                f"risk reduced to {risk_pct:.2f}%"
            )

        return calculate_lot_size(
            balance=balance,
            entry_price=entry,
            stop_loss=stop_loss,
            risk_pct=risk_pct,
            contract_size=contract_size,
            vol_min=vol_min,
            vol_max=vol_max,
            vol_step=vol_step,
            tick_size=tick_size,
            tick_value=tick_value,
            tp_price=tp_price,
            symbol=symbol,
            strategy=strategy,
            write_csv=write_csv,
        )

    # ── Trade approval ────────────────────────────────────────────────────────

    def approve(self) -> Tuple[bool, str]:
        """
        Gate check before entering any trade.
        Returns (approved, reason_string).
        Does NOT check risk exposure — use approve_with_exposure() for that.
        """
        if not self._ready:
            return False, "Not initialized"

        if self._circuit_broken:
            return False, "Circuit breaker active"

        # Cooldown check
        if self._cooldown_until:
            now = datetime.now(timezone.utc)
            if now < self._cooldown_until:
                remaining = (self._cooldown_until - now).total_seconds() / 60
                return False, f"Cooldown: {remaining:.1f}m remaining"
            else:
                self._cooldown_until = None

        if self._dd.any_hit:
            parts = []
            if self._dd.daily_hit:   parts.append(f"daily {self._dd.daily_dd_pct:.1f}%")
            if self._dd.weekly_hit:  parts.append(f"weekly {self._dd.weekly_dd_pct:.1f}%")
            if self._dd.account_hit: parts.append(f"account {self._dd.account_dd_pct:.1f}%")
            return False, f"DD limit: {', '.join(parts)}"

        if self._open_count >= self._cfg.max_open_trades:
            return False, f"Max trades ({self._cfg.max_open_trades}) open"

        return True, "APPROVED"

    def approve_with_exposure(self, new_risk_pct: float) -> Tuple[bool, str]:
        """
        Gate check that also validates total open risk exposure.

        Parameters
        ----------
        new_risk_pct : Risk percentage of the proposed new trade.

        Returns (approved, reason_string).
        """
        ok, reason = self.approve()
        if not ok:
            return False, reason

        projected = self._dd.open_risk_pct + new_risk_pct
        if projected > self._cfg.max_risk_exposure:
            return False, (
                f"MaxExposure {self._cfg.max_risk_exposure}% exceeded: "
                f"open={self._dd.open_risk_pct:.2f}% + new={new_risk_pct:.2f}% = {projected:.2f}%"
            )

        return True, "APPROVED"

    def approve_with_correlation(
        self, new_symbol: str, new_risk_pct: float = 0.0
    ) -> Tuple[bool, str]:
        """
        Combined gate: runs approve_with_exposure() then checks the
        correlation cap so the same macro event cannot cascade-stop multiple
        open positions simultaneously.

        Parameters
        ----------
        new_symbol  : The symbol about to be traded.
        new_risk_pct: Risk percentage of the proposed trade.

        Returns (approved, reason_string).
        """
        ok, reason = self.approve_with_exposure(new_risk_pct)
        if not ok:
            return False, reason

        cap = self._cfg.max_same_corr_group_trades
        group = _corr_group_for(new_symbol)
        if group:
            open_in_group = sum(
                1 for s in self._open_symbols if _corr_group_for(s) == group
            )
            if open_in_group >= cap:
                return False, (
                    f"CorrCap: {new_symbol} group='{group}' already has "
                    f"{open_in_group}/{cap} open trades"
                )

        return True, "APPROVED"

    # ── Trade lifecycle ─────────────────────────────────────────────

    def on_open(self, risk_pct: float = 0.0, symbol: str = "") -> None:
        """Call when a trade is opened. risk_pct tracks exposure; symbol tracks correlation."""
        self._open_count += 1
        self._dd.open_risk_pct = round(self._dd.open_risk_pct + risk_pct, 4)
        if symbol:
            self._open_symbols.append(symbol)

    def on_close(self, pnl: float, risk_pct: float = 0.0, symbol: str = "") -> None:
        """Call when a trade is closed. Releases risk exposure and correlation slot."""
        self._open_count = max(0, self._open_count - 1)
        self._dd.open_risk_pct = max(0.0, round(self._dd.open_risk_pct - risk_pct, 4))
        if symbol and symbol in self._open_symbols:
            self._open_symbols.remove(symbol)
        self._dd.daily_pnl  += pnl
        self._dd.total_pnl  += pnl
        self._dd.daily_trades += 1

        if pnl > 0:
            self._dd.consecutive_losses = 0
            self._exec_fails = 0
        else:
            self._dd.consecutive_losses += 1
            self._last_loss_time = datetime.now(timezone.utc)
            # Cooldown after each loss
            self._cooldown_until = datetime.now(timezone.utc) + timedelta(
                minutes=self._cfg.cooldown_after_loss_m
            )
            if self._dd.consecutive_losses >= self._cfg.circuit_loss_streak:
                self._circuit_broken = True
                self._cooldown_until = datetime.now(timezone.utc) + timedelta(minutes=30.0)
                logger.warning(
                    f"Circuit breaker: {self._dd.consecutive_losses} consecutive losses (cooldown 30m)"
                )

    def on_exec_failure(self) -> None:
        self._exec_fails += 1
        if self._exec_fails >= self._cfg.circuit_exec_fails:
            self._circuit_broken = True
            self._cooldown_until = datetime.now(timezone.utc) + timedelta(minutes=30.0)
            logger.warning(f"Circuit breaker: {self._exec_fails} exec failures (cooldown 30m)")

    def reset_circuit(self) -> None:
        """Manual operator reset."""
        self._circuit_broken = False
        self._exec_fails = 0
        self._dd.consecutive_losses = 0
        self._cooldown_until = None
        logger.warning("Circuit breaker reset by operator")

    # ── Accessors ─────────────────────────────────────────────────────────────

    @property
    def circuit_broken(self) -> bool:
        if self._circuit_broken and self._cooldown_until and datetime.now(timezone.utc) >= self._cooldown_until:
            self._circuit_broken = False
            self._dd.consecutive_losses = 0
            self._cooldown_until = None
            logger.info("Circuit breaker cooldown expired — trading resumed automatically")
        return self._circuit_broken

    @property
    def open_count(self) -> int:
        return self._open_count

    @property
    def drawdown(self) -> DrawdownState:
        return self._dd

    def in_cooldown(self) -> bool:
        if not self._cooldown_until:
            return False
        return datetime.now(timezone.utc) < self._cooldown_until

    def summary(self) -> Dict:
        dd = self._dd
        return {
            "circuit_broken":     self._circuit_broken,
            "in_cooldown":        self.in_cooldown(),
            "open_trades":        self._open_count,
            "open_risk_pct":      round(dd.open_risk_pct, 2),
            "daily_dd_pct":       round(dd.daily_dd_pct, 2),
            "weekly_dd_pct":      round(dd.weekly_dd_pct, 2),
            "account_dd_pct":     round(dd.account_dd_pct, 2),
            "consecutive_losses": dd.consecutive_losses,
            "daily_trades":       dd.daily_trades,
            "daily_pnl":          round(dd.daily_pnl, 2),
            "total_pnl":          round(dd.total_pnl, 2),
            "any_dd_hit":         dd.any_hit,
        }
