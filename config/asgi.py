"""
ASGI config for TrendDNA.

Not used in MVP but included for future async support (WebSockets, etc.).
"""
import os
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

application = get_asgi_application()
