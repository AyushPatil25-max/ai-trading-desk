
        let autoRefreshInterval = null;
        let isAutoRefreshActive = true;

        // Tab Switching
        function switchMainTab(tab) {
            const tabs = ['orchestrator', 'scanner', 'broker', 'monitoring', 'factors', 'streaming', 'providers', 'alerts', 'resilience', 'observability', 'backtest', 'robustness', 'forward', 'certification', 'cluster', 'ipo', 'governance'];
            tabs.forEach(t => {
                const sec = document.getElementById(`tab${t.charAt(0).toUpperCase() + t.slice(1)}`);
                const btn = document.getElementById(`tabBtn${t.charAt(0).toUpperCase() + t.slice(1)}`);
                if (sec && btn) {
                    if (t === tab) {
                        sec.classList.remove('hidden');
                        btn.classList.add('tab-active');
                    } else {
                        sec.classList.add('hidden');
                        btn.classList.remove('tab-active');
                    }
                }
            });
            if (tab === 'scanner') fetchOpportunities();
            if (tab === 'broker') fetchBrokerData();
            if (tab === 'monitoring') {
                fetchMonitoringData();
                fetchReliabilityData();
            }
            if (tab === 'factors') fetchFactorAndRiskData();
            if (tab === 'streaming') fetchStreamingData();
            if (tab === 'providers') fetchProviderHealth();
            if (tab === 'alerts') { fetchAlertStatus(); fetchAlertRules(); }
            if (tab === 'resilience') { fetchResilienceStatus(); fetchResilienceScorecard(); }
            if (tab === 'observability') { fetchObservabilityHealth(); fetchPaperWorkersStatus(); }
            if (tab === 'backtest') { fetchReplayRuns(); }
            if (tab === 'robustness') { fetchRobustnessReports(); }
            if (tab === 'forward') { fetchForwardSessions(); }
            if (tab === 'certification') { fetchSystemCertificationData(); }
            if (tab === 'cluster') { fetchDistributedClusterData(); }
            if (tab === 'ipo') { fetchIPOData(); }
            if (tab === 'governance') { fetchGovernanceData(); }
        }

        // Auto Refresh Control
        function toggleAutoRefresh() {
            isAutoRefreshActive = !isAutoRefreshActive;
            const btn = document.getElementById('autoRefreshBtn');
            const dot = document.getElementById('refreshDot');
            const lbl = document.getElementById('refreshLabel');
            if (isAutoRefreshActive) {
                dot.className = "w-2 h-2 rounded-full bg-cyan-400 animate-pulse";
                lbl.innerText = "Auto-Refresh (4s)";
                startAutoRefresh();
            } else {
                dot.className = "w-2 h-2 rounded-full bg-zinc-600";
                lbl.innerText = "Auto-Refresh (Paused)";
                stopAutoRefresh();
            }
        }

        function startAutoRefresh() {
            if (autoRefreshInterval) clearInterval(autoRefreshInterval);
            autoRefreshInterval = setInterval(() => {
                refreshActiveTabData();
            }, 4000);
        }

        function stopAutoRefresh() {
            if (autoRefreshInterval) {
                clearInterval(autoRefreshInterval);
                autoRefreshInterval = null;
            }
        }

        function refreshActiveTabData() {
            fetchSystemHealthTop();
            const orchestrator = document.getElementById('tabOrchestrator');
            const scanner = document.getElementById('tabScanner');
            const broker = document.getElementById('tabBroker');
            const monitoring = document.getElementById('tabMonitoring');
            const factors = document.getElementById('tabFactors');
            const streaming = document.getElementById('tabStreaming');
            const ipo = document.getElementById('tabIpo');
            const governance = document.getElementById('tabGovernance');

            if (orchestrator && !orchestrator.classList.contains('hidden')) {
                fetchLatestRunAudit();
            } else if (scanner && !scanner.classList.contains('hidden')) {
                fetchOpportunities();
            } else if (broker && !broker.classList.contains('hidden')) {
                fetchBrokerData();
            } else if (monitoring && !monitoring.classList.contains('hidden')) {
                fetchMonitoringData();
                fetchReliabilityData();
            } else if (factors && !factors.classList.contains('hidden')) {
                fetchFactorAndRiskData();
            } else if (ipo && !ipo.classList.contains('hidden')) {
                fetchIPOData();
            } else if (streaming && !streaming.classList.contains('hidden')) {
                fetchStreamingData();
            }
        }

        // ── 1. Top System Health & Broker Status ──
        async function fetchSystemHealthTop() {
            try {
                // Fetch Broker Status
                const brokerRes = await fetch('/api/broker/status');
                if (brokerRes.ok) {
                    const b = await brokerRes.json();
                    document.getElementById('topBrokerName').innerText = `${b.active_broker_name} (${b.broker_mode})`;
                }

                // Fetch System Health
                const monRes = await fetch('/api/monitor/health');
                if (monRes.ok) {
                    const m = await monRes.json();
                    const dot = document.getElementById('topHealthDot');
                    const txt = document.getElementById('topHealthText');
                    const sub = document.getElementById('topHealthSubsystems');
                    txt.innerText = m.overall_health;
                    sub.innerText = `${m.healthy_components_count}/${m.components_count} OK`;

                    if (m.overall_health === 'HEALTHY') {
                        dot.className = "w-2.5 h-2.5 rounded-full bg-emerald-400";
                        txt.className = "font-mono text-xs font-bold text-emerald-400";
                    } else if (m.overall_health === 'DEGRADED') {
                        dot.className = "w-2.5 h-2.5 rounded-full bg-amber-400 animate-pulse";
                        txt.className = "font-mono text-xs font-bold text-amber-300";
                    } else {
                        dot.className = "w-2.5 h-2.5 rounded-full bg-rose-500 animate-ping";
                        txt.className = "font-mono text-xs font-bold text-rose-400";
                    }

                    // Kill Switch Sync
                    const ksBtn = document.getElementById('killSwitchBtn');
                    const ksLbl = document.getElementById('killSwitchLabel');
                    if (m.kill_switch_active) {
                        ksLbl.innerText = "DISARM KILL SWITCH";
                        ksBtn.className = "bg-emerald-600 hover:bg-emerald-500 text-white font-bold text-xs px-3.5 py-1.5 rounded-lg transition shadow flex items-center gap-1.5 font-mono";
                    } else {
                        ksLbl.innerText = "TRIGGER KILL SWITCH";
                        ksBtn.className = "bg-rose-600 hover:bg-rose-500 text-white font-bold text-xs px-3.5 py-1.5 rounded-lg transition shadow flex items-center gap-1.5 font-mono";
                    }
                }
            } catch (err) {
                console.warn("Error fetching system health:", err);
            }
        }

        // Toggle Kill Switch
        async function toggleKillSwitch() {
            const ksLbl = document.getElementById('killSwitchLabel');
            const isTriggered = ksLbl.innerText.includes("DISARM");
            const action = isTriggered ? "disarm" : "trigger";

            try {
                const res = await fetch('/api/telemetry/kill-switch', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ action: action, reason: "Operator dashboard action" })
                });
                if (res.ok) {
                    fetchSystemHealthTop();
                }
            } catch (err) {
                alert("Kill switch toggle failed: " + err.message);
            }
        }

        // ── 2. Run Trading OS Pipeline ──
        async function runTradingOSPipeline() {
            const symbol = document.getElementById('symbolInput').value.trim();
            const price = parseFloat(document.getElementById('priceInput').value) || 3500.0;
            const btn = document.getElementById('runPipelineBtn');

            btn.disabled = true;
            btn.innerHTML = "<span>Executing...</span>";

            try {
                const res = await fetch('/api/trading-os/run', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ symbol: symbol, current_price: price, fill_ratio: 1.0 })
                });
                const summary = await res.json();
                if (!res.ok) throw new Error(summary.detail || "Trading OS run failed");

                await fetchLatestRunAudit();
            } catch (err) {
                alert("Execution Error: " + err.message);
            } finally {
                btn.disabled = false;
                btn.innerHTML = "<span>Run Trading OS Pipeline</span>";
            }
        }

        // Quick Legacy Analysis
        async function runQuickLegacyAnalysis() {
            const symbol = document.getElementById('symbolInput').value.trim();
            const btn = document.getElementById('quickAnalyzeBtn');
            btn.disabled = true;
            btn.innerText = "Analyzing...";

            try {
                const res = await fetch(`/api/analyze?symbol=${encodeURIComponent(symbol)}`);
                const data = await res.json();
                if (!res.ok) throw new Error(data.detail || "Analysis failed");

                alert(`Quick Analysis for ${symbol}:\nClose: Rs ${data.market_data.latest_close}\nVerdict: ${data.final_verdict}\nTechnical Score: ${data.technical.technical_score}/10`);
            } catch (err) {
                alert("Quick analysis error: " + err.message);
            } finally {
                btn.disabled = false;
                btn.innerText = "Quick Metrics";
            }
        }

        // ── 3. Fetch & Render Full Audit Run ──
        async function fetchLatestRunAudit() {
            try {
                const res = await fetch('/api/trading-os/runs/latest');
                if (!res.ok) return;
                const run = await res.json();
                if (!run) return;

                // Run Metadata
                document.getElementById('currentRunId').innerText = run.run_id.slice(-8);
                document.getElementById('currentRunDuration').innerText = `${run.total_duration_ms.toFixed(1)} ms`;
                document.getElementById('currentRunStatus').innerText = run.final_status;
                document.getElementById('currentRunStatus').className = run.final_status === 'COMPLETED' ? 'font-bold text-emerald-400' : 'font-bold text-amber-400';

                // Stepper Status Indicators
                setStepStatus('stepEvidence', 'stepEvidenceStatus', run.evidence ? 'OK' : 'SKIPPED', run.evidence ? 'text-emerald-400' : 'text-zinc-500');
                setStepStatus('stepDebate', 'stepDebateStatus', run.debate ? 'OK' : 'SKIPPED', run.debate ? 'text-emerald-400' : 'text-zinc-500');
                setStepStatus('stepCommittee', 'stepCommitteeStatus', run.committee_decision ? 'OK' : 'SKIPPED', run.committee_decision ? 'text-emerald-400' : 'text-zinc-500');
                setStepStatus('stepRegime', 'stepRegimeStatus', run.regime ? 'OK' : 'SKIPPED', run.regime ? 'text-emerald-400' : 'text-zinc-500');
                setStepStatus('stepScenario', 'stepScenarioStatus', run.scenario ? 'OK' : 'SKIPPED', run.scenario ? 'text-emerald-400' : 'text-zinc-500');
                setStepStatus('stepRiskSizing', 'stepRiskStatus', run.risk ? (run.risk.veto_applied ? 'VETO' : 'OK') : 'SKIPPED', run.risk ? (run.risk.veto_applied ? 'text-rose-400' : 'text-emerald-400') : 'text-zinc-500');
                setStepStatus('stepPreflight', 'stepPreflightStatus', run.preflight ? run.preflight.status : 'SKIPPED', run.preflight && run.preflight.status === 'APPROVED' ? 'text-emerald-400' : 'text-amber-400');

                // Committee Verdict Banner
                const comm = run.committee_decision;
                if (comm) {
                    const commDec = comm.recommendation || comm.decision || 'INDETERMINATE';
                    const commConv = comm.conviction_score !== undefined ? comm.conviction_score : (comm.conviction || 0.0);
                    const commSummary = comm.decision_summary || comm.synthesis_rationale || comm.investment_thesis || "Committee synthesis generated.";
                    const commSupp = (comm.supporting_evidence_ids && comm.supporting_evidence_ids.length > 0) ? comm.supporting_evidence_ids : (comm.supporting_factors || []);
                    const commOpp = (comm.key_risks && comm.key_risks.length > 0) ? comm.key_risks : (comm.opposing_factors || []);

                    document.getElementById('verdictTitle').innerText = `${commDec} (${run.symbol})`;
                    document.getElementById('verdictActionBadge').innerText = comm.action_recommended || commDec;
                    document.getElementById('verdictActionBadge').className = commDec.includes('BUY') 
                        ? "px-3 py-1 rounded-full text-xs font-mono font-bold bg-emerald-950 text-emerald-300 border border-emerald-800"
                        : "px-3 py-1 rounded-full text-xs font-mono font-bold bg-rose-950 text-rose-300 border border-rose-800";
                    document.getElementById('verdictSummaryText').innerText = commSummary;

                    document.getElementById('committeeActionText').innerText = comm.action_recommended || commDec;
                    document.getElementById('committeeConvictionText').innerText = commConv.toFixed(2);
                    document.getElementById('summaryConviction').innerText = commConv.toFixed(2);
                    document.getElementById('committeeDecisionBadge').innerText = comm.state || comm.status || "APPROVED";
                    document.getElementById('committeeRationale').innerText = commSummary;

                    renderList('committeeSupportingList', commSupp);
                    renderList('committeeOpposingList', commOpp);
                }

                // Adversarial Debate Render
                const deb = run.debate;
                if (deb) {
                    document.getElementById('debateStatusBadge').innerText = deb.final_debate_state || deb.status || "COMPLETED";

                    // Bull Case
                    const bullArgs = deb.strongest_bull_arguments || [];
                    const bullConf = deb.bull_case ? deb.bull_case.confidence : (bullArgs.length > 0 ? bullArgs[0].confidence : deb.confidence || 0.0);
                    document.getElementById('bullConvictionScore').innerText = bullConf.toFixed(2);
                    document.getElementById('bullThesis').innerText = deb.bull_case ? deb.bull_case.core_thesis : (bullArgs.length > 0 ? bullArgs[0].claim : "Bull argument formulated.");
                    const bullKey = deb.bull_case ? deb.bull_case.supporting_evidence : bullArgs.map(a => a.claim);
                    renderList('bullKeyPoints', bullKey);

                    // Bear Case
                    const bearArgs = deb.strongest_bear_arguments || [];
                    const bearConf = deb.bear_case ? deb.bear_case.confidence : (bearArgs.length > 0 ? bearArgs[0].confidence : deb.confidence || 0.0);
                    document.getElementById('bearConvictionScore').innerText = bearConf.toFixed(2);
                    document.getElementById('bearThesis').innerText = deb.bear_case ? deb.bear_case.attack_summary : (bearArgs.length > 0 ? bearArgs[0].claim : "Bear argument formulated.");
                    const bearKey = deb.bear_case ? deb.bear_case.bull_claims_challenged : bearArgs.map(a => a.claim);
                    renderList('bearKeyPoints', bearKey);

                    // Rounds & Challenges
                    const rounds = deb.rounds || [];
                    document.getElementById('debateRoundsCount').innerText = `${rounds.length} Rounds`;
                    const rCont = document.getElementById('debateRoundsContainer');

                    let allChallenges = [];
                    rounds.forEach(r => {
                        if (r.challenges) {
                            r.challenges.forEach(c => {
                                allChallenges.push({
                                    challenge: c.challenge || c.explanation || "Adversarial challenge",
                                    rebuttal: r.rebuttals && r.rebuttals.length > 0 ? r.rebuttals[0].response : "Defended with evidence",
                                });
                            });
                        }
                    });
                    if (deb.challenges_and_rebuttals && deb.challenges_and_rebuttals.length > 0) {
                        allChallenges = deb.challenges_and_rebuttals;
                    }

                    if (allChallenges.length > 0) {
                        rCont.innerHTML = allChallenges.map((cr, idx) => `
                            <div class="p-2.5 rounded bg-zinc-900/90 border border-zinc-800/80 space-y-1">
                                <div class="text-[10px] text-amber-400 font-bold">Round ${idx+1} Challenge:</div>
                                <div class="text-[11px] text-zinc-300 font-sans">${cr.challenge}</div>
                                <div class="text-[10px] text-cyan-400 font-bold pt-1">Rebuttal:</div>
                                <div class="text-[11px] text-zinc-300 font-sans">${cr.rebuttal}</div>
                            </div>
                        `).join('');
                    } else {
                        rCont.innerHTML = '<div class="text-zinc-600 text-center py-2 text-xs font-sans">No adversarial challenges generated.</div>';
                    }

                    const contrCount = (deb.unresolved_contradictions || []).length + (deb.contradiction_analyses || []).length;
                    document.getElementById('contradictionText').innerText = contrCount > 0 
                        ? `Contradictions Evaluated: ${contrCount} across evidence sources.`
                        : "No critical contradictions detected.";
                }

                // Regime Intelligence Render
                const reg = run.regime;
                if (reg) {
                    document.getElementById('regimeBadge').innerText = reg.regime_type;
                    document.getElementById('regimeName').innerText = reg.regime_type;
                    document.getElementById('summaryRegime').innerText = reg.regime_type;
                    document.getElementById('regimeConfidence').innerText = `${(reg.confidence * 100).toFixed(1)}%`;
                    document.getElementById('regimeTrend').innerText = reg.trend_state || "--";
                    document.getElementById('regimeVolatility').innerText = reg.volatility_state || "--";
                    document.getElementById('regimeLiquidity').innerText = reg.liquidity_state || "--";
                }

                // Scenarios / Stress Tests
                const scen = run.scenario;
                if (scen) {
                    document.getElementById('scenarioStatusBadge').innerText = scen.stress_test_passed ? "PASSED" : "CAUTION";
                    document.getElementById('scenarioName').innerText = scen.primary_scenario || "Baseline";
                    document.getElementById('scenarioDownside').innerText = `${(scen.downside_risk_pct * 100).toFixed(1)}%`;
                    document.getElementById('scenarioUpside').innerText = `${(scen.upside_potential_pct * 100).toFixed(1)}%`;
                    document.getElementById('scenarioImpact').innerText = scen.expected_impact || "--";
                    document.getElementById('scenarioSummary').innerText = scen.summary || "--";
                }

                // Risk & Position Sizing
                const rsk = run.risk;
                const sz = run.sizing;
                if (rsk) {
                    document.getElementById('summaryRisk').innerText = rsk.veto_applied ? "VETOED" : "CLEARED";
                    document.getElementById('summaryRisk').className = rsk.veto_applied ? "text-lg font-bold text-rose-400" : "text-lg font-bold text-emerald-400";
                    document.getElementById('riskVetoStatus').innerText = rsk.veto_applied ? `VETO: ${rsk.reason || ''}` : "CLEARED";
                    document.getElementById('riskVetoStatus').className = rsk.veto_applied ? "font-bold text-rose-400" : "font-bold text-emerald-400";
                }
                if (sz) {
                    document.getElementById('summarySize').innerText = `${sz.approved_quantity} shs`;
                    document.getElementById('riskApprovedShares').innerText = `${sz.approved_quantity} shs`;
                    document.getElementById('riskStopLoss').innerText = sz.stop_loss_price ? `Rs ${sz.stop_loss_price.toFixed(2)}` : "--";
                }

                // Pre-Flight Gatekeeper
                const pf = run.preflight;
                if (pf) {
                    document.getElementById('preflightGateStatus').innerText = pf.status;
                    document.getElementById('riskPreflightBadge').innerText = pf.status;
                    document.getElementById('preflightFreshness').innerText = pf.data_quality || "FRESH";
                }

            } catch (err) {
                console.warn("Error fetching latest run audit:", err);
            }
        }

        function setStepStatus(boxId, textId, text, colorClass) {
            const el = document.getElementById(textId);
            if (el) {
                el.innerText = text;
                el.className = `font-bold mt-0.5 ${colorClass}`;
            }
        }

        function renderList(elemId, items) {
            const el = document.getElementById(elemId);
            if (!el) return;
            if (!items || items.length === 0) {
                el.innerHTML = '<li class="text-zinc-600">None</li>';
            } else {
                el.innerHTML = items.map(it => `<li>${it}</li>`).join('');
            }
        }

        // ── 4. Opportunity Scanner Tab Data ──
        async function fetchOpportunities() {
            try {
                const statusRes = await fetch('/api/opportunities/scanner/status');
                if (statusRes.ok) {
                    const st = await statusRes.json();
                    document.getElementById('scannerWorkerStateBadge').innerText = st.state;
                    document.getElementById('scannerQueueSize').innerText = st.queue_size;
                    document.getElementById('scannerCyclesCompleted').innerText = st.cycles_completed;
                    document.getElementById('scannerConsecutiveErrors').innerText = st.consecutive_errors;
                }

                const candRes = await fetch('/api/opportunities?limit=50');
                if (candRes.ok) {
                    const candidates = await candRes.json();
                    document.getElementById('candidateCountBadge').innerText = `${candidates.length} Candidates Discovered`;
                    const tbody = document.getElementById('candidatesTableBody');
                    if (candidates.length === 0) {
                        tbody.innerHTML = '<tr><td colspan="9" class="py-6 text-center text-zinc-600 font-sans">No candidates discovered.</td></tr>';
                    } else {
                        tbody.innerHTML = candidates.map(c => `
                            <tr>
                                <td class="py-2 text-cyan-300 font-bold">${c.symbol}</td>
                                <td><span class="px-1.5 py-0.5 rounded text-[10px] bg-zinc-800 text-zinc-300">${c.priority}</span></td>
                                <td><span class="px-1.5 py-0.5 rounded text-[10px] ${c.status === 'APPROVED' ? 'bg-emerald-950 text-emerald-300' : 'bg-zinc-800 text-zinc-400'}">${c.status}</span></td>
                                <td class="text-cyan-400 font-bold">${c.discovery_score.toFixed(2)}</td>
                                <td>${c.stage_a_indicators.rsi ? c.stage_a_indicators.rsi.toFixed(1) : '--'}</td>
                                <td>${c.stage_a_indicators.trend || '--'}</td>
                                <td class="${c.direction === 'BUY' ? 'text-emerald-400' : 'text-rose-400'} font-bold">${c.direction}</td>
                                <td class="text-zinc-500">${c.discovered_at ? new Date(c.discovered_at).toLocaleTimeString() : '--'}</td>
                                <td><button onclick="inspectCandidate('${c.symbol}')" class="text-cyan-400 hover:underline">Inspect</button></td>
                            </tr>
                        `).join('');
                    }
                }
            } catch (err) {
                console.warn("Opportunity fetch error:", err);
            }
        }

        async function controlScanner(action) {
            try {
                const res = await fetch(`/api/opportunities/scanner/${action}`, { method: 'POST' });
                if (res.ok) {
                    fetchOpportunities();
                }
            } catch (err) {
                alert(`Scanner ${action} failed: ` + err.message);
            }
        }

        async function triggerImmediateScan() {
            try {
                const res = await fetch('/api/opportunities/scan', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ universe_id: "NIFTY_50" }) });
                if (res.ok) {
                    fetchOpportunities();
                }
            } catch (err) {
                alert("Trigger scan failed: " + err.message);
            }
        }

        // ── Phase 16: Live Evaluation & Staged Execution Readiness ──
        async function fetchLiveEvaluationData() {
            try {
                // Fetch matrix
                const matRes = await fetch('/api/evaluation/live/agent-matrix');
                if (matRes.ok) {
                    const mat = await matRes.json();
                    const elAcc = document.getElementById('evalOverallAccuracy');
                    if (elAcc) elAcc.innerText = `${(mat.overall_accuracy * 100).toFixed(1)}%`;
                    const elRuns = document.getElementById('evalTotalRuns');
                    if (elRuns) elRuns.innerText = mat.total_runs_evaluated;
                    const elTrades = document.getElementById('evalTotalTrades');
                    if (elTrades) elTrades.innerText = mat.total_completed_trades;

                    const deb = mat.debate_summary;
                    if (deb) {
                        const bG = document.getElementById('evalBullGrade');
                        const bS = document.getElementById('evalBullScore');
                        const bA = document.getElementById('evalBullAcc');
                        if (bG) bG.innerText = deb.bull_grade;
                        if (bS) bS.innerText = deb.bull_skill_score.toFixed(1);
                        if (bA) bA.innerText = `${(deb.bull_accuracy * 100).toFixed(0)}%`;

                        const rG = document.getElementById('evalBearGrade');
                        const rS = document.getElementById('evalBearScore');
                        const rA = document.getElementById('evalBearAcc');
                        if (rG) rG.innerText = deb.bear_grade;
                        if (rS) rS.innerText = deb.bear_skill_score.toFixed(1);
                        if (rA) rA.innerText = `${(deb.bear_accuracy * 100).toFixed(0)}%`;
                    }

                    const cal = mat.calibration;
                    if (cal) {
                        const brierEl = document.getElementById('evalBrierScore');
                        const brierG = document.getElementById('evalBrierGrade');
                        if (brierEl) brierEl.innerText = cal.brier_score.toFixed(4);
                        if (brierG) {
                            brierG.innerText = cal.calibration_grade;
                            brierG.className = cal.calibration_grade === 'EXCELLENT' 
                                ? 'text-[10px] px-1.5 py-0.5 rounded bg-emerald-950 text-emerald-300 border border-emerald-800'
                                : 'text-[10px] px-1.5 py-0.5 rounded bg-zinc-800 text-zinc-300 border border-zinc-700';
                        }
                        const eceEl = document.getElementById('evalECE');
                        if (eceEl) eceEl.innerText = cal.expected_calibration_error.toFixed(3);
                        const overEl = document.getElementById('evalOverconf');
                        if (overEl) overEl.innerText = (cal.overconfidence_score >= 0 ? '+' : '') + cal.overconfidence_score.toFixed(2);
                    }

                    // Render specialists grid
                    const sGrid = document.getElementById('evalSpecialistsGrid');
                    const weights = mat.dynamic_weight_adjustments || {};
                    if (sGrid && mat.specialists && mat.specialists.length > 0) {
                        sGrid.innerHTML = mat.specialists.map(s => {
                            const w = weights[s.specialist_name] || 1.0;
                            const wColor = w > 1.0 ? 'text-emerald-400' : (w < 1.0 ? 'text-amber-400' : 'text-zinc-400');
                            const sShort = s.specialist_name.replace('Specialist', '');
                            return `
                                <div class="p-1 rounded bg-zinc-900/80 border border-zinc-800" title="${s.specialist_name}: ${s.letter_grade} (${s.skill_score})">
                                    <span class="text-zinc-400 block truncate">${sShort}</span>
                                    <span class="text-[9px] font-bold text-zinc-300">${s.letter_grade}</span>
                                    <span class="${wColor} font-bold ml-1">${w.toFixed(2)}x</span>
                                </div>
                            `;
                        }).join('');
                    }
                }

                // Fetch readiness
                const readRes = await fetch('/api/evaluation/live/readiness');
                if (readRes.ok) {
                    const rpt = await readRes.json();
                    const tierBadge = document.getElementById('stagedTierBadge');
                    if (tierBadge) {
                        tierBadge.innerText = rpt.active_tier.replace(/_/g, ' ');
                        tierBadge.className = rpt.is_tier3_certified
                            ? 'text-[10px] font-mono px-2 py-0.5 rounded bg-emerald-950 text-emerald-300 border border-emerald-700 font-bold'
                            : 'text-[10px] font-mono px-2 py-0.5 rounded bg-cyan-950 text-cyan-300 border border-cyan-700 font-bold';
                    }

                    const stEl = document.getElementById('evalReadinessStatus');
                    if (stEl) {
                        stEl.innerText = rpt.is_tier3_certified ? "CERTIFIED" : "AUDITED";
                        stEl.className = rpt.is_tier3_certified ? "font-bold text-emerald-400" : "font-bold text-amber-400";
                    }
                    const dotEl = document.getElementById('evalReadinessDot');
                    if (dotEl) {
                        dotEl.className = rpt.is_tier3_certified ? "w-2 h-2 rounded-full bg-emerald-400" : "w-2 h-2 rounded-full bg-amber-400";
                    }
                    const sumEl = document.getElementById('evalReadinessSummary');
                    if (sumEl) sumEl.innerText = rpt.summary_message;
                }
            } catch (err) {
                console.warn("Live evaluation fetch error:", err);
            }
        }

        async function triggerLiveEvaluation() {
            try {
                const res = await fetch('/api/evaluation/live/evaluate', { method: 'POST' });
                if (res.ok) {
                    fetchLiveEvaluationData();
                }
            } catch (err) {
                alert("Evaluation trigger failed: " + err.message);
            }
        }

        // ── Phase 17: Factor Attribution & Automated Risk Optimization ──
        async function fetchFactorAndRiskData() {
            try {
                // 1. Fetch Exposures
                const expRes = await fetch('/api/factors/exposures');
                if (expRes.ok) {
                    const exp = await expRes.json();
                    const statusBadge = document.getElementById('factorDataStatusBadge');
                    if (statusBadge) {
                        statusBadge.innerText = exp.data_status;
                        statusBadge.className = exp.data_status === 'AVAILABLE'
                            ? 'text-[10px] font-mono px-2 py-0.5 rounded bg-emerald-950 text-emerald-300 border border-emerald-800'
                            : 'text-[10px] font-mono px-2 py-0.5 rounded bg-zinc-800 text-zinc-300 border border-zinc-700';
                    }

                    const elAlpha = document.getElementById('factorAlpha');
                    if (elAlpha) elAlpha.innerText = `${(exp.alpha * 100).toFixed(2)}%`;
                    const elR2 = document.getElementById('factorRSquared');
                    if (elR2) elR2.innerText = `${(exp.r_squared * 100).toFixed(1)}%`;
                    const elSys = document.getElementById('factorSysRisk');
                    if (elSys) elSys.innerText = `${exp.systematic_risk_pct.toFixed(1)}%`;
                    const elSpec = document.getElementById('factorSpecRisk');
                    if (elSpec) elSpec.innerText = `${exp.specific_risk_pct.toFixed(1)}%`;

                    const container = document.getElementById('factorCardsContainer');
                    if (container && exp.factors) {
                        const factorList = Object.values(exp.factors);
                        container.innerHTML = factorList.map(f => {
                            const sigBadge = f.is_significant 
                                ? '<span class="text-[9px] px-1 py-0.2 rounded bg-emerald-950 text-emerald-300 border border-emerald-800">SIG (p<0.05)</span>'
                                : '<span class="text-[9px] px-1 py-0.2 rounded bg-zinc-800 text-zinc-400">NOT SIG</span>';
                            const betaColor = f.beta > 0.05 ? 'text-emerald-400' : (f.beta < -0.05 ? 'text-rose-400' : 'text-zinc-300');
                            return `
                                <div class="p-3 rounded-lg bg-zinc-900/80 border border-zinc-800 space-y-1">
                                    <div class="flex items-center justify-between">
                                        <span class="font-bold text-zinc-300">${f.factor_name}</span>
                                        ${sigBadge}
                                    </div>
                                    <div class="flex items-baseline justify-between pt-1">
                                        <span class="text-xs text-zinc-500">Beta (β):</span>
                                        <span class="${betaColor} font-bold text-sm">${f.beta >= 0 ? '+' : ''}${f.beta.toFixed(3)}</span>
                                    </div>
                                    <div class="text-[10px] text-zinc-500 flex justify-between">
                                        <span>t: ${f.t_statistic.toFixed(2)}</span>
                                        <span>p: ${f.p_value.toFixed(3)}</span>
                                    </div>
                                </div>
                            `;
                        }).join('');
                    }
                }

                // 2. Fetch Regime Analysis
                const regRes = await fetch('/api/factors/regime-analysis');
                if (regRes.ok) {
                    const rpt = await regRes.json();
                    const b = document.getElementById('currentRegimeBadge');
                    if (b) b.innerText = `REGIME: ${rpt.current_regime}`;

                    const tbody = document.getElementById('regimeTableBody');
                    if (tbody && rpt.regime_performances) {
                        tbody.innerHTML = Object.entries(rpt.regime_performances).map(([reg, m]) => {
                            const statusCls = m.sample_size_adequate ? 'text-emerald-400' : 'text-zinc-500';
                            return `
                                <tr>
                                    <td class="py-2 text-white font-bold">${reg}</td>
                                    <td>${m.trade_count}</td>
                                    <td class="${m.win_rate >= 0.5 ? 'text-emerald-400' : 'text-amber-400'} font-bold">${(m.win_rate * 100).toFixed(0)}%</td>
                                    <td>${m.sharpe_ratio.toFixed(2)}</td>
                                    <td class="text-rose-400">${(m.max_drawdown * 100).toFixed(1)}%</td>
                                    <td class="${statusCls}">${m.sample_size_adequate ? 'ADEQUATE' : 'LIMITED'}</td>
                                </tr>
                            `;
                        }).join('');
                    }
                }

                // 3. Fetch Statistical Validation
                const valRes = await fetch('/api/factors/validation');
                if (valRes.ok) {
                    const v = await valRes.json();
                    const dSh = document.getElementById('wfSharpeDelta');
                    if (dSh) {
                        dSh.innerText = `${v.sharpe_delta >= 0 ? '+' : ''}${v.sharpe_delta.toFixed(2)}`;
                        dSh.className = v.sharpe_delta >= 0 ? 'font-bold text-emerald-400 text-base' : 'font-bold text-rose-400 text-base';
                    }
                    const dDD = document.getElementById('wfDDReduction');
                    if (dDD) dDD.innerText = `${(v.drawdown_reduction * 100).toFixed(1)}%`;
                    const ir = document.getElementById('wfInfoRatio');
                    if (ir) ir.innerText = v.information_ratio.toFixed(2);
                    const te = document.getElementById('wfTrackingError');
                    if (te) te.innerText = `${(v.tracking_error * 100).toFixed(1)}%`;
                    const tEl = document.getElementById('wfTStat');
                    if (tEl) tEl.innerText = v.t_statistic.toFixed(2);
                    const pEl = document.getElementById('wfPVal');
                    if (pEl) pEl.innerText = v.p_value.toFixed(3);
                }
            } catch (err) {
                console.warn("Factor and risk data fetch error:", err);
            }
        }

        async function triggerFactorAttribution() {
            try {
                const res = await fetch('/api/factors/attribution', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ symbol: "PORTFOLIO" })
                });
                if (res.ok) {
                    fetchFactorAndRiskData();
                }
            } catch (err) {
                alert("Factor attribution failed: " + err.message);
            }
        }

        async function triggerRiskOptimization() {
            try {
                const res = await fetch('/api/factors/optimize-risk', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ target_volatility: 0.15 })
                });
                if (res.ok) {
                    const opt = await res.json();
                    const realVol = document.getElementById('optRealizedVol');
                    if (realVol) realVol.innerText = `${(opt.baseline_volatility * 100).toFixed(1)}%`;
                    const scalar = document.getElementById('optVolScalar');
                    if (scalar) scalar.innerText = `${opt.volatility_scalar.toFixed(2)}x`;
                    const cash = document.getElementById('optCashAlloc');
                    if (cash) cash.innerText = `${(opt.cash_allocation * 100).toFixed(1)}%`;

                    const bCont = document.getElementById('riskBudgetsContainer');
                    if (bCont && opt.risk_budget_allocations) {
                        bCont.innerHTML = Object.entries(opt.risk_budget_allocations).map(([sym, b]) => {
                            const optW = opt.optimized_weights[sym] || 0.0;
                            return `
                                <div class="flex items-center justify-between p-1.5 rounded bg-zinc-900/80 border border-zinc-800">
                                    <span class="text-white font-bold">${sym}:</span>
                                    <span class="text-zinc-400">Budget: ${(b * 100).toFixed(1)}%</span>
                                    <span class="text-emerald-400 font-bold">Alloc: ${(optW * 100).toFixed(1)}%</span>
                                </div>
                            `;
                        }).join('');
                    }
                }
            } catch (err) {
                alert("Risk optimization failed: " + err.message);
            }
        }

        // ── Phase 18: Real-Time Streaming & High-Frequency Telemetry ──
        let telemetryWs = null;
        let wsReconnectAttempts = 0;
        let streamEventsList = [];
        let streamActiveFilter = 'ALL';

        function initWebSocketTelemetry() {
            try {
                const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
                const host = window.location.host || '127.0.0.1:5000';
                const wsUrl = `${protocol}//${host}/ws/telemetry`;

                telemetryWs = new WebSocket(wsUrl);

                telemetryWs.onopen = () => {
                    wsReconnectAttempts = 0;
                    const dot = document.getElementById('wsStatusDot');
                    const txt = document.getElementById('wsStatusText');
                    if (dot) dot.className = "w-2.5 h-2.5 rounded-full bg-emerald-400";
                    if (txt) {
                        txt.innerText = "CONNECTED (WS LIVE)";
                        txt.className = "font-bold text-emerald-300";
                    }
                };

                telemetryWs.onmessage = (event) => {
                    try {
                        const data = JSON.parse(event.data);
                        handleStreamMessage(data);
                    } catch (err) {
                        console.debug("WS message parse error:", err);
                    }
                };

                telemetryWs.onclose = () => {
                    const dot = document.getElementById('wsStatusDot');
                    const txt = document.getElementById('wsStatusText');
                    if (dot) dot.className = "w-2.5 h-2.5 rounded-full bg-rose-400";
                    if (txt) {
                        txt.innerText = "DISCONNECTED";
                        txt.className = "font-bold text-rose-400";
                    }
                    // Exponential backoff reconnect
                    wsReconnectAttempts++;
                    const delay = Math.min(10000, 1000 * Math.pow(1.5, wsReconnectAttempts));
                    setTimeout(initWebSocketTelemetry, delay);
                };

                telemetryWs.onerror = (err) => {
                    console.debug("WS error:", err);
                };
            } catch (err) {
                console.warn("WebSocket init error:", err);
            }
        }

        function reconnectWebSocket() {
            if (telemetryWs) {
                try { telemetryWs.close(); } catch (_) {}
            }
            initWebSocketTelemetry();
        }

        function handleStreamMessage(msg) {
            // Heartbeat updates throughput and latency meters
            if (msg.type === "HEARTBEAT") {
                const tEl = document.getElementById('streamThroughput');
                if (tEl && msg.events_per_second !== undefined) tEl.innerText = msg.events_per_second.toFixed(1);
                const lEl = document.getElementById('streamLatencyP50');
                if (lEl && msg.avg_latency_ms !== undefined) lEl.innerText = msg.avg_latency_ms.toFixed(1);
                const qEl = document.getElementById('streamQueueDepth');
                if (qEl && msg.queue_depth !== undefined) qEl.innerText = msg.queue_depth;
                return;
            }

            // Normal stream event
            if (msg.event_id || msg.event_type) {
                streamEventsList.unshift(msg);
                if (streamEventsList.length > 200) streamEventsList.pop();
                renderStreamFeed();
            }
        }

        function renderStreamFeed() {
            const container = document.getElementById('streamLiveFeed');
            const counter = document.getElementById('streamFeedCounter');
            if (!container) return;

            const filtered = streamActiveFilter === 'ALL'
                ? streamEventsList
                : streamEventsList.filter(e => e.event_type === streamActiveFilter || (streamActiveFilter === 'TICKS' && e.event_type === 'MARKET_TICK'));

            if (counter) counter.innerText = `${filtered.length} events`;

            if (filtered.length === 0) {
                container.innerHTML = '<div class="text-zinc-600 text-center py-6 font-sans">No matching events in stream.</div>';
                return;
            }

            container.innerHTML = filtered.slice(0, 50).map(e => {
                const typeColor = e.event_type === 'MARKET_TICK' ? 'text-cyan-400'
                    : (e.event_type === 'EXECUTION_EVENT' ? 'text-emerald-400'
                    : (e.event_type === 'SYSTEM_EVENT' ? 'text-purple-400' : 'text-zinc-400'));
                const ts = e.timestamp ? new Date(e.timestamp).toLocaleTimeString() : '--';
                const sym = e.symbol || 'SYSTEM';
                const payloadStr = e.data ? JSON.stringify(e.data).slice(0, 100) : '';

                return `
                    <div class="p-2 rounded bg-zinc-900/70 border border-zinc-800/80 flex items-center justify-between text-[11px] font-mono">
                        <div class="flex items-center gap-2">
                            <span class="text-zinc-500 text-[10px]">${ts}</span>
                            <span class="${typeColor} font-bold">[${e.event_type}]</span>
                            <span class="text-white font-bold">${sym}</span>
                            <span class="text-zinc-400 truncate max-w-md">${payloadStr}</span>
                        </div>
                        <div class="flex items-center gap-1 text-[10px]">
                            ${e.is_stale ? '<span class="px-1 rounded bg-zinc-800 text-zinc-400">STALE</span>' : ''}
                            ${e.is_duplicate ? '<span class="px-1 rounded bg-amber-950 text-amber-300">DUP</span>' : ''}
                            ${e.is_out_of_order ? '<span class="px-1 rounded bg-rose-950 text-rose-300">OOO</span>' : ''}
                        </div>
                    </div>
                `;
            }).join('');
        }

        function filterStreamFeed(filterType) {
            streamActiveFilter = filterType;
            renderStreamFeed();
        }

        function clearStreamFeed() {
            streamEventsList = [];
            renderStreamFeed();
        }

        async function fetchStreamingData() {
            try {
                // Fetch metrics
                const metRes = await fetch('/api/streaming/metrics');
                if (metRes.ok) {
                    const m = await metRes.json();
                    const tEl = document.getElementById('streamThroughput');
                    if (tEl) tEl.innerText = m.events_per_second.toFixed(1);
                    const p50El = document.getElementById('streamLatencyP50');
                    if (p50El) p50El.innerText = m.processing_latency_p50_ms.toFixed(1);
                    const p95El = document.getElementById('streamLatencyP95');
                    if (p95El) p95El.innerText = m.processing_latency_p95_ms.toFixed(1);
                    const p99El = document.getElementById('streamLatencyP99');
                    if (p99El) p99El.innerText = m.processing_latency_p99_ms.toFixed(1);

                    const qDep = document.getElementById('streamQueueDepth');
                    if (qDep) qDep.innerText = m.queue_depth;
                    const qCap = document.getElementById('streamQueueCapacity');
                    if (qCap) qCap.innerText = m.queue_capacity;
                    const qUt = document.getElementById('streamQueueUtil');
                    if (qUt) qUt.innerText = `${m.queue_utilization_pct.toFixed(1)}%`;
                    const qBar = document.getElementById('streamQueueBar');
                    if (qBar) qBar.style.width = `${Math.min(100, m.queue_utilization_pct)}%`;

                    const acc = document.getElementById('streamAcceptedCount');
                    if (acc) acc.innerText = m.events_accepted;
                    const rej = document.getElementById('streamRejectedCount');
                    if (rej) rej.innerText = m.events_rejected;
                    const dup = document.getElementById('streamDuplicateCount');
                    if (dup) dup.innerText = m.events_duplicated;
                    const st = document.getElementById('streamStaleCount');
                    if (st) st.innerText = m.events_stale;
                    const drp = document.getElementById('streamDroppedCount');
                    if (drp) drp.innerText = m.events_dropped;

                    const up = document.getElementById('streamUptime');
                    if (up) up.innerText = `${m.uptime_seconds.toFixed(0)}s`;
                    const rec = document.getElementById('streamReconnects');
                    if (rec) rec.innerText = m.reconnect_count;
                }

                // Fetch Workers Status
                const wRes = await fetch('/api/streaming/workers');
                if (wRes.ok) {
                    const wData = await wRes.json();
                    const wGrid = document.getElementById('workersGridContainer');
                    if (wGrid && wData.workers) {
                        const wList = Object.values(wData.workers);
                        if (wList.length === 0) {
                            wGrid.innerHTML = '<div class="col-span-4 text-center py-4 text-zinc-500 font-sans">No workers active. Click "Start Workers" to launch.</div>';
                        } else {
                            wGrid.innerHTML = wList.map(w => {
                                const stCls = w.state === 'RUNNING' ? 'bg-emerald-950 text-emerald-300 border-emerald-800'
                                    : (w.state === 'PAUSED' ? 'bg-amber-950 text-amber-300 border-amber-800' : 'bg-zinc-800 text-zinc-400 border-zinc-700');
                                return `
                                    <div class="p-3 rounded-lg bg-zinc-900/80 border border-zinc-800 space-y-2">
                                        <div class="flex items-center justify-between">
                                            <span class="font-bold text-white">${w.symbol}</span>
                                            <span class="text-[10px] px-1.5 py-0.5 rounded border ${stCls}">${w.state}</span>
                                        </div>
                                        <div class="space-y-1 text-[11px] text-zinc-400">
                                            <div class="flex justify-between"><span>Ticks:</span><span class="text-white font-bold">${w.ticks_processed}</span></div>
                                            <div class="flex justify-between"><span>Decisions:</span><span class="text-cyan-300 font-bold">${w.decisions_generated}</span></div>
                                            <div class="flex justify-between"><span>Paper Orders:</span><span class="text-emerald-400 font-bold">${w.paper_orders_submitted}</span></div>
                                            <div class="flex justify-between"><span>Failures:</span><span class="${w.failure_count > 0 ? 'text-rose-400 font-bold' : 'text-zinc-500'}">${w.failure_count}</span></div>
                                        </div>
                                    </div>
                                `;
                            }).join('');
                        }
                    }
                }
            } catch (err) {
                console.warn("Streaming data fetch error:", err);
            }
        }

        async function triggerStreamIngest() {
            const sym = document.getElementById('streamIngestSymbol').value.trim() || 'TCS.NS';
            const price = parseFloat(document.getElementById('streamIngestPrice').value) || 3500.0;
            const volume = parseFloat(document.getElementById('streamIngestVolume').value) || 100.0;

            try {
                const res = await fetch('/api/streaming/ingest', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ symbol: sym, price: price, volume: volume })
                });
                if (res.ok) {
                    fetchStreamingData();
                }
            } catch (err) {
                alert("Tick ingestion failed: " + err.message);
            }
        }

        async function controlWorkerPool(action) {
            try {
                const res = await fetch('/api/streaming/workers/control', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ action: action })
                });
                if (res.ok) {
                    fetchStreamingData();
                }
            } catch (err) {
                alert(`Worker ${action} failed: ` + err.message);
            }
        }

        // ── Phase 19: Operational Reliability & Readiness ──
        async function fetchReliabilityData() {
            try {
                const scRes = await fetch('/api/reliability/scorecard');
                if (scRes.ok) {
                    const sc = await scRes.json();
                    const badge = document.getElementById('scorecardVerdictBadge');
                    if (badge) {
                        badge.innerText = `${sc.overall_verdict} (${sc.passed_count}/${sc.total_categories} PASS)`;
                        badge.className = sc.failed_count === 0 
                            ? "text-[10px] px-2 py-0.5 rounded bg-emerald-950 text-emerald-300 border border-emerald-700"
                            : "text-[10px] px-2 py-0.5 rounded bg-rose-950 text-rose-300 border border-rose-700";
                    }

                    const grid = document.getElementById('scorecardCategoriesGrid');
                    if (grid && sc.categories) {
                        grid.innerHTML = Object.values(sc.categories).map(cat => {
                            const stCls = cat.status === 'PASS' ? 'bg-emerald-950 text-emerald-300 border-emerald-800'
                                : (cat.status === 'DEGRADED' ? 'bg-amber-950 text-amber-300 border-amber-800' : 'bg-rose-950 text-rose-300 border-rose-800');
                            return `
                                <div class="p-3 rounded-lg bg-zinc-900/80 border border-zinc-800 space-y-1.5 font-mono text-xs">
                                    <div class="flex items-center justify-between">
                                        <span class="font-bold text-white text-[11px]">${cat.name}</span>
                                        <span class="text-[9px] px-1.5 py-0.5 rounded border ${stCls}">${cat.status}</span>
                                    </div>
                                    <p class="text-[10px] text-zinc-400 leading-tight">${cat.evidence}</p>
                                </div>
                            `;
                        }).join('');
                    }
                }
            } catch (err) {
                console.warn("Reliability data fetch error:", err);
            }
        }

        async function runStressBenchmark() {
            const evtsInput = document.getElementById('stressBenchmarkEvents');
            const numEvts = parseInt(evtsInput ? evtsInput.value : 1000) || 1000;
            const tEl = document.getElementById('bmThroughput');
            const p50El = document.getElementById('bmLatencyP50');
            const p95El = document.getElementById('bmLatencyP95');
            const p99El = document.getElementById('bmLatencyP99');

            if (tEl) tEl.innerText = "Running...";

            try {
                const res = await fetch('/api/reliability/benchmark', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ num_events: numEvts })
                });
                if (res.ok) {
                    const bm = await res.json();
                    if (tEl) tEl.innerText = bm.events_per_second.toFixed(1);
                    if (p50El) p50El.innerText = bm.latency_p50_ms.toFixed(1);
                    if (p95El) p95El.innerText = bm.latency_p95_ms.toFixed(1);
                    if (p99El) p99El.innerText = bm.latency_p99_ms.toFixed(1);
                } else {
                    if (tEl) tEl.innerText = "Error";
                }
            } catch (err) {
                alert("Benchmark failed: " + err.message);
                if (tEl) tEl.innerText = "--";
            }
        }

        function inspectCandidate(symbol) {
            document.getElementById('symbolInput').value = symbol;
            switchMainTab('orchestrator');
            runTradingOSPipeline();
        }

        // ── 5. Paper Broker & Execution Terminal Data ──
        async function fetchBrokerData() {
            try {
                fetchForwardStatus();

                // Phase 15 Manager Status
                try {
                    const mgrRes = await fetch('/api/broker/manager/status');
                    if (mgrRes.ok) {
                        const mgr = await mgrRes.json();
                        const bEnv = document.getElementById('brokerEnvBadge');
                        if (bEnv) {
                            bEnv.innerText = mgr.active_environment;
                            bEnv.className = mgr.active_environment === 'SANDBOX' 
                                ? 'text-[10px] px-2 py-0.5 rounded bg-cyan-950 text-cyan-300 border border-cyan-700 font-mono font-bold'
                                : 'text-[10px] px-2 py-0.5 rounded bg-amber-950 text-amber-300 border border-amber-700 font-mono font-bold';
                        }
                        const bProv = document.getElementById('brokerProviderName');
                        if (bProv) bProv.innerText = mgr.broker_provider;
                        const bConn = document.getElementById('brokerConnState');
                        if (bConn) bConn.innerText = mgr.connection_state;
                        const bRoute = document.getElementById('brokerRoutingMode');
                        if (bRoute) bRoute.innerText = mgr.routing_mode;

                        const rec = mgr.last_reconciliation;
                        const recBadge = document.getElementById('recStatusBadge');
                        const recDet = document.getElementById('recDetails');
                        if (rec && recBadge && recDet) {
                            recBadge.innerText = rec.is_reconciled ? "SYNCHRONIZED" : `MISMATCH (${rec.discrepancy_count})`;
                            recBadge.className = rec.is_reconciled 
                                ? 'text-[10px] px-2 py-0.5 rounded bg-emerald-950 text-emerald-300 border border-emerald-700 font-mono'
                                : 'text-[10px] px-2 py-0.5 rounded bg-rose-950 text-rose-300 border border-rose-700 font-mono';
                            recDet.innerText = rec.summary_message;
                        }
                    }
                } catch (e) {
                    console.warn("Manager status fetch error:", e);
                }

                const acctRes = await fetch('/api/broker/account');
                if (acctRes.ok) {
                    const acct = await acctRes.json();
                    document.getElementById('acctCash').innerText = `Rs ${acct.cash.toLocaleString()}`;
                    document.getElementById('acctEquity').innerText = `Rs ${acct.total_equity.toLocaleString()}`;
                    document.getElementById('acctPower').innerText = `Rs ${acct.buying_power.toLocaleString()}`;
                    document.getElementById('acctRealized').innerText = `Rs ${acct.realized_pnl.toFixed(2)}`;
                    document.getElementById('acctUnrealized').innerText = `Rs ${acct.unrealized_pnl.toFixed(2)}`;
                    document.getElementById('acctPosCount').innerText = acct.open_positions_count;
                }

                const posRes = await fetch('/api/broker/positions');
                if (posRes.ok) {
                    const posMap = await posRes.json();
                    const positions = Object.values(posMap);
                    const posTable = document.getElementById('positionsTableBody');
                    if (positions.length === 0) {
                        posTable.innerHTML = '<tr><td colspan="5" class="py-4 text-center text-zinc-600 font-sans">No open paper positions</td></tr>';
                    } else {
                        posTable.innerHTML = positions.map(p => `
                            <tr>
                                <td class="py-2 text-cyan-300 font-bold">${p.symbol}</td>
                                <td>${p.quantity}</td>
                                <td>Rs ${p.average_entry_price.toFixed(2)}</td>
                                <td>Rs ${p.market_value.toFixed(2)}</td>
                                <td class="${p.unrealized_pnl >= 0 ? 'text-emerald-400' : 'text-rose-400'} font-bold">Rs ${p.unrealized_pnl.toFixed(2)}</td>
                            </tr>
                        `).join('');
                    }
                }

                const ordRes = await fetch('/api/broker/orders');
                if (ordRes.ok) {
                    const orders = await ordRes.json();
                    const ordTable = document.getElementById('ordersTableBody');
                    if (orders.length === 0) {
                        ordTable.innerHTML = '<tr><td colspan="6" class="py-4 text-center text-zinc-600 font-sans">No active paper orders</td></tr>';
                    } else {
                        ordTable.innerHTML = orders.map(o => `
                            <tr>
                                <td class="py-2 text-cyan-300 font-bold">${o.order_id.slice(-8)}</td>
                                <td>${o.symbol}</td>
                                <td class="${o.side === 'BUY' ? 'text-emerald-400' : 'text-rose-400'} font-bold">${o.side}</td>
                                <td>${o.filled_quantity}/${o.requested_quantity}</td>
                                <td><span class="px-1.5 py-0.5 rounded text-[10px] bg-zinc-800 text-zinc-300">${o.status}</span></td>
                                <td><button onclick="viewTimeline('${o.order_id}')" class="text-cyan-400 hover:underline">Timeline</button></td>
                            </tr>
                        `).join('');
                    }
                }

                const telemRes = await fetch('/api/telemetry/dashboard');
                if (telemRes.ok) {
                    const t = await telemRes.json();
                    const m = t.metrics;
                    document.getElementById('metricFillRate').innerText = `${m.fill_rate_pct}%`;
                    document.getElementById('metricRejRate').innerText = `${m.rejection_rate_pct}%`;
                    document.getElementById('metricCancelRate').innerText = `${m.cancellation_rate_pct}%`;
                    document.getElementById('metricPartialRate').innerText = `${m.partial_fill_rate_pct}%`;
                    document.getElementById('metricAvgLat').innerText = `${m.avg_execution_latency_ms} ms`;
                    document.getElementById('metricAvgSlip').innerText = `${m.avg_slippage_pct}%`;
                    document.getElementById('metricComm').innerText = `Rs ${m.total_simulated_commissions.toFixed(2)}`;
                }
            } catch (err) {
                console.warn("Error fetching broker data:", err);
            }
        }

        async function fetchForwardStatus() {
            try {
                const res = await fetch('/api/forward/status');
                if (!res.ok) return;
                const d = await res.json();
                document.getElementById('fwdMode').innerText = d.mode;
                document.getElementById('fwdState').innerText = d.engine_state;
                document.getElementById('fwdState').className = d.engine_state === 'RUNNING' ? 'font-bold text-emerald-400' : (d.engine_state === 'PAUSED' ? 'font-bold text-amber-400' : 'font-bold text-zinc-400');
                document.getElementById('fwdSession').innerText = d.session_state;
                document.getElementById('fwdTicks').innerText = d.ticks_processed;
                document.getElementById('fwdFills').innerText = d.simulated_fills;
            } catch (err) {
                console.warn("Failed forward status fetch:", err);
            }
        }

        async function toggleForwardEngine(action) {
            try {
                const res = await fetch(`/api/forward/${action}`, { method: 'POST' });
                if (res.ok) {
                    fetchBrokerData();
                }
            } catch (err) {
                alert(`Forward engine ${action} failed: ` + err.message);
            }
        }

        async function triggerForwardCycle() {
            try {
                const res = await fetch('/api/forward/cycle', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({}) });
                if (res.ok) {
                    fetchBrokerData();
                }
            } catch (err) {
                alert("Forward cycle failed: " + err.message);
            }
        }

        async function triggerBrokerReconciliation() {
            const btn = document.getElementById('runReconcileBtn');
            if (btn) btn.innerText = "Auditing...";
            try {
                const res = await fetch('/api/broker/reconcile', { method: 'POST' });
                if (res.ok) {
                    fetchBrokerData();
                }
            } catch (err) {
                alert("Reconciliation failed: " + err.message);
            } finally {
                if (btn) btn.innerText = "Audit State Reconciliation";
            }
        }

        async function viewTimeline(orderId) {
            const modal = document.getElementById('timelineModal');
            const content = document.getElementById('timelineContent');
            modal.classList.remove('hidden');
            content.innerHTML = 'Loading timeline...';

            try {
                const res = await fetch(`/api/telemetry/orders/${encodeURIComponent(orderId)}/timeline`);
                const data = await res.json();
                content.innerHTML = `
                    <div class="text-zinc-400 mb-2">Order: <span class="text-white font-bold">${data.order_id}</span> | Symbol: <span class="text-cyan-300 font-bold">${data.symbol}</span></div>
                    <div class="text-zinc-400 mb-4">Total Lifecycle: <span class="text-cyan-400 font-bold">${data.total_lifecycle_ms} ms</span></div>
                    <div class="space-y-2 border-l-2 border-cyan-500/50 pl-3">
                        ${data.steps.map(s => `
                            <div>
                                <div class="font-bold text-white">${s.status} <span class="text-zinc-500 font-normal text-[10px]">(+${s.latency_from_prev_ms} ms)</span></div>
                                <div class="text-zinc-500 text-[10px]">${s.details}</div>
                            </div>
                        `).join('')}
                    </div>
                `;
            } catch (err) {
                content.innerHTML = `<div class="text-rose-400">Failed to load timeline: ${err.message}</div>`;
            }
        }

        function closeTimelineModal() {
            document.getElementById('timelineModal').classList.add('hidden');
        }

        // ── 6. System Health & Telemetry Tab Data ──
        async function fetchMonitoringData() {
            try {
                const compRes = await fetch('/api/monitor/components');
                if (compRes.ok) {
                    const compMap = await compRes.json();
                    const components = Array.isArray(compMap) ? compMap : Object.values(compMap);
                    const grid = document.getElementById('subsystemsGrid');
                    grid.innerHTML = components.map(c => `
                        <div class="p-3 rounded-lg bg-zinc-900/80 border ${c.status === 'HEALTHY' ? 'border-zinc-800' : (c.status === 'DEGRADED' ? 'border-amber-700/50 bg-amber-950/20' : 'border-rose-700/50 bg-rose-950/20')} space-y-1">
                            <div class="flex items-center justify-between">
                                <span class="font-bold text-white text-[11px] truncate" title="${c.name}">${c.name}</span>
                                <span class="text-[9px] px-1.5 py-0.5 rounded font-bold ${c.status === 'HEALTHY' ? 'bg-emerald-950 text-emerald-300' : (c.status === 'DEGRADED' ? 'bg-amber-950 text-amber-300' : 'bg-rose-950 text-rose-300')}">${c.status}</span>
                            </div>
                            <div class="text-[10px] text-zinc-500 flex justify-between">
                                <span>Lat: ${c.avg_latency_ms.toFixed(1)}ms</span>
                                <span>Err: ${c.consecutive_failures}</span>
                            </div>
                        </div>
                    `).join('');
                }

                const tRes = await fetch('/api/telemetry/dashboard');
                if (tRes.ok) {
                    const t = await tRes.json();
                    const alerts = t.risk_alerts || [];
                    const aCont = document.getElementById('alertsContainer');
                    if (alerts.length === 0) {
                        aCont.innerHTML = '<div class="text-zinc-600 text-center py-4 font-sans">No risk alerts or audit events recorded.</div>';
                    } else {
                        aCont.innerHTML = alerts.map(a => `
                            <div class="p-2 rounded bg-rose-950/40 border border-rose-900/50 text-rose-300 flex justify-between">
                                <span><span class="font-bold">[${a.event_type}]</span> ${a.reason || 'Operational event'}</span>
                                <span class="text-zinc-500 text-[10px]">${a.timestamp ? new Date(a.timestamp).toLocaleTimeString() : ''}</span>
                            </div>
                        `).join('');
                    }
                }
            } catch (err) {
                console.warn("Monitoring fetch error:", err);
            }
        }

        // ═══════════ Phase 22: Alerting & Compliance Functions ═══════════

        async function fetchAlertStatus() {
            try {
                const res = await fetch('/api/alerts/status');
                if (!res.ok) return;
                const d = await res.json();
                document.getElementById('alertTotalActive').textContent = d.total_active_alerts || 0;
                document.getElementById('alertEmergencyCount').textContent = (d.alerts_by_severity || {})['EMERGENCY'] || 0;
                document.getElementById('alertCriticalCount').textContent = (d.alerts_by_severity || {})['CRITICAL'] || 0;
                document.getElementById('alertSuppressedCount').textContent = d.total_suppressed || 0;
                document.getElementById('alertAuditCount').textContent = d.total_audit_entries || 0;

                // Fetch active alerts for table
                const aRes = await fetch('/api/alerts/active');
                if (!aRes.ok) return;
                const aData = await aRes.json();
                const tbody = document.getElementById('alertTableBody');
                if ((aData.alerts || []).length === 0) {
                    tbody.innerHTML = '<tr><td colspan="6" class="p-4 text-center text-emerald-400 font-mono">✓ No active alerts. System healthy.</td></tr>';
                } else {
                    const sevColors = { EMERGENCY: 'text-red-500 bg-red-950/60', CRITICAL: 'text-orange-400 bg-orange-950/60', HIGH: 'text-amber-400 bg-amber-950/60', WARNING: 'text-yellow-300 bg-yellow-950/60', INFO: 'text-cyan-300 bg-cyan-950/60' };
                    tbody.innerHTML = aData.alerts.map(a => `
                        <tr class="hover:bg-zinc-800/30">
                            <td class="p-2.5"><span class="px-2 py-0.5 rounded text-[10px] font-bold ${sevColors[a.severity] || 'text-zinc-300'}">${a.severity}</span></td>
                            <td class="p-2.5">${a.category}</td>
                            <td class="p-2.5 text-white">${a.title}</td>
                            <td class="p-2.5 text-zinc-400">${a.source_component || '—'}</td>
                            <td class="p-2.5 text-zinc-500">${a.created_at ? new Date(a.created_at).toLocaleTimeString() : '—'}</td>
                            <td class="p-2.5 text-right">
                                <button onclick="acknowledgeAlert('${a.alert_id}')" class="px-2 py-0.5 bg-zinc-800 hover:bg-zinc-700 text-[10px] text-cyan-400 border border-cyan-600/30 rounded mr-1">ACK</button>
                                <button onclick="resolveAlert('${a.alert_id}')" class="px-2 py-0.5 bg-zinc-800 hover:bg-zinc-700 text-[10px] text-emerald-400 border border-emerald-600/30 rounded">RESOLVE</button>
                            </td>
                        </tr>
                    `).join('');
                }
            } catch (e) { console.warn('Alert status fetch error:', e); }
        }

        async function fetchAlertRules() {
            try {
                const res = await fetch('/api/alerts/rules');
                if (!res.ok) return;
                const d = await res.json();
                document.getElementById('alertRulesCount').textContent = `${d.total_rules} rules configured`;
                const grid = document.getElementById('alertRulesGrid');
                const sevColors = { EMERGENCY: 'border-red-800/60 text-red-400', CRITICAL: 'border-orange-800/60 text-orange-400', HIGH: 'border-amber-800/60 text-amber-400', WARNING: 'border-yellow-800/60 text-yellow-300', INFO: 'border-cyan-800/60 text-cyan-300' };
                grid.innerHTML = (d.rules || []).map(r => `
                    <div class="p-3 rounded-lg bg-zinc-900/60 border ${r.enabled ? (sevColors[r.severity] || 'border-zinc-800') : 'border-zinc-800 opacity-50'}">
                        <div class="flex items-center justify-between mb-1">
                            <span class="text-[10px] font-bold font-mono">${r.rule_id}</span>
                            <span class="text-[10px] font-mono ${r.enabled ? 'text-emerald-400' : 'text-zinc-500'}">${r.enabled ? 'ENABLED' : 'DISABLED'}</span>
                        </div>
                        <div class="text-xs font-mono text-white">${r.name}</div>
                        <div class="text-[10px] text-zinc-500 mt-1">${r.condition_description}</div>
                    </div>
                `).join('');
            } catch (e) { console.warn('Alert rules fetch error:', e); }
        }

        async function triggerAlertEvaluation() {
            try {
                const res = await fetch('/api/alerts/evaluate', { method: 'POST' });
                if (res.ok) { fetchAlertStatus(); }
            } catch (e) { console.warn('Alert evaluation error:', e); }
        }

        async function acknowledgeAlert(alertId) {
            try {
                const res = await fetch(`/api/alerts/${alertId}/acknowledge`, { method: 'POST' });
                if (res.ok) fetchAlertStatus();
            } catch (e) { console.warn('Acknowledge error:', e); }
        }

        async function resolveAlert(alertId) {
            try {
                const res = await fetch(`/api/alerts/${alertId}/resolve`, { method: 'POST' });
                if (res.ok) fetchAlertStatus();
            } catch (e) { console.warn('Resolve error:', e); }
        }

        async function fetchComplianceSnapshot() {
            try {
                const res = await fetch('/api/compliance/snapshot');
                if (!res.ok) return;
                const d = await res.json();
                const ok = (v) => v ? 'text-emerald-400' : 'text-red-400';
                const lbl = (v, y, n) => v ? y : n;
                document.getElementById('compLiveBlocked').className = `text-xs font-bold mt-1 font-mono ${ok(d.live_trading_blocked)}`;
                document.getElementById('compLiveBlocked').textContent = lbl(d.live_trading_blocked, 'BLOCKED ✓', 'UNBLOCKED ✗');
                document.getElementById('compGuardActive').className = `text-xs font-bold mt-1 font-mono ${ok(d.execution_guard_active)}`;
                document.getElementById('compGuardActive').textContent = lbl(d.execution_guard_active, 'ACTIVE ✓', 'INACTIVE ✗');
                document.getElementById('compRiskActive').className = `text-xs font-bold mt-1 font-mono ${ok(d.risk_engine_active)}`;
                document.getElementById('compRiskActive').textContent = lbl(d.risk_engine_active, 'ACTIVE ✓', 'INACTIVE ✗');
                document.getElementById('compOverall').className = `text-xs font-bold mt-1 font-mono ${ok(d.overall_compliant)}`;
                document.getElementById('compOverall').textContent = lbl(d.overall_compliant, 'COMPLIANT ✓', 'NON-COMPLIANT ✗');
            } catch (e) { console.warn('Compliance snapshot error:', e); }
        }

        // ═══════════ Phase 22: Resilience & Recovery Functions ═══════════

        async function fetchResilienceStatus() {
            try {
                const res = await fetch('/api/resilience/status');
                if (!res.ok) return;
                const d = await res.json();
                const stateColors = {
                    HEALTHY: 'text-emerald-400 bg-emerald-950/80 border-emerald-800/60',
                    DEGRADED: 'text-amber-400 bg-amber-950/80 border-amber-800/60',
                    UNAVAILABLE: 'text-red-400 bg-red-950/80 border-red-800/60',
                    RECOVERING: 'text-cyan-400 bg-cyan-950/80 border-cyan-800/60',
                    FAILED_SAFE: 'text-rose-400 bg-rose-950/80 border-rose-800/60'
                };
                const overallState = d.overall_resilience_state || 'HEALTHY';
                const badge = document.getElementById('resilienceOverallBadge');
                badge.className = `px-2.5 py-1 text-xs font-mono rounded-full border ${stateColors[overallState] || 'text-zinc-400'}`;
                badge.textContent = `STATE: ${overallState}`;

                document.getElementById('resilienceStateText').textContent = overallState;
                document.getElementById('resilienceActiveFailures').textContent = d.active_failures_count || 0;
                document.getElementById('resilienceRecoveringCount').textContent = d.recovering_components_count || 0;
                document.getElementById('resilienceOpenCircuits').textContent = d.open_circuits_count || 0;
                document.getElementById('resilienceMTTR').textContent = `${(d.mean_recovery_time_ms || 0).toFixed(1)}ms`;

                // Render component supervisor matrix table
                const comps = d.components || {};
                const tbody = document.getElementById('resilienceComponentTableBody');
                if (Object.keys(comps).length === 0) {
                    tbody.innerHTML = '<tr><td colspan="7" class="p-4 text-center text-zinc-500 font-mono">No component telemetry available.</td></tr>';
                } else {
                    const cStateColor = {
                        HEALTHY: 'text-emerald-400', DEGRADED: 'text-amber-400',
                        UNAVAILABLE: 'text-red-400', RECOVERING: 'text-cyan-400', FAILED_SAFE: 'text-rose-400'
                    };
                    tbody.innerHTML = Object.entries(comps).map(([compKey, rec]) => `
                        <tr class="hover:bg-zinc-800/30">
                            <td class="p-2.5 font-bold text-white">${rec.name || compKey}</td>
                            <td class="p-2.5 font-bold ${cStateColor[rec.state] || 'text-zinc-300'}">${rec.state}</td>
                            <td class="p-2.5"><span class="px-1.5 py-0.5 rounded text-[10px] ${rec.circuit_state === 'CLOSED' ? 'bg-emerald-950/60 text-emerald-400' : 'bg-red-950/60 text-red-400'}">${rec.circuit_state}</span></td>
                            <td class="p-2.5 text-right ${rec.consecutive_failures > 0 ? 'text-amber-400 font-bold' : 'text-zinc-400'}">${rec.consecutive_failures}</td>
                            <td class="p-2.5 text-right ${rec.timeout_count > 0 ? 'text-orange-400 font-bold' : 'text-zinc-400'}">${rec.timeout_count}</td>
                            <td class="p-2.5 text-right text-zinc-400">${(rec.latency_ms || 0).toFixed(1)}ms</td>
                            <td class="p-2.5 text-zinc-400 text-[10px] max-w-xs truncate" title="${rec.active_fallback || 'None'}">${rec.active_fallback || '—'}</td>
                        </tr>
                    `).join('');
                }
            } catch (e) { console.warn('Resilience status fetch error:', e); }
        }

        async function fetchResilienceScorecard() {
            try {
                const res = await fetch('/api/resilience/scorecard');
                if (!res.ok) return;
                const d = await res.json();
                document.getElementById('resilienceScorecardRating').textContent = d.readiness_classification || 'RESILIENT';
                document.getElementById('scorecardTested').textContent = d.total_scenarios_tested || 0;
                document.getElementById('scorecardRate').textContent = `${((d.recovery_success_rate || 1.0) * 100).toFixed(1)}%`;
                document.getElementById('scorecardCircuits').textContent = d.circuit_breaker_activations || 0;
                document.getElementById('scorecardDegraded').textContent = d.degraded_mode_activations || 0;
                document.getElementById('scorecardSummaryMsg').textContent = d.summary_message || 'Scorecard verified clean.';
            } catch (e) { console.warn('Resilience scorecard fetch error:', e); }
        }

        async function resetResilienceCircuits() {
            try {
                const res = await fetch('/api/resilience/circuits/reset', { method: 'POST' });
                if (res.ok) {
                    fetchResilienceStatus();
                    fetchResilienceScorecard();
                }
            } catch (e) { console.warn('Circuit reset error:', e); }
        }

        async function triggerFaultSimulation() {
            const select = document.getElementById('simFaultSelect');
            const faultType = select.value;
            const log = document.getElementById('simFaultLog');
            log.innerHTML = `<span class="text-amber-400">[INJECTING]</span> Injecting ${faultType} fault and executing recovery workflow...`;
            try {
                const res = await fetch('/api/resilience/simulate-failure', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ fault_type: faultType, auto_recover: true })
                });
                if (res.ok) {
                    const data = await res.json();
                    const action = data.recovery_action;
                    log.innerHTML = `
                        <div class="text-emerald-400 font-bold">[SUCCESS] Simulated ${data.fault_type}</div>
                        <div class="text-zinc-300">Action: ${action ? action.action_taken : 'Evaluated'}</div>
                        <div class="text-zinc-400">Result: ${action ? action.result_message : 'Recovered'} (${(action ? action.duration_ms : 0).toFixed(1)}ms)</div>
                    `;
                    fetchResilienceStatus();
                    fetchResilienceScorecard();
                } else {
                    log.innerHTML = `<span class="text-red-400">[ERROR]</span> Simulation request failed: ${res.statusText}`;
                }
            } catch (e) {
                log.innerHTML = `<span class="text-red-400">[ERROR]</span> Network error during simulation: ${e}`;
            }
        }

        // ═══════════ Phase 23: Observability & Audit Functions ═══════════

        async function fetchObservabilityHealth() {
            try {
                const res = await fetch('/api/observability/health');
                if (!res.ok) return;
                const d = await res.json();

                const healthColors = {
                    HEALTHY: 'text-emerald-400 bg-emerald-950/80 border-emerald-800/60',
                    DEGRADED: 'text-amber-400 bg-amber-950/80 border-amber-800/60',
                    UNHEALTHY: 'text-red-400 bg-red-950/80 border-red-800/60',
                    RECOVERING: 'text-cyan-400 bg-cyan-950/80 border-cyan-800/60'
                };
                const overallHealth = d.overall_health || 'HEALTHY';
                const badge = document.getElementById('obsOverallHealthBadge');
                badge.className = `px-2.5 py-1 text-xs font-mono rounded-full border ${healthColors[overallHealth] || 'text-zinc-400'}`;
                badge.textContent = `HEALTH: ${overallHealth}`;

                document.getElementById('obsHealthText').textContent = overallHealth;
                document.getElementById('obsAuditIntegrityText').textContent = d.audit_verification_status || 'VALID';
                document.getElementById('obsLatencyP50').textContent = `${(d.latency_p50_ms || 0).toFixed(1)}ms`;
                document.getElementById('obsLatencyP99').textContent = `${(d.latency_p99_ms || 0).toFixed(1)}ms`;
                document.getElementById('obsThroughput').textContent = `${(d.throughput_events_per_sec || 0).toFixed(1)} evt/s`;
                document.getElementById('obsActiveWorkers').textContent = `${d.active_workers_count || 0} / ${d.total_workers_count || 0}`;

                const auditBadge = document.getElementById('obsAuditChainBadge');
                if (d.audit_verification_status === 'VALID') {
                    auditBadge.className = "px-2.5 py-1 text-xs font-mono rounded-full bg-teal-950/80 text-teal-400 border border-teal-800/60";
                    auditBadge.textContent = "AUDIT: VALID ✓";
                } else {
                    auditBadge.className = "px-2.5 py-1 text-xs font-mono rounded-full bg-rose-950/80 text-rose-400 border border-rose-800/60";
                    auditBadge.textContent = `AUDIT: ${d.audit_verification_status} ✗`;
                }
            } catch (e) { console.warn('Observability health fetch error:', e); }
        }

        async function verifyAuditChain() {
            const reportStatus = document.getElementById('auditReportStatus');
            reportStatus.textContent = "Verifying cryptographic hashes...";
            reportStatus.className = "font-bold text-cyan-400 animate-pulse";
            try {
                const res = await fetch('/api/observability/audit/verify');
                if (!res.ok) return;
                const d = await res.json();
                reportStatus.className = d.status === 'VALID' ? "font-bold text-emerald-400" : "font-bold text-rose-400";
                reportStatus.textContent = d.status;
                document.getElementById('auditReportTotal').textContent = d.total_events_verified || 0;
                document.getElementById('auditReportHead').textContent = d.chain_head_hash || 'GENESIS';
                document.getElementById('auditReportSummary').textContent = d.summary_message || 'Verification complete.';
                fetchObservabilityHealth();
            } catch (e) {
                reportStatus.className = "font-bold text-rose-400";
                reportStatus.textContent = "VERIFICATION_ERROR";
            }
        }

        async function fetchPaperWorkersStatus() {
            try {
                const res = await fetch('/api/observability/control/workers');
                if (!res.ok) return;
                const d = await res.json();
                const tbody = document.getElementById('obsWorkerTableBody');
                const workers = d.workers || [];
                if (workers.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="4" class="p-3 text-center text-zinc-500 font-mono">Zero simulated paper workers running.</td></tr>';
                } else {
                    tbody.innerHTML = workers.map(w => `
                        <tr class="hover:bg-zinc-800/30">
                            <td class="p-2 font-bold text-white">${w.symbol}</td>
                            <td class="p-2"><span class="px-1.5 py-0.5 rounded text-[10px] ${w.state === 'RUNNING' ? 'bg-emerald-950 text-emerald-400' : 'bg-amber-950 text-amber-400'}">${w.state}</span></td>
                            <td class="p-2 text-zinc-400">${w.ticks_processed || 0}</td>
                            <td class="p-2 text-right">
                                ${w.state === 'RUNNING' 
                                    ? `<button onclick="pausePaperWorker('${w.symbol}')" class="px-2 py-0.5 bg-amber-900/60 hover:bg-amber-800 text-[10px] text-amber-200 rounded">Pause</button>`
                                    : `<button onclick="resumePaperWorker('${w.symbol}')" class="px-2 py-0.5 bg-emerald-900/60 hover:bg-emerald-800 text-[10px] text-emerald-200 rounded">Resume</button>`
                                }
                            </td>
                        </tr>
                    `).join('');
                }
            } catch (e) { console.warn('Paper workers fetch error:', e); }
        }

        async function pausePaperWorker(symbol) {
            try {
                const res = await fetch(`/api/observability/control/workers/${symbol}/pause`, { method: 'POST' });
                if (res.ok) fetchPaperWorkersStatus();
            } catch (e) { console.warn('Pause worker error:', e); }
        }

        async function resumePaperWorker(symbol) {
            try {
                const res = await fetch(`/api/observability/control/workers/${symbol}/resume`, { method: 'POST' });
                if (res.ok) fetchPaperWorkersStatus();
            } catch (e) { console.warn('Resume worker error:', e); }
        }

        async function investigateTrace() {
            const query = document.getElementById('traceQueryInput').value.trim();
            if (!query) return;
            const container = document.getElementById('traceResultContainer');
            container.classList.remove('hidden');
            document.getElementById('traceResCorrId').textContent = query;
            document.getElementById('traceResDuration').textContent = "Reconstructing...";

            try {
                const res = await fetch(`/api/observability/trace/${query}`);
                if (!res.ok) {
                    document.getElementById('traceResStatus').textContent = "TRACE_NOT_FOUND";
                    return;
                }
                const d = await res.json();
                document.getElementById('traceResCorrId').textContent = d.correlation_id || query;
                document.getElementById('traceResDuration').textContent = `${(d.total_duration_ms || 0).toFixed(1)}ms`;
                document.getElementById('traceResStages').textContent = (d.stages_traversed || []).join(' → ') || 'NONE';
                document.getElementById('traceResStatus').textContent = d.final_status || 'COMPLETED';

                // Render explainability
                const exp = d.explainability;
                if (exp) {
                    document.getElementById('traceExpDecision').textContent = `${exp.decision_type} (${exp.final_decision})`;
                    document.getElementById('traceExpConviction').textContent = `${exp.direction} • ${(exp.conviction * 100).toFixed(1)}%`;
                    document.getElementById('traceExpReason').textContent = exp.decision_reason || 'None provided';
                } else {
                    document.getElementById('traceExpDecision').textContent = 'No decision explainability attached.';
                    document.getElementById('traceExpConviction').textContent = '—';
                    document.getElementById('traceExpReason').textContent = '—';
                }

                // Render event sequence tree
                const eventsList = document.getElementById('traceEventsList');
                const events = d.events || [];
                if (events.length === 0) {
                    eventsList.innerHTML = '<div class="text-zinc-500">No operational events found for this correlation ID.</div>';
                } else {
                    eventsList.innerHTML = events.map(e => `
                        <div class="p-2 rounded bg-zinc-900/50 border border-zinc-800/60 flex items-center justify-between">
                            <div>
                                <span class="font-bold text-teal-400">[${e.category}]</span>
                                <span class="text-white ml-1">${e.event_type}</span>
                                <span class="text-zinc-500 text-[10px] ml-2">seq=#${e.sequence_number}</span>
                            </div>
                            <div class="text-zinc-400 text-[10px]">${e.timestamp ? new Date(e.timestamp).toLocaleTimeString() : ''}</div>
                        </div>
                    `).join('');
                }
            } catch (e) {
                console.warn('Trace investigation error:', e);
            }
        }

        // ═══════════ Phase 24: Deterministic Historical Replay Functions ═══════════

        async function fetchReplayRuns() {
            try {
                const res = await fetch('/api/replay/runs');
                if (!res.ok) return;
                const d = await res.json();
                if (d.runs && d.runs.length > 0) {
                    const latest = d.runs[d.runs.length - 1];
                    const fullRes = await fetch(`/api/replay/runs/${latest.run_id}`);
                    if (fullRes.ok) {
                        const fullData = await fullRes.json();
                        renderReplayResult(fullData);
                    }
                }
            } catch (e) { console.warn('Fetch replay runs error:', e); }
        }

        async function triggerReplayRun() {
            const symsRaw = document.getElementById('replaySymbolsInput').value;
            const symbols = symsRaw.split(',').map(s => s.trim()).filter(Boolean);
            const bars = parseInt(document.getElementById('replayBarsInput').value) || 30;
            const capital = parseFloat(document.getElementById('replayCapitalInput').value) || 100000;
            const slippage = (parseFloat(document.getElementById('replaySlippageInput').value) || 0.05) / 100.0;
            const brokerage = (parseFloat(document.getElementById('replayBrokerageInput').value) || 0.03) / 100.0;
            const mode = document.getElementById('replayModeSelect').value;

            const payload = {
                symbols: symbols,
                bars_per_symbol: bars,
                config: {
                    initial_capital: capital,
                    symbols: symbols,
                    replay_mode: mode,
                    execution_assumptions: {
                        slippage_pct: slippage,
                        brokerage_pct: brokerage,
                        enable_costs: true
                    }
                }
            };

            try {
                const res = await fetch('/api/replay/run', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                if (res.ok) {
                    const data = await res.json();
                    renderReplayResult(data);
                }
            } catch (e) { console.warn('Trigger replay error:', e); }
        }

        async function triggerWalkForwardRun() {
            const symsRaw = document.getElementById('replaySymbolsInput').value;
            const symbols = symsRaw.split(',').map(s => s.trim()).filter(Boolean);
            const bars = Math.max(parseInt(document.getElementById('replayBarsInput').value) || 30, 40);

            const payload = {
                symbols: symbols,
                bars_per_symbol: bars,
                config: {
                    symbols: symbols,
                    walk_forward_enabled: true
                }
            };

            try {
                const res = await fetch('/api/replay/walk-forward', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                if (res.ok) {
                    const data = await res.json();
                    renderReplayResult(data);
                }
            } catch (e) { console.warn('Trigger walk-forward error:', e); }
        }

        function renderReplayResult(d) {
            if (!d) return;
            const p = d.performance || {};

            document.getElementById('replayFinalEquity').textContent = `₹${(d.final_equity || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}`;
            document.getElementById('replayRealizedPnl').textContent = `P&L: ₹${(p.realized_pnl || 0).toFixed(2)}`;
            document.getElementById('replayTotalReturn').textContent = `${(p.total_return_pct || 0).toFixed(2)}%`;
            document.getElementById('replayTotalReturn').className = (p.total_return_pct >= 0) ? "text-lg font-bold text-emerald-400 font-mono mt-1" : "text-lg font-bold text-rose-400 font-mono mt-1";
            document.getElementById('replayMaxDrawdown').textContent = `${(p.max_drawdown_pct || 0).toFixed(2)}%`;
            document.getElementById('replayWinRate').textContent = `${(p.win_rate_pct || 0).toFixed(1)}%`;
            document.getElementById('replayTradeCount').textContent = `${p.total_trades || 0} Trades (${p.winning_trades || 0}W / ${p.losing_trades || 0}L)`;
            document.getElementById('replayProfitFactor').textContent = p.profit_factor != null ? p.profit_factor.toFixed(2) : '—';
            document.getElementById('replaySharpeSortino').textContent = `${p.sharpe_ratio != null ? p.sharpe_ratio.toFixed(2) : '—'} / ${p.sortino_ratio != null ? p.sortino_ratio.toFixed(2) : '—'}`;

            // Fingerprint
            document.getElementById('replayRunId').textContent = d.run_id || '—';
            document.getElementById('replayFingerprintHash').textContent = d.fingerprint || '—';
            document.getElementById('replaySeed').textContent = (d.config && d.config.seed != null) ? d.config.seed : '42';

            // Walk-Forward Partitions
            const wfBody = document.getElementById('replayWalkForwardBody');
            const partitions = d.walk_forward_partitions || [];
            if (partitions.length === 0) {
                wfBody.innerHTML = '<tr><td colspan="4" class="p-3 text-center text-zinc-500 font-mono">Standard single replay executed. Click \'Walk-Forward\' for cross validation.</td></tr>';
            } else {
                wfBody.innerHTML = partitions.map(w => `
                    <tr class="hover:bg-zinc-800/30">
                        <td class="p-2 font-bold text-white">#${w.window_index}</td>
                        <td class="p-2 ${(w.in_sample_return_pct >= 0) ? 'text-emerald-400' : 'text-rose-400'}">${w.in_sample_return_pct.toFixed(2)}%</td>
                        <td class="p-2 ${(w.out_of_sample_return_pct >= 0) ? 'text-cyan-400 font-bold' : 'text-rose-400 font-bold'}">${w.out_of_sample_return_pct.toFixed(2)}%</td>
                        <td class="p-2 text-right text-zinc-300">${w.trades_count}</td>
                    </tr>
                `).join('');
            }

            // Trade Ledger
            const tradeBody = document.getElementById('replayTradeTableBody');
            const trades = d.trade_ledger || [];
            if (trades.length === 0) {
                tradeBody.innerHTML = '<tr><td colspan="10" class="p-3 text-center text-zinc-500 font-mono">Zero trades met entry criteria during this period.</td></tr>';
            } else {
                tradeBody.innerHTML = trades.map(t => `
                    <tr class="hover:bg-zinc-800/30">
                        <td class="p-2 text-zinc-400">${t.trade_id}</td>
                        <td class="p-2 font-bold text-white">${t.symbol}</td>
                        <td class="p-2"><span class="px-1.5 py-0.5 rounded text-[10px] bg-emerald-950 text-emerald-400">${t.side}</span></td>
                        <td class="p-2 text-zinc-300">₹${t.entry_price.toFixed(2)}</td>
                        <td class="p-2 text-zinc-300">${t.exit_price != null ? `₹${t.exit_price.toFixed(2)}` : '—'}</td>
                        <td class="p-2 text-zinc-400">${t.quantity}</td>
                        <td class="p-2 font-bold ${(t.net_pnl >= 0) ? 'text-emerald-400' : 'text-rose-400'}">₹${t.net_pnl.toFixed(2)}</td>
                        <td class="p-2 ${(t.return_pct >= 0) ? 'text-emerald-400' : 'text-rose-400'}">${t.return_pct.toFixed(2)}%</td>
                        <td class="p-2 text-zinc-400">${t.exit_reason}</td>
                        <td class="p-2 text-right text-teal-400 font-mono text-[10px]">${t.correlation_id}</td>
                    </tr>
                `).join('');
            }
        }

        // ════════════════════ PHASE 25: STRATEGY ROBUSTNESS FUNCTIONS ════════════════════
        async function fetchRobustnessReports() {
            try {
                const res = await fetch('/api/robustness/reports');
                const d = await res.json();
                if (d.reports && d.reports.length > 0) {
                    const latest = d.reports[d.reports.length - 1];
                    const fullRes = await fetch(`/api/robustness/report/${latest.analysis_id}`);
                    const fullData = await fullRes.json();
                    renderRobustnessReport(fullData);
                }
            } catch (e) {
                console.error("fetchRobustnessReports error:", e);
            }
        }

        async function triggerRobustnessAnalysis() {
            try {
                const symStr = document.getElementById('robustSymbolsInput').value;
                const symbols = symStr.split(',').map(s => s.trim()).filter(s => s.length > 0);
                const bars = parseInt(document.getElementById('robustBarsInput').value) || 35;
                const mcIter = parseInt(document.getElementById('robustMCIterationsSelect').value) || 500;

                const payload = {
                    symbols: symbols,
                    bars_per_symbol: bars,
                    monte_carlo_iterations: mcIter,
                    seed: 42
                };

                const res = await fetch('/api/robustness/analyze', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                const data = await res.json();
                renderRobustnessReport(data);
            } catch (e) {
                console.error("triggerRobustnessAnalysis error:", e);
            }
        }

        function renderRobustnessReport(d) {
            if (!d) return;

            // Badges & Score
            const sc = d.scorecard || {};
            const score = sc.overall_score || 0;
            const cls = sc.classification || 'INSUFFICIENT_DATA';

            document.getElementById('robustScoreBadge').textContent = `Score: ${score.toFixed(1)} / 100`;
            document.getElementById('robustClassBadge').textContent = cls;
            document.getElementById('kpiRobustScore').textContent = `${score.toFixed(1)}`;
            document.getElementById('kpiRobustClass').textContent = cls;

            // Top KPIs
            const surfaces = d.sensitivity || [];
            const cliff = surfaces.some(s => s.performance_cliff_detected);
            document.getElementById('kpiParamStability').textContent = cliff ? "CLIFF DETECTED" : "STABLE PLATEAU";
            document.getElementById('kpiParamStability').className = cliff ? "text-xl font-bold font-mono text-rose-400 mt-1" : "text-xl font-bold font-mono text-emerald-400 mt-1";

            const mc = d.monte_carlo || {};
            document.getElementById('kpiMCDrawdown').textContent = `${(mc.drawdown_p95 || 0).toFixed(2)}%`;
            document.getElementById('mcProbLossBadge').textContent = `Prob of Loss: ${((mc.probability_of_net_loss || 0) * 100).toFixed(1)}%`;

            const frics = d.friction_stress || [];
            const sevFric = frics.find(f => f.stress_level === 'SEVERE_STRESS') || {};
            document.getElementById('kpiSevereFriction').textContent = `${(sevFric.total_return_pct || 0).toFixed(2)}%`;
            document.getElementById('kpiSevereFriction').className = (sevFric.total_return_pct >= 0) ? "text-xl font-bold font-mono text-emerald-400 mt-1" : "text-xl font-bold font-mono text-rose-400 mt-1";

            const of = d.overfitting || {};
            document.getElementById('kpiSymbolShare').textContent = `${(of.dominant_symbol_share_pct || 0).toFixed(1)}%`;

            // 12-Category Scorecard Grid
            const catGrid = document.getElementById('scorecardCategoriesGrid');
            const categories = sc.categories || [];
            if (categories.length > 0) {
                catGrid.innerHTML = categories.map(c => `
                    <div class="p-3 rounded-lg border ${c.passed ? 'bg-zinc-900/60 border-zinc-800' : 'bg-rose-950/20 border-rose-900/60'} space-y-1">
                        <div class="flex items-center justify-between">
                            <span class="text-[11px] font-mono font-bold text-zinc-300">${c.category_name}</span>
                            <span class="text-[10px] font-mono px-1.5 py-0.5 rounded ${c.passed ? 'bg-emerald-950 text-emerald-400 border border-emerald-800' : 'bg-rose-950 text-rose-400 border border-rose-800'}">
                                ${c.score.toFixed(0)}/100
                            </span>
                        </div>
                        <p class="text-[10px] text-zinc-400 font-mono line-clamp-2">${c.evidence || '—'}</p>
                    </div>
                `).join('');
            }

            // Monte Carlo Percentile Table
            const mcBody = document.getElementById('mcPercentilesTableBody');
            if (mc.insufficient_data) {
                mcBody.innerHTML = '<tr><td colspan="6" class="p-3 text-center text-amber-500 font-mono">Insufficient trade sample size for Monte Carlo resampling.</td></tr>';
            } else {
                mcBody.innerHTML = `
                    <tr class="hover:bg-zinc-800/30">
                        <td class="p-2 font-bold text-white">Final Equity (₹)</td>
                        <td class="p-2 text-rose-400">₹${(mc.equity_p5 || 0).toFixed(0)}</td>
                        <td class="p-2 text-zinc-300">₹${(mc.equity_p25 || 0).toFixed(0)}</td>
                        <td class="p-2 text-cyan-400 font-bold">₹${(mc.equity_p50 || 0).toFixed(0)}</td>
                        <td class="p-2 text-zinc-300">₹${(mc.equity_p75 || 0).toFixed(0)}</td>
                        <td class="p-2 text-emerald-400 font-bold">₹${(mc.equity_p95 || 0).toFixed(0)}</td>
                    </tr>
                    <tr class="hover:bg-zinc-800/30">
                        <td class="p-2 font-bold text-white">Total Return %</td>
                        <td class="p-2 text-rose-400">${(mc.return_p5 || 0).toFixed(2)}%</td>
                        <td class="p-2 text-zinc-300">${(mc.return_p25 || 0).toFixed(2)}%</td>
                        <td class="p-2 text-cyan-400 font-bold">${(mc.return_p50 || 0).toFixed(2)}%</td>
                        <td class="p-2 text-zinc-300">${(mc.return_p75 || 0).toFixed(2)}%</td>
                        <td class="p-2 text-emerald-400 font-bold">${(mc.return_p95 || 0).toFixed(2)}%</td>
                    </tr>
                    <tr class="hover:bg-zinc-800/30">
                        <td class="p-2 font-bold text-white">Max Drawdown %</td>
                        <td class="p-2 text-emerald-400">${(mc.drawdown_p5 || 0).toFixed(2)}%</td>
                        <td class="p-2 text-zinc-400">—</td>
                        <td class="p-2 text-yellow-400 font-bold">${(mc.drawdown_p50 || 0).toFixed(2)}%</td>
                        <td class="p-2 text-zinc-400">—</td>
                        <td class="p-2 text-rose-400 font-bold">${(mc.drawdown_p95 || 0).toFixed(2)}%</td>
                    </tr>
                `;
            }

            // Market Regime Attribution Table
            const rBody = document.getElementById('regimeTableBody');
            const regimes = d.regimes || [];
            if (regimes.length === 0) {
                rBody.innerHTML = '<tr><td colspan="6" class="p-3 text-center text-zinc-500 font-mono">No regime attributions available.</td></tr>';
            } else {
                rBody.innerHTML = regimes.map(r => `
                    <tr class="hover:bg-zinc-800/30">
                        <td class="p-2 font-bold text-white">${r.regime_type}</td>
                        <td class="p-2 text-zinc-300">${r.trades_count}</td>
                        <td class="p-2 ${(r.total_return_pct >= 0) ? 'text-emerald-400' : 'text-rose-400'}">${r.total_return_pct.toFixed(2)}%</td>
                        <td class="p-2 text-zinc-300">${r.win_rate_pct.toFixed(1)}%</td>
                        <td class="p-2 text-amber-400">${r.max_drawdown_pct.toFixed(2)}%</td>
                        <td class="p-2">
                            <span class="px-1.5 py-0.5 rounded text-[10px] ${r.is_failing_regime ? 'bg-rose-950 text-rose-400 border border-rose-800' : 'bg-emerald-950 text-emerald-400 border border-emerald-800'}">
                                ${r.is_failing_regime ? 'FAIL' : 'PASS'}
                            </span>
                        </td>
                    </tr>
                `).join('');
            }

            // Friction Stress Table
            const fBody = document.getElementById('frictionStressTableBody');
            if (frics.length === 0) {
                fBody.innerHTML = '<tr><td colspan="6" class="p-3 text-center text-zinc-500 font-mono">No friction stress matrix available.</td></tr>';
            } else {
                fBody.innerHTML = frics.map(f => `
                    <tr class="hover:bg-zinc-800/30">
                        <td class="p-2 font-bold text-white">${f.stress_level}</td>
                        <td class="p-2 text-zinc-300">${(f.slippage_pct * 100).toFixed(2)}%</td>
                        <td class="p-2 text-zinc-300">${(f.total_roundtrip_cost_pct * 100).toFixed(3)}%</td>
                        <td class="p-2 ${(f.total_return_pct >= 0) ? 'text-emerald-400' : 'text-rose-400'}">${f.total_return_pct.toFixed(2)}%</td>
                        <td class="p-2 text-zinc-400">-${f.return_degradation_pct.toFixed(2)}%</td>
                        <td class="p-2">
                            <span class="px-1.5 py-0.5 rounded text-[10px] ${f.is_profitable ? 'bg-emerald-950 text-emerald-400 border border-emerald-800' : 'bg-rose-950 text-rose-400 border border-rose-800'}">
                                ${f.is_profitable ? 'PROFITABLE' : 'UNVIABLE'}
                            </span>
                        </td>
                    </tr>
                `).join('');
            }

            // Symbol Robustness & Leave-One-Out Table
            const sBody = document.getElementById('symbolRobustnessTableBody');
            const syms = d.symbol_contributions || [];
            const losos = d.leave_one_out || [];
            if (syms.length === 0) {
                sBody.innerHTML = '<tr><td colspan="6" class="p-3 text-center text-zinc-500 font-mono">No symbol concentration data available.</td></tr>';
            } else {
                sBody.innerHTML = syms.map(s => {
                    const loso = losos.find(l => l.omitted_symbol === s.symbol) || {};
                    return `
                        <tr class="hover:bg-zinc-800/30">
                            <td class="p-2 font-bold text-white">${s.symbol}</td>
                            <td class="p-2 text-zinc-300">${s.trades_count}</td>
                            <td class="p-2 ${(s.realized_pnl >= 0) ? 'text-emerald-400' : 'text-rose-400'}">₹${s.realized_pnl.toFixed(2)}</td>
                            <td class="p-2 text-cyan-300 font-bold">${s.contribution_to_total_return_pct.toFixed(1)}%</td>
                            <td class="p-2 text-zinc-300">${loso.total_return_pct != null ? `${loso.total_return_pct.toFixed(2)}%` : '—'}</td>
                            <td class="p-2">
                                <span class="px-1.5 py-0.5 rounded text-[10px] ${loso.is_viable !== false ? 'bg-emerald-950 text-emerald-400 border border-emerald-800' : 'bg-rose-950 text-rose-400 border border-rose-800'}">
                                    ${loso.is_viable !== false ? 'YES' : 'NO'}
                                </span>
                            </td>
                        </tr>
                    `;
                }).join('');
            }
        }

        // ════════════════════ PHASE 26: FORWARD VALIDATION JAVASCRIPT ════════════════════
        let currentForwardSessionId = null;

        async function fetchForwardSessions() {
            try {
                const res = await fetch('/api/forward-validation/sessions');
                if (!res.ok) return;
                const sessions = await res.json();
                const sel = document.getElementById('forwardSessionSelect');
                if (!sel) return;

                if (!sessions || sessions.length === 0) {
                    sel.innerHTML = '<option value="">No Active Sessions</option>';
                    return;
                }

                sel.innerHTML = sessions.map(s => `
                    <option value="${s.session_id}" ${s.session_id === currentForwardSessionId ? 'selected' : ''}>
                        ${s.session_id} (${s.state})
                    </option>
                `).join('');

                if (!currentForwardSessionId || !sessions.some(s => s.session_id === currentForwardSessionId)) {
                    currentForwardSessionId = sessions[0].session_id;
                }
                loadSelectedSession();
            } catch (err) {
                console.error("Failed to fetch forward sessions:", err);
            }
        }

        async function createForwardSession() {
            try {
                const res = await fetch('/api/forward-validation/sessions', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ symbols: ["TCS.NS", "RELIANCE.NS", "INFY.NS"], mode: "HYBRID" })
                });
                if (res.ok) {
                    const session = await res.json();
                    currentForwardSessionId = session.session_id;
                    await fetchForwardSessions();
                }
            } catch (err) {
                console.error("Failed to create forward session:", err);
            }
        }

        async function loadSelectedSession() {
            const sel = document.getElementById('forwardSessionSelect');
            if (sel && sel.value) {
                currentForwardSessionId = sel.value;
            }
            if (!currentForwardSessionId) return;

            try {
                const res = await fetch(`/api/forward-validation/sessions/${currentForwardSessionId}/report`);
                if (!res.ok) return;
                const report = await res.json();
                renderForwardSessionData(report);
            } catch (err) {
                console.error("Failed to load forward session report:", err);
            }
        }

        async function startActiveSession() {
            if (!currentForwardSessionId) return;
            await fetch(`/api/forward-validation/sessions/${currentForwardSessionId}/start`, { method: 'POST' });
            loadSelectedSession();
        }

        async function pauseActiveSession() {
            if (!currentForwardSessionId) return;
            await fetch(`/api/forward-validation/sessions/${currentForwardSessionId}/pause`, { method: 'POST' });
            loadSelectedSession();
        }

        async function resumeActiveSession() {
            if (!currentForwardSessionId) return;
            await fetch(`/api/forward-validation/sessions/${currentForwardSessionId}/resume`, { method: 'POST' });
            loadSelectedSession();
        }

        async function stopActiveSession() {
            if (!currentForwardSessionId) return;
            await fetch(`/api/forward-validation/sessions/${currentForwardSessionId}/stop`, { method: 'POST' });
            loadSelectedSession();
        }

        async function injectForwardTick() {
            if (!currentForwardSessionId) return;
            const sym = document.getElementById('quickTickSymbol')?.value || "TCS.NS";
            const price = parseFloat(document.getElementById('quickTickPrice')?.value || "3520.0");
            await fetch(`/api/forward-validation/sessions/${currentForwardSessionId}/tick`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ symbol: sym, price: price })
            });
            loadSelectedSession();
        }

        async function runForwardSimulationWave() {
            if (!currentForwardSessionId) {
                await createForwardSession();
                await startActiveSession();
            } else {
                const sel = document.getElementById('forwardSessionSelect');
                if (sel && sel.options[sel.selectedIndex]?.text.includes("CREATED")) {
                    await startActiveSession();
                }
            }

            const sym = document.getElementById('quickTickSymbol')?.value || "TCS.NS";
            let baseP = parseFloat(document.getElementById('quickTickPrice')?.value || "3520.0");

            for (let i = 0; i < 12; i++) {
                const delta = (Math.sin(i * 0.8) * 15.0) + (i * 2.0);
                const p = Math.round((baseP + delta) * 100) / 100;
                await fetch(`/api/forward-validation/sessions/${currentForwardSessionId}/tick`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ symbol: sym, price: p })
                });
            }
            loadSelectedSession();
        }

        function renderForwardSessionData(report) {
            if (!report) return;
            const s = report.session;
            const p = report.performance;
            const eq = report.execution_quality;
            const dq = report.data_quality;
            const sig = report.signal_drift;
            const strat = report.strategy_drift;
            const sc = report.scorecard;

            // Badges & KPIs
            document.getElementById('forwardStateBadge').textContent = `State: ${s.state}`;
            document.getElementById('forwardModeBadge').textContent = `${s.mode}`;
            document.getElementById('kpiForwardState').textContent = s.state;
            document.getElementById('kpiForwardDecisions').textContent = `${s.decisions_count} (${report.decisions?.length || 0})`;
            document.getElementById('kpiForwardFillRate').textContent = `${eq.fill_rate_pct.toFixed(0)}%`;
            document.getElementById('kpiForwardDrift').textContent = strat.drift_state;
            document.getElementById('kpiForwardLatency').textContent = `${eq.order_to_fill_latency_ms_p95.toFixed(1)} ms`;
            document.getElementById('kpiForwardScorecard').textContent = sc.status;

            // Scorecard
            document.getElementById('forwardScorecardScore').textContent = `Score: ${sc.overall_score.toFixed(1)} / 100 (${sc.status})`;
            const scGrid = document.getElementById('forwardScorecardGrid');
            if (scGrid && sc.categories) {
                scGrid.innerHTML = sc.categories.map(c => `
                    <div class="p-3 bg-zinc-900/60 rounded-lg border ${c.passed ? 'border-zinc-800' : 'border-rose-900/60'} font-mono text-xs space-y-1">
                        <div class="flex items-center justify-between">
                            <span class="font-bold text-white">${c.category_name}</span>
                            <span class="px-1.5 py-0.2 rounded text-[10px] ${c.passed ? 'bg-emerald-950 text-emerald-400 border border-emerald-800' : 'bg-rose-950 text-rose-400 border border-rose-800'}">
                                ${c.score.toFixed(0)}
                            </span>
                        </div>
                        <p class="text-[10px] text-zinc-400 leading-tight">${c.evidence || c.status}</p>
                    </div>
                `).join('');
            }

            // Data Quality
            document.getElementById('forwardDQScore').textContent = `Quality: ${dq.quality_score.toFixed(1)}/100`;
            document.getElementById('teleTickRate').textContent = `${dq.tick_rate_per_sec.toFixed(1)} /s`;
            document.getElementById('teleStaleTicks').textContent = dq.stale_ticks_count;
            document.getElementById('teleOutOfOrder').textContent = dq.out_of_order_count;
            document.getElementById('teleInvalidPrices').textContent = dq.invalid_prices_count;

            // Execution Quality
            document.getElementById('teleOrderLatP50').textContent = `${eq.order_to_fill_latency_ms_p50.toFixed(1)} ms`;
            document.getElementById('teleOrderLatP95').textContent = `${eq.order_to_fill_latency_ms_p95.toFixed(1)} ms`;
            document.getElementById('teleSlippageP50').textContent = `₹${eq.simulated_slippage_p50.toFixed(2)}`;
            document.getElementById('teleSlippageP95').textContent = `₹${eq.simulated_slippage_p95.toFixed(2)}`;

            // Drift
            document.getElementById('forwardDriftBadge').textContent = `Status: ${strat.drift_state}`;
            document.getElementById('driftObservedSig').textContent = sig.signal_mean != null ? sig.signal_mean.toFixed(2) : '--';
            document.getElementById('driftDelta').textContent = sig.drift_delta != null ? `${sig.drift_delta.toFixed(2)}` : '--';
            document.getElementById('driftRollingWR').textContent = `${strat.win_rate_rolling_pct.toFixed(1)}%`;

            // Regime transitions
            const regTbody = document.getElementById('regimeTransitionsTableBody');
            if (regTbody) {
                if (!report.regime_transitions || report.regime_transitions.length === 0) {
                    regTbody.innerHTML = '<tr><td colspan="4" class="p-2 text-center text-zinc-500 font-mono">No regime transitions logged.</td></tr>';
                } else {
                    regTbody.innerHTML = report.regime_transitions.slice(-5).reverse().map(t => `
                        <tr class="hover:bg-zinc-900/50">
                            <td class="p-1.5">${new Date(t.timestamp).toLocaleTimeString()}</td>
                            <td class="p-1.5 text-cyan-300 font-bold">${t.previous_regime} &rarr; ${t.new_regime}</td>
                            <td class="p-1.5">${t.strategy_exposure_pct.toFixed(0)}%</td>
                            <td class="p-1.5"><span class="px-1.5 py-0.2 rounded text-[10px] bg-zinc-800 text-zinc-300">${t.risk_state}</span></td>
                        </tr>
                    `).join('');
                }
            }

            // Outcomes
            const outTbody = document.getElementById('forwardOutcomesTableBody');
            if (outTbody) {
                if (!report.outcomes || report.outcomes.length === 0) {
                    outTbody.innerHTML = '<tr><td colspan="9" class="p-3 text-center text-zinc-500 font-mono">No outcomes realized yet.</td></tr>';
                } else {
                    outTbody.innerHTML = report.outcomes.slice(-8).reverse().map(o => `
                        <tr class="hover:bg-zinc-900/50">
                            <td class="p-2 text-zinc-400 font-bold">${o.decision_id}</td>
                            <td class="p-2 text-cyan-400">${o.symbol}</td>
                            <td class="p-2">₹${o.entry_price.toFixed(2)}</td>
                            <td class="p-2">${o.exit_price != null ? `₹${o.exit_price.toFixed(2)}` : '—'}</td>
                            <td class="p-2 text-emerald-400 font-bold">+${o.maximum_favorable_excursion_pct.toFixed(2)}%</td>
                            <td class="p-2 text-rose-400 font-bold">${o.maximum_adverse_excursion_pct.toFixed(2)}%</td>
                            <td class="p-2 font-bold ${(o.return_pct >= 0) ? 'text-emerald-400' : 'text-rose-400'}">${o.return_pct >= 0 ? '+' : ''}${o.return_pct.toFixed(2)}%</td>
                            <td class="p-2">${o.holding_duration_seconds.toFixed(0)}s</td>
                            <td class="p-2">
                                <span class="px-1.5 py-0.5 rounded text-[10px] ${(o.status === 'TARGET_REACHED' || o.status === 'WIN') ? 'bg-emerald-950 text-emerald-400 border border-emerald-800' : (o.status === 'PENDING' ? 'bg-zinc-800 text-zinc-300' : 'bg-rose-950 text-rose-400 border border-rose-800')}">
                                    ${o.status}
                                </span>
                            </td>
                        </tr>
                    `).join('');
                }
            }

            // Comparisons
            const compTbody = document.getElementById('forwardComparisonTableBody');
            if (compTbody && report.comparisons) {
                compTbody.innerHTML = report.comparisons.map(c => `
                    <tr class="hover:bg-zinc-900/50">
                        <td class="p-2 font-bold text-white">${c.metric_name}</td>
                        <td class="p-2 text-zinc-300">${c.expected_backtest_value.toFixed(1)}</td>
                        <td class="p-2 text-cyan-300 font-bold">${c.observed_forward_value.toFixed(1)}</td>
                        <td class="p-2 ${(c.deviation_pct >= 0) ? 'text-emerald-400' : 'text-rose-400'}">${c.deviation_pct >= 0 ? '+' : ''}${c.deviation_pct.toFixed(1)}</td>
                        <td class="p-2">
                            <span class="px-1.5 py-0.5 rounded text-[10px] ${c.sample_sufficient ? 'bg-zinc-800 text-zinc-300' : 'bg-yellow-950 text-yellow-400 border border-yellow-800'}">
                                ${c.sample_sufficient ? 'SUFFICIENT' : 'PRELIMINARY'}
                            </span>
                        </td>
                        <td class="p-2">
                            <span class="px-1.5 py-0.5 rounded text-[10px] ${!c.is_degraded ? 'bg-emerald-950 text-emerald-400 border border-emerald-800' : 'bg-rose-950 text-rose-400 border border-rose-800'}">
                                ${!c.is_degraded ? 'CONSISTENT' : 'DEGRADED'}
                            </span>
                        </td>
                    </tr>
                `).join('');
            }
        }
        // ════════════════════ PHASE 27: SYSTEM CERTIFICATION JAVASCRIPT ════════════════════
        async function fetchSystemCertificationData() {
            try {
                await fetchSystemHealthSummary();
                const res = await fetch('/api/system/certification');
                if (!res.ok) return;
                const rep = await res.json();
                renderCertificationReport(rep);
            } catch (err) {
                console.error("Failed to fetch system certification data:", err);
            }
        }

        async function triggerSystemCertification() {
            try {
                const res = await fetch('/api/system/certification');
                if (res.ok) {
                    const rep = await res.json();
                    renderCertificationReport(rep);
                }
            } catch (err) {
                console.error("Failed to trigger certification:", err);
            }
        }

        async function createSystemCheckpoint() {
            try {
                const res = await fetch('/api/system/checkpoint', { method: 'POST' });
                if (res.ok) {
                    const chk = await res.json();
                    document.getElementById('certLatestCheckpointId').textContent = chk.checkpoint_id;
                    document.getElementById('certLatestChecksum').textContent = chk.payload_checksum;
                    document.getElementById('certSealedEvents').textContent = `${chk.audit_event_count} events`;
                    document.getElementById('kpiCertCheckpoint').textContent = "VALID";
                }
            } catch (err) {
                console.error("Failed to create checkpoint:", err);
            }
        }

        async function fetchSystemHealthSummary() {
            try {
                const res = await fetch('/api/system/health/summary');
                if (!res.ok) return;
                const health = await res.json();
                renderHealthSummary(health);
            } catch (err) {
                console.error("Failed to fetch health summary:", err);
            }
        }

        async function triggerGracefulShutdown() {
            if (!confirm("Are you sure you want to gracefully drain paper operations and shutdown?")) return;
            try {
                const res = await fetch('/api/system/shutdown', { method: 'POST' });
                if (res.ok) {
                    const data = await res.json();
                    document.getElementById('certStateBadge').textContent = `State: ${data.operational_state}`;
                    document.getElementById('kpiCertState').textContent = data.operational_state;
                    alert(`Graceful shutdown initiated: ${data.operational_state}`);
                }
            } catch (err) {
                console.error("Failed to trigger graceful shutdown:", err);
            }
        }

        function renderHealthSummary(health) {
            if (!health) return;
            document.getElementById('certStateBadge').textContent = `State: ${health.operational_state}`;
            document.getElementById('kpiCertState').textContent = health.operational_state;
            document.getElementById('kpiCertLiveness').textContent = health.liveness ? "PASS (UP)" : "FAIL";
            document.getElementById('kpiCertReadiness').textContent = health.readiness ? "PASS" : "FAIL";

            const container = document.getElementById('certSubsystemsContainer');
            if (container) {
                const deps = Object.values(health.dependency_health || {});
                const subs = Object.values(health.subsystem_health || {});
                const all = [...deps, ...subs, health.safety_health].filter(Boolean);

                container.innerHTML = all.map(c => `
                    <div class="flex items-center justify-between p-2 rounded bg-zinc-900/60 border border-zinc-800">
                        <span class="font-bold text-white">${c.name}</span>
                        <span class="px-2 py-0.5 rounded text-[10px] ${c.status === 'HEALTHY' ? 'bg-emerald-950 text-emerald-400 border border-emerald-800' : 'bg-rose-950 text-rose-400 border border-rose-800'}">
                            ${c.status}
                        </span>
                    </div>
                `).join('');
            }
        }

        function renderCertificationReport(rep) {
            if (!rep) return;
            document.getElementById('certStatusBadge').textContent = `Status: ${rep.overall_status}`;
            document.getElementById('kpiCertVerdict').textContent = rep.overall_status;
            document.getElementById('certScorecardScore').textContent = `Score: ${rep.overall_score.toFixed(1)} / 100 (${rep.overall_status})`;
            document.getElementById('certCfgFingerprint').textContent = rep.configuration_fingerprint;

            const grid = document.getElementById('certScorecardGrid');
            if (grid && rep.categories) {
                grid.innerHTML = rep.categories.map(c => `
                    <div class="p-3 bg-zinc-900/60 rounded-lg border ${c.passed ? 'border-zinc-800' : 'border-rose-900/60'} font-mono text-xs space-y-1">
                        <div class="flex items-center justify-between">
                            <span class="font-bold text-white">${c.category_name}</span>
                            <span class="px-1.5 py-0.2 rounded text-[10px] ${c.passed ? 'bg-emerald-950 text-emerald-400 border border-emerald-800' : 'bg-rose-950 text-rose-400 border border-rose-800'}">
                                ${c.score.toFixed(0)}
                            </span>
                        </div>
                        <p class="text-[10px] text-zinc-400 leading-tight">${c.evidence || c.status}</p>
                    </div>
                `).join('');
            }
        }
        // ════════════════════ PHASE 28: DISTRIBUTED STATE & CLUSTER JAVASCRIPT ════════════════════
        async function fetchDistributedClusterData() {
            try {
                const [healthRes, workersRes, recRes] = await Promise.all([
                    fetch('/api/distributed/health'),
                    fetch('/api/distributed/workers'),
                    fetch('/api/distributed/recovery/report')
                ]);

                const health = healthRes.ok ? await healthRes.json() : null;
                const workers = workersRes.ok ? await workersRes.json() : null;
                const recReport = recRes.ok ? await recRes.json() : null;

                renderClusterData(health, workers, recReport);
            } catch (err) {
                console.error("Failed to fetch distributed cluster data:", err);
            }
        }

        async function triggerRecoveryVerification() {
            try {
                const res = await fetch('/api/distributed/recovery/verify', { method: 'POST' });
                if (res.ok) {
                    const report = await res.json();
                    await fetchDistributedClusterData();
                    alert(`14-Step Recovery Complete: ${report.status} (${report.steps_completed}/${report.total_steps} steps passed)`);
                }
            } catch (err) {
                console.error("Failed to trigger recovery verification:", err);
            }
        }

        async function quarantinePartitionFromUI() {
            const sym = document.getElementById('quarantineSymbolInput')?.value?.trim()?.toUpperCase();
            if (!sym) return alert("Please enter a symbol (e.g. TCS.NS)");
            try {
                const res = await fetch(`/api/distributed/workers/${sym}/quarantine`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ reason: "Manual operator quarantine from UI" })
                });
                if (res.ok) {
                    await fetchDistributedClusterData();
                    alert(`Partition ${sym} quarantined.`);
                }
            } catch (err) {
                console.error("Failed to quarantine partition:", err);
            }
        }

        async function unquarantinePartitionFromUI() {
            const sym = document.getElementById('quarantineSymbolInput')?.value?.trim()?.toUpperCase();
            if (!sym) return alert("Please enter a symbol (e.g. TCS.NS)");
            try {
                const res = await fetch(`/api/distributed/workers/${sym}/unquarantine`, { method: 'POST' });
                if (res.ok) {
                    await fetchDistributedClusterData();
                    alert(`Partition ${sym} unquarantined.`);
                }
            } catch (err) {
                console.error("Failed to unquarantine partition:", err);
            }
        }

        function renderClusterData(health, workers, report) {
            if (health) {
                document.getElementById('clusterConsistencyBadge').textContent = `Consistency: ${health.consistency_state}`;
                document.getElementById('clusterCoordBadge').textContent = `Coordination: ${health.coordination_state}`;
                document.getElementById('kpiClusterConsistency').textContent = health.consistency_state;
                document.getElementById('kpiClusterCoord').textContent = health.coordination_state;
                document.getElementById('kpiClusterNodes').textContent = health.node_count;
                document.getElementById('kpiClusterLeases').textContent = health.active_leases_count;
                document.getElementById('kpiClusterRevision').textContent = health.latest_revision;
                document.getElementById('kpiClusterJournal').textContent = health.journal_sequence;
            }

            if (workers) {
                document.getElementById('clusterActiveLeasesCount').textContent = `${workers.active_leases_count} active leases`;
                const tbody = document.getElementById('clusterLeasesTableBody');
                if (tbody) {
                    if (!workers.leases || workers.leases.length === 0) {
                        tbody.innerHTML = '<tr><td colspan="4" class="p-3 text-center text-zinc-500 font-mono">No active partition leases.</td></tr>';
                    } else {
                        tbody.innerHTML = workers.leases.map(l => `
                            <tr class="hover:bg-zinc-900/50">
                                <td class="p-2 text-cyan-400 font-bold">${l.partition}</td>
                                <td class="p-2 text-zinc-300">${l.owner_worker_id}</td>
                                <td class="p-2 text-zinc-400 font-mono text-[10px]">${l.owner_node_id}</td>
                                <td class="p-2"><span class="px-1.5 py-0.5 rounded text-[10px] bg-emerald-950 text-emerald-400 border border-emerald-800">${l.status}</span></td>
                            </tr>
                        `).join('');
                    }
                }

                const qList = document.getElementById('clusterQuarantineList');
                if (qList) {
                    if (!workers.quarantined_partitions || workers.quarantined_partitions.length === 0) {
                        qList.innerHTML = '<div class="p-3 text-center text-zinc-500 font-mono">Zero quarantined partitions. Split-brain guard nominal.</div>';
                        document.getElementById('clusterQuarantineStatus').textContent = "NOMINAL";
                    } else {
                        document.getElementById('clusterQuarantineStatus').textContent = `${workers.quarantined_partitions.length} QUARANTINED`;
                        qList.innerHTML = workers.quarantined_partitions.map(p => `
                            <div class="flex items-center justify-between p-2 bg-amber-950/40 border border-amber-800/60 rounded font-mono text-xs">
                                <span class="text-amber-400 font-bold">${p}</span>
                                <span class="text-rose-400 text-[10px]">EXECUTION_HALTED</span>
                            </div>
                        `).join('');
                    }
                }
            }

            if (report) {
                document.getElementById('clusterRecoveryReportId').textContent = `Report: ${report.report_id}`;
                document.getElementById('clusterRecoveryStatusVal').textContent = report.status;
                document.getElementById('clusterRecoveryRevision').textContent = report.last_valid_revision;
                document.getElementById('clusterRecoveryStateHash').textContent = report.recovered_state_hash ? `${report.recovered_state_hash.substring(0, 16)}...` : '--';

                const stepsUl = document.getElementById('clusterRecoveryStepsList');
                if (stepsUl && report.checks_passed) {
                    stepsUl.innerHTML = report.checks_passed.map(s => `
                        <li class="flex items-center gap-1.5 text-emerald-400">
                            <span>&#10003;</span> <span>${s}</span>
                        </li>
                    `).join('');
                }
            }
        }

        // Initialize on page load
        window.addEventListener('DOMContentLoaded', () => {
            fetchSystemHealthTop();
            fetchLatestRunAudit();
            fetchLiveEvaluationData();
            fetchFactorAndRiskData();
            fetchStreamingData();
            fetchReliabilityData();
            initWebSocketTelemetry();
            startAutoRefresh();
        });
    
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
        // ════════════════════ PHASE 25 MANUAL ORDER GATEWAY ════════════════════
        let activeConfirmationToken = null;
        let activeOrderPayload = null;
        let tokenExpiryInterval = null;

        function toggleManualOrderPriceField() {
            const orderType = document.getElementById('moOrderType')?.value;
            const priceInput = document.getElementById('moPrice');
            if (priceInput) {
                if (orderType === 'MARKET') {
                    priceInput.disabled = true;
                    priceInput.classList.add('opacity-50', 'bg-zinc-800');
                } else {
                    priceInput.disabled = false;
                    priceInput.classList.remove('opacity-50', 'bg-zinc-800');
                }
            }
        }

        async function previewManualOrder() {
            const statusElem = document.getElementById('moFormStatus');
            const previewCard = document.getElementById('moPreviewCard');
            if (statusElem) statusElem.innerText = 'Validating safety gate...';

            const symbol = document.getElementById('moSymbol')?.value.trim().toUpperCase();
            const exchange = document.getElementById('moExchange')?.value;
            const side = document.getElementById('moSide')?.value;
            const qty = parseInt(document.getElementById('moQuantity')?.value || '1', 10);
            const orderType = document.getElementById('moOrderType')?.value;
            const priceVal = document.getElementById('moPrice')?.value;
            const price = orderType === 'LIMIT' ? parseFloat(priceVal) : null;
            const product = document.getElementById('moProduct')?.value;

            activeOrderPayload = {
                symbol: symbol,
                exchange_segment: exchange,
                product_type: product,
                side: side,
                order_type: orderType,
                quantity: qty,
                price: price,
                validity: 'DAY'
            };

            try {
                const res = await fetch('/api/broker/order/preview', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(activeOrderPayload)
                });
                const data = await res.json();

                if (!data || !data.safety_result) {
                    if (statusElem) statusElem.innerText = 'Error generating preview.';
                    return;
                }

                if (!data.safety_result.is_approved) {
                    if (statusElem) statusElem.innerHTML = `<span class="text-rose-400 font-bold">Safety Gate Rejected: ${data.safety_result.reason}</span>`;
                    if (previewCard) previewCard.classList.add('hidden');
                    activeConfirmationToken = null;
                    return;
                }

                if (statusElem) statusElem.innerHTML = `<span class="text-emerald-400 font-bold">Safety Gate Approved</span>`;
                activeConfirmationToken = data.confirmation_token;

                // Populate Preview Card
                document.getElementById('prevSym').innerText = symbol;
                const prevSide = document.getElementById('prevSide');
                if (prevSide) {
                    prevSide.innerText = side;
                    prevSide.className = side === 'BUY' ? 'font-bold text-emerald-400' : 'font-bold text-rose-400';
                }
                document.getElementById('prevQty').innerText = qty;
                document.getElementById('prevVal').innerText = `₹${(data.safety_result.estimated_order_value || 0).toLocaleString('en-IN', {minimumFractionDigits: 2})}`;

                // Setup Expiry Countdown
                if (tokenExpiryInterval) clearInterval(tokenExpiryInterval);
                let expirySec = 120;
                const timerElem = document.getElementById('moTokenExpiryTimer');
                if (timerElem) timerElem.innerText = `Token Valid: ${expirySec}s`;
                tokenExpiryInterval = setInterval(() => {
                    expirySec--;
                    if (expirySec <= 0) {
                        clearInterval(tokenExpiryInterval);
                        if (timerElem) timerElem.innerHTML = `<span class="text-rose-400 font-bold">Token Expired</span>`;
                        activeConfirmationToken = null;
                    } else {
                        if (timerElem) timerElem.innerText = `Token Valid: ${expirySec}s`;
                    }
                }, 1000);

                if (previewCard) previewCard.classList.remove('hidden');
            } catch (err) {
                console.error('Failed to preview order', err);
                if (statusElem) statusElem.innerText = `Preview failed: ${err.message}`;
            }
        }

        async function confirmAndSubmitManualOrder() {
            const submitResultElem = document.getElementById('moSubmitResult');
            if (!activeConfirmationToken || !activeOrderPayload) {
                if (submitResultElem) submitResultElem.innerHTML = `<span class="text-rose-400 font-bold">No active confirmation token. Please preview again.</span>`;
                return;
            }

            if (submitResultElem) submitResultElem.innerHTML = `<span class="text-cyan-400 animate-pulse">Submitting to broker...</span>`;

            try {
                const res = await fetch('/api/broker/order/confirm', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        confirmation_token: activeConfirmationToken,
                        order: activeOrderPayload
                    })
                });
                const data = await res.json();

                if (tokenExpiryInterval) clearInterval(tokenExpiryInterval);
                activeConfirmationToken = null;

                if (data.status === 'REJECTED') {
                    if (submitResultElem) submitResultElem.innerHTML = `<span class="text-rose-400 font-bold">Rejected: ${data.message || data.rejection_reason}</span>`;
                } else {
                    if (submitResultElem) submitResultElem.innerHTML = `<span class="text-emerald-400 font-bold">Submitted! Order ID: ${data.order_id || '--'} (${data.status})</span>`;
                    const queryInput = document.getElementById('moQueryOrderId');
                    if (queryInput && data.order_id) queryInput.value = data.order_id;
                }
            } catch (err) {
                console.error('Failed to submit order', err);
                if (submitResultElem) submitResultElem.innerHTML = `<span class="text-rose-400 font-bold">Submission error: ${err.message}</span>`;
            }
        }

        function cancelManualOrderPreview() {
            if (tokenExpiryInterval) clearInterval(tokenExpiryInterval);
            activeConfirmationToken = null;
            activeOrderPayload = null;
            const previewCard = document.getElementById('moPreviewCard');
            if (previewCard) previewCard.classList.add('hidden');
            const statusElem = document.getElementById('moFormStatus');
            if (statusElem) statusElem.innerText = 'Preview cancelled.';
        }

        async function queryDhanOrderStatus() {
            const orderId = document.getElementById('moQueryOrderId')?.value.trim();
            const outElem = document.getElementById('moQueryStatusOutput');
            if (!orderId) {
                if (outElem) outElem.innerText = 'Please enter an Order ID.';
                return;
            }
            if (outElem) outElem.innerText = 'Querying status...';

            try {
                const res = await fetch(`/api/broker/order/${encodeURIComponent(orderId)}/status`);
                const data = await res.json();
                if (outElem) {
                    if (data.error) {
                        outElem.innerHTML = `<span class="text-rose-400 font-bold">Error: ${data.error}</span>`;
                    } else {
                        outElem.innerHTML = `<span class="text-emerald-300 font-bold">Status: ${data.status}</span> (Dhan: ${data.dhan_status || '--'}) | Filled: ${data.filled_quantity || 0}/${data.quantity || 0} @ Avg ₹${data.average_price || 0}`;
                    }
                }
            } catch (err) {
                if (outElem) outElem.innerHTML = `<span class="text-rose-400">Failed: ${err.message}</span>`;
            }
        }

        async function cancelDhanOrderFromUI() {
            const orderId = document.getElementById('moQueryOrderId')?.value.trim();
            const outElem = document.getElementById('moQueryStatusOutput');
            if (!orderId) {
                if (outElem) outElem.innerText = 'Please enter an Order ID.';
                return;
            }
            if (outElem) outElem.innerText = 'Requesting cancellation...';

            try {
                const res = await fetch(`/api/broker/order/${encodeURIComponent(orderId)}/cancel`, { method: 'POST' });
                const data = await res.json();
                if (outElem) {
                    if (data.cancelled) {
                        outElem.innerHTML = `<span class="text-amber-400 font-bold">Order Cancelled Successfully.</span>`;
                    } else {
                        outElem.innerHTML = `<span class="text-rose-400 font-bold">Cancel Failed: ${data.error || 'Unknown error'}</span>`;
                    }
                }
            } catch (err) {
                if (outElem) outElem.innerHTML = `<span class="text-rose-400 font-bold">Error: ${err.message}</span>`;
            }
        }
        // ════════════════════ PHASE 26 LIVE READINESS & ARMING ════════════════════
        let liveArmCountdownInterval = null;

        async function runLiveReadinessCheck() {
            const indElem = document.getElementById('liveReadinessIndicator');
            const badgeElem = document.getElementById('liveReadinessBadge');
            const sessElem = document.getElementById('liveMarketSessionText');
            const pwrElem = document.getElementById('liveBuyingPowerText');
            const readyElem = document.getElementById('liveOrderReadyText');

            if (badgeElem) badgeElem.innerText = 'AUDITING...';

            try {
                const res = await fetch('/api/broker/live/readiness');
                const data = await res.json();

                if (sessElem) sessElem.innerText = data.market_session || 'UNKNOWN';
                if (pwrElem) pwrElem.innerText = data.buying_power ? `₹${data.buying_power.toLocaleString('en-IN', {minimumFractionDigits: 2})}` : '--';
                if (readyElem) {
                    readyElem.innerText = data.is_ready_for_order ? 'YES (ARMED & READY)' : 'NO';
                    readyElem.className = data.is_ready_for_order ? 'text-emerald-400 font-bold' : 'text-rose-400 font-bold';
                }

                if (indElem && badgeElem) {
                    if (data.overall_status === 'READY') {
                        indElem.className = 'w-3.5 h-3.5 rounded-full bg-emerald-400';
                        badgeElem.className = 'text-[10px] px-2 py-0.5 rounded bg-emerald-950 text-emerald-300 border border-emerald-700 font-mono font-bold';
                        badgeElem.innerText = 'READY TO ARM';
                    } else if (data.overall_status === 'DEGRADED') {
                        indElem.className = 'w-3.5 h-3.5 rounded-full bg-amber-400';
                        badgeElem.className = 'text-[10px] px-2 py-0.5 rounded bg-amber-950 text-amber-300 border border-amber-700 font-mono font-bold';
                        badgeElem.innerText = 'DEGRADED / DISARMED';
                    } else if (data.overall_status === 'BLOCKED') {
                        indElem.className = 'w-3.5 h-3.5 rounded-full bg-rose-500';
                        badgeElem.className = 'text-[10px] px-2 py-0.5 rounded bg-rose-950 text-rose-300 border border-rose-700 font-mono font-bold';
                        badgeElem.innerText = 'BLOCKED (KILL SWITCH)';
                    } else {
                        indElem.className = 'w-3.5 h-3.5 rounded-full bg-zinc-600';
                        badgeElem.className = 'text-[10px] px-2 py-0.5 rounded bg-zinc-900 text-zinc-400 border border-zinc-800 font-mono font-bold';
                        badgeElem.innerText = 'NOT READY';
                    }
                }

                // Update Grid Checks
                const dhanChk = data.checks?.find(c => c.category === 'DHAN' && c.code.includes('CONNECTED') || c.code.includes('AUTH') || c.code.includes('DISABLED'));
                if (dhanChk) {
                    const b = document.getElementById('chkDhanBadge');
                    const m = document.getElementById('chkDhanMsg');
                    if (b) {
                        b.innerText = dhanChk.passed ? 'PASSED' : 'FAILED';
                        b.className = dhanChk.passed ? 'text-[10px] text-emerald-400 font-bold' : 'text-[10px] text-rose-400 font-bold';
                    }
                    if (m) m.innerText = dhanChk.message;
                }

                const safeChk = data.checks?.find(c => c.category === 'SAFETY');
                if (safeChk) {
                    const b = document.getElementById('chkSafetyBadge');
                    const m = document.getElementById('chkSafetyMsg');
                    if (b) {
                        b.innerText = data.blocking_failures?.some(f => f.toLowerCase().includes('kill switch')) ? 'BLOCKED' : 'PASSED';
                        b.className = b.innerText === 'PASSED' ? 'text-[10px] text-emerald-400 font-bold' : 'text-[10px] text-rose-400 font-bold';
                    }
                    if (m) m.innerText = safeChk.message;
                }

                const mktChk = data.checks?.find(c => c.category === 'MARKET');
                if (mktChk) {
                    const b = document.getElementById('chkMarketBadge');
                    const m = document.getElementById('chkMarketMsg');
                    if (b) {
                        b.innerText = mktChk.passed ? 'OPEN' : 'CLOSED';
                        b.className = mktChk.passed ? 'text-[10px] text-emerald-400 font-bold' : 'text-[10px] text-amber-400 font-bold';
                    }
                    if (m) m.innerText = mktChk.message;
                }
            } catch (err) {
                console.error('Failed to run readiness audit', err);
            }
        }

        function openArmLiveModal() {
            const modal = document.getElementById('armLiveModal');
            if (modal) modal.classList.remove('hidden');
        }

        function closeArmLiveModal() {
            const modal = document.getElementById('armLiveModal');
            if (modal) modal.classList.add('hidden');
        }

        async function submitArmLiveTrading() {
            const checkbox = document.getElementById('armRiskAckCheckbox');
            if (!checkbox || !checkbox.checked) {
                alert('You must check the box to explicitly acknowledge real capital risk.');
                return;
            }

            try {
                const res = await fetch('/api/broker/live/arm', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ acknowledgement: true, duration_seconds: 300 })
                });

                const data = await res.json();
                closeArmLiveModal();

                if (res.ok && data.is_armed) {
                    startLiveArmCountdown(data.remaining_seconds || 300);
                    runLiveReadinessCheck();
                } else {
                    alert(`Failed to arm live trading: ${data.detail || 'Readiness precondition failed'}`);
                }
            } catch (err) {
                alert(`Arming failed: ${err.message}`);
            }
        }

        async function disarmLiveTradingFromUI() {
            if (liveArmCountdownInterval) clearInterval(liveArmCountdownInterval);
            try {
                await fetch('/api/broker/live/disarm', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ reason: 'Operator UI Disarm' })
                });
            } catch (e) {}

            const banner = document.getElementById('liveArmedActiveBanner');
            if (banner) banner.classList.add('hidden');
            const armBadge = document.getElementById('liveArmBadge');
            if (armBadge) {
                armBadge.innerText = 'DISARMED';
                armBadge.className = 'text-[10px] px-2 py-0.5 rounded bg-zinc-900 text-zinc-500 border border-zinc-800 font-mono font-bold';
            }
            const chkExec = document.getElementById('chkExecBadge');
            if (chkExec) {
                chkExec.innerText = 'DISARMED';
                chkExec.className = 'text-[10px] text-zinc-500';
            }
            runLiveReadinessCheck();
        }

        function startLiveArmCountdown(totalSeconds) {
            if (liveArmCountdownInterval) clearInterval(liveArmCountdownInterval);
            let sec = totalSeconds;

            const banner = document.getElementById('liveArmedActiveBanner');
            if (banner) banner.classList.remove('hidden');

            const armBadge = document.getElementById('liveArmBadge');
            if (armBadge) {
                armBadge.innerText = '⚡ ARMED';
                armBadge.className = 'text-[10px] px-2 py-0.5 rounded bg-rose-950 text-rose-300 border border-rose-700 font-mono font-bold animate-pulse';
            }

            const chkExec = document.getElementById('chkExecBadge');
            if (chkExec) {
                chkExec.innerText = 'ARMED';
                chkExec.className = 'text-[10px] text-rose-400 font-bold';
            }

            const timerElem = document.getElementById('liveArmedRemainingTimer');
            if (timerElem) timerElem.innerText = `Remaining: ${sec}s`;

            liveArmCountdownInterval = setInterval(() => {
                sec--;
                if (sec <= 0) {
                    clearInterval(liveArmCountdownInterval);
                    disarmLiveTradingFromUI();
                } else {
                    if (timerElem) timerElem.innerText = `Remaining: ${sec}s`;
                }
            }, 1000);
        }

        // ════════════════════ PHASE 29: STRATEGY GOVERNANCE LOGIC ════════════════════
        let activeChampionId = null;
        let lastSelectedChallengerId = null;

        async function fetchGovernanceData() {
            try {
                // Fetch governance summary status
                const res = await fetch('/api/governance/status');
                if (res.ok) {
                    const data = await res.json();
                    document.getElementById('govTotalStrategies').innerText = data.total_strategies_count || 0;
                    document.getElementById('govTotalDecisions').innerText = data.total_decisions_count || 0;
                    document.getElementById('govChallengersCount').innerText = (data.active_challengers || []).length;
                    
                    if (data.policy) {
                        document.getElementById('govPolicyMinTrades').innerText = data.policy.min_trade_count || 30;
                        document.getElementById('govPolicyRollbackDD').innerText = `${data.policy.rollback_max_drawdown_pct || 25.0}%`;
                    }

                    if (data.active_champion) {
                        activeChampionId = data.active_champion.strategy_id;
                        document.getElementById('govActiveChampionName').innerText = data.active_champion.name;
                        document.getElementById('govChampionVersion').innerText = `v${data.active_champion.version}`;
                        renderChampionCard(data.active_champion);
                    } else {
                        activeChampionId = null;
                        document.getElementById('govActiveChampionName').innerText = 'No Champion';
                        document.getElementById('govChampionVersion').innerText = 'None';
                        renderEmptyChampionCard();
                    }

                    renderChallengerTable(data.active_challengers || []);
                }

                // Fetch Decisions
                const decRes = await fetch('/api/governance/decisions?limit=20');
                if (decRes.ok) {
                    const decs = await decRes.json();
                    renderGovernanceDecisions(decs);
                }
            } catch (err) {
                console.error("Failed to fetch governance data:", err);
            }
        }

        function renderChampionCard(champ) {
            document.getElementById('govChampTitle').innerText = `${champ.name} (v${champ.version})`;
            document.getElementById('govChampFingerprint').innerText = `SHA-256: ${champ.config_fingerprint || 'N/A'}`;
            document.getElementById('govChampDefenses').innerText = champ.defenses_count || 0;
            document.getElementById('govChampPromotedAt').innerText = `Promoted: ${new Date(champ.promoted_at).toLocaleDateString()}`;

            const p = champ.performance || {};
            document.getElementById('govChampSharpe').innerText = p.sharpe_ratio != null ? p.sharpe_ratio.toFixed(2) : '--';
            document.getElementById('govChampSortino').innerText = p.sortino_ratio != null ? p.sortino_ratio.toFixed(2) : '--';
            document.getElementById('govChampMaxDD').innerText = `${(p.max_drawdown_pct || 0).toFixed(1)}%`;
            document.getElementById('govChampWinRate').innerText = `${(p.win_rate_pct || 0).toFixed(1)}%`;
            document.getElementById('govChampProfitFactor').innerText = p.profit_factor != null ? p.profit_factor.toFixed(2) : '--';
            document.getElementById('govChampTrades').innerText = p.total_trades || 0;
        }

        function renderEmptyChampionCard() {
            document.getElementById('govChampTitle').innerText = "No Active Champion";
            document.getElementById('govChampFingerprint').innerText = "Register and promote a validated challenger.";
            document.getElementById('govChampDefenses').innerText = "0";
            document.getElementById('govChampPromotedAt').innerText = "Promoted: --";
            document.getElementById('govChampSharpe').innerText = "--";
            document.getElementById('govChampSortino').innerText = "--";
            document.getElementById('govChampMaxDD').innerText = "--";
            document.getElementById('govChampWinRate').innerText = "--";
            document.getElementById('govChampProfitFactor').innerText = "--";
            document.getElementById('govChampTrades').innerText = "0";
        }

        function renderChallengerTable(challengers) {
            const tbody = document.getElementById('govChallengerTableBody');
            if (!tbody) return;

            if (!challengers || challengers.length === 0) {
                tbody.innerHTML = `<tr><td colspan="6" class="py-6 text-center text-zinc-600 font-sans">No active challengers registered.</td></tr>`;
                return;
            }

            tbody.innerHTML = challengers.map(c => {
                const p = c.performance || {};
                return `
                    <tr class="hover:bg-zinc-900/40">
                        <td class="py-2.5 px-2 font-bold text-white">${c.name} <span class="text-zinc-500 text-[10px]">v${c.version}</span></td>
                        <td class="py-2.5 px-2 text-emerald-400">${p.sharpe_ratio != null ? p.sharpe_ratio.toFixed(2) : '--'}</td>
                        <td class="py-2.5 px-2 text-rose-400">${(p.max_drawdown_pct || 0).toFixed(1)}%</td>
                        <td class="py-2.5 px-2 text-cyan-400">${(p.win_rate_pct || 0).toFixed(1)}%</td>
                        <td class="py-2.5 px-2 text-zinc-300">${p.total_trades || 0}</td>
                        <td class="py-2.5 px-2 flex items-center gap-1.5">
                            <button onclick="runGovernanceComparison('${c.strategy_id}')" class="px-2 py-1 rounded bg-cyan-950 text-cyan-300 border border-cyan-800 hover:bg-cyan-900 text-[10px]">
                                Compare
                            </button>
                            <button onclick="evaluateGovernanceGates('${c.strategy_id}')" class="px-2 py-1 rounded bg-amber-950 text-amber-300 border border-amber-800 hover:bg-amber-900 text-[10px]">
                                Gates
                            </button>
                        </td>
                    </tr>
                `;
            }).join('');
        }

        async function runGovernanceComparison(challengerId) {
            if (!activeChampionId) {
                alert("Cannot run comparison: No active Champion strategy found. Promote a champion first.");
                return;
            }
            lastSelectedChallengerId = challengerId;
            try {
                const res = await fetch('/api/governance/compare', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ champion_id: activeChampionId, challenger_id: challengerId }),
                });
                if (res.ok) {
                    const comp = await res.json();
                    renderComparisonGrid(comp);
                } else {
                    const err = await res.json();
                    alert(`Comparison failed: ${err.detail || 'Unknown error'}`);
                }
            } catch (err) {
                console.error("Comparison error:", err);
            }
        }

        function renderComparisonGrid(comp) {
            const badge = document.getElementById('govComparisonBadge');
            if (badge) {
                const winnerColor = comp.overall_winner === 'CHALLENGER' ? 'text-cyan-400 border-cyan-800 bg-cyan-950' : comp.overall_winner === 'CHAMPION' ? 'text-emerald-400 border-emerald-800 bg-emerald-950' : 'text-zinc-400 border-zinc-700 bg-zinc-900';
                badge.className = `text-xs font-mono font-bold px-3 py-1 rounded border ${winnerColor}`;
                badge.innerText = `Winner: ${comp.overall_winner} (Delta: ${comp.score_delta > 0 ? '+' : ''}${comp.score_delta} pts)`;
            }

            const grid = document.getElementById('govComparisonGrid');
            if (!grid) return;

            grid.innerHTML = (comp.dimensions || []).map(d => {
                const wColor = d.winner === 'CHALLENGER' ? 'text-cyan-400' : d.winner === 'CHAMPION' ? 'text-emerald-400' : 'text-zinc-400';
                return `
                    <div class="neon-border rounded-lg p-3 bg-zinc-950/50 space-y-2">
                        <div class="flex items-center justify-between text-[11px] font-mono">
                            <span class="font-bold text-white">${d.dimension_name}</span>
                            <span class="text-[10px] font-bold ${wColor}">[${d.winner}]</span>
                        </div>
                        <div class="text-[10px] text-zinc-500 truncate">${d.description}</div>
                        <div class="grid grid-cols-2 gap-2 text-xs font-mono pt-1 border-t border-zinc-800">
                            <div>
                                <div class="text-[9px] text-emerald-500">Champion: ${d.champion_value != null ? d.champion_value : '--'}</div>
                                <div class="text-xs font-bold text-emerald-400">${d.champion_score.toFixed(0)}/100</div>
                            </div>
                            <div class="text-right">
                                <div class="text-[9px] text-cyan-500">Challenger: ${d.challenger_value != null ? d.challenger_value : '--'}</div>
                                <div class="text-xs font-bold text-cyan-400">${d.challenger_score.toFixed(0)}/100</div>
                            </div>
                        </div>
                    </div>
                `;
            }).join('');
        }

        async function evaluateGovernanceGates(challengerId) {
            lastSelectedChallengerId = challengerId;
            try {
                const res = await fetch('/api/governance/gates/evaluate', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ challenger_id: challengerId, champion_id: activeChampionId }),
                });
                if (res.ok) {
                    const result = await res.json();
                    renderGateChecks(result, challengerId);
                } else {
                    const err = await res.json();
                    alert(`Gate evaluation failed: ${err.detail || 'Unknown error'}`);
                }
            } catch (err) {
                console.error("Gate evaluation error:", err);
            }
        }

        function renderGateChecks(res, challengerId) {
            const badge = document.getElementById('govGatesStatusBadge');
            if (badge) {
                badge.className = res.all_gates_passed ? 'text-[10px] font-mono px-2 py-0.5 rounded bg-emerald-950 text-emerald-300 border border-emerald-700' : 'text-[10px] font-mono px-2 py-0.5 rounded bg-rose-950 text-rose-300 border border-rose-700';
                badge.innerText = res.all_gates_passed ? 'ALL GATES PASSED ✓' : 'GATES BLOCKED ✗';
            }

            const list = document.getElementById('govGatesList');
            if (!list) return;

            let html = (res.gate_checks || []).map(g => {
                const icon = g.passed ? '<span class="text-emerald-400 font-bold">✓</span>' : '<span class="text-rose-400 font-bold">✗</span>';
                const statusColor = g.passed ? 'text-emerald-400' : 'text-rose-400';
                return `
                    <div class="flex items-center justify-between p-2.5 rounded bg-zinc-900/60 border border-zinc-800">
                        <div class="flex items-center gap-2">
                            ${icon}
                            <div>
                                <div class="text-xs font-bold text-white">${g.gate_name}</div>
                                <div class="text-[10px] text-zinc-400">${g.evidence}</div>
                            </div>
                        </div>
                        <span class="text-[10px] font-bold ${statusColor}">Req: ${g.required_value}</span>
                    </div>
                `;
            }).join('');

            if (res.all_gates_passed) {
                html += `
                    <button onclick="promoteChallengerFromUI('${challengerId}')" class="w-full py-2 mt-2 rounded bg-emerald-600 hover:bg-emerald-500 text-white font-bold text-xs transition shadow">
                        Promote to Champion 👑
                    </button>
                `;
            }

            list.innerHTML = html;
        }

        async function promoteChallengerFromUI(challengerId) {
            if (!confirm(`Are you sure you want to promote strategy ${challengerId} to active Champion? This will deprecate the existing champion.`)) {
                return;
            }
            try {
                const res = await fetch('/api/governance/promote', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        challenger_id: challengerId,
                        rationale: "Operator approved promotion after passing all statistical gates.",
                        operator: "OPERATOR_UI"
                    }),
                });
                if (res.ok) {
                    alert("Strategy successfully promoted to Champion!");
                    fetchGovernanceData();
                } else {
                    const err = await res.json();
                    alert(`Promotion failed: ${err.detail || 'Unknown error'}`);
                }
            } catch (err) {
                console.error("Promotion error:", err);
            }
        }

        async function triggerManualRollbackFromUI() {
            const reason = prompt("Enter rollback reason (e.g. Drawdown breach, abnormal volatility, manual override):", "Operator manual safety rollback");
            if (!reason) return;

            try {
                const res = await fetch('/api/governance/rollback', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        reason: "MANUAL",
                        details: reason,
                        operator: "OPERATOR_UI"
                    }),
                });
                if (res.ok) {
                    const data = await res.json();
                    alert(`Rollback executed successfully. Reinstated fallback: ${data.reinstated_fallback_id || 'None'}`);
                    fetchGovernanceData();
                } else {
                    const err = await res.json();
                    alert(`Rollback failed: ${err.detail || 'Unknown error'}`);
                }
            } catch (err) {
                console.error("Rollback error:", err);
            }
        }

        function renderGovernanceDecisions(decisions) {
            const tbody = document.getElementById('govDecisionsTableBody');
            if (!tbody) return;

            if (!decisions || decisions.length === 0) {
                tbody.innerHTML = `<tr><td colspan="7" class="py-6 text-center text-zinc-600 font-sans">No decision audit records found.</td></tr>`;
                return;
            }

            tbody.innerHTML = decisions.map(d => {
                const decColor = d.decision === 'PROMOTE' ? 'text-emerald-400' : d.decision === 'ROLLBACK' ? 'text-rose-400' : d.decision === 'RETIRE' ? 'text-zinc-400' : 'text-cyan-400';
                return `
                    <tr class="hover:bg-zinc-900/40">
                        <td class="py-2 px-2 text-zinc-500">${new Date(d.timestamp).toLocaleTimeString()}</td>
                        <td class="py-2 px-2 font-bold ${decColor}">[${d.decision}]</td>
                        <td class="py-2 px-2 text-white">${d.strategy_id}</td>
                        <td class="py-2 px-2 text-zinc-400">${d.previous_state} → ${d.new_state}</td>
                        <td class="py-2 px-2 text-zinc-300 truncate max-w-xs">${d.rationale}</td>
                        <td class="py-2 px-2 text-zinc-400">${d.operator}</td>
                        <td class="py-2 px-2 text-[10px] text-zinc-500 font-mono">${(d.decision_hash || '').slice(0, 10)}...</td>
                    </tr>
                `;
            }).join('');
        }

        function openRegisterStrategyModal() {
            const name = prompt("Enter Strategy Name:", "TrendMomentumAlpha");
            if (!name) return;
            const version = prompt("Enter Strategy Version:", "1.0.0");
            if (!version) return;
            const desc = prompt("Enter Strategy Description:", "Quantitative momentum strategy");

            fetch('/api/governance/strategies', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    name: name,
                    version: version,
                    description: desc || "",
                    author: "OPERATOR",
                    parameters: { default_param: true }
                })
            }).then(r => {
                if (r.ok) {
                    alert("Strategy successfully registered!");
                    fetchGovernanceData();
                } else {
                    r.json().then(e => alert(`Registration failed: ${e.detail}`));
                }
            }).catch(e => console.error("Registration error:", e));
        }
    
    