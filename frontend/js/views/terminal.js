export function renderTerminal(container) {
    container.innerHTML = `
        <div class="h-full flex flex-col gap-4">
            <!-- Top Section: Market Overview & Symbol Header -->
            <div class="flex gap-4 shrink-0">
                <div class="flex-1 glass-panel p-4 rounded-xl border border-gray-800/60 flex items-center justify-between">
                    <div>
                        <h1 class="text-xl font-bold text-white" id="term-symbol">RELIANCE</h1>
                        <div class="text-xs text-gray-400" id="term-company">NSE</div>
                    </div>
                    <div class="text-right">
                        <div class="text-2xl font-bold text-emerald-400" id="term-ltp">₹--</div>
                        <div class="text-sm text-emerald-400" id="term-change">-- (--)</div>
                    </div>
                </div>
                
                <div class="w-80 glass-panel p-4 rounded-xl border border-gray-800/60 flex flex-col justify-center">
                    <div class="text-xs text-gray-500 mb-1">Market Overview</div>
                    <div class="flex justify-between text-sm">
                        <span class="text-gray-400">NIFTY 50:</span>
                        <span id="mo-nifty" class="text-white">--</span>
                    </div>
                    <div class="flex justify-between text-sm">
                        <span class="text-gray-400">SENSEX:</span>
                        <span id="mo-banknifty" class="text-white">--</span>
                    </div>
                </div>
            </div>
            
            <!-- Middle Section: Chart & Order Panel -->
            <div class="flex-1 flex gap-4 min-h-[400px]">
                <!-- Chart Area -->
                <div class="flex-[3] glass-panel rounded-xl border border-gray-800/60 flex flex-col">
                    <div class="p-3 border-b border-gray-800/60 flex justify-between items-center bg-gray-900/50">
                        <h2 class="text-sm font-semibold text-gray-200">Chart</h2>
                    </div>
                    <div id="term-chart-container" class="flex-1 bg-[#030712] relative overflow-hidden">
                        <div class="absolute inset-0 flex items-center justify-center text-gray-500 text-sm">
                            Chart visualization loading...
                        </div>
                    </div>
                </div>
                
                <!-- Right Side: Order Panel & Market Depth -->
                <div class="flex-[1] flex flex-col gap-4 min-w-[300px]">
                    <!-- Market Depth -->
                    <div class="glass-panel rounded-xl border border-gray-800/60 flex flex-col shrink-0">
                        <div class="p-3 border-b border-gray-800/60 flex justify-between items-center bg-gray-900/50">
                            <h2 class="text-sm font-semibold text-gray-200">Market Depth</h2>
                            <span id="depth-status" class="text-[10px] bg-gray-800 text-gray-400 px-1.5 rounded">UNAVAILABLE</span>
                        </div>
                        <div class="p-2 flex-1 text-xs">
                            <table class="w-full text-center">
                                <thead>
                                    <tr class="text-gray-500 border-b border-gray-800/60">
                                        <th class="font-normal py-1">BID QTY</th>
                                        <th class="font-normal py-1">BID</th>
                                        <th class="font-normal py-1">ASK</th>
                                        <th class="font-normal py-1">ASK QTY</th>
                                    </tr>
                                </thead>
                                <tbody id="term-depth-body">
                                    <tr><td colspan="4" class="py-4 text-gray-500">Market depth unavailable for current data subscription.</td></tr>
                                </tbody>
                            </table>
                        </div>
                    </div>
                    
                    <!-- Order Panel -->
                    <div class="glass-panel rounded-xl border border-gray-800/60 flex flex-col flex-1">
                        <div class="p-3 border-b border-gray-800/60 bg-gray-900/50">
                            <h2 class="text-sm font-semibold text-gray-200">Order Entry</h2>
                        </div>
                        <div class="p-4 flex flex-col gap-3 text-sm">
                            <div class="flex gap-2">
                                <button id="btn-buy" class="flex-1 py-2 bg-emerald-600 hover:bg-emerald-500 text-white font-bold rounded" data-side="BUY">BUY</button>
                                <button id="btn-sell" class="flex-1 py-2 bg-red-600 hover:bg-red-500 text-white font-bold rounded opacity-50" data-side="SELL">SELL</button>
                            </div>
                            
                            <div class="grid grid-cols-2 gap-2 mt-2">
                                <div>
                                    <label class="text-xs text-gray-400">Qty</label>
                                    <input type="number" id="order-qty" value="1" min="1" class="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-white">
                                </div>
                                <div>
                                    <label class="text-xs text-gray-400">Price (Limit)</label>
                                    <input type="number" id="order-price" placeholder="MKT" min="0" step="0.05" class="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-white">
                                </div>
                            </div>
                            
                            <div class="flex justify-between items-center text-xs mt-2 text-gray-400">
                                <span>Product: CNC</span>
                                <span>Validity: DAY</span>
                            </div>
                            
                            <button id="btn-submit-order" class="w-full mt-auto py-2 bg-gray-700 text-white font-bold rounded opacity-50 cursor-not-allowed">
                                LIVE TRADING DISABLED
                            </button>
                            <div id="order-feedback" class="text-[10px] text-center mt-1"></div>
                        </div>
                    </div>
                </div>
            </div>
            
            <!-- Bottom Section: Positions / Orders -->
            <div class="h-48 glass-panel rounded-xl border border-gray-800/60 flex flex-col shrink-0">
                <div class="border-b border-gray-800/60 flex bg-gray-900/50 px-2 text-sm">
                    <button class="px-4 py-2 border-b-2 border-cyan-500 text-cyan-400 font-medium">Positions</button>
                    <button class="px-4 py-2 text-gray-400 hover:text-gray-200">Orders</button>
                </div>
                <div class="flex-1 overflow-y-auto">
                    <table class="w-full text-left text-sm">
                        <thead>
                            <tr class="text-xs text-gray-500 border-b border-gray-800/60 bg-gray-900/30">
                                <th class="p-2 font-medium">Symbol</th>
                                <th class="p-2 font-medium text-right">Qty</th>
                                <th class="p-2 font-medium text-right">Avg Price</th>
                                <th class="p-2 font-medium text-right">LTP</th>
                                <th class="p-2 font-medium text-right">P&L</th>
                            </tr>
                        </thead>
                        <tbody id="term-positions-body">
                            <tr><td colspan="5" class="text-center p-4 text-gray-500">Loading positions...</td></tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    `;

    // Order state
    let activeSide = 'BUY';
    const btnBuy = document.getElementById('btn-buy');
    const btnSell = document.getElementById('btn-sell');
    const btnSubmit = document.getElementById('btn-submit-order');
    const feedback = document.getElementById('order-feedback');
    const qtyInput = document.getElementById('order-qty');
    const priceInput = document.getElementById('order-price');

    btnBuy.addEventListener('click', () => {
        activeSide = 'BUY';
        btnBuy.classList.remove('opacity-50');
        btnSell.classList.add('opacity-50');
    });
    btnSell.addEventListener('click', () => {
        activeSide = 'SELL';
        btnSell.classList.remove('opacity-50');
        btnBuy.classList.add('opacity-50');
    });

    // Market Data Bus Subscription
    let isStale = true;
    let cleanup = null;
    if (window.marketDataBus) {
        cleanup = window.marketDataBus.subscribe((tick) => {
            const sym = document.getElementById('term-symbol').textContent;
            
            if (tick.symbol === "NIFTY 50") {
                const el = document.getElementById('mo-nifty');
                if (el) el.textContent = '₹' + tick.last_price;
            } else if (tick.symbol === "SENSEX") {
                const el = document.getElementById('mo-banknifty');
                if (el) el.textContent = '₹' + tick.last_price;
            }

            if (tick.symbol === sym) {
                const ltpEl = document.getElementById('term-ltp');
                const chgEl = document.getElementById('term-change');
                if (ltpEl && chgEl) {
                    ltpEl.textContent = '₹' + tick.last_price;
                    // Determine age
                    const ageMs = (new Date() - new Date(tick.source_timestamp || Date.now()));
                    isStale = ageMs > 10000;

                    if (isStale) {
                        ltpEl.className = 'text-2xl font-bold text-gray-500';
                        chgEl.textContent = 'STALE';
                    } else {
                        ltpEl.className = 'text-2xl font-bold text-emerald-400';
                        chgEl.textContent = 'LIVE';
                    }

                    // Disable live execution if stale
                    if (isStale) {
                        btnSubmit.disabled = true;
                        btnSubmit.textContent = 'DATA STALE';
                        btnSubmit.classList.add('opacity-50', 'cursor-not-allowed');
                    } else {
                        // Assuming Paper Trading by default based on spec
                        btnSubmit.disabled = false;
                        btnSubmit.textContent = 'SUBMIT PAPER ORDER';
                        btnSubmit.classList.remove('opacity-50', 'cursor-not-allowed');
                        btnSubmit.classList.replace('bg-gray-700', 'bg-cyan-600');
                    }
                }
            }
        });
    }

    let pendingConfirmationToken = null;
    let pendingOrderReq = null;

    btnSubmit.addEventListener('click', async () => {
        if (isStale) return;
        const sym = document.getElementById('term-symbol').textContent;
        const qty = parseInt(qtyInput.value, 10);
        const priceText = priceInput.value.trim();
        const price = priceText ? parseFloat(priceText) : null;

        if (pendingConfirmationToken) {
            // Step 2: Confirm Order
            feedback.textContent = 'Confirming...';
            feedback.className = 'text-[10px] text-center mt-1 text-cyan-400';
            try {
                const res = await fetch('/api/broker/order/confirm', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        confirmation_token: pendingConfirmationToken,
                        order: pendingOrderReq
                    })
                });
                const data = await res.json();
                if (!res.ok || data.status === 'REJECTED') {
                    feedback.textContent = data.rejection_reason || data.detail || 'Order Rejected';
                    feedback.className = 'text-[10px] text-center mt-1 text-red-500';
                } else {
                    feedback.textContent = 'Order Placed: ' + (data.order_id || data.status);
                    feedback.className = 'text-[10px] text-center mt-1 text-emerald-500';
                }
            } catch (err) {
                feedback.textContent = 'Network Error';
                feedback.className = 'text-[10px] text-center mt-1 text-red-500';
            } finally {
                pendingConfirmationToken = null;
                pendingOrderReq = null;
                btnSubmit.textContent = 'SUBMIT PAPER ORDER';
            }
        } else {
            // Step 1: Preview Order
            pendingOrderReq = {
                symbol: sym,
                exchange_segment: 'NSE',
                product_type: 'CNC',
                side: activeSide,
                order_type: price ? 'LIMIT' : 'MARKET',
                quantity: qty,
                price: price
            };
            feedback.textContent = 'Validating...';
            feedback.className = 'text-[10px] text-center mt-1 text-cyan-400';

            try {
                const res = await fetch('/api/broker/order/preview', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(pendingOrderReq)
                });
                const data = await res.json();
                if (!res.ok) {
                    feedback.textContent = data.detail || 'Validation Failed';
                    feedback.className = 'text-[10px] text-center mt-1 text-red-500';
                    pendingOrderReq = null;
                } else if (!data.safety_result.is_approved) {
                    feedback.textContent = data.safety_result.reason || 'Rejected by Safety Gates';
                    feedback.className = 'text-[10px] text-center mt-1 text-red-500';
                    pendingOrderReq = null;
                } else {
                    pendingConfirmationToken = data.confirmation_token;
                    feedback.textContent = 'Order Validated. Click to CONFIRM.';
                    feedback.className = 'text-[10px] text-center mt-1 text-yellow-400';
                    btnSubmit.textContent = 'CONFIRM ORDER';
                }
            } catch (err) {
                feedback.textContent = 'Network Error';
                feedback.className = 'text-[10px] text-center mt-1 text-red-500';
                pendingOrderReq = null;
            }
        }
    });

    // Fetch terminal mock data
    fetch('/api/v1/portfolio')
        .then(res => res.json())
        .then(payload => {
            const tbody = document.getElementById('term-positions-body');
            if (!tbody) return;
            if (payload && payload.data && payload.data.positions) {
                const positions = payload.data.positions;
                if (positions.length > 0) {
                    // XSS mitigation: we escape HTML strings implicitly or avoid innerHTML with unescaped user string
                    // symbol is strictly controlled, but we can do a simple replacement if needed.
                    tbody.innerHTML = positions.map(p => `
                        <tr class="border-b border-gray-800/30">
                            <td class="p-2 font-semibold text-gray-200">${p.symbol}</td>
                            <td class="p-2 text-right text-gray-300">${p.quantity}</td>
                            <td class="p-2 text-right text-gray-400">₹${p.average_price.toFixed(2)}</td>
                            <td class="p-2 text-right text-white">₹${p.current_price.toFixed(2)}</td>
                            <td class="p-2 text-right font-medium ${p.unrealized_pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}">₹${p.unrealized_pnl.toFixed(2)}</td>
                        </tr>
                    `).join('');
                } else {
                    tbody.innerHTML = '<tr><td colspan="5" class="text-center p-4 text-gray-500">No open positions.</td></tr>';
                }
            } else {
                tbody.innerHTML = '<tr><td colspan="5" class="text-center p-4 text-gray-500">Data Unavailable</td></tr>';
            }
        })
        .catch(err => {
            const tbody = document.getElementById('term-positions-body');
            if (tbody) tbody.innerHTML = '<tr><td colspan="5" class="text-center p-4 text-red-500">Error loading positions.</td></tr>';
        });

    // Cleanup on view change
    const containerObserver = new MutationObserver((mutations) => {
        if (!document.body.contains(container) && cleanup) {
            cleanup();
            containerObserver.disconnect();
        }
    });
    containerObserver.observe(document.body, { childList: true, subtree: true });
}
