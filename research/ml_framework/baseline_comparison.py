"""
research/ml_framework/baseline_comparison.py

Evaluates simple baseline heuristics against the Phase 4 test dataset to determine 
if the ML model's 74% accuracy is genuinely intelligent or easily matched by dumb rules 
exploiting the synthetic generator.
"""

import sys
import os
import random
import logging
from typing import List, Dict

try:
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from research.ml_framework.dataset import prepare_data
from research.ml_framework.evaluation import evaluate_predictions

SYMBOLS = ["BTCUSD", "XAUUSD", "EURUSD", "GBPUSD", "USDJPY", "NAS100", "US30"]

logger = logging.getLogger("baseline_comp")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

def baseline_random(dataset: List[Dict]) -> List[float]:
    return [random.uniform(0, 1) for _ in dataset]

def baseline_always_1(dataset: List[Dict]) -> List[float]:
    return [1.0 for _ in dataset]

def baseline_trend(dataset: List[Dict]) -> List[float]:
    # if f_ema_gap > 0 -> BUY probability = 0.8, else 0.2
    return [0.8 if d["features"]["f_ema_gap"] > 0 else 0.2 for d in dataset]

def baseline_mean_reversion(dataset: List[Dict]) -> List[float]:
    # if f_vwap_dev < -0.5 -> BUY probability = 0.8 (it's oversold)
    return [0.8 if d["features"]["f_vwap_dev"] < -0.5 else 0.2 for d in dataset]

def baseline_rsi_momentum(dataset: List[Dict]) -> List[float]:
    # f_rsi > 0 (RSI > 50) -> BUY
    return [0.8 if d["features"]["f_rsi"] > 0 else 0.2 for d in dataset]

def run_baselines():
    logger.info("Loading Test Data...")
    _, _, test_data = prepare_data(SYMBOLS)
    
    y_test_buy = [1 if d["label"] == "BUY_EDGE" else 0 for d in test_data]
    y_test_sell = [1 if d["label"] == "SELL_EDGE" else 0 for d in test_data]
    
    logger.info("Evaluating baselines for BUY_EDGE...")
    
    results_buy = {
        "Random": evaluate_predictions(y_test_buy, baseline_random(test_data)),
        "Always BUY": evaluate_predictions(y_test_buy, baseline_always_1(test_data)),
        "Trend Continuation (EMA)": evaluate_predictions(y_test_buy, baseline_trend(test_data)),
        "Mean Reversion (VWAP)": evaluate_predictions(y_test_buy, baseline_mean_reversion(test_data)),
        "RSI Momentum": evaluate_predictions(y_test_buy, baseline_rsi_momentum(test_data))
    }
    
    logger.info("Evaluating baselines for SELL_EDGE...")
    # For SELL, invert the trend and RSI rules
    def trend_sell(data): return [0.8 if d["features"]["f_ema_gap"] < 0 else 0.2 for d in data]
    def mr_sell(data): return [0.8 if d["features"]["f_vwap_dev"] > 0.5 else 0.2 for d in data]
    def rsi_sell(data): return [0.8 if d["features"]["f_rsi"] < 0 else 0.2 for d in data]
    
    results_sell = {
        "Random": evaluate_predictions(y_test_sell, baseline_random(test_data)),
        "Always SELL": evaluate_predictions(y_test_sell, baseline_always_1(test_data)),
        "Trend Continuation (EMA)": evaluate_predictions(y_test_sell, trend_sell(test_data)),
        "Mean Reversion (VWAP)": evaluate_predictions(y_test_sell, mr_sell(test_data)),
        "RSI Momentum": evaluate_predictions(y_test_sell, rsi_sell(test_data))
    }
    
    with open("reports/baseline_comparison.md", "w", encoding="utf-8") as f:
        f.write("# Baseline Model Comparison\n\n")
        
        f.write("## BUY Model Baselines\n")
        f.write("| Model | Accuracy | Precision | Recall | F1 Score |\n")
        f.write("|---|---|---|---|---|\n")
        f.write("| **Logistic Regression (Phase 4)** | **0.7423** | **0.7420** | **0.6482** | **0.6919** |\n")
        for k, v in results_buy.items():
            if not v: continue
            f.write(f"| {k} | {v['accuracy']:.4f} | {v['precision']:.4f} | {v['recall']:.4f} | {v['f1']:.4f} |\n")
            
        f.write("\n## SELL Model Baselines\n")
        f.write("| Model | Accuracy | Precision | Recall | F1 Score |\n")
        f.write("|---|---|---|---|---|\n")
        f.write("| **Logistic Regression (Phase 4)** | **0.7374** | **0.7496** | **0.6687** | **0.7069** |\n")
        for k, v in results_sell.items():
            if not v: continue
            f.write(f"| {k} | {v['accuracy']:.4f} | {v['precision']:.4f} | {v['recall']:.4f} | {v['f1']:.4f} |\n")
            
        f.write("\n## Conclusion\n")
        f.write("If the dumb 'Trend Continuation (EMA)' heuristic achieves similar accuracy (>70%) to the Logistic Regression model, it conclusively proves the ML model is just exploiting the synthetic data's massive trend autocorrelation, rather than discovering a complex multi-factor edge.\n")

if __name__ == "__main__":
    run_baselines()
