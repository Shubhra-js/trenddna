"""
Clustering service — discovers thematic groups in discussion embeddings.

WHAT CLUSTERING DOES:
    Given N discussions as 384-dimensional vectors, KMeans finds K groups
    where discussions within each group are semantically similar. The
    algorithm minimizes the sum of squared distances from each point to
    its cluster centroid — which, for L2-normalized embeddings, is
    equivalent to maximizing cosine similarity within clusters.

WHY KMEANS (not DBSCAN or Hierarchical):
    1. Every discussion gets assigned to exactly one cluster (no outliers).
    2. L2-normalized vectors → cosine distance ≈ Euclidean distance,
       which is exactly what KMeans optimizes.
    3. Silhouette score automatically selects K — no manual tuning.
    4. For 50-100 discussions, KMeans runs in <100ms.

    DBSCAN would leave outlier discussions unassigned, and the epsilon
    parameter is harder to tune in 384-dimensional space.

INTERVIEW Q: "How do you choose K automatically?"
    "I run KMeans for K=2 to K=8, compute the silhouette score for each.
    Silhouette score measures how similar a discussion is to its own
    cluster versus the next closest cluster (range -1 to +1). I pick
    the K with the highest silhouette score. If all scores are below
    0.15, I fallback to K=2 — which means the data doesn't have strong
    thematic grouping, and two broad clusters are better than many noisy ones."

INTERVIEW Q: "What is silhouette score?"
    "For each data point, silhouette = (b - a) / max(a, b), where
    a = average distance to same-cluster points, b = average distance
    to nearest different-cluster points. A score near 1 means tight,
    well-separated clusters. Near 0 means overlapping clusters.
    Negative means the point is in the wrong cluster."

INTERVIEW Q: "How do you generate cluster labels without LLMs?"
    "I run TF-IDF on each cluster's combined text, extract the top 5
    keywords, then use a heuristic: capitalize the two most distinctive
    keywords and append a category word from a small mapping (e.g.,
    'price' → 'concerns', 'performance' → 'analysis'). This gives
    labels like 'Pricing Concerns' or 'Performance Discussion' without
    any external API calls."
"""
import logging
import time
from collections import Counter

import numpy as np
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.feature_extraction.text import TfidfVectorizer

from django.utils import timezone

from apps.topics.models import Topic, Discussion
from apps.analysis.models import AnalysisRun, Cluster, ClusterMembership, Embedding

logger = logging.getLogger("apps.analysis")

# =============================================================================
# Configuration
# =============================================================================

# Range of K values to evaluate
MIN_K = 2
MAX_K = 8

# Minimum silhouette score to accept clustering results.
# Below this threshold, we fallback to K=2 (broad grouping).
MIN_SILHOUETTE_THRESHOLD = 0.15

# Minimum number of discussions required for clustering.
# Below this, clustering is skipped entirely.
MIN_DISCUSSIONS_FOR_CLUSTERING = 10

# Number of representative discussions to store per cluster
TOP_DISCUSSIONS_PER_CLUSTER = 3

# Number of TF-IDF keywords to extract per cluster
TOP_KEYWORDS = 5

# =============================================================================
# Category suffixes for heuristic label generation
# =============================================================================

