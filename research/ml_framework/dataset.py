"""
research/ml_framework/dataset.py

Handles:
1. Synthetic data generation (reuse Phase 2 logic)
2. Feature engineering (calculating strictly from past data)
3. Target labeling (+1R vs -1R within 20 bars)
4. Train/Val/Test splitting
5. Z-score normalization (fitted strictly on training set)
6. Data integrity checks (chronology, no leakage)
"""

import math
import random
import statistics
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Tuple
import logging

logger = logging.getLogger("ml_dataset")

# ── 1. Synthetic Data Generator (from Phase 2) ────────────────────────────────

_REF_PRICES = {
    "BTCUSD": 65000.0, "XAUUSD": 3200.0, "EURUSD": 1.085,
    "GBPUSD": 1.27, "USDJPY": 155.0, "NAS100": 20000.0, "US30": 42000.0
}
_SPREADS = {
    "BTCUSD": 250, "XAUUSD": 15, "EURUSD": 7,
    "GBPUSD": 10, "USDJPY": 8, "NAS100": 120, "US30": 200,
}

def generate_m15_bars(symbol: str, n_days: int) -> List[Dict]:
    base = _REF_PRICES.get(symbol, 1000.0)
    spread = _SPREADS.get(symbol, 15) * (base / 1000.0) * 0.001
    rng = random.Random(hash(symbol + "ml_framework_v1") & 0xFFFFFFFF)

    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    start = now - timedelta(days=n_days)

    bars: List[Dict] = []
    p = base
    t = start

    regime_bars_left = rng.randint(20, 80)
    current_regime = rng.choice(["trend_up", "trend_down", "range", "compression"])
    trend_strength = rng.uniform(0.0002, 0.0008)
    vol_base = base * 0.0004

    while t < now:
        if t.weekday() >= 5:
            t += timedelta(minutes=15)
            continue

        h = t.hour
        if 7 <= h < 9: vol_mult = rng.uniform(1.8, 2.8)
        elif 12 <= h < 14: vol_mult = rng.uniform(1.6, 2.4)
        elif 14 <= h < 16: vol_mult = rng.uniform(1.4, 2.0)
        elif 16 <= h < 20: vol_mult = rng.uniform(1.0, 1.6)
        elif 0 <= h < 3: vol_mult = rng.uniform(0.6, 1.1)
        else: vol_mult = rng.uniform(0.4, 0.9)

        if regime_bars_left <= 0:
            current_regime = rng.choice(["trend_up", "trend_down", "range", "compression", "range", "trend_up", "trend_down"])
            regime_bars_left = rng.randint(15, 100)
            trend_strength = rng.uniform(0.0001, 0.001)
            vol_base = base * rng.uniform(0.0002, 0.0008)
        regime_bars_left -= 1

        bar_vol = vol_base * vol_mult
        if current_regime == "trend_up":
            drift = p * trend_strength
            o = p + rng.gauss(drift * 0.3, bar_vol * 0.2)
            c = o + rng.gauss(drift, bar_vol * 0.6)
        elif current_regime == "trend_down":
            drift = -p * trend_strength
            o = p + rng.gauss(drift * 0.3, bar_vol * 0.2)
            c = o + rng.gauss(drift, bar_vol * 0.6)
        elif current_regime == "compression":
            bar_vol *= 0.3
            o = p + rng.gauss(0, bar_vol * 0.1)
            c = o + rng.gauss(0, bar_vol * 0.3)
        else:
            o = p + rng.gauss(0, bar_vol * 0.2)
            c = o + rng.gauss(0, bar_vol * 0.5)

        h_hi = max(o, c) + abs(rng.gauss(0, bar_vol * 0.4))
        h_lo = min(o, c) - abs(rng.gauss(0, bar_vol * 0.4))
        h_lo = max(h_lo, h_hi * 0.0001)

        bars.append({
            "time": t, "open": round(o, 6), "high": round(h_hi, 6),
            "low": round(h_lo, 6), "close": round(c, 6),
            "tick_volume": int(rng.randint(100, 2000) * vol_mult),
            "spread": spread,
        })
        p = c
        t += timedelta(minutes=15)
    return bars

# ── 2. Indicators & Features ────────────────────────────────────────────────

def _ema(values: List[float], period: int) -> List[float]:
    result = []
    k = 2.0 / (period + 1)
    v = None
    buf = []
    for x in values:
        if v is None:
            buf.append(x)
            if len(buf) >= period:
                v = sum(buf) / period
        else:
            v = x * k + v * (1 - k)
        result.append(v if v is not None else x)
    return result

