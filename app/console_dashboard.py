"""
app/console_dashboard.py — Real-Time Live Console Dashboard (1Hz Refresh)

Renders a live terminal UI displaying real-time connection status, broker info, account balance,
equity, floating PnL, active trades, spreads, drawdown, CPU/RAM usage, and MT5 state.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False


class ConsoleDashboard:
    """
    Renders live ANSI dashboard output in terminal.
    """

    def __init__(self, orchestrator: Any):
        self.orch = orchestrator
        self._running = False

    def generate_dashboard_text(self) -> str:
        """Generate formatted dashboard string."""
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        # System Metrics
        cpu_pct = psutil.cpu_percent() if PSUTIL_AVAILABLE else 0.0
        ram_pct = psutil.virtual_memory().percent if PSUTIL_AVAILABLE else 0.0

        # Connection & Account
        connector_ok = getattr(self.orch.client, "connected", False)
        conn_str = "CONNECTED" if connector_ok else "DISCONNECTED / SIM"

        acct = self.orch.client.get_account() or {}
        login = acct.get("login", "N/A")
        currency = acct.get("currency", "USD")
        balance = acct.get("balance", 0.0)
        equity = acct.get("equity", 0.0)
        margin = acct.get("margin", 0.0)
        free_margin = acct.get("free_margin", 0.0)
        floating_pnl = acct.get("profit", 0.0)

        # Risk & Drawdown
        risk_summary = self.orch.risk.summary() if hasattr(self.orch, "risk") else {}
        daily_dd = risk_summary.get("daily_dd_pct", 0.0)
        account_dd = risk_summary.get("account_dd_pct", 0.0)
        circuit_broken = risk_summary.get("circuit_broken", False)

        # Open Positions
        active_trades = self.orch.engine.all_active_trades() if hasattr(self.orch, "engine") else []
        open_count = len(active_trades)

        # Symbols & Spreads
        symbols = self.orch._symbols if hasattr(self.orch, "_symbols") else []
        spread_lines = []
        for sym in symbols[:5]:
            md = self.orch.msd.get(sym) if hasattr(self.orch, "msd") else None
            tick = md.latest_tick if md else None
            if tick:
                spread_lines.append(f"{sym:<7} Bid={tick.bid:<9.4f} Ask={tick.ask:<9.4f} Spd={tick.spread_pts:>3}pts")
            else:
                spread_lines.append(f"{sym:<7} N/A")

        spreads_str = " | ".join(spread_lines[:3])

        trade_lines = []
        for t in active_trades:
            trade_lines.append(
                f"   - #{t.ticket} {t.symbol:<6} {t.direction:<5} "
                f"Entry={t.entry_price:<9.4f} Vol={t.volume:<4.2f} "
                f"PnL=${t.unrealized_pnl:>6.2f} ({t.r_multiple:>+4.2f}R)"
            )
        trade_display = "\n".join(trade_lines) if trade_lines else "   (No open positions)"

        lines = [
            "==================================================================================",
            f"   INSTITUTIONAL TRADING BOT — LIVE DASHBOARD | {now_str}",
            "==================================================================================",
            f" Status:       [{conn_str}] | MT5: {'OK' if connector_ok else 'WARN'} | Circuit: {'BROKEN' if circuit_broken else 'OK'}",
            f" Account:      #{login} | Balance: ${balance:,.2f} {currency} | Equity: ${equity:,.2f}",
            f" Floating PnL: ${floating_pnl:>+8.2f} | Free Margin: ${free_margin:,.2f} | Margin: ${margin:,.2f}",
            f" Risk/Drawdown: Daily DD: {daily_dd:.2f}% | Account DD: {account_dd:.2f}% | Open Trades: {open_count}",
            f" System Load:  CPU: {cpu_pct:>4.1f}% | Memory: {ram_pct:>4.1f}%",
            "----------------------------------------------------------------------------------",
            " Live Market Feeds & Spreads:",
            f" {spreads_str}",
            "----------------------------------------------------------------------------------",
            " Active Positions:",
            trade_display,
            "==================================================================================",
        ]
        return "\n".join(lines)

    async def run_loop(self, refresh_interval_s: float = 1.0) -> None:
        """Run console update loop every 1 second."""
        self._running = True
        while self._running:
            try:
                txt = self.generate_dashboard_text()
                # Clear terminal screen ansi sequence
                sys.stdout.write("\033[H\033[J")
                sys.stdout.write(txt + "\n")
                sys.stdout.flush()
            except Exception as e:
                pass
            await asyncio.sleep(refresh_interval_s)

    def stop(self) -> None:
        self._running = False
