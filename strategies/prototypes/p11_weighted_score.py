"""
P11 — Feature-Weighted AI Scoring Strategy
===========================================
Abandons hard AND logic. Evaluates 7 predictive features on a continuous scale (-1.0 to +1.0).
Computes a weighted sum normalized to 100.
Enters trades if the total score exceeds a configurable threshold.
"""
from __future__ import annotations

import logging
from collections import deque
from typing import Deque, Optional, Tuple, Dict

from strategies.base import BaseStrategy
from strategies.context import StrategyContext
from strategies.signal import StrategySignal

logger = logging.getLogger(__name__)


class P11WeightedScoreStrategy(BaseStrategy):
    name = "P11_Weighted_Score"
    version = "1.0"

    default_sl_atr_mult = 1.2
    default_tp_rr = 2.0

    def __init__(self):
        super().__init__()
        # Initial Phase 2 Weights
        self.weights = {
            "rsi": 30.0,
            "ema": 20.0,
            "vwap": 18.0,
            "atr": 12.0,
            "sweep": 10.0,
            "session": 5.0,
            "regime": 5.0
        }
        self.threshold = 70.0
        
        # Buffers
        self._m15_highs: Deque[float] = deque(maxlen=20)
        self._m15_lows: Deque[float] = deque(maxlen=20)
        self._m15_closes: Deque[float] = deque(maxlen=20)
        self._m15_opens: Deque[float] = deque(maxlen=20)

        self._ema20: Optional[float] = None
        self._ema50: Optional[float] = None
        self._avg_gain: float = 0.0
        self._avg_loss: float = 0.0
        self._rsi14: float = 50.0
        self._last_close: Optional[float] = None
        
        # VWAP
        self._vwap_cum_pv = 0.0
        self._vwap_cum_v = 0.0
        self._vwap_day = None
        self._vwap_val: Optional[float] = None

    def set_weights(self, weights: Dict[str, float], threshold: float):
        """Dynamically update weights from the optimizer."""
        self.weights = weights
        self.threshold = threshold

    def on_bar(self, ctx: StrategyContext) -> None:
        if not ctx.bars_m15:
            return
        bar = ctx.bars_m15[-1]
        
        self._m15_highs.append(bar.high)
        self._m15_lows.append(bar.low)
        self._m15_closes.append(bar.close)
        self._m15_opens.append(bar.open)

        c = bar.close
        if self._ema20 is None:
            self._ema20 = c
        else:
            k20 = 2.0 / (20 + 1)
            self._ema20 = (c - self._ema20) * k20 + self._ema20

        if self._ema50 is None:
            self._ema50 = c
        else:
            k50 = 2.0 / (50 + 1)
            self._ema50 = (c - self._ema50) * k50 + self._ema50

        if self._last_close is not None:
            change = c - self._last_close
            gain = change if change > 0 else 0.0
            loss = -change if change < 0 else 0.0
            self._avg_gain = (self._avg_gain * 13 + gain) / 14
            self._avg_loss = (self._avg_loss * 13 + loss) / 14
            if self._avg_loss == 0:
                self._rsi14 = 100.0 if self._avg_gain > 0 else 50.0
            else:
                rs = self._avg_gain / self._avg_loss
                self._rsi14 = 100.0 - (100.0 / (1.0 + rs))
                
        day = bar.time.strftime("%Y-%m-%d") if bar.time else ctx.timestamp.strftime("%Y-%m-%d")
        if self._vwap_day != day:
            self._vwap_cum_pv = 0.0
            self._vwap_cum_v = 0.0
            self._vwap_day = day
            
        tp = (bar.high + bar.low + c) / 3.0
        v = max(getattr(bar, 'tick_vol', 1), 1)
        self._vwap_cum_pv += tp * v
        self._vwap_cum_v += v
        self._vwap_val = self._vwap_cum_pv / self._vwap_cum_v
                
        self._last_close = c

    def _check_liquidity_sweep(self) -> float:
        """Returns +1.0 for Bull Sweep, -1.0 for Bear Sweep, 0.0 otherwise."""
        if len(self._m15_highs) < 10:
            return 0.0
            
        highs = list(self._m15_highs)
        lows = list(self._m15_lows)
        closes = list(self._m15_closes)
        opens = list(self._m15_opens)

        bull_sweep = 0.0
        bear_sweep = 0.0

        for i in range(-4, 0):
            if i - 5 < -len(highs):
                continue
            prior_high = max(highs[i-5:i])
            prior_low = min(lows[i-5:i])
            bar_h, bar_l, bar_c, bar_o = highs[i], lows[i], closes[i], opens[i]
            body_max = max(bar_o, bar_c)
            body_min = min(bar_o, bar_c)

            if bar_l < prior_low and bar_c > prior_low and (body_min - bar_l) > (body_max - body_min):
                bull_sweep = 1.0
            if bar_h > prior_high and bar_c < prior_high and (bar_h - body_max) > (body_max - body_min):
                bear_sweep = -1.0

        if bull_sweep > 0 and bear_sweep == 0:
            return 1.0
        if bear_sweep < 0 and bull_sweep == 0:
            return -1.0
        return 0.0

    def evaluate(self, ctx: StrategyContext) -> StrategySignal:
        if len(self._m15_highs) < 15 or self._ema50 is None:
            return self._flat("Warmup", ["warmup"])
        if ctx.atr <= 0 or self._vwap_val is None:
            return self._flat("Missing ATR/VWAP", ["data_missing"])

        c = ctx.price
        atr = ctx.atr
        
        # 1. RSI Score
        f_rsi = (self._rsi14 - 50.0) / 50.0
        
        # 2. EMA Score
        ema_gap = (self._ema20 - self._ema50) / atr
        f_ema = max(-1.0, min(1.0, ema_gap / 1.5))
        
        # Trend Consensus (used to apply direction to non-directional magnitudes)
        trend_sign = 1.0 if f_ema >= 0 else -1.0
        
        # 3. VWAP Score
        vwap_dev = (c - self._vwap_val) / atr
        f_vwap = max(-1.0, min(1.0, vwap_dev / 2.0))
        
        # 4. ATR Score (Magnitude polarized by Trend)
        atr_pct = ctx.atr_percentile
        f_atr = (atr_pct / 100.0) * trend_sign
        
        # 5. Liquidity Sweep
        f_sweep = self._check_liquidity_sweep()
        
        # 6. Session Score
        if ctx.is_overlap:
            s_val = 1.0
        elif ctx.is_london:
            s_val = 0.5
        else:
            s_val = 0.0
        f_session = s_val * trend_sign
        
        # 7. Regime Score
        r_val = 0.0
        if atr_pct > 80:
            r_val = 1.0  # HIGH_VOL
        elif atr_pct < 40 and abs(ema_gap) < 0.3:
            r_val = 0.5  # RANGE
        f_regime = r_val * trend_sign

        # Normalization Factor (ensure weights sum to 100)
        total_w = sum(abs(w) for w in self.weights.values())
        if total_w == 0:
            total_w = 1.0

        # Weighted Sum
        score = (
            f_rsi * self.weights["rsi"] +
            f_ema * self.weights["ema"] +
            f_vwap * self.weights["vwap"] +
            f_atr * self.weights["atr"] +
            f_sweep * self.weights["sweep"] +
            f_session * self.weights["session"] +
            f_regime * self.weights["regime"]
        )
        
        normalized_score = (score / total_w) * 100.0

        if normalized_score >= self.threshold:
            return self._long(
                confidence=normalized_score,
                reason=f"P11 Score {normalized_score:.1f} >= {self.threshold:.1f}",
                passed=["score_threshold"]
            )
        elif normalized_score <= -self.threshold:
            return self._short(
                confidence=abs(normalized_score),
                reason=f"P11 Score {normalized_score:.1f} <= -{self.threshold:.1f}",
                passed=["score_threshold"]
            )

        return self._flat(f"Score {normalized_score:.1f} insufficient")
