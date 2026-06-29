"""
Django admin configuration for Topic and Discussion models.

WHY THIS FILE EXISTS:
    Django admin gives you a free database inspection UI. During development,
    you can verify that ingestion worked correctly, inspect discussion content,
    and debug data issues without writing custom views or raw SQL queries.

INTERVIEW Q: "Why customize the admin?"
    "The default admin shows raw IDs and all fields. Custom list_display,
    list_filter, and search_fields make it a usable debugging tool. The
    inline lets me see a topic's discussions without navigating away."
"""
import json

from django.contrib import admin
from django.utils.html import format_html

from apps.topics.models import Topic, Discussion


class DiscussionInline(admin.TabularInline):
    """Show discussions inline on the Topic detail page."""
    model = Discussion
    extra = 0  # Don't show empty forms for adding new discussions
    readonly_fields = ["source", "source_id", "title", "author", "published_at"]
    fields = ["source", "title", "author", "published_at"]
    show_change_link = True
    can_delete = False


@admin.register(Topic)
class TopicAdmin(admin.ModelAdmin):
    list_display = [
        "name", "status", "discussion_count",
        "reddit_count", "youtube_count",
        "ingestion_duration_display", "created_at",
    ]
    list_filter = ["status", "created_at"]
    search_fields = ["name"]
    readonly_fields = ["created_at", "updated_at", "ingestion_metrics_display"]
    inlines = [DiscussionInline]

    def discussion_count(self, obj):
        return obj.discussions.count()
    discussion_count.short_description = "Total"

    def reddit_count(self, obj):
        return obj.discussions.filter(source="reddit").count()
    reddit_count.short_description = "Reddit"

    def youtube_count(self, obj):
        return obj.discussions.filter(source="youtube").count()
    youtube_count.short_description = "YouTube"

    def _get_metrics(self, obj):
        """Parse ingestion metrics stored as JSON in description."""
        try:
            if obj.description:
                return json.loads(obj.description)
        except (json.JSONDecodeError, TypeError):
            pass
        return {}

    def ingestion_duration_display(self, obj):
        metrics = self._get_metrics(obj)
        duration = metrics.get("ingestion_duration")
        if duration is not None:
            return f"{duration}s"
        return "—"
    ingestion_duration_display.short_description = "Duration"

    def ingestion_metrics_display(self, obj):
        """Rich HTML display of ingestion metrics on the detail page."""
        metrics = self._get_metrics(obj)
        if not metrics:
            return "No ingestion metrics available"

        parts = [
            f"<strong>Duration:</strong> {metrics.get('ingestion_duration', '—')}s",
            f"<strong>Saved:</strong> {metrics.get('saved', 0)}",
            f"<strong>Duplicates:</strong> {metrics.get('duplicates', 0)}",
            f"<strong>Quality Filtered:</strong> {metrics.get('quality_filtered', 0)}",
            f"<strong>Skipped:</strong> {metrics.get('skipped', 0)}",
        ]
        sources = metrics.get("sources", {})
        if sources:
            parts.append(f"<strong>Sources:</strong> {sources}")
        failed = metrics.get("failed_sources", [])
        if failed:
            parts.append(f"<strong>Failed Sources:</strong> {', '.join(failed)}")

        return format_html("<br>".join(parts))
    ingestion_metrics_display.short_description = "Ingestion Metrics"


@admin.register(Discussion)
class DiscussionAdmin(admin.ModelAdmin):
    list_display = ["title_short", "source", "topic", "author", "content_preview", "published_at"]
    list_filter = ["source", "topic"]
    search_fields = ["title", "content", "author"]
    readonly_fields = ["created_at"]

    def title_short(self, obj):
        return obj.title[:60] if obj.title else "(no title)"
    title_short.short_description = "Title"

    def content_preview(self, obj):
        """Show first 80 chars of content for quick scanning."""
        if obj.content:
            preview = obj.content[:80]
            return f"{preview}..." if len(obj.content) > 80 else preview
        return "—"
    content_preview.short_description = "Content Preview"
