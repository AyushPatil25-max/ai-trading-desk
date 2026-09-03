
        // ════════════════════ IPO INTELLIGENCE ════════════════════
        async function fetchIPOData(status = '') {
            try {
                let url = '/api/ipo/list';
                if (status) {
                    url += `?status=${status}`;
                }
                const response = await fetch(url);
                const data = await response.json();
                const tbody = document.getElementById('ipoTableBody');
                if (!tbody) return;

                if (!data || data.length === 0) {
                    tbody.innerHTML = `<tr><td colspan="11" class="py-6 text-center text-zinc-600 font-sans">No IPOs found.</td></tr>`;
                    return;
                }

                tbody.innerHTML = '';
                for (const ipo of data) {
                    let gmpStr = '--';
                    let estListingStr = '--';
                    if (ipo.latest_gmp) {
                        gmpStr = `₹${ipo.latest_gmp.gmp_value} (${ipo.latest_gmp.gmp_percentage?.toFixed(2) || 0}%)`;
                        estListingStr = `₹${ipo.latest_gmp.estimated_listing_price?.toFixed(2) || '--'}`;
                    }
                    
                    let subStr = '--';
                    if (ipo.latest_subscription) {
                        subStr = `${ipo.latest_subscription.total?.toFixed(2)}x`;
                    }
                    
                    let issueSizeStr = ipo.total_issue_size ? `₹${(ipo.total_issue_size / 10000000).toFixed(2)} Cr` : '--';
                    let priceBandStr = ipo.issue_price ? `₹${ipo.issue_price}` : (ipo.price_band_low ? `₹${ipo.price_band_low}-₹${ipo.price_band_high}` : '--');
                    let minInvStr = ipo.minimum_investment ? `₹${ipo.minimum_investment}` : '--';

                    const tr = document.createElement('tr');
                    tr.className = "hover:bg-zinc-900/50 transition cursor-pointer";
                    tr.onclick = () => analyzeIpo(ipo.ipo_id);
                    tr.innerHTML = `
                        <td class="py-3 px-2 text-white font-bold">${ipo.company_name}</td>
                        <td class="py-3 px-2 text-zinc-400">${ipo.ipo_type}</td>
                        <td class="py-3 px-2">
                            <span class="px-2 py-0.5 rounded text-[10px] ${ipo.status === 'OPEN' ? 'bg-emerald-900 text-emerald-400' : 'bg-zinc-800 text-zinc-400'}">${ipo.status}</span>
                        </td>
                        <td class="py-3 px-2 text-zinc-300">${issueSizeStr}</td>
                        <td class="py-3 px-2 text-cyan-300">${priceBandStr}</td>
                        <td class="py-3 px-2 text-zinc-400">${minInvStr}</td>
                        <td class="py-3 px-2 text-amber-400 font-bold">${gmpStr}</td>
                        <td class="py-3 px-2 text-amber-400">${estListingStr}</td>
                        <td class="py-3 px-2 text-emerald-300">${subStr}</td>
                        <td class="py-3 px-2" id="verdict_${ipo.ipo_id}">
                            <span class="text-[10px] text-zinc-600">Pending Analysis</span>
                        </td>
                        <td class="py-3 px-2">
                            <button class="bg-indigo-900/50 hover:bg-indigo-800 text-indigo-300 px-2 py-1 rounded text-[10px]" onclick="event.stopPropagation(); analyzeIpo('${ipo.ipo_id}')">Analyze</button>
                        </td>
                    `;
                    tbody.appendChild(tr);
                }
            } catch (err) {
                console.error("Failed to fetch IPO data", err);
            }
        }

        async function analyzeIpo(ipoId) {
            const vCell = document.getElementById(`verdict_${ipoId}`);
            if (vCell) vCell.innerHTML = `<span class="text-[10px] text-cyan-400 animate-pulse">Analyzing...</span>`;
            try {
                const response = await fetch(`/api/ipo/${ipoId}/analysis`);
                const data = await response.json();
                if (vCell) {
                    let color = 'text-zinc-400 bg-zinc-800';
                    if (data.verdict === 'STRONG') color = 'text-emerald-400 bg-emerald-900';
                    if (data.verdict === 'POSITIVE') color = 'text-emerald-300 bg-emerald-900/50';
                    if (data.verdict === 'NEUTRAL') color = 'text-yellow-400 bg-yellow-900';
                    if (data.verdict === 'WEAK' || data.verdict === 'AVOID') color = 'text-rose-400 bg-rose-900';
                    
                    vCell.innerHTML = `<span class="px-2 py-0.5 rounded text-[10px] font-bold ${color}">${data.verdict}</span>`;
                }
            } catch (err) {
                console.error("Failed to analyze IPO", err);
                if (vCell) vCell.innerHTML = `<span class="text-[10px] text-rose-400">Error</span>`;
            }
        }
    
    