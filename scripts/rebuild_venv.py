"""
scripts/rebuild_venv.py - Rebuild venv using new Python installation
Run with: C:\Python311\python.exe scripts\rebuild_venv.py
"""
import subprocess
import sys
import os

VENV_DIR = r"D:\dev\xauusd_pro\.venv"
REQUIREMENTS = [
    "MetaTrader5", "pandas", "numpy", "matplotlib",
    "scipy", "aiohttp", "fastapi", "uvicorn",
    "pytest", "pytest-asyncio", "pytest-mock",
    "scikit-learn", "python-dotenv",
]

print(f"Rebuilding venv at {VENV_DIR} using {sys.executable}")
subprocess.run([sys.executable, "-m", "venv", VENV_DIR, "--clear"], check=True)
pip = os.path.join(VENV_DIR, "Scripts", "pip.exe")
subprocess.run([pip, "install", "--upgrade", "pip"], check=True)
subprocess.run([pip, "install"] + REQUIREMENTS, check=True)
print("Venv rebuilt successfully!")
