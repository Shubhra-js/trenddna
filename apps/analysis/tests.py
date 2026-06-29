"""
Tests for the analysis app — embeddings, models, and services.

Tests are organized by concern:
1. EmbeddingModelTest — model creation and constraints
2. EmbeddingServiceTest — embedding generation pipeline
3. QualityFilterTest — tests for the new quality filter functions

INTERVIEW Q: "How do you test ML code?"
    "I test the pipeline logic (batch loading, storage, deduplication)
    without calling the real model in most tests. The model test uses
    a mock that returns known vectors, so I can verify the service
    correctly serializes, stores, and retrieves them. I have one
    integration test that loads the real model to verify dimensions."
"""
import numpy as np
from unittest.mock import patch, MagicMock

from django.test import TestCase
from rest_framework.test import APIClient

from apps.topics.models import Topic, Discussion
from apps.analysis.models import Embedding
from apps.ingestion.services.preprocessing_service import (
    is_quality_content,
    is_near_duplicate,
)


class QualityFilterTest(TestCase):
    """Test the quality filter functions added in Phase 3 refinements."""

    def test_empty_content_rejected(self):
        self.assertFalse(is_quality_content(""))

    def test_none_content_rejected(self):
        self.assertFalse(is_quality_content(None))

    def test_short_content_rejected(self):
        """Content under 20 chars should be rejected."""
        self.assertFalse(is_quality_content("too short"))

    def test_valid_content_accepted(self):
        self.assertTrue(
            is_quality_content("this is a meaningful discussion about artificial intelligence")
        )

    def test_repetitive_content_rejected(self):
        """Spam-like repetitive text should be rejected."""
        self.assertFalse(
            is_quality_content("buy buy buy buy buy buy buy buy buy buy")
        )

    def test_near_duplicate_detection(self):
        """Near-duplicate text (>80% Jaccard overlap) should be detected."""
        seen = {"this is a test about machine learning and artificial intelligence"}
        # Same text with one word changed — should be flagged
        self.assertTrue(
            is_near_duplicate(
                "this is a test about machine learning and deep intelligence",
                seen,
            )
        )

    def test_non_duplicate_passes(self):
        """Sufficiently different text should not be flagged."""
        seen = {"this is about machine learning and artificial intelligence"}
        self.assertFalse(
            is_near_duplicate(
                "the stock market crashed today due to inflation concerns",
                seen,
            )
        )

    def test_empty_seen_set(self):
        """Empty seen set should never flag duplicates."""
        self.assertFalse(is_near_duplicate("any text here", set()))


class EmbeddingModelTest(TestCase):
    """Test the Embedding model — creation, constraints, serialization."""

    def setUp(self):
        self.topic = Topic.objects.create(name="Test embedding topic")
        self.discussion = Discussion.objects.create(
            topic=self.topic,
            source="reddit",
            source_id="test_emb_1",
            title="Test discussion",
            content="A meaningful discussion about artificial intelligence.",
        )

    def test_create_embedding(self):
        """Verify we can create an Embedding with serialized numpy vector."""
        vector = np.random.randn(384).astype(np.float32)
        embedding = Embedding.objects.create(
            discussion=self.discussion,
            vector=vector.tobytes(),
            model_name="all-MiniLM-L6-v2",
            dimensions=384,
        )

        self.assertEqual(embedding.dimensions, 384)
        self.assertEqual(embedding.model_name, "all-MiniLM-L6-v2")
        self.assertEqual(len(embedding.vector), 384 * 4)  # 4 bytes per float32

    def test_vector_roundtrip(self):
        """Verify vector survives serialize → DB → deserialize roundtrip."""
        original = np.array([0.1, -0.5, 0.3] + [0.0] * 381, dtype=np.float32)
        Embedding.objects.create(
            discussion=self.discussion,
            vector=original.tobytes(),
        )

        # Reload from DB
        saved = Embedding.objects.get(discussion=self.discussion)
        restored = np.frombuffer(saved.vector, dtype=np.float32)

        np.testing.assert_array_almost_equal(original, restored)

    def test_one_to_one_constraint(self):
        """Each discussion can have only one embedding."""
        vector = np.zeros(384, dtype=np.float32).tobytes()
        Embedding.objects.create(
            discussion=self.discussion,
            vector=vector,
        )
        with self.assertRaises(Exception):
            Embedding.objects.create(
                discussion=self.discussion,
                vector=vector,
            )


