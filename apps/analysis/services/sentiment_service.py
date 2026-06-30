"""
Sentiment analysis service — measures opinion polarity in discussions.

WHAT VADER DOES:
    VADER (Valence Aware Dictionary and sEntiment Reasoner) is a rule-based
    sentiment analysis tool built for social media text. It uses a lexicon
    of ~7,500 words rated for sentiment polarity plus rules for:
    - Capitalization: "GREAT" is more intense than "great"
    - Punctuation: "Great!!!" is more intense than "Great"
    - Degree modifiers: "very good" > "good"
    - Negation: "not good" flips polarity
    - Conjunctions: "The food was great but the service was terrible"

WHY VADER (not TextBlob, not transformers):
    1. Built for social media — handles Reddit/YouTube comment style
    2. No training needed — works out of the box on any domain
    3. Fast — ~10,000 texts/second (transformer models: ~100/second)
    4. No GPU, no API keys, no cost
    5. Interpretable — every score can be traced to lexicon entries

INTERVIEW Q: "Why not use a transformer-based sentiment model?"
    "For an MVP analyzing 50-200 discussions, VADER gives good-enough
    results in milliseconds. A fine-tuned BERT for sentiment would
    improve accuracy by ~5-10% but add 2GB of model weight, require
    GPU for reasonable speed, and is harder to explain in an interview.
    VADER's rule-based approach means I can debug any score by looking
    at which words triggered it."

INTERVIEW Q: "How accurate is VADER?"
    "On social media text, VADER achieves ~0.96 classification accuracy
    (F1) for positive/negative/neutral — comparable to human annotators.
    It struggles with sarcasm and domain-specific jargon, but for
    general internet discussions, it's reliable."
"""
import logging
import time
import ssl

from django.db.models import Avg

from apps.topics.models import Topic, Discussion
from apps.analysis.models import SentimentResult, Cluster, ClusterMembership

logger = logging.getLogger("apps.analysis")

# =============================================================================
# VADER Initialization (lazy-loaded)
# =============================================================================

_analyzer = None


def _get_analyzer():
    """
    Lazy-load the VADER analyzer. Downloads lexicon on first use.

    WHY LAZY:
        Importing nltk and loading the lexicon takes ~200ms. We only
        pay this cost when sentiment analysis is actually needed.
    """
    global _analyzer
    if _analyzer is None:
        try:
            from nltk.sentiment.vader import SentimentIntensityAnalyzer
            _analyzer = SentimentIntensityAnalyzer()
        except LookupError:
            # Download VADER lexicon if not present
            import nltk
            try:
                _create_unverified = ssl._create_unverified_context
            except AttributeError:
                pass
            else:
                ssl._create_default_https_context = _create_unverified
            nltk.download("vader_lexicon", quiet=True)
            from nltk.sentiment.vader import SentimentIntensityAnalyzer
            _analyzer = SentimentIntensityAnalyzer()
    return _analyzer


# =============================================================================
# Sentiment Thresholds
# =============================================================================

# VADER compound score thresholds for label assignment
# These are the standard thresholds recommended in the VADER paper.
POSITIVE_THRESHOLD = 0.05
NEGATIVE_THRESHOLD = -0.05


def _classify_sentiment(compound: float) -> str:
    """
    Classify compound score into positive/negative/neutral.

    INTERVIEW Q: "Why 0.05 and not 0.0?"
        "The VADER paper recommends ±0.05 as the neutral zone. Scores
        between -0.05 and +0.05 are genuinely ambiguous — classifying
        them as neutral reduces false positives in both directions."
    """
    if compound >= POSITIVE_THRESHOLD:
        return SentimentResult.Label.POSITIVE
    elif compound <= NEGATIVE_THRESHOLD:
        return SentimentResult.Label.NEGATIVE
    return SentimentResult.Label.NEUTRAL


# =============================================================================
# Main Service Functions
# =============================================================================

