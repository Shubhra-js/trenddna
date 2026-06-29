"""
API views — thin controllers that delegate to serializers and (later) services.

WHY THIS FILE EXISTS:
    Views handle HTTP concerns only: parse the request, call the right
    serializer or service, return a response. Business logic will live
    in service modules (ingestion/services.py, analysis/services.py).

INTERVIEW Q: "Why is the view so thin?"
    "Fat views are hard to test — you need to mock HTTP requests. Service
    functions are plain Python that accept parameters and return results.
    I can unit test 'generate_clusters(discussions)' without touching
    Django's request/response cycle. This is the Service Layer pattern."

INTERVIEW Q: "Why ViewSet instead of APIView?"
    "ViewSets combine related views (list, create, retrieve) into one
    class and auto-generate URL patterns via a router. It reduces
    boilerplate for standard CRUD operations. For custom non-CRUD
    endpoints, I'd use @action decorators or standalone APIViews."
"""
import logging

from rest_framework import viewsets, status
from rest_framework.decorators import api_view
from rest_framework.response import Response
from django.db.models import Count
from django.shortcuts import render

from apps.topics.models import Topic
from apps.topics.serializers import (
    TopicCreateSerializer,
    TopicListSerializer,
    TopicDetailSerializer,
)

logger = logging.getLogger("apps.topics")


@api_view(["GET"])
def health_check(request):
    """
    Minimal health check endpoint.

    WHY THIS EXISTS:
        Render pings a health endpoint to know if the server is alive.
        If this returns non-200, Render restarts the container. It also
        serves as a smoke test during development.

    WHAT INTERVIEWER MAY ASK:
        "What would you add to a production health check?"
        → Database connectivity check, cache ping, disk space, memory usage.
        For MVP, a simple 200 OK is sufficient.
    """
    return Response({
        "status": "healthy",
        "service": "trenddna",
        "version": "0.1.0",
    })


def dashboard_view(request):
    """
    Serve the main dashboard page.
    Django templates render the HTML; JavaScript handles all interaction
    via the REST API — a "thin template" approach.
    """
    return render(request, "dashboard.html")

class TopicViewSet(viewsets.ModelViewSet):
    """
    API endpoint for topic management.

    list:   GET  /api/v1/topics/        → All topics with discussion counts
    create: POST /api/v1/topics/        → Create topic (pipeline trigger later)
    read:   GET  /api/v1/topics/{id}/   → Full topic detail with stats
    """

    def get_queryset(self):
        """
        Annotate with discussion_count to avoid N+1 queries.

        WHY annotate here instead of in the serializer:
            The serializer's SerializerMethodField calls obj.discussions.count()
            which fires a separate SQL query per topic. For the list view with
            20 topics, that's 20 extra queries. Annotation does it in one query.
            The list serializer uses the annotated field; the detail serializer
            uses SerializerMethodField (acceptable for single-object views).
        """
        return Topic.objects.annotate(
            discussion_count=Count("discussions")
        ).order_by("-created_at")

    def get_serializer_class(self):
        """Pick the right serializer based on the current action."""
        if self.action == "create":
            return TopicCreateSerializer
        if self.action == "list":
            return TopicListSerializer
        return TopicDetailSerializer

    def create(self, request, *args, **kwargs):
        """
        Create a new topic.

        In later phases, this will also trigger the analysis pipeline:
            1. Create Topic
            2. Create AnalysisRun
            3. Kick off ingestion → embedding → clustering → sentiment
        For Phase 1, it just creates the database record.
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        topic = serializer.save()

        logger.info("Topic created: '%s' (id=%d)", topic.name, topic.id)

        # Return detail view of the created topic
        response_serializer = TopicDetailSerializer(topic)
        return Response(
            response_serializer.data,
            status=status.HTTP_201_CREATED,
        )
