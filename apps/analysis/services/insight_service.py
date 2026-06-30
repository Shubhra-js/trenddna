"""
Insight engine — generates plain-English findings from analysis data.

WHAT THIS DOES:
    After sentiment analysis runs, this service examines the data and
    generates human-readable insights using deterministic rules. No LLMs,
    no API calls — just pattern recognition on structured data.

WHY RULES (not LLMs):
    1. Deterministic — same data always produces the same insights
    2. Fast — microseconds, not seconds
    3. Free — no API keys, no token costs
    4. Explainable — each insight traces to a specific rule
    5. Testable — we can assert exact outputs for known inputs

INTERVIEW Q: "How does your insight engine work?"
    "I have 7 deterministic rules that examine clusters, sentiment scores,
    and source distributions. Each rule checks a condition (e.g., 'is there
    a cluster with avg sentiment below -0.2?') and generates a finding with
    a confidence score. The rules are designed to surface patterns a human
    analyst would notice — dominant themes, sentiment outliers, polarization,
    and cross-source differences."

INTERVIEW Q: "What's the confidence score?"
    "It's a heuristic, not a probability. High confidence (0.9) means the
    pattern is strong and clear — e.g., 80% of discussions are positive.
    Low confidence (0.5) means the pattern is weak — e.g., only a small
    difference between sources. It helps rank insights by importance."
"""
import logging

from django.db.models import Avg, Count, Q
from django.utils import timezone

from apps.topics.models import Topic, Discussion
from apps.analysis.models import (
    AnalysisRun,
    Cluster,
    Insight,
    SentimentResult,
)

logger = logging.getLogger("apps.analysis")


def generate_insights(topic_id: int, analysis_run: AnalysisRun = None) -> list[dict]:
    """
    Generate rule-based insights for a topic.

    Rules:
    1. Overall sentiment summary
    2. Most positive cluster
    3. Most negative cluster
    4. Most polarized cluster
    5. Source comparison (Reddit vs YouTube)
    6. Dominant theme
    7. Unexpected findings

    Args:
        topic_id: Topic to analyze.
        analysis_run: AnalysisRun to attach insights to. If None, uses latest.

    Returns:
        List of insight dicts: [{type, content, confidence, metadata}]
    """
    topic = Topic.objects.get(id=topic_id)

    # Get or create analysis run
    if analysis_run is None:
        analysis_run = (
            AnalysisRun.objects
            .filter(topic=topic)
            .order_by("-started_at")
            .first()
        )
        if analysis_run is None:
            analysis_run = AnalysisRun.objects.create(
                topic=topic,
                status=AnalysisRun.Status.RUNNING,
            )

    # Gather data
    sentiments = SentimentResult.objects.filter(discussion__topic_id=topic_id)
    clusters = Cluster.objects.filter(topic_id=topic_id)
    discussions = Discussion.objects.filter(topic_id=topic_id)

    if not sentiments.exists():
        logger.info("No sentiment data for topic '%s' — skipping insights", topic.name)
        return []

    # Generate insights from each rule
    insights = []
    insights.extend(_rule_overall_sentiment(sentiments, topic))
    insights.extend(_rule_most_positive_cluster(clusters))
    insights.extend(_rule_most_negative_cluster(clusters))
    insights.extend(_rule_polarized_cluster(clusters))
    insights.extend(_rule_source_comparison(discussions, sentiments))
    insights.extend(_rule_dominant_theme(clusters, discussions))
    insights.extend(_rule_unexpected_findings(sentiments, clusters))

    # Store in database
    insight_objects = []
    for ins in insights:
        insight_objects.append(Insight(
            topic=topic,
            analysis_run=analysis_run,
            insight_type=ins["type"],
            content=ins["content"],
            confidence=ins["confidence"],
            metadata=ins.get("metadata", {}),
        ))

    if insight_objects:
        Insight.objects.bulk_create(insight_objects)

    logger.info(
        "Generated %d insights for topic '%s'",
        len(insights), topic.name,
    )

    return insights


# =============================================================================
# Insight Rules
# =============================================================================

