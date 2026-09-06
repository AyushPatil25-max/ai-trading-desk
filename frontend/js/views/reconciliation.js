export function renderReconciliation(container) {
    container.innerHTML = `
        <div class="h-full flex flex-col gap-4">
            <div class="flex gap-4">
                <div class="glass-panel p-4 rounded-xl border border-gray-800/60 flex-1">
                    <h2 class="text-sm font-semibold text-gray-200 mb-2">DHAN BROKER STATUS</h2>
                    <div class="grid grid-cols-2 gap-4 text-sm mt-4">
                        <div><span class="text-gray-400">Connection:</span> <span id="rec-conn" class="text-white">Loading...</span></div>
                        <div><span class="text-gray-400">Authentication:</span> <span id="rec-auth" class="text-white">Loading...</span></div>
                        <div><span class="text-gray-400">Last API Call:</span> <span id="rec-last-call" class="text-white">-</span></div>
                        <div><span class="text-gray-400">Latency:</span> <span id="rec-lat" class="text-white">-</span></div>
                    </div>
                </div>
                <div class="glass-panel p-4 rounded-xl border border-gray-800/60 flex-1">
                    <h2 class="text-sm font-semibold text-gray-200 mb-2">RECONCILIATION</h2>
                    <div class="flex flex-col h-full justify-between">
                        <div>
                            <span class="text-gray-400 text-sm">Overall Status:</span> 
                            <span id="rec-overall" class="font-bold text-lg text-white ml-2">UNKNOWN</span>
                        </div>
                        <button id="btn-run-rec" class="py-2 bg-cyan-600 hover:bg-cyan-500 text-white rounded font-medium mt-4">
                            RUN RECONCILIATION
                        </button>
                    </div>
                </div>
            </div>
            
            <div class="glass-panel rounded-xl border border-gray-800/60 flex-1 flex flex-col">
                <div class="p-3 border-b border-gray-800/60 bg-gray-900/50">
                    <h2 class="text-sm font-semibold text-gray-200">Reconciliation Report</h2>
                </div>
                <div class="p-4 flex-1 overflow-auto text-sm" id="rec-report">
                    <div class="text-gray-500 text-center mt-10">Run reconciliation to view report.</div>
                </div>
            </div>
        </div>
    `;

    function loadStatus() {
        fetch('/api/broker/validation/status')
            .then(res => res.json())
            .then(data => {
                document.getElementById('rec-conn').textContent = data.connection_status;
                document.getElementById('rec-auth').textContent = data.authentication_status;
                
                if (data.connection_status === 'CONNECTED' || data.connection_status === 'DHAN_CONNECTED') {
                    document.getElementById('rec-conn').className = 'text-emerald-400';
                }
                if (data.authentication_status === 'AUTHENTICATED') {
                    document.getElementById('rec-auth').className = 'text-emerald-400';
                } else {
                    document.getElementById('rec-auth').className = 'text-red-400';
                }
                
                if (data.last_successful_call) {
                    document.getElementById('rec-last-call').textContent = new Date(data.last_successful_call).toLocaleTimeString();
                }
                if (data.latency_ms) {
                    document.getElementById('rec-lat').textContent = data.latency_ms.toFixed(1) + ' ms';
                }
            }).catch(e => {
                document.getElementById('rec-conn').textContent = 'ERROR';
                document.getElementById('rec-auth').textContent = 'ERROR';
            });
    }

    function renderReport(data) {
        document.getElementById('rec-overall').textContent = data.overall_status;
        if (data.overall_status === 'MATCHED') document.getElementById('rec-overall').className = 'font-bold text-lg ml-2 text-emerald-400';
        else if (data.overall_status === 'MISMATCH') document.getElementById('rec-overall').className = 'font-bold text-lg ml-2 text-red-400';
        else document.getElementById('rec-overall').className = 'font-bold text-lg ml-2 text-yellow-400';
        
        let html = '<div class="grid grid-cols-2 gap-6">';
        ['orders', 'trades', 'positions', 'holdings', 'funds'].forEach(k => {
            const v = data[k] || {};
            html += \`
                <div class="border border-gray-800 rounded p-3 bg-gray-900/30">
                    <h3 class="font-bold text-gray-300 uppercase mb-2">\${k}</h3>
                    <div class="text-xs grid grid-cols-2 gap-1">
                        <span class="text-gray-500">Status:</span> <span class="font-medium \${v.status==='MATCHED'?'text-emerald-400':(v.status==='UNAVAILABLE'?'text-gray-500':'text-yellow-400')}">\${v.status || 'UNKNOWN'}</span>
                        <span class="text-gray-500">Matched:</span> <span class="text-white">\${v.matched_count || 0}</span>
                        <span class="text-gray-500">Mismatched:</span> <span class="text-red-400">\${v.mismatched_count || 0}</span>
                        <span class="text-gray-500">Missing:</span> <span class="text-red-400">\${v.missing_count || 0}</span>
                    </div>
                </div>
            \`;
        });
        html += '</div>';

        if (data.discrepancies && data.discrepancies.length > 0) {
            html += '<h3 class="font-bold text-gray-300 mt-6 mb-2">DISCREPANCIES</h3>';
            html += '<table class="w-full text-left text-xs"><thead class="text-gray-500 border-b border-gray-800"><tr><th class="py-1">Entity</th><th>Field</th><th>Broker</th><th>Local</th><th>Diff</th><th>Status</th></tr></thead><tbody>';
            data.discrepancies.forEach(d => {
                html += \`<tr class="border-b border-gray-800/30">
                    <td class="py-1 text-gray-300">\${d.entity_type} \${d.broker_key || d.local_key || ''}</td>
                    <td class="text-gray-400">\${d.field || ''}</td>
                    <td class="text-gray-200">\${d.broker_value}</td>
                    <td class="text-gray-200">\${d.local_value}</td>
                    <td class="text-yellow-400">\${d.difference || ''}</td>
                    <td class="text-red-400">\${d.status}</td>
                </tr>\`;
            });
            html += '</tbody></table>';
        }

        document.getElementById('rec-report').innerHTML = html;
    }

    document.getElementById('btn-run-rec').addEventListener('click', () => {
        document.getElementById('rec-report').innerHTML = '<div class="text-center p-8 text-cyan-400">Running reconciliation...</div>';
        fetch('/api/broker/reconciliation/run', { method: 'POST' })
            .then(res => res.json())
            .then(renderReport)
            .catch(e => {
                document.getElementById('rec-report').innerHTML = '<div class="text-center p-8 text-red-500">Failed to run reconciliation</div>';
            });
    });

    loadStatus();
    
    // Attempt to load latest
    fetch('/api/broker/reconciliation/history/latest')
        .then(res => {
            if (res.ok) return res.json();
            throw new Error('None');
        })
        .then(renderReport)
        .catch(e => {});
}
