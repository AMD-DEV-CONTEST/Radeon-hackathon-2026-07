// RepositoryAnalysisAgent frontend: chat interface with SSE streaming, tool call visualization,
// repo path switching, indexing, and stop generation.

const API = '/api';
let currentSessionId = null;
let isStreaming = false;
let currentAbortController = null;
let currentRepoPath = null;

// ── DOM elements ──
const messagesEl = document.getElementById('messages');
const inputEl = document.getElementById('chatInput');
const btnSend = document.getElementById('btnSend');
const btnStop = document.getElementById('btnStop');
const btnNewChat = document.getElementById('btnNewChat');
const healthDot = document.getElementById('healthDot');
const healthText = document.getElementById('healthText');
const modelName = document.getElementById('modelName');
const repoPathText = document.getElementById('repoPathText');
const indexStatus = document.getElementById('indexStatus');
const fileTree = document.getElementById('fileTree');
const sessionsEl = document.getElementById('sessions');
const repoPathInput = document.getElementById('repoPathInput');
const btnIndex = document.getElementById('btnIndex');
const btnReindex = document.getElementById('btnReindex');

// ── Input handling ──
inputEl.addEventListener('input', () => {
    inputEl.style.height = 'auto';
    inputEl.style.height = inputEl.scrollHeight + 'px';
});

inputEl.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
});

btnSend.addEventListener('click', sendMessage);
btnStop.addEventListener('click', stopGeneration);
btnNewChat.addEventListener('click', () => {
    currentSessionId = null;
    messagesEl.innerHTML = renderWelcome();
    loadSessions();
});

// ── Repo path + indexing ──
btnIndex.addEventListener('click', () => triggerIndex(false));
btnReindex.addEventListener('click', () => triggerIndex(true));

async function triggerIndex(force) {
    let path = repoPathInput.value.trim();
    if (!path) {
        if (currentRepoPath) {
            path = currentRepoPath;
        } else {
            flashStatus('Enter a repo path first');
            return;
        }
    }

    btnIndex.disabled = true;
    btnReindex.disabled = true;
    indexStatus.textContent = force ? 'Force re-indexing...' : 'Indexing...';
    healthDot.className = 'status-dot warn';

    try {
        const resp = await fetch(`${API}/index`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ repo_path: path, force }),
        });
        const data = await resp.json();
        if (data.status === 'started') {
            currentRepoPath = path;
            repoPathText.textContent = path;
            flashStatus('Indexing started');
            pollIndexStatus();
        } else if (data.status === 'already_indexing') {
            flashStatus('Already indexing...');
            pollIndexStatus();
        }
    } catch (err) {
        flashStatus('Index error: ' + err.message);
    }

    btnIndex.disabled = false;
    btnReindex.disabled = false;
}

function pollIndexStatus() {
    const timer = setInterval(async () => {
        try {
            const resp = await fetch(`${API}/index/status`);
            const data = await resp.json();
            if (data.is_indexing) {
                indexStatus.textContent = `Indexing... (${data.chunk_count} chunks)`;
            } else {
                clearInterval(timer);
                if (data.chunk_count > 0) {
                    indexStatus.textContent = `${data.chunk_count} chunks indexed`;
                    healthDot.className = 'status-dot ok';
                    loadFileTree();
                } else {
                    indexStatus.textContent = 'Not indexed';
                }
            }
        } catch {
            clearInterval(timer);
        }
    }, 2000);
}

function flashStatus(msg) {
    const old = indexStatus.textContent;
    indexStatus.textContent = msg;
    setTimeout(() => { indexStatus.textContent = old; }, 3000);
}

// ── Stop generation ──
function stopGeneration() {
    if (currentAbortController) {
        currentAbortController.abort();
        currentAbortController = null;
    }
}

function sendMessage() {
    const text = inputEl.value.trim();
    if (!text || isStreaming) return;

    const welcome = messagesEl.querySelector('.welcome');
    if (welcome) welcome.remove();

    appendUserMessage(text);
    inputEl.value = '';
    inputEl.style.height = 'auto';
    streamChat(text);
}

