"""
research/ml_framework/realism_study.py

Tests the hypothesis by progressively adding realism (noise, shocks, lower trend persistence)
to the synthetic market generator and measuring the degradation of the ML model's accuracy.
"""

import sys
import os
import math
import random
import statistics
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Dict

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

# Import the original building blocks, but we will patch the generator
import research.ml_framework.dataset as orig_dataset
from research.ml_framework.models.logistic import LogisticRegression
from research.ml_framework.evaluation import evaluate_predictions
from research.ml_framework.pipeline import prepare_xy

logger = logging.getLogger("realism_study")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

def generate_realistic_m15_bars(symbol: str, n_days: int) -> List[Dict]:
    """A much more realistic generator with low trend persistence and high noise."""
    base = orig_dataset._REF_PRICES.get(symbol, 1000.0)
    spread = orig_dataset._SPREADS.get(symbol, 15) * (base / 1000.0) * 0.001
    rng = random.Random(hash(symbol + "realism_v1") & 0xFFFFFFFF)

    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    start = now - timedelta(days=n_days)

    bars: List[Dict] = []
    p = base
    t = start

    regime_bars_left = rng.randint(5, 20)  # MUCH shorter persistence (5-20 bars instead of 20-100)
    current_regime = rng.choice(["trend_up", "trend_down", "range", "choppy"])
    trend_strength = rng.uniform(0.00005, 0.0002) # Much weaker drift
    vol_base = base * 0.0004

    while t < now:
        if t.weekday() >= 5:
            t += timedelta(minutes=15)
            continue

        h = t.hour
        # Normal session volatility
        if 7 <= h < 9: vol_mult = rng.uniform(1.2, 1.8)
        elif 12 <= h < 14: vol_mult = rng.uniform(1.4, 2.0)
        elif 14 <= h < 16: vol_mult = rng.uniform(1.2, 1.6)
        elif 16 <= h < 20: vol_mult = rng.uniform(0.8, 1.2)
        elif 0 <= h < 3: vol_mult = rng.uniform(0.6, 1.0)
        else: vol_mult = rng.uniform(0.4, 0.7)

        if regime_bars_left <= 0:
            current_regime = rng.choice(["trend_up", "trend_down", "range", "choppy", "range"])
            regime_bars_left = rng.randint(5, 20)
            trend_strength = rng.uniform(0.00005, 0.0002)
            vol_base = base * rng.uniform(0.0002, 0.0008)
            
            # Random shock (gap)
            if rng.random() < 0.1:
                p += p * rng.gauss(0, 0.003)
                
        regime_bars_left -= 1

        bar_vol = vol_base * vol_mult
        
        # Massive noise component added to all regimes
        noise = rng.gauss(0, bar_vol * 1.5) 
        
        if current_regime == "trend_up":
            drift = p * trend_strength
            o = p + rng.gauss(drift * 0.1, bar_vol * 0.5)
            c = o + rng.gauss(drift, bar_vol * 0.8) + noise
        elif current_regime == "trend_down":
            drift = -p * trend_strength
            o = p + rng.gauss(drift * 0.1, bar_vol * 0.5)
            c = o + rng.gauss(drift, bar_vol * 0.8) + noise
        elif current_regime == "choppy":
            bar_vol *= 2.0
            o = p + rng.gauss(0, bar_vol * 0.6)
            c = o + rng.gauss(0, bar_vol * 0.6) + noise
        else:
            o = p + rng.gauss(0, bar_vol * 0.3)
            c = o + rng.gauss(0, bar_vol * 0.3) + noise

        h_hi = max(o, c) + abs(rng.gauss(0, bar_vol * 0.8))
        h_lo = min(o, c) - abs(rng.gauss(0, bar_vol * 0.8))
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


def run_realism_study():
    # Patch the generator in dataset module
    logger.info("Patching synthetic generator with Realistic mode...")
    orig_dataset.generate_m15_bars = generate_realistic_m15_bars
    
    logger.info("Generating realistic dataset (24 months)...")
    symbols = ["BTCUSD", "XAUUSD", "EURUSD", "GBPUSD", "USDJPY", "NAS100", "US30"]
    train_data, val_data, test_data = orig_dataset.prepare_data(symbols)
    
    logger.info("Training Logistic Regression on Realistic Data (BUY_EDGE)...")
    X_train, y_train_buy = prepare_xy(train_data, "BUY_EDGE")
    X_test, y_test_buy = prepare_xy(test_data, "BUY_EDGE")
    
    model_buy = LogisticRegression(learning_rate=0.05, epochs=150, l2_penalty=0.005)
    model_buy.fit(X_train, y_train_buy)
    
    logger.info("Evaluating on Realistic Test Set...")
    prob_test_buy = model_buy.predict_proba(X_test)
    eval_buy = evaluate_predictions(y_test_buy, prob_test_buy)
    
    # Evaluate Baseline Random for comparison
    from research.ml_framework.baseline_comparison import baseline_random
    eval_rand = evaluate_predictions(y_test_buy, baseline_random(test_data))
    
    with open("reports/realism_study.md", "w", encoding="utf-8") as f:
        f.write("# Realism Study\n\n")
        f.write("## Hypothesis\n")
        f.write("If the ML model's 74% accuracy was genuinely discovering a robust market edge, it should degrade gracefully as realism increases. If it collapses to 50% (random), the model was exclusively exploiting the predictable mathematical artifacts of the naive synthetic generator.\n\n")
        
        f.write("## Modifications to Generator\n")
        f.write("- **Trend Persistence**: Reduced from 20-100 bars down to 5-20 bars.\n")
        f.write("- **Drift Strength**: Reduced by 75%.\n")
        f.write("- **Noise**: Added massive Gaussian noise component to price action, creating choppy spikes.\n")
        f.write("- **Shocks**: Added random 10% chance of a gap event at regime transitions.\n\n")
        
        f.write("## Results (BUY_EDGE)\n")
        f.write("| Model | Accuracy | Precision | Recall | F1 Score |\n")
        f.write("|---|---|---|---|---|\n")
        f.write(f"| **Logistic Regression (Naive Synthetic)** | 0.7423 | 0.7420 | 0.6482 | 0.6919 |\n")
        f.write(f"| **Logistic Regression (Realistic Synthetic)** | {eval_buy['accuracy']:.4f} | {eval_buy['precision']:.4f} | {eval_buy['recall']:.4f} | {eval_buy['f1']:.4f} |\n")
        f.write(f"| **Random Guess** | {eval_rand['accuracy']:.4f} | {eval_rand['precision']:.4f} | {eval_rand['recall']:.4f} | {eval_rand['f1']:.4f} |\n\n")
        
        f.write("## Conclusion\n")
        if eval_buy['accuracy'] < 0.55:
            f.write("The model's performance collapsed completely to near-random levels when applied to a realistic price series. This confirms beyond a doubt that the 'edge' discovered in Phase 4 was entirely a synthetic artifact caused by generating auto-correlated trend walks. The ML model is **NOT** ready for live trading.\n")
        else:
            f.write("The model retained significant predictive power, indicating some structural edge survived the realism injection.\n")
            
    logger.info("Realism study completed.")

if __name__ == "__main__":
    run_realism_study()
