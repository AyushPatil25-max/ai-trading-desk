
export async function renderIPOs(container) {
    container.innerHTML = `
        <div class="flex justify-between items-center mb-6">
            <h2 class="text-xl font-bold text-white">IPO Intelligence</h2>
            <div class="flex bg-gray-900 border border-gray-800 rounded-lg p-1 text-sm">
                <button class="px-4 py-1.5 rounded-md bg-gray-800 text-white font-medium shadow">Open & Upcoming</button>
                <button class="px-4 py-1.5 rounded-md text-gray-400 hover:text-white">Listed</button>
            </div>
        </div>
        
        <div id="ipoGrid" class="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-6">
            <div class="col-span-full text-center py-12">
                <div class="animate-spin rounded-full h-8 w-8 border-b-2 border-cyan-400 mx-auto mb-4"></div>
                <div class="text-gray-500 text-sm">Loading IPO Data...</div>
            </div>
        </div>
        
        <!-- IPO Detail Modal Container -->
        <div id="ipoModal" class="fixed inset-0 bg-black/80 backdrop-blur-sm z-50 hidden flex items-center justify-center p-4">
            <div class="bg-gray-950 border border-gray-800 rounded-2xl w-full max-w-5xl h-[90vh] flex flex-col shadow-2xl overflow-hidden relative">
                <div class="absolute top-4 right-4 z-10">
                    <button onclick="document.getElementById('ipoModal').classList.add('hidden')" class="p-2 bg-gray-900 hover:bg-gray-800 rounded-full text-gray-400 hover:text-white transition">
                        <i data-lucide="x" class="w-5 h-5"></i>
                    </button>
                </div>
                <div id="ipoModalContent" class="flex-1 overflow-y-auto p-8 scroll-smooth"></div>
            </div>
        </div>
    `;

    try {
        const res = await fetch('/api/ipo/list');
        const data = await res.json();
        
        const grid = document.getElementById('ipoGrid');
        
        if (!data || data.length === 0) {
            grid.innerHTML = '<div class="col-span-full p-8 text-center text-gray-500 border border-dashed border-gray-800 rounded-xl">No IPOs currently found.</div>';
            return;
        }

        grid.innerHTML = data.map(ipo => {
            const size = ipo.issue_size_crore ? `₹${ipo.issue_size_crore.toFixed(1)} Cr` : 'TBD';
            const price = ipo.issue_price ? `₹${ipo.issue_price}` : (ipo.price_band_high ? `₹${ipo.price_band_low}-₹${ipo.price_band_high}` : 'TBD');
            const gmp = ipo.latest_gmp ? `₹${ipo.latest_gmp.gmp_value} (${ipo.latest_gmp.gmp_percentage?.toFixed(1)}%)` : '--';
            const statusColor = ipo.status === 'OPEN' ? 'bg-emerald-900/50 text-emerald-400 border-emerald-800' : 'bg-gray-800 text-gray-300 border-gray-700';
            
            return `
                <div onclick="window.viewIpoDetail('${ipo.id}')" class="glass-panel rounded-xl p-5 hover:border-cyan-900/50 hover:shadow-[0_0_15px_-3px_rgba(6,182,212,0.15)] transition cursor-pointer group flex flex-col h-full">
                    <div class="flex justify-between items-start mb-3">
                        <div>
                            <h3 class="font-bold text-white text-lg group-hover:text-cyan-400 transition-colors line-clamp-1" title="${ipo.company_name}">${ipo.company_name}</h3>
                            <div class="text-xs text-gray-500 mt-0.5">${ipo.exchange} · ${ipo.ipo_type}</div>
                        </div>
                        <span class="px-2.5 py-0.5 rounded text-[10px] font-bold tracking-wider border ${statusColor}">${ipo.status}</span>
                    </div>
                    
                    <div class="grid grid-cols-2 gap-y-4 gap-x-2 mt-4 text-sm mb-6 flex-1">
                        <div>
                            <div class="text-gray-500 text-[10px] uppercase mb-0.5">Issue Size</div>
                            <div class="text-gray-200 font-medium">${size}</div>
                        </div>
                        <div>
                            <div class="text-gray-500 text-[10px] uppercase mb-0.5">Price</div>
                            <div class="text-gray-200 font-medium">${price}</div>
                        </div>
                        <div>
                            <div class="text-gray-500 text-[10px] uppercase mb-0.5">Grey Market</div>
                            <div class="text-emerald-400 font-medium">${gmp}</div>
                        </div>
                        <div>
                            <div class="text-gray-500 text-[10px] uppercase mb-0.5">Subscription</div>
                            <div class="text-gray-200 font-medium">${ipo.total_subscription ? ipo.total_subscription.toFixed(2) + 'x' : '--'}</div>
                        </div>
                    </div>
                    
                    <div class="border-t border-gray-800/60 pt-3 flex justify-between items-center">
                        <div class="text-xs text-gray-400"><span class="text-gray-600">Close:</span> ${ipo.close_date || 'TBD'}</div>
                        <div class="text-xs font-semibold text-cyan-500 group-hover:text-cyan-400">View Full Analysis &rarr;</div>
                    </div>
                </div>
            `;
        }).join('');
        lucide.createIcons();
    } catch (e) {
        document.getElementById('ipoGrid').innerHTML = '<div class="col-span-full text-rose-500 p-8 text-center">Failed to load IPO data.</div>';
    }

    window.viewIpoDetail = async (id) => {
        const modal = document.getElementById('ipoModal');
        const content = document.getElementById('ipoModalContent');
        modal.classList.remove('hidden');
        content.innerHTML = '<div class="flex items-center justify-center h-full"><div class="animate-spin rounded-full h-8 w-8 border-b-2 border-cyan-400"></div></div>';
        
        try {
            // Fetch Details and Analysis concurrently
            const [detailRes, analysisRes] = await Promise.all([
                fetch(`/api/ipo/${id}`).catch(()=>null),
                fetch(`/api/ipo/${id}/analysis`).catch(()=>null)
            ]);
            
            const detail = detailRes ? await detailRes.json() : null;
            const analysis = analysisRes && analysisRes.status === 200 ? await analysisRes.json() : null;
            
            if (!detail) {
                content.innerHTML = '<div class="text-center text-rose-400 py-12">Failed to load IPO details.</div>';
                return;
            }

            const size = detail.issue_size_crore ? `₹${detail.issue_size_crore.toFixed(1)} Cr` : 'TBD';
            const price = detail.issue_price ? `₹${detail.issue_price}` : (detail.price_band_high ? `₹${detail.price_band_low}-₹${detail.price_band_high}` : 'TBD');
            
            // Build Analysis section
            let analysisHtml = `<div class="p-6 text-center text-gray-500 border border-dashed border-gray-800 rounded-xl">Analysis pending or insufficient data.</div>`;
            
            if (analysis) {
                const vColors = {
                    'STRONG': 'bg-emerald-900/50 text-emerald-400 border-emerald-800',
                    'POSITIVE': 'bg-emerald-900/30 text-emerald-300 border-emerald-900',
                    'NEUTRAL': 'bg-yellow-900/30 text-yellow-300 border-yellow-900',
                    'WEAK': 'bg-rose-900/30 text-rose-400 border-rose-900',
                    'AVOID': 'bg-rose-900/50 text-rose-500 border-rose-800',
                    'INSUFFICIENT_DATA': 'bg-gray-800 text-gray-400 border-gray-700'
                };
                const vColor = vColors[analysis.verdict] || vColors['INSUFFICIENT_DATA'];

                analysisHtml = `
                    <div class="bg-gray-900/80 border border-gray-700/50 rounded-xl p-6 mb-8">
                        <div class="flex items-center justify-between mb-6">
                            <div class="flex items-center gap-4">
                                <div class="text-4xl font-black text-white">${analysis.overall_score}<span class="text-lg text-gray-500 font-normal">/100</span></div>
                                <div class="px-4 py-1.5 rounded-lg border font-bold text-sm tracking-wide ${vColor}">
                                    ${analysis.verdict}
                                </div>
                            </div>
                        </div>
                        
                        <div class="grid grid-cols-2 md:grid-cols-5 gap-4 mb-6">
                            <div class="bg-gray-950 p-3 rounded-lg border border-gray-800">
                                <div class="text-[10px] text-gray-500 uppercase mb-1">Fundamentals</div>
                                <div class="text-lg font-bold text-white">${analysis.fundamental_score}</div>
                            </div>
                            <div class="bg-gray-950 p-3 rounded-lg border border-gray-800">
                                <div class="text-[10px] text-gray-500 uppercase mb-1">Valuation</div>
                                <div class="text-lg font-bold text-white">${analysis.valuation_score}</div>
                            </div>
                            <div class="bg-gray-950 p-3 rounded-lg border border-gray-800">
                                <div class="text-[10px] text-gray-500 uppercase mb-1">Subscription</div>
                                <div class="text-lg font-bold text-white">${analysis.subscription_score}</div>
                            </div>
                            <div class="bg-gray-950 p-3 rounded-lg border border-gray-800 text-emerald-900/20">
                                <div class="text-[10px] text-emerald-500/70 uppercase mb-1 font-bold">GMP Sentiment</div>
                                <div class="text-lg font-bold text-emerald-400">${analysis.gmp_score}</div>
                            </div>
                            <div class="bg-gray-950 p-3 rounded-lg border border-gray-800">
                                <div class="text-[10px] text-gray-500 uppercase mb-1">Risk</div>
                                <div class="text-lg font-bold ${analysis.risk_score > 60 ? 'text-rose-400' : 'text-white'}">${analysis.risk_score}</div>
                            </div>
                        </div>
                        
                        <div>
                            <div class="text-xs text-gray-500 uppercase mb-2">Analysis Reasoning</div>
                            <ul class="space-y-2 text-sm">
                                ${(analysis.strengths || []).map(r => `<li class="flex gap-2 items-start"><i data-lucide="check-circle" class="w-4 h-4 text-emerald-500 shrink-0 mt-0.5"></i><span class="text-gray-300">${r}</span></li>`).join('')}
                                ${(analysis.weaknesses || []).map(r => `<li class="flex gap-2 items-start"><i data-lucide="minus-circle" class="w-4 h-4 text-amber-500 shrink-0 mt-0.5"></i><span class="text-gray-300">${r}</span></li>`).join('')}
                                ${(analysis.red_flags || []).map(r => `<li class="flex gap-2 items-start"><i data-lucide="alert-triangle" class="w-4 h-4 text-rose-500 shrink-0 mt-0.5"></i><span class="text-gray-300">${r}</span></li>`).join('')}
                                ${(analysis.warnings || []).map(r => `<li class="flex gap-2 items-start"><i data-lucide="info" class="w-4 h-4 text-cyan-500 shrink-0 mt-0.5"></i><span class="text-gray-300">${r}</span></li>`).join('')}
                            </ul>
                        </div>
                    </div>
                `;
            }

            content.innerHTML = `
                <div class="mb-8 border-b border-gray-800 pb-6">
                    <div class="flex items-center gap-3 mb-2">
                        <h2 class="text-3xl font-bold text-white tracking-tight">${detail.company_name}</h2>
                        <span class="px-2 py-1 bg-gray-800 rounded text-xs font-mono text-gray-400 border border-gray-700">${detail.status}</span>
                    </div>
                    <p class="text-gray-400 text-sm">${detail.exchange} · ${detail.ipo_type}</p>
                </div>

                <div class="mb-8">
                    <h3 class="text-sm font-bold text-white uppercase tracking-wider mb-4 border-b border-gray-800 pb-2">AI Assessment</h3>
                    ${analysisHtml}
                </div>

                <div class="grid grid-cols-1 md:grid-cols-2 gap-8 mb-8">
                    <div>
                        <h3 class="text-sm font-bold text-white uppercase tracking-wider mb-4 border-b border-gray-800 pb-2">Issue Details</h3>
                        <div class="space-y-3 text-sm">
                            <div class="flex justify-between border-b border-gray-800/50 pb-2">
                                <span class="text-gray-500">Issue Size</span>
                                <span class="text-gray-200">${size}</span>
                            </div>
                            <div class="flex justify-between border-b border-gray-800/50 pb-2">
                                <span class="text-gray-500">Price Band</span>
                                <span class="text-gray-200">${price}</span>
                            </div>
                            <div class="flex justify-between border-b border-gray-800/50 pb-2">
                                <span class="text-gray-500">Lot Size</span>
                                <span class="text-gray-200">${detail.market_lot || detail.lot_size || 'N/A'} shares</span>
                            </div>
                            <div class="flex justify-between border-b border-gray-800/50 pb-2">
                                <span class="text-gray-500 flex items-center gap-1">Min Investment</span>
                                <span class="text-gray-200">₹${detail.minimum_investment || 'N/A'}</span>
                            </div>
                            <div class="flex justify-between pb-2">
                                <span class="text-gray-500">Open - Close</span>
                                <span class="text-gray-200">${detail.open_date || 'N/A'} to ${detail.close_date || 'N/A'}</span>
                            </div>
                        </div>
                        
                        <div class="mt-4 text-[10px] text-gray-600">
                            <strong>Source:</strong> ${detail.source_name || 'Official'} 
                            | <strong>Data Quality:</strong> ${detail.data_quality_status || 'N/A'}
                        </div>
                    </div>
                    
                    <div>
                        <h3 class="text-sm font-bold text-white uppercase tracking-wider mb-4 border-b border-gray-800 pb-2 flex items-center justify-between">
                            <span>Market Sentiment (GMP)</span>
                            <span class="text-[9px] text-amber-500/70 border border-amber-900/50 px-1.5 py-0.5 rounded bg-amber-950/20 uppercase tracking-widest font-bold">Unofficial Data</span>
                        </h3>
                        <div class="bg-gray-900/50 border border-gray-800 rounded-lg p-4">
                            <div class="text-center mb-4">
                                <div class="text-3xl font-bold text-emerald-400">₹${detail.latest_gmp?.gmp_value || 'N/A'}</div>
                                <div class="text-sm text-emerald-500/70 mt-1 flex items-center justify-center gap-2">
                                    <span>Est. Premium: ${detail.latest_gmp?.gmp_percentage ? detail.latest_gmp.gmp_percentage.toFixed(1) + '%' : 'N/A'}</span>
                                    <span class="text-[9px] bg-emerald-900/40 border border-emerald-800 text-emerald-400 px-1 rounded uppercase tracking-widest font-bold">AI Estimate</span>
                                </div>
                            </div>
                            <div class="text-xs text-gray-500 text-center">
                                GMP is highly volatile market sentiment and does not guarantee listing gains. Evaluate fundamentals before investing.
                            </div>
                        </div>
                    </div>
                </div>
            `;
            lucide.createIcons();
        } catch (e) {
            content.innerHTML = '<div class="text-center text-rose-400 py-12">Error loading IPO details.</div>';
        }
    }
}
