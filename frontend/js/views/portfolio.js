export function renderPortfolio(container) {
    container.innerHTML = `
        <div class="flex flex-col h-full space-y-4 overflow-y-auto pb-8">
            <div class="glass-panel p-4 rounded-xl border border-gray-800/60 flex justify-between items-center">
                <h1 class="text-lg font-semibold text-white">Portfolio Intelligence</h1>
                <div class="flex gap-2 items-center">
                    <span id="portfolio-state" class="px-2 py-1 rounded text-xs font-mono bg-gray-800 text-gray-400">LOADING</span>
                    <button id="portfolio-refresh-btn" class="bg-cyan-600 hover:bg-cyan-700 text-white px-3 py-1.5 rounded text-sm font-medium transition-colors">Refresh</button>
                </div>
            </div>

            <!-- Top Summary Cards -->
            <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
                <div class="glass-panel p-4 rounded-xl border border-gray-800/60">
                    <div class="text-sm text-gray-400">Portfolio Value</div>
                    <div id="port-value" class="text-xl font-bold text-white">₹--</div>
                </div>
                <div class="glass-panel p-4 rounded-xl border border-gray-800/60">
                    <div class="text-sm text-gray-400">Invested</div>
                    <div id="port-invested" class="text-xl font-bold text-white">₹--</div>
                </div>
                <div class="glass-panel p-4 rounded-xl border border-gray-800/60">
                    <div class="text-sm text-gray-400">Unrealized P&L</div>
                    <div id="port-pnl" class="text-xl font-bold text-white">₹--</div>
                </div>
                <div class="glass-panel p-4 rounded-xl border border-gray-800/60">
                    <div class="text-sm text-gray-400">Available Cash</div>
                    <div id="port-cash" class="text-xl font-bold text-white">₹--</div>
                </div>
            </div>

            <div class="grid grid-cols-1 lg:grid-cols-3 gap-4">
                <!-- Holdings Table -->
                <div class="lg:col-span-2 glass-panel rounded-xl border border-gray-800/60 flex flex-col">
                    <div class="p-4 border-b border-gray-800/60 bg-gray-900/50">
                        <h2 class="text-sm font-semibold text-gray-200">Holdings & Positions</h2>
                    </div>
                    <div class="overflow-x-auto">
                        <table class="w-full text-left border-collapse">
                            <thead>
                                <tr class="text-xs text-gray-500 border-b border-gray-800/60">
                                    <th class="p-3 font-medium">Symbol</th>
                                    <th class="p-3 font-medium text-right">Qty</th>
                                    <th class="p-3 font-medium text-right">Avg Price</th>
                                    <th class="p-3 font-medium text-right">LTP</th>
                                    <th class="p-3 font-medium text-right">Value</th>
                                    <th class="p-3 font-medium text-right">P&L</th>
                                </tr>
                            </thead>
                            <tbody id="portfolio-holdings-body" class="text-sm">
                                <tr><td colspan="6" class="text-center p-4 text-gray-500">Loading...</td></tr>
                            </tbody>
                        </table>
                    </div>
                </div>

                <!-- AI Analysis -->
                <div class="glass-panel rounded-xl border border-gray-800/60 flex flex-col">
                    <div class="p-4 border-b border-gray-800/60 bg-gray-900/50 flex justify-between">
                        <h2 class="text-sm font-semibold text-gray-200">AI Portfolio Insight</h2>
                    </div>
                    <div id="portfolio-ai-body" class="p-4 space-y-4 text-sm">
                        <div class="text-center text-gray-500">Loading AI Analysis...</div>
                    </div>
                </div>
            </div>
        </div>
    `;

    document.getElementById('portfolio-refresh-btn').addEventListener('click', loadPortfolio);

    function formatCurrency(val) {
        if (val === null || val === undefined) return 'UNAVAILABLE';
        return '₹' + val.toLocaleString('en-IN', { maximumFractionDigits: 2 });
    }

    function formatNumber(val) {
        if (val === null || val === undefined) return '-';
        return val.toLocaleString('en-IN', { maximumFractionDigits: 2 });
    }

    function escapeHTML(str) {
        if (!str) return '';
        const div = document.createElement('div');
        div.appendChild(document.createTextNode(str));
        return div.innerHTML;
    }

    async function loadPortfolio() {
        try {
            const res = await fetch('/api/v1/portfolio');
            const payload = await res.json();
            const stateLabel = document.getElementById('portfolio-state');
            stateLabel.textContent = escapeHTML(payload.state);
            
            if (payload.state === 'UNAVAILABLE' || payload.state === 'ERROR') {
                stateLabel.className = 'px-2 py-1 rounded text-xs font-mono bg-red-900/50 text-red-400';
            } else if (payload.state === 'PARTIAL' || payload.state === 'STALE') {
                stateLabel.className = 'px-2 py-1 rounded text-xs font-mono bg-yellow-900/50 text-yellow-400';
            } else {
                stateLabel.className = 'px-2 py-1 rounded text-xs font-mono bg-emerald-900/50 text-emerald-400';
            }

            const data = payload.data;
            if (data) {
                const acc = data.account_state || {};
                document.getElementById('port-value').textContent = formatCurrency(acc.net_portfolio_value);
                document.getElementById('port-invested').textContent = formatCurrency(acc.total_invested_value);
                
                const pnlEl = document.getElementById('port-pnl');
                pnlEl.textContent = formatCurrency(acc.unrealized_pnl);
                pnlEl.className = 'text-xl font-bold ' + (acc.unrealized_pnl >= 0 ? 'text-emerald-400' : 'text-red-400');
                
                document.getElementById('port-cash').textContent = formatCurrency(acc.cash);

                // Holdings table
                const tbody = document.getElementById('portfolio-holdings-body');
                let hHtml = '';
                const items = [...(data.holdings || []), ...(data.positions || [])];
                
                if (items.length === 0) {
                    hHtml = '<tr><td colspan="6" class="text-center p-4 text-gray-500">No holdings or positions found.</td></tr>';
                } else {
                    items.forEach(h => {
                        const pnlColor = h.unrealized_pnl >= 0 ? 'text-emerald-400' : 'text-red-400';
                        hHtml += `
                            <tr class="border-b border-gray-800/30 hover:bg-gray-800/20 transition-colors">
                                <td class="p-3 font-semibold text-gray-200">${escapeHTML(h.symbol)}</td>
                                <td class="p-3 text-right text-gray-300">${formatNumber(h.quantity)}</td>
                                <td class="p-3 text-right text-gray-400">${formatCurrency(h.average_price)}</td>
                                <td class="p-3 text-right text-white">${formatCurrency(h.current_price)}</td>
                                <td class="p-3 text-right text-gray-300">${formatCurrency(h.current_value)}</td>
                                <td class="p-3 text-right font-medium ${pnlColor}">${formatCurrency(h.unrealized_pnl)}</td>
                            </tr>
                        `;
                    });
                }
                tbody.innerHTML = hHtml;
            } else {
                document.getElementById('portfolio-holdings-body').innerHTML = '<tr><td colspan="6" class="text-center p-4 text-red-500">Data Unavailable</td></tr>';
            }

            loadAI();
        } catch (e) {
            console.error(e);
            document.getElementById('portfolio-state').textContent = 'ERROR';
        }
    }

    async function loadAI() {
        try {
            const res = await fetch('/api/v1/portfolio/ai-analysis');
            if (!res.ok) {
                document.getElementById('portfolio-ai-body').innerHTML = '<div class="text-red-400">AI Analysis Unavailable</div>';
                return;
            }
            const ai = await res.json();
            let html = `
                <div class="mb-3">
                    <div class="text-xs text-gray-500 uppercase tracking-wider mb-1">Overall Assessment</div>
                    <div class="text-gray-200">${escapeHTML(ai.overall_assessment)}</div>
                </div>
                <div class="mb-3">
                    <div class="text-xs text-gray-500 uppercase tracking-wider mb-1">Summary</div>
                    <div class="text-gray-300">${escapeHTML(ai.summary)}</div>
                </div>
            `;
            if (ai.concentration_warnings && ai.concentration_warnings.length > 0) {
                html += `
                    <div class="mb-3">
                        <div class="text-xs text-orange-500 uppercase tracking-wider mb-1">Concentration Warnings</div>
                        <ul class="list-disc pl-4 text-orange-400">
                            ${ai.concentration_warnings.map(w => `<li>${escapeHTML(w)}</li>`).join('')}
                        </ul>
                    </div>
                `;
            }
            html += `<div class="mt-4 text-[10px] text-gray-500">Confidence: ${escapeHTML(ai.confidence)} | Method: ${escapeHTML(ai.methodology)}</div>`;
            document.getElementById('portfolio-ai-body').innerHTML = html;
        } catch (e) {
            console.error(e);
            document.getElementById('portfolio-ai-body').innerHTML = '<div class="text-red-400">AI Analysis Error</div>';
        }
    }

    loadPortfolio();
}
