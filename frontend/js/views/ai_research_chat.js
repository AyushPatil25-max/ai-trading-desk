// Minimal AI Research Chat view
// Renders a UI for creating a chat session, listing messages, and sending user queries.
// Uses the backend /api/research-chat endpoints.

export function renderAIResearchChat(container) {
    const showError = (msg) => {
        container.innerHTML = `<div class="p-4 text-red-400 bg-red-900/30 rounded">${msg}</div>`;
    };

    // Helper to render loading spinner
    const renderSpinner = () => {
        container.innerHTML = `<div class="flex items-center justify-center h-64"><div class="animate-spin rounded-full h-8 w-8 border-b-2 border-cyan-400"></div></div>`;
    };

    // State
    let currentSessionId = null;

    // UI entry point – list sessions & create new
    const loadSessions = async () => {
        renderSpinner();
        try {
            const resp = await fetch('/api/research-chat/sessions');
            if (!resp.ok) throw new Error('Failed to load sessions');
            const sessions = await resp.json();
            const html = [];
            html.push('<div class="flex flex-col space-y-4">');
            html.push(`<div class="flex justify-between items-center"><h2 class="text-xl font-semibold">AI Research Chat</h2><button id="btnCreateSession" class="bg-cyan-900/30 hover:bg-cyan-800 text-cyan-400 px-3 py-1 rounded">New Session</button></div>`);
            if (sessions.length === 0) {
                html.push('<p class="text-gray-400">No chat sessions. Start a new one.</p>');
            } else {
                html.push('<ul class="space-y-2">');
                sessions.forEach(s => {
                    html.push(`<li class="p-2 bg-gray-800/30 rounded hover:bg-gray-700 cursor-pointer" data-id="${s.session_id}"><span class="font-medium">Session ${s.session_id.slice(0,6)}</span> <span class="text-sm text-gray-400">${new Date(s.created_at).toLocaleString()}</span></li>`);
                });
                html.push('</ul>');
            }
            html.push('</div>');
            container.innerHTML = html.join('');

            // Handlers
            document.getElementById('btnCreateSession').addEventListener('click', async () => {
                const res = await fetch('/api/research-chat/sessions', { method: 'POST' });
                if (!res.ok) return showError('Failed to create session');
                const newSess = await res.json();
                loadSessions();
            });
            container.querySelectorAll('li[data-id]').forEach(el => {
                el.addEventListener('click', () => {
                    const sid = el.getAttribute('data-id');
                    loadChat(sid);
                });
            });
        } catch (e) {
            showError(e.message);
        }
    };

    // Load a specific chat session UI
    const loadChat = async (sessionId) => {
        currentSessionId = sessionId;
        renderSpinner();
        try {
            const [sessionResp, msgsResp] = await Promise.all([
                fetch(`/api/research-chat/sessions/${sessionId}`),
                fetch(`/api/research-chat/sessions/${sessionId}/messages`)
            ]);
            if (!sessionResp.ok) throw new Error('Session not found');
            const session = await sessionResp.json();
            const messages = msgsResp.ok ? await msgsResp.json() : [];

            const html = [];
            html.push('<div class="flex flex-col h-full">');
            html.push(`<button id="btnBack" class="mb-2 text-cyan-400 hover:underline">← Back to sessions</button>`);
            html.push('<div id="msgList" class="flex-1 overflow-y-auto space-y-2 mb-2"></div>');
            html.push('<div class="flex space-x-2"><input id="userInput" type="text" placeholder="Ask a question..." class="flex-1 bg-gray-700 text-white p-1 rounded"/><button id="btnSend" class="bg-cyan-900/30 hover:bg-cyan-800 text-cyan-400 px-3 py-1 rounded">Send</button></div>');
            html.push('</div>');
            container.innerHTML = html.join('');

            const renderMessages = () => {
                const list = document.getElementById('msgList');
                list.innerHTML = '';
                messages.forEach(m => {
                    const roleClass = m.role === 'assistant' ? 'bg-gray-800/40' : 'bg-cyan-900/30';
                    let evid = m.evidence_refs && m.evidence_refs.length ? `<div class="text-xs text-gray-300 mt-1">Evidence: ${m.evidence_refs.map(id => `<a href="#" class="evidence-link" data-id="${id}">${id}</a>`).join(', ')}</div>` : '';
                    
                    if (m.quality_result) {
                        const statusColor = m.quality_result.overall_status === 'HIGH_QUALITY' ? 'text-green-400' :
                                            m.quality_result.overall_status === 'HAS_CONTRADICTIONS' ? 'text-red-400' : 'text-yellow-400';
                        evid += `<div class="text-xs mt-1 p-2 bg-gray-900/50 rounded border border-gray-700">
                                    <div class="font-medium ${statusColor}">Quality: ${m.quality_result.overall_status} (${m.quality_result.evidence_coverage_pct.toFixed(0)}% coverage)</div>`;
                        
                        if (m.quality_result.claims && m.quality_result.claims.length > 0) {
                            evid += `<ul class="mt-1 ml-4 list-disc space-y-1">`;
                            m.quality_result.claims.forEach(c => {
                                const cColor = c.validation_status === 'SUPPORTED' ? 'text-green-400' : 
                                               c.validation_status === 'CONTRADICTED' ? 'text-red-400' : 
                                               c.validation_status === 'PARTIALLY_SUPPORTED' ? 'text-yellow-400' : 'text-gray-400';
                                evid += `<li class="${cColor}">[${c.validation_status}] ${c.claim_text} <span class="text-gray-500">- ${c.explanation}</span></li>`;
                            });
                            evid += `</ul>`;
                        }
                        if (m.quality_result.uncertainty_warnings && m.quality_result.uncertainty_warnings.length > 0) {
                            m.quality_result.uncertainty_warnings.forEach(w => {
                                evid += `<div class="text-red-400 mt-1 italic">${w}</div>`;
                            });
                        }
                        evid += `</div>`;
                    }
                    
                    list.insertAdjacentHTML('beforeend', `<div class="p-2 rounded ${roleClass}"><strong>${m.role}:</strong> ${m.content}${evid}</div>`);
                });
                // Attach evidence link handler
                document.querySelectorAll('.evidence-link').forEach(a => {
                    a.addEventListener('click', (e) => {
                        e.preventDefault();
                        const id = a.getAttribute('data-id');
                        // Assuming a global function to open workspace item exists
                        if (window.openWorkspaceItem) window.openWorkspaceItem(id);
                    });
                });
            };
            renderMessages();

            document.getElementById('btnBack').addEventListener('click', loadSessions);
            document.getElementById('btnSend').addEventListener('click', async () => {
                const input = document.getElementById('userInput');
                const content = input.value.trim();
                if (!content) return;
                input.value = '';
                // optimistic UI
                messages.push({ role: 'user', content, message_id: 'tmp-' + Date.now(), timestamp: new Date().toISOString(), evidence_refs: null });
                renderMessages();
                try {
                    const res = await fetch(`/api/research-chat/sessions/${sessionId}/messages`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ content })
                    });
                    if (!res.ok) throw new Error('LLM call failed');
                    const chatResp = await res.json();
                    // Replace temporary user message with server version (if needed) and add assistant reply
                    messages.pop(); // remove temp user (already added)
                    messages.push({ role: 'user', content, message_id: chatResp.message.message_id, timestamp: chatResp.message.timestamp, evidence_refs: null });
                    messages.push({ 
                        role: 'assistant', 
                        content: chatResp.message.content, 
                        message_id: chatResp.message.message_id, 
                        timestamp: chatResp.message.timestamp, 
                        evidence_refs: chatResp.evidence_refs,
                        quality_result: chatResp.quality_result
                    });
                    renderMessages();
                } catch (e) {
                    showError(e.message);
                }
            });
        } catch (e) {
            showError(e.message);
        }
    };

    // Start by listing sessions
    loadSessions();
}
