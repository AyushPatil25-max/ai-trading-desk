export class ScannerView {
    constructor() {
        this.currentView = 'top';
        this.opportunities = [];
        this.loading = false;
    }

    async render(container) {
        container.innerHTML = 
            <div class="flex flex-col h-full overflow-hidden">
                <div class="flex-none bg-gray-900 border-b border-gray-800 px-6 py-4">
                    <div class="flex justify-between items-center">
                        <div>
                            <h1 class="text-2xl font-black text-white tracking-tight uppercase">Market Scanner</h1>
                            <p class="text-sm text-gray-500 mt-1">Real-time Opportunity Detection Engine</p>
                        </div>
                        <div class="flex gap-2">
                            <button id="refreshScannerBtn" class="bg-gray-800 hover:bg-gray-700 text-white px-4 py-2 rounded text-sm font-bold tracking-wide border border-gray-700 transition-colors flex items-center gap-2">
                                <i data-lucide="refresh-cw" class="w-4 h-4"></i> Scan Market
                            </button>
                        </div>
                    </div>
                </div>

                <div class="flex-none border-b border-gray-800 bg-gray-950 px-6">
                    <div class="flex gap-6 overflow-x-auto text-sm font-bold uppercase tracking-wider" id="scannerTabs">
                        <button data-tab="top" class="py-4 text-emerald-400 border-b-2 border-emerald-400 whitespace-nowrap">Top Opportunities</button>
                        <button data-tab="momentum" class="py-4 text-gray-500 hover:text-gray-300 border-b-2 border-transparent whitespace-nowrap">Momentum</button>
                        <button data-tab="breakouts" class="py-4 text-gray-500 hover:text-gray-300 border-b-2 border-transparent whitespace-nowrap">Breakouts</button>
                        <button data-tab="reversals" class="py-4 text-gray-500 hover:text-gray-300 border-b-2 border-transparent whitespace-nowrap">Reversals</button>
                        <button data-tab="volume" class="py-4 text-gray-500 hover:text-gray-300 border-b-2 border-transparent whitespace-nowrap">Volume Spikes</button>
                        <button data-tab="gaps" class="py-4 text-gray-500 hover:text-gray-300 border-b-2 border-transparent whitespace-nowrap">Gaps</button>
                    </div>
                </div>

                <div class="flex-1 overflow-auto bg-gray-950 p-6" id="scannerContent">
                    <div class="text-center text-gray-500 py-12">
                        <i data-lucide="scan" class="w-12 h-12 mx-auto mb-4 opacity-50"></i>
                        <p>Click "Scan Market" to discover opportunities</p>
                    </div>
                </div>
            </div>
        ;
        
        lucide.createIcons();
        this.bindEvents(container);
        this.loadOpportunities();
    }

    bindEvents(container) {
        const tabs = container.querySelectorAll('#scannerTabs button');
        tabs.forEach(tab => {
            tab.addEventListener('click', (e) => {
                // Update active state
                tabs.forEach(t => {
                    t.classList.remove('text-emerald-400', 'border-emerald-400');
                    t.classList.add('text-gray-500', 'border-transparent');
                });
                e.target.classList.remove('text-gray-500', 'border-transparent');
                e.target.classList.add('text-emerald-400', 'border-emerald-400');
                
                this.currentView = e.target.dataset.tab;
                this.loadOpportunities();
            });
        });

        container.querySelector('#refreshScannerBtn').addEventListener('click', () => {
            this.loadOpportunities();
        });
    }

    async loadOpportunities() {
        const content = document.getElementById('scannerContent');
        if (!content) return;

        this.loading = true;
        content.innerHTML = 
            <div class="flex items-center justify-center h-full text-gray-500">
                <i data-lucide="loader-2" class="w-8 h-8 animate-spin"></i>
                <span class="ml-3 font-mono text-sm uppercase tracking-widest">Scanning Market Universe...</span>
            </div>
        ;
        lucide.createIcons();

        try {
            let endpoint = '/api/v1/scanner/opportunities';
            if (this.currentView === 'top') endpoint = '/api/v1/scanner/top';
            else if (this.currentView === 'momentum') endpoint = '/api/v1/scanner/momentum';
            else if (this.currentView === 'breakouts') endpoint = '/api/v1/scanner/breakouts';
            else if (this.currentView === 'reversals') endpoint = '/api/v1/scanner/reversals';
            else if (this.currentView === 'volume') endpoint = '/api/v1/scanner/volume-spikes';
            else if (this.currentView === 'gaps') endpoint = '/api/v1/scanner/gaps';

            const response = await fetch(endpoint);
            const data = await response.json();
            
            this.opportunities = data.opportunities || [];
            this.renderOpportunities(content);
        } catch (error) {
            console.error("Scanner error:", error);
            content.innerHTML = 
                <div class="text-center text-rose-500 py-12">
                    <i data-lucide="alert-triangle" class="w-12 h-12 mx-auto mb-4"></i>
                    <p class="font-bold">Failed to load scanner results.</p>
                    <p class="text-sm text-gray-400 mt-2">\</p>
                </div>
            ;
            lucide.createIcons();
        } finally {
            this.loading = false;
        }
    }

    renderOpportunities(container) {
        if (this.opportunities.length === 0) {
            container.innerHTML = 
                <div class="text-center text-gray-500 py-12">
                    <i data-lucide="shield-alert" class="w-12 h-12 mx-auto mb-4 opacity-50"></i>
                    <p>No high-confidence opportunities found for this criteria.</p>
                </div>
            ;
            lucide.createIcons();
            return;
        }

        let html = '<div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">';
        
        this.opportunities.forEach(op => {
            const ltp = op.market.ltp || 'N/A';
            const change = op.market.spread || 'N/A'; // just as placeholder if change not available directly
            const score = Math.round(op.opportunity.opportunity_score);
            const conf = Math.round(op.opportunity.confidence * 100);
            
            let statusColor = "bg-gray-800 text-gray-300";
            if (op.market.data_quality === 'LIVE') statusColor = "bg-emerald-900/30 text-emerald-400 border border-emerald-800";
            if (op.market.data_quality === 'STALE') statusColor = "bg-amber-900/30 text-amber-400 border border-amber-800";
            if (op.market.data_quality === 'HISTORICAL') statusColor = "bg-blue-900/30 text-blue-400 border border-blue-800";
            
            const directionColor = op.opportunity.direction === 'BULLISH' ? 'text-emerald-400' : (op.opportunity.direction === 'BEARISH' ? 'text-rose-400' : 'text-gray-400');
            
            html += 
                <div class="bg-gray-900 border border-gray-800 rounded-lg p-4 hover:border-gray-700 transition-colors cursor-pointer scanner-card" data-symbol="\">
                    <div class="flex justify-between items-start mb-3">
                        <div>
                            <h3 class="text-lg font-bold text-white uppercase tracking-wider">\</h3>
                            <div class="text-[10px] uppercase tracking-widest \ px-1.5 py-0.5 rounded mt-1 inline-block">\</div>
                        </div>
                        <div class="text-right">
                            <div class="text-sm font-mono text-white">₹\</div>
                        </div>
                    </div>
                    
                    <div class="mb-4">
                        <div class="text-xs text-gray-500 uppercase tracking-wider mb-1">Signal</div>
                        <div class="font-bold \ flex items-center gap-1">
                            <i data-lucide="\" class="w-4 h-4"></i>
                            \
                        </div>
                    </div>
                    
                    <div class="grid grid-cols-2 gap-2 mb-4">
                        <div class="bg-gray-950 p-2 rounded border border-gray-800/50">
                            <div class="text-[9px] text-gray-500 uppercase tracking-widest">Score</div>
                            <div class="text-lg font-bold text-white">\</div>
                        </div>
                        <div class="bg-gray-950 p-2 rounded border border-gray-800/50">
                            <div class="text-[9px] text-gray-500 uppercase tracking-widest">Confidence</div>
                            <div class="text-lg font-bold text-white">\%</div>
                        </div>
                    </div>
                    
                    <div class="text-xs text-gray-400 border-t border-gray-800 pt-3 line-clamp-2">
                        \
                    </div>
                </div>
            ;
        });
        
        html += '</div>';
        container.innerHTML = html;
        lucide.createIcons();
    }
}
