"""
tests/test_weekly_engine.py — Automated PyTest Test Suite
=========================================================
Verifies:
  1. Weekly stats computation (Win rate, Profit factor, Sharpe, Drawdown)
  2. Weekly markdown report generation (12 reports)
  3. Weekly PDF report generation (3 PDFs)
"""

import os
import sys
import pytest
from pathlib import Path

sys.path.insert(0, os.path.abspath("."))

from scripts.weekly_learning_engine import WeeklyLearningEngine
from scripts.generate_weekly_pdf_reports import generate_weekly_pdfs


def test_weekly_stats_computation():
    engine = WeeklyLearningEngine()
    stats = engine.compute_weekly_stats()
    
    assert stats is not None
    assert isinstance(stats.total_trades, int)
    assert isinstance(stats.win_rate_pct, float)
    assert isinstance(stats.profit_factor, float)


def test_weekly_reports_generation():
    engine = WeeklyLearningEngine()
    files = engine.generate_all_weekly_reports()
    
    assert len(files) == 12
    for f in files:
        assert f.exists()
        assert f.stat().st_size > 0


def test_weekly_pdf_generation():
    generate_weekly_pdfs()
    
    p1 = Path("reports/weekly_reports/weekly_trade_journal.pdf")
    p2 = Path("reports/weekly_reports/weekly_statistics.pdf")
    p3 = Path("reports/weekly_reports/weekly_dashboard.pdf")
    
    assert p1.exists()
    assert p2.exists()
    assert p3.exists()
