"""
strategies/context.py — Strategy Context

Packages all market data available to a strategy at one M15 decision point.
Built by the research harness and passed to BaseStrategy.evaluate().
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

from app.market_data import Bar, Tick, VolState, TF_M5, TF_M15, TF_H1
from app.order_flow import OFSnapshot
from app.session import SessionState


@dataclass
class StrategyContext:
    """
    Immutable snapshot of all market state at one evaluation step.

    All strategies receive the exact same context object — guaranteeing
    apples-to-apples comparison on identical data.
    """
    # Identity
    symbol:     str
    timestamp:  datetime

    # Bars (most recent last)
    bars_m5:    List[Bar] = field(default_factory=list)
    bars_m15:   List[Bar] = field(default_factory=list)
    bars_h1:    List[Bar] = field(default_factory=list)

    # Latest tick
    tick:       Optional[Tick] = None

    # Derived indicators (pre-computed by MarketData)
    atr:        float = 0.0          # ATR(14) on M5
    atr_m15:    float = 0.0          # ATR(14) on M15 — wider context
    vwap:       Optional[float] = None
    vwap_slope: float = 0.0
    ema50:      Optional[float] = None   # H1 EMA50
    ema200:     Optional[float] = None   # H1 EMA200
    ema50_m15:  Optional[float] = None   # M15 EMA50 (for pullback detection)

    # Volatility regime
    vol_state:  VolState = field(default_factory=VolState)

    # Order flow (may be None if no tick data for this bar)
    of_snapshot: Optional[OFSnapshot] = None

    # Session
    session:    Optional[SessionState] = None

    # Broker specs
    contract_size: float = 100.0
    spread:        float = 0.0

    # ── Convenience properties ────────────────────────────────────────────────

    @property
    def price(self) -> float:
        """Mid price."""
        return self.tick.mid if self.tick else (self.bars_m15[-1].close if self.bars_m15 else 0.0)

    @property
    def is_london(self) -> bool:
        h = self.timestamp.hour
        return 7 <= h < 12

    @property
    def is_new_york(self) -> bool:
        h = self.timestamp.hour
        return 12 <= h < 20

    @property
    def is_overlap(self) -> bool:
        h = self.timestamp.hour
        return 12 <= h < 16

    @property
    def session_active(self) -> bool:
        return self.session.is_active if self.session else False

    @property
    def news_blackout(self) -> bool:
        return self.session.news_blackout if self.session else False

    @property
    def ema_bull(self) -> bool:
        """H1 EMA50 > EMA200 (bullish structure)."""
        return (self.ema50 is not None and self.ema200 is not None
                and self.ema50 > self.ema200)

    @property
    def ema_bear(self) -> bool:
        """H1 EMA50 < EMA200 (bearish structure)."""
        return (self.ema50 is not None and self.ema200 is not None
                and self.ema50 < self.ema200)

    @property
    def vol_regime(self) -> str:
        return self.vol_state.regime  # COMPRESSED|NORMAL|EXPANDING|EXPLOSIVE

    @property
    def atr_percentile(self) -> float:
        return self.vol_state.percentile

    def recent_m15(self, n: int) -> List[Bar]:
        """Return last n M15 bars."""
        return self.bars_m15[-n:] if len(self.bars_m15) >= n else self.bars_m15

    def recent_m5(self, n: int) -> List[Bar]:
        return self.bars_m5[-n:] if len(self.bars_m5) >= n else self.bars_m5
