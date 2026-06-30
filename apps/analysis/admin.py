"""
Django admin for analysis models — debugging and data inspection.
"""
from django.contrib import admin
from apps.analysis.models import (
    AnalysisRun,
    SentimentResult,
    Cluster,
    ClusterMembership,
    Insight,
    Embedding,
)


@admin.register(AnalysisRun)
class AnalysisRunAdmin(admin.ModelAdmin):
    list_display = ["id", "topic", "status", "cluster_count", "silhouette_display", "started_at", "completed_at"]
    list_filter = ["status"]
    readonly_fields = ["started_at"]

    def cluster_count(self, obj):
        return obj.clusters.count()
    cluster_count.short_description = "Clusters"

    def silhouette_display(self, obj):
        params = obj.parameters or {}
        score = params.get("silhouette_score")
        if score is not None:
            return f"{score:.4f}"
        return "—"
    silhouette_display.short_description = "Silhouette"


@admin.register(SentimentResult)
class SentimentResultAdmin(admin.ModelAdmin):
    list_display = ["discussion", "topic_name", "label", "compound_score", "positive_score", "negative_score"]
    list_filter = ["label"]
    readonly_fields = ["created_at"]

    def topic_name(self, obj):
        return obj.discussion.topic.name
    topic_name.short_description = "Topic"


@admin.register(Cluster)
class ClusterAdmin(admin.ModelAdmin):
    list_display = ["label", "topic", "algorithm", "member_count", "coherence_score", "sentiment_display", "keywords_display"]
    list_filter = ["algorithm", "topic"]
    search_fields = ["label", "summary"]

    def keywords_display(self, obj):
        if obj.keywords:
            return ", ".join(obj.keywords[:5])
        return "—"
    keywords_display.short_description = "Keywords"

    def sentiment_display(self, obj):
        data = obj.sentiment_data or {}
        label = data.get("label", "—")
        score = data.get("avg_score", 0)
        if label == "—":
            return "—"
        return f"{label} ({score:+.2f})"
    sentiment_display.short_description = "Sentiment"


@admin.register(ClusterMembership)
class ClusterMembershipAdmin(admin.ModelAdmin):
    list_display = ["discussion", "cluster", "distance"]
    list_filter = ["cluster"]


@admin.register(Insight)
class InsightAdmin(admin.ModelAdmin):
    list_display = ["insight_type", "topic", "content_preview", "confidence", "created_at"]
    list_filter = ["insight_type", "topic"]
    search_fields = ["content"]
    readonly_fields = ["created_at"]

    def content_preview(self, obj):
        return obj.content[:80] + "..." if len(obj.content) > 80 else obj.content
    content_preview.short_description = "Content"


@admin.register(Embedding)
class EmbeddingAdmin(admin.ModelAdmin):
    list_display = ["discussion", "model_name", "dimensions", "vector_size", "created_at"]
    list_filter = ["model_name", "dimensions"]
    readonly_fields = ["created_at"]

    def vector_size(self, obj):
        """Show vector storage size in bytes."""
        if obj.vector:
            return f"{len(obj.vector)} bytes"
        return "—"
    vector_size.short_description = "Size"
