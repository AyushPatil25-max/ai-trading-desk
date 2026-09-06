export function renderWatchlists(container) {
    container.innerHTML = `
        <div class="h-full flex flex-col gap-4">
            <div class="glass-panel p-4 rounded-xl border border-gray-800/60 flex justify-between items-center shrink-0">
                <h1 class="text-xl font-bold text-white">Watchlists</h1>
                <div class="flex gap-2">
                    <select class="bg-gray-800 border border-gray-700 rounded text-sm text-white px-2 py-1">
                        <option>My Watchlist 1</option>
                        <option>NIFTY 50</option>
                    </select>
                    <button class="bg-cyan-600 hover:bg-cyan-500 text-white px-3 py-1 rounded text-sm font-medium transition-colors">
                        + Add Symbol
                    </button>
                </div>
            </div>

            <div class="flex-1 glass-panel rounded-xl border border-gray-800/60 flex flex-col overflow-hidden">
                <div class="overflow-x-auto flex-1">
                    <table class="w-full text-left text-sm">
                        <thead class="sticky top-0 bg-gray-900 border-b border-gray-800/60 shadow-sm z-10">
                            <tr class="text-xs text-gray-500">
                                <th class="p-3 font-medium">SYMBOL</th>
                                <th class="p-3 font-medium text-right">LTP</th>
                                <th class="p-3 font-medium text-right">CHANGE</th>
                                <th class="p-3 font-medium text-right">%</th>
                                <th class="p-3 font-medium text-right">BID</th>
                                <th class="p-3 font-medium text-right">ASK</th>
                                <th class="p-3 font-medium text-right">VOLUME</th>
                                <th class="p-3 font-medium text-right">AGE</th>
                                <th class="p-3 font-medium text-center">STATE</th>
                            </tr>
                        </thead>
                        <tbody id="wl-body">
                            <tr><td colspan="9" class="text-center p-8 text-gray-500">Loading Watchlist...</td></tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    `;

    // Mock data for UI layout
    setTimeout(() => {
        const tbody = document.getElementById('wl-body');
        if (!tbody) return;
        const symbols = ['RELIANCE', 'TCS', 'HDFCBANK', 'INFY', 'ICICIBANK'];
        tbody.innerHTML = symbols.map(sym => `
            <tr class="border-b border-gray-800/30 hover:bg-gray-800/50 cursor-pointer">
                <td class="p-3 font-semibold text-gray-200 flex items-center gap-2">
                    <button class="text-red-500 hover:text-red-400" title="Remove">&times;</button>
                    ${sym}
                </td>
                <td class="p-3 text-right text-white">₹--</td>
                <td class="p-3 text-right text-gray-400">--</td>
                <td class="p-3 text-right text-gray-400">--%</td>
                <td class="p-3 text-right text-gray-400">--</td>
                <td class="p-3 text-right text-gray-400">--</td>
                <td class="p-3 text-right text-gray-400">--</td>
                <td class="p-3 text-right text-gray-500 text-xs">--</td>
                <td class="p-3 text-center"><span class="px-1.5 py-0.5 bg-gray-800 text-gray-500 rounded text-[10px]">UNAVAILABLE</span></td>
            </tr>
        `).join('');
    }, 100);
}