class EmbeddingServiceTest(TestCase):
    """
    Test the embedding service with mocked SentenceTransformer.

    WHY MOCK:
        Loading the real model takes 2-3 seconds and 80MB of RAM.
        Tests should be fast and deterministic. The mock returns
        known vectors so we can verify storage and retrieval logic.
    """

    def setUp(self):
        self.topic = Topic.objects.create(name="Embedding test topic")
        # Create 3 test discussions
        for i in range(3):
            Discussion.objects.create(
                topic=self.topic,
                source="reddit",
                source_id=f"emb_test_{i}",
                title=f"Discussion {i}",
                content=f"This is discussion number {i} about a meaningful topic with enough content.",
            )

    @patch("apps.analysis.services.embedding_service._get_model")
    def test_generate_embeddings_creates_records(self, mock_get_model):
        """Verify that generate_embeddings creates Embedding rows."""
        # Mock model returns 384-dim vectors
        mock_model = MagicMock()
        mock_model.encode.return_value = np.random.randn(3, 384).astype(np.float32)
        mock_get_model.return_value = mock_model

        from apps.analysis.services.embedding_service import generate_embeddings
        stats = generate_embeddings(self.topic.id)

        self.assertEqual(stats["embedded"], 3)
        self.assertEqual(stats["model"], "all-MiniLM-L6-v2")
        self.assertEqual(stats["dimensions"], 384)
        self.assertEqual(Embedding.objects.filter(discussion__topic=self.topic).count(), 3)

    @patch("apps.analysis.services.embedding_service._get_model")
    def test_skips_already_embedded(self, mock_get_model):
        """Running embeddings twice should skip already-embedded discussions."""
        mock_model = MagicMock()
        mock_model.encode.return_value = np.random.randn(3, 384).astype(np.float32)
        mock_get_model.return_value = mock_model

        from apps.analysis.services.embedding_service import generate_embeddings

        # First run
        stats1 = generate_embeddings(self.topic.id)
        self.assertEqual(stats1["embedded"], 3)

        # Second run — should skip all
        stats2 = generate_embeddings(self.topic.id)
        self.assertEqual(stats2["embedded"], 0)
        self.assertEqual(stats2["skipped"], 3)

    @patch("apps.analysis.services.embedding_service._get_model")
    def test_get_embedding_vectors(self, mock_get_model):
        """Verify get_embedding_vectors returns correct matrix shape."""
        mock_model = MagicMock()
        vectors = np.random.randn(3, 384).astype(np.float32)
        mock_model.encode.return_value = vectors
        mock_get_model.return_value = mock_model

        from apps.analysis.services.embedding_service import (
            generate_embeddings,
            get_embedding_vectors,
        )

        generate_embeddings(self.topic.id)
        ids, matrix = get_embedding_vectors(self.topic.id)

        self.assertEqual(len(ids), 3)
        self.assertEqual(matrix.shape, (3, 384))


