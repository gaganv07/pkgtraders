# Replay Data Integrity Report: Root-Cause Analysis

This report documents the audit and root-cause analysis of the trade lifecycle data integrity issues in `strategy_audit.py`.

---

## 1. Why `exit_time` is Missing

We identified three primary reasons why `exit_time` is missing from the exported datasets:

1. **Missing Key in `exec_log`**:
   In `strategy_audit.py` (around line 415), the callback `on_close(trade)` logs completed trades into `exec_log`. However, the dictionary schema appended to `exec_log` did not include an `exit_time` key at all. It only recorded `holding_secs` and `timestamp` (representing entry time).
   
2. **Backfill Copy-Paste Bug**:
   At the end of the replay loop (around lines 809–817), the script backfills trade results for accepted signals in `signals_log`. The backfill logic was:
   ```python
   sig["profit_proxy"]  = m["profit"]
   sig["exit_time_proxy"] = str(m.get("exit_price", "NULL"))
   ```
   * First, `exit_time_proxy` was set to `exit_price` instead of the exit time.
   * Second, the actual standard `exit_time` (and other fields like `exit_price`, `entry_price`, `R_multiple`, `close_reason`) were never copied or backfilled into the signal records.

3. **Stale Brain Directory Path**:
   The `brain_dir` path on line 825 of `strategy_audit.py` was hardcoded to a stale conversation ID:
   `brain_dir = r"C:\Users\LENOVO\.gemini\antigravity-ide\brain\65acb589-3828-4e69-9f4c-cd4071acc3e8"`
   This prevented the updated files from correctly syncing to the active conversation's artifact directory (`86515f4f-c227-440d-8805-95d41e87d7aa`), causing verification/downstream tools (like `ab_validation.py`) to read stale or empty data.

---

## 2. Why Completed Trades are Not Written Correctly

* **`executed_trades.csv`**:
  This file is generated directly from `exec_log`. Because `exec_log` was missing crucial keys (`exit_time`, `entry_time`, `pnl`, `entry_price`, `exit_price`), these columns were not exported to the CSV.
* **`signals.csv`**:
  For accepted signals, they are added to `signals_log` at entry time (before the trade outcome is simulated). Because the backfill loop only updated `profit_proxy` and `exit_time_proxy` (which itself was buggy), the main lifecycle columns (`exit_time`, `exit_price`, `entry`, `sl`, `tp3`, `volume`, `risk_usd`, `R_multiple`, `close_reason`) remained at their default `NULL` or empty values.

---

## 3. Consistency of Close Reasons

We audited the simulation engine and verified how the different close conditions are processed:

* **TP Hit**:
  * **Simulation**: Checked in `_check_exits(sym, tick, t)`. If hit, records `"TP"` in `exit_info`.
  * **Processing**: Finalized by `TradeEngine._finalize` -> `on_close(trade)`. Overrides `trade.close_reason` with `"TP"`.
  * **Consistency**: **Consistent**.
  
* **SL Hit**:
  * **Simulation**: Checked in `_check_exits(sym, tick, t)`. If hit, records `"SL"` in `exit_info`.
  * **Processing**: Finalized by `TradeEngine._finalize` -> `on_close(trade)`. Overrides `trade.close_reason` with `"SL"`.
  * **Consistency**: **Consistent**.

* **Manual Close**:
  * **Simulation**: Not actively triggered during offline replay since replay is hands-off.
  * **Processing**: Finalized via `_finalize` if triggered, defaulting to `"MT5_CLOSE"` if no exit info exists.
  * **Consistency**: **Consistent**.

* **Timeout Close**:
  * **Simulation**: Checked in `_manage` when `t.age_h >= max_trade_dur_h` and `current_r < 0`.
  * **Processing**: Calls `_force_close(..., "TIME_STOP")` -> `_finalize(..., "TIME_STOP")`. Since `exit_info` is empty, the reason remains `"TIME_STOP"`.
  * **Consistency**: **Consistent**.

* **End-of-Data Close**:
  * **Simulation**: Forced at the end of the replay loop for any remaining positions in `client._replayed_positions`.
  * **Processing**: Calls `engine._finalize(..., "EOW_CLOSE")`.
  * **Consistency**: **Consistent**.

---

## Conclusion & Action Plan

To establish complete trade lifecycle data integrity, we will apply the following fixes in **Phase 3**:
1. Update `exec_log` dictionary creation in `on_close` to include all lifecycle keys: `entry_time`, `exit_time`, `entry_price`, `exit_price`, `pnl`, `R_multiple`, `close_reason` (in addition to legacy mappings).
2. Fix the backfill loop in `strategy_audit.py` to copy all lifecycle parameters from `exec_log` to `signals_log` for accepted signals.
3. Make `brain_dir` dynamically resolve using command-line arguments, environment variables, or fallback to the current conversation ID.
4. Regenerate the datasets and run validation scripts.
