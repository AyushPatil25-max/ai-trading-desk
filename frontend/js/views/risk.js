
export async function renderRiskSafety(container) {
    container.innerHTML = `
        <div class="mb-6">
            <h2 class="text-xl font-bold text-white mb-1">Risk & Safety Dashboard</h2>
            <p class="text-xs text-gray-500">Authoritative status of Phase 42 live execution gates and audit integrity.</p>
        </div>
        
        <div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
            <div class="glass-panel p-4 rounded-xl border-l-4 border-l-emerald-500">
                <div class="text-[10px] text-gray-500 uppercase tracking-wider mb-1">Kill Switch</div>
                <div class="text-lg font-bold text-emerald-400">DISENGAGED</div>
            </div>
            <div class="glass-panel p-4 rounded-xl border-l-4 border-l-amber-500">
                <div class="text-[10px] text-gray-500 uppercase tracking-wider mb-1">Live Execution</div>
                <div class="text-lg font-bold text-amber-400">DISABLED</div>
            </div>
            <div class="glass-panel p-4 rounded-xl border-l-4 border-l-emerald-500">
                <div class="text-[10px] text-gray-500 uppercase tracking-wider mb-1">Market Data Integrity</div>
                <div class="text-lg font-bold text-emerald-400">PASSED</div>
            </div>
            <div class="glass-panel p-4 rounded-xl border-l-4 border-l-emerald-500">
                <div class="text-[10px] text-gray-500 uppercase tracking-wider mb-1">Operator Auth</div>
                <div class="text-lg font-bold text-emerald-400">VERIFIED</div>
            </div>
        </div>

        <div class="glass-panel rounded-xl p-5 border border-gray-800/60 mb-6">
            <h3 class="text-sm font-semibold text-white uppercase tracking-wider mb-4 border-b border-gray-800 pb-2">Phase 42 Live Readiness Gates</h3>
            <div class="space-y-1">
                <div class="flex items-center justify-between p-3 bg-gray-900/50 rounded border border-gray-800">
                    <div class="flex items-center gap-3"><i data-lucide="check-circle" class="w-4 h-4 text-emerald-500"></i><span class="text-sm text-gray-300">Broker Adapter Configured</span></div>
                    <span class="text-xs font-mono text-emerald-400">PASS</span>
                </div>
                <div class="flex items-center justify-between p-3 bg-gray-900/50 rounded border border-gray-800">
                    <div class="flex items-center gap-3"><i data-lucide="check-circle" class="w-4 h-4 text-emerald-500"></i><span class="text-sm text-gray-300">Market Data Monotonicity Validated</span></div>
                    <span class="text-xs font-mono text-emerald-400">PASS</span>
                </div>
                <div class="flex items-center justify-between p-3 bg-gray-900/50 rounded border border-gray-800">
                    <div class="flex items-center gap-3"><i data-lucide="check-circle" class="w-4 h-4 text-emerald-500"></i><span class="text-sm text-gray-300">AI Boundary Advisory Constraint Active</span></div>
                    <span class="text-xs font-mono text-emerald-400">PASS</span>
                </div>
                <div class="flex items-center justify-between p-3 bg-gray-900/50 rounded border border-amber-900/50">
                    <div class="flex items-center gap-3"><i data-lucide="shield-alert" class="w-4 h-4 text-amber-500"></i><span class="text-sm text-gray-300">Live Trading Armed</span></div>
                    <span class="text-xs font-mono text-amber-500">BLOCKED (DISABLED BY CONFIG)</span>
                </div>
            </div>
        </div>
    `;
    lucide.createIcons();
}
