"""
research/ml_framework/dataset_real.py

Takes real MT5 OHLCV bars from mt5_loader and engineers features/labels.
Maintains rigorous anti-leakage and chronological splitting standards.
"""

import math
import statistics
import logging
from typing import List, Dict

from research.ml_framework.mt5_loader import load_all_mt5_data
from research.ml_framework.dataset import _ema, _rsi_series, _atr_series, Scaler

logger = logging.getLogger("dataset_real")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

def build_real_dataset(symbols_bars: Dict[str, List[Dict]]) -> List[Dict]:
    """Generates features and labels for real MT5 bars."""
    dataset = []
    
    for sym, raw in symbols_bars.items():
        if len(raw) < 150:
            logger.warning(f"Not enough data for {sym}, skipping.")
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
            
    dataset.sort(key=lambda x: x["meta"]["time"])
    return dataset


def prepare_real_data():
    logger.info("Loading MT5 Data...")
    raw_data = load_all_mt5_data()
    
    logger.info("Extracting Features and Labels...")
    full_dataset = build_real_dataset(raw_data)
    
    if not full_dataset:
        logger.error("No valid dataset generated. Are there CSVs in data/mt5?")
        return [], [], []
        
    # Chronological Split: 60% Train, 20% Val, 20% Test
    n = len(full_dataset)
    train_idx = int(n * 0.6)
    val_idx = int(n * 0.8)
    
    train_set = full_dataset[:train_idx]
    val_set = full_dataset[train_idx:val_idx]
    test_set = full_dataset[val_idx:]
    
    logger.info("Fitting Scaler on REAL Training Data Only...")
    scaler = Scaler()
    scaler.fit(train_set)
    
    return scaler.transform(train_set), scaler.transform(val_set), scaler.transform(test_set)
