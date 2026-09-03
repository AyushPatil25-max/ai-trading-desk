
export async function renderPortfolio(container) {
    container.innerHTML = `
        <div class="flex justify-between items-center mb-6">
            <h2 class="text-xl font-bold text-white">Portfolio & Trading</h2>
        </div>
        
        <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <!-- Broker Integration Status -->
            <div class="glass-panel rounded-xl p-5 border border-gray-800/60 lg:col-span-1">
                <h3 class="text-sm font-semibold text-white uppercase tracking-wider mb-4 border-b border-gray-800 pb-2 flex items-center justify-between">
                    Broker Integration
                    <span class="text-emerald-400 text-xs font-mono bg-emerald-900/30 px-2 py-0.5 rounded border border-emerald-800">Connected</span>
                </h3>
                <div class="space-y-4 text-sm">
                    <div class="flex justify-between items-center">
                        <span class="text-gray-500">Broker</span>
                        <span class="font-bold text-white">Dhan</span>
                    </div>
                    <div class="flex justify-between items-center">
                        <span class="text-gray-500">API Status</span>
                        <span class="text-emerald-400 font-medium">Online</span>
                    </div>
                    <div class="flex justify-between items-center">
                        <span class="text-gray-500">Account Type</span>
                        <span class="text-amber-400 font-mono font-medium">PAPER TRADING</span>
                    </div>
                    
                    <div class="pt-4 border-t border-gray-800/50 mt-4">
                        <button class="w-full py-2 bg-gray-800 hover:bg-gray-700 text-white rounded-lg text-sm transition">Test Connection Profile</button>
                    </div>
                </div>
            </div>

            <!-- Orders/Positions (Mocked for Paper) -->
            <div class="glass-panel rounded-xl p-5 border border-gray-800/60 lg:col-span-2">
                <div class="flex items-center justify-between mb-4 border-b border-gray-800 pb-2">
                    <h3 class="text-sm font-semibold text-white uppercase tracking-wider">Today's Orders</h3>
                    <span class="text-xs text-gray-500">Live Execution is DISABLED</span>
                </div>
                
                <div class="text-center py-12 text-gray-500 border border-dashed border-gray-800 rounded-lg">
                    <i data-lucide="inbox" class="w-8 h-8 mx-auto mb-2 opacity-50"></i>
                    <p>No orders submitted.</p>
                    <p class="text-xs mt-1 text-gray-600">The system is operating in Observational / Paper mode.</p>
                </div>
            </div>
        </div>
    `;
    lucide.createIcons();
}
