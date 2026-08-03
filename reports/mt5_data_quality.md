# MT5 Data Quality Audit (PARTIAL VALIDATION)

> [!WARNING]
> **PARTIAL VALIDATION NOTICE**: This data quality audit is a partial validation because 15 symbol/timeframe combinations are missing. Results below reflect only the available datasets.

## Quality Metrics per Dataset
| Symbol | TF | Total Bars | Quality Score | Duplicates | Non-Pos Prices | Bad OHLC | Order Violations | Zero Volume | Weekend Gaps | Holiday Gaps |
|---|---|---|---|---|---|---|---|---|---|---|
| EURUSD | H1 | 43266 | 100.0% | 0 | 0 | 0 | 0 | 0 | 930 | 2360 |
| GBPUSD | H1 | 43352 | 100.0% | 0 | 0 | 0 | 0 | 0 | 881 | 2157 |
| NAS100 | M15 | 28950 | 100.0% | 0 | 0 | 0 | 0 | 0 | 65 | 263 |
| US30 | M15 | 28951 | 100.0% | 0 | 0 | 0 | 0 | 0 | 65 | 262 |
| USDJPY | M15 | 92964 | 100.0% | 0 | 0 | 0 | 0 | 0 | 196 | 37 |
| XAUUSD | M15 | 100004 | 100.0% | 0 | 0 | 0 | 0 | 0 | 222 | 887 |

## Quality Audit Findings & Interpretation
- **Spread Integrity**: The spread columns in these MT5 exports contain mostly zeroes, implying spread information was not exported or is broker-simulated as zero. A default spread value of 15 points is applied in the pipeline for safety.
- **Volume Integrity**: Zero volume checks returned low anomaly rates across all active datasets.
- **OHLC Integrity**: 0 bad OHLC (High < Low, High < Close/Open, etc.) detected across all parsed bars. Prices remain positive throughout.
