import logging
from strategies.base import BaseStrategy
from strategies.context import StrategyContext
from strategies.signal import StrategySignal

logger = logging.getLogger(__name__)

class BTCBreakRetestStrategy(BaseStrategy):
    name = "BTC_P4_BreakRetest"
    version = "1.0"

    default_sl_atr_mult = 1.5
    default_tp_rr = 2.0

    def __init__(self):
        super().__init__()
        # State tracking
        self.broken_resistance: float = 0.0
        self.broken_support: float = 0.0
        self.pending_retest_long = False
        self.pending_retest_short = False
        self.break_bar_index = 0

    def on_bar(self, ctx: StrategyContext) -> None:
        if len(ctx.bars_m15) < 55:
            return

        curr = ctx.bars_m15[-1]
        
        # Calculate resistance and support levels from 50 bars prior to recent bars
        # This keeps the levels stable rather than resetting every bar
        if not self.pending_retest_long and not self.pending_retest_short:
            prev_50 = ctx.bars_m15[-51:-1]
            self.stable_resistance = max(b.high for b in prev_50)
            self.stable_support = min(b.low for b in prev_50)

        # Detect Breakout
        if not self.pending_retest_long and not self.pending_retest_short:
            # Long Breakout
            if curr.close > self.stable_resistance:
                self.broken_resistance = self.stable_resistance
                self.pending_retest_long = True
                self.break_bar_index = self._bar_count
            # Short Breakout
            elif curr.close < self.stable_support:
                self.broken_support = self.stable_support
                self.pending_retest_short = True
                self.break_bar_index = self._bar_count

        # Expiry for retest: must retest within 12 bars of breakout
        if self._bar_count - self.break_bar_index > 12:
            self.pending_retest_long = False
            self.pending_retest_short = False

        self._bar_count += 1

    def evaluate(self, ctx: StrategyContext) -> StrategySignal:
        if len(ctx.bars_m15) < 55:
            return self._flat("Warming up")

        curr = ctx.bars_m15[-1]
        prev = ctx.bars_m15[-2]

        # ── LONG Retest ───────────────────────────────────────────────────────
        if ctx.ema_bull and self.pending_retest_long:
            # Retest condition: current low is below or near the broken resistance level,
            # but close remains above it.
            retested = curr.low <= self.broken_resistance * 1.001 and curr.close > self.broken_resistance
            # Confirmation: current bar close > previous high or close > open (bullish)
            confirmed = curr.close > curr.open and curr.close > prev.close

            if retested and confirmed:
                self.pending_retest_long = False # Consume signal
                sl_dist = curr.close - curr.low
                sl_dist = max(sl_dist, ctx.atr_m15 * 0.5 if ctx.atr_m15 > 0 else 1.0)
                sl_mult = sl_dist / ctx.atr_m15 if ctx.atr_m15 > 0 else self.default_sl_atr_mult

                return self._long(
                    confidence=75.0,
                    reason=f"Break-Retest LONG: Retested resistance={self.broken_resistance:.1f} and closed bullish",
                    sl_mult=sl_mult,
                    tp_rr=self.default_tp_rr,
                    passed=["h1_ema_bull", "resistance_retest", "bullish_confirmation"]
                )

        # ── SHORT Retest ──────────────────────────────────────────────────────
        elif ctx.ema_bear and self.pending_retest_short:
            # Retest condition: current high is above or near the broken support level,
            # but close remains below it.
            retested = curr.high >= self.broken_support * 0.999 and curr.close < self.broken_support
            confirmed = curr.close < curr.open and curr.close < prev.close

            if retested and confirmed:
                self.pending_retest_short = False # Consume signal
                sl_dist = curr.high - curr.close
                sl_dist = max(sl_dist, ctx.atr_m15 * 0.5 if ctx.atr_m15 > 0 else 1.0)
                sl_mult = sl_dist / ctx.atr_m15 if ctx.atr_m15 > 0 else self.default_sl_atr_mult

                return self._short(
                    confidence=75.0,
                    reason=f"Break-Retest SHORT: Retested support={self.broken_support:.1f} and closed bearish",
                    sl_mult=sl_mult,
                    tp_rr=self.default_tp_rr,
                    passed=["h1_ema_bear", "support_retest", "bearish_confirmation"]
                )

        return self._flat("No break-retest confirmation")
