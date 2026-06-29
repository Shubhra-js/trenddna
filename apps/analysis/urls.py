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
]
