"""
reports/generator.py — Performance Report Generator

Generates:
  - Daily / Weekly / Monthly performance summaries
  - CSV export of trades and daily stats
  - PDF reports (requires reportlab)
  - Full analytics: Sharpe, Sortino, Calmar, Recovery Factor, Expectancy
"""

from __future__ import annotations

import csv
import logging
import math
import statistics
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.platypus import (
        SimpleDocTemplate, Table, TableStyle,
        Paragraph, Spacer,
    )
    from reportlab.lib.styles import getSampleStyleSheet
    _PDF = True
except ImportError:
    _PDF = False


class ReportGenerator:
    """Generates all performance reports from SQLite trade data."""

    def __init__(self, report_dir: str = "reports"):
        self._dir = Path(report_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    # ── Daily ─────────────────────────────────────────────────────

    def generate_daily(self, db, date: Optional[str] = None) -> Dict[str, Any]:
        """Compute + persist daily stats. Returns stats dict."""
        if date is None:
            date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        stats = db.compute_daily_stats(date)
        if stats:
            logger.info(
                f"Daily report {date}: {stats['total_trades']} trades "
                f"PnL=${stats['net_pnl']:+.2f} WR={stats['win_rate']:.1f}%"
            )
            self.write_daily_markdown_report(stats, date)
        return stats or {}

    def write_daily_markdown_report(self, stats: Dict[str, Any], date_str: str) -> str:
        out_dir = self._dir / "daily_reports"
        out_dir.mkdir(parents=True, exist_ok=True)
        file_path = out_dir / f"daily_{date_str.replace('-', '')}.md"

        content = f"""# Daily Performance Report — {date_str}

Generated: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")}

- **Total Trades**: {stats.get('total_trades', 0)}
- **Winning Trades**: {stats.get('winning', 0)} | **Losing Trades**: {stats.get('losing', 0)}
- **Win Rate**: {stats.get('win_rate', 0.0):.1f}%
- **Gross Profit**: ${stats.get('gross_profit', 0.0):.2f}
- **Gross Loss**: ${stats.get('gross_loss', 0.0):.2f}
- **Net PnL**: ${stats.get('net_pnl', 0.0):+.2f}
- **Profit Factor**: {stats.get('profit_factor', 0.0):.2f}
- **Max Drawdown**: ${stats.get('max_drawdown', 0.0):.2f}
- **Average Quality Score**: {stats.get('avg_quality', 0.0):.1f}
- **Average Latency**: {stats.get('avg_latency_ms', 0.0):.1f} ms
- **Average Slippage**: {stats.get('avg_slippage', 0.0):.2f} pts
"""
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        logger.info(f"Daily markdown report written to {file_path}")
        return str(file_path)

    def generate_weekly(self, db) -> Dict[str, Any]:
        """Aggregate last 7 days of daily stats."""
        stats = db.get_daily_stats(7)
        if not stats:
            return {}
        agg = self._aggregate(stats, "weekly")
        week_str = datetime.now(timezone.utc).strftime("%Y_W%U")
        self.write_weekly_markdown_report(agg, week_str)
        return agg

    def write_weekly_markdown_report(self, stats: Dict[str, Any], week_str: str) -> str:
        out_dir = self._dir / "weekly_reports"
        out_dir.mkdir(parents=True, exist_ok=True)
        file_path = out_dir / f"weekly_{week_str}.md"

        content = f"""# Weekly Performance Report — {week_str}

Generated: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")}

- **Total Trades**: {stats.get('total_trades', 0)}
- **Win Rate**: {stats.get('win_rate', 0.0):.1f}% ({stats.get('winning', 0)} W / {stats.get('losing', 0)} L)
- **Net PnL**: ${stats.get('net_pnl', 0.0):+.2f}
- **Profit Factor**: {stats.get('profit_factor', 0.0):.2f}
- **Average Quality**: {stats.get('avg_quality', 0.0):.1f}
"""
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        logger.info(f"Weekly markdown report written to {file_path}")
        return str(file_path)

    def generate_monthly(self, db) -> Dict[str, Any]:
        """Aggregate last 30 days."""
        stats = db.get_daily_stats(30)
        if not stats:
            return {}
        agg = self._aggregate(stats, "monthly")
        month_str = datetime.now(timezone.utc).strftime("%Y_%m")
        self.write_monthly_markdown_report(agg, month_str)
        return agg

    def write_monthly_markdown_report(self, stats: Dict[str, Any], month_str: str) -> str:
        out_dir = self._dir / "monthly_reports"
        out_dir.mkdir(parents=True, exist_ok=True)
        file_path = out_dir / f"monthly_{month_str}.md"

        content = f"""# Monthly Performance Report — {month_str}

Generated: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")}

- **Total Trades**: {stats.get('total_trades', 0)}
- **Win Rate**: {stats.get('win_rate', 0.0):.1f}% ({stats.get('winning', 0)} W / {stats.get('losing', 0)} L)
- **Net PnL**: ${stats.get('net_pnl', 0.0):+.2f}
- **Profit Factor**: {stats.get('profit_factor', 0.0):.2f}
- **Average Quality**: {stats.get('avg_quality', 0.0):.1f}
"""
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        logger.info(f"Monthly markdown report written to {file_path}")
        return str(file_path)

    def _aggregate(self, stats: List[Dict], label: str) -> Dict:
        tt  = sum(s.get("total_trades", 0) for s in stats)
        win = sum(s.get("winning", 0) for s in stats)
        gp  = sum(s.get("gross_profit", 0) for s in stats)
        gl  = sum(s.get("gross_loss", 0) for s in stats)
        pnl = gp - gl
        return {
            "period":       label,
            "total_trades": tt,
            "winning":      win,
            "losing":       tt - win,
            "gross_profit": round(gp, 2),
            "gross_loss":   round(gl, 2),
            "net_pnl":      round(pnl, 2),
            "win_rate":     round(win / tt * 100, 1) if tt else 0,
            "profit_factor": round(gp / gl, 2) if gl > 0 else 0,
            "avg_quality":  round(
                statistics.mean(s.get("avg_quality", 0) for s in stats), 1
            ),
        }

    # ── CSV ───────────────────────────────────────────────────────

    def export_trades_csv(
        self, trades: List[Dict], filename: Optional[str] = None
    ) -> str:
        if filename is None:
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            filename = f"trades_{ts}.csv"
        path = self._dir / filename
        fields = [
            "id", "ticket", "symbol", "direction", "status",
            "entry_price", "entry_time", "close_price", "close_time",
            "close_reason", "volume", "initial_vol", "risk_usd",
            "quality_score", "atr_entry", "sl", "tp1", "tp2", "tp3",
            "realized_pnl", "spread_entry", "latency_ms", "slippage",
            "tp1_done", "tp2_done", "breakeven_done", "trailing_active",
        ]
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(trades)
        logger.info(f"Exported {len(trades)} trades → {path}")
        return str(path)

    def export_daily_csv(
        self, stats: List[Dict], filename: Optional[str] = None
    ) -> str:
        if filename is None:
            ts = datetime.now(timezone.utc).strftime("%Y%m%d")
            filename = f"daily_stats_{ts}.csv"
        path = self._dir / filename
        if not stats:
            return str(path)
        fields = [
            "date", "total_trades", "winning", "losing",
            "gross_profit", "gross_loss", "net_pnl",
            "win_rate", "profit_factor", "avg_quality",
            "avg_latency_ms", "avg_slippage",
            "max_drawdown", "sharpe", "sortino",
        ]
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(stats)
        logger.info(f"Exported {len(stats)} daily rows → {path}")
        return str(path)

    # ── Full analytics ────────────────────────────────────────────

    def full_analytics(self, trades: List[Dict]) -> Dict[str, Any]:
        """Compute comprehensive metrics from a trade list."""
        closed = [t for t in trades if t.get("status") == "CLOSED"]
        if not closed:
            return {}

        pnls   = [t.get("realized_pnl", 0) or 0 for t in closed]
        wins   = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        gp     = sum(wins)
        gl     = abs(sum(losses))
        n      = len(closed)

        # Equity curve
        equity = 10000.0
        peak   = equity
        max_dd = 0.0
        dd_pct = 0.0
        for p in pnls:
            equity += p
            peak = max(peak, equity)
            dd   = peak - equity
            max_dd = max(max_dd, dd)
        dd_pct = max_dd / 10000.0 * 100

        # Sharpe / Sortino
        sharpe = sortino = calmar = recovery = 0.0
        if len(pnls) > 1:
            mu  = statistics.mean(pnls)
            std = statistics.stdev(pnls)
            if std > 0:
                sharpe = mu / std * math.sqrt(252)
            neg = [p for p in pnls if p < 0]
            if len(neg) > 1:
                ds = statistics.stdev(neg)
                if ds > 0:
                    sortino = mu / ds * math.sqrt(252)

        final_pnl = sum(pnls)
        if max_dd > 0:
            calmar   = final_pnl / max_dd
            recovery = final_pnl / max_dd

        return {
            "total_trades":    n,
            "winning_trades":  len(wins),
            "losing_trades":   len(losses),
            "win_rate":        round(len(wins) / n * 100, 1),
            "gross_profit":    round(gp, 2),
            "gross_loss":      round(gl, 2),
            "net_pnl":         round(final_pnl, 2),
            "profit_factor":   round(gp / gl, 2) if gl > 0 else 0,
            "avg_win":         round(statistics.mean(wins), 2) if wins else 0,
            "avg_loss":        round(statistics.mean(losses), 2) if losses else 0,
            "largest_win":     round(max(wins), 2) if wins else 0,
            "largest_loss":    round(min(losses), 2) if losses else 0,
            "expectancy":      round(final_pnl / n, 2),
            "max_drawdown":    round(max_dd, 2),
            "max_dd_pct":      round(dd_pct, 2),
            "sharpe":          round(sharpe, 3),
            "sortino":         round(sortino, 3),
            "calmar":          round(calmar, 3),
            "recovery_factor": round(recovery, 3),
            "avg_quality":     round(
                statistics.mean(t.get("quality_score", 0) or 0 for t in closed), 1
            ),
            "avg_latency_ms":  round(
                statistics.mean(t.get("latency_ms", 0) or 0 for t in closed), 1
            ),
        }

    # ── PDF ───────────────────────────────────────────────────────

    def export_pdf(
        self,
        trades: List[Dict],
        stats_list: List[Dict],
        title: str = "XAUUSD Pro Scalper — Performance Report",
    ) -> Optional[str]:
        if not _PDF:
            logger.warning("reportlab not installed — PDF unavailable")
            return None

        ts   = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        path = self._dir / f"report_{ts}.pdf"
        doc  = SimpleDocTemplate(str(path), pagesize=A4)
        sty  = getSampleStyleSheet()
        story: list = []

        story.append(Paragraph(title, sty["Title"]))
        story.append(Paragraph(
            f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
            sty["Normal"],
        ))
        story.append(Spacer(1, 16))

        # Summary
        analytics = self.full_analytics(trades)
        if analytics:
            story.append(Paragraph("Performance Summary", sty["Heading2"]))
            tbl_data = [
                ["Metric", "Value"],
                ["Total Trades",    str(analytics["total_trades"])],
                ["Win Rate",        f"{analytics['win_rate']:.1f}%"],
                ["Net P&L",         f"${analytics['net_pnl']:+,.2f}"],
                ["Profit Factor",   f"{analytics['profit_factor']:.2f}"],
                ["Sharpe Ratio",    f"{analytics['sharpe']:.3f}"],
                ["Sortino Ratio",   f"{analytics['sortino']:.3f}"],
                ["Max Drawdown",    f"${analytics['max_drawdown']:,.2f} ({analytics['max_dd_pct']:.1f}%)"],
                ["Recovery Factor", f"{analytics['recovery_factor']:.2f}"],
                ["Expectancy",      f"${analytics['expectancy']:+.2f}"],
                ["Avg Quality",     f"{analytics['avg_quality']:.0f}/100"],
                ["Avg Latency",     f"{analytics['avg_latency_ms']:.0f}ms"],
            ]
            t = Table(tbl_data, colWidths=[200, 200])
            t.setStyle(TableStyle([
                ("BACKGROUND",  (0, 0), (-1, 0), colors.HexColor("#1f6feb")),
                ("TEXTCOLOR",   (0, 0), (-1, 0), colors.white),
                ("FONTSIZE",    (0, 0), (-1, -1), 10),
                ("GRID",        (0, 0), (-1, -1), 0.5, colors.HexColor("#30363d")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1),
                 [colors.HexColor("#161b22"), colors.HexColor("#0d1117")]),
                ("TEXTCOLOR",   (0, 1), (-1, -1), colors.HexColor("#e6edf3")),
                ("ALIGN",       (1, 0), (-1, -1), "RIGHT"),
            ]))
            story.append(t)
            story.append(Spacer(1, 20))

        # Daily stats table
        if stats_list:
            story.append(Paragraph("Daily Statistics (Last 30 Days)", sty["Heading2"]))
            hdrs = ["Date", "Trades", "W/L", "Net P&L", "Win%", "PF", "Sharpe"]
            rows = [hdrs] + [
                [
                    s.get("date", ""),
                    str(s.get("total_trades", 0)),
                    f"{s.get('winning',0)}/{s.get('losing',0)}",
                    f"${s.get('net_pnl', 0):+,.2f}",
                    f"{s.get('win_rate', 0):.0f}%",
                    f"{s.get('profit_factor', 0):.2f}",
                    f"{s.get('sharpe', 0):.3f}",
                ]
                for s in stats_list[:30]
            ]
            t2 = Table(rows, colWidths=[70, 50, 50, 80, 50, 50, 60])
            t2.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f6feb")),
                ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
                ("FONTSIZE",   (0, 0), (-1, -1), 9),
                ("GRID",       (0, 0), (-1, -1), 0.5, colors.HexColor("#30363d")),
            ]))
            story.append(t2)

        doc.build(story)
        logger.info(f"PDF report: {path}")
        return str(path)