class EmbeddingStatusTest(TestCase):
    """Test that the status endpoint includes embedding counts."""

    def setUp(self):
        self.client = APIClient()
        self.topic = Topic.objects.create(name="Status test topic")

    def test_status_includes_embeddings_count(self):
        """GET /api/v1/topics/{id}/status/ should include embeddings_count."""
        # Create a discussion and embedding
        disc = Discussion.objects.create(
            topic=self.topic,
            source="reddit",
            source_id="status_emb_1",
            content="Test content",
        )
        vector = np.zeros(384, dtype=np.float32).tobytes()
        Embedding.objects.create(discussion=disc, vector=vector)

        response = self.client.get(f"/api/v1/topics/{self.topic.id}/status/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["embeddings_count"], 1)

    def test_status_zero_embeddings(self):
        """Status should show 0 embeddings for a topic with no embeddings."""
        response = self.client.get(f"/api/v1/topics/{self.topic.id}/status/")
        self.assertEqual(response.data["embeddings_count"], 0)


# =============================================================================
# Phase 5: Clustering Tests
# =============================================================================

from apps.analysis.models import AnalysisRun, Cluster, ClusterMembership


class ClusteringServiceTest(TestCase):
    """
    Test the clustering service with mock embeddings.

    WHY MOCK EMBEDDINGS (not real ones):
        We're testing clustering logic, not the embedding model.
        Mocking lets us control the vector space precisely:
        we create clusters of known vectors and verify KMeans
        correctly groups them.
    """

    def setUp(self):
        self.topic = Topic.objects.create(name="Clustering test topic")
        # Create 12 discussions (above MIN_DISCUSSIONS_FOR_CLUSTERING=10)
        self.discussions = []
        for i in range(12):
            d = Discussion.objects.create(
                topic=self.topic,
                source="reddit",
                source_id=f"cluster_test_{i}",
                title=f"Discussion {i}",
                content=f"This is discussion number {i} about a meaningful topic with plenty of text content here.",
            )
            self.discussions.append(d)

    def _create_mock_embeddings(self, n_clusters=3):
        """Create embeddings that naturally form n_clusters groups."""
        np.random.seed(42)
        vectors = []
        for i, disc in enumerate(self.discussions):
            # Assign to cluster based on index
            cluster_idx = i % n_clusters
            # Create vector near a cluster center
            center = np.zeros(384, dtype=np.float32)
            center[cluster_idx * 10:(cluster_idx + 1) * 10] = 1.0
            noise = np.random.randn(384).astype(np.float32) * 0.1
            vector = center + noise
            # L2 normalize (like our real embeddings)
            vector = vector / np.linalg.norm(vector)

            Embedding.objects.create(
                discussion=disc,
                vector=vector.tobytes(),
                model_name="all-MiniLM-L6-v2",
                dimensions=384,
            )
            vectors.append(vector)
        return np.array(vectors)

    def test_cluster_discussions_creates_clusters(self):
        """Verify clustering creates Cluster and ClusterMembership rows."""
        self._create_mock_embeddings(n_clusters=3)

        from apps.analysis.services.clustering_service import cluster_discussions
        stats = cluster_discussions(self.topic.id)

        self.assertFalse(stats["skipped"])
        self.assertGreaterEqual(stats["cluster_count"], 2)
        self.assertLessEqual(stats["cluster_count"], 8)
        self.assertEqual(stats["algorithm"], "kmeans")
        self.assertGreater(stats["silhouette_score"], -1)

        # Verify Cluster rows created
        clusters = Cluster.objects.filter(topic=self.topic)
        self.assertEqual(clusters.count(), stats["cluster_count"])

        # Verify every discussion has a membership
        total_members = sum(c.member_count for c in clusters)
        self.assertEqual(total_members, 12)

        # Verify ClusterMembership rows
        memberships = ClusterMembership.objects.filter(
            cluster__topic=self.topic
        )
        self.assertEqual(memberships.count(), 12)

    def test_cluster_stores_metrics_in_analysis_run(self):
        """Verify AnalysisRun stores best_k, silhouette, algorithm."""
        self._create_mock_embeddings(n_clusters=2)

        from apps.analysis.services.clustering_service import cluster_discussions
        stats = cluster_discussions(self.topic.id)

        run = AnalysisRun.objects.filter(topic=self.topic).first()
        self.assertIsNotNone(run)
        self.assertEqual(run.status, AnalysisRun.Status.COMPLETED)
        self.assertIn("best_k", run.parameters)
        self.assertIn("silhouette_score", run.parameters)
        self.assertIn("algorithm", run.parameters)
        self.assertEqual(run.parameters["algorithm"], "kmeans")

    def test_clusters_have_labels_and_keywords(self):
        """Every cluster must have a non-empty label and keywords list."""
        self._create_mock_embeddings(n_clusters=2)

        from apps.analysis.services.clustering_service import cluster_discussions
        cluster_discussions(self.topic.id)

        for cluster in Cluster.objects.filter(topic=self.topic):
            self.assertTrue(len(cluster.label) > 0, "Cluster label is empty")
            self.assertIsInstance(cluster.keywords, list)
            self.assertTrue(len(cluster.keywords) > 0, "Keywords list is empty")

    def test_clusters_have_explainability_summary(self):
        """Every cluster must have a summary explanation."""
        self._create_mock_embeddings(n_clusters=2)

        from apps.analysis.services.clustering_service import cluster_discussions
        cluster_discussions(self.topic.id)

        for cluster in Cluster.objects.filter(topic=self.topic):
            self.assertTrue(len(cluster.summary) > 0, "Summary is empty")
            self.assertIn("discussions", cluster.summary.lower())


class ClusteringEdgeCaseTest(TestCase):
    """Test clustering safeguards and edge cases."""

    def setUp(self):
        self.topic = Topic.objects.create(name="Edge case topic")

    def test_skip_if_too_few_discussions(self):
        """Clustering should be skipped if < 10 discussions."""
        # Create only 5 discussions with embeddings
        for i in range(5):
            d = Discussion.objects.create(
                topic=self.topic,
                source="reddit",
                source_id=f"edge_{i}",
                content=f"Short content about topic {i} that is meaningful enough.",
            )
            vector = np.random.randn(384).astype(np.float32)
            vector = vector / np.linalg.norm(vector)
            Embedding.objects.create(
                discussion=d,
                vector=vector.tobytes(),
            )

        from apps.analysis.services.clustering_service import cluster_discussions
        stats = cluster_discussions(self.topic.id)

        self.assertTrue(stats["skipped"])
        self.assertIn("minimum", stats["skip_reason"])
        self.assertEqual(stats["cluster_count"], 0)

    def test_no_embeddings_skips_clustering(self):
        """Topic with no embeddings should skip clustering."""
        Discussion.objects.create(
            topic=self.topic,
            source="reddit",
            source_id="no_emb_1",
            content="Discussion without embedding",
        )

        from apps.analysis.services.clustering_service import cluster_discussions
        stats = cluster_discussions(self.topic.id)

        self.assertTrue(stats["skipped"])


class ClusterAPITest(TestCase):
    """Test the GET /api/v1/topics/{id}/clusters/ endpoint."""

    def setUp(self):
        self.client = APIClient()
        self.topic = Topic.objects.create(name="API cluster test")

    def test_empty_topic_returns_zero_clusters(self):
        """Topic with no clusters should return empty list."""
        response = self.client.get(
            f"/api/v1/topics/{self.topic.id}/clusters/"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["cluster_count"], 0)
        self.assertEqual(response.data["clusters"], [])

    def test_nonexistent_topic_returns_404(self):
        response = self.client.get("/api/v1/topics/99999/clusters/")
        self.assertEqual(response.status_code, 404)

    def test_clusters_endpoint_returns_correct_shape(self):
        """Verify response has all required fields when clusters exist."""
        # Create an analysis run with clusters
        run = AnalysisRun.objects.create(
            topic=self.topic,
            status=AnalysisRun.Status.COMPLETED,
            parameters={"algorithm": "kmeans", "silhouette_score": 0.42},
        )
        disc = Discussion.objects.create(
            topic=self.topic,
            source="reddit",
            source_id="api_cluster_1",
            title="Test discussion",
            content="Discussion about pricing and costs of products in the market.",
        )
        cluster = Cluster.objects.create(
            topic=self.topic,
            analysis_run=run,
            label="Pricing Concerns",
            keywords=["price", "expensive", "quality"],
            summary="This cluster is about pricing.",
            algorithm="kmeans",
            member_count=1,
            coherence_score=0.5,
        )
        ClusterMembership.objects.create(
            discussion=disc,
            cluster=cluster,
            distance=0.25,
        )

        response = self.client.get(
            f"/api/v1/topics/{self.topic.id}/clusters/"
        )
        self.assertEqual(response.status_code, 200)
        data = response.data

        # Top-level fields
        self.assertEqual(data["cluster_count"], 1)
        self.assertEqual(data["algorithm"], "kmeans")
        self.assertEqual(data["silhouette_score"], 0.42)
        self.assertEqual(data["largest_cluster"], "Pricing Concerns")

        # Cluster detail
        c = data["clusters"][0]
        self.assertEqual(c["label"], "Pricing Concerns")
        self.assertEqual(c["keywords"], ["price", "expensive", "quality"])
        self.assertEqual(c["member_count"], 1)
        self.assertIn("summary", c)
        self.assertIn("top_discussions", c)
        self.assertEqual(len(c["top_discussions"]), 1)

    def test_status_includes_cluster_count(self):
        """GET /status/ should include cluster_count field."""
        response = self.client.get(
            f"/api/v1/topics/{self.topic.id}/status/"
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("cluster_count", response.data)


class LabelGenerationTest(TestCase):
    """Test the heuristic label generation from keywords."""

    def test_pricing_keywords_generate_label(self):
        from apps.analysis.services.clustering_service import _generate_label
        label = _generate_label(["price", "expensive", "quality"])
        self.assertIn("Pricing", label)

    def test_performance_keywords_generate_label(self):
        from apps.analysis.services.clustering_service import _generate_label
        label = _generate_label(["performance", "speed", "benchmark"])
        self.assertIn("Performance", label)

    def test_fallback_label(self):
        from apps.analysis.services.clustering_service import _generate_label
        label = _generate_label(["random", "stuff"])
        self.assertIn("Discussion", label)

    def test_empty_keywords(self):
        from apps.analysis.services.clustering_service import _generate_label
        label = _generate_label([])
        self.assertEqual(label, "General Discussion")
