"""
Ingestion API views — trigger data collection and check status.

WHY SEPARATE FROM topics/views.py:
    Ingestion is a different bounded context. These endpoints handle
    "collect data from external sources" — a concern separate from
    "CRUD topics." If ingestion logic changes (e.g., add Celery),
    only this file changes.
"""
import json
import logging

from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status

from apps.topics.models import Topic
from apps.pipeline.jobs import get_job_runner
from apps.ingestion.services.ingestion_service import ingest_topic

logger = logging.getLogger("apps.ingestion")


@api_view(["POST"])
def trigger_ingestion(request, topic_id):
    """
    POST /api/v1/topics/{id}/ingest/

    Submits ingestion to the JobRunner (background thread by default).
    Returns 202 (Accepted) immediately — the frontend polls
    GET /status/ to track progress.

    Responses:
        202 — Ingestion started
        404 — Topic not found
        409 — Ingestion already in progress
    """
    try:
        topic = Topic.objects.get(id=topic_id)
    except Topic.DoesNotExist:
        return Response(
            {"error": "Topic not found"},
            status=status.HTTP_404_NOT_FOUND,
        )

    # Prevent duplicate ingestion runs
    if topic.status == Topic.Status.INGESTING:
        return Response(
            {"error": "Ingestion already in progress for this topic"},
            status=status.HTTP_409_CONFLICT,
        )

    # Submit to the job runner (ThreadJobRunner by default)
    runner = get_job_runner()
    job_id = runner.submit(ingest_topic, topic.id)

    return Response(
        {
            "topic_id": topic.id,
            "job_id": job_id,
            "status": "ingesting",
            "message": "Ingestion started. Poll GET /api/v1/topics/{id}/status/ for progress.",
        },
        status=status.HTTP_202_ACCEPTED,
    )


@api_view(["GET"])
def get_topic_status(request, topic_id):
    """
    GET /api/v1/topics/{id}/status/

    Returns the current ingestion/analysis status for a topic.
    The frontend polls this every 2 seconds during ingestion to
    show real-time progress (discussion count increases as items
    are saved by the background thread).

    Response:
    {
        "topic_id": 1,
        "status": "completed",
        "discussion_count": 42,
        "ingestion_duration": 12.5,
        "sources": {"reddit": 35, "youtube": 7},
        "failed_sources": []
    }
    """
    try:
        topic = Topic.objects.get(id=topic_id)
    except Topic.DoesNotExist:
        return Response(
            {"error": "Topic not found"},
            status=status.HTTP_404_NOT_FOUND,
        )

    # Count discussions by source
    discussions = topic.discussions.all()
    reddit_count = discussions.filter(source="reddit").count()
    youtube_count = discussions.filter(source="youtube").count()

    # Count embeddings (live from DB)
    from apps.analysis.models import Embedding, Cluster
    embeddings_count = Embedding.objects.filter(
        discussion__topic_id=topic_id,
    ).count()

    # Count clusters (live from DB)
    cluster_count = Cluster.objects.filter(topic_id=topic_id).count()

    # Parse ingestion metrics from topic.description (stored as JSON)
    ingestion_duration = None
    failed_sources = []
    embedding_metrics = {}
    try:
        if topic.description:
            metrics = json.loads(topic.description)
            ingestion_duration = metrics.get("ingestion_duration")
            failed_sources = metrics.get("failed_sources", [])
            embedding_metrics = metrics.get("embeddings", {})
    except (json.JSONDecodeError, TypeError):
        pass

    return Response({
        "topic_id": topic.id,
        "status": topic.status,
        "discussion_count": reddit_count + youtube_count,
        "ingestion_duration": ingestion_duration,
        "sources": {
            "reddit": reddit_count,
            "youtube": youtube_count,
        },
        "failed_sources": failed_sources,
        "embeddings_count": embeddings_count,
        "embedding_model": embedding_metrics.get("model", ""),
        "embedding_duration": embedding_metrics.get("duration"),
        "cluster_count": cluster_count,
    })
