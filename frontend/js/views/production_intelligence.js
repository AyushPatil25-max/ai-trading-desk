export function renderProductionIntelligence(container) {
    const renderSpinner = () => {
        container.innerHTML = `<div class="flex items-center justify-center h-64"><div class="animate-spin rounded-full h-8 w-8 border-b-2 border-cyan-400"></div></div>`;
    };

    const showError = (msg) => {
        container.innerHTML = `<div class="p-4 text-red-400 bg-red-900/30 rounded">${msg}</div>`;
    };

    const loadData = async () => {
        renderSpinner();
        try {
            const res = await fetch('/api/production-intelligence/readiness');
            if (!res.ok) throw new Error('Failed to load production intelligence data');
            const data = await res.json();
            renderUI(data);
        } catch (e) {
            showError(e.message);
        }
    };

    const getStatusColor = (status) => {
        switch(status) {
            case 'HEALTHY': return 'text-green-400';
            case 'DEGRADED': return 'text-yellow-400';
            case 'UNAVAILABLE': return 'text-red-400';
            case 'NOT_CONFIGURED': return 'text-gray-400';
            default: return 'text-white';
        }
    };

    const renderUI = (data) => {
        let html = '<div class="space-y-6">';

        // Header
        const overallColor = data.is_ready ? 'text-green-400' : 'text-yellow-400';
        html += `
            <div class="flex justify-between items-center pb-4 border-b border-gray-700">
                <h2 class="text-2xl font-semibold">Production Intelligence Platform</h2>
                <div class="flex space-x-4 items-center">
                    <span class="text-sm">Status: <span class="font-bold ${overallColor}">${data.overall_status}</span></span>
                    <button id="btnRefreshProd" class="bg-cyan-900/30 hover:bg-cyan-800 text-cyan-400 px-3 py-1 rounded text-sm">Refresh</button>
                </div>
            </div>
        `;

        // Safety controls
        html += `
            <div class="p-4 bg-gray-800/50 rounded border border-gray-700">
                <h3 class="text-lg font-medium mb-2 border-b border-gray-700 pb-1">Safety Architecture</h3>
                <div class="grid grid-cols-2 gap-4">
                    <div>
                        <div class="text-gray-400 text-sm">Live Execution Enabled</div>
                        <div class="font-mono ${!data.live_execution_enabled ? 'text-green-400' : 'text-red-400'}">${data.live_execution_enabled}</div>
                    </div>
                    <div>
                        <div class="text-gray-400 text-sm">Execution Freeze Active</div>
                        <div class="font-mono ${data.execution_freeze_active ? 'text-green-400' : 'text-red-400'}">${data.execution_freeze_active}</div>
                    </div>
                </div>
            </div>
        `;

        // Warnings
        if (data.warnings && data.warnings.length > 0) {
            html += `
                <div class="p-4 bg-red-900/30 border border-red-700 rounded text-red-400 space-y-1">
                    <h3 class="font-semibold text-red-300">System Warnings</h3>
                    <ul class="list-disc pl-5">
                        ${data.warnings.map(w => `<li>${w}</li>`).join('')}
                    </ul>
                </div>
            `;
        }

        // Components
        html += `
            <div>
                <h3 class="text-lg font-medium mb-2 border-b border-gray-700 pb-1">Component Health</h3>
                <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                    ${data.components.map(c => `
                        <div class="p-3 bg-gray-800/30 rounded border border-gray-700">
                            <div class="flex justify-between items-start">
                                <span class="font-medium">${c.name}</span>
                                <span class="text-sm font-bold ${getStatusColor(c.status)}">${c.status}</span>
                            </div>
                            <div class="text-xs text-gray-400 mt-1">${c.details || ''}</div>
                            ${c.latency_ms !== null ? `<div class="text-xs text-gray-500 mt-1">Latency: ${c.latency_ms.toFixed(1)}ms</div>` : ''}
                        </div>
                    `).join('')}
                </div>
            </div>
        `;

        // Providers
        html += `
            <div>
                <h3 class="text-lg font-medium mb-2 border-b border-gray-700 pb-1">Data Provider Quality</h3>
                <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                    ${data.providers.map(p => `
                        <div class="p-3 bg-gray-800/30 rounded border border-gray-700">
                            <div class="flex justify-between items-start">
                                <span class="font-medium">${p.provider_name}</span>
                                <span class="text-sm font-bold ${getStatusColor(p.status)}">${p.status}</span>
                            </div>
                            <div class="flex space-x-4 mt-2 text-xs text-gray-400">
                                <div>Freshness: <span class="text-gray-300">${p.freshness}</span></div>
                                <div>Completeness: <span class="text-gray-300">${(p.completeness * 100).toFixed(0)}%</span></div>
                            </div>
                            ${p.quality_warnings.length > 0 ? `<div class="mt-2 text-xs text-yellow-500">Warnings: ${p.quality_warnings.join(', ')}</div>` : ''}
                        </div>
                    `).join('')}
                </div>
            </div>
        `;

        // Pipelines
        html += `
            <div>
                <h3 class="text-lg font-medium mb-2 border-b border-gray-700 pb-1">Intelligence Pipelines</h3>
                <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                    ${data.pipelines.map(p => `
                        <div class="p-3 bg-gray-800/30 rounded border border-gray-700">
                            <div class="flex justify-between items-start">
                                <span class="font-medium">${p.pipeline_name}</span>
                                <span class="text-sm font-bold ${getStatusColor(p.status)}">${p.status}</span>
                            </div>
                        </div>
                    `).join('')}
                </div>
            </div>
        `;

        html += '</div>';
        container.innerHTML = html;

        document.getElementById('btnRefreshProd').addEventListener('click', loadData);
    };

    loadData();
}
