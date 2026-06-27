"""
Central configuration for the web-server template.

Everything that used to be hardcoded in app.py lives here and is driven by
environment variables (loaded from a `.env` file in development). Each value
falls back to the CURRENT working default, so the app still runs with no `.env`.

Pick the active config with the APP_ENV environment variable:
    APP_ENV=development   (default)  -> DevelopmentConfig
    APP_ENV=production               -> ProductionConfig
    APP_ENV=testing                  -> TestingConfig

See SECRETS.md for the "HOW TO GO LIVE" checklist (real ECPay keys, AWS key,
switching the database engine, etc.).
"""
import os

# Optionally load a local .env file if python-dotenv is installed.
# (Not required: every setting below has a safe default.)
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def _list(name: str, default: str = "") -> list[str]:
    """Comma-separated env var -> list of non-empty strings."""
    return [v.strip() for v in os.getenv(name, default).split(",") if v.strip()]


class Config:
    """Base config. Shared defaults for every environment."""

    # ---- Core Flask --------------------------------------------------------
    SECRET_KEY = os.getenv("SECRET_KEY", "super-secret-key-change-this-in-production")
    PORT = int(os.getenv("PORT", "5000"))
    TIMEZONE = os.getenv("TIMEZONE", "Asia/Taipei")

    # ---- Session cookie security -------------------------------------------
    SESSION_COOKIE_HTTPONLY = True          # JS can't read the cookie
    SESSION_COOKIE_SAMESITE = "Lax"         # basic CSRF mitigation
    SESSION_COOKIE_SECURE = _bool("SESSION_COOKIE_SECURE", False)  # True in prod (HTTPS)
    PERMANENT_SESSION_LIFETIME = int(os.getenv("PERMANENT_SESSION_LIFETIME", "86400"))

    # ---- Reverse proxy -----------------------------------------------------
    # When the app runs behind nginx (or any proxy), enable this so Flask honors
    # X-Forwarded-Proto/For/Host: HTTPS detection (Secure cookies + correct
    # external URLs) and the real client IP (for rate limiting). Off by default
    # (direct/local); on in production. See ProxyFix in app.create_app().
    TRUST_PROXY = _bool("TRUST_PROXY", False)

    # ===== DATABASE =========================================================
    # To change which database the server uses, edit DATABASE_URL in your .env
    # (or this default). Examples:
    #   SQLite (default):  sqlite:///data.db
    #   PostgreSQL:        postgresql+psycopg2://user:pass@host:5432/dbname
    #   MySQL:             mysql+pymysql://user:pass@host:3306/dbname
    # Non-SQLite engines need a driver in requirements.txt (see SECRETS.md).
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "sqlite:///data.db")
    # Secondary bind that holds the system users / accounts.
    SQLALCHEMY_BINDS = {
        "user_db": os.getenv("USER_DATABASE_URL", "sqlite:///user.db"),
    }
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # ========================================================================

    # ---- Backups -----------------------------------------------------------
    DATABASE_FILE = os.getenv("DATABASE_FILE", "data.db")
    BACKUP_DIR = os.getenv("BACKUP_DIR", "backups")
    RETENTION_DAYS = int(os.getenv("RETENTION_DAYS", "30"))

    # ---- ECPay (payment) ---------------------------------------------------
    # Defaults are ECPay's OFFICIAL public SANDBOX merchant (2000132). This trio
    # is the only one that works against the stage endpoint below, so payments
    # work out of the box for testing. Swap for your own official credentials in
    # .env when going live -- AND switch ECPAY_ACTION_URL to the live URL too:
    # a production MerchantID sent to the stage URL (or vice versa) fails with
    # "10200074 找不到加密金鑰" (encryption key not found). See SECRETS.md.
    ECPAY_MERCHANT_ID = os.getenv("ECPAY_MERCHANT_ID", "2000132")
    ECPAY_HASH_KEY = os.getenv("ECPAY_HASH_KEY", "5294y06JbISpM5x9")
    ECPAY_HASH_IV = os.getenv("ECPAY_HASH_IV", "v77hoKGq4kWxNNIS")
    # Default to the SANDBOX/stage endpoint (safe). Switch to the live URL in .env
    # when going live: https://payment.ecpay.com.tw/Cashier/AioCheckOut/V5
    ECPAY_ACTION_URL = os.getenv(
        "ECPAY_ACTION_URL", "https://payment-stage.ecpay.com.tw/Cashier/AioCheckOut/V5"
    )
    # Order defaults — change these (or pass per-call to create_ecpay_order) without
    # touching code: payment methods, encryption, default item name, description.
    ECPAY_CHOOSE_PAYMENT = os.getenv("ECPAY_CHOOSE_PAYMENT", "ALL")
    ECPAY_ENCRYPT_TYPE = int(os.getenv("ECPAY_ENCRYPT_TYPE", "1"))
    ECPAY_DEFAULT_ITEM = os.getenv("ECPAY_DEFAULT_ITEM", "Premium_Membership")
    ECPAY_TRADE_DESC = os.getenv("ECPAY_TRADE_DESC", "Subscription")
    # Public base URL ECPay calls back to (e.g. your ngrok / domain).
    PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:5000")
    VIP_PRICE = int(os.getenv("VIP_PRICE", "199"))
    VIP_DAYS = int(os.getenv("VIP_DAYS", "365"))

    # ---- Email (optional SMTP; password-reset links) -----------------------
    # If SMTP_HOST is unset, reset links are logged instead of emailed (dev).
    SMTP_HOST = os.getenv("SMTP_HOST", "")
    SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USER = os.getenv("SMTP_USER", "")
    SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
    SMTP_FROM = os.getenv("SMTP_FROM", "")
    SMTP_USE_TLS = _bool("SMTP_USE_TLS", True)

    # ---- External data API protection -------------------------------------
    # Comma-separated list of accepted X-API-Key values. Each external client
    # gets its own key; rotate by editing this list. Empty list = API locked.
    API_KEYS = _list("API_KEYS", "dev-test-key-change-me")

    # ---- Security add-ons --------------------------------------------------
    # Rate limits (Flask-Limiter syntax). Tune per environment.
    RATELIMIT_DEFAULT = os.getenv("RATELIMIT_DEFAULT", "200 per minute")
    RATELIMIT_LOGIN = os.getenv("RATELIMIT_LOGIN", "10 per minute")
    RATELIMIT_SAVE = os.getenv("RATELIMIT_SAVE", "60 per minute")
    RATELIMIT_RESET = os.getenv("RATELIMIT_RESET", "5 per minute")
    RATELIMIT_ENABLED = _bool("RATELIMIT_ENABLED", True)
    # Where Flask-Limiter keeps its counters. "memory://" is fine for dev/single
    # process; for production behind multiple workers use e.g. "redis://host:6379".
    RATELIMIT_STORAGE_URI = os.getenv("RATELIMIT_STORAGE_URI", "memory://")
    WTF_CSRF_ENABLED = _bool("WTF_CSRF_ENABLED", True)
    # Lifetime (seconds) of password-reset and API login tokens.
    RESET_TOKEN_MAX_AGE = int(os.getenv("RESET_TOKEN_MAX_AGE", "3600"))
    API_TOKEN_MAX_AGE = int(os.getenv("API_TOKEN_MAX_AGE", "2592000"))  # 30 days

    # ---- Default admin (seeded on first run) -------------------------------
    # On startup, if no account with this username exists, one is auto-created
    # so a fresh deploy has a working admin. CHANGE THE PASSWORD after first
    # login (or set these in .env). Set DEFAULT_ADMIN_ENABLED=false to disable.
    DEFAULT_ADMIN_ENABLED = _bool("DEFAULT_ADMIN_ENABLED", True)
    DEFAULT_ADMIN_USERNAME = os.getenv("DEFAULT_ADMIN_USERNAME", "admin")
    DEFAULT_ADMIN_PASSWORD = os.getenv("DEFAULT_ADMIN_PASSWORD", "admin12345")
    DEFAULT_ADMIN_ROLE = os.getenv("DEFAULT_ADMIN_ROLE", "superadmin")


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    DEBUG = False
    # Require HTTPS for the session cookie in production (override via env if needed).
    SESSION_COOKIE_SECURE = _bool("SESSION_COOKIE_SECURE", True)
    # Production runs behind nginx -> trust forwarded headers (override via env).
    TRUST_PROXY = _bool("TRUST_PROXY", True)


class TestingConfig(Config):
    TESTING = True
    DEBUG = True
    # Self-contained DB so tests never touch real data.
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_BINDS = {"user_db": "sqlite:///:memory:"}
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False
    DEFAULT_ADMIN_ENABLED = False
    API_KEYS = ["test-key"]
    ECPAY_MERCHANT_ID = "2000132"
    ECPAY_HASH_KEY = "5294y06JbISpM5x9"
    ECPAY_HASH_IV = "v77hoKGq4kWxNNIS"


_CONFIGS = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
}


def get_config(name: str | None = None):
    """Resolve a config class from a name or the APP_ENV env var."""
    name = (name or os.getenv("APP_ENV", "development")).strip().lower()
    return _CONFIGS.get(name, DevelopmentConfig)
