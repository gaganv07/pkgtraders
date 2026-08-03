# Sanity Tests Report

| Test | Accuracy | Precision | Recall | F1 Score |
|---|---|---|---|---|
| Baseline | 0.7555 | 0.7559 | 0.6939 | 0.7236 |
| Shuffled Labels | 0.5424 | 0.6699 | 0.0155 | 0.0303 |
| Shuffled Features | 0.5385 | 0.4065 | 0.0012 | 0.0025 |

*Conclusion*: If shuffled labels or features retain >50% accuracy, there is massive data leakage. If they collapse to ~50%, the pipeline is technically sound, and the baseline edge (if any) was derived from the features mapping to the labels.