def _rule_overall_sentiment(sentiments, topic) -> list[dict]:
    """
    Rule 1: Summarize overall sentiment distribution.
    Always fires — every analysis gets an overall summary.
    """
    total = sentiments.count()
    avg = sentiments.aggregate(avg=Avg("compound_score"))["avg"] or 0.0
    pos = sentiments.filter(label=SentimentResult.Label.POSITIVE).count()
    neg = sentiments.filter(label=SentimentResult.Label.NEGATIVE).count()
    neu = sentiments.filter(label=SentimentResult.Label.NEUTRAL).count()

    # Describe intensity
    if avg > 0.3:
        desc = "strongly positive"
    elif avg > 0.05:
        desc = "moderately positive"
    elif avg < -0.3:
        desc = "strongly negative"
    elif avg < -0.05:
        desc = "moderately negative"
    else:
        desc = "mostly neutral"

    pos_pct = round(pos / total * 100) if total else 0
    neg_pct = round(neg / total * 100) if total else 0

    return [{
        "type": Insight.InsightType.SENTIMENT_SHIFT,
        "content": (
            f"Overall sentiment around '{topic.name}' is {desc} "
            f"(average: {avg:+.2f}). "
            f"{pos_pct}% of discussions are positive, "
            f"{neg_pct}% are negative."
        ),
        "confidence": 0.95,
        "metadata": {
            "average_score": round(avg, 4),
            "positive_count": pos,
            "neutral_count": neu,
            "negative_count": neg,
            "total": total,
        },
    }]


def _rule_most_positive_cluster(clusters) -> list[dict]:
    """
    Rule 2: Identify the most positive cluster (avg > 0.15).
    """
    results = []
    for c in clusters:
        data = c.sentiment_data or {}
        score = data.get("avg_score", 0)
        if score > 0.15:
            results.append({
                "type": Insight.InsightType.CLUSTER_SUMMARY,
                "content": (
                    f"The '{c.label}' cluster is predominantly positive "
                    f"(avg sentiment: {score:+.2f}). "
                    f"{data.get('positive_pct', 0)}% of its {c.member_count} "
                    f"discussions express positive sentiment."
                ),
                "confidence": min(0.5 + abs(score), 0.95),
                "metadata": {
                    "cluster_id": c.id,
                    "cluster_label": c.label,
                    "avg_score": score,
                },
            })

    # Return only the most positive
    if results:
        results.sort(key=lambda x: x["metadata"]["avg_score"], reverse=True)
        return [results[0]]
    return []


def _rule_most_negative_cluster(clusters) -> list[dict]:
    """
    Rule 3: Identify the most negative cluster (avg < -0.1).
    """
    results = []
    for c in clusters:
        data = c.sentiment_data or {}
        score = data.get("avg_score", 0)
        if score < -0.1:
            results.append({
                "type": Insight.InsightType.CLUSTER_SUMMARY,
                "content": (
                    f"Discussions about '{c.label}' are notably negative "
                    f"(avg sentiment: {score:+.2f}). "
                    f"{data.get('negative_pct', 0)}% of its {c.member_count} "
                    f"discussions express negative sentiment."
                ),
                "confidence": min(0.5 + abs(score), 0.95),
                "metadata": {
                    "cluster_id": c.id,
                    "cluster_label": c.label,
                    "avg_score": score,
                },
            })

    # Return the most negative
    if results:
        results.sort(key=lambda x: x["metadata"]["avg_score"])
        return [results[0]]
    return []


def _rule_polarized_cluster(clusters) -> list[dict]:
    """
    Rule 4: Find clusters with both high positive AND high negative %.
    Polarization = min(positive_pct, negative_pct) >= 25
    """
    for c in clusters:
        data = c.sentiment_data or {}
        pos_pct = data.get("positive_pct", 0)
        neg_pct = data.get("negative_pct", 0)

        if pos_pct >= 25 and neg_pct >= 25:
            return [{
                "type": Insight.InsightType.SENTIMENT_SHIFT,
                "content": (
                    f"The '{c.label}' cluster is polarized — "
                    f"{pos_pct}% of discussions are positive while "
                    f"{neg_pct}% are negative. This topic generates "
                    f"strong opinions on both sides."
                ),
                "confidence": 0.8,
                "metadata": {
                    "cluster_id": c.id,
                    "cluster_label": c.label,
                    "positive_pct": pos_pct,
                    "negative_pct": neg_pct,
                },
            }]
    return []


