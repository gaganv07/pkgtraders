"""
research/ml_framework/pipeline.py

Orchestrates the Baseline AI Prediction Framework (Phase 4).
- Data generation & integrity validation
- Model training (Logistic Regression baseline)
- Evaluation & reporting
"""

import sys
import os
import logging
import json
from typing import List, Dict

try:
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from research.ml_framework.dataset import prepare_data, run_integrity_checks
from research.ml_framework.models.logistic import LogisticRegression
from research.ml_framework.evaluation import evaluate_predictions, calibration_curve, precision_at_thresholds

SYMBOLS = ["BTCUSD", "XAUUSD", "EURUSD", "GBPUSD", "USDJPY", "NAS100", "US30"]

logger = logging.getLogger("ml_pipeline")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler("reports/ml_pipeline.log", mode="w", encoding="utf-8")])

def prepare_xy(dataset: List[Dict], target_label: str) -> tuple:
    X = []
    y = []
    # Ensure stable ordering of feature keys
    keys = sorted([k for k, v in dataset[0]["features"].items() if isinstance(v, float)])
    for d in dataset:
        row = [d["features"][k] for k in keys]
        X.append(row)
        y.append(1 if d["label"] == target_label else 0)
    return X, y

def main():
    logger.info("Phase 4 Baseline ML Pipeline Starting...")
    
    # 1. Dataset Construction
    train_data, val_data, test_data = prepare_data(SYMBOLS)
    logger.info(f"Generated samples - Train: {len(train_data)} | Val: {len(val_data)} | Test: {len(test_data)}")
    
    # 2. Data Integrity Verification
    logger.info("Running Data Integrity Checks...")
    integrity_report = run_integrity_checks(train_data, val_data, test_data)
    with open("reports/data_integrity.md", "w", encoding="utf-8") as f:
        f.write(f"# Data Integrity Report\n\n{integrity_report}\n")
    if "❌" in integrity_report:
        logger.error("Data Integrity failed. Stopping pipeline.")
        return

    # 3. Model Training (BUY and SELL independent models)
    logger.info("Training Logistic Regression (BUY_EDGE)...")
    X_train, y_train_buy = prepare_xy(train_data, "BUY_EDGE")
    X_val, y_val_buy = prepare_xy(val_data, "BUY_EDGE")
    X_test, y_test_buy = prepare_xy(test_data, "BUY_EDGE")
    
    model_buy = LogisticRegression(learning_rate=0.05, epochs=150, l2_penalty=0.005)
    model_buy.fit(X_train, y_train_buy)
    
    logger.info("Training Logistic Regression (SELL_EDGE)...")
    _, y_train_sell = prepare_xy(train_data, "SELL_EDGE")
    _, y_val_sell = prepare_xy(val_data, "SELL_EDGE")
    _, y_test_sell = prepare_xy(test_data, "SELL_EDGE")
    
    model_sell = LogisticRegression(learning_rate=0.05, epochs=150, l2_penalty=0.005)
    model_sell.fit(X_train, y_train_sell)
    
    # 4. Evaluation
    logger.info("Evaluating on Test Set...")
    prob_test_buy = model_buy.predict_proba(X_test)
    prob_test_sell = model_sell.predict_proba(X_test)
    
    eval_buy = evaluate_predictions(y_test_buy, prob_test_buy)
    eval_sell = evaluate_predictions(y_test_sell, prob_test_sell)
    
    cal_buy = calibration_curve(y_test_buy, prob_test_buy)
    cal_sell = calibration_curve(y_test_sell, prob_test_sell)
    
    prec_buy = precision_at_thresholds(y_test_buy, prob_test_buy)
    prec_sell = precision_at_thresholds(y_test_sell, prob_test_sell)
    
    # 5. Reporting
    with open("reports/model_evaluation.md", "w", encoding="utf-8") as f:
        f.write(f"""# Model Evaluation (Out-Of-Sample Test)

## BUY Model (Logistic Regression)
- **Accuracy**: {eval_buy['accuracy']:.4f}
- **Precision**: {eval_buy['precision']:.4f}
- **Recall**: {eval_buy['recall']:.4f}
- **F1 Score**: {eval_buy['f1']:.4f}
- **Brier Score**: {eval_buy['brier_score']:.4f}

## SELL Model (Logistic Regression)
- **Accuracy**: {eval_sell['accuracy']:.4f}
- **Precision**: {eval_sell['precision']:.4f}
- **Recall**: {eval_sell['recall']:.4f}
- **F1 Score**: {eval_sell['f1']:.4f}
- **Brier Score**: {eval_sell['brier_score']:.4f}
""")

    with open("reports/confusion_matrix.md", "w", encoding="utf-8") as f:
        f.write(f"""# Confusion Matrices (Threshold = 0.5)

## BUY Model
| | Predicted Positive | Predicted Negative |
|---|---|---|
| **Actual Positive** | True Positive: {eval_buy['confusion_matrix']['tp']} | False Negative: {eval_buy['confusion_matrix']['fn']} |
| **Actual Negative** | False Positive: {eval_buy['confusion_matrix']['fp']} | True Negative: {eval_buy['confusion_matrix']['tn']} |

## SELL Model
| | Predicted Positive | Predicted Negative |
|---|---|---|
| **Actual Positive** | True Positive: {eval_sell['confusion_matrix']['tp']} | False Negative: {eval_sell['confusion_matrix']['fn']} |
| **Actual Negative** | False Positive: {eval_sell['confusion_matrix']['fp']} | True Negative: {eval_sell['confusion_matrix']['tn']} |

## Precision at Confidence Thresholds
**BUY Model**
""")
        for k, v in prec_buy.items():
            f.write(f"- {k}: {v}\n")
        f.write("\n**SELL Model**\n")
        for k, v in prec_sell.items():
            f.write(f"- {k}: {v}\n")

    with open("reports/calibration.md", "w", encoding="utf-8") as f:
        f.write("# Probability Calibration Curves\n\n## BUY Model\n| Bin | Count | Mean Predicted Prob | Actual Frequency |\n|---|---|---|---|\n")
        for c in cal_buy:
            f.write(f"| {c['bin']} | {c['count']} | {c['mean_pred']:.4f} | {c['actual_freq']:.4f} |\n")
        
        f.write("\n## SELL Model\n| Bin | Count | Mean Predicted Prob | Actual Frequency |\n|---|---|---|---|\n")
        for c in cal_sell:
            f.write(f"| {c['bin']} | {c['count']} | {c['mean_pred']:.4f} | {c['actual_freq']:.4f} |\n")

    logger.info("Pipeline completed. All reports generated.")

if __name__ == "__main__":
    main()
