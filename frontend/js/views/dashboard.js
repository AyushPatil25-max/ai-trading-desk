
export async function renderDashboard(container) {
    container.innerHTML = `
        <div class="grid grid-cols-1 md:grid-cols-3 gap-6 mb-6">
            <div class="glass-panel rounded-xl p-5" id="marketStatusCard">
                <div class="text-gray-400 text-xs font-semibold mb-1 uppercase">Market Status</div>
                <div class="text-2xl font-bold text-white mb-2" id="dashMarketState">LOADING...</div>
                <div class="flex gap-4 text-sm" id="dashIndices">
                </div>
            </div>
            <div class="glass-panel rounded-xl p-5">
                <div class="text-gray-400 text-xs font-semibold mb-1 uppercase">AI Market Summary</div>
                <div class="text-sm text-gray-300 leading-relaxed">
                    <span class="text-cyan-400 font-semibold">BULLISH BIAS:</span> 
                    Strong momentum detected in Financials and IT. Quality factors outperforming. Risk levels moderate. 
                </div>
            </div>
            <div class="glass-panel rounded-xl p-5 border border-amber-900/50 relative overflow-hidden">
                <div class="absolute inset-0 bg-amber-900/10"></div>
                <div class="relative z-10">
                    <div class="text-amber-400/80 text-xs font-bold mb-1 uppercase flex items-center gap-2">
                        <i data-lucide="shield-alert" class="w-3 h-3"></i> Trading Status
                    </div>
                    <div class="text-xl font-bold text-white mb-1">PAPER TRADING</div>
                    <div class="text-xs text-gray-400 font-mono">Live Execution Gate: LOCKED</div>
                </div>
            </div>
        </div>

        <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <div class="glass-panel rounded-xl p-5 flex flex-col">
                <div class="flex items-center justify-between mb-4">
                    <h3 class="font-semibold text-white">Top Opportunities</h3>
                    <button onclick="window.navigateTo('opportunities')" class="text-xs text-cyan-400 hover:text-cyan-300">View All</button>
                </div>
                <div class="flex-1 flex items-center justify-center text-sm text-gray-500 border border-dashed border-gray-800 rounded-lg p-6">
                    <button onclick="window.navigateTo('opportunities')" class="px-4 py-2 bg-gray-800 rounded hover:bg-gray-700 text-gray-300">Run Scan</button>
                </div>
            </div>
            
            <div class="glass-panel rounded-xl p-5 flex flex-col">
                <div class="flex items-center justify-between mb-4">
                    <h3 class="font-semibold text-white">Upcoming & Open IPOs</h3>
                    <button onclick="window.navigateTo('ipos')" class="text-xs text-cyan-400 hover:text-cyan-300">View All</button>
                </div>
                <div class="flex-1 flex items-center justify-center text-sm text-gray-500 border border-dashed border-gray-800 rounded-lg p-6">
                    Loading IPO Intelligence...
                </div>
            </div>
        </div>
    `;

    try {
        const res = await fetch('/api/v1/stocks/market/status');
        const data = await res.json();
        if (data.status === 'OPEN' || data.status === 'CLOSED') {
            document.getElementById('dashMarketState').innerText = data.status;
            const nColor = data.nifty.pct >= 0 ? 'text-emerald-400' : 'text-rose-400';
            const sColor = data.sensex.pct >= 0 ? 'text-emerald-400' : 'text-rose-400';
            
            document.getElementById('dashIndices').innerHTML = `
                <div><span class="text-gray-500">NIFTY:</span> <span class="${nColor}">${data.nifty.price.toFixed(2)} (${data.nifty.pct > 0 ? '+' : ''}${data.nifty.pct.toFixed(2)}%)</span></div>
                <div><span class="text-gray-500">SENSEX:</span> <span class="${sColor}">${data.sensex.price.toFixed(2)} (${data.sensex.pct > 0 ? '+' : ''}${data.sensex.pct.toFixed(2)}%)</span></div>
            `;
        } else {
            document.getElementById('dashMarketState').innerText = 'UNAVAILABLE';
            document.getElementById('dashIndices').innerHTML = `<div class="text-rose-400">Failed to fetch index data</div>`;
        }
    } catch (e) {
        document.getElementById('dashMarketState').innerText = 'ERROR';
    }
}
