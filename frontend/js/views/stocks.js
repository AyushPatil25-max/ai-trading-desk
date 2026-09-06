
export async function renderStocks(container) {
    container.innerHTML = `
        <div class="flex flex-col h-full gap-4">
            <div class="flex gap-4">
                <div class="flex-1 relative">
                    <i data-lucide="search" class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500"></i>
                    <input type="text" id="stockSearchInput" placeholder="Search by Symbol, Company Name, ISIN..." 
                           class="w-full bg-gray-900 border border-gray-700 rounded-lg py-2 pl-10 pr-4 text-sm text-white focus:outline-none focus:border-cyan-500 transition-colors">
                </div>
                <button id="btnSearchStocks" class="bg-cyan-900/50 hover:bg-cyan-800 text-cyan-100 border border-cyan-800 px-6 py-2 rounded-lg text-sm font-medium transition-colors">
                    Search
                </button>
            </div>
            
            <div class="grid grid-cols-1 md:grid-cols-4 gap-6 flex-1 min-h-0">
                <!-- Search Results List -->
                <div class="glass-panel rounded-xl border border-gray-800/60 overflow-hidden flex flex-col md:col-span-1">
                    <div class="p-3 border-b border-gray-800/60 bg-gray-900/50 font-semibold text-sm">Results</div>
                    <div id="stockResults" class="flex-1 overflow-y-auto p-2 space-y-1">
                        <div class="text-center p-4 text-xs text-gray-500">Enter a query to search.</div>
                    </div>
                </div>
                
                <!-- Stock Detail Panel -->
                <div class="glass-panel rounded-xl border border-gray-800/60 overflow-hidden flex flex-col md:col-span-3">
                    <div id="stockDetailContent" class="flex-1 overflow-y-auto p-6 flex flex-col items-center justify-center text-gray-500">
                        <i data-lucide="line-chart" class="w-12 h-12 mb-4 text-gray-700"></i>
                        <p>Select a stock to view detailed intelligence</p>
                    </div>
                </div>
            </div>
        </div>
    `;

    document.getElementById('btnSearchStocks').addEventListener('click', async () => {
        const query = document.getElementById('stockSearchInput').value;
        if (!query) return;
        const resDiv = document.getElementById('stockResults');
        resDiv.innerHTML = '<div class="text-center p-4 text-xs text-cyan-500">Searching...</div>';
        
        try {
            const res = await fetch(`/api/v1/stocks/search?query=${encodeURIComponent(query)}&limit=15`);
            const data = await res.json();
            
            if (!data || data.length === 0) {
                resDiv.innerHTML = '<div class="text-center p-4 text-xs text-gray-500">No results found.</div>';
                return;
            }
            
            resDiv.innerHTML = data.map(s => `
                <button onclick="window.loadStockDetail('${s.canonical_symbol}')" class="w-full text-left p-3 rounded-lg hover:bg-gray-800 transition-colors border border-transparent hover:border-gray-700 group">
                    <div class="flex justify-between items-start mb-1">
                        <span class="font-bold text-white group-hover:text-cyan-400">${s.canonical_symbol}</span>
                        <span class="text-[10px] bg-gray-800 px-1.5 py-0.5 rounded text-gray-400">${s.exchange}</span>
                    </div>
                    <div class="text-xs text-gray-400 truncate">${s.company_name}</div>
                </button>
            `).join('');
        } catch (e) {
            resDiv.innerHTML = '<div class="text-center p-4 text-xs text-rose-500">Search failed.</div>';
        }
    });

    window.loadStockDetail = async (symbol) => {
        const container = document.getElementById('stockDetailContent');
        container.innerHTML = `<div class="flex flex-col items-center justify-center h-full"><div class="animate-spin rounded-full h-8 w-8 border-b-2 border-cyan-400 mb-4"></div><p class="text-sm text-cyan-400">Loading comprehensive analysis for ${symbol}...</p></div>`;
        
        try {
            const [resA, resF, resT] = await Promise.all([
                fetch(`/api/v1/stocks/${symbol}/analysis`),
                fetch(`/api/v1/stocks/${symbol}/fundamentals`),
                fetch(`/api/v1/stocks/${symbol}/technicals`)
            ]);
            
            if (resA.status !== 200) {
                container.innerHTML = `<div class="p-6 text-center text-rose-400">Analysis unavailable.</div>`;
                return;
            }
            const data = await resA.json();
            const fund = resF.status === 200 ? await resF.json() : null;
            const tech = resT.status === 200 ? await resT.json() : null;
            
            data.fundamental_data = fund || data.fundamental_data;
            data.technical_data = tech || data.technical_data;

            const verdict = (data.verdict || data.decision || 'INSUFFICIENT_DATA').toString().toUpperCase();
            const confScore = data.confidence_score !== undefined && data.confidence_score !== null ? data.confidence_score : Math.round((data.confidence || 0) * 100);

            // Map verdict colors per Phase 4
            const vColors = {
                'BULLISH': 'bg-emerald-900/50 text-emerald-400 border-emerald-800',
                'BEARISH': 'bg-rose-900/50 text-rose-400 border-rose-800',
                'HOLD': 'bg-yellow-900/30 text-yellow-300 border-yellow-900',
                'REJECT': 'bg-red-950 text-red-400 border-red-800',
                'INSUFFICIENT_DATA': 'bg-gray-800 text-gray-400 border-gray-700'
            };
            const vColor = vColors[verdict] || vColors['INSUFFICIENT_DATA'];

            container.innerHTML = `
                <!-- Header -->
                <div class="flex justify-between items-start mb-6">
                    <div>
                        <div class="flex items-center gap-3 mb-1">
                            <h2 class="text-3xl font-bold text-white tracking-tight">${data.symbol}</h2>
                            <span class="px-2 py-1 bg-gray-800 rounded text-xs font-mono text-gray-400 border border-gray-700">${data.fundamental_data?.sector || 'NSE Equity'}</span>
                        </div>
                        <p class="text-gray-400">${data.company_name || data.fundamental_data?.company_name || symbol}</p>
                    </div>
                    <div class="text-right">
                        <div class="text-2xl font-bold text-white mb-1">${data.technical_data?.current_price ? '₹' + data.technical_data.current_price : '₹ --'}</div>
                        <div class="text-sm ${data.technical_data?.daily_return > 0 ? 'text-emerald-400' : (data.technical_data?.daily_return < 0 ? 'text-rose-400' : 'text-gray-400')}">
                            ${data.technical_data?.daily_return !== null && data.technical_data?.daily_return !== undefined ? (data.technical_data.daily_return > 0 ? '+' : '') + (data.technical_data.daily_return * 100).toFixed(2) + '%' : 'Outside Trading Hours'}
                        </div>
                    </div>
                </div>

                <!-- Status Banner if Insufficient Data -->
                ${verdict === 'INSUFFICIENT_DATA' ? `
                <div class="bg-amber-950/40 border border-amber-800/60 rounded-xl p-4 mb-6 flex items-start gap-3">
                    <i data-lucide="info" class="w-5 h-5 text-amber-400 shrink-0 mt-0.5"></i>
                    <div class="text-xs text-amber-200/90 leading-relaxed">
                        <span class="font-semibold text-amber-400">DATA STATUS: INSUFFICIENT DATA</span> — Real-time tick stream requires active NSE trading hours (09:15–15:30 IST) or live ticks on the Upstox WebSocket feed. Deterministic technical analysis will calculate dynamically when live market quotes arrive.
                    </div>
                </div>
                ` : ''}

                <!-- AI Assessment Card -->
                <div class="bg-gray-900/80 border border-gray-700/50 rounded-xl p-5 mb-8">
                    <div class="text-xs font-bold text-gray-500 uppercase tracking-wider mb-4 border-b border-gray-800 pb-2 flex justify-between">
                        <span>Evidence-Based Assessment</span>
                        <span class="text-gray-400 font-mono">Source: ${data.data_source || 'Upstox'} | State: ${data.data_status || 'FRESH'}</span>
                    </div>
                    
                    <div class="flex items-center justify-between mb-6">
                        <div class="flex items-center gap-4">
                            <div class="text-4xl font-black text-white">${data.overall_score}<span class="text-lg text-gray-500 font-normal">/100</span></div>
                            <div class="px-4 py-1.5 rounded-lg border font-bold text-sm tracking-wide ${vColor}">
                                ${verdict.replace(/_/g, ' ')}
                            </div>
                        </div>
                        <div class="text-right">
                            <div class="text-xs text-gray-500 mb-1">Confidence</div>
                            <div class="text-sm font-semibold text-white">${confScore}%</div>
                        </div>
                    </div>
                    
                    <div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
                        <div class="bg-gray-950 p-3 rounded-lg border border-gray-800">
                            <div class="text-[10px] text-gray-500 uppercase mb-1">Fundamentals</div>
                            <div class="text-lg font-bold ${data.fundamental_score > 70 ? 'text-emerald-400' : 'text-white'}">${data.fundamental_score}</div>
                        </div>
                        <div class="bg-gray-950 p-3 rounded-lg border border-gray-800">
                            <div class="text-[10px] text-gray-500 uppercase mb-1">Valuation</div>
                            <div class="text-lg font-bold ${data.valuation_score > 70 ? 'text-emerald-400' : 'text-white'}">${data.valuation_score}</div>
                        </div>
                        <div class="bg-gray-950 p-3 rounded-lg border border-gray-800">
                            <div class="text-[10px] text-gray-500 uppercase mb-1">Technical</div>
                            <div class="text-lg font-bold ${data.technical_score > 70 ? 'text-emerald-400' : 'text-white'}">${data.technical_score}</div>
                        </div>
                        <div class="bg-gray-950 p-3 rounded-lg border border-gray-800">
                            <div class="text-[10px] text-gray-500 uppercase mb-1">Risk Condition</div>
                            <div class="text-lg font-bold ${data.risk_score < 40 ? 'text-emerald-400' : 'text-amber-400'}">${data.risk_score}</div>
                        </div>
                    </div>
                    
                    <div>
                        <div class="text-xs text-gray-500 uppercase mb-2">Analysis Summary</div>
                        <ul class="space-y-1.5 text-sm">
                            ${(data.positive_factors || []).map(r => `<li class="flex gap-2 items-start"><i data-lucide="check-circle" class="w-4 h-4 text-emerald-500 shrink-0 mt-0.5"></i><span class="text-gray-300">${r}</span></li>`).join('')}
                            ${(data.negative_factors || []).map(r => `<li class="flex gap-2 items-start"><i data-lucide="minus-circle" class="w-4 h-4 text-amber-500 shrink-0 mt-0.5"></i><span class="text-gray-300">${r}</span></li>`).join('')}
                            ${(data.risk_warnings || []).map(r => `<li class="flex gap-2 items-start"><i data-lucide="alert-triangle" class="w-4 h-4 text-rose-500 shrink-0 mt-0.5"></i><span class="text-gray-300">${r}</span></li>`).join('')}
                        </ul>
                    </div>
                </div>

                <!-- Tabs (Fundamentals, Technicals, Valuation) -->
                <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
                    <!-- Key Metrics -->
                    <div class="border border-gray-800/60 rounded-xl p-5">
                        <h3 class="text-sm font-semibold text-white mb-4">Key Fundamentals</h3>
                        <div class="space-y-3 text-sm">
                            <div class="flex justify-between border-b border-gray-800/50 pb-2">
                                <span class="text-gray-500">Market Cap</span>
                                <span class="text-gray-200">₹${(data.fundamental_data?.market_cap / 1e7).toFixed(2)} Cr</span>
                            </div>
                            <div class="flex justify-between border-b border-gray-800/50 pb-2">
                                <span class="text-gray-500">P/E Ratio</span>
                                <span class="text-gray-200">${data.fundamental_data?.pe_ratio || '--'}</span>
                            </div>
                            <div class="flex justify-between border-b border-gray-800/50 pb-2">
                                <span class="text-gray-500">P/B Ratio</span>
                                <span class="text-gray-200">${data.fundamental_data?.pb_ratio || '--'}</span>
                            </div>
                            <div class="flex justify-between border-b border-gray-800/50 pb-2">
                                <span class="text-gray-500">ROE</span>
                                <span class="text-gray-200">${data.fundamental_data?.roe ? (data.fundamental_data.roe * 100).toFixed(2) + '%' : '--'}</span>
                            </div>
                            <div class="flex justify-between pb-2">
                                <span class="text-gray-500">Debt to Equity</span>
                                <span class="text-gray-200">${data.fundamental_data?.debt_to_equity || '--'}</span>
                            </div>
                        </div>
                    </div>
                    
                    <!-- Technicals -->
                    <div class="border border-gray-800/60 rounded-xl p-5">
                        <h3 class="text-sm font-semibold text-white mb-4">Technicals & Momentum</h3>
                        <div class="space-y-3 text-sm">
                            <div class="flex justify-between border-b border-gray-800/50 pb-2">
                                <span class="text-gray-500">52W High</span>
                                <span class="text-gray-200">₹${data.technical_data?.high_52w || '--'}</span>
                            </div>
                            <div class="flex justify-between border-b border-gray-800/50 pb-2">
                                <span class="text-gray-500">52W Low</span>
                                <span class="text-gray-200">₹${data.technical_data?.low_52w || '--'}</span>
                            </div>
                            <div class="flex justify-between border-b border-gray-800/50 pb-2">
                                <span class="text-gray-500">RSI (14)</span>
                                <span class="text-gray-200">${data.technical_data?.rsi_14 || '--'}</span>
                            </div>
                            <div class="flex justify-between border-b border-gray-800/50 pb-2">
                                <span class="text-gray-500">Trend</span>
                                <span class="text-gray-200 uppercase">${data.technical_data?.trend || '--'}</span>
                            </div>
                        </div>
                    </div>
                </div>
            `;
            lucide.createIcons();
        } catch (e) {
            console.error("Stock analysis load failure for " + symbol, e);
            container.innerHTML = `
                <div class="p-8 text-center flex flex-col items-center justify-center">
                    <i data-lucide="alert-circle" class="w-10 h-10 text-rose-400 mb-3"></i>
                    <div class="text-white font-semibold mb-1">Analysis Query Failed</div>
                    <div class="text-xs text-rose-300 font-mono mb-4">${e.message || 'Network or schema failure'}</div>
                    <p class="text-xs text-gray-500 max-w-md">Verify backend connection or try searching for another canonical equity symbol.</p>
                </div>
            `;
            if (window.lucide) lucide.createIcons();
        }
    };
}
