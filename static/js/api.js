/**
 * TrendDNA — API Client Module
 *
 * WHY THIS FILE EXISTS:
 *   Centralizes all backend communication in one place. Every API call
 *   goes through this module, so changing the base URL, adding auth
 *   headers, or modifying error handling affects all requests at once.
 *
 * INTERVIEW Q: "Why separate the API client from the UI logic?"
 *   "Separation of concerns. app.js handles DOM manipulation and user
 *   interaction. api.js handles HTTP requests. If I switch from fetch
 *   to axios, or add JWT tokens, I only change this file."
 *
 * INTERVIEW Q: "Why not use axios?"
 *   "fetch() is built into every modern browser — zero dependencies.
 *   Axios adds request interceptors and auto-transforms, but for an
 *   MVP with 5 endpoints, fetch is sufficient and lighter."
 */

const TrendAPI = (() => {
    // Base URL — works in both dev and production
    const BASE_URL = '/api/v1';

    /**
     * Generic request handler with consistent error handling.
     *
     * WHY: Every API call needs the same boilerplate — set headers,
     * check response status, parse JSON, handle errors. This function
     * eliminates that repetition.
     *
     * COMMON MISTAKE: Not checking response.ok before parsing JSON.
     * A 400/500 response still returns a body — you need to throw
     * an error so the caller's catch() block runs.
     */
    async function request(endpoint, options = {}) {
        const url = `${BASE_URL}${endpoint}`;

        const config = {
            headers: {
                'Content-Type': 'application/json',
                ...options.headers,
            },
            ...options,
        };

        try {
            const response = await fetch(url, config);

            // Parse response body (even error responses have JSON bodies)
            let data;
            try {
                data = await response.json();
            } catch {
                data = null;
            }

            if (!response.ok) {
                // Build a descriptive error from the API response
                const error = new Error(
                    data?.message || data?.detail || `HTTP ${response.status}`
                );
                error.status = response.status;
                error.data = data;
                throw error;
            }

            return data;
        } catch (error) {
            // Network errors (server down, CORS blocked, etc.)
            if (!error.status) {
                error.message = 'Network error — is the server running?';
            }
            throw error;
        }
    }

    // =================================================================
    // Public API Methods
    // =================================================================

    return {
        /**
         * Create a new topic and trigger analysis.
         * POST /api/v1/topics/
         */
        createTopic(name) {
            return request('/topics/', {
                method: 'POST',
                body: JSON.stringify({ name }),
            });
        },

        /**
         * List all topics with summary stats.
         * GET /api/v1/topics/
         */
        listTopics(page = 1) {
            return request(`/topics/?page=${page}`);
        },

        /**
         * Get full detail for a single topic.
         * GET /api/v1/topics/{id}/
         */
        getTopic(id) {
            return request(`/topics/${id}/`);
        },

        /**
         * Health check — verify server is alive.
         * GET /api/v1/health/
         */
        healthCheck() {
            return request('/health/');
        },

        // =============================================================
        // Ingestion endpoints (Phase 3 — real implementations)
        // =============================================================

        /**
         * Trigger data ingestion for a topic.
         * POST /api/v1/topics/{id}/ingest/
         * Returns 202 immediately; backend runs in background thread.
         */
        triggerIngestion(id) {
            return request(`/topics/${id}/ingest/`, {
                method: 'POST',
            });
        },

        /**
         * Get real-time ingestion/analysis status.
         * GET /api/v1/topics/{id}/status/
         * Returns { status, discussion_count, sources: {reddit, youtube} }
         */
        getTopicStatus(id) {
            return request(`/topics/${id}/status/`);
        },

        // =============================================================
        // Analysis endpoints (Phase 5 — cluster results)
        // =============================================================

        /**
         * Get cluster data for a topic.
         * GET /api/v1/topics/{id}/clusters/
         * Returns { cluster_count, clusters: [{label, keywords, ...}] }
         */
        getClusters(id) {
            return request(`/topics/${id}/clusters/`);
        },

        /**
         * Get sentiment timeline data (Phase 7).
         * GET /api/v1/topics/{id}/sentiment/
         */
        getSentiment(id) {
            return request(`/topics/${id}/sentiment/`);
        },

        /**
         * Get AI-generated insights (Phase 7).
         * GET /api/v1/topics/{id}/insights/
         */
        getInsights(id) {
            return request(`/topics/${id}/insights/`);
        },
    };
})();

