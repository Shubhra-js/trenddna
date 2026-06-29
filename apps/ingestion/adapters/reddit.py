"""
Reddit data source adapter — fetches posts and comments via Reddit's OAuth API.

WHY OAUTH API (not public JSON):
    Reddit's public .json endpoints aggressively block server IPs and
    non-browser User-Agents with 403 errors. The OAuth API (oauth.reddit.com)
    is the officially supported method for application access. It requires
    a free Reddit app registration but provides reliable, higher-rate access.

    If no Reddit credentials are configured, the adapter falls back to
    the public JSON API as a best-effort attempt.

INTERVIEW Q: "How do you authenticate with Reddit?"
    "I register a free 'script' app at reddit.com/prefs/apps. It gives
    me a client_id and client_secret. I use those to get a short-lived
    OAuth bearer token via HTTP Basic Auth — no user login needed. The
    token lasts 1 hour and gives me 100 requests/minute."

INTERVIEW Q: "What are the rate limits?"
    "With OAuth: 100 requests/minute. Without: ~30/minute and frequent
    403 blocks. I add a 2-second delay between comment fetches. For
    a single topic ingestion (~6 requests), this is well within limits."
"""
import logging
import time
from datetime import datetime, timezone

import requests
from decouple import config

from apps.ingestion.adapters.base import BaseSourceAdapter

logger = logging.getLogger("apps.ingestion")


