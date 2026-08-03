"""
research/ml_framework/sanity_tests.py

Runs robustness and sanity checks on the ML model:
- Shuffled labels
- Shuffled features
- Feature Ablation (single feature models)
Generates reports/sanity_tests.md and reports/ablation_study.md.
"""

import sys
import os
import random
import logging
from typing import List, Dict

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from research.ml_framework.dataset import prepare_data
from research.ml_framework.models.logistic import LogisticRegression
from research.ml_framework.evaluation import evaluate_predictions
from research.ml_framework.pipeline import prepare_xy

logger = logging.getLogger("sanity_tests")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

SYMBOLS = ["BTCUSD", "XAUUSD", "EURUSD", "GBPUSD", "USDJPY", "NAS100", "US30"]

def run_sanity_tests():
    logger.info("Loading normal dataset...")
    train_data, _, test_data = prepare_data(SYMBOLS)
    
    # We will test exclusively on the BUY_EDGE target to save time.
    X_train, y_train = prepare_xy(train_data, "BUY_EDGE")
    X_test, y_test = prepare_xy(test_data, "BUY_EDGE")
    
    results = {}
    
    # 1. Baseline
    logger.info("Training Baseline...")
    model_base = LogisticRegression(learning_rate=0.05, epochs=50)
    model_base.fit(X_train, y_train)
    results["Baseline"] = evaluate_predictions(y_test, model_base.predict_proba(X_test))
    
    # 2. Shuffled Labels
    logger.info("Training Shuffled Labels...")
    y_train_shuffled = y_train.copy()
    random.shuffle(y_train_shuffled)
    model_lbl = LogisticRegression(learning_rate=0.05, epochs=50)
    model_lbl.fit(X_train, y_train_shuffled)
    results["Shuffled Labels"] = evaluate_predictions(y_test, model_lbl.predict_proba(X_test))
    
    # 3. Shuffled Features
    logger.info("Training Shuffled Features...")
    X_train_shuffled = [x.copy() for x in X_train]
    n_features = len(X_train[0])
    for col in range(n_features):
        col_data = [row[col] for row in X_train_shuffled]
        random.shuffle(col_data)
        for i, row in enumerate(X_train_shuffled):
            row[col] = col_data[i]
            
    model_feat = LogisticRegression(learning_rate=0.05, epochs=50)
    model_feat.fit(X_train_shuffled, y_train)
    results["Shuffled Features"] = evaluate_predictions(y_test, model_feat.predict_proba(X_test))
    
    # Write Sanity Tests Report
    with open("reports/sanity_tests.md", "w", encoding="utf-8") as f:
        f.write("# Sanity Tests Report\n\n")
        f.write("| Test | Accuracy | Precision | Recall | F1 Score |\n")
        f.write("|---|---|---|---|---|\n")
        for k, v in results.items():
            f.write(f"| {k} | {v['accuracy']:.4f} | {v['precision']:.4f} | {v['recall']:.4f} | {v['f1']:.4f} |\n")
        f.write("\n*Conclusion*: If shuffled labels or features retain >50% accuracy, there is massive data leakage. If they collapse to ~50%, the pipeline is technically sound, and the baseline edge (if any) was derived from the features mapping to the labels.\n")
        
    # 4. Ablation Study
    logger.info("Running Feature Ablation...")
    
    keys = sorted([k for k, v in train_data[0]["features"].items() if isinstance(v, float)])
    idx_rsi = keys.index("f_rsi")
    idx_ema_gap = keys.index("f_ema_gap")
    idx_vwap = keys.index("f_vwap_dev")
    idx_atr = keys.index("f_atr_pct")
    
    ablation_results = {}
    
    def train_single_feature(feature_idx, name):
        X_tr_single = [[row[feature_idx]] for row in X_train]
        X_te_single = [[row[feature_idx]] for row in X_test]
        model = LogisticRegression(learning_rate=0.05, epochs=50)
        model.fit(X_tr_single, y_train)
        ablation_results[name] = evaluate_predictions(y_test, model.predict_proba(X_te_single))
        
    train_single_feature(idx_rsi, "Only RSI")
    train_single_feature(idx_ema_gap, "Only EMA Gap")
    train_single_feature(idx_vwap, "Only VWAP Deviation")
    train_single_feature(idx_atr, "Only ATR Percentile")
    
    with open("reports/ablation_study.md", "w", encoding="utf-8") as f:
        f.write("# Feature Ablation Study\n\n")
        f.write("| Feature | Accuracy | Precision | Recall | F1 Score |\n")
        f.write("|---|---|---|---|---|\n")
        for k, v in ablation_results.items():
            f.write(f"| {k} | {v['accuracy']:.4f} | {v['precision']:.4f} | {v['recall']:.4f} | {v['f1']:.4f} |\n")
            
    logger.info("Sanity tests and ablation study completed.")

if __name__ == "__main__":
    run_sanity_tests()
