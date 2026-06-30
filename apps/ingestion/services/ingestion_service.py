"""
Ingestion service — orchestrates data collection from all sources.

WHY THIS FILE EXISTS:
    This is the Service Layer for ingestion. The view calls
    ingest_topic(topic_id) and this function handles everything:
    adapter initialization, fetching, preprocessing, saving, and
    error handling. The view stays thin (HTTP only), and this service
    is a plain Python function that can be tested without Django's
    request/response cycle.

INTERVIEW Q: "How does the ingestion pipeline run?"
    "The view submits ingest_topic() to the JobRunner, which runs it
    in a background thread. The function updates topic.status as it
    progresses, so the frontend can poll GET /status/ and see the
    discussion_count increase in real time. The job runner is pluggable —
    I can swap ThreadJobRunner for CeleryJobRunner without changing
    this file."

INTERVIEW Q: "What if two users trigger ingestion for the same topic?"
    "The view checks topic.status == 'ingesting' and returns 409
    Conflict. Only one ingestion can run per topic at a time. This
    is a simple mutex — production would use database locking or
    Celery's task deduplication."
"""
import json
import logging
import time
from datetime import datetime
from typing import Optional

from django.utils import timezone

from apps.topics.models import Topic, Discussion
from apps.ingestion.adapters.reddit import RedditAdapter
from apps.ingestion.adapters.youtube import YouTubeAdapter
from apps.ingestion.services.preprocessing_service import (
    preprocess_text,
    is_quality_content,
    is_near_duplicate,
)

logger = logging.getLogger("apps.ingestion")


def ingest_topic(topic_id: int) -> dict:
    """
    Run the full ingestion pipeline for a topic.

    This function is submitted to the JobRunner (thread or sync).
    It updates the topic status as it progresses so the frontend
    can poll for real-time updates.

    Steps:
    1. Set topic status → "ingesting"
    2. Initialize adapters (Reddit always, YouTube if configured)
    3. Fetch raw discussions from each source (with limits)
    4. Preprocess text (clean, normalize)
    5. Quality filter (min length, dedup, repetition check)
    6. Save to database with deduplication
    7. Set topic status → "completed"
    8. Store ingestion metrics

    Returns:
        dict with ingestion stats
    """
    topic = Topic.objects.get(id=topic_id)
    topic.status = Topic.Status.INGESTING
    topic.save(update_fields=["status", "updated_at"])

    started_at = time.time()

    stats = {
        "saved": 0,
        "duplicates": 0,
        "skipped": 0,
        "quality_filtered": 0,
        "errors": [],
        "sources": {},
        "failed_sources": [],
    }

    try:
        # Initialize available adapters
        adapters = _get_adapters()
        logger.info(
            "Ingestion started for topic '%s' (id=%d) with %d source(s)",
            topic.name, topic.id, len(adapters),
        )

        # Track seen content for near-duplicate detection
        seen_texts = set()

        # Fetch from each source
        for adapter in adapters:
            source_name = adapter.get_source_name()
            try:
                raw_discussions = adapter.fetch(topic.name)
                logger.info(
                    "Fetched %d raw discussions from %s",
                    len(raw_discussions), source_name,
                )

                # Preprocess, filter, and save each discussion
                source_saved = 0
                for raw in raw_discussions:
                    result = _save_discussion(topic, raw, seen_texts)
                    if result == "saved":
                        stats["saved"] += 1
                        source_saved += 1
                    elif result == "duplicate":
                        stats["duplicates"] += 1
                    elif result == "quality_filtered":
                        stats["quality_filtered"] += 1
                    elif result == "skipped":
                        stats["skipped"] += 1

                stats["sources"][source_name] = source_saved

            except Exception as e:
                error_msg = f"{source_name}: {str(e)}"
                stats["errors"].append(error_msg)
                stats["failed_sources"].append(source_name)
                logger.error("Adapter error — %s", error_msg)

        # Calculate ingestion duration
        ingestion_duration = round(time.time() - started_at, 2)

        logger.info(
            "Ingestion completed for '%s' in %.1fs: "
            "%d saved, %d filtered, %d duplicates, %d skipped",
            topic.name, ingestion_duration,
            stats["saved"], stats["quality_filtered"],
            stats["duplicates"], stats["skipped"],
        )

        # ===== Phase 4: Chain embedding generation =====
        # WHY chain here (not separate endpoint):
        #   The pipeline is: ingestion → embedding → clustering → completed.
        #   Each step feeds the next. Running them in sequence within one
        #   job means the user clicks "Analyze" once and gets the full pipeline.
        #   Status updates let the frontend show each step's progress.

        embedding_stats = {"embedded": 0, "duration": 0.0}
        if stats["saved"] > 0:
            topic.status = Topic.Status.ANALYZING
            topic.save(update_fields=["status", "updated_at"])

            try:
                from apps.analysis.services.embedding_service import generate_embeddings
                embedding_stats = generate_embeddings(topic_id)
            except Exception as e:
                logger.error("Embedding generation failed for topic %d: %s", topic_id, e)
                stats["errors"].append(f"embeddings: {str(e)}")

        # ===== Phase 5: Chain clustering =====
        # Clustering runs after embeddings. Metrics are stored in AnalysisRun
        # (not topic.description) to keep Topic lightweight.
        clustering_stats = {"cluster_count": 0, "skipped": True}
        if embedding_stats.get("embedded", 0) > 0:
            try:
                from apps.analysis.services.clustering_service import cluster_discussions
                clustering_stats = cluster_discussions(topic_id)
            except Exception as e:
                logger.error("Clustering failed for topic %d: %s", topic_id, e)
                stats["errors"].append(f"clustering: {str(e)}")

        # ===== Phase 6: Chain sentiment analysis =====
        sentiment_stats = {"positive": 0, "neutral": 0, "negative": 0}
        try:
            from apps.analysis.services.sentiment_service import (
                analyze_sentiment,
                compute_cluster_sentiment,
            )
            sentiment_stats = analyze_sentiment(topic_id)

            # Aggregate sentiment per cluster
            if clustering_stats.get("cluster_count", 0) > 0:
                compute_cluster_sentiment(topic_id)
        except Exception as e:
            logger.error("Sentiment analysis failed for topic %d: %s", topic_id, e)
            stats["errors"].append(f"sentiment: {str(e)}")

        # ===== Phase 6: Chain insight generation =====
        try:
            from apps.analysis.services.insight_service import generate_insights
            from apps.analysis.models import AnalysisRun
            # Reuse the analysis run created by clustering
            analysis_run = (
                AnalysisRun.objects
                .filter(topic_id=topic_id)
                .order_by("-started_at")
                .first()
            )
            generate_insights(topic_id, analysis_run)
        except Exception as e:
            logger.error("Insight generation failed for topic %d: %s", topic_id, e)
            stats["errors"].append(f"insights: {str(e)}")

        # Store lightweight ingestion metrics in topic.description
        # (clustering/sentiment metrics live in AnalysisRun + SentimentResult)
        metrics = {
            "ingestion_duration": ingestion_duration,
            "saved": stats["saved"],
            "duplicates": stats["duplicates"],
            "skipped": stats["skipped"],
            "quality_filtered": stats["quality_filtered"],
            "failed_sources": stats["failed_sources"],
            "sources": stats["sources"],
            "embeddings": {
                "count": embedding_stats.get("embedded", 0),
                "duration": embedding_stats.get("duration", 0.0),
                "model": embedding_stats.get("model", ""),
            },
        }
        topic.description = json.dumps(metrics)
        topic.status = Topic.Status.COMPLETED
        topic.save(update_fields=["status", "description", "updated_at"])

    except Exception as e:
        logger.error("Ingestion failed for topic %d: %s", topic_id, str(e))
        topic.status = Topic.Status.FAILED
        topic.save(update_fields=["status", "updated_at"])
        stats["errors"].append(str(e))

    return stats


