"""
research/ml_framework/pipeline_real.py

Trains and evaluates the Logistic Regression baseline model on REAL MT5 data.
Generates comprehensive ML evaluation reports.
"""

import sys
import os
import logging
from typing import List, Dict

try:
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from research.ml_framework.dataset_real import prepare_real_data
from research.ml_framework.pipeline import prepare_xy
from research.ml_framework.models.logistic import LogisticRegression
from research.ml_framework.evaluation import evaluate_predictions, calibration_curve, precision_at_thresholds

logger = logging.getLogger("pipeline_real")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

def run_real_pipeline():
    logger.info("Starting REAL Data Pipeline...")
    train_data, val_data, test_data = prepare_real_data()
    
    if not train_data or not test_data:
        logger.error("No valid dataset generated. Are there CSVs in data/mt5?")
        return
        
    logger.info(f"Loaded Real Data - Train: {len(train_data)}, Val: {len(val_data)}, Test: {len(test_data)}")
    
    # Train BUY model
    logger.info("Training Logistic Regression (BUY_EDGE)...")
    X_train, y_train_buy = prepare_xy(train_data, "BUY_EDGE")
    X_test, y_test_buy = prepare_xy(test_data, "BUY_EDGE")
    
    model_buy = LogisticRegression(learning_rate=0.05, epochs=150, l2_penalty=0.005)
    model_buy.fit(X_train, y_train_buy)
    
    # Train SELL model
    logger.info("Training Logistic Regression (SELL_EDGE)...")
    _, y_train_sell = prepare_xy(train_data, "SELL_EDGE")
    _, y_test_sell = prepare_xy(test_data, "SELL_EDGE")
    
    model_sell = LogisticRegression(learning_rate=0.05, epochs=150, l2_penalty=0.005)
    model_sell.fit(X_train, y_train_sell)
    
    logger.info("Evaluating on REAL Test Set...")
    prob_buy = model_buy.predict_proba(X_test)
    prob_sell = model_sell.predict_proba(X_test)
    
    eval_buy = evaluate_predictions(y_test_buy, prob_buy)
    eval_sell = evaluate_predictions(y_test_sell, prob_sell)
    
    cal_buy = calibration_curve(y_test_buy, prob_buy)
    cal_sell = calibration_curve(y_test_sell, prob_sell)
    
    prec_buy = precision_at_thresholds(y_test_buy, prob_buy)
    prec_sell = precision_at_thresholds(y_test_sell, prob_sell)
    
    logger.info("Writing Reports...")
    with open("reports/real_data_model_results.md", "w", encoding="utf-8") as f:
        f.write("# Real Data Model Evaluation\n\n")
        f.write("## BUY Model\n")
        f.write(f"- Accuracy: {eval_buy['accuracy']:.4f}\n")
        f.write(f"- Precision: {eval_buy['precision']:.4f}\n")
        f.write(f"- Recall: {eval_buy['recall']:.4f}\n")
        f.write(f"- F1 Score: {eval_buy['f1']:.4f}\n")
        f.write(f"- Brier Score: {eval_buy['brier_score']:.4f}\n\n")
        
        f.write("## SELL Model\n")
        f.write(f"- Accuracy: {eval_sell['accuracy']:.4f}\n")
        f.write(f"- Precision: {eval_sell['precision']:.4f}\n")
        f.write(f"- Recall: {eval_sell['recall']:.4f}\n")
        f.write(f"- F1 Score: {eval_sell['f1']:.4f}\n")
        f.write(f"- Brier Score: {eval_sell['brier_score']:.4f}\n\n")
        
    with open("reports/out_of_sample_real_data.md", "w", encoding="utf-8") as f:
        f.write("# Out Of Sample Performance (Real Data)\n\n")
        f.write("## BUY Model (Precision at Threshold)\n")
        for k, v in prec_buy.items(): f.write(f"- {k}: {v}\n")
        f.write("\n## SELL Model (Precision at Threshold)\n")
        for k, v in prec_sell.items(): f.write(f"- {k}: {v}\n")
        
    with open("reports/probability_calibration.md", "w", encoding="utf-8") as f:
        f.write("# Probability Calibration (Real Data)\n\n")
        f.write("## BUY Model\n| Bin | Count | Mean Pred | Actual Freq |\n|---|---|---|---|\n")
        for c in cal_buy: f.write(f"| {c['bin']} | {c['count']} | {c['mean_pred']:.4f} | {c['actual_freq']:.4f} |\n")
        
        f.write("\n## SELL Model\n| Bin | Count | Mean Pred | Actual Freq |\n|---|---|---|---|\n")
        for c in cal_sell: f.write(f"| {c['bin']} | {c['count']} | {c['mean_pred']:.4f} | {c['actual_freq']:.4f} |\n")
        
    with open("reports/phase6_executive_summary.md", "w", encoding="utf-8") as f:
        f.write("# Phase 6 Executive Summary\n\n")
        f.write("## Transition to Real MT5 Data\n")
        f.write("The platform has been successfully converted to parse and evaluate strictly on genuine, historical MT5 OHLCV exports. Synthetic data generation has been permanently decommissioned for ML evaluation.\n\n")
        f.write("## Baseline Results\n")
        f.write(f"The complex Logistic Regression model achieved an out-of-sample accuracy of **{eval_buy['accuracy']:.2%}** on real market data. This establishes our first genuine benchmark.\n\n")
        f.write("## Next Steps\n")
        f.write("If the accuracy on real data is hovering around 50% (random), it means the current 20-feature set contains no predictive edge for real market mechanics. We must now explore advanced feature engineering or more complex non-linear ML models (e.g., LightGBM / Gradient Boosted Trees) in Phase 7.\n")
        
    logger.info("Real Pipeline completed.")

if __name__ == "__main__":
    run_real_pipeline()
