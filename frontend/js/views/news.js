export function renderNews(container) {
    container.innerHTML = `
        <div class="flex flex-col h-full space-y-4">
            <!-- Header Controls -->
            <div class="glass-panel p-4 rounded-xl border border-gray-800/60 flex flex-wrap gap-4 items-center justify-between">
                <div class="flex gap-2 items-center">
                    <div class="relative">
                        <i data-lucide="search" class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400"></i>
                        <input type="text" id="news-symbol" placeholder="Symbol (e.g. RELIANCE)" class="bg-gray-900 border border-gray-700 text-white text-sm rounded-lg pl-9 p-2 w-48 focus:ring-cyan-500 focus:border-cyan-500">
                    </div>
                    <button id="news-load-btn" class="bg-cyan-600 hover:bg-cyan-700 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors">
                        Load News
                    </button>
                </div>
            </div>
            
            <div class="grid grid-cols-1 lg:grid-cols-3 gap-4 flex-1 overflow-hidden">
                <!-- News Feed -->
                <div class="lg:col-span-2 glass-panel rounded-xl border border-gray-800/60 flex flex-col h-full overflow-hidden">
                    <div class="p-4 border-b border-gray-800/60 flex justify-between items-center bg-gray-900/50">
                        <h2 class="text-sm font-semibold text-gray-200">Company News & Events</h2>
                        <span id="news-count" class="text-xs text-gray-400">0 items</span>
                    </div>
                    <div id="news-loading" class="hidden flex-1 items-center justify-center">
                        <div class="animate-spin rounded-full h-8 w-8 border-b-2 border-cyan-400"></div>
                    </div>
                    <div id="news-feed" class="flex-1 overflow-y-auto p-4 space-y-4">
                        <div class="text-center text-gray-500 mt-10 text-sm">Enter a symbol and click Load News</div>
                    </div>
                </div>

                <!-- Event Feed -->
                <div class="glass-panel rounded-xl border border-gray-800/60 flex flex-col h-full overflow-hidden">
                    <div class="p-4 border-b border-gray-800/60 bg-gray-900/50">
                        <h2 class="text-sm font-semibold text-gray-200">Corporate Actions</h2>
                    </div>
                    <div id="events-feed" class="flex-1 overflow-y-auto p-4 space-y-4">
                        <div class="text-center text-gray-500 mt-10 text-sm">No events loaded</div>
                    </div>
                </div>
            </div>
        </div>
    `;

    document.getElementById('news-load-btn').addEventListener('click', loadData);
    document.getElementById('news-symbol').addEventListener('keypress', (e) => {
        if(e.key === 'Enter') loadData();
    });

    function escapeHTML(str) {
        if (!str) return '';
        const div = document.createElement('div');
        div.appendChild(document.createTextNode(str));
        return div.innerHTML;
    }

    async function loadData() {
        const symbol = escapeHTML(document.getElementById('news-symbol').value);
        if (!symbol) return;
        
        document.getElementById('news-loading').classList.remove('hidden');
        document.getElementById('news-feed').innerHTML = '';
        document.getElementById('events-feed').innerHTML = '';
        document.getElementById('news-count').textContent = 'Loading...';
        
        try {
            const [newsRes, eventsRes] = await Promise.all([
                fetch(`/api/v1/news/${symbol}`),
                fetch(`/api/v1/events/${symbol}`)
            ]);
            
            const newsPayload = await newsRes.json();
            const eventsPayload = await eventsRes.json();
            
            const news = newsPayload.data || [];
            const events = eventsPayload.data || [];
            
            document.getElementById('news-count').textContent = `${news.length || 0} items`;
            
            if (newsPayload.state === 'ERROR') {
                document.getElementById('news-feed').innerHTML = '<div class="text-center text-red-500 mt-10 text-sm">Error loading news.</div>';
            } else {
                renderNewsFeed(news);
            }
            
            if (eventsPayload.state === 'ERROR') {
                document.getElementById('events-feed').innerHTML = '<div class="text-center text-red-500 mt-10 text-sm">Error loading events.</div>';
            } else {
                renderEventsFeed(events);
            }
        } catch (e) {
            console.error(e);
            document.getElementById('news-feed').innerHTML = '<div class="text-center text-red-500 text-sm">Error loading data.</div>';
        } finally {
            document.getElementById('news-loading').classList.add('hidden');
        }
    }
    
    function renderNewsFeed(newsList) {
        const feed = document.getElementById('news-feed');
        if (!newsList || newsList.length === 0) {
            feed.innerHTML = '<div class="text-center text-gray-500 mt-10 text-sm">No recent news found.</div>';
            return;
        }
        
        let html = '';
        newsList.forEach(item => {
            const date = item.published_at ? new Date(item.published_at).toLocaleString() : "Unknown Date";
            let stateBadge = '';
            if (item.data_state === 'STALE') {
                stateBadge = '<span class="px-2 py-0.5 rounded text-[10px] font-mono bg-yellow-900/50 text-yellow-400">STALE</span>';
            }
            
            const aiText = item.rule_sentiment ? `(${item.rule_sentiment} Rule-Based)` : '';
            
            html += `
                <div class="bg-gray-900/50 border border-gray-800/60 rounded-lg p-4 hover:border-gray-700 transition-colors">
                    <div class="flex justify-between items-start mb-2">
                        <div class="flex gap-2 items-center flex-wrap">
                            <span class="px-2 py-1 rounded bg-gray-800 text-xs font-medium text-gray-300">${date}</span>
                            <span class="px-2 py-1 rounded ${getCategoryStyle(item.category)} text-[10px] font-medium uppercase tracking-wider">${item.category}</span>
                            <span class="text-xs text-gray-500">${stateBadge}</span>
                        </div>
                    </div>
                    <a href="${item.url}" target="_blank" rel="noopener noreferrer" class="text-sm font-semibold text-white hover:text-cyan-400 block mb-2 transition-colors">
                        ${escapeHTML(item.title)}
                    </a>
                    <p class="text-xs text-gray-400 line-clamp-2">${escapeHTML(item.summary)}</p>
                    
                    <div class="mt-3 flex gap-2">
                        <span class="text-[10px] uppercase font-mono px-1.5 py-0.5 rounded ${getSentimentStyle(item.sentiment_state)}">
                            ${item.sentiment_state} ${aiText}
                        </span>
                        <span class="text-[10px] text-gray-500 font-mono">Provenance: ${item.provenance}</span>
                    </div>
                </div>
            `;
        });
        feed.innerHTML = html;
    }

    function renderEventsFeed(eventsList) {
        const feed = document.getElementById('events-feed');
        if (!eventsList || eventsList.length === 0) {
            feed.innerHTML = '<div class="text-center text-gray-500 mt-10 text-sm">No upcoming corporate events.</div>';
            return;
        }
        
        let html = '';
        eventsList.forEach(item => {
            const date = item.scheduled_time ? new Date(item.scheduled_time).toLocaleDateString() : "Unknown Date";
            
            html += `
                <div class="bg-gray-900/50 border border-gray-800/60 rounded-lg p-3">
                    <div class="flex justify-between items-center mb-1">
                        <span class="px-2 py-0.5 rounded bg-cyan-900/30 text-cyan-400 border border-cyan-800/50 text-[10px] font-medium uppercase">${item.type}</span>
                        <span class="text-[10px] text-gray-500">${date}</span>
                    </div>
                    <h3 class="text-xs font-medium text-gray-200">${escapeHTML(item.title)}</h3>
                    <div class="mt-2 text-[10px] text-gray-500">Source: ${item.source} (${item.state})</div>
                </div>
            `;
        });
        feed.innerHTML = html;
    }
    
    function getCategoryStyle(cat) {
        switch(cat) {
            case 'CORPORATE_ACTION': return 'bg-purple-900/30 text-purple-400 border border-purple-800/50';
            case 'RESULTS': return 'bg-blue-900/30 text-blue-400 border border-blue-800/50';
            case 'MARKET': return 'bg-emerald-900/30 text-emerald-400 border border-emerald-800/50';
            default: return 'bg-gray-800 text-gray-400 border border-gray-700';
        }
    }
    
    function getSentimentStyle(sent) {
        switch(sent) {
            case 'POSITIVE': return 'text-emerald-400 bg-emerald-900/20';
            case 'NEGATIVE': return 'text-red-400 bg-red-900/20';
            default: return 'text-gray-400 bg-gray-800/50';
        }
    }
}