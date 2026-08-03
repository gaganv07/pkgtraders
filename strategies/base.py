"""
strategies/base.py — BaseStrategy Abstract Base Class

Every V2 prototype implements this interface.
The research harness calls evaluate() at every M15 step.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Optional

from strategies.context import StrategyContext
from strategies.signal import StrategySignal

logger = logging.getLogger(__name__)


class BaseStrategy(ABC):
    """
    Abstract base for all V2 entry model prototypes.

    Responsibilities of each subclass:
      - Maintain its own internal state (swing points, profile, etc.)
      - on_bar(): update state on each new bar (called before evaluate)
      - evaluate(): return a StrategySignal at each M15 step

    Rules:
      - Do NOT import from app.trade_quality or app.market_selector
      - Do NOT modify any global state
      - Must be stateless between instances (each prototype gets its own instance)
      - evaluate() must never raise — catch internally and return FLAT on error
    """

    #: Short name used in reports and CSV headers
    name:    str = "BaseStrategy"
    version: str = "0.1"

    #: Default SL and TP ratios (can be overridden per signal)
    default_sl_atr_mult: float = 1.0
    default_tp_rr:       float = 2.0

    def __init__(self):
        self._bar_count: int = 0
        self._signal_count: int = 0
        self._logger = logging.getLogger(f"strategy.{self.name}")

    @abstractmethod
    def evaluate(self, ctx: StrategyContext) -> StrategySignal:
        """
        Called at every M15 bar close.

        Returns a StrategySignal with direction LONG/SHORT/FLAT.
        FLAT means no trade at this step.

        Must not raise exceptions.
        """

    @abstractmethod
    def on_bar(self, ctx: StrategyContext) -> None:
        """
        Called before evaluate() on every new bar.
        Use for state maintenance (e.g. updating volume profiles,
        swing highs/lows, indicator buffers).
        """

    def reset(self) -> None:
        """Reset all internal state (called between walk-forward windows)."""
        self._bar_count = 0
        self._signal_count = 0

    def _flat(self, reason: str = "", failed: Optional[list] = None) -> StrategySignal:
        """Convenience: return a FLAT signal."""
        return StrategySignal(
            direction="FLAT", confidence=0.0,
            reason=reason,
            filters_failed=failed or [],
        )

    def _long(self, confidence: float, reason: str,
              sl_mult: Optional[float] = None, tp_rr: Optional[float] = None,
              passed: Optional[list] = None) -> StrategySignal:
        self._signal_count += 1
        return StrategySignal(
            direction="LONG",
            confidence=min(100.0, max(0.0, confidence)),
            sl_atr_mult=sl_mult or self.default_sl_atr_mult,
            tp_rr=tp_rr or self.default_tp_rr,
            reason=reason,
            filters_passed=passed or [],
        )

    def _short(self, confidence: float, reason: str,
               sl_mult: Optional[float] = None, tp_rr: Optional[float] = None,
               passed: Optional[list] = None) -> StrategySignal:
        self._signal_count += 1
        return StrategySignal(
            direction="SHORT",
            confidence=min(100.0, max(0.0, confidence)),
            sl_atr_mult=sl_mult or self.default_sl_atr_mult,
            tp_rr=tp_rr or self.default_tp_rr,
            reason=reason,
            filters_passed=passed or [],
        )
