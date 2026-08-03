"""
app/performance.py — Live Performance Tracker

Tracks and logs all institutional-grade performance metrics in real-time:

  Balance, Equity, Drawdown
  Win rate, Profit factor
  Sharpe ratio (approximated from trade returns)
  Average R-multiple
  Daily / Weekly / Monthly returns
  Per-symbol breakdown

Metrics are computed from the stream of closed trades and periodically
logged at INFO level and stored in the database.

Design: stateless w.r.t. source of truth — the database owns the
canonical trade records; PerformanceTracker caches a rolling window
for fast in-process calculations without re-querying DB every tick.
"""

from __future__ import annotations

import logging
import math
import statistics
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, date, timezone, timedelta
from typing import Deque, Dict, List, Optional, Tuple

from app.config import settings
from app.trade_engine import ActiveTrade

logger = logging.getLogger(__name__)


# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class TradeSummary:
    """Compact summary of one closed trade — stored in rolling cache."""
    trade_id:   str
    symbol:     str
    direction:  str
    pnl:        float      # realized P&L in USD
    r_multiple: float      # pnl / risk_usd
    close_time: datetime
    quality:    float      # quality score at entry


@dataclass
class PerformanceSnapshot:
    """Full performance snapshot at a point in time."""
    # Account state
    balance:      float = 0.0
    equity:       float = 0.0
    drawdown_pct: float = 0.0    # from peak equity

    # Overall stats
    total_trades:  int   = 0
    winning_trades: int  = 0
    losing_trades:  int  = 0
    win_rate:      float = 0.0   # 0–100 %
    gross_profit:  float = 0.0
    gross_loss:    float = 0.0
    profit_factor: float = 0.0   # |gross_profit| / |gross_loss|
    net_pnl:       float = 0.0

    # Risk-adjusted
    sharpe_approx:  float = 0.0   # simplified Sharpe from trade R-series
    avg_r_multiple: float = 0.0
    max_r:          float = 0.0
    min_r:          float = 0.0

    # Period returns
    daily_return_pct:   float = 0.0
    weekly_return_pct:  float = 0.0
    monthly_return_pct: float = 0.0

    # Peak/trough
    peak_equity:    float = 0.0
    max_drawdown:   float = 0.0   # largest historical drawdown %

    # Per-symbol breakdown
    symbol_stats:   Dict[str, Dict] = field(default_factory=dict)

    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ── PerformanceTracker ────────────────────────────────────────────────────────

