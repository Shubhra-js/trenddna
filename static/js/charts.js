/**
 * TrendDNA — Chart.js Configuration Module
 *
 * WHY THIS FILE EXISTS:
 *   Centralizes chart configuration and creation. Chart.js global defaults
 *   are set here so every chart has consistent styling matching our dark theme.
 *
 * INTERVIEW Q: "Why Chart.js instead of D3?"
 *   "Chart.js gives us line charts, bar charts, and doughnut charts out
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

    // Track chart instances for cleanup on re-render
    let sentimentDonutChart = null;
    let clusterBarsChart = null;

    return {
        init: initDefaults,
        COLORS,

        /**
         * Create a doughnut chart showing positive/neutral/negative distribution.
         *
         * WHY DOUGHNUT (not pie):
         *   The hollow center provides space for the average score display.
         *   Doughnut charts are also easier to compare across topics.
         */
        createSentimentDonut(canvasId, data) {
            if (typeof Chart === 'undefined') return;

            const canvas = document.getElementById(canvasId);
            if (!canvas) return;

            // Destroy previous chart if re-rendering
            if (sentimentDonutChart) {
                sentimentDonutChart.destroy();
            }

            const ctx = canvas.getContext('2d');
            sentimentDonutChart = new Chart(ctx, {
                type: 'doughnut',
                data: {
                    labels: ['Positive', 'Neutral', 'Negative'],
                    datasets: [{
                        data: [data.positive, data.neutral, data.negative],
                        backgroundColor: [COLORS.positive, COLORS.neutral, COLORS.negative],
                        borderWidth: 0,
                        hoverOffset: 6,
                    }],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    cutout: '65%',
                    plugins: {
                        legend: {
                            position: 'bottom',
                            labels: {
                                padding: 20,
                                usePointStyle: true,
                                pointStyleWidth: 10,
                            },
                        },
                        tooltip: {
                            callbacks: {
                                label(context) {
                                    const total = context.dataset.data.reduce((a, b) => a + b, 0);
                                    const pct = total > 0
                                        ? Math.round(context.parsed / total * 100)
                                        : 0;
                                    return `${context.label}: ${context.parsed} (${pct}%)`;
                                },
                            },
                        },
                    },
                },
            });
        },

        /**
         * Create horizontal bar chart showing sentiment per cluster.
         *
         * Each cluster gets a bar colored by its dominant sentiment.
         */
        createClusterSentimentBars(canvasId, clusters) {
            if (typeof Chart === 'undefined') return;

            const canvas = document.getElementById(canvasId);
            if (!canvas) return;

            if (clusterBarsChart) {
                clusterBarsChart.destroy();
            }

            const labels = clusters.map(c => c.label.length > 25
                ? c.label.substring(0, 25) + '…'
                : c.label
            );
            const scores = clusters.map(c => c.average_score);
            const colors = scores.map(s =>
                s > 0.05 ? COLORS.positive
                : s < -0.05 ? COLORS.negative
                : COLORS.neutral
            );

            const ctx = canvas.getContext('2d');
            clusterBarsChart = new Chart(ctx, {
                type: 'bar',
                data: {
                    labels,
                    datasets: [{
                        label: 'Avg Sentiment',
                        data: scores,
                        backgroundColor: colors,
                        borderRadius: 4,
                        barThickness: 24,
                    }],
                },
                options: {
                    indexAxis: 'y',
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        x: {
                            min: -1,
                            max: 1,
                            grid: { color: 'rgba(148, 163, 184, 0.1)' },
                            ticks: {
                                callback: v => v.toFixed(1),
                            },
                        },
                        y: {
                            grid: { display: false },
                        },
                    },
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            callbacks: {
                                label(context) {
                                    const score = context.parsed.x;
                                    const label = score > 0.05 ? 'Positive'
                                        : score < -0.05 ? 'Negative'
                                        : 'Neutral';
                                    return `${label}: ${score.toFixed(3)}`;
                                },
                            },
                        },
                    },
                },
            });
        },
    };
})();

// Initialize chart defaults when the script loads
document.addEventListener('DOMContentLoaded', () => {
    TrendCharts.init();
});