# Maps common keywords to descriptive category suffixes.
# Used by _generate_label() to create human-readable titles.
KEYWORD_CATEGORY_MAP = {
    "price": "Concerns",
    "pricing": "Concerns",
    "cost": "Concerns",
    "expensive": "Concerns",
    "cheap": "Concerns",
    "money": "Concerns",
    "worth": "Concerns",
    "buy": "Decisions",
    "purchase": "Decisions",
    "recommend": "Recommendations",
    "performance": "Analysis",
    "speed": "Analysis",
    "benchmark": "Analysis",
    "fast": "Analysis",
    "slow": "Analysis",
    "bug": "Issues",
    "issue": "Issues",
    "problem": "Issues",
    "error": "Issues",
    "fix": "Issues",
    "crash": "Issues",
    "love": "Reactions",
    "hate": "Reactions",
    "amazing": "Reactions",
    "terrible": "Reactions",
    "awesome": "Reactions",
    "worst": "Reactions",
    "best": "Reactions",
    "hype": "Reactions",
    "excited": "Reactions",
    "disappointed": "Reactions",
    "update": "Updates",
    "release": "Updates",
    "version": "Updates",
    "new": "Updates",
    "launch": "Updates",
    "feature": "Discussion",
    "design": "Discussion",
    "quality": "Discussion",
    "compare": "Comparison",
    "vs": "Comparison",
    "better": "Comparison",
    "alternative": "Comparison",
    "review": "Reviews",
    "opinion": "Reviews",
    "experience": "Reviews",
    "community": "Discussion",
    "help": "Support",
    "question": "Support",
    "how": "Support",
}

# Fallback category when no keywords match the map
DEFAULT_CATEGORY = "Discussion"


