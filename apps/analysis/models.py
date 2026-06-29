"""
Analysis models: AnalysisRun, SentimentResult, Cluster, ClusterMembership, Insight.

WHY ALL MODELS ARE DEFINED NOW (even though logic comes later):
    Django migrations need all tables created upfront. The Topic detail
    serializer will reference analysis stats (cluster_count, avg_sentiment),
    so the tables must exist even if they're empty. Defining models early
    also validates the ER diagram design before we write business logic.

INTERVIEW Q: "Walk me through these models."
    "AnalysisRun tracks each pipeline execution — when it started, what
    parameters were used, and whether it succeeded. SentimentResult stores
    VADER scores per discussion. Cluster groups semantically similar
    discussions with auto-generated labels. ClusterMembership is an explicit
    many-to-many with a distance field for ranking. Insight stores
    AI-generated explanations with confidence scores."
"""
from django.db import models

from apps.topics.models import Topic, Discussion


class AnalysisRun(models.Model):
    """
    Tracks each execution of the analysis pipeline.

    WHY THIS TABLE EXISTS:
        A topic can be re-analyzed with different parameters (e.g., switch
        from KMeans to DBSCAN). Without tracking runs, you can't compare
        results, debug failures, or audit what happened.

    INTERVIEW Q: "Is this an audit log?"
        "Partially. It's primarily for operational visibility. If analysis
        fails at the clustering step, I see exactly when and why. It also
        enables re-analysis without losing previous results."
    """

    class Status(models.TextChoices):
        RUNNING = "running", "Running"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    topic = models.ForeignKey(
        Topic,
        on_delete=models.CASCADE,
        related_name="analysis_runs",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.RUNNING,
    )
    parameters = models.JSONField(
        default=dict,
        blank=True,
        help_text='Algorithm config, e.g. {"algorithm": "kmeans", "max_k": 10}',
    )
    error_message = models.TextField(blank=True, default="")
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self):
        return f"Run #{self.id} for '{self.topic.name}' ({self.status})"


class SentimentResult(models.Model):
    """
    VADER sentiment scores for a single discussion.

    WHY SEPARATE TABLE (not columns on Discussion):
        Single Responsibility. Discussion owns text data; SentimentResult
        owns analysis output. If we swap VADER for a transformer model,
        we only change the sentiment service and this table.

    WHY STORE ALL FOUR SCORES:
        compound_score is the primary metric for timelines, but the
        component scores enable richer visualizations — stacked bar charts
        showing positive/negative/neutral ratios per cluster.
    """

    class Label(models.TextChoices):
        POSITIVE = "positive", "Positive"
        NEGATIVE = "negative", "Negative"
        NEUTRAL = "neutral", "Neutral"

    discussion = models.OneToOneField(
        Discussion,
        on_delete=models.CASCADE,
        related_name="sentiment",
    )
    compound_score = models.FloatField(help_text="VADER compound: -1.0 to 1.0")
    positive_score = models.FloatField(help_text="Positive component: 0 to 1")
    negative_score = models.FloatField(help_text="Negative component: 0 to 1")
    neutral_score = models.FloatField(help_text="Neutral component: 0 to 1")
    label = models.CharField(max_length=10, choices=Label.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.label} ({self.compound_score:+.2f})"


