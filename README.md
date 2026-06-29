# TrendDNA — Internet Archaeologist

> Analyze how internet discussions evolve around any topic.

TrendDNA ingests public discussions from Reddit and YouTube, processes them through
an NLP pipeline (semantic embeddings, clustering, sentiment analysis), detects trend
spikes, and surfaces explainable insights on an interactive dashboard.

## What It Does

1. **Enter a topic** — "remote work", "electric vehicles", "AI in education"
2. **Collects discussions** — Reddit posts/comments + YouTube comments
3. **Clusters by theme** — Groups semantically similar discussions using KMeans
4. **Tracks sentiment** — VADER analysis shows how opinions shift over time
5. **Detects spikes** — Finds sudden surges in volume or sentiment changes
6. **Explains why** — Every insight comes with source, method, and interpretation

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Django + Django REST Framework |
| Frontend | HTML, CSS, JavaScript, Chart.js |
| Database | PostgreSQL |
| Embeddings | sentence-transformers (all-MiniLM-L6-v2) |
| Clustering | scikit-learn (KMeans, DBSCAN) |
| Sentiment | VADER (vaderSentiment) |
| Deployment | Render |

## Architecture

```
User → Frontend Dashboard → REST API → Pipeline Orchestrator
                                            │
                         ┌──────────────────┼──────────────────┐
                         │                  │                  │
                    Ingestion          Analysis           Insights
                   (Adapters)      (Embed/Cluster/      (Explain)
                  Reddit│YouTube    Sentiment/Trends)
                         │                  │                  │
                         └──────────────────┼──────────────────┘
                                            │
                                        PostgreSQL
```

**Key Design Patterns:**
- **Adapter Pattern** — Data sources implement a common interface for extensibility
- **Service Layer** — Business logic separated from HTTP handling
- **Pipeline Orchestrator** — Coordinates multi-step analysis with error handling

## Features

- [x] Topic-based discussion analysis
- [x] Multi-platform data ingestion (Reddit, YouTube)
- [x] Semantic clustering with automatic labeling
- [x] Sentiment timeline visualization
- [x] Trend spike detection with confidence scores
- [x] Explainability panel ("Why am I seeing this?")
- [x] Dark, minimal analytics dashboard
- [x] RESTful API with versioning

## Project Structure

```
trenddna/
├── config/             # Django settings (base/dev/prod)
├── apps/
│   ├── topics/         # Topic CRUD + Discussion models
│   ├── ingestion/      # Reddit & YouTube adapters
│   ├── analysis/       # Embeddings, clustering, sentiment, trends
│   └── pipeline/       # Orchestrator
├── templates/          # Django HTML templates
├── static/             # CSS, JS, assets
├── docs/               # Architecture, API, ER diagram
└── scripts/            # Utility scripts
```