def analyze_sentiment(topic_id: int) -> dict:
    """
    Analyze sentiment for all discussions in a topic.

    Pipeline:
    1. Load discussions that don't have SentimentResult yet
    2. For each: VADER polarity_scores() → compound, pos, neg, neu
    3. Classify label from compound score
    4. bulk_create SentimentResult rows

    Returns:
        {
            "discussion_count": 42,
            "positive": 18,
            "neutral": 15,
            "negative": 9,
            "average_sentiment": 0.23,
            "duration": 1.2,
            "skipped": 3,
        }
    """
    started_at = time.time()
    topic = Topic.objects.get(id=topic_id)

    # Get discussions that haven't been analyzed yet
    analyzed_ids = set(
        SentimentResult.objects
        .filter(discussion__topic_id=topic_id)
        .values_list("discussion_id", flat=True)
    )

    discussions = Discussion.objects.filter(topic_id=topic_id)
    unanalyzed = [d for d in discussions if d.id not in analyzed_ids]

    if not unanalyzed:
        # All discussions already analyzed
        existing = SentimentResult.objects.filter(discussion__topic_id=topic_id)
        counts = _count_labels(existing)
        avg = existing.aggregate(avg=Avg("compound_score"))["avg"] or 0.0
        logger.info(
            "Sentiment already complete for '%s' (%d results)",
            topic.name, len(analyzed_ids),
        )
        return {
            "discussion_count": len(analyzed_ids),
            "skipped": len(analyzed_ids),
            **counts,
            "average_sentiment": round(avg, 4),
            "duration": round(time.time() - started_at, 2),
        }

    # Run VADER on unanalyzed discussions
    analyzer = _get_analyzer()
    results = []

    for disc in unanalyzed:
        text = disc.content or ""
        if not text.strip():
            continue

        scores = analyzer.polarity_scores(text)
        label = _classify_sentiment(scores["compound"])

        results.append(SentimentResult(
            discussion=disc,
            compound_score=scores["compound"],
            positive_score=scores["pos"],
            negative_score=scores["neg"],
            neutral_score=scores["neu"],
            label=label,
        ))

    # Bulk insert
    if results:
        SentimentResult.objects.bulk_create(results, ignore_conflicts=True)

    # Count labels across ALL results (existing + new)
    all_results = SentimentResult.objects.filter(discussion__topic_id=topic_id)
    counts = _count_labels(all_results)
    avg = all_results.aggregate(avg=Avg("compound_score"))["avg"] or 0.0

    duration = round(time.time() - started_at, 2)
    logger.info(
        "Sentiment analysis for '%s': %d analyzed in %.1fs "
        "(+%d positive, %d neutral, -%d negative, avg=%.3f)",
        topic.name, len(results), duration,
        counts["positive"], counts["neutral"], counts["negative"], avg,
    )

    return {
        "discussion_count": len(results) + len(analyzed_ids),
        "skipped": len(analyzed_ids),
        **counts,
        "average_sentiment": round(avg, 4),
        "duration": duration,
    }


def compute_cluster_sentiment(topic_id: int) -> list[dict]:
    """
    Aggregate sentiment per cluster and store in cluster.sentiment_data.

    For each cluster:
    1. Get member discussions' SentimentResults
    2. Calculate: avg compound, dominant label, pos/neg/neutral percentages
    3. Store as JSON in cluster.sentiment_data

    Returns:
        List of cluster sentiment summaries.
    """
    clusters = Cluster.objects.filter(topic_id=topic_id)
    cluster_sentiments = []

    for cluster in clusters:
        # Get member discussion IDs
        member_ids = (
            ClusterMembership.objects
            .filter(cluster=cluster)
            .values_list("discussion_id", flat=True)
        )

        # Get sentiment results for members
        sentiments = SentimentResult.objects.filter(discussion_id__in=member_ids)
        total = sentiments.count()

        if total == 0:
            sentiment_data = {
                "avg_score": 0.0,
                "label": "neutral",
                "positive_pct": 0,
                "negative_pct": 0,
                "neutral_pct": 100,
            }
        else:
            avg_score = sentiments.aggregate(avg=Avg("compound_score"))["avg"] or 0.0
            pos_count = sentiments.filter(label=SentimentResult.Label.POSITIVE).count()
            neg_count = sentiments.filter(label=SentimentResult.Label.NEGATIVE).count()
            neu_count = sentiments.filter(label=SentimentResult.Label.NEUTRAL).count()

            sentiment_data = {
                "avg_score": round(avg_score, 4),
                "label": _classify_sentiment(avg_score),
                "positive_pct": round(pos_count / total * 100),
                "negative_pct": round(neg_count / total * 100),
                "neutral_pct": round(neu_count / total * 100),
            }

        cluster.sentiment_data = sentiment_data
        cluster.save(update_fields=["sentiment_data"])

        cluster_sentiments.append({
            "cluster_id": cluster.id,
            "label": cluster.label,
            **sentiment_data,
        })

    logger.info(
        "Cluster sentiment computed for topic %d: %d clusters",
        topic_id, len(cluster_sentiments),
    )

    return cluster_sentiments


# =============================================================================
# Helper Functions
# =============================================================================

def _count_labels(queryset) -> dict:
    """Count positive/neutral/negative labels in a queryset."""
    return {
        "positive": queryset.filter(label=SentimentResult.Label.POSITIVE).count(),
        "neutral": queryset.filter(label=SentimentResult.Label.NEUTRAL).count(),
        "negative": queryset.filter(label=SentimentResult.Label.NEGATIVE).count(),
    }
