"""
dashboard/control_center.py — Legacy Asset Partners AI Trading Control Center Backend

FastAPI + WebSockets read-only telemetry engine providing 1Hz real-time stream,
REST analytics endpoints, PDF/Excel report exports, and system health metrics.

STRICT READ-ONLY GUARANTEE:
- Never submits order requests to MT5.
- Never modifies existing positions or parameters.
"""

from __future__ import annotations

import asyncio
import csv
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import psutil
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response

from dashboard.reports_exporter import ReportsExporter

logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent
REPORTS_DIR = ROOT / "reports"
JOURNAL_CSV = REPORTS_DIR / "live_trade_journal.csv"
EQUITY_CSV  = REPORTS_DIR / "equity_curve.csv"
ANALYTICS_JSON = REPORTS_DIR / "execution_analytics.json"
HEALTH_JSON    = REPORTS_DIR / "health_report.json"

app = FastAPI(title="Legacy Asset Partners — AI Trading Control Center", version="3.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
)

_orchestrator = None


def attach_orchestrator(orch: Any) -> None:
    """Attach live system orchestrator instance (read-only reference)."""
    global _orchestrator
    _orchestrator = orch


# ── Active WebSockets Manager ─────────────────────────────────────────────────

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        for connection in list(self.active_connections):
            try:
                await connection.send_text(message)
            except Exception:
                self.disconnect(connection)


ws_manager = ConnectionManager()


# ── Helpers for Reading Bot State & Artifacts ─────────────────────────────────

def _get_live_telemetry() -> Dict[str, Any]:
    """Gather complete read-only state snapshot."""
    now_utc = datetime.now(timezone.utc).isoformat()

    # 1. Account & Connection Status
    account_info = {}
    mt5_status = "DISCONNECTED"
    if _orchestrator and hasattr(_orchestrator, "client"):
        account_info = _orchestrator.client.get_account() or {}
        mt5_status = "CONNECTED" if getattr(_orchestrator.client, "connected", False) else "DISCONNECTED"
    else:
        # Try reading health json fallback
        if HEALTH_JSON.exists():
            try:
                with open(HEALTH_JSON, "r", encoding="utf-8") as f:
                    hdata = json.load(f)
                    mt5_status = "CONNECTED" if hdata.get("mt5_connected") else "DISCONNECTED"
            except Exception:
                pass

    # 2. Financial Metrics & Analytics
    analytics_data = {}
    if ANALYTICS_JSON.exists():
        try:
            with open(ANALYTICS_JSON, "r", encoding="utf-8") as f:
                analytics_data = json.load(f)
        except Exception:
            pass

    # 3. Open Positions
    open_positions = []
    if _orchestrator and hasattr(_orchestrator, "engine"):
        trades = _orchestrator.engine.all_active_trades()
        for t in trades:
            md = _orchestrator.msd.get(t.symbol) if hasattr(_orchestrator, "msd") else None
            tick = md.latest_tick if md else None
            curr_price = tick.bid if t.direction == "LONG" and tick else (tick.ask if tick else t.entry_price)
            
            pnl_usd = t.unrealized_pnl
            open_positions.append({
                "trade_id": t.trade_id,
                "ticket": t.ticket,
                "symbol": t.symbol,
                "direction": t.direction,
                "entry_price": t.entry_price,
                "current_price": curr_price,
                "sl": t.sl,
                "tp1": t.tp1,
                "tp2": t.tp2,
                "breakeven_status": getattr(t, "breakeven_done", False),
                "trailing_status": getattr(t, "trailing_active", False),
                "pnl_usd": round(pnl_usd, 2),
                "pnl_pct": round((pnl_usd / account_info.get("balance", 1.0) * 100.0) if account_info.get("balance", 0) > 0 else 0.0, 2),
                "risk_usd": round(t.risk_usd, 2),
                "volume": t.volume,
                "ai_score": t.quality_score,
                "entry_time": t.entry_time.isoformat() if t.entry_time else "",
                "holding_time_s": round(t.age_h * 3600.0, 1),
                "spread_pts": t.spread_entry,
                "atr": t.atr_entry,
                "rsi": 50.0,
                "ema20": 0.0,
                "ema50": 0.0,
                "vwap": 0.0,
                "strategy_name": "Institutional Microstructure Scalper",
                "magic": getattr(_orchestrator.engine, "_cfg", None).magic if hasattr(_orchestrator.engine, "_cfg") else 20250701,
            })

    # 4. System Resource Usage
    cpu_pct = psutil.cpu_percent()
    mem = psutil.virtual_memory()

    # 5. Risk & Circuit Breaker State
    risk_summary = _orchestrator.risk.summary() if (_orchestrator and hasattr(_orchestrator, "risk")) else {}

    return {
        "timestamp": now_utc,
        "connection": {
            "mt5_status": mt5_status,
            "internet_status": "ONLINE",
            "broker": account_info.get("broker", "Black Bull Group Limited"),
            "server": account_info.get("server", "BlackBullMarkets-Demo"),
            "account_number": account_info.get("login", 907901),
        },
        "account": {
            "balance": round(account_info.get("balance", 1149.97), 2),
            "equity": round(account_info.get("equity", 1149.97), 2),
            "free_margin": round(account_info.get("free_margin", 1149.97), 2),
            "margin": round(account_info.get("margin", 0.0), 2),
            "margin_level": round(account_info.get("margin_level", 0.0), 1),
            "floating_pnl": round(account_info.get("profit", 0.0), 2),
            "currency": account_info.get("currency", "USD"),
        },
        "risk": {
            "daily_loss_limit_pct": 3.0,
            "daily_dd_pct": risk_summary.get("daily_dd_pct", 0.0),
            "account_dd_pct": risk_summary.get("account_dd_pct", 0.0),
            "max_account_dd_pct": 15.0,
            "open_risk_pct": risk_summary.get("current_exposure_pct", 0.0),
            "circuit_breaker": risk_summary.get("circuit_broken", False),
            "news_blackout": False,
            "weekend_protection": False,
        },
        "kpis": analytics_data,
        "open_positions": open_positions,
        "system": {
            "cpu_pct": cpu_pct,
            "ram_pct": mem.percent,
            "ram_mb": round(mem.used / 1024 / 1024, 1),
            "disk_pct": psutil.disk_usage("/").percent,
        },
    }


