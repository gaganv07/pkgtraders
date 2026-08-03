import logging
from strategies.base import BaseStrategy
from strategies.context import StrategyContext
from strategies.signal import StrategySignal

logger = logging.getLogger(__name__)

class BTCMSSSweepStrategy(BaseStrategy):
    name = "BTC_P1_MSSSweep"
    version = "1.0"

    default_sl_atr_mult = 1.5
    default_tp_rr = 2.0

    def __init__(self):
        super().__init__()
        # State tracking
        self.sweep_long_active = False
        self.sweep_short_active = False
        self.sweep_bar_index = 0

    def on_bar(self, ctx: StrategyContext) -> None:
        if len(ctx.bars_m15) < 21:
            return
        
        # Current bar is the last one in the buffer
        curr = ctx.bars_m15[-1]
        
        # Calculate 20-bar high/low excluding the current bar
        prev_20 = ctx.bars_m15[-21:-1]
        high_20 = max(b.high for b in prev_20)
        low_20 = min(b.low for b in prev_20)

        # Detect sweep
        # Long Sweep: Price went below the 20-bar low but closed above it
        if curr.low < low_20 and curr.close > low_20:
            self.sweep_long_active = True
            self.sweep_short_active = False
            self.sweep_bar_index = self._bar_count
            
        # Short Sweep: Price went above the 20-bar high but closed below it
        elif curr.high > high_20 and curr.close < high_20:
            self.sweep_short_active = True
            self.sweep_long_active = False
            self.sweep_bar_index = self._bar_count

        # Expiry for sweep signals (must happen within 3 bars)
        if self._bar_count - self.sweep_bar_index > 3:
            self.sweep_long_active = False
            self.sweep_short_active = False

        self._bar_count += 1

    def evaluate(self, ctx: StrategyContext) -> StrategySignal:
        if len(ctx.bars_m15) < 21:
            return self._flat("Insufficient bars for swing analysis")

        curr = ctx.bars_m15[-1]
        prev = ctx.bars_m15[-2]

        # MSS (Market Structure Shift) confirmation:
        # Long Entry: Bullish H1 structure + active long sweep + current bar closes above previous bar high (MSS)
        if ctx.ema_bull and self.sweep_long_active:
            if curr.close > prev.high:
                self.sweep_long_active = False # consume signal
                # Find lowest low of the last 3 bars for SL
                sl_val = min(b.low for b in ctx.bars_m15[-3:])
                sl_dist = curr.close - sl_val
                atr_dist = ctx.atr_m15 * self.default_sl_atr_mult
                # Ensure SL is not too small
                if sl_dist < atr_dist * 0.5:
                    sl_dist = atr_dist
                sl_mult_actual = sl_dist / ctx.atr_m15 if ctx.atr_m15 > 0 else self.default_sl_atr_mult
                
                return self._long(
                    confidence=75.0,
                    reason=f"MSS Sweep LONG: Close {curr.close:.1f} > Prev High {prev.high:.1f} after Sweep",
                    sl_mult=sl_mult_actual,
                    tp_rr=self.default_tp_rr,
                    passed=["h1_ema_bull", "liquidity_sweep_long", "mss_confirm"]
                )

        # Short Entry: Bearish H1 structure + active short sweep + current bar closes below previous bar low (MSS)
        elif ctx.ema_bear and self.sweep_short_active:
            if curr.close < prev.low:
                self.sweep_short_active = False # consume signal
                # Find highest high of the last 3 bars for SL
                sl_val = max(b.high for b in ctx.bars_m15[-3:])
                sl_dist = sl_val - curr.close
                atr_dist = ctx.atr_m15 * self.default_sl_atr_mult
                # Ensure SL is not too small
                if sl_dist < atr_dist * 0.5:
                    sl_dist = atr_dist
                sl_mult_actual = sl_dist / ctx.atr_m15 if ctx.atr_m15 > 0 else self.default_sl_atr_mult

                return self._short(
                    confidence=75.0,
                    reason=f"MSS Sweep SHORT: Close {curr.close:.1f} < Prev Low {prev.low:.1f} after Sweep",
                    sl_mult=sl_mult_actual,
                    tp_rr=self.default_tp_rr,
                    passed=["h1_ema_bear", "liquidity_sweep_short", "mss_confirm"]
                )

        return self._flat("No MSS or Sweep signal")
