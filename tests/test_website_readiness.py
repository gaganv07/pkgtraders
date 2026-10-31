from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEBSITE = ROOT / "website"


def read_page(name: str) -> str:
    return (WEBSITE / name).read_text(encoding="utf-8")


def test_email_signin_does_not_create_new_supabase_users() -> None:
    login = read_page("login.html")
    assert "shouldCreateUser: false" in login
    assert "Continue with Apple" not in login
    assert 'id="apple"' not in login


def test_supabase_browser_sdk_is_pinned_to_a_stable_version() -> None:
    for page in ("login.html", "dashboard.html"):
        source = read_page(page)
        assert "@supabase/supabase-js@2.118.0" in source
        assert "@supabase/supabase-js@2</script>" not in source


def test_dashboard_separates_feed_freshness_from_account_mode() -> None:
    dashboard = read_page("dashboard.html")
    assert "FEED FRESH" in dashboard
    assert "FEED STALE" in dashboard
    assert "REAL ACCOUNT" in dashboard
    assert "DEMO ACCOUNT" in dashboard
    assert "timeZone: 'UTC'" in dashboard
    assert "LIVE · Last broker update" not in dashboard
    assert "clearDashboardData()" in dashboard


def test_homepage_uses_configured_instrument_count_limited_access_and_hamburger_menu() -> None:
    homepage = read_page("index.html")
    assert "7 configured instruments" in homepage
    assert "public onboarding is not open" in homepage
    assert 'id="menu-toggle"' in homepage
    assert 'aria-label="Open navigation"' in homepage
    assert 'class="bar"' in homepage
    assert 'href="/getting-started.html"' in homepage
    assert "LIMITED ACCESS" in homepage.upper()
    assert "integration testing" in homepage
    assert "not generally available" in homepage
    assert "8 pairs" not in homepage


def test_public_pages_disclose_prelaunch_and_support_gaps() -> None:
    contact = read_page("contact.html")
    privacy = read_page("privacy.html")
    terms = read_page("terms.html")
    pricing = read_page("pricing.html")
    faq = read_page("faq.html")

    assert "No monitored support inbox" in contact
    assert "No fixed retention periods" in privacy
    assert "PRE-LAUNCH NOTICE" in terms
    assert "not accepting public customers yet" in pricing
    assert "pre-approved accounts" in faq


def test_vercel_security_headers_are_configured() -> None:
    config = json.loads((WEBSITE / "vercel.json").read_text(encoding="utf-8"))
    headers = config["headers"]
    assert headers
    values = {
        item["key"].lower(): item["value"]
        for item in headers[0]["headers"]
    }
    assert values["x-content-type-options"] == "nosniff"
    assert values["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in values["content-security-policy"]


def test_dashboard_supports_authorized_multi_account_views() -> None:
    dashboard = read_page("dashboard.html")
    assert 'id="account-select"' in dashboard
    api = (WEBSITE / "api" / "trades.js").read_text(encoding="utf-8")
    assert "authorized_account_ids: operatorAccess.allowedAccountIds" in api
    assert "p.account_id || 'primary'" in dashboard
    assert "d.account_id || 'primary'" in dashboard
    assert "Multi-currency" in dashboard


def test_trade_api_requires_operator_mapping_and_filters_account_ids() -> None:
    api = (WEBSITE / "api" / "trades.js").read_text(encoding="utf-8")
    assert "vortext_authorized_operators" in api
    assert "user_id: 'eq.' + user.id" in api
    assert "operator.is_active !== true" in api
    assert "allowedAccountIds.includes(targetAccountId)" in api
    assert "vortext_user_account_access" not in api
    assert "validSignature" in api
    assert "VORTEXT_BOT_HMAC_SECRET" in api



def test_dashboard_has_three_independent_status_indicators() -> None:
    dashboard = read_page("dashboard.html")
    assert 'id="feed-connection"' in dashboard
    assert 'id="account-mode"' in dashboard
    assert 'id="broker-updated"' in dashboard
    assert "FEED CONNECTED · FRESH" in dashboard
    assert "FEED STALE" in dashboard
    assert "Last successful broker update" in dashboard
    assert "REAL ACCOUNT" in dashboard
    assert "DEMO ACCOUNT" in dashboard
    assert "LIVE · Last broker update" not in dashboard


def test_getting_started_covers_mt5_setup_and_safe_testing() -> None:
    guide = read_page("getting-started.html")
    for phrase in (
        "official MetaTrader 5 terminal",
        "broker and account compatibility",
        "Connect an account in MT5",
        "demo account first",
        "Safe account and credential setup",
        "not generally available",
        "https://www.metatrader5.com/en/download",
        "exact server name",
        "Never send passwords",
    ):
        assert phrase.lower() in guide.lower()


def test_unreleased_research_modules_are_marked_as_under_validation() -> None:
    homepage = read_page("index.html")
    assert "Research modules under validation" in homepage
    assert "not released for general customer use" in homepage
    assert "Live system health" not in homepage
