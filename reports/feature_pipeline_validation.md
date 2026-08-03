# Feature & Label Pipeline Validation (PARTIAL VALIDATION)

> [!WARNING]
> **PARTIAL VALIDATION NOTICE**: This feature pipeline audit is a partial validation because 15 symbol/timeframe combinations are missing. Statistics below reflect the available datasets only.

## Execution Summary
- **Total Samples Generated**: 336647
- **Feature Dimensions**: 22 features per sample
- **NaN or Inf Values**: ✅ None
- **Temporal Leakage Audit**: Enforced Z-score Normalization fit on training split only.

## Class Balance (Total Dataset)
- **BUY_EDGE**: 163988 (48.71%)
- **SELL_EDGE**: 163113 (48.45%)
- **NO_EDGE**: 9546 (2.84%)

## Feature Metadata (Sample Metrics)
| Feature Key | Sample Scaled Value |
|---|---|
| f_asia | 1.5266 |
| f_atr_pct | -1.2722 |
| f_body_ratio | 1.0979 |
| f_bull_bar | 0.9780 |
| f_dow_sin | 1.3403 |
| f_ema20_dist | -0.0241 |
| f_ema50_dist | -0.4379 |
| f_ema_gap | -0.7784 |
| f_hour_cos | 1.3937 |
| f_hour_sin | -0.0010 |
| f_london | -0.5099 |
| f_lower_wick | -0.2485 |
| f_ny | -0.4447 |
| f_overlap | -0.4447 |
| f_ret_1 | 1.0276 |
| f_ret_3 | 0.6892 |
| f_rsi | 0.0436 |
| f_sweep | -0.0040 |
| f_upper_wick | -1.1180 |
| f_vwap_dev | 0.0768 |
| symbol | EURUSD_H1 |
| time | 2009-02-24T00:00:00+00:00 |
