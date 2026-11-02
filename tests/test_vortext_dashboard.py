from datetime import datetime, timezone
from types import SimpleNamespace
import pytest
from app.vortext_dashboard import make_signature, VortextDashboardPublisher


def test_hmac_signature_is_deterministic_and_binds_the_body():
    secret = "x" * 64
    timestamp = "1793161000"
    body = b'{"bot_id":"vortext-main"}'
    sig = make_signature(secret, timestamp, body)
    assert len(sig) == 64
    assert sig == make_signature(secret, timestamp, body)
    assert sig != make_signature(secret, timestamp, body + b" ")


def test_publisher_is_disabled_by_default(monkeypatch):
    for key in ("VORTEXT_DASHBOARD_SYNC_ENABLED", "VORTEXT_DASHBOARD_INGEST_URL", "VORTEXT_BOT_HMAC_SECRET"):
        monkeypatch.delenv(key, raising=False)
    publisher = VortextDashboardPublisher(mt5_client=object())
    assert publisher.enabled is False


def test_snapshot_refuses_simulated_or_disconnected_client(monkeypatch):
    import app.vortext_dashboard as module
    monkeypatch.setattr(module, "_mt5", SimpleNamespace(), raising=True)
    disconnected = SimpleNamespace(connected=False, _sim_mode=False)
    with pytest.raises(RuntimeError, match="not connected"):
        module.build_snapshot(disconnected)
    simulated = SimpleNamespace(connected=True, _sim_mode=True)
    with pytest.raises(RuntimeError, match="simulated"):
        module.build_snapshot(simulated)
