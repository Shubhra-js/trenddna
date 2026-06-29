# TrendDNA — REST API Design

## Base URL

```
Development:  http://localhost:8000/api/v1/
Production:   https://trenddna.onrender.com/api/v1/
```

**Why `/api/v1/`?** API versioning from day one. If we change response shapes later,
we create `/api/v2/` without breaking existing consumers. This is a standard REST
practice that interviewers expect.

---

## Endpoints Overview

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `POST` | `/api/v1/topics/` | Create a topic and trigger analysis |
| `GET` | `/api/v1/topics/` | List all analyzed topics |
| `GET` | `/api/v1/topics/{id}/` | Get topic detail with summary stats |
| `GET` | `/api/v1/topics/{id}/discussions/` | Paginated discussions for a topic |
| `GET` | `/api/v1/topics/{id}/clusters/` | Cluster data with top discussions |
| `GET` | `/api/v1/topics/{id}/sentiment/` | Sentiment timeline data |
| `GET` | `/api/v1/topics/{id}/trends/` | Trend spikes and triggers |
| `GET` | `/api/v1/topics/{id}/insights/` | AI-generated insights |
| `POST` | `/api/v1/topics/{id}/reanalyze/` | Re-trigger analysis pipeline |
| `GET` | `/api/v1/topics/{id}/status/` | Analysis pipeline status |

---

## Detailed Endpoint Specifications

### 1. Create Topic

```
POST /api/v1/topics/
```

Creates a new topic and triggers the full analysis pipeline.

**Request Body:**
```json
{
  "name": "artificial intelligence in education",
  "sources": ["reddit", "youtube"]
}
```

**Response (201 Created):**
```json
{
  "id": 1,
  "name": "artificial intelligence in education",
  "status": "ingesting",
  "created_at": "2026-06-14T12:00:00Z",
  "analysis_run_id": 1,
  "message": "Analysis pipeline started. Poll /api/v1/topics/1/status/ for progress."
}
```

**Error (400 Bad Request):**
```json
{
  "error": "validation_error",
  "details": {
    "name": ["This field is required."],
    "sources": ["At least one source must be specified."]
  }
}
```

**Interview Q**: "Why does creating a topic also start analysis?"
**Answer**: "In the user flow, creating a topic and analyzing it are the same action.
Separating them would require the user to make two API calls for one intent. The
pipeline runs synchronously for MVP — if it took longer, I'd return a 202 Accepted
and have the client poll the status endpoint."

---

### 2. List Topics

```
GET /api/v1/topics/
```

Returns all topics with summary statistics.

**Query Parameters:**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `page` | int | 1 | Page number |
| `page_size` | int | 10 | Results per page |
| `status` | string | — | Filter by status |
| `ordering` | string | `-created_at` | Sort field |

**Response (200 OK):**
```json
{
  "count": 25,
  "next": "/api/v1/topics/?page=2",
  "previous": null,
  "results": [
    {
      "id": 1,
      "name": "artificial intelligence in education",
      "status": "completed",
      "discussion_count": 347,
      "cluster_count": 5,
      "avg_sentiment": 0.23,
      "created_at": "2026-06-14T12:00:00Z"
    }
  ]
}
```

**Why pagination?**: Without it, listing 100 topics with stats would return a massive
JSON payload. Cursor-based pagination is better for real-time feeds, but offset
pagination is simpler and sufficient for a dashboard.

---

### 3. Topic Detail

```
GET /api/v1/topics/{id}/
```

Returns full topic information with analysis summary.

**Response (200 OK):**
```json
{
  "id": 1,
  "name": "artificial intelligence in education",
  "description": "Analysis of 347 discussions from Reddit and YouTube about AI's role in education.",
  "status": "completed",
  "created_at": "2026-06-14T12:00:00Z",
  "updated_at": "2026-06-14T12:05:30Z",
  "stats": {
    "total_discussions": 347,
    "reddit_count": 215,
    "youtube_count": 132,
    "cluster_count": 5,
    "avg_sentiment": 0.23,
    "sentiment_distribution": {
      "positive": 142,
      "neutral": 128,
      "negative": 77
    },
    "date_range": {
      "earliest": "2026-01-15T08:00:00Z",
      "latest": "2026-06-14T10:30:00Z"
    }
  },
  "latest_analysis_run": {
    "id": 1,
    "status": "completed",
    "started_at": "2026-06-14T12:00:00Z",
    "completed_at": "2026-06-14T12:05:30Z",
    "parameters": {
      "algorithm": "kmeans",
      "optimal_k": 5
    }
  }
}
```

---

### 4. Discussions