// ── SSE chat streaming ──
async function streamChat(message) {
    isStreaming = true;
    btnSend.style.display = 'none';
    btnStop.style.display = 'flex';
    inputEl.disabled = true;

    const msgDiv = document.createElement('div');
    msgDiv.className = 'msg msg-assistant';
    const roleEl = document.createElement('div');
    roleEl.className = 'msg-role';
    roleEl.textContent = 'RepositoryAnalysisAgent';
    const contentEl = document.createElement('div');
    contentEl.className = 'msg-content';
    msgDiv.appendChild(roleEl);
    msgDiv.appendChild(contentEl);
    messagesEl.appendChild(msgDiv);

    const typing = document.createElement('div');
    typing.className = 'typing-indicator';
    typing.innerHTML = '<span></span><span></span><span></span>';
    contentEl.appendChild(typing);

    currentAbortController = new AbortController();
    let hasContent = false;

    try {
        const resp = await fetch(`${API}/chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message,
                session_id: currentSessionId,
                repo_path: currentRepoPath,
            }),
            signal: currentAbortController.signal,
        });

        const sessionId = resp.headers.get('X-Session-Id');
        if (sessionId) currentSessionId = sessionId;

        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let finalText = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });

            const lines = buffer.split('\n');
            buffer = lines.pop();

            for (const line of lines) {
                if (!line.startsWith('data: ')) continue;
                const data = line.slice(6).trim();
                if (!data) continue;

                let event;
                try { event = JSON.parse(data); } catch { continue; }

                if (typing.parentNode && (event.type === 'text' || event.type === 'text_delta'
                    || event.type === 'tool_call' || event.type === 'thinking'
                    || event.type === 'tool_result' || event.type === 'progress')) {
                    typing.remove();
                    hasContent = true;
                }

                handleEvent(event, contentEl);
                if (event.type === 'done' || event.type === 'text') {
                    if (event.content) finalText += event.content;
                }
            }
        }

        if (!hasContent && !finalText) {
            contentEl.innerHTML = '<em>No response received.</em>';
        }

        contentEl.querySelectorAll('pre code').forEach(block => {
            if (window.hljs) hljs.highlightElement(block);
        });

    } catch (err) {
        typing.remove();
        if (err.name === 'AbortError') {
            const stopMsg = document.createElement('div');
            stopMsg.className = 'stopped-msg';
            stopMsg.textContent = '— stopped —';
            contentEl.appendChild(stopMsg);
        } else {
            contentEl.innerHTML = `<span style="color: var(--red);">Error: ${err.message}</span>`;
        }
    }

    isStreaming = false;
    btnSend.style.display = 'flex';
    btnStop.style.display = 'none';
    inputEl.disabled = false;
    inputEl.focus();
    currentAbortController = null;
    scrollToBottom();
    loadSessions();
}

function handleEvent(event, container) {
    switch (event.type) {
        case 'text_delta': {
            // Accumulate streaming tokens into the current text element
            let textEl = container.querySelector('.streaming-text');
            if (!textEl) {
                textEl = document.createElement('div');
                textEl.className = 'streaming-text';
                container.appendChild(textEl);
            }
            textEl.textContent += event.content;
            scrollToBottom();
            break;
        }
        case 'progress': {
            // Show a brief progress indicator
            let progEl = container.querySelector('.progress-msg');
            if (!progEl) {
                progEl = document.createElement('div');
                progEl.className = 'progress-msg';
                container.appendChild(progEl);
            }
            progEl.textContent = '\u23F3 ' + event.content;
            scrollToBottom();
            break;
        }
        case 'thinking': {
            // Remove streaming text and progress (they were replaced by thinking)
            const streamEl = container.querySelector('.streaming-text');
            if (streamEl) streamEl.remove();
            const progEl = container.querySelector('.progress-msg');
            if (progEl) progEl.remove();
            const block = document.createElement('div');
            block.className = 'thinking-block';
            const header = document.createElement('div');
            header.className = 'thinking-header';
            header.innerHTML = `<span class="thinking-icon">&#128161;</span> Reasoning (step ${event.iteration || ''})`;
            const content = document.createElement('div');
            content.className = 'thinking-content';
            content.textContent = event.content;
            content.style.display = 'none';
            header.addEventListener('click', () => {
                content.style.display = content.style.display === 'none' ? 'block' : 'none';
            });
            block.appendChild(header);
            block.appendChild(content);
            container.appendChild(block);
            break;
        }
        case 'tool_call': {
            const block = document.createElement('div');
            block.className = 'tool-call-block';
            const nameEl = document.createElement('div');
            nameEl.className = 'tool-call-name';
            nameEl.textContent = '\u25B8 ' + event.content;
            if (event.arguments && Object.keys(event.arguments).length) {
                const argsEl = document.createElement('div');
                argsEl.className = 'tool-call-args';
                argsEl.textContent = JSON.stringify(event.arguments);
                block.appendChild(nameEl);
                block.appendChild(argsEl);
            } else {
                block.appendChild(nameEl);
            }
            container.appendChild(block);
            break;
        }
        case 'tool_result': {
            const lastTool = container.querySelector('.tool-call-block:last-child');
            if (lastTool) {
                const result = document.createElement('div');
                result.className = 'tool-result';
                result.textContent = event.content;
                result.style.display = 'none';
                lastTool.addEventListener('click', () => {
                    result.style.display = result.style.display === 'none' ? 'block' : 'none';
                });
                lastTool.style.cursor = 'pointer';
                lastTool.appendChild(result);
            }
            break;
        }
        case 'text': {
            // Finalize: convert streaming text to rendered markdown
            let streamEl = container.querySelector('.streaming-text');
            const progEl = container.querySelector('.progress-msg');
            if (progEl) progEl.remove();
            if (streamEl) {
                // Streaming text was the answer
                if (event.content && event.content.trim()) {
                    streamEl.innerHTML = renderMarkdown(event.content);
                }
            } else {
                // No streaming happened, add normally
                const textEl = document.createElement('div');
                textEl.innerHTML = renderMarkdown(event.content);
                container.appendChild(textEl);
            }
            break;
        }
        case 'done':
            break;
        case 'error': {
            const errEl = document.createElement('div');
            errEl.style.color = 'var(--red)';
            errEl.textContent = event.content;
            container.appendChild(errEl);
            break;
        }
    }
    scrollToBottom();
}