def _get_adapters() -> list:
    """
    Initialize and return all available adapters.

    Reddit always runs (no credentials needed).
    YouTube runs only if YOUTUBE_API_KEY is configured.
    """
    adapters = [RedditAdapter()]

    youtube = YouTubeAdapter()
    if youtube.is_available():
        adapters.append(youtube)
    else:
        logger.info("YouTube adapter skipped (no API key configured)")

    return adapters


def _save_discussion(topic: Topic, raw: dict, seen_texts: set) -> str:
    """
    Preprocess, quality-filter, and save a single discussion.

    Pipeline:
    1. Preprocess text (clean, normalize)
    2. Quality filter (min length, repetition check)
    3. Near-duplicate check against already-seen content
    4. Save with deduplication via unique constraint

    Returns:
        "saved" — new record created
        "duplicate" — record already existed (updated)
        "quality_filtered" — rejected by quality checks
        "skipped" — content too short or save error
    """
    # Step 1: Preprocess text fields
    content = preprocess_text(raw.get("content", ""))
    title = preprocess_text(raw.get("title", ""))

    # Step 2: Quality filter
    if not is_quality_content(content):
        return "quality_filtered"

    # Step 3: Near-duplicate check
    if is_near_duplicate(content, seen_texts):
        return "quality_filtered"

    # Track this content for future duplicate checks
    seen_texts.add(content)

    # Parse published_at if it's a string
    published_at = raw.get("published_at")
    if isinstance(published_at, str) and published_at:
        try:
            published_at = datetime.fromisoformat(
                published_at.replace("Z", "+00:00")
            )
        except (ValueError, TypeError):
            published_at = None

    try:
        _, created = Discussion.objects.update_or_create(
            source=raw.get("source", ""),
            source_id=raw.get("source_id", ""),
            defaults={
                "topic": topic,
                "title": title,
                "content": content,
                "author": raw.get("author", ""),
                "url": raw.get("url", ""),
                "published_at": published_at,
                "metadata": raw.get("metadata", {}),
            },
        )
        return "saved" if created else "duplicate"

    except Exception as e:
        logger.error("Failed to save discussion %s: %s", raw.get("source_id"), e)
        return "skipped"
