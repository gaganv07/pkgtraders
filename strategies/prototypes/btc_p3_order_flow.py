import logging
import statistics
from collections import deque
from strategies.base import BaseStrategy
from strategies.context import StrategyContext
from strategies.signal import StrategySignal

logger = logging.getLogger(__name__)

class BTCOrderFlowMomentumStrategy(BaseStrategy):
    name = "BTC_P3_OrderFlow"
    version = "1.0"

    default_sl_atr_mult = 1.5
    default_tp_rr = 2.0

    def __init__(self):
        super().__init__()
        self.vol_window = 20
        self.vol_buffer = deque(maxlen=self.vol_window)
        self.vol_spike_mult = 1.8

    def on_bar(self, ctx: StrategyContext) -> None:
        if ctx.bars_m15:
            self.vol_buffer.append(ctx.bars_m15[-1].tick_vol)
        self._bar_count += 1

    def evaluate(self, ctx: StrategyContext) -> StrategySignal:
        if len(self.vol_buffer) < self.vol_window:
            return self._flat("Volume buffer warming up")

        curr = ctx.bars_m15[-1]
        
        # Calculate average volume of the previous 20 bars (excluding the current one)
        prev_vols = list(self.vol_buffer)[:-1]
        avg_vol = statistics.mean(prev_vols) if prev_vols else 1.0
        
        # Volume expansion: current volume >= vol_spike_mult x average
        vol_expansion = curr.tick_vol >= self.vol_spike_mult * avg_vol
        body_size = abs(curr.close - curr.open)
        
        # Body size requirement to avoid entry on wippy dojis: body >= 1.0x ATR_m15
        strong_body = body_size >= ctx.atr_m15 if ctx.atr_m15 > 0 else True

        # ── LONG Momentum ─────────────────────────────────────────────────────
        if ctx.ema_bull and vol_expansion and strong_body:
            if curr.close > curr.open:
                return self._long(
                    confidence=70.0,
                    reason=f"Volume Momentum LONG: Vol {curr.tick_vol} >= {self.vol_spike_mult}x Avg {avg_vol:.0f}, Body {body_size:.1f}",
                    sl_mult=self.default_sl_atr_mult,
                    tp_rr=self.default_tp_rr,
                    passed=["h1_ema_bull", "vol_expansion", "bullish_marubozu"]
                )

        # ── SHORT Momentum ────────────────────────────────────────────────────
        elif ctx.ema_bear and vol_expansion and strong_body:
            if curr.close < curr.open:
                return self._short(
                    confidence=70.0,
                    reason=f"Volume Momentum SHORT: Vol {curr.tick_vol} >= {self.vol_spike_mult}x Avg {avg_vol:.0f}, Body {body_size:.1f}",
                    sl_mult=self.default_sl_atr_mult,
                    tp_rr=self.default_tp_rr,
                    passed=["h1_ema_bear", "vol_expansion", "bearish_marubozu"]
                )

        return self._flat("No volume momentum breakout detected")