class RedditAdapter(BaseSourceAdapter):
    """
    Fetches posts and top comments from Reddit.

    Auth strategy (in order of preference):
    1. OAuth API with client credentials → most reliable
    2. Public JSON API fallback → may be blocked

    Strategy:
    1. Search for posts matching the topic query
    2. Collect post titles and bodies as discussions
    3. Fetch top comments from the most upvoted posts
    4. Normalize everything into the standard schema
    """

    OAUTH_URL = "https://oauth.reddit.com"
    PUBLIC_URL = "https://www.reddit.com"
    TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
    REQUEST_DELAY = 2.0  # Seconds between requests (respect rate limits)

    # Explicit ingestion limits — controls API usage and keeps analysis fast
    LIMITS = {
        "max_posts": 25,
        "comments_per_post": 5,
        "top_posts_for_comments": 5,
    }

    def __init__(self):
        self.client_id = config("REDDIT_CLIENT_ID", default="")
        self.client_secret = config("REDDIT_CLIENT_SECRET", default="")
        self.access_token = None

        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "TrendDNA/0.1 (by /u/trenddna_bot)",
        })

    def get_source_name(self) -> str:
        return "reddit"

    def _authenticate(self) -> bool:
        """
        Get an OAuth access token using client credentials grant.

        WHY client credentials (not user login):
            Script apps can authenticate with just client_id + secret.
            No user session needed. The token grants read-only access
            to public subreddits — exactly what we need.
        """
        if not self.client_id or not self.client_secret:
            logger.info("Reddit OAuth credentials not configured, using public API")
            return False

        try:
            response = requests.post(
                self.TOKEN_URL,
                auth=(self.client_id, self.client_secret),
                data={"grant_type": "client_credentials"},
                headers={"User-Agent": "TrendDNA/0.1 (by /u/trenddna_bot)"},
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()
            self.access_token = data.get("access_token")

            if self.access_token:
                self.session.headers["Authorization"] = f"Bearer {self.access_token}"
                logger.info("Reddit OAuth authenticated successfully")
                return True

        except Exception as e:
            logger.warning("Reddit OAuth failed: %s — falling back to public API", e)

        return False

    def _get_base_url(self) -> str:
        """Return the appropriate API base URL based on auth status."""
        return self.OAUTH_URL if self.access_token else self.PUBLIC_URL

    def fetch(self, query: str, limit: int = 50) -> list[dict]:
        """
        Fetch Reddit posts and comments matching the query.

        Flow:
        1. Attempt OAuth authentication
        2. Search for posts (capped by LIMITS["max_posts"])
        3. From top posts by score, fetch comments (capped by LIMITS)
        4. Return combined list of normalized discussions
        """
        discussions = []

        # Try to authenticate first
        self._authenticate()

        max_posts = self.LIMITS["max_posts"]
        comments_per_post = self.LIMITS["comments_per_post"]
        top_n = self.LIMITS["top_posts_for_comments"]

        try:
            # Step 1: Search for posts
            posts = self._search_posts(query, limit=max_posts)
            logger.info("Reddit: found %d posts for '%s'", len(posts), query)

            # Normalize posts into discussions
            for post in posts:
                normalized = self._normalize_post(post)
                if normalized and normalized["content"].strip():
                    discussions.append(normalized)

            # Step 2: Fetch comments from top posts (by score)
            top_posts = sorted(posts, key=lambda p: p.get("score", 0), reverse=True)

            for post in top_posts[:top_n]:
                time.sleep(self.REQUEST_DELAY)  # Rate limit
                comments = self._fetch_comments(post, limit=comments_per_post)
                for comment in comments:
                    normalized = self._normalize_comment(post, comment)
                    if normalized and normalized["content"].strip():
                        discussions.append(normalized)

        except Exception as e:
            logger.error("Reddit adapter error: %s", str(e))

        logger.info("Reddit: returning %d total discussions", len(discussions))
        return discussions[:limit]

    def _search_posts(self, query: str, limit: int = 25) -> list[dict]:
        """
        Search Reddit for posts matching the query.

        Uses OAuth endpoint if authenticated, public .json otherwise.
        """
        base = self._get_base_url()

        if self.access_token:
            url = f"{base}/search"
        else:
            url = f"{base}/search.json"

        params = {
            "q": query,
            "sort": "relevance",
            "limit": limit,
            "t": "year",
            "type": "link",
        }

        try:
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            children = data.get("data", {}).get("children", [])
            return [child["data"] for child in children if child.get("data")]

        except requests.exceptions.HTTPError as e:
            status_code = e.response.status_code if e.response is not None else 0
            if status_code == 429:
                logger.warning("Reddit rate limited, waiting 5s and retrying")
                time.sleep(5)
                return self._search_posts(query, limit)  # One retry
            elif status_code == 403:
                logger.warning(
                    "Reddit returned 403 (Blocked). "
                    "Set REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET in .env "
                    "for reliable access. See: https://www.reddit.com/prefs/apps"
                )
            else:
                logger.error("Reddit search HTTP error: %s", str(e))
            return []
        except Exception as e:
            logger.error("Reddit search error: %s", str(e))
            return []

    def _fetch_comments(self, post: dict, limit: int = 10) -> list[dict]:
        """
        Fetch top comments from a specific post.

        Reddit comment endpoint returns [post_listing, comments_listing].
        We want the second element's children.
        """
        permalink = post.get("permalink", "")
        if not permalink:
            return []

        base = self._get_base_url()

        if self.access_token:
            url = f"{base}{permalink}"
        else:
            url = f"{base}{permalink}.json"

        params = {"limit": limit, "sort": "top", "depth": 1}

        try:
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            if not isinstance(data, list) or len(data) < 2:
                return []

            # Second element is the comments listing
            children = data[1].get("data", {}).get("children", [])
            comments = []
            for child in children:
                if child.get("kind") == "t1":  # t1 = comment
                    comment_data = child.get("data", {})
                    # Skip deleted/removed comments and automoderator
                    author = comment_data.get("author", "")
                    if author in ("[deleted]", "[removed]", "AutoModerator"):
                        continue
                    body = comment_data.get("body", "")
                    if body and body not in ("[deleted]", "[removed]"):
                        comments.append(comment_data)

            return comments

        except Exception as e:
            logger.error("Reddit comments error for %s: %s", permalink, str(e))
            return []

    def _normalize_post(self, post: dict) -> dict | None:
        """Convert a Reddit post into the standard discussion schema."""
        post_id = post.get("id", "")
        if not post_id:
            return None

        # Combine title and body for richer text content
        title = post.get("title", "")
        selftext = post.get("selftext", "")
        content = f"{title}. {selftext}" if selftext else title

        # Skip posts with no real text content (link-only posts)
        if not content or len(content.strip()) < 10:
            return None

        # Convert Unix timestamp to ISO datetime
        created_utc = post.get("created_utc", 0)
        published_at = (
            datetime.fromtimestamp(created_utc, tz=timezone.utc).isoformat()
            if created_utc
            else None
        )

        return {
            "source": "reddit",
            "source_id": f"post_{post_id}",
            "title": title,
            "content": content,
            "author": post.get("author", ""),
            "url": f"https://reddit.com{post.get('permalink', '')}",
            "published_at": published_at,
            "metadata": {
                "subreddit": post.get("subreddit", ""),
                "score": post.get("score", 0),
                "num_comments": post.get("num_comments", 0),
                "upvote_ratio": post.get("upvote_ratio", 0),
                "type": "post",
            },
        }

    def _normalize_comment(self, post: dict, comment: dict) -> dict | None:
        """Convert a Reddit comment into the standard discussion schema."""
        comment_id = comment.get("id", "")
        if not comment_id:
            return None

        body = comment.get("body", "")
        if not body or len(body.strip()) < 5:
            return None

        created_utc = comment.get("created_utc", 0)
        published_at = (
            datetime.fromtimestamp(created_utc, tz=timezone.utc).isoformat()
            if created_utc
            else None
        )

        return {
            "source": "reddit",
            "source_id": f"comment_{comment_id}",
            "title": post.get("title", ""),
            "content": body,
            "author": comment.get("author", ""),
            "url": f"https://reddit.com{comment.get('permalink', '')}",
            "published_at": published_at,
            "metadata": {
                "subreddit": post.get("subreddit", ""),
                "score": comment.get("score", 0),
                "parent_post_id": post.get("id", ""),
                "type": "comment",
            },
        }
