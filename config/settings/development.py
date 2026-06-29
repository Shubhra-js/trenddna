"""
Development settings — local development overrides.

WHY THIS FILE EXISTS:
    Development needs are opposite to production: we want verbose errors,
    auto-reload, SQLite (no setup), and permissive CORS. This file
    inherits everything from base.py and overrides only what differs.

WHAT HAPPENS IF REMOVED:
    Developers would need PostgreSQL installed locally just to run the
    project. The SQLite fallback eliminates that friction — clone, install
    dependencies, run migrations, and you're up in 60 seconds.
"""
from config.settings.base import *  # noqa: F401, F403

# =============================================================================
# Debug
# =============================================================================
DEBUG = True
ALLOWED_HOSTS = ["*"]

# =============================================================================
# Database — SQLite for zero-setup development
# =============================================================================
# WHY SQLite in dev: No need to install PostgreSQL, create a database, or
# manage credentials just to work on a feature. SQLite creates a file.
#
# INTERVIEW Q: "Why not use PostgreSQL in dev too?"
#   "PostgreSQL in dev would test closer to production, but it adds setup
#   friction. SQLite is sufficient for development because our queries use
#   standard ORM calls — no raw SQL or PostgreSQL-specific features."
#
# CAVEAT: JSONField works in SQLite on Django 5.x, but if you hit issues,
# switch to PostgreSQL locally.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

# =============================================================================
# CORS — allow everything in development
# =============================================================================
CORS_ALLOW_ALL_ORIGINS = True

# =============================================================================
# DRF — enable browsable API for development convenience
# =============================================================================
REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"] = [  # noqa: F405
    "rest_framework.renderers.JSONRenderer",
    "rest_framework.renderers.BrowsableAPIRenderer",
]
