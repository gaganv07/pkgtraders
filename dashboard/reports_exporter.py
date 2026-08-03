"""
dashboard/reports_exporter.py — Institutional PDF & Excel Report Exporter

Generates PDF and Excel reports for Daily, Weekly, Monthly, Yearly, and Custom date ranges.
"""

from __future__ import annotations

import io
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)

try:
    from reportlab.lib.pagesizes import letter, A4
    from reportlab.lib import colors
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
    )
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False


class ReportsExporter:
    """
    Generates Excel and PDF reports from trade journal and database records.
    """

    @staticmethod
    def generate_excel_report(
        trades: List[Dict[str, Any]],
        analytics: Dict[str, Any],
        daily_stats: List[Dict[str, Any]],
        symbol_stats: Dict[str, Any],
    ) -> bytes:
        """
        Generate a multi-tab Excel spreadsheet containing:
        1. Performance Summary
        2. Trade Journal
        3. Symbol Breakdown
        4. Daily Statistics
        """
        output = io.BytesIO()

        summary_data = [
            {"Metric": "Generated Date", "Value": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")},
            {"Metric": "Total Trades", "Value": analytics.get("total_trades", len(trades))},
            {"Metric": "Win Rate (%)", "Value": analytics.get("win_rate_pct", 0.0)},
            {"Metric": "Net Profit ($)", "Value": analytics.get("total_pnl", 0.0)},
            {"Metric": "Profit Factor", "Value": analytics.get("profit_factor", 0.0)},
            {"Metric": "Expectancy ($)", "Value": analytics.get("expectancy_usd", 0.0)},
            {"Metric": "Max Drawdown ($)", "Value": analytics.get("max_drawdown_usd", 0.0)},
            {"Metric": "Max Drawdown (%)", "Value": analytics.get("max_drawdown_pct", 0.0)},
            {"Metric": "Recovery Factor", "Value": analytics.get("recovery_factor", 0.0)},
            {"Metric": "Sharpe Ratio", "Value": analytics.get("sharpe_ratio", 0.0)},
            {"Metric": "Sortino Ratio", "Value": analytics.get("sortino_ratio", 0.0)},
            {"Metric": "Execution Success Rate (%)", "Value": analytics.get("execution_success_rate_pct", 100.0)},
        ]
        df_summary = pd.DataFrame(summary_data)

        if trades:
            df_trades = pd.DataFrame(trades)
        else:
            df_trades = pd.DataFrame([{"Message": "No trades recorded"}])

        try:
            with pd.ExcelWriter(output, engine="openpyxl") as writer:
                df_summary.to_excel(writer, sheet_name="Summary", index=False)
                df_trades.to_excel(writer, sheet_name="Trade Journal", index=False)
                if symbol_stats:
                    sym_rows = [{"Symbol": k, "Net Profit ($)": v} for k, v in symbol_stats.items()]
                    pd.DataFrame(sym_rows).to_excel(writer, sheet_name="Symbol Breakdown", index=False)
        except Exception:
            # Fallback to CSV format in BytesIO if openpyxl engine is unavailable
            csv_str = df_summary.to_csv(index=False) + "\n\n" + df_trades.to_csv(index=False)
            output = io.BytesIO(csv_str.encode("utf-8"))

        output.seek(0)
        return output.getvalue()

    @staticmethod
    def generate_pdf_report(
        title: str,
        trades: List[Dict[str, Any]],
        analytics: Dict[str, Any],
        symbol_stats: Dict[str, Any],
    ) -> bytes:
        """
        Generate a PDF report using ReportLab.
        """
        if not REPORTLAB_AVAILABLE:
            # Fallback simple text buffer if reportlab is not installed
            buffer = io.BytesIO()
            txt = f"PDF Report: {title}\nGenerated: {datetime.now(timezone.utc)}\nTotal Trades: {len(trades)}\n"
            buffer.write(txt.encode("utf-8"))
            buffer.seek(0)
            return buffer.getvalue()

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
        styles = getSampleStyleSheet()

        title_style = ParagraphStyle(
            "DocTitle",
            parent=styles["Title"],
            fontName="Helvetica-Bold",
            fontSize=18,
            leading=22,
            textColor=colors.HexColor("#00e5ff"),
            alignment=0,
        )
        heading_style = ParagraphStyle(
            "Heading2Custom",
            parent=styles["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=12,
            leading=16,
            textColor=colors.HexColor("#e6edf3"),
            spaceBefore=12,
            spaceAfter=6,
        )
        normal_style = ParagraphStyle(
            "NormalCustom",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=9,
            leading=12,
            textColor=colors.HexColor("#8b949e"),
        )

        elements = []
        elements.append(Paragraph("LEGACY ASSET PARTNERS", title_style))
        elements.append(Paragraph(f"AI TRADING CONTROL CENTER — {title.upper()}", heading_style))
        elements.append(Paragraph(f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')} | Confidential Institutional Audit", normal_style))
        elements.append(Spacer(1, 10))
        elements.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#30363d"), spaceAfter=15))

        # Overview Table
        elements.append(Paragraph("Performance & Analytics Overview", heading_style))
        summary_rows = [
            ["Metric", "Value", "Metric", "Value"],
            ["Total Trades", str(analytics.get("total_trades", len(trades))), "Win Rate", f"{float(analytics.get('win_rate_pct', 0.0) or 0.0):.2f}%"],
            ["Net Profit", f"${float(analytics.get('total_pnl', 0.0) or 0.0):+.2f}", "Profit Factor", f"{float(analytics.get('profit_factor', 0.0) or 0.0):.2f}"],
            ["Expectancy", f"${float(analytics.get('expectancy_usd', 0.0) or 0.0):.2f}", "Max Drawdown", f"${float(analytics.get('max_drawdown_usd', 0.0) or 0.0):.2f}"],
            ["Sharpe Ratio", f"{float(analytics.get('sharpe_ratio', 0.0) or 0.0):.2f}", "Sortino Ratio", f"{float(analytics.get('sortino_ratio', 0.0) or 0.0):.2f}"],
            ["Recovery Factor", f"{float(analytics.get('recovery_factor', 0.0) or 0.0):.2f}", "Execution Success", f"{float(analytics.get('execution_success_rate_pct', 100.0) or 100.0):.1f}%"],
        ]
        t = Table(summary_rows, colWidths=[130, 130, 130, 130])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#161b22")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#00e5ff")),
            ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("TEXTCOLOR", (0, 1), (-1, -1), colors.HexColor("#e6edf3")),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#30363d")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#0d1117"), colors.HexColor("#161b22")]),
        ]))
        elements.append(t)
        elements.append(Spacer(1, 15))

        # Recent Trades Table
        if trades:
            elements.append(Paragraph("Recent Completed Executions", heading_style))
            trade_rows = [["Time", "Symbol", "Dir", "Entry", "Exit", "PnL ($)", "AI Score"]]
            for tr in trades[:15]:
                pnl_val = float(tr.get("realized_pnl", tr.get("pnl", 0.0)) or 0.0)
                entry_val = float(tr.get("entry_price", 0.0) or 0.0)
                exit_val = float(tr.get("close_price", tr.get("exit_price", 0.0)) or 0.0)
                score_val = float(tr.get("quality_score", tr.get("ai_score", 0.0)) or 0.0)
                trade_rows.append([
                    str(tr.get("entry_time", tr.get("timestamp", "")))[:16],
                    str(tr.get("symbol", "")),
                    str(tr.get("direction", "")),
                    f"${entry_val:.2f}",
                    f"${exit_val:.2f}",
                    f"${pnl_val:+.2f}",
                    f"{score_val:.1f}",
                ])
            t_trade = Table(trade_rows, colWidths=[100, 70, 50, 75, 75, 75, 75])
            t_trade.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#161b22")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#00e5ff")),
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("TEXTCOLOR", (0, 1), (-1, -1), colors.HexColor("#e6edf3")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#30363d")),
            ]))
            elements.append(t_trade)

        doc.build(elements)
        buffer.seek(0)
        return buffer.getvalue()
