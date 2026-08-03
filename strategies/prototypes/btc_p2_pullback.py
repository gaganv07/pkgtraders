import logging
from strategies.base import BaseStrategy
from strategies.context import StrategyContext
from strategies.signal import StrategySignal

logger = logging.getLogger(__name__)

class BTCPullbackStrategy(BaseStrategy):
    name = "BTC_P2_Pullback"
    version = "1.0"

    default_sl_atr_mult = 1.5
    default_tp_rr = 2.5

    def on_bar(self, ctx: StrategyContext) -> None:
        self._bar_count += 1

    def evaluate(self, ctx: StrategyContext) -> StrategySignal:
        if not ctx.bars_m15 or ctx.ema50_m15 is None:
            return self._flat("EMA50_M15 not loaded")

        curr = ctx.bars_m15[-1]
        body = abs(curr.close - curr.open)
        # Avoid division by zero
        body_effective = max(body, ctx.atr_m15 * 0.05 if ctx.atr_m15 > 0 else 0.0001)

        # ── Pullback LONG ─────────────────────────────────────────────────────
        if ctx.ema_bull:
            # Low touched or went below M15 EMA50, but close is above it
            touched_ema = curr.low <= ctx.ema50_m15 and curr.close > ctx.ema50_m15
            lower_wick = min(curr.open, curr.close) - curr.low
            
            # Rejection wick validation: wick >= 1.5 * body, and wick is at least 0.2 * ATR_m15
            rejection_ok = lower_wick >= 1.2 * body_effective and (ctx.atr_m15 > 0 and lower_wick >= ctx.atr_m15 * 0.2)
            
            if touched_ema and rejection_ok:
                sl_dist = curr.close - curr.low
                sl_dist = max(sl_dist, ctx.atr_m15 * 0.5 if ctx.atr_m15 > 0 else 1.0)
                sl_mult = sl_dist / ctx.atr_m15 if ctx.atr_m15 > 0 else self.default_sl_atr_mult
                
                return self._long(
                    confidence=80.0,
                    reason=f"Pullback LONG: Touched EMA50_M15={ctx.ema50_m15:.1f} with Lower Wick {lower_wick:.1f}",
                    sl_mult=sl_mult,
                    tp_rr=self.default_tp_rr,
                    passed=["h1_ema_bull", "ema50_m15_pullback", "wick_rejection"]
                )

        # ── Pullback SHORT ────────────────────────────────────────────────────
        elif ctx.ema_bear:
            # High touched or went above M15 EMA50, but close is below it
            touched_ema = curr.high >= ctx.ema50_m15 and curr.close < ctx.ema50_m15
            upper_wick = curr.high - max(curr.open, curr.close)
            
            rejection_ok = upper_wick >= 1.2 * body_effective and (ctx.atr_m15 > 0 and upper_wick >= ctx.atr_m15 * 0.2)
            
            if touched_ema and rejection_ok:
                sl_dist = curr.high - curr.close
                sl_dist = max(sl_dist, ctx.atr_m15 * 0.5 if ctx.atr_m15 > 0 else 1.0)
                sl_mult = sl_dist / ctx.atr_m15 if ctx.atr_m15 > 0 else self.default_sl_atr_mult

                return self._short(
                    confidence=80.0,
                    reason=f"Pullback SHORT: Touched EMA50_M15={ctx.ema50_m15:.1f} with Upper Wick {upper_wick:.1f}",
                    sl_mult=sl_mult,
                    tp_rr=self.default_tp_rr,
                    passed=["h1_ema_bear", "ema50_m15_pullback", "wick_rejection"]
                )

        return self._flat("No pullback setup")
