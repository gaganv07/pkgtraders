from pathlib import Path


def test_login_page_only_advertises_configured_auth_methods():
    repo_root = Path(__file__).resolve().parents[1]
    login_page = (repo_root / "website" / "login.html").read_text(encoding="utf-8")

    assert 'id="google"' in login_page
    assert 'id="apple"' not in login_page
    assert 'oauth("google")' in login_page
    assert 'oauth("apple")' not in login_page
    assert "signInWithOtp" in login_page
    assert "Google or Apple" not in login_page
