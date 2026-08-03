"""
research/ml_framework/evaluation.py

Contains all evaluation metrics requested by the user:
- Accuracy, Precision, Recall, F1
- Brier Score
- Calibration Analysis (Reliability Curve)
- Confusion Matrix
- Precision at Probability Thresholds
"""

import math
from typing import List, Dict, Tuple

def evaluate_predictions(y_true: List[int], y_prob: List[float], threshold=0.5) -> Dict:
    if not y_true or len(y_true) != len(y_prob):
        return {}
        
    n = len(y_true)
    y_pred = [1 if p >= threshold else 0 for p in y_prob]
    
    tp = sum(1 for yt, yp in zip(y_true, y_pred) if yt == 1 and yp == 1)
    fp = sum(1 for yt, yp in zip(y_true, y_pred) if yt == 0 and yp == 1)
    tn = sum(1 for yt, yp in zip(y_true, y_pred) if yt == 0 and yp == 0)
    fn = sum(1 for yt, yp in zip(y_true, y_pred) if yt == 1 and yp == 0)
    
    accuracy = (tp + tn) / n if n > 0 else 0
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0
    f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0
    
    brier = sum((p - y)**2 for p, y in zip(y_prob, y_true)) / n
    
    return {
        "accuracy": accuracy,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "brier_score": brier,
        "confusion_matrix": {"tp": tp, "fp": fp, "tn": tn, "fn": fn}
    }

def calibration_curve(y_true: List[int], y_prob: List[float], bins=10) -> List[Dict]:
    """Bins predictions to compare mean predicted probability vs actual event frequency."""
    bin_width = 1.0 / bins
    cal_data = []
    
    for i in range(bins):
        low = i * bin_width
        high = (i + 1) * bin_width if i < bins - 1 else 1.01
        
        bin_probs = []
        bin_trues = []
        for p, y in zip(y_prob, y_true):
            if low <= p < high:
                bin_probs.append(p)
                bin_trues.append(y)
                
        if bin_probs:
            cal_data.append({
                "bin": f"{low:.1f}-{high if high <= 1.0 else 1.0:.1f}",
                "count": len(bin_probs),
                "mean_pred": sum(bin_probs) / len(bin_probs),
                "actual_freq": sum(bin_trues) / len(bin_trues)
            })
    return cal_data

def precision_at_thresholds(y_true: List[int], y_prob: List[float]) -> Dict[str, float]:
    """Calculates precision at increasingly confident thresholds."""
    thresholds = [0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8]
    results = {}
    
    for t in thresholds:
        tp = sum(1 for yt, yp in zip(y_true, y_prob) if yp >= t and yt == 1)
        fp = sum(1 for yt, yp in zip(y_true, y_prob) if yp >= t and yt == 0)
        total = tp + fp
        results[f"P >= {t:.2f}"] = tp / total if total > 0 else 0.0
        results[f"Count >= {t:.2f}"] = total
        
    return results
