"""
Production settings — security hardening and PostgreSQL.

WHY THIS FILE EXISTS:
    Production has different security requirements (no DEBUG, HTTPS headers,
    restricted CORS) and uses PostgreSQL instead of SQLite. Separating these
    into their own file makes security auditing straightforward — a reviewer
    only needs to read this one file to verify production is secure.

INTERVIEW Q: "Walk me through your production hardening."
    "I disable DEBUG so stack traces aren't leaked to users. I enable
    SECURE_SSL_REDIRECT to force HTTPS. Session and CSRF cookies are
    marked Secure so they're only sent over HTTPS. CORS is restricted
    to explicit origins. Static files are served by WhiteNoise with
    compression and caching headers, not by Django's dev server."
"""
from config.settings.base import *  # noqa: F401, F403
from decouple import config
import dj_database_url

# =============================================================================
# Security
# =============================================================================
DEBUG = False
ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="").split(",")

# HTTPS enforcement
SECURE_SSL_REDIRECT = config("SECURE_SSL_REDIRECT", default=True, cast=bool)
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True

# =============================================================================
# Database — PostgreSQL via DATABASE_URL
# =============================================================================
# WHY dj-database-url: Render (and Heroku, Railway, etc.) provide the database
# connection as a single URL string. This library parses it into Django's
# DATABASES dict format. conn_max_age=600 enables persistent connections
# (reuses connections for 10 minutes instead of opening/closing per request).
DATABASES = {
    "default": dj_database_url.config(
        default=config("DATABASE_URL"),
        conn_max_age=600,
    )
}

# =============================================================================
# CORS — restricted to explicit origins
# =============================================================================
CORS_ALLOWED_ORIGINS = config("CORS_ALLOWED_ORIGINS", default="").split(",")

# =============================================================================
# Static Files — WhiteNoise with compression
# =============================================================================
STORAGES = {
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

# =============================================================================
# DRF — JSON only in production (no browsable API)
# =============================================================================
REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"] = [  # noqa: F405
    "rest_framework.renderers.JSONRenderer",
]
