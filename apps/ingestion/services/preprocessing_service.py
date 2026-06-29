"""
Text preprocessing pipeline — cleans raw discussion text for NLP analysis.

WHY THIS FILE EXISTS:
    Raw text from Reddit and YouTube contains URLs, emojis, HTML entities,
    excessive whitespace, and formatting artifacts. The embedding model
    (all-MiniLM-L6-v2) works better on clean, normalized text. Each
    cleaning step is a pure function — easy to test and reorder.

INTERVIEW Q: "Why lowercase everything?"
    "The embedding model (all-MiniLM-L6-v2) is case-insensitive, so
    lowercasing doesn't lose semantic information. For sentiment analysis,
    VADER handles case internally. Lowercasing reduces vocabulary size
    and prevents 'AI' and 'ai' being treated as different tokens."

INTERVIEW Q: "Why remove URLs instead of replacing with a token?"
    "URLs don't carry sentiment or topical meaning — they're noise.
    Replacing with [URL] would add a meaningless token to every
    discussion that contains a link. Removal is cleaner."

INTERVIEW Q: "Why not use spaCy or NLTK for preprocessing?"
    "For the five cleaning operations we need (lowercase, URL removal,
    emoji removal, whitespace normalization, HTML unescape), regex is
    simpler and has zero dependencies. spaCy would add a 500MB model
    download for tokenization we don't need at this stage."
"""
import re
import html
import logging

logger = logging.getLogger("apps.ingestion")


# =============================================================================
# Compiled regex patterns (compiled once at module load for performance)
# =============================================================================

# Matches http/https URLs including query strings
_URL_PATTERN = re.compile(
    r"https?://[^\s<>\"')\]]+",
    re.IGNORECASE,
)

# Matches common emoji Unicode ranges
# Source: Unicode Emoji charts (ranges cover most emoji blocks)
_EMOJI_PATTERN = re.compile(
    "["
    "\U0001F600-\U0001F64F"  # Emoticons
    "\U0001F300-\U0001F5FF"  # Misc Symbols & Pictographs
    "\U0001F680-\U0001F6FF"  # Transport & Map
    "\U0001F1E0-\U0001F1FF"  # Flags
    "\U00002700-\U000027BF"  # Dingbats
    "\U0000FE00-\U0000FE0F"  # Variation Selectors
    "\U0001F900-\U0001F9FF"  # Supplemental Symbols
    "\U0001FA00-\U0001FA6F"  # Chess Symbols
    "\U0001FA70-\U0001FAFF"  # Symbols Extended-A
    "\U00002702-\U000027B0"  # Dingbats range
    "\U0000200D"             # Zero Width Joiner
    "\U0000200C"             # Zero Width Non-Joiner
    "]+",
    flags=re.UNICODE,
)

# Matches Reddit markdown formatting
_REDDIT_MARKDOWN = re.compile(
    r"(?:"
    r"\*\*|"          # Bold
    r"~~|"            # Strikethrough
    r"&gt;|"          # Quoted text (HTML entity)
    r"&amp;|"         # Ampersand (HTML entity)
    r"&lt;|"          # Less than (HTML entity)
    r"\[([^\]]*)\]\([^)]*\)"  # Markdown links [text](url) → keep text
    r")",
)

# Matches 2+ whitespace characters (spaces, tabs, newlines)
_WHITESPACE_PATTERN = re.compile(r"\s{2,}")

# Matches Reddit/YouTube user mentions
_MENTION_PATTERN = re.compile(r"(?:u/|@)\w+")


# =============================================================================
# Public API
# =============================================================================

