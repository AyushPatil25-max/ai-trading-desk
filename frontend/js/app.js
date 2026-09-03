
import { renderDashboard } from './views/dashboard.js';
import { renderStocks } from './views/stocks.js';
import { renderOpportunities } from './views/opportunities.js';
import { renderIPOs } from './views/ipo.js';
import { renderPortfolio } from './views/portfolio.js';
import { renderRiskSafety } from './views/risk.js';
import { renderSystem } from './views/system.js';

const routes = [
    { id: 'dashboard', name: 'Dashboard', icon: 'layout-dashboard', render: renderDashboard },
    { id: 'stocks', name: 'Stocks', icon: 'line-chart', render: renderStocks },
    { id: 'opportunities', name: 'Opportunities', icon: 'zap', render: renderOpportunities },
    { id: 'ipos', name: 'IPOs', icon: 'rocket', render: renderIPOs },
    { id: 'portfolio', name: 'Portfolio & Trading', icon: 'briefcase', render: renderPortfolio },
    { id: 'risk', name: 'Risk & Safety', icon: 'shield-alert', render: renderRiskSafety },
    { id: 'system', name: 'System Architecture', icon: 'cpu', render: renderSystem }
];

let currentView = 'dashboard';

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
    window.navigateTo('dashboard');
});
