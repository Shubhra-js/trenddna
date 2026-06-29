"""
Tests for the Topics API.

WHY THIS FILE EXISTS:
    Automated tests verify that the API contract doesn't break when you
    refactor code. These tests cover the happy path (create, list, retrieve)
    and validation edge cases (empty name, short name, nonexistent topic).

INTERVIEW Q: "How do you structure your tests?"
    "I use Django's TestCase which wraps each test in a transaction that
    rolls back after. DRF's APIClient simulates HTTP requests without
    starting a real server. I test the API contract (status codes, response
    shapes) rather than internal implementation details."

INTERVIEW Q: "Why not use pytest?"
    "Django's built-in test runner is sufficient for this project size.
    pytest adds fixture flexibility and parametrize, which I'd adopt in
    a larger project. For an MVP with ~20 tests, the built-in works fine."
"""
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status as http_status

from apps.topics.models import Topic


class HealthCheckTest(TestCase):
    """Verify the health endpoint returns 200 with service info."""

    def setUp(self):
        self.client = APIClient()

    def test_health_returns_200(self):
        response = self.client.get("/api/v1/health/")
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)

    def test_health_contains_service_name(self):
        response = self.client.get("/api/v1/health/")
        self.assertEqual(response.data["status"], "healthy")
        self.assertEqual(response.data["service"], "trenddna")
        self.assertIn("version", response.data)


class TopicCreateTest(TestCase):
    """Verify topic creation via POST /api/v1/topics/."""

    def setUp(self):
        self.client = APIClient()

    def test_create_valid_topic(self):
        response = self.client.post(
            "/api/v1/topics/",
            {"name": "artificial intelligence in education"},
            format="json",
        )
        self.assertEqual(response.status_code, http_status.HTTP_201_CREATED)
        self.assertEqual(response.data["name"], "artificial intelligence in education")
        self.assertEqual(response.data["status"], "pending")
        # Verify it was actually saved to the database
        self.assertTrue(Topic.objects.filter(name="artificial intelligence in education").exists())

    def test_create_strips_whitespace(self):
        response = self.client.post(
            "/api/v1/topics/",
            {"name": "  remote work  "},
            format="json",
        )
        self.assertEqual(response.status_code, http_status.HTTP_201_CREATED)
        self.assertEqual(response.data["name"], "remote work")

    def test_create_empty_name_fails(self):
        response = self.client.post(
            "/api/v1/topics/",
            {"name": ""},
            format="json",
        )
        self.assertEqual(response.status_code, http_status.HTTP_400_BAD_REQUEST)

    def test_create_short_name_fails(self):
        response = self.client.post(
            "/api/v1/topics/",
            {"name": "a"},
            format="json",
        )
        self.assertEqual(response.status_code, http_status.HTTP_400_BAD_REQUEST)

    def test_create_missing_name_fails(self):
        response = self.client.post(
            "/api/v1/topics/",
            {},
            format="json",
        )
        self.assertEqual(response.status_code, http_status.HTTP_400_BAD_REQUEST)


class TopicListTest(TestCase):
    """Verify topic listing via GET /api/v1/topics/."""

    def setUp(self):
        self.client = APIClient()

    def test_list_empty(self):
        response = self.client.get("/api/v1/topics/")
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 0)
        self.assertEqual(response.data["results"], [])

    def test_list_multiple_topics(self):
        Topic.objects.create(name="Topic 1")
        Topic.objects.create(name="Topic 2")
        Topic.objects.create(name="Topic 3")

        response = self.client.get("/api/v1/topics/")
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 3)
        self.assertEqual(len(response.data["results"]), 3)

    def test_list_contains_expected_fields(self):
        Topic.objects.create(name="Test Topic")

        response = self.client.get("/api/v1/topics/")
        topic = response.data["results"][0]
        self.assertIn("id", topic)
        self.assertIn("name", topic)
        self.assertIn("status", topic)
        self.assertIn("discussion_count", topic)
        self.assertIn("created_at", topic)


class TopicDetailTest(TestCase):
    """Verify topic detail via GET /api/v1/topics/{id}/."""

    def setUp(self):
        self.client = APIClient()

    def test_retrieve_existing_topic(self):
        topic = Topic.objects.create(name="Test Topic")

        response = self.client.get(f"/api/v1/topics/{topic.id}/")
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertEqual(response.data["name"], "Test Topic")
        self.assertEqual(response.data["status"], "pending")
        self.assertEqual(response.data["discussion_count"], 0)

    def test_retrieve_nonexistent_topic(self):
        response = self.client.get("/api/v1/topics/99999/")
        self.assertEqual(response.status_code, http_status.HTTP_404_NOT_FOUND)
