# TrendDNA — System Architecture

## 1. System Overview

TrendDNA is a full-stack discussion analysis platform that ingests public internet
discussions (Reddit, YouTube), processes them through an NLP pipeline (embeddings,
clustering, sentiment analysis), and presents interactive analytics on a dashboard.

### What problem does it solve?

When a topic trends online, discussions fragment across platforms and evolve rapidly.
TrendDNA consolidates these fragments, clusters them by theme, tracks sentiment shifts
over time, and explains *why* certain patterns emerge — turning noise into signal.

### Interview Explanation (3 sentences)

> "TrendDNA ingests discussions from Reddit and YouTube about any topic, runs them
> through an NLP pipeline — embeddings for semantic similarity, KMeans for grouping,
> VADER for sentiment — and surfaces trend spikes with explainability. The backend is
> Django with DRF serving a REST API, the frontend is a vanilla JS dashboard with
> Chart.js, and PostgreSQL stores everything. The architecture uses a service layer
> pattern and adapter pattern for data sources, so the system is testable, extensible,
> and cleanly separated."

---

## 2. High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                     FRONTEND (Django Templates)                     │
│              HTML + CSS + JavaScript + Chart.js                     │
│                                                                     │
│   ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐  │
│   │  Topic     │  │  Cluster   │  │ Sentiment  │  │ Explain-   │  │
│   │  Search    │  │  Explorer  │  │ Timeline   │  │ ability    │  │
│   └────────────┘  └────────────┘  └────────────┘  └────────────┘  │
└──────────────────────────┬──────────────────────────────────────────┘
                           │ REST API (JSON)
                           │
┌──────────────────────────┴──────────────────────────────────────────┐
│                    DJANGO + DRF BACKEND                             │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │                   API Layer (DRF ViewSets)                    │  │
│  │   TopicViewSet  │  AnalysisViewSet  │  InsightViewSet         │  │
│  └────────────────────────┬──────────────────────────────────────┘  │
│                           │                                         │
│  ┌────────────────────────┴──────────────────────────────────────┐  │
│  │                  Pipeline Orchestrator                         │  │
│  │       Ingest  →  Preprocess  →  Embed  →  Cluster  →         │  │
│  │       Sentiment  →  Trends  →  Insights                       │  │
│  └────────────────────────┬──────────────────────────────────────┘  │
│                           │                                         │
│  ┌───────────┐  ┌─────────┴───┐  ┌────────────┐  ┌─────────────┐  │
│  │ Ingestion │  │  Analysis   │  │  Pipeline   │  │  Topics     │  │
│  │ App       │  │  App        │  │  App        │  │  App        │  │
│  │           │  │             │  │             │  │             │  │
│  │ Adapters: │  │ Embeddings  │  │ Orchestrate │  │ CRUD        │  │
│  │  Reddit   │  │ Clustering  │  │ Chain steps │  │ Models      │  │
│  │  YouTube  │  │ Sentiment   │  │ Status      │  │ API         │  │
│  │  (Future) │  │ Trends      │  │ Error mgmt  │  │             │  │
│  │           │  │ Insights    │  │             │  │             │  │
│  └───────────┘  └─────────────┘  └─────────────┘  └─────────────┘  │
│                                                                     │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
                  ┌────────┴────────┐
                  │   PostgreSQL    │
                  │                 │
                  │  topics         │
                  │  discussions    │
                  │  analysis_runs  │
                  │  clusters       │
                  │  memberships    │
                  │  sentiments     │
                  │  insights       │
                  └─────────────────┘
```

---

## 3. Data Flow Pipeline

```
  User enters topic
        │
        ▼
  ┌─────────────┐
  │ Create Topic│  → Save to DB, create AnalysisRun
  └──────┬──────┘
         │
         ▼
  ┌─────────────┐     ┌─────────────┐
  │   Reddit    │     │   YouTube   │
  │   Adapter   │     │   Adapter   │  → Adapter pattern
  └──────┬──────┘     └──────┬──────┘
         │                   │
         └────────┬──────────┘
                  │
                  ▼
  ┌──────────────────────┐
  │   Text Preprocessor  │  → Clean HTML, normalize, deduplicate
  └──────────┬───────────┘
             │
             ▼
  ┌──────────────────────┐
  │   Save Discussions   │  → Persist cleaned text to DB
  └──────────┬───────────┘
             │
             ▼
  ┌──────────────────────┐
  │  Generate Embeddings │  → all-MiniLM-L6-v2 (in-memory, not persisted)
  └──────────┬───────────┘
             │
             ▼
  ┌──────────────────────┐
  │  Cluster (KMeans)    │  → Group by semantic similarity
  └──────────┬───────────┘     Silhouette score picks optimal K
             │
             ▼
  ┌──────────────────────┐
  │  Sentiment Analysis  │  → VADER per discussion, aggregate per cluster
  └──────────┬───────────┘
             │
             ▼
  ┌──────────────────────┐
  │  Trend Detection     │  → Spike detection, keyword acceleration
  └──────────┬───────────┘
             │
             ▼
  ┌──────────────────────┐
  │  Insight Generation  │  → Summarize clusters, explain patterns
  └──────────┬───────────┘
             │
             ▼
  ┌──────────────────────┐
  │  Update AnalysisRun  │  → Mark complete, return results
  └──────────────────────┘