```
GET /api/v1/topics/{id}/discussions/
```

Paginated list of discussions with sentiment scores.

**Query Parameters:**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `page` | int | 1 | Page number |
| `page_size` | int | 20 | Results per page |
| `source` | string | — | Filter: `reddit` or `youtube` |
| `sentiment` | string | — | Filter: `positive`, `negative`, `neutral` |
| `cluster_id` | int | — | Filter by cluster |
| `ordering` | string | `-published_at` | Sort field |

**Response (200 OK):**
```json
{
  "count": 347,
  "next": "/api/v1/topics/1/discussions/?page=2",
  "results": [
    {
      "id": 42,
      "source": "reddit",
      "title": "How AI tutors are changing my classroom",
      "content": "I've been using ChatGPT as a teaching assistant...",
      "author": "teacher_2026",
      "url": "https://reddit.com/r/education/...",
      "published_at": "2026-06-10T14:30:00Z",
      "sentiment": {
        "compound_score": 0.78,
        "label": "positive"
      },
      "cluster_id": 2,
      "metadata": {
        "subreddit": "education",
        "upvotes": 342,
        "num_comments": 89
      }
    }
  ]
}
```

---

### 5. Clusters

```
GET /api/v1/topics/{id}/clusters/
```

Returns cluster data for visualization.

**Response (200 OK):**
```json
{
  "algorithm": "kmeans",
  "optimal_k": 5,
  "clusters": [
    {
      "id": 1,
      "label": "AI tutoring personalized learning",
      "keywords": ["tutoring", "personalized", "adaptive", "student", "learning"],
      "summary": "Discussions about AI-powered tutoring systems and how they personalize learning paths for individual students.",
      "member_count": 89,
      "coherence_score": 0.72,
      "avg_sentiment": 0.45,
      "top_discussions": [
        {
          "id": 42,
          "title": "How AI tutors are changing my classroom",
          "distance": 0.12,
          "sentiment_label": "positive"
        }
      ],
      "sentiment_breakdown": {
        "positive": 52,
        "neutral": 24,
        "negative": 13
      }
    }
  ]
}
```

---

### 6. Sentiment Timeline

```
GET /api/v1/topics/{id}/sentiment/
```

Time-series sentiment data for Chart.js line charts.

**Query Parameters:**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `granularity` | string | `day` | `hour`, `day`, `week`, `month` |
| `source` | string | — | Filter by source |

**Response (200 OK):**
```json
{
  "granularity": "day",
  "timeline": [
    {
      "date": "2026-06-01",
      "avg_sentiment": 0.34,
      "positive_count": 12,
      "negative_count": 3,
      "neutral_count": 8,
      "discussion_count": 23,
      "sources": {
        "reddit": 15,
        "youtube": 8
      }
    },
    {
      "date": "2026-06-02",
      "avg_sentiment": -0.12,
      "positive_count": 5,
      "negative_count": 14,
      "neutral_count": 6,
      "discussion_count": 25,
      "sources": {
        "reddit": 18,
        "youtube": 7
      }
    }
  ],
  "overall": {
    "avg_sentiment": 0.23,
    "trend": "slightly_positive",
    "volatility": 0.45
  }
}
```

**Why return `discussion_count` per day?**: So the frontend can show volume alongside
sentiment. A sentiment spike with only 2 discussions is noise; a spike with 50
discussions is signal. This distinction is critical for the explainability panel.

---

### 7. Trend Triggers

```
GET /api/v1/topics/{id}/trends/
```

Detected spikes, keyword acceleration, and their likely causes.

**Response (200 OK):**
```json
{
  "spikes": [
    {
      "date": "2026-06-05",
      "metric": "volume",
      "magnitude": 3.2,
      "description": "Discussion volume increased 320% compared to baseline",
      "likely_triggers": [
        "Viral Reddit post in r/technology (2.4k upvotes)",
        "YouTube video by TechChannel (500k views)"
      ],
      "accelerating_keywords": ["ban", "cheating", "plagiarism"],
      "confidence": 0.85
    }
  ],
  "keyword_trends": [
    {
      "keyword": "plagiarism",
      "frequency_change": "+240%",
      "period": "2026-06-03 to 2026-06-07",
      "associated_sentiment": -0.45
    }
  ]
}
```

---

### 8. Insights

```
GET /api/v1/topics/{id}/insights/
```

AI-generated explanations with the explainability panel data.

