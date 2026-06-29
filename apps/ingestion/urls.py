"""
URL routing for the ingestion app.

These are nested under /api/v1/topics/{id}/ since they operate
on a specific topic.
"""
from django.urls import path
from apps.ingestion import views

app_name = "ingestion"

urlpatterns = [
    path(
        "topics/<int:topic_id>/ingest/",
        views.trigger_ingestion,
        name="trigger-ingestion",
    ),
    path(
        "topics/<int:topic_id>/status/",
        views.get_topic_status,
        name="topic-status",
    ),
]
