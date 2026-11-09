import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from backend/ (works when cwd is repo root or backend/)
_env = Path(__file__).resolve().parent / ".env"
load_dotenv(_env)

ROOT = Path(__file__).resolve().parents[1]

POSTGRES_CONFIG = {
    "host": os.getenv("PG_HOST", "localhost"),
    "port": os.getenv("PG_PORT", "5432"),
    "dbname": os.getenv("PG_DB", "founder_portal_local"),
    "user": os.getenv("PG_USER", "fp_local"),
    "password": os.getenv("PG_PASSWORD", ""),
    # Encrypted connections to a managed PostgreSQL server: "require" encrypts;
    # "verify-full" also checks the server certificate against PG_SSLROOTCERT. Empty = libpq default (prefer).
    "sslmode": os.getenv("PG_SSLMODE", "").strip(),
    "sslrootcert": os.getenv("PG_SSLROOTCERT", "").strip(),
}

# "replica" on the laptop (the sandbox: the copy of production where all work is built and tested), "dev" on the
# server for team testing (test data, a visible DEV label), "production" for the live portal, and "local" for
# throw-away test copies. Replica and production hide the sign-in demo hint; production also hides
# the API docs.
APP_ENV = os.getenv("APP_ENV", "local")

# Only the built frontend is ever served as static files, never the repo root (secrets live there).
FRONTEND_DIR = Path(os.getenv("FRONTEND_DIR", str(ROOT / "dist"))).resolve()

# Downloadable resource files. Uploads from the analyst workspace go to CONTENT_DIR/uploads.
CONTENT_DIR = Path(os.getenv("CONTENT_DIR", str(ROOT / "content"))).resolve()
# Files uploaded through the workspace. Test runs can point this elsewhere,
# so test uploads never mix with real ones.
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", str(CONTENT_DIR / "uploads"))).resolve()

# Comma-separated list of extra origins allowed to call the API (same-origin needs none).
ALLOWED_ORIGINS = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()]

MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "15"))
LOGIN_MAX_FAILURES = int(os.getenv("LOGIN_MAX_FAILURES", "5"))
LOGIN_LOCKOUT_MINUTES = int(os.getenv("LOGIN_LOCKOUT_MINUTES", "15"))

# Live sector news: approved feeds are read in the background every NEWS_FETCH_MINUTES.
# Set NEWS_FETCH_ENABLED=0 when a cron job / systemd timer runs `python -m backend.scripts.fetch_news` instead.
NEWS_FETCH_ENABLED = os.getenv("NEWS_FETCH_ENABLED", "0").lower() not in ("0", "false", "no")
NEWS_FETCH_MINUTES = int(os.getenv("NEWS_FETCH_MINUTES", "15"))

# Automatic news suggestions (feeds matched to companies) are a beta feature.
# In alpha they are switched off: no feed reading, and the /api/admin/news routes answer 404.
# Beta adds a news API, Exa.ai web search and AI-written summaries on top (see README).
NEWS_SUGGESTIONS_ENABLED = os.getenv("NEWS_SUGGESTIONS_ENABLED", "0").lower() in ("1", "true", "yes")

# Sign in with a one-time code sent by email (alpha-v1.2.6, 30 Oct 2026). Built but switched off: while off,
# the sign-in page shows no code button and the /api/auth/otp/* routes answer 404. Turn on with
# OTP_SIGNIN_ENABLED=1 only once real email delivery (SMTP_HOST) is set up.
OTP_SIGNIN_ENABLED = os.getenv("OTP_SIGNIN_ENABLED", "0").lower() in ("1", "true", "yes")
OTP_MINUTES = int(os.getenv("OTP_MINUTES", "10"))        # how long a code works
OTP_MAX_ATTEMPTS = int(os.getenv("OTP_MAX_ATTEMPTS", "5"))  # wrong guesses before a code stops working

# Email (meeting 23 Oct 2026). Without SMTP_HOST every message stays in the workspace outbox as "not sent"
# (test mode); staff can copy it, open it in their email app or send it on WhatsApp.
SMTP_HOST = os.getenv("SMTP_HOST", "").strip()
if os.getenv("EMAIL_DISABLED", "0").lower() in ("1", "true", "yes"):  # test copies never send real email
    SMTP_HOST = ""
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "").strip()
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", "Demo Ventures Founder's Resource Portal <portal@team.demo>").strip()
SMTP_STARTTLS = os.getenv("SMTP_STARTTLS", "1").lower() not in ("0", "false", "no")
# Address used in links inside emails and WhatsApp messages (the portal's public address once hosted).
# Office inbox that receives every internal-event RSVP, besides the organiser and the company's Demo Ventures team (optional).
EVENTS_OFFICE_EMAIL = os.getenv("EVENTS_OFFICE_EMAIL", "").strip()
PORTAL_URL = os.getenv("PORTAL_URL", "http://127.0.0.1:8000").rstrip("/")