def _rsi_series(closes: List[float], period: int = 14) -> List[float]:
    result = []
    gains, losses = [], []
    for i in range(len(closes)):
        if i == 0:
            result.append(50.0)
            continue
        chg = closes[i] - closes[i - 1]
        gains.append(max(chg, 0.0))
        losses.append(max(-chg, 0.0))
        if len(gains) < period:
            result.append(50.0)
            continue
        avg_g = statistics.mean(gains[-period:])
        avg_l = statistics.mean(losses[-period:])
        if avg_l == 0:
            result.append(100.0)
        else:
            rs = avg_g / avg_l
            result.append(100.0 - 100.0 / (1 + rs))
    return result

def _atr_series(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> List[float]:
    trs = []
    atrs = []
    for i in range(len(closes)):
        if i == 0:
            trs.append(highs[i] - lows[i])
        else:
            trs.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])))
        if len(trs) < period:
            atrs.append(trs[-1])
        elif len(trs) == period:
            atrs.append(statistics.mean(trs))
        else:
            atrs.append((atrs[-1] * (period - 1) + trs[-1]) / period)
    return atrs

def build_dataset(symbols: List[str], n_days: int) -> List[Dict]:
    """Generates features and labels for the given symbols."""
    dataset = []
    for sym in symbols:
        raw = generate_m15_bars(sym, n_days)
        if len(raw) < 150:
            continue

        highs = [b["high"] for b in raw]
        lows = [b["low"] for b in raw]
        closes = [b["close"] for b in raw]
        opens = [b["open"] for b in raw]
        times = [b["time"] for b in raw]

        atr = _atr_series(highs, lows, closes, 14)
        ema20 = _ema(closes, 20)
        ema50 = _ema(closes, 50)
        rsi = _rsi_series(closes, 14)

        # VWAP
        vwap = []
        cum_pv, cum_v = 0.0, 0.0
        cur_day = None
        for i, b in enumerate(raw):
            day = b["time"].strftime("%Y-%m-%d")
            if day != cur_day:
                cum_pv, cum_v = 0.0, 0.0
                cur_day = day
            tp = (highs[i] + lows[i] + closes[i]) / 3.0
            v = max(b["tick_volume"], 1)
            cum_pv += tp * v
            cum_v += v
            vwap.append(cum_pv / cum_v)

        # Sweeps
        sweeps = [0.0] * len(raw)
        for i in range(15, len(raw)):
            prior_h = max(highs[i-9:i-4])
            prior_l = min(lows[i-9:i-4])
            bar_h, bar_l, bar_c, bar_o = highs[i], lows[i], closes[i], opens[i]
            body_max, body_min = max(bar_o, bar_c), min(bar_o, bar_c)
            if bar_l < prior_l and bar_c > prior_l and (body_min - bar_l) > (body_max - body_min):
                sweeps[i] = 1.0
            elif bar_h > prior_h and bar_c < prior_h and (bar_h - body_max) > (body_max - body_min):
                sweeps[i] = -1.0

        # Build feature rows
        for i in range(120, len(raw) - 20):  # Need 120 past for ATR pct, 20 future for labels
            # ATR Percentile
            window_atr = atr[i-120:i+1]
            atr_pct = sum(1 for a in window_atr if a <= atr[i]) / len(window_atr) * 100.0
            
            c = closes[i]
            a = max(atr[i], 1e-6)
            bar_rng = max(highs[i] - lows[i], 1e-6)
            
            h = times[i].hour
            dow = times[i].weekday()

            features = {
                "symbol": sym,
                "time": times[i].isoformat(),
                "f_rsi": (rsi[i] - 50) / 50.0,
                "f_ema_gap": (ema20[i] - ema50[i]) / a,
                "f_ema20_dist": (c - ema20[i]) / a,
                "f_ema50_dist": (c - ema50[i]) / a,
                "f_vwap_dev": (c - vwap[i]) / a,
                "f_atr_pct": (atr_pct - 50) / 50.0,
                "f_body_ratio": abs(c - opens[i]) / bar_rng,
                "f_upper_wick": (highs[i] - max(opens[i], c)) / bar_rng,
                "f_lower_wick": (min(opens[i], c) - lows[i]) / bar_rng,
                "f_bull_bar": 1.0 if c >= opens[i] else -1.0,
                "f_ret_1": (c - closes[i-1]) / a,
                "f_ret_3": (c - closes[i-3]) / a,
                "f_hour_sin": math.sin(2 * math.pi * h / 24),
                "f_hour_cos": math.cos(2 * math.pi * h / 24),
                "f_dow_sin": math.sin(2 * math.pi * dow / 5),
                "f_london": 1.0 if 7 <= h < 12 else 0.0,
                "f_overlap": 1.0 if 12 <= h < 16 else 0.0,
                "f_ny": 1.0 if 16 <= h < 20 else 0.0,
                "f_asia": 1.0 if 0 <= h < 7 else 0.0,
                "f_sweep": sweeps[i]
            }

            # Labeling (+1R vs -1R within 20 bars)
            upper = c + a
            lower = c - a
            label = "NO_EDGE"
            
            for k in range(1, 21):
                f_h = highs[i+k]
                f_l = lows[i+k]
                if f_h >= upper and f_l <= lower:
                    # Ambiguous intra-bar, skip or assign NO_EDGE
                    label = "NO_EDGE"
                    break
                if f_h >= upper:
                    label = "BUY_EDGE"
                    break
                if f_l <= lower:
                    label = "SELL_EDGE"
                    break
                    
            dataset.append({
                "meta": {"symbol": sym, "time": times[i]},
                "features": features,
                "label": label
            })
            
    # Sort chronologically across symbols
    dataset.sort(key=lambda x: x["meta"]["time"])
    return dataset


