// Minimal Research Workspace view
// This module renders a simple UI for listing, creating, and viewing research workspaces.
// It uses the existing fetch API (relative paths) to communicate with the backend.

export function renderResearchWorkspace(container) {
    // Helper to display error messages
    const showError = (msg) => {
        container.innerHTML = `<div class="p-4 text-red-400 bg-red-900/30 rounded">${msg}</div>`;
    };

    // Render loading spinner
    container.innerHTML = `<div class="flex items-center justify-center h-64"><div class="animate-spin rounded-full h-8 w-8 border-b-2 border-cyan-400"></div></div>`;

    // Fetch workspace list
    fetch('/api/research-workspace/workspaces')
        .then(res => {
            if (!res.ok) throw new Error('Failed to fetch workspaces');
            return res.json();
        })
        .then(workspaces => {
            // Main UI layout
            const html = [];
            html.push('<div class="flex flex-col space-y-4">');
            // Header with Create button
            html.push(`<div class="flex justify-between items-center"><h2 class="text-xl font-semibold">Research Workspaces</h2><button id="btnCreateWorkspace" class="bg-cyan-900/30 hover:bg-cyan-800 text-cyan-400 px-3 py-1 rounded">Create</button></div>`);
            // List
            if (workspaces.length === 0) {
                html.push('<p class="text-gray-400">No workspaces found.</p>');
            } else {
                html.push('<ul class="space-y-2">');
                workspaces.forEach(ws => {
                    html.push(`
<li class="p-2 bg-gray-800/50 rounded hover:bg-gray-700 cursor-pointer" data-id="${ws.workspace_id}">
  <div class="flex justify-between items-center">
    <span class="font-medium">${ws.name}</span>
    <span class="text-sm text-gray-400">${ws.status}</span>
  </div>
  <p class="text-sm text-gray-400">${ws.description || ''}</p>
</li>`);
                });
                html.push('</ul>');
            }
            html.push('</div>');
            container.innerHTML = html.join('');

            // Attach handlers
            const btnCreate = document.getElementById('btnCreateWorkspace');
            if (btnCreate) {
                btnCreate.addEventListener('click', () => {
                    const name = prompt('Workspace name:');
                    if (!name) return;
                    const description = prompt('Description (optional)');
                    fetch('/api/research-workspace/workspaces', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ name, description })
                    })
                        .then(r => {
                            if (!r.ok) throw new Error('Create failed');
                            return r.json();
                        })
                        .then(() => renderResearchWorkspace(container))
                        .catch(err => showError(err.message));
                });
            }
            // Click on a workspace to view details
            container.querySelectorAll('li[data-id]').forEach(el => {
                el.addEventListener('click', () => {
                    const wsId = el.getAttribute('data-id');
                    renderWorkspaceDetail(wsId, container);
                });
            });
        })
        .catch(err => showError(err.message));
}

// Detail view for a specific workspace (items + notes)
function renderWorkspaceDetail(workspaceId, container) {
    const backBtn = `<button id="btnBack" class="mb-2 text-cyan-400 hover:underline">← Back to list</button>`;
    container.innerHTML = backBtn + `<div class="flex items-center justify-center h-48"><div class="animate-spin rounded-full h-8 w-8 border-b-2 border-cyan-400"></div></div>`;
    document.getElementById('btnBack').addEventListener('click', () => renderResearchWorkspace(container));

    // Fetch workspace info
    const wsPromise = fetch(`/api/research-workspace/workspaces/${workspaceId}`).then(r => r.ok ? r.json() : Promise.reject('Workspace not found'));
    const itemsPromise = fetch(`/api/research-workspace/workspaces/${workspaceId}/items`).then(r => r.ok ? r.json() : []);
    const notesPromise = fetch(`/api/research-workspace/workspaces/${workspaceId}/notes`).then(r => r.ok ? r.json() : []);

    Promise.all([wsPromise, itemsPromise, notesPromise])
        .then(([ws, items, notes]) => {
            const html = [];
            html.push('<div class="space-y-4">');
            html.push(`<h3 class="text-lg font-semibold">${ws.name} <span class="text-sm text-gray-400">(${ws.status})</span></h3>`);
            if (ws.description) html.push(`<p class="text-gray-300">${ws.description}</p>`);
            // Items
            html.push('<h4 class="font-medium mt-4">Items</h4>');
            if (items.length === 0) {
                html.push('<p class="text-gray-400">No items.</p>');
            } else {
                html.push('<ul class="space-y-2">');
                items.forEach(it => {
                    html.push(`<li class="bg-gray-800/30 p-2 rounded"><strong>${it.title}</strong> <span class="text-sm text-gray-400">[${it.item_type}]</span>` +
                        (it.symbol ? ` – Symbol: <code class="text-cyan-300">${it.symbol}</code>` : '') +
                        `</li>`);
                });
                html.push('</ul>');
            }
            // Notes
            html.push('<h4 class="font-medium mt-4">Notes</h4>');
            if (notes.length === 0) {
                html.push('<p class="text-gray-400">No notes.</p>');
            } else {
                html.push('<ul class="space-y-2">');
                notes.forEach(n => {
                    html.push(`<li class="bg-gray-800/30 p-2 rounded"><strong>${n.title}</strong><p class="text-sm text-gray-300">${n.content}</p></li>`);
                });
                html.push('</ul>');
            }
            // Simple note creation form
            html.push(`<div class="mt-4"><h5 class="font-medium">Add Note</h5>
<input id="noteTitle" type="text" placeholder="Title" class="w-full bg-gray-700 text-white p-1 rounded mb-1"/>
<textarea id="noteContent" placeholder="Content" class="w-full bg-gray-700 text-white p-1 rounded mb-1"></textarea>
<button id="btnAddNote" class="bg-cyan-900/30 hover:bg-cyan-800 text-cyan-400 px-3 py-1 rounded">Create Note</button></div>`);
            html.push('</div>');
            container.innerHTML = backBtn + html.join('');
            // Note creation handler
            document.getElementById('btnAddNote').addEventListener('click', () => {
                const title = document.getElementById('noteTitle').value.trim();
                const content = document.getElementById('noteContent').value.trim();
                if (!title || !content) return alert('Title and content required');
                fetch(`/api/research-workspace/workspaces/${workspaceId}/notes`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ title, content })
                })
                    .then(r => r.ok ? r.json() : Promise.reject('Failed to create note'))
                    .then(() => renderWorkspaceDetail(workspaceId, container))
                    .catch(err => alert(err));
            });
        })
        .catch(err => {
            container.innerHTML = `<div class="p-4 text-red-400 bg-red-900/30 rounded">${err}</div>`;
        });
}
