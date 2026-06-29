"""
Core data models: Topic and Discussion.

WHY THIS FILE EXISTS:
    These are the two foundational tables. Every other model (clusters,
    sentiment, insights) references either Topic or Discussion. They live
    in the topics app because they represent the core domain objects.

INTERVIEW Q: "Why are Topic and Discussion in the same app?"
    "They have a tight 1:N relationship and are always queried together.
    Separating them into different apps would create cross-app imports
    and unnecessary complexity. Django apps should group tightly-coupled
    models."

INTERVIEW Q: "Explain your model design decisions."
    "I used TextChoices for type-safe enums (status, source), JSONField for
    platform-specific metadata to avoid NULL-heavy columns, and a unique
    constraint on (source, source_id) to prevent duplicate ingestion. The
    Discussion model is designed so the adapter pattern can normalize
    different platforms into one table."
"""
from django.db import models


class Topic(models.Model):
    """
    Root entity representing a user's analysis query.
    Everything else — discussions, clusters, insights — links back here.
    """

    class Status(models.TextChoices):
        """
        Pipeline status progression: pending → ingesting → analyzing → completed
        WHY NOT a boolean is_complete: Can't distinguish ingesting from analyzing.
        The frontend needs this granularity to show meaningful progress messages.
        """
        PENDING = "pending", "Pending"
        INGESTING = "ingesting", "Ingesting Data"
        ANALYZING = "analyzing", "Running Analysis"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    name = models.CharField(
        max_length=200,
        help_text="User-provided topic query, e.g. 'AI in education'",
    )
    description = models.TextField(
        blank=True,
        default="",
        help_text="Auto-generated summary after analysis completes",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "topics"

    def __str__(self):
        return f"{self.name} ({self.status})"


class Discussion(models.Model):
    """
    Individual post or comment collected from a data source.
    Normalized across platforms — Reddit posts and YouTube comments
    share the same schema via the adapter pattern.

    WHY metadata as JSONField:
        Reddit has subreddit, upvotes, num_comments.
        YouTube has video_id, like_count, reply_count.
        A JSON field avoids platform-specific columns that would be
        NULL for other sources. The pipeline doesn't need these fields —
        only the frontend uses them for display context.
    """

    class Source(models.TextChoices):
        REDDIT = "reddit", "Reddit"
        YOUTUBE = "youtube", "YouTube"

    topic = models.ForeignKey(
        Topic,
        on_delete=models.CASCADE,
        related_name="discussions",
    )
    source = models.CharField(max_length=20, choices=Source.choices)
    # Platform-specific ID for deduplication during re-ingestion
    source_id = models.CharField(max_length=200)
    title = models.CharField(max_length=500, blank=True, default="")
    content = models.TextField()
    author = models.CharField(max_length=200, blank=True, default="")
    url = models.URLField(max_length=500, blank=True, default="")
    published_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-published_at"]
        # Prevent duplicate ingestion: same source + source_id = same discussion
        constraints = [
            models.UniqueConstraint(
                fields=["source", "source_id"],
                name="unique_source_discussion",
            )
        ]
        indexes = [
            models.Index(
                fields=["topic", "published_at"],
                name="idx_discussion_timeline",
            ),
        ]

    def __str__(self):
        return f"[{self.source}] {self.title[:50] if self.title else '(no title)'}"
