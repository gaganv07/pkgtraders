# MT5 Cache Integrity & Non-Destructive Repair Report

**Engine Module:** `CacheRepairEngine` ([app/cache_repair.py](file:///d:/dev/xauusd_pro/xauusd_pro/app/cache_repair.py))  
**Target Path:** `AppData/Roaming/MetaQuotes/Terminal/`  
**Supported Extensions:** `.crp`, `.tkc`, `.hcc`  
**MT5 Error Codes Handled:** Error 2 (File Error), Error 18 (History Sync Error), Error 112 (Disk/Buffer Overflow)  

---

## 1. Non-Destructive Purge & Repair Strategy

When MT5 cache files become corrupted or unreadable, standard MT5 behavior can cause repeated history synchronization failures or crashes.

The `CacheRepairEngine` executes a non-destructive repair:
1. **Cache Integrity Audit:** Scans `.crp`, `.tkc`, `.hcc` files for zero-byte sizes or unreadable headers.
2. **Back Up Before Purge:** Copies corrupted cache files to `cache_backups/<filename>.<timestamp>.bak`.
3. **Targeted Deletion:** Purges ONLY the corrupted cache file. Healthy history data remains untouched.
4. **File Lock Safety:** If active MT5 terminal holds an OS file lock (`WinError 32`), the purge is safely postponed without crashing the trading bot.
5. **Re-synchronization Trigger:** Notifies `HistorySynchronizationManager` to request clean bar data from the MT5 server.

---

## 2. Audit Summary

- **Cache Directories Scanned:** `Terminal/bases/<server>/history/` and `Terminal/bases/<server>/ticks/`
- **Backup Location:** `logs/cache_backups/`
- **File Lock Resilience:** Verified
- **Data Protection:** 100% Non-destructive