```

---

## 4. Design Patterns & Interview Points

### 4.1 Adapter Pattern (Ingestion)

```
                ┌───────────────────────┐
                │  BaseSourceAdapter    │  ← Abstract base class
                │  + fetch(topic)       │
                │  + normalize(data)    │
                └───────────┬───────────┘
                            │
              ┌─────────────┼─────────────┐
              │             │             │
    ┌─────────┴──┐  ┌──────┴─────┐  ┌────┴───────┐
    │  Reddit    │  │  YouTube   │  │  Future    │
    │  Adapter   │  │  Adapter   │  │  Adapter   │
    └────────────┘  └────────────┘  └────────────┘
```

**Why**: Each platform has different APIs and data shapes. The adapter pattern
normalizes them into a common interface so the pipeline doesn't care where
data comes from.

**What interviewer may ask**: "Why not just use if/else for each platform?"

**How to explain**: "If/else creates tight coupling — adding Instagram would mean
modifying existing code. With adapters, I just create a new class that implements
`fetch()` and `normalize()`. The pipeline calls the same interface regardless.
This follows the Open/Closed Principle — open for extension, closed for modification."

**What happens if removed**: The pipeline would need platform-specific logic scattered
throughout, making it fragile and hard to test.

---

### 4.2 Service Layer Pattern

```
  View (thin) → Service (business logic) → Model (data access)
