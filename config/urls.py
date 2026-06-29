"""
Root URL configuration.

WHY THIS FILE EXISTS:
    Maps URL paths to Django apps. All API endpoints live under /api/v1/
    for versioning. The admin panel is at /admin/.

INTERVIEW Q: "Why /api/v1/ prefix?"
    "API versioning from day one. If I change response shapes later, I
    create /api/v2/ without breaking existing consumers. The /v1/ prefix
    makes this possible without reverse proxies or content negotiation."
"""
from django.contrib import admin
from django.urls import path, include

from apps.topics.views import health_check, dashboard_view

urlpatterns = [
    # Dashboard — serves the main frontend at root URL
    path("", dashboard_view, name="dashboard"),

    # Django admin — free database inspection tool during development
    path("admin/", admin.site.urls),

    # Health check — used by Render for uptime monitoring
    path("api/v1/health/", health_check, name="health-check"),

    # Topic API endpoints
    path("api/v1/", include("apps.topics.urls")),

    # Ingestion API endpoints (ingest trigger + status)
    path("api/v1/", include("apps.ingestion.urls")),

    # Analysis API endpoints (cluster results, analytics)
    path("api/v1/", include("apps.analysis.urls")),
]