def _rule_source_comparison(discussions, sentiments) -> list[dict]:
    """
    Rule 5: Compare sentiment between Reddit and YouTube.
    Fires when the difference exceeds 0.15.
    """
    reddit_ids = set(
        discussions.filter(source="reddit").values_list("id", flat=True)
    )
    youtube_ids = set(
        discussions.filter(source="youtube").values_list("id", flat=True)
    )

    if not reddit_ids or not youtube_ids:
        return []  # Need both sources for comparison

    reddit_avg = (
        sentiments.filter(discussion_id__in=reddit_ids)
        .aggregate(avg=Avg("compound_score"))["avg"] or 0.0
    )
    youtube_avg = (
        sentiments.filter(discussion_id__in=youtube_ids)
        .aggregate(avg=Avg("compound_score"))["avg"] or 0.0
    )

    diff = abs(reddit_avg - youtube_avg)
    if diff < 0.15:
        return []

    if reddit_avg > youtube_avg:
        more_positive = "Reddit"
        less_positive = "YouTube"
    else:
        more_positive = "YouTube"
        less_positive = "Reddit"

    return [{
        "type": Insight.InsightType.TREND_SPIKE,
        "content": (
            f"{more_positive} discussions are more positive than "
            f"{less_positive} ({reddit_avg:+.2f} vs {youtube_avg:+.2f}). "
            f"This suggests different audience sentiment across platforms."
        ),
        "confidence": min(0.5 + diff, 0.9),
        "metadata": {
            "reddit_avg": round(reddit_avg, 4),
            "youtube_avg": round(youtube_avg, 4),
            "difference": round(diff, 4),
        },
    }]


def _rule_dominant_theme(clusters, discussions) -> list[dict]:
    """
    Rule 6: Flag if one cluster contains >40% of all discussions.
    """
    total_discussions = discussions.count()
    if total_discussions == 0:
        return []

    for c in clusters:
        pct = round(c.member_count / total_discussions * 100)
        if pct > 40:
            return [{
                "type": Insight.InsightType.TREND_SPIKE,
                "content": (
                    f"'{c.label}' is the dominant theme with {pct}% of all "
                    f"discussions ({c.member_count} out of {total_discussions}). "
                    f"This topic heavily revolves around this theme."
                ),
                "confidence": min(0.5 + pct / 100, 0.95),
                "metadata": {
                    "cluster_id": c.id,
                    "cluster_label": c.label,
                    "percentage": pct,
                    "member_count": c.member_count,
                },
            }]
    return []


def _rule_unexpected_findings(sentiments, clusters) -> list[dict]:
    """
    Rule 7: Detect contradictions between overall and cluster sentiment.
    E.g., overall positive but a negative cluster exists (or vice versa).
    """
    avg = sentiments.aggregate(avg=Avg("compound_score"))["avg"] or 0.0

    for c in clusters:
        data = c.sentiment_data or {}
        cluster_score = data.get("avg_score", 0)

        # Overall positive but this cluster is negative
        if avg > 0.1 and cluster_score < -0.1:
            return [{
                "type": Insight.InsightType.EXPLANATION,
                "content": (
                    f"Despite overall positive sentiment ({avg:+.2f}), "
                    f"a cluster of criticism exists in '{c.label}' "
                    f"(avg: {cluster_score:+.2f}). This represents a "
                    f"minority viewpoint worth investigating."
                ),
                "confidence": 0.75,
                "metadata": {
                    "overall_avg": round(avg, 4),
                    "cluster_id": c.id,
                    "cluster_label": c.label,
                    "cluster_avg": round(cluster_score, 4),
                },
            }]

        # Overall negative but this cluster is positive
        if avg < -0.1 and cluster_score > 0.1:
            return [{
                "type": Insight.InsightType.EXPLANATION,
                "content": (
                    f"Despite overall negative sentiment ({avg:+.2f}), "
                    f"positive sentiment exists in '{c.label}' "
                    f"(avg: {cluster_score:+.2f}). Some discussions "
                    f"express appreciation despite the dominant criticism."
                ),
                "confidence": 0.75,
                "metadata": {
                    "overall_avg": round(avg, 4),
                    "cluster_id": c.id,
                    "cluster_label": c.label,
                    "cluster_avg": round(cluster_score, 4),
                },
            }]

    return []