```

**Why**: Django views handle HTTP concerns only. Business logic lives in service
functions that can be tested independently without HTTP.

**What interviewer may ask**: "Why not put logic directly in views?"

**How to explain**: "Fat views are hard to test — you need to mock HTTP requests.
Service functions are plain Python that accept parameters and return results.
I can unit test `generate_clusters(discussions)` without touching Django's
request/response cycle."

---

### 4.3 Pipeline Orchestrator

**Why**: The analysis pipeline has 6+ steps that must execute in order with error
handling at each stage. The orchestrator coordinates this, tracks progress,
and handles partial failures.

**What interviewer may ask**: "Why not use Celery for async tasks?"

**How to explain**: "Celery adds operational complexity — a Redis broker, a worker
process, monitoring. For an MVP analyzing ~500 discussions per topic, synchronous
execution completes in under 30 seconds. I designed the orchestrator so it can
be made async later by wrapping each step in a Celery task, but the added
infrastructure cost isn't justified yet."

---

## 5. Technology Choices

| Technology | Role | Why This | Alternative | Tradeoff |
|---|---|---|---|---|
| Django + DRF | Backend API | Batteries-included, admin panel, ORM, mature ecosystem | FastAPI | Django has better ORM, admin, and ecosystem for a full-stack app |
| PostgreSQL | Database | ACID-compliant, JSON fields for metadata, Render support | SQLite / MongoDB | SQLite can't handle concurrent writes; MongoDB lacks relations we need |
| sentence-transformers | Embeddings | Local inference, no API cost, ~80MB model | OpenAI API | Free, offline, deterministic — ideal for portfolio project |
| all-MiniLM-L6-v2 | Embedding model | 384-dim, fast, good quality-to-size ratio | all-mpnet-base-v2 | MiniLM is 5x faster; mpnet is slightly more accurate but 3x larger |
| KMeans | Clustering | Simple, deterministic, explainable | DBSCAN | KMeans needs K (we use Silhouette); DBSCAN auto-finds clusters but is harder to explain |
| VADER | Sentiment | Rule-based, no training, fast, works on short text | TextBlob / HuggingFace | VADER handles social media text well (slang, emojis, caps) |
| Chart.js | Visualization | Lightweight, well-documented, sufficient for our charts | D3.js / Plotly | D3 is more powerful but much harder; Chart.js covers our needs |
| Vanilla JS | Frontend | No build step, simple, interview-friendly | React / Vue | Frameworks add complexity; vanilla JS proves fundamentals |

---

## 6. Folder Structure

```
trenddna/
│
├── manage.py                          # Django management
├── requirements.txt                   # Python dependencies
├── .env.example                       # Environment variable template
├── .gitignore                         # Git ignore rules
├── README.md                          # Project documentation
│
├── config/                            # Django project configuration
│   ├── __init__.py
│   ├── settings/
│   │   ├── __init__.py                # Loads env-appropriate settings
│   │   ├── base.py                    # Shared settings (apps, middleware)
│   │   ├── development.py             # DEBUG=True, relaxed CORS
│   │   └── production.py              # Security, PostgreSQL, static files
│   ├── urls.py                        # Root URL configuration
│   ├── wsgi.py                        # WSGI entry point (Gunicorn)
│   └── asgi.py                        # ASGI entry point (future)
│
├── apps/                              # Django applications
│   ├── __init__.py
│   │
│   ├── topics/                        # Topic management
│   │   ├── __init__.py
│   │   ├── models.py                  # Topic, Discussion models
│   │   ├── serializers.py             # DRF serializers
│   │   ├── views.py                   # API endpoints
│   │   ├── urls.py                    # URL routing
│   │   ├── admin.py                   # Django admin config
│   │   └── tests.py                   # Unit tests
│   │
│   ├── ingestion/                     # Data collection
│   │   ├── __init__.py
│   │   ├── base.py                    # Abstract adapter interface
│   │   ├── reddit.py                  # Reddit adapter
│   │   ├── youtube.py                 # YouTube adapter
│   │   ├── preprocessor.py            # Text cleaning pipeline
│   │   ├── services.py                # Ingestion orchestration
│   │   └── tests.py
│   │
│   ├── analysis/                      # NLP + Analytics
│   │   ├── __init__.py
│   │   ├── models.py                  # Cluster, Sentiment, Insight models
│   │   ├── embeddings.py              # Embedding generation service
│   │   ├── clustering.py              # KMeans / DBSCAN service
│   │   ├── sentiment.py               # VADER sentiment service
│   │   ├── trends.py                  # Spike & trend detection
│   │   ├── insights.py                # Explainability engine
│   │   ├── serializers.py             # DRF serializers
│   │   ├── views.py                   # Analysis API endpoints
│   │   ├── urls.py                    # URL routing
│   │   └── tests.py
│   │
│   └── pipeline/                      # Orchestration
│       ├── __init__.py
│       ├── orchestrator.py            # Pipeline coordinator
│       └── tests.py
│
├── templates/                         # Django HTML templates
│   ├── base.html                      # Base layout
│   └── dashboard.html                 # Main dashboard page
│
├── static/                            # Static assets
│   ├── css/
│   │   └── main.css                   # Stylesheet (dark, minimal)
│   ├── js/
│   │   ├── app.js                     # Main application logic
│   │   ├── api.js                     # API client module
│   │   └── charts.js                  # Chart.js visualizations
│   └── assets/                        # Images, icons
│
├── docs/                              # Documentation
│   ├── architecture.md                # This file
│   ├── api_design.md                  # REST API specification
│   ├── er_diagram.md                  # Database schema
│   └── deployment.md                  # Render deployment guide
│
└── scripts/                           # Utility scripts
    └── seed_data.py                   # Sample data for testing
```

### Why this structure?

**Interview Point**: "I separated concerns into four Django apps — `topics` owns the
data models, `ingestion` handles platform adapters, `analysis` runs the NLP pipeline,
and `pipeline` orchestrates them. This means I can test each layer independently.
For example, I can unit test sentiment analysis without needing Reddit data — I just
pass mock text."

**Common Mistake**: Putting everything in one app. This works for small projects but
makes testing, code navigation, and team collaboration harder.

---

## 7. Security Considerations

- **No API keys in code**: All secrets in `.env`, loaded via `python-decouple`
- **CORS**: Restricted in production, open in development
- **Rate limiting**: Respect Reddit/YouTube rate limits with backoff
- **Input sanitization**: Strip HTML from ingested content
- **CSRF**: Django's built-in protection for template-rendered forms
- **SQL injection**: ORM prevents this by default

---

## 8. Scalability Notes (Interview Talking Points)

**Current design handles**: ~500 discussions per topic, single-server deployment.

**If asked "how would you scale this?":**

1. **Async pipeline**: Wrap orchestrator steps in Celery tasks with Redis broker
2. **Vector storage**: Move embeddings to pgvector or Pinecone for similarity search
3. **Caching**: Redis cache for frequently-accessed analysis results
4. **CDN**: Serve static files from CloudFront/Cloudflare
5. **Read replicas**: PostgreSQL read replicas for dashboard queries
6. **Horizontal scaling**: Gunicorn workers behind a load balancer

**Key insight for interviews**: "I designed the system to be simple now but scalable
later. The service layer pattern means I can swap synchronous calls for Celery tasks
without changing the API or frontend. The adapter pattern means I can add new data
sources without modifying existing code."