def cluster_discussions(topic_id: int) -> dict:
    """
    Run the full clustering pipeline for a topic.

    Pipeline:
    1. Load embedding vectors
    2. Validate minimum discussion count
    3. Auto-select K via silhouette analysis
    4. Run final KMeans with best K
    5. Extract TF-IDF keywords per cluster
    6. Generate human-readable labels
    7. Create explainability text
    8. Store AnalysisRun + Cluster + ClusterMembership rows

    Args:
        topic_id: The topic whose discussions to cluster.

    Returns:
        {
            "cluster_count": int,
            "best_k": int,
            "silhouette_score": float,
            "algorithm": str,
            "duration": float,
            "clusters": [{"label": str, "keywords": list, "member_count": int}],
            "skipped": bool,
            "skip_reason": str | None,
        }
    """
    started_at = time.time()
    topic = Topic.objects.get(id=topic_id)

    stats = {
        "cluster_count": 0,
        "best_k": 0,
        "silhouette_score": 0.0,
        "algorithm": "kmeans",
        "duration": 0.0,
        "clusters": [],
        "skipped": False,
        "skip_reason": None,
    }

    # Step 1: Load embedding vectors
    from apps.analysis.services.embedding_service import get_embedding_vectors
    discussion_ids, vectors = get_embedding_vectors(topic_id)

    # Step 2: Safeguard — minimum discussions
    if len(discussion_ids) < MIN_DISCUSSIONS_FOR_CLUSTERING:
        stats["skipped"] = True
        stats["skip_reason"] = (
            f"Only {len(discussion_ids)} discussions "
            f"(minimum {MIN_DISCUSSIONS_FOR_CLUSTERING} required)"
        )
        stats["duration"] = round(time.time() - started_at, 2)
        logger.info(
            "Clustering skipped for '%s': %s",
            topic.name, stats["skip_reason"],
        )
        return stats

    # Step 3: Auto-select K via silhouette analysis
    best_k, best_score, all_scores = _select_best_k(vectors)

    # Step 4: Silhouette fallback
    if best_score < MIN_SILHOUETTE_THRESHOLD:
        logger.info(
            "Silhouette %.3f below threshold %.3f — falling back to K=2",
            best_score, MIN_SILHOUETTE_THRESHOLD,
        )
        best_k = MIN_K
        # Recompute with K=2
        kmeans = KMeans(n_clusters=2, random_state=42, n_init=10)
        labels = kmeans.fit_predict(vectors)
        best_score = silhouette_score(vectors, labels)
    else:
        # Run final KMeans with the selected K
        kmeans = KMeans(n_clusters=best_k, random_state=42, n_init=10)
        labels = kmeans.fit_predict(vectors)

    logger.info(
        "Clustering '%s': K=%d, silhouette=%.3f",
        topic.name, best_k, best_score,
    )

    # Step 5: Create AnalysisRun with metrics
    analysis_run = AnalysisRun.objects.create(
        topic=topic,
        status=AnalysisRun.Status.RUNNING,
        parameters={
            "algorithm": "kmeans",
            "best_k": best_k,
            "silhouette_score": round(best_score, 4),
            "k_range": [MIN_K, MAX_K],
            "all_silhouette_scores": {
                str(k): round(s, 4) for k, s in all_scores.items()
            },
            "min_silhouette_threshold": MIN_SILHOUETTE_THRESHOLD,
            "inertia": round(float(kmeans.inertia_), 2),
        },
    )

    # Step 6: Load discussion texts for TF-IDF
    discussions_by_id = dict(
        Discussion.objects.filter(id__in=discussion_ids)
        .values_list("id", "content")
    )

    # Step 7: Create clusters with labels and keywords
    cluster_data = []
    for cluster_idx in range(best_k):
        # Get member discussion IDs and their indices
        member_mask = labels == cluster_idx
        member_ids = [
            discussion_ids[i]
            for i in range(len(discussion_ids))
            if member_mask[i]
        ]
        member_texts = [
            discussions_by_id.get(did, "") for did in member_ids
        ]

        # Extract keywords via TF-IDF
        keywords = _extract_keywords(member_texts, cluster_idx, best_k)

        # Generate human-readable label
        label = _generate_label(keywords)

        # Calculate coherence (average intra-cluster cosine similarity)
        cluster_vectors = vectors[member_mask]
        coherence = _calculate_coherence(cluster_vectors)

        # Generate explainability summary
        summary = _generate_explainability(
            label, keywords, len(member_ids), coherence,
        )

        # Create Cluster row
        cluster_obj = Cluster.objects.create(
            topic=topic,
            analysis_run=analysis_run,
            label=label,
            keywords=keywords,
            summary=summary,
            algorithm="kmeans",
            member_count=len(member_ids),
            coherence_score=round(coherence, 4),
        )

        # Create ClusterMembership rows
        # Calculate distance from each member to the cluster centroid
        centroid = kmeans.cluster_centers_[cluster_idx]
        memberships = []
        for i, did in enumerate(member_ids):
            vec_idx = discussion_ids.index(did)
            distance = float(np.linalg.norm(vectors[vec_idx] - centroid))
            memberships.append(
                ClusterMembership(
                    discussion_id=did,
                    cluster=cluster_obj,
                    distance=distance,
                )
            )

        ClusterMembership.objects.bulk_create(memberships)

        cluster_data.append({
            "label": label,
            "keywords": keywords,
            "member_count": len(member_ids),
            "coherence_score": round(coherence, 4),
        })

    # Step 8: Finalize AnalysisRun
    analysis_run.status = AnalysisRun.Status.COMPLETED
    analysis_run.completed_at = timezone.now()
    analysis_run.save(update_fields=["status", "completed_at"])

    stats["cluster_count"] = best_k
    stats["best_k"] = best_k
    stats["silhouette_score"] = round(best_score, 4)
    stats["clusters"] = cluster_data
    stats["duration"] = round(time.time() - started_at, 2)

    logger.info(
        "Clustering complete for '%s': %d clusters in %.1fs (silhouette=%.3f)",
        topic.name, best_k, stats["duration"], best_score,
    )

    return stats


# =============================================================================
# Internal Helper Functions
# =============================================================================

