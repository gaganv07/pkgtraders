"""
scripts/benchmark_phase6_fleet.py — Comprehensive Resource & Capacity Benchmark

Measures performance across tiers: 1, 2, 3, 5, 10 accounts:
- Total startup time
- Worker startup time
- Terminal provisioning & verification
- Signal fan-out latency (total and per-account)
- Execution queue latency
- Memory (Process RSS MB and system RAM)
- CPU utilization %
- Disk usage on Drive D:
- Session & connection stability
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import psutil

# Ensure project root is in sys.path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from app.multi_account.account_registry import AccountConfig, AccountRegistry
from app.multi_account.account_context import NormalizedSignal
from app.multi_account.account_manager import MT5AccountManager
from app.multi_account.terminal_supervisor import get_terminal_supervisor

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("BenchmarkPhase6")


def get_dir_size_bytes(path: str) -> int:
    """Calculate total size of directory in bytes."""
    total = 0
    if not os.path.exists(path):
        return 0
    for root, dirs, files in os.walk(path):
        for f in files:
            fp = os.path.join(root, f)
            try:
                total += os.path.getsize(fp)
            except OSError:
                pass
    return total


async def benchmark_tier(account_count: int) -> Dict[str, Any]:
    """Run benchmark for a specific account count tier."""
    logger.info(f"--- Running Benchmark for Tier: {account_count} Account(s) ---")
    
    proc = psutil.Process()
    mem_before_mb = proc.memory_info().rss / (1024 * 1024)
    disk_d_usage_before = psutil.disk_usage("D:\\")

    reg = AccountRegistry()
    manager = MT5AccountManager(registry=reg, max_accounts=max(account_count, 10))
    terminal_supervisor = get_terminal_supervisor()

    # 1. Total setup time
    t_start = time.perf_counter()
    term_provision_times = []

    for i in range(account_count):
        acc_id = f"bench_acc_{i+1:03d}"
        t_term_0 = time.perf_counter()
        target_dir = terminal_supervisor.provision_terminal_directory(acc_id)
        term_provision_times.append((time.perf_counter() - t_term_0) * 1000.0)

        cfg = AccountConfig(
            account_id=acc_id,
            login=900000 + i + 1,
            server="BenchmarkServer",
            magic_number=20250000 + i + 1,
            risk_per_trade_pct=1.0,
            initial_balance=1000.0 * (i + 1),
            dry_run=True,
            portable_terminal_directory=str(target_dir),
            terminal_path=str(target_dir / "terminal64.exe"),
        )
        ctx = manager.add_account(cfg)
        # Pre-set snapshot
        ctx.update_snapshot(balance=1000.0 * (i + 1), equity=1000.0 * (i + 1))

    t_configured = time.perf_counter()
    config_time_ms = (t_configured - t_start) * 1000.0

    # 2. Worker startup time
    t_worker_0 = time.perf_counter()
    connect_results = await manager.connect_all()
    worker_startup_ms = (time.perf_counter() - t_worker_0) * 1000.0
    total_startup_ms = (time.perf_counter() - t_start) * 1000.0

    connected_count = sum(1 for res in connect_results.values() if res is True)
    connection_stability_pct = (connected_count / account_count) * 100.0

    # 3. Connection stability probe
    ping_ok_count = 0
    for ctx in manager.get_all_contexts():
        if ctx.session and ctx.session.is_connected():
            ping_ok_count += 1

    # 4. Signal Fan-out Latency
    signal = NormalizedSignal(
        signal_id=f"sig_bench_{account_count}_{int(time.time())}",
        timestamp=datetime.now(timezone.utc),
        symbol="XAUUSD",
        direction="LONG",
        entry_reference=2050.0,
        stop_loss=2040.0,
        take_profit_1=2070.0,
        quality_score=90.0,
    )

    # Prime execution queue and measure latency
    psutil.cpu_percent(interval=None)  # reset cpu counter
    t_fanout_0 = time.perf_counter()
    reports = await manager.distribute_signal(signal)
    fanout_latency_ms = (time.perf_counter() - t_fanout_0) * 1000.0
    cpu_during_fanout = psutil.cpu_percent(interval=0.05)

    successful_executions = sum(1 for r in reports.values() if r.is_success)
    execution_latencies = [r.latency_ms for r in reports.values() if r.latency_ms > 0]
    avg_exec_lat_ms = sum(execution_latencies) / len(execution_latencies) if execution_latencies else 0.0
    max_exec_lat_ms = max(execution_latencies) if execution_latencies else 0.0

    # 5. Memory & Disk Metrics
    mem_after_mb = proc.memory_info().rss / (1024 * 1024)
    mem_delta_mb = mem_after_mb - mem_before_mb

    terminals_base_dir = r"D:\MT5_Terminals"
    disk_terminals_kb = get_dir_size_bytes(terminals_base_dir) / 1024.0

    # 6. Clean disconnect
    await manager.disconnect_all()

    tier_result = {
        "account_count": account_count,
        "total_startup_ms": round(total_startup_ms, 2),
        "avg_terminal_provision_ms": round(sum(term_provision_times) / len(term_provision_times), 2),
        "worker_startup_ms": round(worker_startup_ms, 2),
        "connection_stability_pct": round(connection_stability_pct, 1),
        "responsive_sessions_count": ping_ok_count,
        "signal_fanout_latency_ms": round(fanout_latency_ms, 2),
        "avg_execution_latency_ms": round(avg_exec_lat_ms, 2),
        "max_execution_latency_ms": round(max_exec_lat_ms, 2),
        "successful_executions": successful_executions,
        "process_ram_mb": round(mem_after_mb, 2),
        "ram_delta_mb": round(mem_delta_mb, 2),
        "cpu_peak_pct": round(cpu_during_fanout, 1),
        "terminals_disk_usage_kb": round(disk_terminals_kb, 2),
        "status": "PASS" if (successful_executions == account_count and connection_stability_pct == 100.0) else "FAIL",
    }
    logger.info(
        f"Tier {account_count} Result: Fanout={tier_result['signal_fanout_latency_ms']}ms, "
        f"RAM={tier_result['process_ram_mb']}MB, CPU={tier_result['cpu_peak_pct']}%, "
        f"Success={tier_result['successful_executions']}/{account_count}"
    )
    return tier_result


async def main():
    tiers = [1, 2, 3, 5, 10]
    all_results = {}
    system_spec = {
        "os": "Windows",
        "cpu_count_logical": psutil.cpu_count(logical=True),
        "cpu_count_physical": psutil.cpu_count(logical=False),
        "total_ram_gb": round(psutil.virtual_memory().total / (1024**3), 2),
        "available_ram_gb": round(psutil.virtual_memory().available / (1024**3), 2),
        "disk_d_free_gb": round(psutil.disk_usage("D:\\").free / (1024**3), 2),
        "disk_c_free_mb": round(psutil.disk_usage("C:\\").free / (1024**2), 2),
    }

    logger.info(f"System Specification: {system_spec}")

    for t in tiers:
        res = await benchmark_tier(t)
        all_results[f"{t}_accounts"] = res
        # Brief pause between tiers
        await asyncio.sleep(0.5)

    final_report = {
        "benchmark_timestamp": datetime.now(timezone.utc).isoformat(),
        "system_spec": system_spec,
        "tiers": all_results,
    }

    out_path = Path(ROOT) / "reports" / "fleet_benchmark_results.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(final_report, f, indent=2)

    logger.info(f"Benchmark results successfully saved to: {out_path}")
    print("\n=== BENCHMARK SUMMARY TABLE ===")
    print(f"{'Accounts':<10}{'Startup (ms)':<15}{'Fanout (ms)':<15}{'Avg Lat (ms)':<15}{'RAM (MB)':<12}{'CPU %':<10}{'Stability':<10}")
    print("-" * 87)
    for t in tiers:
        d = all_results[f"{t}_accounts"]
        print(
            f"{d['account_count']:<10}"
            f"{d['total_startup_ms']:<15}"
            f"{d['signal_fanout_latency_ms']:<15}"
            f"{d['avg_execution_latency_ms']:<15}"
            f"{d['process_ram_mb']:<12}"
            f"{d['cpu_peak_pct']:<10}"
            f"{d['connection_stability_pct']:<10}%"
        )


if __name__ == "__main__":
    asyncio.run(main())
