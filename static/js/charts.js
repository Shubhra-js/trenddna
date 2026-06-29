/**
 * TrendDNA — Chart.js Configuration Module
 *
 * WHY THIS FILE EXISTS:
 *   Centralizes chart configuration and creation. Currently contains
 *   placeholder setup for Phase 7 when real data will be visualized.
 *   Chart.js global defaults are set here so every chart has consistent
 *   styling matching our dark theme.
 *
 * INTERVIEW Q: "Why Chart.js instead of D3?"
 *   "Chart.js gives us line charts, bar charts, and scatter plots out
 *   of the box with minimal config. D3 is more powerful for custom
 *   visualizations but requires much more code. For an analytics
 *   dashboard with standard chart types, Chart.js is sufficient."
 */

const TrendCharts = (() => {
    // Apply dark theme defaults to all charts once Chart.js loads
    function initDefaults() {
        if (typeof Chart === 'undefined') return;

        Chart.defaults.color = '#94a3b8';
        Chart.defaults.borderColor = '#1e293b';
        Chart.defaults.font.family = "'Inter', sans-serif";
        Chart.defaults.font.size = 12;
        Chart.defaults.plugins.legend.labels.usePointStyle = true;
        Chart.defaults.plugins.legend.labels.padding = 16;
        Chart.defaults.plugins.tooltip.backgroundColor = '#1a2235';
        Chart.defaults.plugins.tooltip.borderColor = '#1e293b';
        Chart.defaults.plugins.tooltip.borderWidth = 1;
        Chart.defaults.plugins.tooltip.cornerRadius = 8;
        Chart.defaults.plugins.tooltip.padding = 12;
    }

    // Theme-consistent color palette for chart data
    const COLORS = {
        accent: '#6366f1',
        accentLight: '#818cf8',
        positive: '#22c55e',
        negative: '#ef4444',
        neutral: '#94a3b8',
        warning: '#f59e0b',
        info: '#3b82f6',
        series: ['#6366f1', '#22c55e', '#f59e0b', '#ef4444', '#3b82f6', '#a855f7'],
    };

    return {
        init: initDefaults,
        COLORS,

        // Placeholder — will create real charts in Phase 7
        createSentimentTimeline(canvasId, data) {
            console.log('[TrendCharts] Sentiment timeline will be implemented in Phase 7');
        },

        createClusterScatter(canvasId, data) {
            console.log('[TrendCharts] Cluster scatter will be implemented in Phase 7');
        },
    };
})();

// Initialize chart defaults when the script loads
document.addEventListener('DOMContentLoaded', () => {
    TrendCharts.init();
});
