"""
Analysis URL configuration.
"""
from django.urls import path
from apps.analysis import views

urlpatterns = [
    path(
        "topics/<int:topic_id>/clusters/",
        views.get_topic_clusters,
        name="topic-clusters",
    ),
    path(
        "topics/<int:topic_id>/sentiment/",
        views.get_topic_sentiment,
        name="topic-sentiment",
    ),
    path(
        "topics/<int:topic_id>/insights/",
        views.get_topic_insights,
        name="topic-insights",
    ),
]
