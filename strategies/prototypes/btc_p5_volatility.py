import logging
import math
from collections import deque
from strategies.base import BaseStrategy
from strategies.context import StrategyContext
from strategies.signal import StrategySignal

logger = logging.getLogger(__name__)

class BTCVolatilitySqueezeStrategy(BaseStrategy):
    name = "BTC_P5_Volatility"
    version = "1.0"

    default_sl_atr_mult = 1.5
    default_tp_rr = 2.5

    def __init__(self):
        super().__init__()
        self.bb_period = 20
        self.hist_len = 100
        self.close_buffer = deque(maxlen=self.bb_period)
        self.bandwidth_buffer = deque(maxlen=self.hist_len)

    def on_bar(self, ctx: StrategyContext) -> None:
        if ctx.bars_m15:
            close = ctx.bars_m15[-1].close
            self.close_buffer.append(close)
            
            # Compute current Bollinger Band width
            if len(self.close_buffer) >= self.bb_period:
                closes = list(self.close_buffer)
                sma = sum(closes) / len(closes)
                variance = sum((x - sma) ** 2 for x in closes) / (len(closes) - 1)
                stdev = math.sqrt(variance) if variance > 0 else 0.0001
                upper = sma + 2.0 * stdev
                lower = sma - 2.0 * stdev
                bandwidth = (upper - lower) / sma if sma > 0 else 0.0
                self.bandwidth_buffer.append(bandwidth)
                
        self._bar_count += 1

    def evaluate(self, ctx: StrategyContext) -> StrategySignal:
        if len(self.close_buffer) < self.bb_period or len(self.bandwidth_buffer) < 50:
            return self._flat("Warming up BB buffers")

        curr = ctx.bars_m15[-1]
        
        # Calculate Bollinger Bands
        closes = list(self.close_buffer)
        sma = sum(closes) / len(closes)
        variance = sum((x - sma) ** 2 for x in closes) / (len(closes) - 1)
        stdev = math.sqrt(variance) if variance > 0 else 0.0001
        upper = sma + 2.0 * stdev
        lower = sma - 2.0 * stdev
        
        current_bw = self.bandwidth_buffer[-1]
        
        # Check squeeze: current bandwidth is in the lowest 25% of the last 100 bandwidth values
        bw_list = list(self.bandwidth_buffer)
        bw_list.sort()
        threshold_25 = bw_list[len(bw_list) // 4]
        is_squeeze = current_bw <= threshold_25

        # ── LONG Squeeze Breakout ─────────────────────────────────────────────
        if ctx.ema_bull and is_squeeze:
            if curr.close > upper:
                return self._long(
                    confidence=75.0,
                    reason=f"BB Squeeze LONG: Bandwidth {current_bw:.4f} <= 25th %ile {threshold_25:.4f}, Close {curr.close:.1f} > Upper {upper:.1f}",
                    sl_mult=self.default_sl_atr_mult,
                    tp_rr=self.default_tp_rr,
                    passed=["h1_ema_bull", "bb_squeeze", "bollinger_upper_breakout"]
                )

        # ── SHORT Squeeze Breakout ────────────────────────────────────────────
        elif ctx.ema_bear and is_squeeze:
            if curr.close < lower:
                return self._short(
                    confidence=75.0,
                    reason=f"BB Squeeze SHORT: Bandwidth {current_bw:.4f} <= 25th %ile {threshold_25:.4f}, Close {curr.close:.1f} < Lower {lower:.1f}",
                    sl_mult=self.default_sl_atr_mult,
                    tp_rr=self.default_tp_rr,
                    passed=["h1_ema_bear", "bb_squeeze", "bollinger_lower_breakout"]
                )

        return self._flat("No squeeze breakout detected")
