"""Database encryption settings and the dev-environment label."""
import importlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _dsn_with(monkeypatch, **env):
    # Empty, not deleted: reloading config re-reads backend/.env, which would otherwise refill them on a
    # machine whose settings use SSL. The portal treats an empty value as not set.
    for k in ("PG_SSLMODE", "PG_SSLROOTCERT"):
        monkeypatch.setenv(k, "")
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("PG_PASSWORD", "x")
    import backend.config as config
    import backend.db as db
    importlib.reload(config)
    importlib.reload(db)
    try:
        return db._dsn()
    finally:
        for k in env:
            monkeypatch.delenv(k, raising=False)
        importlib.reload(config)
        importlib.reload(db)


def test_central_server_connections_can_require_encryption(monkeypatch):
    assert "sslmode=require" in _dsn_with(monkeypatch, PG_SSLMODE="require")
    full = _dsn_with(monkeypatch, PG_SSLMODE="verify-full", PG_SSLROOTCERT="/etc/ssl/certs/db-ca.pem")
    assert "sslmode=verify-full" in full and "sslrootcert=/etc/ssl/certs/db-ca.pem" in full


def test_local_connections_are_unchanged_without_ssl_settings(monkeypatch):
    dsn = _dsn_with(monkeypatch)
    assert "sslmode" not in dsn and "sslrootcert" not in dsn


def test_dev_server_shows_a_dev_label():
    js = (ROOT / "api-integration.js").read_text(encoding="utf-8")
    assert "markEnvironment(data.environment)" in js and 'env !== "dev"' in js and "[DEV]" in js
    # No environment label on the page itself (partner review, 5 Nov 2026): only the tab title says [DEV].
    assert "DEV · TEST DATA" not in js and 'html[data-env="dev"]' not in (ROOT / "styles.css").read_text(encoding="utf-8")
    assert "<b>ALPHA</b>" not in (ROOT / "index.html").read_text(encoding="utf-8")
