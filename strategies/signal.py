"""
strategies/signal.py — Strategy Signal Output

Returned by BaseStrategy.evaluate() at every M15 step.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass
class StrategySignal:
    """
    Output of a strategy evaluation.

    direction   : "LONG" | "SHORT" | "FLAT"
    confidence  : 0-100  (maps to quality score for logging/comparison)
    sl_atr_mult : Stop-loss distance expressed as a multiple of ATR.
                  The harness computes: sl_price = entry ± (atr × sl_atr_mult)
    tp_rr       : Take-profit expressed as R:R ratio.
                  tp_price = entry ± (sl_distance × tp_rr)
    reason      : Human-readable entry rationale (logged to CSV)
    filters_passed / filters_failed : diagnostic filter lists
    """
    direction:       str   = "FLAT"
    confidence:      float = 0.0
    sl_atr_mult:     float = 1.0
    tp_rr:           float = 2.0
    reason:          str   = ""
    filters_passed:  List[str] = field(default_factory=list)
    filters_failed:  List[str] = field(default_factory=list)

    @property
    def is_entry(self) -> bool:
        return self.direction in ("LONG", "SHORT") and self.confidence > 0
