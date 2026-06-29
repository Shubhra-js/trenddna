"""
URL routing for the topics app.

WHY a DRF Router:
    The DefaultRouter introspects the ViewSet and auto-generates URL
    patterns for list, create, retrieve, update, and delete actions.
    This eliminates manual path() definitions for standard CRUD.

WHAT HAPPENS IF REMOVED:
    You'd need to write 3+ path() entries manually and keep them in sync
    with the ViewSet actions. The router does this automatically.
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter

from apps.topics.views import TopicViewSet

router = DefaultRouter()
router.register(r"topics", TopicViewSet, basename="topic")

urlpatterns = [
    path("", include(router.urls)),
]
