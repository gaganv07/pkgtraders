"""
scripts/generate_periodical_reports.py — CLI Periodical Report Exporter

Generates Daily, Weekly, and Monthly performance reports into:
- reports/daily_reports/
- reports/weekly_reports/
- reports/monthly_reports/

Usage:
    python scripts/generate_periodical_reports.py --all
    python scripts/generate_periodical_reports.py --daily
    python scripts/generate_periodical_reports.py --weekly
    python scripts/generate_periodical_reports.py --monthly
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from app.config import settings
from app.database import Database
from reports.generator import ReportGenerator


def main():
    parser = argparse.ArgumentParser(description="Periodical Report Generator CLI")
    parser.add_argument("--daily", action="store_true", help="Generate Daily report")
    parser.add_argument("--weekly", action="store_true", help="Generate Weekly report")
    parser.add_argument("--monthly", action="store_true", help="Generate Monthly report")
    parser.add_argument("--all", action="store_true", help="Generate all reports")
    args = parser.parse_args()

    db = Database(settings.system.db_path)
    gen = ReportGenerator()

    do_all = args.all or (not args.daily and not args.weekly and not args.monthly)

    if args.daily or do_all:
        daily_res = gen.generate_daily(db)
        print(f"[OK] Generated Daily report: {daily_res}")

    if args.weekly or do_all:
        weekly_res = gen.generate_weekly(db)
        print(f"[OK] Generated Weekly report: {weekly_res}")

    if args.monthly or do_all:
        monthly_res = gen.generate_monthly(db)
        print(f"[OK] Generated Monthly report: {monthly_res}")

    print("\n[OK] Periodical report generation complete!")


if __name__ == "__main__":
    main()
