"""
research/ml_framework/baselines_real.py

Evaluates simple heuristic rules on the REAL historical MT5 dataset.
Generates reports/real_data_baselines.md
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

from research.ml_framework.dataset_real import prepare_real_data
from research.ml_framework.evaluation import evaluate_predictions

logger = logging.getLogger("baselines_real")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

def run_real_baselines():
    logger.info("Loading and processing REAL MT5 Data...")
    _, _, test_data = prepare_real_data()
    
    if not test_data:
        logger.error("No test data available. Exiting.")
        return
        
    y_test_buy = [1 if d["label"] == "BUY_EDGE" else 0 for d in test_data]
    y_test_sell = [1 if d["label"] == "SELL_EDGE" else 0 for d in test_data]
    
    # Baselines
    def b_random(data): return [random.uniform(0, 1) for _ in data]
    def b_always_1(data): return [1.0 for _ in data]
    def b_trend(data): return [0.8 if d["features"]["f_ema_gap"] > 0 else 0.2 for d in data]
    def b_mr(data): return [0.8 if d["features"]["f_vwap_dev"] < -0.5 else 0.2 for d in data]
    def b_trend_s(data): return [0.8 if d["features"]["f_ema_gap"] < 0 else 0.2 for d in data]
    def b_mr_s(data): return [0.8 if d["features"]["f_vwap_dev"] > 0.5 else 0.2 for d in data]

    results_buy = {
        "Random": evaluate_predictions(y_test_buy, b_random(test_data)),
        "Always BUY": evaluate_predictions(y_test_buy, b_always_1(test_data)),
        "Trend Continuation": evaluate_predictions(y_test_buy, b_trend(test_data)),
        "Mean Reversion": evaluate_predictions(y_test_buy, b_mr(test_data))
    }
    
    results_sell = {
        "Random": evaluate_predictions(y_test_sell, b_random(test_data)),
        "Always SELL": evaluate_predictions(y_test_sell, b_always_1(test_data)),
        "Trend Continuation": evaluate_predictions(y_test_sell, b_trend_s(test_data)),
        "Mean Reversion": evaluate_predictions(y_test_sell, b_mr_s(test_data))
    }
    
    with open("reports/real_data_baselines.md", "w", encoding="utf-8") as f:
        f.write("# Real MT5 Data - Baseline Performance\n\n")
        f.write("## BUY Model Baselines\n")
        f.write("| Model | Accuracy | Precision | Recall | F1 Score |\n")
        f.write("|---|---|---|---|---|\n")
        for k, v in results_buy.items():
            if v: f.write(f"| {k} | {v['accuracy']:.4f} | {v['precision']:.4f} | {v['recall']:.4f} | {v['f1']:.4f} |\n")
            
        f.write("\n## SELL Model Baselines\n")
        f.write("| Model | Accuracy | Precision | Recall | F1 Score |\n")
        f.write("|---|---|---|---|---|\n")
        for k, v in results_sell.items():
            if v: f.write(f"| {k} | {v['accuracy']:.4f} | {v['precision']:.4f} | {v['recall']:.4f} | {v['f1']:.4f} |\n")
            
    logger.info("Real data baselines completed.")

if __name__ == "__main__":
    run_real_baselines()
