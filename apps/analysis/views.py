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
from apps.analysis.models import Cluster, ClusterMembership

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