// ── Rendering helpers ──
function appendUserMessage(text) {
    const msg = document.createElement('div');
    msg.className = 'msg msg-user';
    const content = document.createElement('div');
    content.className = 'msg-content';
    content.textContent = text;
    msg.appendChild(content);
    messagesEl.appendChild(msg);
    scrollToBottom();
}

function renderWelcome() {
    return `<div class="welcome">
        <div class="welcome-icon">&#128269;</div>
        <h2>RepositoryAnalysisAgent</h2>
        <p>Privacy-first local code intelligence. Ask anything about this codebase.</p>
    </div>`;
}

function renderMarkdown(text) {
    let html = text;
    html = html.replace(/```(\w+)?\n([\s\S]*?)```/g, (m, lang, code) => {
        const langClass = lang ? ` class="language-${lang}"` : '';
        return `<pre><code${langClass}>${escapeHtml(code.trim())}</code></pre>`;
    });
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
    html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    html = html.split('\n\n').map(p => `<p>${p.replace(/\n/g, '<br>')}</p>`).join('');
    return html;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function scrollToBottom() {
    messagesEl.scrollTop = messagesEl.scrollHeight;
}

// ── Health check ──
async function checkHealth() {
    try {
        const resp = await fetch(`${API}/health`);
        const data = await resp.json();

        if (data.llm_available) {
            healthDot.className = 'status-dot ok';
            healthText.textContent = 'LLM Online';
        } else {
            healthDot.className = 'status-dot error';
            healthText.textContent = 'LLM Offline';
        }

        if (data.gpu_name) {
            modelName.textContent = `${data.llm_model} | ${data.gpu_name}`;
        } else {
            modelName.textContent = data.llm_model || '';
        }

        if (!data.indexing && data.chunk_count > 0) {
            indexStatus.textContent = `${data.chunk_count} chunks indexed`;
        } else if (data.indexing) {
            healthDot.className = 'status-dot warn';
            healthText.textContent = 'Indexing...';
        }

        // Auto-poll if indexing
        if (data.indexing) pollIndexStatus();
    } catch {
        healthDot.className = 'status-dot error';
        healthText.textContent = 'Server Offline';
    }
}

// ── File browser ──
async function loadFileTree(path = '.') {
    try {
        const resp = await fetch(`${API}/workspace/tree?path=${encodeURIComponent(path)}`);
        const data = await resp.json();
        fileTree.innerHTML = '';

        // Show parent dir link if not at root
        if (path !== '.') {
            const parent = path.includes('/') ? path.rsplit('/', 1)[0] : '.';
            const upEl = document.createElement('div');
            upEl.className = 'file-entry';
            upEl.innerHTML = '\u2191 ..';
            upEl.addEventListener('click', () => loadFileTree(parent === path ? '.' : parent));
            fileTree.appendChild(upEl);
        }

        data.entries.forEach(entry => {
            const el = document.createElement('div');
            el.className = 'file-entry' + (entry.is_dir ? ' dir' : '');
            el.textContent = (entry.is_dir ? '\u{1F4C1} ' : '\u{1F4C4} ') + entry.name;
            if (entry.is_dir) {
                el.addEventListener('click', () => {
                    const newPath = path === '.' ? entry.name : `${path}/${entry.name}`;
                    loadFileTree(newPath);
                });
            }
            fileTree.appendChild(el);
        });

        if (data.entries.length === 0) {
            fileTree.innerHTML = '<div class="file-entry" style="opacity:0.5">Empty</div>';
        }
    } catch {
        fileTree.innerHTML = '<div class="file-entry" style="opacity:0.5">Unavailable</div>';
    }
}

// ── Sessions ──
async function loadSessions() {
    try {
        const resp = await fetch(`${API}/sessions`);
        const data = await resp.json();
        sessionsEl.innerHTML = '';

        data.sessions.forEach(s => {
            const el = document.createElement('div');
            el.className = 'session-item';
            if (s.session_id === currentSessionId) el.classList.add('active');
            el.textContent = s.title || s.session_id;
            el.addEventListener('click', () => loadSession(s.session_id));
            sessionsEl.appendChild(el);
        });

        if (data.sessions.length === 0) {
            sessionsEl.innerHTML = '<div class="file-entry" style="opacity:0.5">No sessions</div>';
        }
    } catch {}
}

async function loadSession(sessionId) {
    currentSessionId = sessionId;
    try {
        const resp = await fetch(`${API}/sessions/${sessionId}`);
        const data = await resp.json();
        messagesEl.innerHTML = '';

        data.messages.forEach(msg => {
            if (msg.role === 'user') {
                appendUserMessage(msg.content);
            } else if (msg.role === 'assistant') {
                const div = document.createElement('div');
                div.className = 'msg msg-assistant';
                const role = document.createElement('div');
                role.className = 'msg-role';
                role.textContent = 'RepositoryAnalysisAgent';
                const content = document.createElement('div');
                content.className = 'msg-content';
                content.innerHTML = renderMarkdown(msg.content);
                div.appendChild(role);
                div.appendChild(content);
                messagesEl.appendChild(div);
            }
        });

        messagesEl.querySelectorAll('pre code').forEach(block => {
            if (window.hljs) hljs.highlightElement(block);
        });

        loadSessions();
        scrollToBottom();
    } catch {}
}

// ── Init ──
checkHealth();
loadSessions();
setInterval(checkHealth, 15000);
