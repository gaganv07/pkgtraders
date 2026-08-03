# ================================================================
# XAUUSD Pro Scalper — Dockerfile
#
# NOTE: MetaTrader 5 requires Windows. This image runs the
# Python trading logic in simulation mode on Linux/Docker.
# For live trading, deploy on a Windows VPS and install
# MetaTrader5 package directly.
# ================================================================

FROM python:3.11-slim

LABEL maintainer="xauusd-pro-scalper"
LABEL description="XAUUSD Pro Institutional Scalping Bot"

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl gcc libssl-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/          ./app/
COPY dashboard/    ./dashboard/
COPY reports/      ./reports/
COPY backtesting/  ./backtesting/
COPY tests/        ./tests/

RUN mkdir -p logs database/backups reports

RUN useradd -m -u 1000 scalper && chown -R scalper:scalper /app
USER scalper

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8080/ping || exit 1

CMD ["python", "-m", "app.main"]
