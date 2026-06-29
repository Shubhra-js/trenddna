"""
YouTube data source adapter — fetches video metadata and comments via Data API v3.

WHY YouTube Data API (not scraping):
    Scraping YouTube violates ToS and breaks frequently. The Data API v3
    is free (10,000 units/day) and returns structured JSON. A search
    costs 100 units, commentThreads costs 1 unit. So we can do ~100
    searches or ~10,000 comment fetches per day — plenty for an MVP.

INTERVIEW Q: "What happens if the API key isn't configured?"
    "The adapter checks is_available() before fetching. If YOUTUBE_API_KEY
    is empty, the ingestion service skips YouTube entirely and logs a
    warning. Reddit still runs. This is graceful degradation — the system
    works with whatever sources are available."

INTERVIEW Q: "How do you manage API quota?"
    "I limit searches to 5 videos and 20 comments per video. That's
    5 × 100 + 5 × 1 = 505 units per topic. At 10,000 units/day, I can
    analyze ~19 topics per day on the free tier. For production, I'd
    apply for a quota increase or implement caching."
"""
import logging
from datetime import datetime

import requests
from decouple import config

from apps.ingestion.adapters.base import BaseSourceAdapter

logger = logging.getLogger("apps.ingestion")


class YouTubeAdapter(BaseSourceAdapter):
    """
    Fetches video metadata and comments from YouTube Data API v3.

    Strategy:
    1. Search for videos matching the topic query
    2. For each video, fetch comment threads
    3. Normalize video metadata and comments into standard schema
    """

    API_BASE = "https://www.googleapis.com/youtube/v3"

    # Explicit ingestion limits — controls API quota usage
    # 10 searches × 100 units + 10 × 10 × 1 unit = 1,100 units per topic
    # Free tier: 10,000 units/day → ~9 topics/day
    LIMITS = {
        "max_videos": 10,
        "comments_per_video": 10,
    }

    def __init__(self):
        self.api_key = config("YOUTUBE_API_KEY", default="")
        self.session = requests.Session()

    def get_source_name(self) -> str:
        return "youtube"

    def is_available(self) -> bool:
        """YouTube requires an API key to function."""
        return bool(self.api_key)

    def fetch(self, query: str, limit: int = 50) -> list[dict]:
        """
        Fetch YouTube video metadata and comments.

        Flow:
        1. Search for videos (capped by LIMITS["max_videos"])
        2. For each video, fetch comments (capped by LIMITS["comments_per_video"])
        3. Return normalized discussions
        """
        if not self.is_available():
            logger.warning(
                "YouTube API key not configured — skipping YouTube ingestion. "
                "Set YOUTUBE_API_KEY in .env to enable."
            )
            return []

        max_videos = self.LIMITS["max_videos"]
        comments_per_video = self.LIMITS["comments_per_video"]
        discussions = []

        try:
            # Step 1: Search for videos
            videos = self._search_videos(query, max_results=max_videos)
            logger.info("YouTube: found %d videos for '%s'", len(videos), query)

            for video in videos:
                video_id = video.get("id", {}).get("videoId", "")
                if not video_id:
                    continue

                # Add video metadata as a discussion
                video_disc = self._normalize_video(video)
                if video_disc:
                    discussions.append(video_disc)

                # Step 2: Fetch comments for this video
                comments = self._fetch_comments(video_id, limit=comments_per_video)

                for comment in comments:
                    normalized = self._normalize_comment(video, comment)
                    if normalized and normalized["content"].strip():
                        discussions.append(normalized)

        except Exception as e:
            logger.error("YouTube adapter error: %s", str(e))

        logger.info("YouTube: returning %d total discussions", len(discussions))
        return discussions

    def _search_videos(self, query: str, max_results: int = 5) -> list[dict]:
        """
        Search YouTube for videos matching the query.

        WHY type=video and order=relevance:
            type=video excludes playlists and channels.
            order=relevance gives us the most topically related results.
            videoCategoryId is not set to avoid limiting to specific categories.
        """
        url = f"{self.API_BASE}/search"
        params = {
            "q": query,
            "type": "video",
            "part": "snippet",
            "order": "relevance",
            "maxResults": max_results,
            "key": self.api_key,
        }

        try:
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            return data.get("items", [])

        except requests.exceptions.HTTPError as e:
            if e.response is not None:
                error_body = e.response.text[:200]
                logger.error("YouTube search HTTP %d: %s", e.response.status_code, error_body)
            else:
                logger.error("YouTube search error: %s", str(e))
            return []
        except Exception as e:
            logger.error("YouTube search error: %s", str(e))
            return []

    def _fetch_comments(self, video_id: str, limit: int = 20) -> list[dict]:
        """
        Fetch top-level comment threads for a video.

        WHY commentThreads (not comments):
            commentThreads returns top-level comments with reply counts.
            The comments endpoint requires a parent comment ID. For our
            analysis, top-level comments provide the broadest sentiment signal.
        """
        url = f"{self.API_BASE}/commentThreads"
        params = {
            "videoId": video_id,
            "part": "snippet",
            "order": "relevance",
            "maxResults": limit,
            "textFormat": "plainText",
            "key": self.api_key,
        }

        try:
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            return data.get("items", [])

        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == 403:
                # Comments might be disabled on this video
                logger.warning("Comments disabled for video %s", video_id)
            else:
                logger.error("YouTube comments error for %s: %s", video_id, str(e))
            return []
        except Exception as e:
            logger.error("YouTube comments error for %s: %s", video_id, str(e))
            return []

    def _normalize_video(self, video: dict) -> dict | None:
        """Convert YouTube video search result into standard schema."""
        video_id = video.get("id", {}).get("videoId", "")
        snippet = video.get("snippet", {})
        if not video_id or not snippet:
            return None

        title = snippet.get("title", "")
        description = snippet.get("description", "")
        content = f"{title}. {description}" if description else title

        if not content or len(content.strip()) < 10:
            return None

        published_at = snippet.get("publishedAt", "")

        return {
            "source": "youtube",
            "source_id": f"video_{video_id}",
            "title": title,
            "content": content,
            "author": snippet.get("channelTitle", ""),
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "published_at": published_at,
            "metadata": {
                "channel_id": snippet.get("channelId", ""),
                "channel_title": snippet.get("channelTitle", ""),
                "type": "video",
            },
        }

    def _normalize_comment(self, video: dict, comment_thread: dict) -> dict | None:
        """Convert YouTube comment thread into standard schema."""
        snippet = comment_thread.get("snippet", {})
        top_comment = snippet.get("topLevelComment", {}).get("snippet", {})

        if not top_comment:
            return None

        comment_id = comment_thread.get("id", "")
        text = top_comment.get("textDisplay", "")

        if not text or len(text.strip()) < 5:
            return None

        video_id = video.get("id", {}).get("videoId", "")
        video_title = video.get("snippet", {}).get("title", "")
        published_at = top_comment.get("publishedAt", "")

        return {
            "source": "youtube",
            "source_id": f"comment_{comment_id}",
            "title": video_title,
            "content": text,
            "author": top_comment.get("authorDisplayName", ""),
            "url": f"https://www.youtube.com/watch?v={video_id}&lc={comment_id}",
            "published_at": published_at,
            "metadata": {
                "video_id": video_id,
                "like_count": top_comment.get("likeCount", 0),
                "reply_count": snippet.get("totalReplyCount", 0),
                "type": "comment",
            },
        }
