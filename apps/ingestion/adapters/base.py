"""
Abstract base class for data source adapters.

WHY THIS FILE EXISTS:
    The Adapter Pattern decouples "how we fetch data" from "what we do
    with it." Each platform (Reddit, YouTube) has a different API, but
    the ingestion service doesn't care — it calls adapter.fetch() and
    gets back a uniform list of dicts.

INTERVIEW Q: "Why use an abstract base class?"
    "It enforces a contract. Any new adapter MUST implement fetch() and
    get_source_name(). If a developer forgets, Python raises TypeError
    at instantiation — not at runtime when data is missing. It also
    makes the code self-documenting: reading BaseSourceAdapter tells
    you exactly what every adapter must provide."

INTERVIEW Q: "How would you add Twitter/X later?"
    "Create apps/ingestion/adapters/twitter.py, subclass BaseSourceAdapter,
    implement fetch() and get_source_name(), and register it in the
    ingestion service's adapter list. Zero changes to existing code.
    That's the Open/Closed Principle — open for extension, closed for
    modification."
"""
from abc import ABC, abstractmethod
from typing import Optional


class BaseSourceAdapter(ABC):
    """
    Contract that every data source adapter must follow.

    Each adapter:
    1. Accepts a search query (the topic name)
    2. Fetches raw data from its platform's API
    3. Returns a list of normalized dicts ready for preprocessing

    The normalized dict schema:
    {
        "source": str,           # "reddit" or "youtube"
        "source_id": str,        # Platform-specific unique ID
        "title": str,            # Post/video title (may be empty)
        "content": str,          # Main text content
        "author": str,           # Author username
        "url": str,              # Direct link to the content
        "published_at": str,     # ISO 8601 datetime string
        "metadata": dict,        # Platform-specific extras
    }
    """

    @abstractmethod
    def fetch(self, query: str, limit: int = 50) -> list[dict]:
        """
        Fetch discussions matching the query.

        Args:
            query: The topic name to search for.
            limit: Maximum number of discussions to return.

        Returns:
            List of normalized discussion dicts.
        """
        pass

    @abstractmethod
    def get_source_name(self) -> str:
        """Return the source identifier, e.g. 'reddit' or 'youtube'."""
        pass

    def is_available(self) -> bool:
        """
        Check if this adapter can run (API keys configured, etc.).
        Override in subclasses that require configuration.
        """
        return True
