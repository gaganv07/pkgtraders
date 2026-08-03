# ETL Pipeline Validation (PARTIAL VALIDATION)

> [!WARNING]
> **PARTIAL VALIDATION NOTICE**: This ETL validation is a partial validation because 15 out of 21 required datasets are missing. Full timezone alignment checks and symbol alignments are restricted to the available subset.

## ETL Verification Checklist
- [x] **CSV Parsing**: Robust support verified for comma and tab delimiters. Auto-detection functions correctly.
- [x] **Broker-Specific Formatting**: Successfully handled broker formats lacking column headers and using combined date-time in Column 0 (`YYYY.MM.DD HH:MM`).
- [x] **Timestamp Parsing**: Correctly parsed and validated all date/time sequences. Format fallbacks verified.
- [x] **Timezone Consistency**: Enforced UTC timezone alignment on all loaded records during parsing.
- [x] **Missing Values**: Handled corrupt rows by logging and safely skipping, avoiding parse crashes.
- [x] **Symbol & TF Alignment**: Symbol-pooled chronological dataset alignment verified successfully.

## Alignment Profile
| Key | File Size | Parsed Bars | Align Start | Align End |
|---|---|---|---|---|
| EURUSD_H1 | 4.71 MB | 43266 | 2008-09-05 00:00 | 2026-07-20 20:00 |
| GBPUSD_H1 | 4.72 MB | 43352 | 2008-09-05 00:00 | 2026-07-20 20:00 |
| NAS100_M15 | 4.02 MB | 28950 | 2025-04-25 08:15 | 2026-07-20 20:45 |
| US30_M15 | 3.99 MB | 28951 | 2025-04-25 08:15 | 2026-07-20 20:45 |
| USDJPY_M15 | 11.45 MB | 92964 | 2022-10-19 05:15 | 2026-07-20 20:45 |
| XAUUSD_M15 | 13.12 MB | 100004 | 2022-04-21 04:00 | 2026-07-20 20:30 |
