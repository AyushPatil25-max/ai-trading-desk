import { renderTerminal } from './views/terminal.js';
import { renderResearchWorkspace } from './views/research_workspace.js';
import { renderAIResearchChat } from './views/ai_research_chat.js';
import { renderWatchlists } from './views/watchlists.js';
import { renderScanner } from './views/scanner.js';
import { renderChart } from './views/chart.js';
import { renderStocks } from './views/stocks.js';
import { renderIPOs } from './views/ipo.js';
import { renderPortfolio } from './views/portfolio.js';
import { renderNews } from './views/news.js';
import { renderAlerts } from './views/alerts.js';
import { renderReconciliation } from './views/reconciliation.js';

import { renderHistoricalResearch } from './views/historical_research.js';
import { renderProductionIntelligence } from './views/production_intelligence.js';

const routes = [
    { id: 'terminal', name: 'Terminal', icon: 'monitor', render: renderTerminal },
    { id: 'broker', name: 'Broker Validation', icon: 'shield-check', render: renderReconciliation },
    { id: 'watchlists', name: 'Watchlists', icon: 'list', render: renderWatchlists },
    { id: 'scanner', name: 'Scanner', icon: 'zap', render: renderScanner },
    { id: 'chart', name: 'Charts', icon: 'bar-chart-2', render: renderChart },
    { id: 'stocks', name: 'Stock Intelligence', icon: 'line-chart', render: renderStocks },
    { id: 'ipos', name: 'IPO Intelligence', icon: 'rocket', render: renderIPOs },
    { id: 'portfolio', name: 'Portfolio', icon: 'pie-chart', render: renderPortfolio },
    { id: 'news', name: 'News & Events', icon: 'newspaper', render: renderNews },
    { id: 'research', name: 'Research', icon: 'brain', render: renderResearchWorkspace },
    { id: 'ai-research-chat', name: 'AI Chat', icon: 'message-circle', render: renderAIResearchChat },
    { id: 'historical-research', name: 'Historical Research', icon: 'history', render: renderHistoricalResearch },
    { id: 'production-intelligence', name: 'Production Intelligence', icon: 'server', render: renderProductionIntelligence },
    { id: 'alerts', name: 'Alerts', icon: 'bell', render: renderAlerts }
];

let currentView = 'terminal';

function initNav() {
    const nav = document.getElementById('mainNav');
    nav.innerHTML = routes.map(route => `
        <button onclick="window.navigateTo('${route.id}')" 
                id="nav-${route.id}"
                class="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all
                       ${route.id === currentView ? 'bg-cyan-900/30 text-cyan-400 border border-cyan-800/50' : 'text-gray-400 hover:text-gray-200 hover:bg-gray-800/50'}">
            <i data-lucide="${route.icon}" class="w-4 h-4"></i>
            ${route.name}
        </button>
    `).join('');
    lucide.createIcons();
}

window.navigateTo = (viewId) => {
    currentView = viewId;
    initNav();
    const route = routes.find(r => r.id === viewId);
    document.getElementById('pageTitle').textContent = route.name;
    const container = document.getElementById('viewContainer');
    container.innerHTML = '<div class="flex items-center justify-center h-64"><div class="animate-spin rounded-full h-8 w-8 border-b-2 border-cyan-400"></div></div>';
    
    // Slight delay for smoothness
    setTimeout(() => {
        route.render(container);
        lucide.createIcons();
    }, 50);
};

document.addEventListener('DOMContentLoaded', () => {
    initNav();
    window.navigateTo('terminal');

    // Update time
    setInterval(() => {
        const timeEl = document.getElementById('statusTime');
        if (timeEl) {
            const now = new Date();
            timeEl.textContent = now.toLocaleTimeString('en-IN');
        }
    }, 1000);

    // Global Market Data Bus
    window.marketDataBus = {
        listeners: new Set(),
        subscribe(fn) {
            this.listeners.add(fn);
            return () => this.listeners.delete(fn);
        },
        publish(tick) {
            this.listeners.forEach(fn => fn(tick));
        },
        latestTicks: {}
    };

    // Connect SSE
    const sse = new EventSource('/api/v1/stream/market-data');
    sse.addEventListener('tick', (e) => {
        try {
            const tick = JSON.parse(e.data);
            window.marketDataBus.latestTicks[tick.symbol] = tick;
            window.marketDataBus.publish(tick);
        } catch (err) {
            console.error('Error parsing tick', err);
        }
    });

    const btnKillSwitch = document.getElementById('btnKillSwitch');
    if (btnKillSwitch) {
        btnKillSwitch.addEventListener('click', async () => {
            if (confirm("EMERGENCY: Are you sure you want to trigger the KILL SWITCH? This will halt all trading.")) {
                try {
                    await fetch('/api/telemetry/kill-switch', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({ action: 'trigger', reason: 'Operator manual emergency stop' })
                    });
                    alert("KILL SWITCH TRIGGERED");
                } catch(e) {
                    console.error(e);
                    alert("Failed to trigger kill switch via API.");
                }
            }
        });
    }
});
