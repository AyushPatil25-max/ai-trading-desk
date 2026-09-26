export function renderChart(container) {
    container.innerHTML = `
        <div class="flex flex-col h-full space-y-4">
            <!-- Header Controls -->
            <div class="glass-panel p-4 rounded-xl border border-gray-800/60 flex flex-wrap gap-4 items-center justify-between">
                <div class="flex gap-2 items-center">
                    <div class="relative">
                        <i data-lucide="search" class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400"></i>
                        <input type="text" id="chart-symbol" placeholder="Symbol (e.g. RELIANCE)" class="bg-gray-900 border border-gray-700 text-white text-sm rounded-lg pl-9 p-2 w-48 focus:ring-cyan-500 focus:border-cyan-500">
                    </div>
                    
                    <select id="chart-tf" class="bg-gray-900 border border-gray-700 text-white text-sm rounded-lg p-2 focus:ring-cyan-500 focus:border-cyan-500">
                        <option value="1m">1m</option>
                        <option value="5m">5m</option>
                        <option value="15m">15m</option>
                        <option value="30m">30m</option>
                        <option value="1h">1h</option>
                        <option value="1D" selected>1D</option>
                        <option value="1W">1W</option>
                    </select>
                    
                    <button id="chart-load-btn" class="bg-cyan-600 hover:bg-cyan-700 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors">
                        Load Chart
                    </button>
                </div>
                
                <div class="flex gap-4 items-center text-sm">
                    <div id="chart-state-badge" class="hidden px-2 py-1 rounded text-xs font-mono"></div>
                    <div id="chart-quality-badge" class="hidden px-2 py-1 rounded text-xs font-mono bg-gray-800 text-gray-300"></div>
                    <div class="text-gray-400">LTP: <span id="chart-ltp" class="text-white font-mono">--</span></div>
                    <div class="text-gray-400" title="Tick update time from provider">Tick: <span id="chart-time" class="text-white font-mono">--</span></div>
                </div>
            </div>
            
            <!-- Indicators Toggle -->
            <div class="glass-panel p-3 rounded-xl border border-gray-800/60 flex flex-wrap gap-3 items-center text-xs">
                <span class="text-gray-400 font-medium mr-2">Overlays:</span>
                <label class="flex items-center gap-1 cursor-pointer"><input type="checkbox" id="t-sma20" class="rounded border-gray-700 bg-gray-900 text-cyan-500 focus:ring-cyan-500" checked> SMA20</label>
                <label class="flex items-center gap-1 cursor-pointer"><input type="checkbox" id="t-sma50" class="rounded border-gray-700 bg-gray-900 text-cyan-500 focus:ring-cyan-500"> SMA50</label>
                <label class="flex items-center gap-1 cursor-pointer"><input type="checkbox" id="t-sma200" class="rounded border-gray-700 bg-gray-900 text-cyan-500 focus:ring-cyan-500"> SMA200</label>
                <label class="flex items-center gap-1 cursor-pointer"><input type="checkbox" id="t-ema20" class="rounded border-gray-700 bg-gray-900 text-cyan-500 focus:ring-cyan-500"> EMA20</label>
                <label class="flex items-center gap-1 cursor-pointer"><input type="checkbox" id="t-ema50" class="rounded border-gray-700 bg-gray-900 text-cyan-500 focus:ring-cyan-500"> EMA50</label>
                <label class="flex items-center gap-1 cursor-pointer"><input type="checkbox" id="t-ema200" class="rounded border-gray-700 bg-gray-900 text-cyan-500 focus:ring-cyan-500"> EMA200</label>
                <label class="flex items-center gap-1 cursor-pointer"><input type="checkbox" id="t-vwap" class="rounded border-gray-700 bg-gray-900 text-cyan-500 focus:ring-cyan-500"> VWAP</label>
                <label class="flex items-center gap-1 cursor-pointer"><input type="checkbox" id="t-bb" class="rounded border-gray-700 bg-gray-900 text-cyan-500 focus:ring-cyan-500"> BB</label>
                <label class="flex items-center gap-1 cursor-pointer"><input type="checkbox" id="t-st" class="rounded border-gray-700 bg-gray-900 text-cyan-500 focus:ring-cyan-500"> SuperTrend</label>
                <label class="flex items-center gap-1 cursor-pointer"><input type="checkbox" id="t-pivots" class="rounded border-gray-700 bg-gray-900 text-cyan-500 focus:ring-cyan-500"> Pivots (S/R)</label>
                
                <div class="w-full h-px bg-gray-800/60 my-1"></div>
                
                <span class="text-gray-400 font-medium mr-2">Sub-Panels:</span>
                <label class="flex items-center gap-1 cursor-pointer"><input type="checkbox" id="t-vol" class="rounded border-gray-700 bg-gray-900 text-cyan-500 focus:ring-cyan-500" checked> Volume</label>
                <label class="flex items-center gap-1 cursor-pointer"><input type="checkbox" id="t-rsi" class="rounded border-gray-700 bg-gray-900 text-cyan-500 focus:ring-cyan-500" checked> RSI</label>
                <label class="flex items-center gap-1 cursor-pointer"><input type="checkbox" id="t-macd" class="rounded border-gray-700 bg-gray-900 text-cyan-500 focus:ring-cyan-500"> MACD</label>
                <label class="flex items-center gap-1 cursor-pointer"><input type="checkbox" id="t-adx" class="rounded border-gray-700 bg-gray-900 text-cyan-500 focus:ring-cyan-500"> ADX & DMI</label>
            </div>
            
            <!-- Chart Container -->
            <div class="flex-1 glass-panel rounded-xl border border-gray-800/60 overflow-hidden flex flex-col relative" id="charts-wrapper" style="min-height: 600px;">
                <div id="chart-loading" class="absolute inset-0 bg-gray-950/80 z-10 flex items-center justify-center hidden">
                    <div class="animate-spin rounded-full h-8 w-8 border-b-2 border-cyan-400"></div>
                </div>
                
                <div id="main-chart" class="flex-1 min-h-[350px]"></div>
                <div id="rsi-chart" class="h-32 border-t border-gray-800/60 hidden"></div>
                <div id="macd-chart" class="h-32 border-t border-gray-800/60 hidden"></div>
                <div id="adx-chart" class="h-32 border-t border-gray-800/60 hidden"></div>
            </div>
        </div>
    `;
    
    // Global references for cleanup/resize
    let charts = {};
    let activeSeries = {};
    let chartData = null;
    
    const colors = {
        bg: '#030712', text: '#9ca3af', grid: '#1f2937',
        up: '#10b981', down: '#ef4444',
        sma20: '#3b82f6', sma50: '#f59e0b', sma200: '#ef4444', 
        ema20: '#8b5cf6', ema50: '#d946ef', ema200: '#be123c',
        vwap: '#ec4899', bb: '#6366f1', stUp: '#10b981', stDown: '#ef4444',
        pivot: '#fbbf24', r: '#ef4444', s: '#10b981'
    };

    function initCharts() {
        if (!window.LightweightCharts) return;
        
        const chartOptions = {
            layout: { background: { type: 'solid', color: 'transparent' }, textColor: colors.text },
            grid: { vertLines: { color: colors.grid }, horzLines: { color: colors.grid } },
            crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
            timeScale: { timeVisible: true, secondsVisible: false, borderColor: colors.grid },
            rightPriceScale: { borderColor: colors.grid }
        };

        const mainChart = LightweightCharts.createChart(document.getElementById('main-chart'), chartOptions);
        charts.main = mainChart;
        
        const candleSeries = mainChart.addCandlestickSeries({
            upColor: colors.up, downColor: colors.down,
            borderVisible: false, wickUpColor: colors.up, wickDownColor: colors.down
        });
        activeSeries.candles = candleSeries;
        
        // Sync time scales
        const syncTime = (source, targets) => {
            source.timeScale().subscribeVisibleLogicalRangeChange(range => {
                if (range) targets.forEach(t => t.timeScale().setVisibleLogicalRange(range));
            });
        };
        
        const createSubChart = (id) => {
            const chart = LightweightCharts.createChart(document.getElementById(id), {
                ...chartOptions,
                timeScale: { ...chartOptions.timeScale, visible: false } // hide time axis on subcharts
            });
            syncTime(mainChart, [chart]);
            syncTime(chart, [mainChart]); // two-way sync
            return chart;
        };
        
        charts.rsi = createSubChart('rsi-chart');
        charts.macd = createSubChart('macd-chart');
        charts.adx = createSubChart('adx-chart');
        
        new ResizeObserver(entries => {
            for (let entry of entries) {
                if(entry.target.id === 'main-chart') charts.main.applyOptions({ width: entry.contentRect.width, height: entry.contentRect.height });
                if(entry.target.id === 'rsi-chart') charts.rsi.applyOptions({ width: entry.contentRect.width, height: entry.contentRect.height });
                if(entry.target.id === 'macd-chart') charts.macd.applyOptions({ width: entry.contentRect.width, height: entry.contentRect.height });
                if(entry.target.id === 'adx-chart') charts.adx.applyOptions({ width: entry.contentRect.width, height: entry.contentRect.height });
            }
        }).observe(document.getElementById('charts-wrapper'));
    }
    
    function parseTime(tStr) {
        const d = new Date(tStr);
        return d.getTime() / 1000;
    }

    async function loadData() {
        const symbol = document.getElementById('chart-symbol').value;
        const tf = document.getElementById('chart-tf').value;
        if (!symbol) return;
        
        document.getElementById('chart-loading').classList.remove('hidden');
        
        try {
            const res = await fetch(`/api/v1/charts?symbol=${symbol}&timeframe=${tf}`);
            const data = await res.json();
            
            if (!res.ok) {
                alert(data.detail || "Error loading chart");
                return;
            }
            
            chartData = data;
            
            // Update UI
            document.getElementById('chart-ltp').textContent = data.candles.length ? data.candles[data.candles.length-1].close.toFixed(2) : '--';
            
            let tickTime = data.last_market_update ? new Date(data.last_market_update).toLocaleTimeString() : '--';
            document.getElementById('chart-time').textContent = tickTime;
            
            const badge = document.getElementById('chart-state-badge');
            badge.classList.remove('hidden', 'bg-emerald-900/50', 'text-emerald-400', 'bg-yellow-900/50', 'text-yellow-400', 'bg-gray-800', 'text-gray-400', 'bg-red-900/50', 'text-red-400');
            
            if (data.data_state === 'LIVE') badge.classList.add('bg-emerald-900/50', 'text-emerald-400');
            else if (data.data_state === 'STALE') badge.classList.add('bg-yellow-900/50', 'text-yellow-400');
            else if (data.data_state === 'HISTORICAL') badge.classList.add('bg-gray-800', 'text-gray-400');
            else badge.classList.add('bg-red-900/50', 'text-red-400');
            badge.textContent = data.data_state;

            const qBadge = document.getElementById('chart-quality-badge');
            qBadge.classList.remove('hidden', 'text-emerald-400', 'text-yellow-400', 'text-red-400');
            if (data.data_quality === 'COMPLETE') qBadge.classList.add('text-emerald-400');
            else if (data.data_quality === 'PARTIAL') qBadge.classList.add('text-yellow-400');
            else qBadge.classList.add('text-red-400');
            qBadge.textContent = "Data: " + data.data_quality;
            
            renderData();
        } catch (e) {
            console.error(e);
            alert("Network error fetching chart data");
        } finally {
            document.getElementById('chart-loading').classList.add('hidden');
        }
    }
    
    function renderData() {
        if (!chartData || !charts.main) return;
        
        const d = chartData.candles.map(c => ({
            time: parseTime(c.timestamp), open: c.open, high: c.high, low: c.low, close: c.close,
            value: c.volume, color: c.close >= c.open ? colors.up + '80' : colors.down + '80',
            indicators: c.indicators, vwap: c.vwap
        }));
        
        // Remove old series safely
        Object.keys(activeSeries).forEach(k => {
            if (k !== 'candles') {
                try { charts.main.removeSeries(activeSeries[k]); } catch(e){}
                try { charts.rsi.removeSeries(activeSeries[k]); } catch(e){}
                try { charts.macd.removeSeries(activeSeries[k]); } catch(e){}
                try { charts.adx.removeSeries(activeSeries[k]); } catch(e){}
            }
        });
        
        activeSeries.candles.setData(d);
        
        // Volume
        if (document.getElementById('t-vol').checked) {
            activeSeries.vol = charts.main.addHistogramSeries({ color: '#26a69a', priceFormat: { type: 'volume' }, priceScaleId: '', scaleMargins: { top: 0.85, bottom: 0 } });
            activeSeries.vol.setData(d.map(x => ({ time: x.time, value: x.value, color: x.color })));
        }
        
        // Overlays
        const buildLine = (name, color, lineWidth=2, style=0) => {
            activeSeries[name] = charts.main.addLineSeries({ color, lineWidth, lineStyle: style, crosshairMarkerVisible: false });
            const sData = d.map(x => ({ time: x.time, value: x.indicators ? x.indicators[name] || x[name] : null })).filter(x => x.value !== null);
            activeSeries[name].setData(sData);
        };
        
        if (document.getElementById('t-sma20').checked) buildLine('sma20', colors.sma20);
        if (document.getElementById('t-sma50').checked) buildLine('sma50', colors.sma50);
        if (document.getElementById('t-sma200').checked) buildLine('sma200', colors.sma200);
        
        if (document.getElementById('t-ema20').checked) buildLine('ema20', colors.ema20);
        if (document.getElementById('t-ema50').checked) buildLine('ema50', colors.ema50);
        if (document.getElementById('t-ema200').checked) buildLine('ema200', colors.ema200);
        
        if (document.getElementById('t-vwap').checked) buildLine('vwap', colors.vwap);
        
        if (document.getElementById('t-bb').checked) {
            buildLine('bb_upper', colors.bb, 1, 2); 
            buildLine('bb_lower', colors.bb, 1, 2);
        }
        if (document.getElementById('t-st').checked) {
            buildLine('supertrend', colors.stUp, 2);
        }
        if (document.getElementById('t-pivots').checked) {
            buildLine('pivot', colors.pivot, 1, 2);
            buildLine('r1', colors.r, 1, 2);
            buildLine('s1', colors.s, 1, 2);
            buildLine('r2', colors.r, 1, 3);
            buildLine('s2', colors.s, 1, 3);
            buildLine('r3', colors.r, 1, 4);
            buildLine('s3', colors.s, 1, 4);
        }
        
        // Sub-Panels
        document.getElementById('rsi-chart').classList.toggle('hidden', !document.getElementById('t-rsi').checked);
        if (document.getElementById('t-rsi').checked) {
            activeSeries.rsi = charts.rsi.addLineSeries({ color: colors.sma20, lineWidth: 2 });
            activeSeries.rsi.setData(d.map(x => ({ time: x.time, value: x.indicators ? x.indicators.rsi14 : null })).filter(x => x.value !== null));
        }
        
        document.getElementById('macd-chart').classList.toggle('hidden', !document.getElementById('t-macd').checked);
        if (document.getElementById('t-macd').checked) {
            activeSeries.macd = charts.macd.addLineSeries({ color: colors.sma20, lineWidth: 2 });
            activeSeries.macd_sig = charts.macd.addLineSeries({ color: colors.sma50, lineWidth: 2 });
            activeSeries.macd_hist = charts.macd.addHistogramSeries({ color: colors.vwap });
            
            activeSeries.macd.setData(d.map(x => ({ time: x.time, value: x.indicators ? x.indicators.macd : null })).filter(x => x.value !== null));
            activeSeries.macd_sig.setData(d.map(x => ({ time: x.time, value: x.indicators ? x.indicators.macd_signal : null })).filter(x => x.value !== null));
            activeSeries.macd_hist.setData(d.map(x => ({ time: x.time, value: x.indicators ? x.indicators.macd_hist : null, color: (x.indicators && x.indicators.macd_hist >= 0) ? colors.up : colors.down })).filter(x => x.value !== null));
        }
        
        document.getElementById('adx-chart').classList.toggle('hidden', !document.getElementById('t-adx').checked);
        if (document.getElementById('t-adx').checked) {
            activeSeries.adx = charts.adx.addLineSeries({ color: colors.sma50, lineWidth: 2 });
            activeSeries.pdi = charts.adx.addLineSeries({ color: colors.up, lineWidth: 1 });
            activeSeries.mdi = charts.adx.addLineSeries({ color: colors.down, lineWidth: 1 });
            
            activeSeries.adx.setData(d.map(x => ({ time: x.time, value: x.indicators ? x.indicators.adx14 : null })).filter(x => x.value !== null));
            activeSeries.pdi.setData(d.map(x => ({ time: x.time, value: x.indicators ? x.indicators.plus_di : null })).filter(x => x.value !== null));
            activeSeries.mdi.setData(d.map(x => ({ time: x.time, value: x.indicators ? x.indicators.minus_di : null })).filter(x => x.value !== null));
        }
    }

    // Bind events
    document.getElementById('chart-load-btn').addEventListener('click', loadData);
    document.getElementById('chart-symbol').addEventListener('keypress', (e) => { if(e.key === 'Enter') loadData(); });
    
    // Auto-render when checkboxes change
    document.querySelectorAll('input[type="checkbox"]').forEach(cb => cb.addEventListener('change', renderData));
    
    // Attempt init shortly after DOM insertion
    setTimeout(initCharts, 50);
}
