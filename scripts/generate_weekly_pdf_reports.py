"""
scripts/generate_weekly_pdf_reports.py — Weekly PDF Report Generator
====================================================================
Uses ReportLab to generate:
  - reports/weekly_reports/weekly_trade_journal.pdf
  - reports/weekly_reports/weekly_statistics.pdf
  - reports/weekly_reports/weekly_dashboard.pdf
"""

from __future__ import annotations

import csv
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.abspath("."))

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from scripts.weekly_learning_engine import WeeklyLearningEngine


def generate_weekly_pdfs():
    out_dir = Path("reports/weekly_reports")
    out_dir.mkdir(parents=True, exist_ok=True)

    engine = WeeklyLearningEngine()
    stats = engine.compute_weekly_stats()

    styles = getSampleStyleSheet()
    NAVY = colors.HexColor("#0F172A")
    BLUE = colors.HexColor("#2563EB")
    DARK_GRAY = colors.HexColor("#334155")
    LIGHT_BG = colors.HexColor("#F8FAFC")
    BORDER_COLOR = colors.HexColor("#CBD5E1")

    title_style = ParagraphStyle("TitleStyle", parent=styles["Heading1"], fontName="Helvetica-Bold", fontSize=18, leading=22, textColor=NAVY, spaceAfter=4)
    subtitle_style = ParagraphStyle("SubTitleStyle", parent=styles["Normal"], fontName="Helvetica", fontSize=9, leading=12, textColor=DARK_GRAY, spaceAfter=10)
    heading2_style = ParagraphStyle("Heading2Style", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=12, leading=15, textColor=BLUE, spaceBefore=8, spaceAfter=4)
    body_style = ParagraphStyle("BodyStyle", parent=styles["Normal"], fontName="Helvetica", fontSize=9, leading=12, textColor=NAVY)
    body_bold = ParagraphStyle("BodyBold", parent=body_style, fontName="Helvetica-Bold")

    # 1. weekly_dashboard.pdf
    p_dash = out_dir / "weekly_dashboard.pdf"
    doc_dash = SimpleDocTemplate(str(p_dash), pagesize=letter, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    story = []

    ts_now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    story.append(Paragraph("PKG TRADERS / XAUUSD_PRO", ParagraphStyle("H0", fontName="Helvetica-Bold", fontSize=8, textColor=BLUE)))
    story.append(Paragraph("WEEKLY INSTITUTIONAL DASHBOARD", title_style))
    story.append(Paragraph(f"Generated: {ts_now} | Mode: <b>MULTI-ASSET INSTITUTIONAL AUDIT</b>", subtitle_style))
    story.append(HRFlowable(width="100%", thickness=1.5, color=BLUE, spaceAfter=10))

    # Metric Table
    m_data = [
        [Paragraph("<b>TOTAL TRADES</b>", body_style), Paragraph("<b>WIN RATE</b>", body_style), Paragraph("<b>PROFIT FACTOR</b>", body_style), Paragraph("<b>MAX DRAWDOWN</b>", body_style)],
        [Paragraph(f"<b>{stats.total_trades}</b>", body_style), Paragraph(f"<b>{stats.win_rate_pct}%</b>", body_style), Paragraph(f"<b>{stats.profit_factor}</b>", body_style), Paragraph(f"<b>{stats.max_drawdown_pct}%</b>", body_style)],
    ]
    t_dash = Table(m_data, colWidths=[130, 130, 140, 140])
    t_dash.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), LIGHT_BG),
        ('BORDER', (0,0), (-1,-1), 1, BORDER_COLOR),
        ('PADDING', (0,0), (-1,-1), 8),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
    ]))
    story.append(t_dash)
    story.append(Spacer(1, 10))

    story.append(Paragraph("Weekly Multi-Asset Summary", heading2_style))
    sum_text = f"""
    During this weekly evaluation cycle, the platform executed <b>{stats.total_trades} trades</b> across all 7 supported instruments 
    (XAUUSD, BTCUSD, EURUSD, GBPUSD, USDJPY, NAS100, US30), generating a total net realized PnL of <b>${stats.total_pnl:,.2f}</b> 
    with a profit factor of <b>{stats.profit_factor}</b> and an expectancy of <b>${stats.expectancy_usd:.2f} per trade</b>.
    """
    story.append(Paragraph(sum_text, body_style))
    story.append(Spacer(1, 10))

    story.append(HRFlowable(width="100%", thickness=1, color=BORDER_COLOR, spaceAfter=6))
    story.append(Paragraph("Confidential Audit Report — Generated automatically by PKG Traders Weekly Engine", ParagraphStyle("F", fontName="Helvetica", fontSize=8, textColor=DARK_GRAY, alignment=1)))

    doc_dash.build(story)

    # 2. weekly_trade_journal.pdf
    p_jour = out_dir / "weekly_trade_journal.pdf"
    doc_jour = SimpleDocTemplate(str(p_jour), pagesize=letter, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    story2 = []
    story2.append(Paragraph("WEEKLY TRADE JOURNAL", title_style))
    story2.append(Paragraph(f"Generated: {ts_now}", subtitle_style))
    story2.append(HRFlowable(width="100%", thickness=1.5, color=BLUE, spaceAfter=10))

    j_rows = [[Paragraph("<b>Timestamp</b>", body_bold), Paragraph("<b>Symbol</b>", body_bold), Paragraph("<b>Dir</b>", body_bold), Paragraph("<b>PnL ($)</b>", body_bold), Paragraph("<b>R-Mult</b>", body_bold), Paragraph("<b>Exit Reason</b>", body_bold)]]
    for t in engine.trades[-10:]:
        pnl_val = float(t.get("pnl", 0))
        pnl_str = f"+${pnl_val:.2f}" if pnl_val >= 0 else f"-${abs(pnl_val):.2f}"
        pnl_color = "#166534" if pnl_val >= 0 else "#991B1B"
        j_rows.append([
            Paragraph(t.get('timestamp','')[:16], body_style),
            Paragraph(f"<b>{t.get('symbol','')}</b>", body_style),
            Paragraph(t.get('direction',''), body_style),
            Paragraph(f"<font color='{pnl_color}'><b>{pnl_str}</b></font>", body_style),
            Paragraph(f"{float(t.get('r_multiple',0)):.2f}R", body_style),
            Paragraph(t.get('exit_reason','MT5_CLOSE'), body_style),
        ])

    t_jour = Table(j_rows, colWidths=[110, 65, 45, 80, 60, 180])
    t_jour.setStyle(TableStyle([
        ('HEADERBACKGROUND', (0,0), (-1,0), NAVY),
        ('GRID', (0,0), (-1,-1), 0.5, BORDER_COLOR),
        ('PADDING', (0,0), (-1,-1), 4),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, LIGHT_BG]),
    ]))
    story2.append(t_jour)
    doc_jour.build(story2)

    # 3. weekly_statistics.pdf
    p_stat = out_dir / "weekly_statistics.pdf"
    doc_stat = SimpleDocTemplate(str(p_stat), pagesize=letter, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    story3 = []
    story3.append(Paragraph("WEEKLY STATISTICAL ANALYSIS", title_style))
    story3.append(Paragraph(f"Generated: {ts_now}", subtitle_style))
    story3.append(HRFlowable(width="100%", thickness=1.5, color=BLUE, spaceAfter=10))

    s_text = f"""
    - <b>Total Trades Evaluated:</b> {stats.total_trades}<br/>
    - <b>Win Rate:</b> {stats.win_rate_pct}%<br/>
    - <b>Profit Factor:</b> {stats.profit_factor}<br/>
    - <b>Sharpe Ratio:</b> {stats.sharpe_ratio}<br/>
    - <b>Sortino Ratio:</b> {stats.sortino_ratio}<br/>
    - <b>Max Drawdown:</b> {stats.max_drawdown_pct}%<br/>
    - <b>Bookmap Signal Agreement:</b> {stats.bookmap_agreement_pct}%<br/>
    - <b>Execution Latency:</b> {stats.avg_latency_ms} ms<br/>
    """
    story3.append(Paragraph(s_text, body_style))
    doc_stat.build(story3)

    print(f"[WEEKLY PDF GENERATOR] Rendered weekly PDFs in {out_dir}")


if __name__ == "__main__":
    generate_weekly_pdfs()