def _select_best_k(vectors: np.ndarray) -> tuple[int, float, dict]:
    """
    Evaluate K=2..8 and select the K with the highest silhouette score.

    WHY silhouette over elbow method:
        The elbow method requires visual inspection (subjective). Silhouette
        gives a single number — the best K is just argmax. This makes it
        fully automatic, no human judgment needed.

    Returns:
        (best_k, best_silhouette_score, all_scores_dict)
    """
    n_samples = len(vectors)
    max_k = min(MAX_K, n_samples - 1)  # K must be < N

    if max_k < MIN_K:
        return MIN_K, 0.0, {}

    scores = {}
    best_k = MIN_K
    best_score = -1.0

    for k in range(MIN_K, max_k + 1):
        kmeans = KMeans(n_clusters=k, random_state=42, n_init=10)
        cluster_labels = kmeans.fit_predict(vectors)

        score = silhouette_score(vectors, cluster_labels)
        scores[k] = score

        if score > best_score:
            best_score = score
            best_k = k

        logger.debug("K=%d: silhouette=%.4f, inertia=%.2f", k, score, kmeans.inertia_)

    return best_k, best_score, scores


def _extract_keywords(
    texts: list[str],
    cluster_idx: int,
    total_clusters: int,
) -> list[str]:
    """
    Extract top keywords from a cluster's discussions using TF-IDF.

    WHY TF-IDF (not just word frequency):
        Word frequency would surface common words like "the", "is", "it".
        TF-IDF down-weights words that appear across many clusters (high DF)
        and up-weights words distinctive to this cluster. If "GPU" appears
        in every cluster, its TF-IDF score is low. If "overclocking" appears
        only in this cluster, its score is high.

    Args:
        texts: Discussion content strings for this cluster.
        cluster_idx: Used for logging.
        total_clusters: Used for logging.

    Returns:
        List of top keywords (strings), e.g. ["price", "expensive", "quality"]
    """
    if not texts or all(not t.strip() for t in texts):
        return ["general", "discussion"]

    try:
        vectorizer = TfidfVectorizer(
            max_features=100,
            stop_words="english",
            min_df=1,
            max_df=0.95,  # Ignore words in >95% of docs
            ngram_range=(1, 1),  # Unigrams only
        )
        tfidf_matrix = vectorizer.fit_transform(texts)

        # Sum TF-IDF scores across all documents in this cluster
        feature_names = vectorizer.get_feature_names_out()
        scores = tfidf_matrix.sum(axis=0).A1  # Dense 1D array

        # Sort by score, take top N
        top_indices = scores.argsort()[::-1][:TOP_KEYWORDS]
        keywords = [feature_names[i] for i in top_indices]

        return keywords

    except Exception as e:
        logger.warning("TF-IDF failed for cluster %d: %s", cluster_idx, e)
        return ["general", "discussion"]


def _generate_label(keywords: list[str]) -> str:
    """
    Generate a human-readable cluster label from TF-IDF keywords.

    Heuristic:
    1. Find the first keyword that maps to a category suffix
    2. Use the top keyword (capitalized) + category suffix
    3. Fallback: capitalize top two keywords + "Discussion"

    Examples:
        ["price", "expensive", "quality"] → "Pricing Concerns"
        ["gpu", "benchmark", "fps"]       → "Benchmark Analysis"
        ["community", "mod", "server"]    → "Community Discussion"
        ["random", "stuff", "misc"]       → "Random & Stuff Discussion"

    INTERVIEW Q: "Why not use an LLM for labeling?"
        "LLM calls add latency (~1s per cluster), cost money, and require
        API keys. My heuristic runs in microseconds and produces readable
        labels for common discussion themes. For exotic topics, the fallback
        of 'Keyword1 & Keyword2 Discussion' is still informative."
    """
    if not keywords:
        return "General Discussion"

    # Find the first keyword with a category mapping
    category = None
    primary_keyword = None

    for kw in keywords:
        kw_lower = kw.lower()
        if kw_lower in KEYWORD_CATEGORY_MAP:
            category = KEYWORD_CATEGORY_MAP[kw_lower]
            primary_keyword = kw
            break

    if category and primary_keyword:
        # Map keyword to a more readable form for the label
        label_word = _keyword_to_label_word(primary_keyword)
        return f"{label_word} {category}"

    # Fallback: use top two keywords
    if len(keywords) >= 2:
        w1 = keywords[0].capitalize()
        w2 = keywords[1].capitalize()
        return f"{w1} & {w2} {DEFAULT_CATEGORY}"

    return f"{keywords[0].capitalize()} {DEFAULT_CATEGORY}"