def preprocess_text(text: str) -> str:
    """
    Clean raw discussion text through a multi-step pipeline.

    Pipeline order matters:
    1. HTML unescape first (converts &amp; → &, etc.)
    2. Remove URLs (before lowercasing to preserve URL detection)
    3. Remove markdown formatting
    4. Remove user mentions
    5. Remove emojis
    6. Lowercase
    7. Normalize whitespace (must be last)

    Args:
        text: Raw text from Reddit or YouTube.

    Returns:
        Cleaned, normalized text ready for embedding.
    """
    if not text:
        return ""

    # Step 1: Decode HTML entities (Reddit uses &gt;, &amp;, etc.)
    text = html.unescape(text)

    # Step 2: Remove URLs
    text = _URL_PATTERN.sub("", text)

    # Step 3: Clean Reddit markdown (preserve link text)
    text = _REDDIT_MARKDOWN.sub(lambda m: m.group(1) if m.group(1) else "", text)

    # Step 4: Remove user mentions
    text = _MENTION_PATTERN.sub("", text)

    # Step 5: Remove emojis
    text = _EMOJI_PATTERN.sub("", text)

    # Step 6: Lowercase
    text = text.lower()

    # Step 7: Normalize whitespace (collapse runs, strip edges)
    text = _WHITESPACE_PATTERN.sub(" ", text)
    text = text.strip()

    return text


def preprocess_batch(texts: list[str]) -> list[str]:
    """
    Preprocess a batch of texts.
    Convenience wrapper for processing multiple discussions at once.
    """
    return [preprocess_text(t) for t in texts]


# =============================================================================
# Quality Filters
# =============================================================================

# Minimum character count for a discussion to be considered meaningful.
# 20 chars ≈ 3-4 words. Anything shorter is likely noise.
MIN_CONTENT_LENGTH = 20

# If a single word makes up more than this fraction of all words,
# the text is likely spam (e.g., "buy buy buy buy buy buy").
MAX_WORD_REPETITION_RATIO = 0.6

# Jaccard similarity threshold for near-duplicate detection.
# 0.8 means 80% of words overlap — effectively the same discussion.
NEAR_DUPLICATE_THRESHOLD = 0.8


def is_quality_content(text: str) -> bool:
    """
    Check if preprocessed text meets quality standards.

    Rejects:
    1. Empty or too-short content (< 20 chars)
    2. Extremely repetitive text (one word > 60% of all words)

    INTERVIEW Q: "Why filter at ingestion, not at analysis?"
        "Garbage in, garbage out. If I feed 'lol lol lol' to the
        embedding model, it wastes compute and creates a junk vector
        that pollutes cluster centroids. Filtering early keeps the
        embedding and clustering stages clean."

    Args:
        text: Already-preprocessed text (lowercase, cleaned).

    Returns:
        True if the text is worth keeping.
    """
    if not text or len(text) < MIN_CONTENT_LENGTH:
        return False

    # Check for repetitive text (spam detection)
    words = text.split()
    if not words:
        return False

    # Count the most common word
    from collections import Counter
    word_counts = Counter(words)
    most_common_count = word_counts.most_common(1)[0][1]

    if most_common_count / len(words) > MAX_WORD_REPETITION_RATIO:
        return False

    return True


def is_near_duplicate(text: str, seen_texts: set) -> bool:
    """
    Check if text is a near-duplicate of any already-seen discussion.

    Uses Jaccard similarity on word sets — fast and effective for
    detecting copy-pasted or slightly modified duplicate content.

    INTERVIEW Q: "Why Jaccard instead of cosine similarity?"
        "At ingestion time, we don't have embeddings yet. Jaccard
        works on raw word sets — O(n) time with set operations.
        It catches exact and near-exact duplicates. Semantic
        deduplication (different words, same meaning) happens
        later during clustering."

    INTERVIEW Q: "Why not use a hash?"
        "Exact hashes miss near-duplicates — a post with one extra
        comma would have a completely different hash. Jaccard
        similarity of 0.8 catches texts that are 80% identical,
        which covers copy-paste with minor edits."

    Args:
        text: Already-preprocessed text to check.
        seen_texts: Set of previously seen text strings.

    Returns:
        True if text is a near-duplicate (should be skipped).
    """
    if not seen_texts:
        return False

    text_words = set(text.split())
    if not text_words:
        return False

    for seen in seen_texts:
        seen_words = set(seen.split())
        if not seen_words:
            continue

        # Jaccard similarity = |intersection| / |union|
        intersection = len(text_words & seen_words)
        union = len(text_words | seen_words)

        if union > 0 and (intersection / union) >= NEAR_DUPLICATE_THRESHOLD:
            return True

    return False
