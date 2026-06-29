"""
Tests for the ingestion pipeline.

Tests are organized by layer:
1. PreprocessingTest — pure function tests for text cleaning
2. IngestionAPITest — endpoint integration tests
3. AdapterNormalizationTest — verifies normalized data shape

INTERVIEW Q: "How do you test external API calls?"
    "I don't call Reddit/YouTube in unit tests — that would be flaky
    and slow. I test the preprocessing layer with known inputs, test
    the API endpoints with Django's test client, and test adapters'
    normalization with fixture data. For integration tests against
    real APIs, I'd use VCR.py to record and replay HTTP responses."
"""
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status as http_status

from apps.topics.models import Topic, Discussion
from apps.ingestion.services.preprocessing_service import preprocess_text


class PreprocessingTest(TestCase):
    """Test the text preprocessing pipeline — pure functions, no I/O."""

    def test_lowercase(self):
        result = preprocess_text("This Is UPPERCASE Text")
        self.assertEqual(result, "this is uppercase text")

    def test_url_removal(self):
        result = preprocess_text("Check this out https://example.com/page and this http://test.org")
        self.assertEqual(result, "check this out and this")

    def test_emoji_removal(self):
        result = preprocess_text("Great post! 🔥🚀 Really helpful 👍")
        self.assertEqual(result, "great post! really helpful")

    def test_whitespace_normalization(self):
        result = preprocess_text("Too    many     spaces   here")
        self.assertEqual(result, "too many spaces here")

    def test_newline_normalization(self):
        result = preprocess_text("Line one\n\n\nLine two\n\nLine three")
        self.assertEqual(result, "line one line two line three")

    def test_html_unescape(self):
        result = preprocess_text("This &amp; that &gt; everything &lt; nothing")
        self.assertEqual(result, "this & that > everything < nothing")

    def test_reddit_markdown_links(self):
        result = preprocess_text("Read [this article](https://example.com) for details")
        self.assertEqual(result, "read this article for details")

    def test_mention_removal(self):
        result = preprocess_text("Thanks u/someuser and @anotheruser for the help")
        self.assertEqual(result, "thanks and for the help")

    def test_empty_string(self):
        self.assertEqual(preprocess_text(""), "")

    def test_none_input(self):
        self.assertEqual(preprocess_text(None), "")

    def test_preserves_meaning(self):
        """Ensure cleaning doesn't destroy important content."""
        result = preprocess_text(
            "AI is transforming healthcare. Machine learning models can now "
            "detect cancer with 95% accuracy using medical imaging data."
        )
        self.assertIn("ai is transforming healthcare", result)
        self.assertIn("machine learning models", result)
        self.assertIn("95% accuracy", result)

    def test_combined_cleaning(self):
        """Test a realistic Reddit comment with multiple artifacts."""
        raw = (
            "This is **amazing**!! 🔥🔥 Check out https://example.com\n\n"
            "u/someone posted about it &amp; it's &gt; anything I've seen\n\n"
            "   Really    great    stuff   "
        )
        result = preprocess_text(raw)
        self.assertNotIn("https://", result)
        self.assertNotIn("🔥", result)
        self.assertNotIn("**", result)
        self.assertNotIn("u/someone", result)
        self.assertNotIn("&amp;", result)
        self.assertEqual(result, result.lower())
        # No double spaces
        self.assertNotIn("  ", result)