def _keyword_to_label_word(keyword: str) -> str:
    """
    Convert a keyword to a more label-friendly form.
    E.g., "price" → "Pricing", "expensive" → "Pricing",
          "performance" → "Performance", "bug" → "Bug"
    """
    word_map = {
        "price": "Pricing",
        "pricing": "Pricing",
        "cost": "Cost",
        "expensive": "Pricing",
        "cheap": "Budget",
        "money": "Value",
        "worth": "Value",
        "buy": "Purchase",
        "purchase": "Purchase",
        "recommend": "Recommendation",
        "performance": "Performance",
        "speed": "Speed",
        "benchmark": "Benchmark",
        "fast": "Performance",
        "slow": "Performance",
        "bug": "Bug",
        "issue": "Technical",
        "problem": "Problem",
        "error": "Error",
        "fix": "Fix",
        "crash": "Crash",
        "love": "Fan",
        "hate": "Critical",
        "amazing": "Positive",
        "terrible": "Negative",
        "awesome": "Positive",
        "worst": "Negative",
        "best": "Positive",
        "hype": "Hype",
        "excited": "Excitement",
        "disappointed": "Disappointment",
        "update": "Update",
        "release": "Release",
        "version": "Version",
        "new": "New",
        "launch": "Launch",
        "feature": "Feature",
        "design": "Design",
        "quality": "Quality",
        "compare": "Comparison",
        "vs": "Comparison",
        "better": "Comparison",
        "alternative": "Alternative",
        "review": "User",
        "opinion": "Opinion",
        "experience": "User",
        "community": "Community",
        "help": "Help",
        "question": "Question",
        "how": "How-To",
    }
    return word_map.get(keyword.lower(), keyword.capitalize())


def _calculate_coherence(cluster_vectors: np.ndarray) -> float:
    """
    Calculate intra-cluster coherence as average pairwise cosine similarity.

    Range: 0.0 (random vectors) to 1.0 (identical vectors).

    WHY cosine similarity (not Euclidean distance):
        Our vectors are L2-normalized, so cosine similarity = dot product.
        A coherence of 0.7 means cluster members are quite semantically
        similar. Below 0.3 means the cluster is loose (diverse themes).
    """
    if len(cluster_vectors) < 2:
        return 1.0  # A single-member cluster is perfectly coherent

    # For L2-normalized vectors, cosine similarity = dot product
    # Compute pairwise similarities using matrix multiplication
    similarity_matrix = cluster_vectors @ cluster_vectors.T

    # Extract upper triangle (exclude self-similarity diagonal)
    n = len(cluster_vectors)
    upper_indices = np.triu_indices(n, k=1)
    pairwise_similarities = similarity_matrix[upper_indices]

    return float(np.mean(pairwise_similarities))


def _generate_explainability(
    label: str,
    keywords: list[str],
    member_count: int,
    coherence: float,
) -> str:
    """
    Generate a plain-English explanation of why this cluster exists.

    This is shown in the frontend's explainability panel. The goal is
    to make the clustering results interpretable for non-technical users.
    """
    keyword_str = ", ".join(f'"{kw}"' for kw in keywords[:3])

    # Describe coherence in plain language
    if coherence > 0.6:
        coherence_desc = "strongly"
    elif coherence > 0.4:
        coherence_desc = "moderately"
    else:
        coherence_desc = "loosely"

    explanation = (
        f"This cluster contains {member_count} discussions that are "
        f"{coherence_desc} related. They share semantic similarity around "
        f"topics like {keyword_str}. The clustering algorithm grouped these "
        f"discussions because their embedding vectors — numerical "
        f"representations of meaning — were close together in "
        f"384-dimensional space."
    )

    return explanation
