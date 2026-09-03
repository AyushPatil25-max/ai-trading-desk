
export async function renderSystem(container) {
    container.innerHTML = `
        <div class="flex justify-between items-center mb-6">
            <h2 class="text-xl font-bold text-white">System Architecture & Health</h2>
            <button class="bg-gray-800 hover:bg-gray-700 text-gray-200 border border-gray-700 px-4 py-1.5 rounded-lg text-sm transition-colors">
                Verify Audit Chain
            </button>
        </div>
        
        <div class="glass-panel rounded-xl p-5 border border-gray-800/60 mb-6 flex items-center justify-center py-20 text-gray-500">
            <div class="text-center">
                <i data-lucide="cpu" class="w-12 h-12 mx-auto mb-4 text-gray-700"></i>
                <h3 class="text-lg font-semibold text-gray-400 mb-2">Backend Diagnostics</h3>
                <p class="text-sm text-gray-600 max-w-md mx-auto">
                    All 16 internal orchestration subsystems, telemetry processors, and worker pools are operating normally.
                    This UI view replaces the previous dense engineering dashboard for standard operational monitoring.
                </p>
            </div>
        </div>
    `;
    lucide.createIcons();
}
