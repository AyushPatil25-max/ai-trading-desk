export function renderAlerts(container) {
    container.innerHTML = `
        <div class="h-full flex flex-col gap-4">
            <div class="glass-panel p-4 rounded-xl border border-gray-800/60 flex justify-between items-center shrink-0">
                <h1 class="text-xl font-bold text-white">System Alerts & Notifications</h1>
                <button class="bg-cyan-600 hover:bg-cyan-500 text-white px-3 py-1 rounded text-sm font-medium transition-colors">
                    Acknowledge All
                </button>
            </div>

            <div class="flex-1 glass-panel rounded-xl border border-gray-800/60 flex flex-col overflow-hidden">
                <div class="overflow-y-auto flex-1 p-4">
                    <div id="alerts-container" class="space-y-3">
                        <div class="text-center p-8 text-gray-500">Loading alerts...</div>
                    </div>
                </div>
            </div>
        </div>
    `;

    fetch('/api/alerts/active')
        .then(res => res.json())
        .then(payload => {
            const container = document.getElementById('alerts-container');
            if (!container) return;
            const alerts = payload.alerts || payload || [];
            if (alerts.length === 0) {
                container.innerHTML = '<div class="text-center p-8 text-gray-500">No active alerts.</div>';
                return;
            }
            container.innerHTML = alerts.map(a => `
                <div class="p-3 border rounded-lg ${a.severity === 'CRITICAL' ? 'bg-red-900/20 border-red-800/50' : 'bg-gray-800/50 border-gray-700/50'} flex justify-between items-start">
                    <div>
                        <div class="flex items-center gap-2 mb-1">
                            <span class="px-2 py-0.5 rounded text-[10px] font-bold ${a.severity === 'CRITICAL' ? 'bg-red-900 text-red-400' : 'bg-gray-700 text-gray-300'}">${a.severity}</span>
                            <span class="font-semibold text-white text-sm">${a.title}</span>
                            <span class="text-xs text-gray-500 font-mono">${new Date(a.timestamp).toLocaleTimeString()}</span>
                        </div>
                        <div class="text-sm text-gray-400">${a.message}</div>
                    </div>
                    <button class="text-xs text-cyan-400 hover:text-cyan-300 px-2 py-1 border border-cyan-800/50 rounded">ACK</button>
                </div>
            `).join('');
        })
        .catch(err => {
            const container = document.getElementById('alerts-container');
            if (container) container.innerHTML = '<div class="text-center p-8 text-red-500">Failed to load alerts.</div>';
        });
}
