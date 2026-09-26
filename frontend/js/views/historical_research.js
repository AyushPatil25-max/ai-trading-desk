export function renderHistoricalResearch(container) {
    container.innerHTML = `
        <div class="space-y-6">
            <!-- Header -->
            <div class="flex flex-col md:flex-row md:items-center justify-between gap-4 bg-gray-900 border border-gray-800 p-6 rounded-xl">
                <div>
                    <h2 class="text-xl font-bold text-white flex items-center gap-2">
                        <i data-lucide="history" class="w-6 h-6 text-cyan-400"></i>
                        Historical Research & Backtesting
                    </h2>
                    <p class="text-gray-400 text-sm mt-1">Deterministic point-in-time evaluation of historical setups</p>
                </div>
            </div>

            <!-- Configuration Form -->
            <div class="bg-gray-900 border border-gray-800 rounded-xl p-6">
                <h3 class="text-lg font-semibold text-white mb-4">New Research Run</h3>
                <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
                    <div>
                        <label class="block text-sm font-medium text-gray-400 mb-1">Symbol</label>
                        <input type="text" id="histSymbol" value="RELIANCE.NS" class="w-full bg-gray-800 border border-gray-700 text-white rounded-lg px-4 py-2 focus:outline-none focus:border-cyan-500">
                    </div>
                    <div>
                        <label class="block text-sm font-medium text-gray-400 mb-1">Evaluation Date (As Of)</label>
                        <input type="date" id="histDate" class="w-full bg-gray-800 border border-gray-700 text-white rounded-lg px-4 py-2 focus:outline-none focus:border-cyan-500" value="2024-01-01">
                    </div>
                    <div>
                        <label class="block text-sm font-medium text-gray-400 mb-1">Holding Period (Bars)</label>
                        <input type="number" id="histHoldingPeriod" value="5" class="w-full bg-gray-800 border border-gray-700 text-white rounded-lg px-4 py-2 focus:outline-none focus:border-cyan-500">
                    </div>
                    <div class="flex items-end">
                        <button id="btnRunHistResearch" class="w-full bg-cyan-600 hover:bg-cyan-500 text-white font-medium py-2 px-4 rounded-lg transition-colors flex items-center justify-center gap-2">
                            <i data-lucide="play" class="w-4 h-4"></i>
                            Run Backtest
                        </button>
                    </div>
                </div>
                
                <div id="histLoading" class="hidden mt-4 flex items-center gap-2 text-cyan-400 text-sm">
                    <i data-lucide="loader-2" class="w-4 h-4 animate-spin"></i>
                    Running deterministic backtest...
                </div>
            </div>

            <!-- Results Display -->
            <div id="histResultContainer" class="hidden space-y-6">
                <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
                    <div class="bg-gray-900 border border-gray-800 p-6 rounded-xl">
                        <div class="text-gray-400 text-sm font-medium">Forward Return</div>
                        <div id="histFwdReturn" class="text-2xl font-bold text-white mt-1">--</div>
                    </div>
                    <div class="bg-gray-900 border border-gray-800 p-6 rounded-xl">
                        <div class="text-gray-400 text-sm font-medium">Max Drawdown</div>
                        <div id="histMaxDrawdown" class="text-2xl font-bold text-white mt-1">--</div>
                    </div>
                    <div class="bg-gray-900 border border-gray-800 p-6 rounded-xl">
                        <div class="text-gray-400 text-sm font-medium">Outcome Status</div>
                        <div id="histStatus" class="text-2xl font-bold text-white mt-1">--</div>
                    </div>
                </div>
                
                <div class="bg-gray-900 border border-gray-800 rounded-xl p-6">
                    <h3 class="text-lg font-semibold text-white mb-4">Detailed Metrics</h3>
                    <div class="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm" id="histDetailsGrid">
                        <!-- Filled by JS -->
                    </div>
                </div>
            </div>

            <!-- Past Results List -->
            <div class="bg-gray-900 border border-gray-800 rounded-xl p-6">
                <h3 class="text-lg font-semibold text-white mb-4">Recent Historical Runs</h3>
                <div class="overflow-x-auto">
                    <table class="w-full text-left text-sm text-gray-300">
                        <thead class="text-xs text-gray-500 uppercase bg-gray-800">
                            <tr>
                                <th class="px-4 py-3 rounded-tl-lg">Symbol</th>
                                <th class="px-4 py-3">Evaluation Date</th>
                                <th class="px-4 py-3">Status</th>
                                <th class="px-4 py-3 rounded-tr-lg">Net Return</th>
                            </tr>
                        </thead>
                        <tbody id="histResultsList" class="divide-y divide-gray-800">
                            <!-- Filled dynamically -->
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    `;

    lucide.createIcons();

    const btnRun = document.getElementById('btnRunHistResearch');
    const symbolInput = document.getElementById('histSymbol');
    const dateInput = document.getElementById('histDate');
    const periodInput = document.getElementById('histHoldingPeriod');
    const loading = document.getElementById('histLoading');
    const resultContainer = document.getElementById('histResultContainer');

    btnRun.addEventListener('click', async () => {
        const symbol = symbolInput.value.trim();
        const as_of = dateInput.value;
        const holding = parseInt(periodInput.value, 10);

        if (!symbol || !as_of || !holding) {
            alert('Please fill all fields');
            return;
        }

        btnRun.disabled = true;
        loading.classList.remove('hidden');
        resultContainer.classList.add('hidden');

        try {
            const res = await fetch('/api/historical-research/run', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    symbol: symbol,
                    as_of: as_of + "T00:00:00Z",
                    config: {
                        mode: "SINGLE_DECISION",
                        holding_period_bars: holding
                    }
                })
            });

            if (!res.ok) throw new Error(await res.text());
            const data = await res.json();
            
            displayResult(data);
            loadRecentRuns();
        } catch (e) {
            console.error(e);
            alert('Failed to run backtest: ' + e.message);
        } finally {
            btnRun.disabled = false;
            loading.classList.add('hidden');
        }
    });

    function displayResult(data) {
        const outcome = data.primary_outcome;
        if (!outcome) return;

        resultContainer.classList.remove('hidden');

        const retEl = document.getElementById('histFwdReturn');
        retEl.textContent = outcome.net_return_pct.toFixed(2) + '%';
        retEl.className = `text-2xl font-bold mt-1 ${outcome.net_return_pct > 0 ? 'text-green-400' : outcome.net_return_pct < 0 ? 'text-red-400' : 'text-gray-300'}`;

        document.getElementById('histMaxDrawdown').textContent = outcome.drawdown_pct.toFixed(2) + '%';
        document.getElementById('histStatus').textContent = outcome.outcome_status;

        const details = document.getElementById('histDetailsGrid');
        details.innerHTML = `
            <div><div class="text-gray-500">Entry Price</div><div class="text-white font-medium">${outcome.entry_price.toFixed(2)}</div></div>
            <div><div class="text-gray-500">Exit Price</div><div class="text-white font-medium">${outcome.exit_price.toFixed(2)}</div></div>
            <div><div class="text-gray-500">MFE</div><div class="text-green-400 font-medium">${outcome.mfe_pct.toFixed(2)}%</div></div>
            <div><div class="text-gray-500">MAE</div><div class="text-red-400 font-medium">${outcome.mae_pct.toFixed(2)}%</div></div>
            <div><div class="text-gray-500">Total Cost</div><div class="text-white font-medium">${outcome.total_cost.toFixed(2)}</div></div>
            <div><div class="text-gray-500">Gross PnL</div><div class="text-white font-medium">${outcome.gross_pnl.toFixed(2)}</div></div>
            <div><div class="text-gray-500">Decision Score</div><div class="text-white font-medium">${data.decision_quality_score.toFixed(2)}</div></div>
            <div><div class="text-gray-500">Stop Hit?</div><div class="text-white font-medium">${outcome.stop_loss_hit ? 'Yes' : 'No'}</div></div>
        `;
    }

    async function loadRecentRuns() {
        try {
            const res = await fetch('/api/historical-research/results');
            if (!res.ok) return;
            const data = await res.json();
            
            const tbody = document.getElementById('histResultsList');
            tbody.innerHTML = data.map(r => {
                const dateStr = new Date(r.evaluation_timestamp).toISOString().split('T')[0];
                const retColor = r.net_return_pct > 0 ? 'text-green-400' : r.net_return_pct < 0 ? 'text-red-400' : 'text-gray-400';
                return `
                    <tr class="hover:bg-gray-800/50">
                        <td class="px-4 py-3 font-medium text-white">${r.symbol}</td>
                        <td class="px-4 py-3">${dateStr}</td>
                        <td class="px-4 py-3">${r.outcome_status || '--'}</td>
                        <td class="px-4 py-3 font-medium ${retColor}">${r.net_return_pct !== undefined ? r.net_return_pct.toFixed(2) + '%' : '--'}</td>
                    </tr>
                `;
            }).join('');
        } catch (e) {
            console.error('Failed to load recent runs', e);
        }
    }

    loadRecentRuns();
}