def _read_trade_journal(limit: int = 200, search: str = "", symbol: str = "") -> List[Dict[str, Any]]:
    """Read trade history entries from CSV journal."""
    trades = []
    if not JOURNAL_CSV.exists():
        return trades

    try:
        with open(JOURNAL_CSV, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Apply filters
                if symbol and row.get("symbol", "").upper() != symbol.upper():
                    continue
                if search:
                    row_str = " ".join(row.values()).lower()
                    if search.lower() not in row_str:
                        continue
                trades.append(row)
    except Exception as e:
        logger.error(f"Error reading trade journal: {e}")

    return trades[-limit:][::-1]


# ── REST API Endpoints ────────────────────────────────────────────────────────

@app.get("/api/v2/overview")
async def get_overview():
    return _get_live_telemetry()


@app.get("/api/v2/live_trades")
async def get_live_trades():
    telemetry = _get_live_telemetry()
    return telemetry.get("open_positions", [])


@app.get("/api/v2/trade_history")
async def get_trade_history(
    limit: int = Query(200, le=1000),
    search: str = Query(""),
    symbol: str = Query(""),
):
    return _read_trade_journal(limit=limit, search=search, symbol=symbol)


@app.get("/api/v2/symbol_analytics")
async def get_symbol_analytics():
    trades = _read_trade_journal(limit=1000)
    symbols = ["BTCUSD", "XAUUSD", "EURUSD", "GBPUSD", "USDJPY", "NAS100", "US30"]
    result = {}

    for sym in symbols:
        sym_trades = [t for t in trades if t.get("symbol", "").upper() == sym]
        count = len(sym_trades)
        pnls = [float(t.get("pnl", 0.0)) for t in sym_trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        
        result[sym] = {
            "symbol": sym,
            "trades": count,
            "wins": len(wins),
            "losses": len(losses),
            "win_rate_pct": round(len(wins) / count * 100.0, 1) if count > 0 else 0.0,
            "net_profit_usd": round(sum(pnls), 2),
            "profit_factor": round(sum(wins) / abs(sum(losses)), 2) if abs(sum(losses)) > 0 else 0.0,
            "avg_r": round(float(np.mean([float(t.get("r_multiple", 0.0)) for t in sym_trades])), 2) if sym_trades else 0.0,
            "avg_spread_pts": round(float(np.mean([float(t.get("spread_pts", 0.0)) for t in sym_trades])), 1) if sym_trades else 0.0,
        }

    return result


@app.get("/api/v2/health")
async def get_health():
    telemetry = _get_live_telemetry()
    return {
        "healthy": telemetry["connection"]["mt5_status"] == "CONNECTED",
        "mt5_status": telemetry["connection"]["mt5_status"],
        "internet_status": telemetry["connection"]["internet_status"],
        "system": telemetry["system"],
        "timestamp": telemetry["timestamp"],
    }


# ── PDF & Excel Exporters ─────────────────────────────────────────────────────

@app.get("/api/v2/export/excel")
async def export_excel():
    trades = _read_trade_journal(limit=1000)
    analytics = _get_live_telemetry().get("kpis", {})
    symbol_stats = await get_symbol_analytics()

    excel_bytes = ReportsExporter.generate_excel_report(trades, analytics, [], symbol_stats)
    filename = f"LAP_Control_Center_Report_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.xlsx"
    return Response(
        content=excel_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.get("/api/v2/export/pdf")
async def export_pdf(range_title: str = Query("Continuous Live Demo Validation")):
    trades = _read_trade_journal(limit=1000)
    analytics = _get_live_telemetry().get("kpis", {})
    symbol_stats = await get_symbol_analytics()

    pdf_bytes = ReportsExporter.generate_pdf_report(range_title, trades, analytics, symbol_stats)
    filename = f"LAP_Audit_Report_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ── WebSockets Real-Time Stream (1Hz) ─────────────────────────────────────────

@app.websocket("/ws/live")
async def websocket_live_telemetry(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        while True:
            telemetry = _get_live_telemetry()
            await websocket.send_text(json.dumps(telemetry))
            await asyncio.sleep(1.0)
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        ws_manager.disconnect(websocket)


# ── Main Single-Page App HTML Route ───────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def serve_control_center():
    template_path = Path(__file__).parent / "templates" / "control_center.html"
    if template_path.exists():
        with open(template_path, "r", encoding="utf-8") as f:
            return HTMLResponse(f.read())
    return HTMLResponse("<h1>Control Center Template Loading...</h1>")
