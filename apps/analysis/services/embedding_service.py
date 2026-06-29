"""
Embedding service — generates semantic vector representations of discussions.

WHAT ARE EMBEDDINGS:
    Embeddings are fixed-length numerical vectors (arrays of 384 floats)
    that capture the semantic meaning of text. Two sentences with similar
    meaning produce vectors that are close together in 384-dimensional space,
    even if they share no words.

WHY VECTORS REPRESENT MEANING:
    The model (all-MiniLM-L6-v2) is a transformer neural network trained
    on hundreds of millions of sentence pairs. During training, it learns
    to map semantically similar sentences to nearby points in vector space:
        - "I love this product" → [0.12, -0.45, ...] (384 dims)
        - "This item is amazing" → [0.11, -0.44, ...] (close in space)
        - "Stock prices crashed" → [-0.87, 0.33, ...] (far away)

    The 384 dimensions encode topic, sentiment, and context. Unlike keyword
    matching, embeddings understand that "bank" in "river bank" differs
    from "savings bank."

WHY THIS FILE EXISTS:
    Service layer for embedding generation. The ingestion service calls
    generate_embeddings(topic_id) after data collection completes. This
    function batch-encodes all discussions for a topic and stores the
    vectors in the Embedding model.

INTERVIEW Q: "Why all-MiniLM-L6-v2?"
    "It's 80MB (vs 400MB for BERT-large), runs locally without a GPU,
    produces 384-dimensional vectors, and scores within 5% of larger
    models on semantic similarity benchmarks. For a placement project
    analyzing ~50-100 discussions, it's the sweet spot of quality vs
    resource usage."

INTERVIEW Q: "Why batch encoding?"
    "SentenceTransformer.encode() accepts a list of strings and processes
    them in batches (default 32). This is 10-50x faster than encoding
    one at a time because the GPU/CPU can parallelize matrix operations
    across the batch. For 50 discussions, batch encoding takes ~1 second
    vs ~10 seconds one-by-one."

INTERVIEW Q: "How do you store vectors?"
    "As raw bytes in a BinaryField. numpy.ndarray.tobytes() serializes
    a 384-float32 vector into 1,536 bytes. To deserialize:
    numpy.frombuffer(bytes, dtype=float32). This is compact (no JSON
    overhead) and fast (zero parsing). For production with similarity
    search, I'd switch to pgvector — but for batch reads during
    clustering, BinaryField is simpler."
"""
import logging
import time
from typing import Optional

import numpy as np

from apps.topics.models import Topic, Discussion
from apps.analysis.models import Embedding

logger = logging.getLogger("apps.analysis")

# Model configuration
MODEL_NAME = "all-MiniLM-L6-v2"
EMBEDDING_DIMENSIONS = 384
BATCH_SIZE = 32

# Module-level cache for the model (loaded once, reused across calls)
# WHY: Loading the model takes 2-3 seconds. Caching it means the first
# topic takes 3s, subsequent topics take <1s for the embedding step.
_model_cache = None


def _get_model():
    """
    Lazy-load the SentenceTransformer model.

    WHY lazy loading:
        Importing sentence_transformers at module level would add 3 seconds
        to Django startup (even for manage.py commands that don't need
        embeddings). Lazy loading means the cost is paid only when
        generate_embeddings() is first called.
    """
    global _model_cache
    if _model_cache is None:
        from sentence_transformers import SentenceTransformer
        logger.info("Loading SentenceTransformer model: %s", MODEL_NAME)
        _model_cache = SentenceTransformer(MODEL_NAME)
        logger.info("Model loaded successfully (%d dimensions)", EMBEDDING_DIMENSIONS)
    return _model_cache


