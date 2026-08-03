"""
scripts/launch_desktop_control_center.py — Desktop App Launcher for Legacy Asset Partners Control Center

Starts the read-only FastAPI + WebSockets server in a background thread and opens
a standalone Desktop Control Center window using pywebview (or default browser).

Usage:
    python scripts/launch_desktop_control_center.py
    python scripts/launch_desktop_control_center.py --port 8000
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
import webbrowser
from pathlib import Path

# Add project root to sys.path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import uvicorn
from dashboard.control_center import app

try:
    import webview
    WEBVIEW_AVAILABLE = True
except ImportError:
    WEBVIEW_AVAILABLE = False


def start_server(host: str = "127.0.0.1", port: int = 8000):
    uvicorn.run(app, host=host, port=port, log_level="warning")


def main():
    parser = argparse.ArgumentParser(description="Legacy Asset Partners — Desktop Control Center Launcher")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host interface")
    parser.add_argument("--port", type=int, default=8000, help="Port number")
    parser.add_argument("--browser", action="store_true", help="Force opening in default web browser")
    args = parser.parse_args()

    print("=" * 70)
    print("   LEGACY ASSET PARTNERS — AI TRADING CONTROL CENTER")
    print("   Institutional Multi-Asset Read-Only Desktop Platform")
    print("=" * 70)

    url = f"http://{args.host}:{args.port}/"

    # Start FastAPI server in background thread
    t = threading.Thread(target=start_server, args=(args.host, args.port), daemon=True)
    t.start()
    time.sleep(1.5)

    print(f"\n[OK] Backend engine active at: {url}")

    if WEBVIEW_AVAILABLE and not args.browser:
        print("[OK] Launching native Desktop Application window (pywebview)...")
        webview.create_window(
            "Legacy Asset Partners — AI Trading Control Center",
            url,
            width=1400,
            height=900,
            resizable=True,
        )
        webview.start()
    else:
        print("[OK] Launching in default web browser window...")
        webbrowser.open(url)
        try:
            while True:
                time.sleep(1.0)
        except KeyboardInterrupt:
            print("\n[OK] Desktop Control Center stopped.")


if __name__ == "__main__":
    main()
