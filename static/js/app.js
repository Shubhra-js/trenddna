/**
 * TrendDNA — Main Application Logic
 *
 * WHY THIS FILE EXISTS:
 *   Handles all DOM interaction, user events, and UI state management.
 *   Uses api.js for backend calls and charts.js for visualization.
 *   This is the "controller" in an MVC-like separation.
 *
 * INTERVIEW Q: "How is your frontend organized?"
 *   "I separated concerns into three modules: api.js handles HTTP requests,
 *   charts.js handles Chart.js configuration, and app.js handles DOM
 *   manipulation and user interaction. Each module is an IIFE that exposes
 *   a public API via the revealing module pattern. This keeps the global
 *   namespace clean and makes dependencies explicit."
 *
 * INTERVIEW Q: "Why not a framework like React?"
 *   "For a dashboard with one page and a handful of interactive elements,
 *   vanilla JS is simpler and proves I understand the DOM API. A framework
 *   would add a build step, a node_modules folder, and JSX/virtual DOM
 *   overhead for a page that has ~10 interactive elements."
 */

const TrendApp = (() => {
    // =================================================================
    // DOM Element Cache
    // =================================================================
    // Cache DOM lookups for performance (avoid querying the DOM repeatedly)
    const elements = {};

    function cacheElements() {
        elements.topicForm = document.getElementById('topic-form');
        elements.topicInput = document.getElementById('topic-input');
        elements.submitBtn = document.getElementById('submit-btn');
        elements.btnText = document.querySelector('.search__btn-text');
        elements.btnLoading = document.querySelector('.search__btn-loading');

        elements.statusPanel = document.getElementById('status-panel');
        elements.statusTopicName = document.getElementById('status-topic-name');
        elements.statusSteps = document.getElementById('status-steps');
        elements.statusClose = document.getElementById('status-close');

        elements.statsRow = document.getElementById('stats-row');
        elements.statDiscussions = document.querySelector('#stat-discussions .stat-card__value');
        elements.statClusters = document.querySelector('#stat-clusters .stat-card__value');
        elements.statSentiment = document.querySelector('#stat-sentiment .stat-card__value');
        elements.statSources = document.querySelector('#stat-sources .stat-card__value');

        elements.historyEmpty = document.getElementById('history-empty');
        elements.historyLoading = document.getElementById('history-loading');
        elements.historyList = document.getElementById('history-list');
        elements.refreshBtn = document.getElementById('refresh-btn');

        elements.toastContainer = document.getElementById('toast-container');

        // Cluster panel elements
        elements.clusterList = document.getElementById('cluster-list');
        elements.clusterPlaceholder = document.getElementById('cluster-placeholder');
        elements.clusterBadge = document.getElementById('cluster-badge');
        elements.explainContent = document.getElementById('explainability-content');
        elements.explainPlaceholder = document.getElementById('explain-placeholder');
    }

    // =================================================================
    // State
    // =================================================================
    let currentTopicId = null;
    let isSubmitting = false;
    let statusPollInterval = null;

    // =================================================================
    // Event Binding
    // =================================================================
    function bindEvents() {
        // Topic form submission
        elements.topicForm.addEventListener('submit', handleTopicSubmit);

        // Refresh button
        elements.refreshBtn.addEventListener('click', loadTopicHistory);

        // Close status panel
        elements.statusClose.addEventListener('click', () => {
            elements.statusPanel.hidden = true;
            stopStatusPolling();
        });

        // Keyboard shortcut: focus search on '/'
        document.addEventListener('keydown', (e) => {
            if (e.key === '/' && document.activeElement !== elements.topicInput) {
                e.preventDefault();
                elements.topicInput.focus();
            }
        });
    }

    // =================================================================
    // Topic Submission
    // =================================================================
    async function handleTopicSubmit(e) {
        e.preventDefault();

        if (isSubmitting) return;

        const name = elements.topicInput.value.trim();
        if (name.length < 2) {
            showToast('Topic name must be at least 2 characters', 'error');
            return;
        }

        setSubmitLoading(true);

        try {
            // Step 1: Create the topic
            const topic = await TrendAPI.createTopic(name);
            currentTopicId = topic.id;

            showToast(`Topic "${topic.name}" created — starting ingestion`, 'success');
            elements.topicInput.value = '';

            // Step 2: Show status panel
            showStatusPanel(topic.name);
            updateStatCards(topic);

            // Step 3: Trigger real ingestion
            await triggerIngestion(topic.id);

            // Step 4: Start polling for real-time updates
            startStatusPolling(topic.id);

            // Refresh the history list
            await loadTopicHistory();

        } catch (error) {
            console.error('Failed to create topic:', error);

            if (error.data?.name) {
                showToast(error.data.name[0], 'error');
            } else {
                showToast(error.message || 'Failed to create topic', 'error');
            }
        } finally {
            setSubmitLoading(false);
        }
    }

    /**
     * Trigger ingestion via the backend API.
     *
     * PHASE 3 CHANGE:
     *   Replaced the Phase 2 simulation with a real POST to
     *   /api/v1/topics/{id}/ingest/. The backend starts a background
     *   thread and returns 202 immediately.
     */
    async function triggerIngestion(topicId) {
        try {
            const result = await TrendAPI.triggerIngestion(topicId);
            // Mark the ingestion step as active
            setStepActive('ingestion', 'Collecting from Reddit & YouTube...');
        } catch (error) {
            if (error.status === 409) {
                showToast('Ingestion already in progress', 'info');
            } else {
                showToast('Failed to start ingestion: ' + error.message, 'error');
            }
        }
    }

    function setSubmitLoading(loading) {
        isSubmitting = loading;
        elements.submitBtn.disabled = loading;
        elements.btnText.hidden = loading;
        elements.btnLoading.hidden = !loading;
    }

    // =================================================================
    // Status Panel — Real-time Polling
    // =================================================================
    function showStatusPanel(topicName) {
        elements.statusTopicName.textContent = topicName;
        elements.statusPanel.hidden = false;

        // Reset all steps to default state
        const steps = elements.statusSteps.querySelectorAll('.step');
        steps.forEach(step => {
            step.classList.remove('step--active', 'step--completed', 'step--failed');
            step.querySelector('.step__detail').textContent = '';
        });
    }

    /**
     * Poll GET /api/v1/topics/{id}/status/ every 2 seconds.
     *
     * PHASE 3 CHANGE:
     *   Replaced the Phase 2 fake setInterval simulation with real
     *   API polling. Each poll returns the current topic status and
     *   live discussion_count (which increases as the background
     *   thread saves items).
     *
     * INTERVIEW Q: "Why polling instead of WebSockets?"
     *   "Polling is simpler and sufficient for ingestion that takes
     *   10-30 seconds. WebSockets add infrastructure complexity
     *   (Django Channels, Redis pub/sub). I'd switch to WebSockets
     *   if I needed sub-second real-time updates or persistent
     *   bidirectional communication."
     */
    function startStatusPolling(topicId) {
        // Clear any existing interval
        stopStatusPolling();

        let lastCount = 0;

        statusPollInterval = setInterval(async () => {
            try {
                const status = await TrendAPI.getTopicStatus(topicId);

                // Update stat cards with real data
                elements.statDiscussions.textContent = status.discussion_count;
                const activeSources = [];
                if (status.sources.reddit > 0) activeSources.push('Reddit');
                if (status.sources.youtube > 0) activeSources.push('YouTube');
                elements.statSources.textContent = activeSources.length || '—';

                // Update step indicators based on real progress
                if (status.discussion_count > 0 && status.discussion_count !== lastCount) {
                    setStepCompleted('ingestion',
                        `${status.sources.reddit} Reddit, ${status.sources.youtube} YouTube`
                    );
                    setStepCompleted('preprocessing',
                        `Cleaned ${status.discussion_count} discussions`
                    );
                    lastCount = status.discussion_count;
                }

                // Show embedding progress when status is 'analyzing'
                if (status.status === 'analyzing') {
                    setStepCompleted('ingestion',
                        `${status.sources.reddit} Reddit, ${status.sources.youtube} YouTube`
                    );
                    setStepCompleted('preprocessing',
                        `${status.discussion_count} discussions cleaned`
                    );
                    setStepActive('embedding',
                        `Generating vectors for ${status.discussion_count} discussions...`
                    );
                }

                // Check if pipeline is done
                if (status.status === 'completed') {
                    stopStatusPolling();
                    handleIngestionComplete(status);
                } else if (status.status === 'failed') {
                    stopStatusPolling();
                    handleIngestionFailed();
                }

            } catch (error) {
                console.error('Status poll failed:', error);
            }
        }, 2000);
    }

    function stopStatusPolling() {
        if (statusPollInterval) {
            clearInterval(statusPollInterval);
            statusPollInterval = null;
        }
    }

    /**
     * Handle successful ingestion completion.
     * Mark completed steps, show summary, refresh history.
     */
    function handleIngestionComplete(status) {
        // Mark all completed steps
        setStepCompleted('ingestion',
            `${status.sources.reddit} Reddit, ${status.sources.youtube} YouTube`
        );
        setStepCompleted('preprocessing', `${status.discussion_count} discussions cleaned`);

        // Show embedding completion (Phase 4)
        if (status.embeddings_count > 0) {
            setStepCompleted('embedding',
                `${status.embeddings_count} vectors generated`
            );
        } else {
            setStepActive('embedding', 'No discussions to embed');
        }

        // Show clustering completion (Phase 5)
        if (status.cluster_count > 0) {
            setStepCompleted('clustering',
                `${status.cluster_count} themes discovered`
            );
            // Update cluster stat card
            elements.statClusters.textContent = status.cluster_count;
        } else {
            setStepCompleted('clustering', 'Too few discussions to cluster');
        }

        // Mark future steps as pending
        const futureSteps = ['sentiment', 'trends', 'insights'];
        futureSteps.forEach(step => {
            const el = elements.statusSteps.querySelector(`[data-step="${step}"]`);
            if (el) {
                el.querySelector('.step__detail').textContent = 'Phase 6+';
            }
        });

        showToast(
            `Pipeline complete! ${status.discussion_count} discussions, ${status.cluster_count || 0} clusters`,
            'success'
        );

        // Auto-load cluster results
        if (currentTopicId) {
            loadClusters(currentTopicId);
        }

        // Refresh history to show updated counts
        loadTopicHistory();
    }

    function handleIngestionFailed() {
        const ingestionStep = elements.statusSteps.querySelector('[data-step="ingestion"]');
        if (ingestionStep) {
            ingestionStep.classList.remove('step--active');
            ingestionStep.classList.add('step--failed');
            ingestionStep.querySelector('.step__detail').textContent = 'Failed';
        }
        showToast('Ingestion failed — check server logs', 'error');
    }

    // =================================================================
    // Step Indicator Helpers
    // =================================================================
    function setStepActive(stepName, detail = '') {
        const step = elements.statusSteps.querySelector(`[data-step="${stepName}"]`);
        if (step) {
            step.classList.remove('step--completed', 'step--failed');
            step.classList.add('step--active');
            step.querySelector('.step__detail').textContent = detail;
        }
    }

    function setStepCompleted(stepName, detail = 'Done') {
        const step = elements.statusSteps.querySelector(`[data-step="${stepName}"]`);
        if (step) {
            step.classList.remove('step--active', 'step--failed');
            step.classList.add('step--completed');
            step.querySelector('.step__detail').textContent = detail;
        }
    }

    // =================================================================
    // Stat Cards
    // =================================================================
    function updateStatCards(topic) {
        elements.statDiscussions.textContent = topic.discussion_count || '0';
        elements.statClusters.textContent = '—';
        elements.statSentiment.textContent = '—';
        elements.statSources.textContent = '—';
    }

    // =================================================================
    // Topic History
    // =================================================================
    async function loadTopicHistory() {
        // Show loading, hide others
        elements.historyEmpty.hidden = true;
        elements.historyList.hidden = true;
        elements.historyLoading.hidden = false;

        try {
            const data = await TrendAPI.listTopics();
            const topics = data.results || [];

            if (topics.length === 0) {
                elements.historyLoading.hidden = true;
                elements.historyEmpty.hidden = false;
                return;
            }

            // Build topic cards
            elements.historyList.innerHTML = topics.map(topic => buildTopicCard(topic)).join('');
            elements.historyLoading.hidden = true;
            elements.historyList.hidden = false;

            // Add click listeners to topic cards
            elements.historyList.querySelectorAll('.topic-card').forEach(card => {
                card.addEventListener('click', () => {
                    const topicId = card.dataset.topicId;
                    handleTopicSelect(topicId);
                });
            });

        } catch (error) {
            console.error('Failed to load topics:', error);
            elements.historyLoading.hidden = true;
            elements.historyEmpty.hidden = false;
            showToast('Failed to load topic history', 'error');
        }
    }

    function buildTopicCard(topic) {
        const date = new Date(topic.created_at);
        const timeAgo = formatTimeAgo(date);

        return `
            <div class="topic-card" data-topic-id="${topic.id}" tabindex="0" role="button"
                 aria-label="View analysis for ${escapeHtml(topic.name)}">
                <div class="topic-card__info">
                    <div class="topic-card__name">${escapeHtml(topic.name)}</div>
                    <div class="topic-card__meta">
                        <span class="topic-card__status topic-card__status--${topic.status}">
                            ${topic.status}
                        </span>
                        <span>${timeAgo}</span>
                    </div>
                </div>
                <div class="topic-card__discussions">
                    ${topic.discussion_count || 0} discussions
                </div>
            </div>
        `;
    }

    async function handleTopicSelect(topicId) {
        try {
            const topic = await TrendAPI.getTopic(topicId);
            currentTopicId = topic.id;
            updateStatCards(topic);

            // Also fetch live status for source breakdown
            const status = await TrendAPI.getTopicStatus(topicId);
            elements.statDiscussions.textContent = status.discussion_count;
            const activeSources = [];
            if (status.sources.reddit > 0) activeSources.push('Reddit');
            if (status.sources.youtube > 0) activeSources.push('YouTube');
            elements.statSources.textContent = activeSources.length || '—';

            // Scroll to dashboard
            document.getElementById('dashboard-section').scrollIntoView({
                behavior: 'smooth'
            });

            showToast(`Loaded: ${topic.name} (${status.discussion_count} discussions)`, 'info');
        } catch (error) {
            showToast('Failed to load topic details', 'error');
        }
    }

    // =================================================================
    // Toast Notifications
    // =================================================================
    function showToast(message, type = 'info') {
        const toast = document.createElement('div');
        toast.className = `toast toast--${type}`;
        toast.textContent = message;
        elements.toastContainer.appendChild(toast);

        // Auto-dismiss after 4 seconds
        setTimeout(() => {
            toast.classList.add('toast--out');
            toast.addEventListener('animationend', () => toast.remove());
        }, 4000);
    }

    // =================================================================
    // Utilities
    // =================================================================
    function formatTimeAgo(date) {
        const seconds = Math.floor((new Date() - date) / 1000);

        if (seconds < 60) return 'just now';
        if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
        if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
        if (seconds < 604800) return `${Math.floor(seconds / 86400)}d ago`;

        return date.toLocaleDateString('en-US', {
            month: 'short',
            day: 'numeric',
        });
    }

    /**
     * Escape HTML to prevent XSS when inserting user-provided text.
     *
     * WHY THIS MATTERS:
     *   Topic names come from user input. Without escaping, a name like
     *   '<script>alert("xss")</script>' would execute JavaScript.
     *   This function replaces dangerous characters with HTML entities.
     */
    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    // =================================================================
    // Cluster Rendering (Phase 5)
    // =================================================================

    /**
     * Load and render cluster results for a topic.
     * Called automatically after pipeline completes.
     */
    async function loadClusters(topicId) {
        try {
            const data = await TrendAPI.getClusters(topicId);

            if (!data.clusters || data.clusters.length === 0) {
                return; // No clusters — keep placeholder visible
            }

            // Hide placeholder, show cluster list
            if (elements.clusterPlaceholder) elements.clusterPlaceholder.hidden = true;
            if (elements.clusterList) elements.clusterList.hidden = false;

            // Update badge
            if (elements.clusterBadge) {
                elements.clusterBadge.textContent = `${data.cluster_count} clusters`;
            }

            // Render cluster cards
            elements.clusterList.innerHTML = data.clusters
                .map(renderClusterCard)
                .join('');

            // Render explainability panel
            renderExplainability(data);

        } catch (error) {
            console.error('Failed to load clusters:', error);
        }
    }

    /**
     * Render a single cluster card with label, keywords, count,
     * and representative discussions.
     */
    function renderClusterCard(cluster) {
        const keywordTags = cluster.keywords
            .map(kw => `<span class="cluster-card__tag">${escapeHtml(kw)}</span>`)
            .join('');

        const discussionItems = (cluster.top_discussions || [])
            .map(d => `
                <div class="cluster-card__discussion">
                    <span class="cluster-card__source cluster-card__source--${d.source}">
                        ${d.source}
                    </span>
                    <span class="cluster-card__disc-text">
                        ${escapeHtml(d.content_preview || d.title)}
                    </span>
                </div>
            `).join('');

        return `
            <div class="cluster-card">
                <div class="cluster-card__header">
                    <h4 class="cluster-card__title">${escapeHtml(cluster.label)}</h4>
                    <span class="cluster-card__count">${cluster.member_count} discussions</span>
                </div>
                <div class="cluster-card__keywords">
                    ${keywordTags}
                </div>
                <div class="cluster-card__discussions">
                    ${discussionItems || '<p class="cluster-card__empty">No preview available</p>'}
                </div>
            </div>
        `;
    }

    /**
     * Render the explainability panel with cluster formation explanation.
     */
    function renderExplainability(data) {
        if (elements.explainPlaceholder) elements.explainPlaceholder.hidden = true;
        if (elements.explainContent) {
            elements.explainContent.hidden = false;

            const silhouetteDesc = data.silhouette_score > 0.5 ? 'well-separated'
                : data.silhouette_score > 0.25 ? 'reasonably distinct'
                : 'broadly grouped';

            let html = `
                <div class="explainability__section">
                    <h4 class="explainability__heading">Why These Clusters?</h4>
                    <p class="explainability__text">
                        Each discussion was converted into a <strong>384-dimensional semantic vector</strong>
                        using a sentence-transformer model. Discussions with similar meaning produce
                        vectors that are close together in this high-dimensional space.
                    </p>
                    <p class="explainability__text">
                        <strong>KMeans clustering</strong> found <strong>${data.cluster_count}</strong>
                        natural groupings by minimizing the distance between discussions and their
                        cluster centers. The clusters are <strong>${silhouetteDesc}</strong>
                        (silhouette score: ${data.silhouette_score?.toFixed(3) || '—'}).
                    </p>
                </div>
                <div class="explainability__section">
                    <h4 class="explainability__heading">Cluster Details</h4>
            `;

            data.clusters.forEach(c => {
                html += `
                    <div class="explainability__cluster">
                        <strong>${escapeHtml(c.label)}</strong>
                        <span class="explainability__meta">
                            ${c.member_count} discussions · coherence: ${c.coherence_score?.toFixed(2) || '—'}
                        </span>
                        <p class="explainability__summary">${escapeHtml(c.summary)}</p>
                    </div>
                `;
            });

            html += '</div>';
            elements.explainContent.innerHTML = html;
        }
    }

    // =================================================================
    // Health Check
    // =================================================================
    async function checkHealth() {
        try {
            await TrendAPI.healthCheck();
            const dot = document.querySelector('.nav__status-dot');
            const text = document.querySelector('.nav__status-text');
            if (dot) dot.style.backgroundColor = 'var(--color-success)';
            if (text) text.textContent = 'System Online';
        } catch {
            const dot = document.querySelector('.nav__status-dot');
            const text = document.querySelector('.nav__status-text');
            if (dot) dot.style.backgroundColor = 'var(--color-error)';
            if (text) text.textContent = 'System Offline';
        }
    }

    // =================================================================
    // Initialization
    // =================================================================
    function init() {
        cacheElements();
        bindEvents();
        checkHealth();
        loadTopicHistory();
    }

    // Start when DOM is ready
    document.addEventListener('DOMContentLoaded', init);

    // Public API (for debugging in browser console)
    return {
        showToast,
        loadTopicHistory,
        checkHealth,
    };
})();
