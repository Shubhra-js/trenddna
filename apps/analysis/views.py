"""
Analysis API views — cluster results and analytics.

WHY SEPARATE FROM ingestion/views.py:
    Ingestion handles "collect data." Analysis handles "show results."
    Different bounded contexts, different audiences. The cluster endpoint
    is read-only (GET), while ingestion has write operations (POST).
"""
import logging

from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status

from apps.topics.models import Topic
from apps.analysis.models import Cluster, ClusterMembership, SentimentResult, Insight

logger = logging.getLogger("apps.analysis")


@api_view(["GET"])
def get_topic_clusters(request, topic_id):
    """
    GET /api/v1/topics/{id}/clusters/

    Returns all clusters for a topic with labels, keywords,
    member counts, and representative discussions.

    Response:
    {
        "topic_id": 1,
        "cluster_count": 4,
        "algorithm": "kmeans",
        "silhouette_score": 0.42,
        "largest_cluster": "Pricing Concerns",
        "clusters": [
            {
                "id": 1,
                "label": "Pricing Concerns",
                "keywords": ["price", "expensive", "quality"],
                "member_count": 15,
                "coherence_score": 0.51,
                "summary": "This cluster contains ...",
                "top_discussions": [
                    {
                        "id": 10,
                        "title": "...",
                        "content_preview": "...",
                        "source": "reddit"
                    }
                ]
            }
        ]
    }
    """
    try:
        topic = Topic.objects.get(id=topic_id)
    except Topic.DoesNotExist:
        return Response(
            {"error": "Topic not found"},
            status=status.HTTP_404_NOT_FOUND,
        )

    # Get the latest analysis run's clusters
    clusters = (
        Cluster.objects
        .filter(topic=topic)
        .order_by("-member_count")
    )

    if not clusters.exists():
        return Response({
            "topic_id": topic.id,
            "cluster_count": 0,
            "algorithm": None,
            "silhouette_score": None,
            "largest_cluster": None,
            "clusters": [],
        })

    # Get silhouette score from the analysis run
    latest_run = clusters.first().analysis_run
    params = latest_run.parameters or {}
    sil_score = params.get("silhouette_score")
    algorithm = params.get("algorithm", "kmeans")

    # Build cluster response
    cluster_list = []
    largest_cluster_label = None
    largest_count = 0

    for cluster in clusters:
        # Get top representative discussions (closest to centroid)
        top_memberships = (
            ClusterMembership.objects
            .filter(cluster=cluster)
            .select_related("discussion")
            .order_by("distance")[:3]
        )

        top_discussions = []
        for membership in top_memberships:
            disc = membership.discussion
            content_preview = disc.content[:120] if disc.content else ""
            if len(disc.content or "") > 120:
                content_preview += "..."
            top_discussions.append({
                "id": disc.id,
                "title": disc.title or "(no title)",
                "content_preview": content_preview,
                "source": disc.source,
                "distance": round(membership.distance, 4),
            })

        cluster_list.append({
            "id": cluster.id,
            "label": cluster.label,
            "keywords": cluster.keywords,
            "member_count": cluster.member_count,
            "coherence_score": cluster.coherence_score,
            "summary": cluster.summary,
            "top_discussions": top_discussions,
        })

        if cluster.member_count > largest_count:
            largest_count = cluster.member_count
            largest_cluster_label = cluster.label

    return Response({
        "topic_id": topic.id,
        "cluster_count": len(cluster_list),
        "algorithm": algorithm,
        "silhouette_score": sil_score,
        "largest_cluster": largest_cluster_label,
        "clusters": cluster_list,
    })


@api_view(["GET"])
def get_topic_sentiment(request, topic_id):
    """
    GET /api/v1/topics/{id}/sentiment/

    Returns overall sentiment distribution and per-cluster breakdown.
    """
    try:
        topic = Topic.objects.get(id=topic_id)
    except Topic.DoesNotExist:
        return Response(
            {"error": "Topic not found"},
            status=status.HTTP_404_NOT_FOUND,
        )

    sentiments = SentimentResult.objects.filter(discussion__topic_id=topic_id)
    total = sentiments.count()

    if total == 0:
        return Response({
            "topic_id": topic.id,
            "discussion_count": 0,
            "overall": {
                "positive": 0,
                "neutral": 0,
                "negative": 0,
                "average_score": 0.0,
            },
            "cluster_breakdown": [],
        })

    from django.db.models import Avg
    avg = sentiments.aggregate(avg=Avg("compound_score"))["avg"] or 0.0
    pos = sentiments.filter(label=SentimentResult.Label.POSITIVE).count()
    neg = sentiments.filter(label=SentimentResult.Label.NEGATIVE).count()
    neu = sentiments.filter(label=SentimentResult.Label.NEUTRAL).count()

    # Cluster sentiment breakdown
    clusters = Cluster.objects.filter(topic_id=topic_id)
    cluster_breakdown = []
    for c in clusters:
        data = c.sentiment_data or {}
        cluster_breakdown.append({
            "cluster_id": c.id,
            "label": c.label,
            "sentiment_label": data.get("label", "neutral"),
            "average_score": data.get("avg_score", 0.0),
            "positive_pct": data.get("positive_pct", 0),
            "negative_pct": data.get("negative_pct", 0),
            "neutral_pct": data.get("neutral_pct", 0),
            "member_count": c.member_count,
        })

    return Response({
        "topic_id": topic.id,
        "discussion_count": total,
        "overall": {
            "positive": pos,
            "neutral": neu,
            "negative": neg,
            "average_score": round(avg, 4),
        },
        "cluster_breakdown": cluster_breakdown,
    })


@api_view(["GET"])
def get_topic_insights(request, topic_id):
    """
    GET /api/v1/topics/{id}/insights/

    Returns AI-generated insights for a topic.
    """
    try:
        topic = Topic.objects.get(id=topic_id)
    except Topic.DoesNotExist:
        return Response(
            {"error": "Topic not found"},
            status=status.HTTP_404_NOT_FOUND,
        )

    insights = Insight.objects.filter(topic_id=topic_id).order_by("-confidence")

    insight_list = []
    for ins in insights:
        insight_list.append({
            "id": ins.id,
            "type": ins.insight_type,
            "content": ins.content,
            "confidence": ins.confidence,
            "metadata": ins.metadata,
        })

    return Response({
        "topic_id": topic.id,
        "insight_count": len(insight_list),
        "insights": insight_list,
    })

