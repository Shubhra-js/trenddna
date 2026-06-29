"""
WSGI config for TrendDNA.

WHY THIS FILE EXISTS:
    WSGI (Web Server Gateway Interface) is the standard interface between
    Python web applications and web servers. Gunicorn uses this file to
    find our Django application in production.

INTERVIEW Q: "What's the difference between WSGI and ASGI?"
    "WSGI is synchronous — one request, one thread. ASGI is asynchronous —
    supports WebSockets and long-polling. We use WSGI because our API is
    request-response only. If we added real-time features, we'd switch to
    ASGI with Daphne or Uvicorn."

HOW IT'S USED:
    gunicorn config.wsgi:application --bind 0.0.0.0:8000
"""
import os
from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

application = get_wsgi_application()