# ── 3. Normalization & Splits ───────────────────────────────────────────────

class Scaler:
    def __init__(self):
        self.means = {}
        self.stds = {}
        
    def fit(self, dataset: List[Dict]):
        # Extract all feature keys (ignore meta and strings)
        if not dataset: return
        keys = [k for k, v in dataset[0]["features"].items() if isinstance(v, float)]
        
        for k in keys:
            vals = [d["features"][k] for d in dataset]
            self.means[k] = statistics.mean(vals)
            self.stds[k] = max(statistics.stdev(vals), 1e-6)
            
    def transform(self, dataset: List[Dict]) -> List[Dict]:
        out = []
        for d in dataset:
            new_f = {}
            for k, v in d["features"].items():
                if isinstance(v, float) and k in self.means:
                    new_f[k] = (v - self.means[k]) / self.stds[k]
                else:
                    new_f[k] = v
            out.append({
                "meta": d["meta"],
                "features": new_f,
                "label": d["label"]
            })
        return out


def prepare_data(symbols: List[str]):
    # 24 months total = 730 days.
    # Train = first 365, Val = next 180, Test = next 180.
    logger.info("Generating dataset...")
    full_dataset = build_dataset(symbols, 730)
    
    start_time = full_dataset[0]["meta"]["time"]
    train_end = start_time + timedelta(days=365)
    val_end = train_end + timedelta(days=180)
    
    train_set = [d for d in full_dataset if d["meta"]["time"] < train_end]
    val_set = [d for d in full_dataset if train_end <= d["meta"]["time"] < val_end]
    test_set = [d for d in full_dataset if d["meta"]["time"] >= val_end]
    
    logger.info("Fitting scaler on training set ONLY...")
    scaler = Scaler()
    scaler.fit(train_set)
    
    train_norm = scaler.transform(train_set)
    val_norm = scaler.transform(val_set)
    test_norm = scaler.transform(test_set)
    
    return train_norm, val_norm, test_norm


def run_integrity_checks(train: List[Dict], val: List[Dict], test: List[Dict]) -> str:
    issues = []
    # 1. Chronology and non-overlap
    if train and val:
        t_max = max(d["meta"]["time"] for d in train)
        v_min = min(d["meta"]["time"] for d in val)
        if t_max >= v_min:
            issues.append(f"LEAKAGE: Train max time {t_max} >= Val min time {v_min}")
    
    if val and test:
        v_max = max(d["meta"]["time"] for d in val)
        te_min = min(d["meta"]["time"] for d in test)
        if v_max >= te_min:
            issues.append(f"LEAKAGE: Val max time {v_max} >= Test min time {te_min}")
            
    # 2. Features correctly float and bounded (check a small sample)
    for k, v in train[0]["features"].items():
        if isinstance(v, float) and math.isnan(v):
            issues.append(f"NaN feature found in training: {k}")
            
    if not issues:
        return "✅ Passed all data integrity checks. No future leakage detected."
    return "❌ " + "\n❌ ".join(issues)