class Cluster(models.Model):
    """
    A group of semantically similar discussions.

    INTERVIEW Q: "How do you generate the cluster label?"
        "After KMeans assigns discussions, I run TF-IDF on each cluster's
        combined text to extract the top 3-5 keywords. Those become the
        label. E.g., a GPU pricing cluster gets 'GPU prices shortage NVIDIA'."
    """

    topic = models.ForeignKey(
        Topic,
        on_delete=models.CASCADE,
        related_name="clusters",
    )
    analysis_run = models.ForeignKey(
        AnalysisRun,
        on_delete=models.CASCADE,
        related_name="clusters",
    )
    label = models.CharField(max_length=200)
    keywords = models.JSONField(default=list, blank=True)
    summary = models.TextField(blank=True, default="")
    algorithm = models.CharField(max_length=20, default="kmeans")
    member_count = models.IntegerField(default=0)
    coherence_score = models.FloatField(
        default=0.0,
        help_text="Intra-cluster similarity — higher is better",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-member_count"]

    def __str__(self):
        return f"Cluster '{self.label}' ({self.member_count} members)"


class ClusterMembership(models.Model):
    """
    Explicit many-to-many between Discussion and Cluster.

    WHY NOT ManyToManyField:
        Django's built-in M2M doesn't store extra data. The distance field
        lets us rank discussions within a cluster — those closest to the
        centroid are the most representative. The explainability panel uses
        this to show "most representative discussions" for each cluster.
    """

    discussion = models.ForeignKey(
        Discussion,
        on_delete=models.CASCADE,
        related_name="cluster_memberships",
    )
    cluster = models.ForeignKey(
        Cluster,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    distance = models.FloatField(help_text="Distance from cluster centroid")

    class Meta:
        unique_together = ["discussion", "cluster"]
        ordering = ["distance"]

    def __str__(self):
        return f"Discussion #{self.discussion_id} → Cluster #{self.cluster_id}"


class Insight(models.Model):
    """
    AI-generated explanations and detected patterns.

    INTERVIEW Q: "What's the difference between insight types?"
        trend_spike     — "Volume increased 300% on March 15th"
        sentiment_shift — "Sentiment shifted from +0.34 to -0.12"
        cluster_summary — "Cluster 2 is about salary negotiations"
        explanation     — "This spike was driven by 3 viral Reddit posts"
    """

    class InsightType(models.TextChoices):
        TREND_SPIKE = "trend_spike", "Trend Spike"
        SENTIMENT_SHIFT = "sentiment_shift", "Sentiment Shift"
        CLUSTER_SUMMARY = "cluster_summary", "Cluster Summary"
        EXPLANATION = "explanation", "Explanation"

    topic = models.ForeignKey(
        Topic,
        on_delete=models.CASCADE,
        related_name="insights",
    )
    analysis_run = models.ForeignKey(
        AnalysisRun,
        on_delete=models.CASCADE,
        related_name="insights",
    )
    insight_type = models.CharField(max_length=30, choices=InsightType.choices)
    content = models.TextField()
    confidence = models.FloatField(
        default=0.0,
        help_text="0.0 to 1.0 — how confident the system is in this insight",
    )
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Supporting data: spike timestamps, keyword lists, etc.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-confidence", "-created_at"]

    def __str__(self):
        return f"[{self.insight_type}] {self.content[:50]}"


class Embedding(models.Model):
    """
    Stores a sentence-transformer embedding vector for a discussion.

    WHY BinaryField (not ArrayField or JSONField):
        A 384-dim float32 vector is 1,536 bytes. BinaryField stores raw
        bytes — compact and fast. ArrayField would store 384 floats as a
        PostgreSQL array (larger, slower). JSONField would serialize to
        text (even larger). For production, pgvector extension provides
        native vector search, but BinaryField is simpler and sufficient
        for batch operations (clustering reads all vectors at once).

    WHY model_name and dimensions:
        Reproducibility. If we switch from all-MiniLM-L6-v2 (384d) to
        a larger model (768d), old embeddings are invalidated. These
        fields let the service detect mismatches and re-embed.

    INTERVIEW Q: "How do you deserialize the vector?"
        "numpy.frombuffer(embedding.vector, dtype=np.float32) gives back
        the original numpy array. It's a zero-copy operation — very fast."
    """

    discussion = models.OneToOneField(
        Discussion,
        on_delete=models.CASCADE,
        related_name="embedding",
    )
    vector = models.BinaryField(
        help_text="Serialized numpy float32 array (384 dimensions = 1,536 bytes)",
    )
    model_name = models.CharField(
        max_length=100,
        default="all-MiniLM-L6-v2",
        help_text="Sentence-transformer model used to generate this embedding",
    )
    dimensions = models.IntegerField(
        default=384,
        help_text="Vector dimensionality (must match model output)",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["model_name"], name="idx_embedding_model"),
        ]

    def __str__(self):
        return f"Embedding for Discussion #{self.discussion_id} ({self.dimensions}d)"