class PerformanceTracker:
    """
    Rolling performance analytics engine.

    Usage (from Orchestrator):
        self.perf = PerformanceTracker(initial_balance)
        ...
        self.perf.record_trade(closed_trade)
        snap = self.perf.snapshot(balance, equity)
    """

    _SHARPE_WINDOW = 50   # last N trade R-multiples for Sharpe estimate

    def __init__(self, initial_balance: float = 500.0):
        self._initial_balance  = initial_balance
        self._peak_equity      = initial_balance
        self._max_dd           = 0.0
        self._log_interval     = settings.perf.log_interval_s

        # Rolling trade cache
        self._trades: Deque[TradeSummary] = deque(maxlen=500)

        # Period baseline balances (for return calculations)
        self._day_start_balance:   float = initial_balance
        self._week_start_balance:  float = initial_balance
        self._month_start_balance: float = initial_balance
        self._period_day:   int = datetime.now(timezone.utc).day
        self._period_week:  int = datetime.now(timezone.utc).isocalendar()[1]
        self._period_month: int = datetime.now(timezone.utc).month

        # Per-symbol stats
        self._sym_wins:  Dict[str, int]   = defaultdict(int)
        self._sym_loss:  Dict[str, int]   = defaultdict(int)
        self._sym_pnl:   Dict[str, float] = defaultdict(float)

        self._last_snap: Optional[PerformanceSnapshot] = None
        self._last_log:  float = 0.0

        logger.info(f"PerformanceTracker initialized — starting balance=${initial_balance:,.2f}")

    # ── Trade recording ───────────────────────────────────────────────────────

    def record_trade(self, trade: ActiveTrade) -> None:
        """Call this when a trade is finalized (close_price and realized_pnl set)."""
        if trade.realized_pnl == 0 and not trade.close_time:
            return

        r_mult = (
            trade.realized_pnl / trade.risk_usd
            if trade.risk_usd and trade.risk_usd > 0
            else 0.0
        )

        summary = TradeSummary(
            trade_id=trade.trade_id,
            symbol=trade.symbol,
            direction=trade.direction,
            pnl=trade.realized_pnl,
            r_multiple=r_mult,
            close_time=trade.close_time or datetime.now(timezone.utc),
            quality=trade.quality_score,
        )
        self._trades.append(summary)

        # Per-symbol tracking
        sym = trade.symbol
        if trade.realized_pnl > 0:
            self._sym_wins[sym] += 1
        else:
            self._sym_loss[sym] += 1
        self._sym_pnl[sym] += trade.realized_pnl

        logger.debug(
            f"[PERF] Recorded trade={trade.trade_id} "
            f"sym={sym} pnl=${trade.realized_pnl:.2f} R={r_mult:.2f}"
        )

    # ── Snapshot computation ──────────────────────────────────────────────────

    def snapshot(self, balance: float, equity: float, open_positions: int = 0, floating_pnl: float = 0.0) -> PerformanceSnapshot:
        """Compute and return the current performance snapshot."""
        self._update_period_baselines(balance)

        snap = PerformanceSnapshot(balance=balance, equity=equity)

        # Peak / drawdown
        self._peak_equity = max(self._peak_equity, equity)
        if self._peak_equity > 0:
            snap.drawdown_pct = (self._peak_equity - equity) / self._peak_equity * 100.0
            self._max_dd = max(self._max_dd, snap.drawdown_pct)
        snap.peak_equity = self._peak_equity
        snap.max_drawdown = self._max_dd

        # Trade stats from rolling cache
        trades = list(self._trades)
        snap.total_trades = len(trades)
        wins  = [t for t in trades if t.pnl > 0]
        losers = [t for t in trades if t.pnl <= 0]
        snap.winning_trades = len(wins)
        snap.losing_trades  = len(losers)
        snap.win_rate       = len(wins) / len(trades) * 100.0 if trades else 0.0

        snap.gross_profit = sum(t.pnl for t in wins)
        snap.gross_loss   = sum(t.pnl for t in losers)
        snap.net_pnl      = snap.gross_profit + snap.gross_loss

        if snap.gross_loss < 0:
            snap.profit_factor = abs(snap.gross_profit / snap.gross_loss)
        elif snap.gross_profit > 0:
            snap.profit_factor = float("inf")
        else:
            snap.profit_factor = 0.0

        # R-multiple stats
        r_series = [t.r_multiple for t in trades]
        if r_series:
            snap.avg_r_multiple = statistics.mean(r_series)
            snap.max_r          = max(r_series)
            snap.min_r          = min(r_series)

        # Simplified Sharpe from last N trade returns
        snap.sharpe_approx = self._sharpe(r_series[-self._SHARPE_WINDOW:])

        # Period returns
        if self._day_start_balance > 0:
            snap.daily_return_pct = (balance - self._day_start_balance) / self._day_start_balance * 100.0
        if self._week_start_balance > 0:
            snap.weekly_return_pct = (balance - self._week_start_balance) / self._week_start_balance * 100.0
        if self._month_start_balance > 0:
            snap.monthly_return_pct = (balance - self._month_start_balance) / self._month_start_balance * 100.0

        # Per-symbol breakdown
        all_symbols = set(self._sym_wins) | set(self._sym_loss)
        for sym in all_symbols:
            w = self._sym_wins.get(sym, 0)
            l = self._sym_loss.get(sym, 0)
            total_sym = w + l
            snap.symbol_stats[sym] = {
                "trades":      total_sym,
                "wins":        w,
                "losses":      l,
                "win_rate":    round(w / total_sym * 100, 1) if total_sym else 0.0,
                "net_pnl":     round(self._sym_pnl.get(sym, 0.0), 2),
            }

        self._last_snap = snap

        # Throttled structured logging
        if time.time() - self._last_log >= self._log_interval:
            # Perform balance-equity consistency checks
            tolerance = 0.01
            if open_positions == 0:
                try:
                    assert abs(equity - balance) < tolerance
                except AssertionError:
                    computed_equity = balance + floating_pnl
                    diff = abs(computed_equity - equity)
                    print(
f"""====================================================
PERFORMANCE WARNING
====================================================
Balance: {balance:.2f}
Equity: {equity:.2f}
Open Positions: {open_positions}
Floating PnL: {floating_pnl:.2f}
Computed Equity: {computed_equity:.2f}
Broker Equity: {equity:.2f}
Difference: {diff:.2f}
====================================================
""", flush=True)

            self._log_snapshot(snap)
            self._last_log = time.time()

        return snap

    def _sharpe(self, r_series: List[float]) -> float:
        """
        Approximate Sharpe ratio from trade R-multiples.
        Sharpe ≈ mean(R) / std(R)  (no risk-free rate, trade-level)
        """
        if len(r_series) < 5:
            return 0.0
        try:
            mu  = statistics.mean(r_series)
            std = statistics.stdev(r_series)
            if std <= 0:
                return 0.0
            return round(mu / std, 2)
        except Exception:
            return 0.0

    def _update_period_baselines(self, balance: float) -> None:
        """Reset day/week/month baselines on period rollover."""
        now = datetime.now(timezone.utc)

        if now.day != self._period_day:
            self._day_start_balance = balance
            self._period_day = now.day

        week = now.isocalendar()[1]
        if week != self._period_week:
            self._week_start_balance  = balance
            self._period_week = week

        if now.month != self._period_month:
            self._month_start_balance = balance
            self._period_month = now.month

    def _log_snapshot(self, snap: PerformanceSnapshot) -> None:
        """Emit a structured performance log line."""
        logger.info(
            f"[PERF] "
            f"Bal=${snap.balance:,.2f} | "
            f"Equity=${snap.equity:,.2f} | "
            f"DD={snap.drawdown_pct:.2f}% | "
            f"WinRate={snap.win_rate:.1f}% | "
            f"PF={snap.profit_factor:.2f} | "
            f"Sharpe={snap.sharpe_approx:.2f} | "
            f"AvgR={snap.avg_r_multiple:.2f} | "
            f"Day={snap.daily_return_pct:+.2f}% | "
            f"Week={snap.weekly_return_pct:+.2f}% | "
            f"Month={snap.monthly_return_pct:+.2f}% | "
            f"Trades={snap.total_trades}"
        )

    # ── Accessors ─────────────────────────────────────────────────────────────

    def to_dict(self) -> Dict:
        """Return last snapshot as a plain dict (for dashboard state)."""
        snap = self._last_snap
        if snap is None:
            return {}
        return {
            "balance":        round(snap.balance, 2),
            "equity":         round(snap.equity, 2),
            "drawdown_pct":   round(snap.drawdown_pct, 2),
            "max_drawdown":   round(snap.max_drawdown, 2),
            "peak_equity":    round(snap.peak_equity, 2),
            "total_trades":   snap.total_trades,
            "win_rate":       round(snap.win_rate, 1),
            "profit_factor":  round(snap.profit_factor, 2),
            "sharpe":         snap.sharpe_approx,
            "avg_r":          round(snap.avg_r_multiple, 2),
            "daily_return":   round(snap.daily_return_pct, 2),
            "weekly_return":  round(snap.weekly_return_pct, 2),
            "monthly_return": round(snap.monthly_return_pct, 2),
            "symbol_stats":   snap.symbol_stats,
            "ts": snap.timestamp.isoformat(),
        }

    @property
    def last_snapshot(self) -> Optional[PerformanceSnapshot]:
        return self._last_snap