class IngestionAPITest(TestCase):
    """Test the ingestion trigger and status endpoints."""

    def setUp(self):
        self.client = APIClient()
        self.topic = Topic.objects.create(name="Test ingestion topic")

    def test_trigger_ingestion_returns_202(self):
        """POST /api/v1/topics/{id}/ingest/ should return 202 Accepted."""
        response = self.client.post(f"/api/v1/topics/{self.topic.id}/ingest/")
        self.assertEqual(response.status_code, http_status.HTTP_202_ACCEPTED)
        self.assertEqual(response.data["status"], "ingesting")

    def test_trigger_nonexistent_topic_returns_404(self):
        response = self.client.post("/api/v1/topics/99999/ingest/")
        self.assertEqual(response.status_code, http_status.HTTP_404_NOT_FOUND)

    def test_duplicate_ingestion_returns_409(self):
        """Trying to ingest a topic that's already ingesting should fail."""
        self.topic.status = Topic.Status.INGESTING
        self.topic.save()

        response = self.client.post(f"/api/v1/topics/{self.topic.id}/ingest/")
        self.assertEqual(response.status_code, http_status.HTTP_409_CONFLICT)

    def test_status_returns_counts(self):
        """GET /api/v1/topics/{id}/status/ should return discussion counts."""
        # Create some test discussions
        Discussion.objects.create(
            topic=self.topic, source="reddit", source_id="r1",
            content="Reddit test discussion", title="Test",
        )
        Discussion.objects.create(
            topic=self.topic, source="reddit", source_id="r2",
            content="Another reddit discussion", title="Test 2",
        )
        Discussion.objects.create(
            topic=self.topic, source="youtube", source_id="y1",
            content="YouTube test comment", title="Test Video",
        )

        response = self.client.get(f"/api/v1/topics/{self.topic.id}/status/")
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertEqual(response.data["discussion_count"], 3)
        self.assertEqual(response.data["sources"]["reddit"], 2)
        self.assertEqual(response.data["sources"]["youtube"], 1)

    def test_status_nonexistent_topic_returns_404(self):
        response = self.client.get("/api/v1/topics/99999/status/")
        self.assertEqual(response.status_code, http_status.HTTP_404_NOT_FOUND)

    def test_status_empty_topic(self):
        """New topic with no discussions should return zero counts."""
        response = self.client.get(f"/api/v1/topics/{self.topic.id}/status/")
        self.assertEqual(response.data["discussion_count"], 0)
        self.assertEqual(response.data["sources"]["reddit"], 0)
        self.assertEqual(response.data["sources"]["youtube"], 0)


class AdapterNormalizationTest(TestCase):
    """Test that adapters produce correctly shaped data."""

    def test_reddit_adapter_normalize_post(self):
        """Verify RedditAdapter._normalize_post returns correct schema."""
        from apps.ingestion.adapters.reddit import RedditAdapter

        adapter = RedditAdapter()
        post = {
            "id": "abc123",
            "title": "Test Post Title",
            "selftext": "This is the body of the post with enough content to pass the length check.",
            "author": "testuser",
            "subreddit": "technology",
            "score": 42,
            "num_comments": 10,
            "upvote_ratio": 0.95,
            "permalink": "/r/technology/comments/abc123/test/",
            "created_utc": 1700000000,
        }

        result = adapter._normalize_post(post)

        self.assertIsNotNone(result)
        self.assertEqual(result["source"], "reddit")
        self.assertEqual(result["source_id"], "post_abc123")
        self.assertEqual(result["title"], "Test Post Title")
        self.assertIn("Test Post Title", result["content"])
        self.assertIn("body of the post", result["content"])
        self.assertEqual(result["author"], "testuser")
        self.assertIn("reddit.com", result["url"])
        self.assertIsNotNone(result["published_at"])
        self.assertEqual(result["metadata"]["subreddit"], "technology")
        self.assertEqual(result["metadata"]["score"], 42)
        self.assertEqual(result["metadata"]["type"], "post")

    def test_reddit_adapter_skips_short_posts(self):
        """Posts with very short content should be skipped."""
        from apps.ingestion.adapters.reddit import RedditAdapter

        adapter = RedditAdapter()
        post = {"id": "short1", "title": "Hi", "selftext": ""}
        result = adapter._normalize_post(post)
        self.assertIsNone(result)

    def test_youtube_adapter_normalize_video(self):
        """Verify YouTubeAdapter._normalize_video returns correct schema."""
        from apps.ingestion.adapters.youtube import YouTubeAdapter

        adapter = YouTubeAdapter()
        video = {
            "id": {"videoId": "dQw4w9WgXcQ"},
            "snippet": {
                "title": "Test Video Title That Is Long Enough",
                "description": "A detailed description of the test video content for analysis.",
                "channelTitle": "TestChannel",
                "channelId": "UC123",
                "publishedAt": "2024-01-15T10:00:00Z",
            },
        }

        result = adapter._normalize_video(video)

        self.assertIsNotNone(result)
        self.assertEqual(result["source"], "youtube")
        self.assertEqual(result["source_id"], "video_dQw4w9WgXcQ")
        self.assertIn("Test Video Title", result["content"])
        self.assertEqual(result["author"], "TestChannel")
        self.assertIn("youtube.com", result["url"])
        self.assertEqual(result["metadata"]["type"], "video")
