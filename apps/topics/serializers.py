"""
DRF Serializers — convert model instances to/from JSON.

WHY THIS FILE EXISTS:
    Serializers are the bridge between Python objects and JSON. They handle
    validation on input and formatting on output. Using multiple serializers
    for the same model (list vs. detail vs. create) is a DRF best practice.

INTERVIEW Q: "Why not use one serializer for everything?"
    "Listing topics shows name and status; the detail view includes stats
    and analysis run info. Using one serializer either exposes too much
    data on list views (performance hit) or requires conditional field
    logic (code smell). Separate serializers keep each endpoint focused."

COMMON MISTAKE:
    Using ModelSerializer for create and returning its data directly.
    The create serializer validates input (name), but the response should
    use the detail serializer to include computed fields like discussion_count.
"""
from rest_framework import serializers
from apps.topics.models import Topic


class TopicCreateSerializer(serializers.ModelSerializer):
    """Validates input when creating a new topic."""

    class Meta:
        model = Topic
        fields = ["name"]

    def validate_name(self, value):
        """Strip whitespace and enforce minimum length."""
        cleaned = value.strip()
        if len(cleaned) < 2:
            raise serializers.ValidationError(
                "Topic name must be at least 2 characters."
            )
        return cleaned


class TopicListSerializer(serializers.ModelSerializer):
    """
    Summary view for listing topics.
    Includes discussion_count as an annotated field from the queryset.
    """
    discussion_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Topic
        fields = ["id", "name", "status", "discussion_count", "created_at"]


class TopicDetailSerializer(serializers.ModelSerializer):
    """Full detail view with computed statistics."""
    discussion_count = serializers.SerializerMethodField()

    class Meta:
        model = Topic
        fields = [
            "id", "name", "description", "status",
            "discussion_count", "created_at", "updated_at",
        ]

    def get_discussion_count(self, obj):
        return obj.discussions.count()
