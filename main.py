"""
Main Entry Point for XAUUSD Pro Trading Bot
Allows executing `python main.py` directly from xauusd_pro directory.
"""
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.main import main
import asyncio

if __name__ == "__main__":
    asyncio.run(main())
