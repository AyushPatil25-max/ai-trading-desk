
export async function renderOpportunities(container) {
    container.innerHTML = `
        <div class="flex justify-between items-center mb-6">
            <h2 class="text-xl font-bold text-white">AI Opportunities Screener</h2>
            <button onclick="window.runScreener()" class="bg-cyan-900/50 hover:bg-cyan-800 text-cyan-100 border border-cyan-800 px-4 py-1.5 rounded-lg text-sm font-medium transition-colors">
                Run Scan
            </button>
        </div>
        
        <div class="bg-gray-900 border border-gray-800 rounded-xl p-4 mb-6">
            <h3 class="text-sm font-semibold text-gray-300 mb-2">Strong Fundamentals + Undervalued</h3>
            <p class="text-xs text-gray-500 mb-4">
                Identifies companies with healthy profitability, acceptable debt, acceptable earnings quality, 
                and reasonable valuation below historical/sector references.
            </p>
            <div id="screenerResults" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                <div class="col-span-full text-center py-8 text-gray-500 text-sm border border-dashed border-gray-800 rounded-lg">
                    Click "Run Scan" to find opportunities.
                </div>
            </div>
        </div>
    `;

    window.runScreener = async () => {
        const resDiv = document.getElementById('screenerResults');
        resDiv.innerHTML = '<div class="col-span-full py-12 text-center text-cyan-500 text-sm"><div class="animate-spin rounded-full h-6 w-6 border-b-2 border-cyan-400 mx-auto mb-3"></div>Scanning 500+ NSE/BSE securities...</div>';
        
        try {
            const res = await fetch('/api/v1/stocks/screener/undervalued?limit=12');
            const data = await res.json();
            
            if (!data || data.length === 0) {
                resDiv.innerHTML = `
                    <div class="col-span-full py-10 px-6 text-center border border-dashed border-gray-800 rounded-xl bg-gray-950/40">
                        <div class="text-amber-400 font-semibold text-sm mb-1">NO DATA / INSUFFICIENT DATA AVAILABLE</div>
                        <p class="text-xs text-gray-500 max-w-lg mx-auto leading-relaxed">
                            Generating legitimate opportunity setups requires real-time live market ticks from the active Upstox feed and full quarterly statements. No synthetic or fake opportunities are generated.
                        </p>
                    </div>
                `;
                return;
            }

            resDiv.innerHTML = data.map(item => `
                <div class="glass-panel p-4 rounded-lg border border-emerald-900/30 hover:border-emerald-700/50 transition flex flex-col h-full">
                    <div class="flex justify-between items-start mb-2">
                        <h4 class="font-bold text-white">${item.symbol}</h4>
                        <span class="px-2 py-0.5 bg-emerald-900/30 text-emerald-400 border border-emerald-800 rounded text-[10px] font-bold">SCORE: ${item.overall_score}</span>
                    </div>
                    <div class="text-xs text-gray-500 mb-4">${item.company_name}</div>
                    
                    <div class="grid grid-cols-2 gap-2 text-xs mb-4 flex-1">
                        <div>
                            <div class="text-gray-600">P/E Ratio</div>
                            <div class="text-gray-300 font-medium">${item.pe_ratio || '--'}</div>
                        </div>
                        <div>
                            <div class="text-gray-600">ROE</div>
                            <div class="text-gray-300 font-medium">${item.roe ? (item.roe*100).toFixed(1)+'%' : '--'}</div>
                        </div>
                        <div class="col-span-2 mt-2">
                            <div class="text-gray-600 mb-1">AI Thesis</div>
                            <div class="text-gray-400 italic line-clamp-2">${item.thesis || 'Strong fundamentals with attractive valuation.'}</div>
                        </div>
                    </div>
                    
                    <button onclick="window.navigateTo('stocks'); setTimeout(()=> { document.getElementById('stockSearchInput').value='${item.symbol}'; document.getElementById('btnSearchStocks').click(); }, 100);" class="w-full py-1.5 text-xs text-center border border-gray-700 rounded text-gray-400 hover:text-white hover:bg-gray-800 transition">View Details</button>
                </div>
            `).join('');
        } catch(e) {
            resDiv.innerHTML = '<div class="col-span-full text-center py-8 text-rose-500 text-sm">Scan failed or backend endpoint unavailable.</div>';
        }
    };
}