**Response (200 OK):**
```json
{
  "insights": [
    {
      "id": 1,
      "type": "sentiment_shift",
      "content": "Sentiment around 'AI in education' shifted from positive (+0.34) to negative (-0.12) between June 1-3, coinciding with a viral post about AI-detected plagiarism.",
      "confidence": 0.82,
      "explainability": {
        "source": "Derived from VADER sentiment scores across 48 discussions",
        "method": "Rolling 3-day average with Z-score spike detection (threshold: 2.0)",
        "interpretation": "The shift correlates with 3 high-engagement Reddit posts about academic integrity concerns. Keyword 'plagiarism' appeared in 67% of negative discussions during this period."
      }
    },
    {
      "id": 2,
      "type": "cluster_summary",
      "content": "The largest discussion cluster (89 posts) focuses on 'personalized AI tutoring', with overwhelmingly positive sentiment (+0.45).",
      "confidence": 0.91,
      "explainability": {
        "source": "KMeans clustering of 347 discussion embeddings (K=5, silhouette=0.62)",
        "method": "Cluster labeled via TF-IDF top-5 keywords. Sentiment aggregated from member VADER scores.",
        "interpretation": "This cluster is dominated by educators sharing positive experiences. 58 of 89 discussions originate from r/education and r/teachers."
      }
    }
  ]
}
```

**Interview Q**: "Why include the explainability object?"
**Answer**: "Black-box analytics erode trust. If I tell a user 'sentiment shifted
negative', they'll ask 'says who?' The explainability panel answers three questions:
What data was used? What method produced this? What does it mean? This is inspired
by XAI (Explainable AI) principles."

---

### 9. Re-analyze

```
POST /api/v1/topics/{id}/reanalyze/
```

Triggers a new analysis run with optional parameter overrides.

**Request Body (optional):**
```json
{
  "algorithm": "dbscan",
  "refresh_data": true
}
```

**Response (202 Accepted):**
```json
{
  "analysis_run_id": 2,
  "status": "running",
  "message": "Re-analysis started. Poll /api/v1/topics/1/status/ for progress."
}
```

---

### 10. Analysis Status

```
GET /api/v1/topics/{id}/status/
```

Pipeline progress for the frontend polling mechanism.

**Response (200 OK):**
```json
{
  "topic_id": 1,
  "status": "analyzing",
  "current_step": "clustering",
  "steps": {
    "ingestion": {"status": "completed", "details": "347 discussions collected"},
    "preprocessing": {"status": "completed", "details": "Cleaned and normalized"},
    "embedding": {"status": "completed", "details": "347 embeddings generated"},
    "clustering": {"status": "running", "details": "Testing K=3 to K=10..."},
    "sentiment": {"status": "pending"},
    "trends": {"status": "pending"},
    "insights": {"status": "pending"}
  },
  "started_at": "2026-06-14T12:00:00Z",
  "elapsed_seconds": 45
}
```

---

## Error Handling

All errors follow a consistent format:

```json
{
  "error": "error_code",
  "message": "Human-readable description",
  "details": {}
}
```

| HTTP Code | Error Code | When |
|-----------|------------|------|
| 400 | `validation_error` | Invalid request body |
| 404 | `not_found` | Topic/resource doesn't exist |
| 409 | `analysis_in_progress` | Trying to re-analyze while one is running |
| 429 | `rate_limited` | Too many requests |
| 500 | `internal_error` | Unhandled server error |
| 503 | `source_unavailable` | Reddit/YouTube API unreachable |

**Interview Q**: "Why consistent error codes?"
**Answer**: "The frontend needs to distinguish between 'show a validation error on
the form' (400) and 'show a retry button' (503). Consistent error shapes let the
API client have a single error handler that routes to the right UI state."

---

## Design Decisions

### Why REST and not GraphQL?

- REST is simpler, more widely understood, and sufficient for our use case
- Our data access patterns are predictable (dashboard views map to endpoints)
- GraphQL shines when clients need flexible queries — our frontend has fixed views
- **Interview point**: "I'd consider GraphQL if the frontend needed to query arbitrary
  combinations of clusters, sentiments, and discussions in one request. Our dashboard
  has fixed views, so REST's simplicity wins."

### Why not WebSockets for live updates?

- Analysis runs take 15-60 seconds, not minutes
- Polling every 2 seconds for status is simple and sufficient
- WebSockets add connection management complexity
- **Interview point**: "I'd add WebSockets if analysis took minutes or if multiple
  users needed real-time collaboration. For a single-user MVP, polling is fine."

### Why nested resources (`/topics/{id}/clusters/`)?

- Clusters don't exist without a topic — they're not independent resources
- Nested URLs make the hierarchy clear
- **Interview point**: "I followed the rule: if a resource can't exist independently,
  nest it under its parent. Clusters are meaningless without a topic context."
