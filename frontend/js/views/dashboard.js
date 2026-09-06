
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
        const res = await fetch('/api/v1/stream/health');
        const health = await res.json();
        
        const source = new EventSource('/api/v1/stream/market-data');
        const indices = { "NIFTY 50": null, "SENSEX": null };
        
        const mState = document.getElementById('dashMarketState');
        
        const renderHealthState = (state, data) => {
            const subsList = (data.subscribed_instruments || []).slice(0, 5).join(', ');
            const subsMore = (data.subscribed_instruments || []).length > 5 ? ` +${data.subscribed_instruments.length - 5} more` : '';
            const subCount = data.subscription_count !== undefined ? data.subscription_count : (data.subscribed_instruments || []).length;
            const ticks = data.ticks_received || 0;
            const recons = data.reconnect_count || 0;

            if (state === 'LIVE') {
                mState.innerHTML = `
                    <div class="text-2xl font-bold text-emerald-400 mb-1 flex items-center gap-2">
                        <span class="w-2.5 h-2.5 rounded-full bg-emerald-400 animate-ping"></span> LIVE (Upstox)
                    </div>
                    <div class="text-xs text-gray-400 space-y-0.5 font-normal">
                        <div>Ticks: <span class="text-emerald-300 font-semibold">${ticks.toLocaleString()}</span> | Latency: ${data.last_tick_age_ms || 0} ms</div>
                        <div>Last: <span class="text-white font-mono">${data.last_tick_symbol || '--'}</span> (₹${data.last_tick_price || '--'})</div>
                        <div>Subscribed: ${subCount} instruments (${subsList}${subsMore})</div>
                    </div>
                `;
            } else if (state === 'SUBSCRIBED_NO_TICKS') {
                mState.innerHTML = `
                    <div class="text-xl font-bold text-amber-400 mb-1">SUBSCRIBED — WAITING FOR TICKS</div>
                    <div class="text-xs text-gray-400 space-y-0.5 font-normal">
                        <div>Status: WebSocket Connected | Zero ticks received</div>
                        <div>Subscribed: <span class="text-amber-200">${subCount} instruments</span> (${subsList}${subsMore})</div>
                        <div class="text-gray-500 italic">Feed active; awaits next exchange market session (09:15 IST).</div>
                    </div>
                `;
            } else if (state === 'CONNECTED_NO_SUBSCRIPTIONS' || state === 'CONNECTED') {
                mState.innerHTML = `
                    <div class="text-xl font-bold text-amber-400 mb-1">CONNECTED — NO SUBSCRIPTIONS</div>
                    <div class="text-xs text-gray-400 font-normal">WebSocket connected. Awaiting instrument subscription resolution.</div>
                `;
            } else if (state === 'STALE') {
                const sec = data.last_tick_age_ms ? Math.floor(data.last_tick_age_ms / 1000) : 10;
                mState.innerHTML = `
                    <div class="text-xl font-bold text-rose-400 mb-1">STALE — LAST TICK ${sec}s AGO</div>
                    <div class="text-xs text-gray-400 space-y-0.5 font-normal">
                        <div>Last: ${data.last_tick_symbol || '--'} | Ticks: ${ticks.toLocaleString()}</div>
                        <div>Reconnections: ${recons}</div>
                    </div>
                `;
            } else if (state === 'NOT_CONFIGURED') {
                mState.innerHTML = `
                    <div class="text-xl font-bold text-gray-400 mb-1">NOT CONFIGURED</div>
                    <div class="text-xs text-gray-500 font-normal">UPSTOX_ACCESS_TOKEN not configured in .env.</div>
                `;
            } else {
                mState.innerHTML = `
                    <div class="text-xl font-bold text-rose-400 mb-1">${state || 'DISCONNECTED'}</div>
                    <div class="text-xs text-gray-400 font-normal">Market feed disconnected. Reconnections: ${recons}</div>
                `;
            }
        };
        
        renderHealthState(health.connection_state, health);
        
        source.addEventListener('tick', (event) => {
            const data = JSON.parse(event.data);
            if (data.symbol === "NIFTY 50" || data.symbol === "SENSEX") {
                indices[data.symbol] = data;
            }
            
            // Re-render health state dynamically as live ticks arrive
            health.ticks_received = (health.ticks_received || 0) + 1;
            health.last_tick_age_ms = data.feed_latency_ms || 15;
            health.last_tick_symbol = data.symbol;
            health.last_tick_price = data.last_traded_price;
            renderHealthState('LIVE', health);
            
            let html = '';
            for (const sym of ["NIFTY 50", "SENSEX"]) {
                if (indices[sym]) {
                    const price = indices[sym].last_traded_price.toFixed(2);
                    html += `<div><span class="text-gray-500">${sym}:</span> <span class="text-emerald-400">${price}</span></div>`;
                }
            }
            if (html) {
                document.getElementById('dashIndices').innerHTML = html;
            }
        });

        source.onerror = () => {
            renderHealthState('STALE / DISCONNECTED', { reconnect_count: health.reconnect_count });
        };

        // Cleanup on navigate away
        window.activeEventSource = source;
    } catch (e) {
        document.getElementById('dashMarketState').innerText = 'ERROR';
    }
}