def generate_embeddings(topic_id: int) -> dict:
    """
    Generate semantic embeddings for all discussions in a topic.

    Pipeline:
    1. Load all discussions that don't already have embeddings
    2. Extract text content
    3. Batch encode using SentenceTransformer
    4. Store each vector as an Embedding row
    5. Return stats

    Args:
        topic_id: The topic whose discussions to embed.

    Returns:
        {
            "embedded": int,     # Number of new embeddings created
            "skipped": int,      # Already had embeddings
            "duration": float,   # Seconds elapsed
            "model": str,        # Model name used
            "dimensions": int,   # Vector dimensionality
        }
    """
    started_at = time.time()

    topic = Topic.objects.get(id=topic_id)

    stats = {
        "embedded": 0,
        "skipped": 0,
        "duration": 0.0,
        "model": MODEL_NAME,
        "dimensions": EMBEDDING_DIMENSIONS,
    }

    # Step 1: Get discussions that need embedding
    # Exclude those that already have an embedding with the same model
    discussions = list(
        topic.discussions
        .exclude(embedding__model_name=MODEL_NAME)
        .values_list("id", "content")
    )

    if not discussions:
        stats["skipped"] = topic.discussions.count()
        stats["duration"] = round(time.time() - started_at, 2)
        logger.info(
            "No new discussions to embed for topic '%s' (%d already embedded)",
            topic.name, stats["skipped"],
        )
        return stats

    discussion_ids = [d[0] for d in discussions]
    texts = [d[1] for d in discussions]

    logger.info(
        "Generating embeddings for %d discussions (topic: '%s')",
        len(texts), topic.name,
    )

    # Step 2: Batch encode
    model = _get_model()
    vectors = model.encode(
        texts,
        batch_size=BATCH_SIZE,
        show_progress_bar=False,
        normalize_embeddings=True,  # L2 normalize for cosine similarity
    )

    # Step 3: Store embeddings
    embeddings_to_create = []
    for i, (disc_id, vector) in enumerate(zip(discussion_ids, vectors)):
        # Serialize numpy array to bytes
        vector_bytes = vector.astype(np.float32).tobytes()

        embeddings_to_create.append(
            Embedding(
                discussion_id=disc_id,
                vector=vector_bytes,
                model_name=MODEL_NAME,
                dimensions=EMBEDDING_DIMENSIONS,
            )
        )

    # Bulk create for performance (one INSERT instead of N)
    # ignore_conflicts=True handles race conditions where another
    # process might have created embeddings concurrently
    Embedding.objects.bulk_create(
        embeddings_to_create,
        ignore_conflicts=True,
    )

    stats["embedded"] = len(embeddings_to_create)
    stats["skipped"] = topic.discussions.count() - len(embeddings_to_create)
    stats["duration"] = round(time.time() - started_at, 2)

    logger.info(
        "Embeddings complete for '%s': %d embedded in %.1fs (model: %s)",
        topic.name, stats["embedded"], stats["duration"], MODEL_NAME,
    )

    return stats


def get_embedding_vectors(topic_id: int) -> tuple[list[int], np.ndarray]:
    """
    Load all embedding vectors for a topic as a numpy matrix.

    Used by downstream services (clustering, similarity search).

    Returns:
        (discussion_ids, vectors_matrix)
        - discussion_ids: list of Discussion PKs
        - vectors_matrix: numpy array of shape [N, 384]

    INTERVIEW Q: "Why return a matrix instead of individual vectors?"
        "scikit-learn's KMeans.fit() expects a 2D matrix. Returning
        (ids, matrix) lets the clustering service pass the matrix
        directly without reshaping. The ids list maintains the mapping
        between row index and Discussion PK."
    """
    embeddings = (
        Embedding.objects
        .filter(discussion__topic_id=topic_id, model_name=MODEL_NAME)
        .values_list("discussion_id", "vector")
    )

    if not embeddings:
        return [], np.array([])

    ids = []
    vectors = []
    for disc_id, vector_bytes in embeddings:
        ids.append(disc_id)
        vectors.append(np.frombuffer(vector_bytes, dtype=np.float32))

    return ids, np.vstack(vectors)
