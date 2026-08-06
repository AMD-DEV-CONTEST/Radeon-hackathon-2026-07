/* ============================================================
 * app.js — Smart Claim Review Assistant frontend logic
 *
 * Core features:
 *   1) Real streaming SSE: fetch + ReadableStream + TextDecoder
 *      Each SSE event triggers onEvent immediately, no setTimeout typewriter
 *   2) Unbroken reasoning chain: reasoning / content chunks appended to DOM immediately
 *   3) Backend done event returns a structured dict (not HTML); frontend
 *      implements renderSingleCard / renderBatchCard to render cards itself
 *   4) Batch card: each successful non-duplicate invoice row must have a drug
 *      sub-table below it (drug / amount / category / medical reimbursable /
 *      commercial reimbursable / reason)
 * ============================================================ */

'use strict';

/* ============================================================
 * Auth token utilities (login module)
 * Token stored in localStorage; apiFetch auto-attaches Authorization
 * header and triggers login overlay on 401.
 * ============================================================ */
const TOKEN_KEY = 'claim_auth_token';
function getToken() { try { return localStorage.getItem(TOKEN_KEY) || ''; } catch (_) { return ''; } }
function setToken(t) { try { localStorage.setItem(TOKEN_KEY, t); } catch (_) {} }
function clearToken() { try { localStorage.removeItem(TOKEN_KEY); } catch (_) {} }
function authHeader() { const t = getToken(); return t ? { 'Authorization': 'Bearer ' + t } : {}; }

function showLoginOverlay() {
  const ov = document.getElementById('login-overlay');
  if (ov) ov.style.display = 'flex';
}
function hideLoginOverlay() {
  const ov = document.getElementById('login-overlay');
  if (ov) ov.style.display = 'none';
}

/** Unified fetch wrapper: auto-attach Authorization header; on 401 clear
 *  token and show login overlay. */
async function apiFetch(url, opts) {
  opts = opts || {};
  opts.headers = Object.assign({}, opts.headers || {}, authHeader());
  const resp = await fetch(url, opts);
  if (resp.status === 401) {
    clearToken();
    showLoginOverlay();
    throw new Error('401 Unauthorized');
  }
  return resp;
}

/** Login: POST /api/login with username/password, store token on success */
async function doLogin() {
  const user = document.getElementById('login-user').value.trim();
  const pass = document.getElementById('login-pass').value;
  const errEl = document.getElementById('login-error');
  if (errEl) errEl.classList.add('hidden');
  try {
    const resp = await fetch('/api/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: user, password: pass }),
    });
    if (!resp.ok) {
      const detail = resp.status === 401 ? 'Invalid username or password' : ('HTTP ' + resp.status);
      if (errEl) { errEl.textContent = detail; errEl.classList.remove('hidden'); }
      return;
    }
    const data = await resp.json();
    setToken(data.token || '');
    hideLoginOverlay();
    document.getElementById('login-pass').value = '';
  } catch (e) {
    if (errEl) { errEl.textContent = 'Network error: ' + (e.message || e); errEl.classList.remove('hidden'); }
  }
}

/* ============================================================
 * Global state
 * ============================================================ */
let sessionId = '';
let selectedSingleFile = null;     // Single tab: currently selected image File object
let selectedBatchFiles = [];        // Batch tab: currently selected file list
let isStreamingSingle = false;      // Single tab: whether streaming is in progress
let isStreamingBatch = false;       // Batch tab: whether streaming is in progress
let hasBatchResult = false;         // Batch tab: whether an exportable batch result exists

// Conclusion → style mapping. Keys match backend English values; CONC_LABEL
// provides display text.
const CONCLUSION_STYLE = {
  'Full Pass': { icon: '✅', cls: 'conc-pass' },
  'Partial Pass': { icon: '⚠️', cls: 'conc-partial' },
  'Rejected':     { icon: '❌', cls: 'conc-reject' },
};
const CONC_LABEL = {
  'Full Pass': 'Fully Approved',
  'Partial Pass': 'Partially Approved',
  'Rejected': 'Rejected',
};
const BATCH_CONCLUSION_STYLE = {
  'All Passed': { icon: '✅', cls: 'conc-pass' },
  'Partial Pass': { icon: '⚠️', cls: 'conc-partial' },
  'All Rejected': { icon: '❌', cls: 'conc-reject' },
};
const BATCH_CONC_LABEL = {
  'All Passed': 'All Approved',
  'Partial Pass': 'Partially Approved',
  'All Rejected': 'All Rejected',
};

/** Map a backend conclusion to display text */
function labelConc(v) { return CONC_LABEL[v] || v || '-'; }
/** Map a backend batch conclusion to display text */
function labelBatchConc(v) { return BATCH_CONC_LABEL[v] || v || '-'; }

/* ============================================================
 * 8.1 Utility functions
 * ============================================================ */

/** Get or generate a session_id (12-char hex), persisted to localStorage */
function getSessionId() {
  try {
    let id = localStorage.getItem('claim_session_id');
    if (!id) {
      id = genSessionId();
      localStorage.setItem('claim_session_id', id);
    }
    return id;
  } catch (_) {
    // Fallback to in-memory if localStorage is unavailable
    return sessionId || genSessionId();
  }
}

function genSessionId() {
  try {
    if (crypto && crypto.randomUUID) {
      return crypto.randomUUID().replace(/-/g, '').slice(0, 12);
    }
  } catch (_) {}
  // Fallback: use Math.random
  let s = '';
  for (let i = 0; i < 12; i++) {
    s += Math.floor(Math.random() * 16).toString(16);
  }
  return s;
}

/** Start a new session: generate a new session_id, clear both tabs' messages
 *  and right-side cards */
function newSession() {
  sessionId = genSessionId();
  try { localStorage.setItem('claim_session_id', sessionId); } catch (_) {}
  updateSessionIdDisplay();

  // Clear single tab
  clearChat('chat-messages-single', 'right-card-single',
    'Hello, I\'m the <b>Smart Claim Review Assistant</b>. Upload an invoice image and click Send to start review; or type a follow-up question…');
  // Clear batch tab
  clearChat('chat-messages-batch', 'right-card-batch',
    'Hello, this is <b>Batch Invoice Review</b> mode. Select a folder containing multiple invoice images, then click "Start Batch Review".');

  hasBatchResult = false;
  const exportBtn = document.getElementById('export-csv');
  if (exportBtn) exportBtn.disabled = true;
}

function clearChat(msgBoxId, cardId, welcomeText) {
  const box = document.getElementById(msgBoxId);
  if (box) {
    box.innerHTML = '';
    const welcome = document.createElement('div');
    welcome.className = 'bubble bubble-assistant';
    welcome.innerHTML = `<div class="bubble-meta">Smart Assistant</div>` +
      `<div class="bubble-body">${welcomeText}</div>`;
    box.appendChild(welcome);
  }
  const card = document.getElementById(cardId);
  if (card) {
    card.innerHTML = `<div class="text-xs text-slate-400 text-center py-8">` +
      `The ${cardId.includes('batch') ? 'summary card' : 'claim decision'} will appear here after review completes</div>`;
  }
}

/** HTML-escape user input */
function escapeHtml(str) {
  if (str == null) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/**
 * Backend already returns HTML strings (from format_decision_card /
 * format_batch_card), so innerHTML is sufficient; but user-input messages
 * need escapeHtml. This supports both "already HTML" and "plain string".
 */
function renderMarkdownSafe(html) {
  if (html == null) return '';
  return String(html);
}

/** Lightweight markdown rendering (for follow-up content, escaped then formatted) */
function renderLiteMarkdown(text) {
  let s = escapeHtml(text);
  // Code blocks
  s = s.replace(/```([\s\S]*?)```/g, (_, c) => `<pre class="bg-slate-50 p-2 rounded text-xs overflow-x-auto my-1">${c}</pre>`);
  // Inline code
  s = s.replace(/`([^`\n]+)`/g, '<code>$1</code>');
  // Bold
  s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  // Headings
  s = s.replace(/^###\s+(.+)$/gm, '<h3>$1</h3>');
  s = s.replace(/^##\s+(.+)$/gm, '<h3>$1</h3>');
  // Line breaks
  s = s.replace(/\n/g, '<br/>');
  return s;
}

/** Number formatting: 2 decimal places + thousands separator */
function fmtNum(v) {
  if (v == null || v === '') return '-';
  const n = Number(v);
  if (Number.isNaN(n)) return String(v);
  // Integers display as integers, floats keep 2 decimals
  if (Number.isInteger(n)) return n.toLocaleString('en-US');
  return n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/* ============================================================
 * 8.2 streamSSE core utility (critical!)
 * Real streaming: fetch + ReadableStream + TextDecoder
 * Each SSE event triggers onEvent immediately, no batching no delay
 * ============================================================ */
async function streamSSE(response, onEvent) {
  if (!response.ok || !response.body) {
    throw new Error(`HTTP ${response.status} ${response.statusText}`);
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buffer = '';
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    // SSE events are separated by \n\n
    let idx;
    while ((idx = buffer.indexOf('\n\n')) >= 0) {
      const rawEvent = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      // Parse data: lines (an event may contain multiple data: lines,
      // joined by \n per SSE spec)
      const lines = rawEvent.split('\n');
      const dataParts = [];
      for (const line of lines) {
        if (line.startsWith('data:')) {
          dataParts.push(line.slice(5).replace(/^\s/, ''));
        }
        // Ignore event:/id:/retry:/comment lines; backend only uses data:
      }
      const dataStr = dataParts.join('\n').trim();
      if (!dataStr) continue;
      try {
        const obj = JSON.parse(dataStr);
        onEvent(obj);
      } catch (e) {
        // Non-JSON payload (e.g. keepalive comment), ignore
      }
    }
  }
}

/* ============================================================
 * 8.3 renderStreamingBubble(reasoning, content)
 * Render streaming follow-up bubble content
 * ============================================================ */
function renderStreamingBubble(reasoning, content, opts) {
  opts = opts || {};
  const showCursor = opts.showCursor !== false;
  const parts = [];

  if (!reasoning && !content) {
    return `<div class="text-slate-500">🤔 Thinking…${showCursor ? '<span class="cursor"></span>' : ''}</div>`;
  }

  if (reasoning) {
    // Key UX: during thinking (content empty), details is expanded by default
    // so the user sees the reasoning stream; once content starts arriving,
    // details auto-collapses to avoid a long reasoning chain pushing content
    // out of the viewport. Users can still click summary to expand.
    const openAttr = content ? '' : ' open';
    parts.push(
      `<details class="thinking"${openAttr}>` +
      `<summary>💭 Reasoning</summary>` +
      `<div>${escapeHtml(reasoning)}</div>` +
      `</details>`
    );
  }

  if (content) {
    parts.push(`<div class="bubble-content">${renderLiteMarkdown(content)}</div>`);
  } else if (reasoning) {
    // Thinking, content not yet arrived
    parts.push(`<div class="text-slate-400 text-xs">Generating content…${showCursor ? '<span class="cursor"></span>' : ''}</div>`);
  } else {
    parts.push(`<span class="cursor"></span>`);
  }

  return parts.join('');
}

/* ============================================================
 * DOM helpers: append bubbles / scroll to bottom
 * ============================================================ */
function appendUserBubble(boxId, text, imageThumbUrl) {
  const box = document.getElementById(boxId);
  if (!box) return null;
  const div = document.createElement('div');
  div.className = 'bubble bubble-user';
  let html = `<div class="bubble-meta">You</div>` +
    `<div class="bubble-body">${escapeHtml(text)}`;
  if (imageThumbUrl) {
    html += `<br/><img class="bubble-thumb" src="${imageThumbUrl}" alt="Invoice image"/>`;
  }
  html += `</div>`;
  div.innerHTML = html;
  box.appendChild(div);
  scrollToBottom(boxId);
  return div;
}

function appendAssistantBubble(boxId, initialHtml) {
  const box = document.getElementById(boxId);
  if (!box) return null;
  const div = document.createElement('div');
  div.className = 'bubble bubble-assistant';
  div.innerHTML = `<div class="bubble-meta">Smart Assistant</div>` +
    `<div class="bubble-body">${initialHtml || ''}</div>`;
  box.appendChild(div);
  scrollToBottom(boxId);
  return div;
}

function appendErrorBubble(boxId, text) {
  const box = document.getElementById(boxId);
  if (!box) return null;
  const div = document.createElement('div');
  div.className = 'bubble bubble-assistant bubble-error';
  div.innerHTML = `<div class="bubble-meta">Smart Assistant</div>` +
    `<div class="bubble-body">⚠️ ${escapeHtml(text)}</div>`;
  box.appendChild(div);
  scrollToBottom(boxId);
  return div;
}

function scrollToBottom(boxId) {
  const box = document.getElementById(boxId);
  if (!box) return;
  box.scrollTop = box.scrollHeight;
}

function updateSessionIdDisplay() {
  const el = document.getElementById('session-id-display');
  if (el) el.textContent = sessionId || '-';
}

/* ============================================================
 * 8.4 Single review interaction handleInvoiceProcess()
 * ============================================================ */
async function handleInvoiceProcess() {
  if (isStreamingSingle) return;
  const input = document.getElementById('input-single');
  const message = (input.value || '').trim();
  const file = selectedSingleFile;
  const doVerify = document.getElementById('do-verify-single').checked;

  if (!message && !file) {
    input.focus();
    return;
  }

  // Has image: run deterministic pipeline
  if (file) {
    await handleInvoiceUpload(message, file, doVerify);
    return;
  }

  // No image: run follow-up
  if (message) {
    input.value = '';
    await handleFollowup(message, 'chat-messages-single');
  }
}

async function handleInvoiceUpload(message, file, doVerify) {
  isStreamingSingle = true;
  setSendLoading('send-single', true);

  const userText = (message ? message + '\n\n' : '') + '📎 Invoice image uploaded, starting review…';
  const thumbUrl = URL.createObjectURL(file);
  appendUserBubble('chat-messages-single', userText.trim(), thumbUrl);

  // Clear input and image selection
  document.getElementById('input-single').value = '';
  clearSingleImage();

  const assistantBubble = appendAssistantBubble('chat-messages-single',
    '🤔 Starting review…<span class="cursor"></span>');
  const body = assistantBubble.querySelector('.bubble-body');

  const formData = new FormData();
  formData.append('image', file);
  formData.append('do_verify', doVerify ? 'true' : 'false');
  formData.append('session_id', sessionId);

  const statusLog = [];
  let finalResult = null;

  try {
    const resp = await apiFetch('/api/invoice/process', { method: 'POST', body: formData });
    await streamSSE(resp, (ev) => {
      const t = ev && ev.type;
      if (t === 'status') {
        statusLog.push(ev.text || '');
        body.innerHTML = statusLog.map(s => `<div class="status-line">${escapeHtml(s)}</div>`).join('') +
          '<span class="cursor"></span>';
        scrollToBottom('chat-messages-single');
      } else if (t === 'done') {
        finalResult = ev.result || null;
        // Prefer backend-returned HTML card field; otherwise frontend renders
        const summary = renderResultSummary(finalResult);
        body.innerHTML = summary;
        const cardHtml = (finalResult && (finalResult.decision_card || finalResult.card))
          ? (finalResult.decision_card || finalResult.card)
          : renderSingleCard(finalResult);
        const card = document.getElementById('right-card-single');
        if (card) card.innerHTML = `<div class="card-content">${cardHtml}</div>`;
        scrollToBottom('chat-messages-single');
      } else if (t === 'error') {
        body.innerHTML += `<div class="text-red-600 mt-2">⚠️ ${escapeHtml(ev.text || 'Processing error')}</div>`;
        scrollToBottom('chat-messages-single');
      }
    });
    // If the stream ends without any status / done, show a hint
    if (!finalResult && statusLog.length === 0) {
      body.innerHTML = '<span class="text-slate-500">No response received.</span>';
    }
  } catch (err) {
    body.innerHTML = `<span class="text-red-600">⚠️ Request failed: ${escapeHtml(err.message || String(err))}</span>`;
  } finally {
    isStreamingSingle = false;
    setSendLoading('send-single', false);
    // Release object URL
    setTimeout(() => { try { URL.revokeObjectURL(thumbUrl); } catch (_) {} }, 1000);
  }
}

/** Summary text for single review done event result */
function renderResultSummary(result) {
  if (!result) return '<span class="text-slate-500">Processing complete.</span>';
  if (!result.ok) {
    return `<div class="text-red-600">❌ Processing failed (${escapeHtml(result.stage || '')}): ` +
      `${escapeHtml(result.message || '')}</div>`;
  }
  const extract = result.extract || {};
  const verify = result.verify || {};
  const decision = result.decision || {};
  const vFlag = verify.verified ? '✅ Passed' : '❌ Failed';
  const lines = [];
  lines.push(`<div class="status-line">Invoice authenticity: ${vFlag} (${escapeHtml(verify.message || '')})</div>`);
  lines.push(`<div class="status-line">Invoice No. ${escapeHtml(extract.fphm || '')} | Date ${escapeHtml(extract.date || '')} | Total ${escapeHtml(String(extract.code || ''))}</div>`);
  if (decision.summary_text) {
    lines.push(`<div class="status-line mt-2">${renderLiteMarkdown(decision.summary_text)}</div>`);
  }
  return lines.join('');
}

/* ============================================================
 * 8.5 Single decision card renderSingleCard(result)
 * Backend SSE returns a structured dict; frontend renders the card itself
 * ============================================================ */
function renderSingleCard(result) {
  if (!result) return '';
  if (!result.ok) {
    return `<div class="conc-block conc-reject">❌ Processing failed (${escapeHtml(result.stage || '')}): ${escapeHtml(result.message || '')}</div>`;
  }
  const extract = result.extract || {};
  const verify = result.verify || {};
  const decision = result.decision || {};
  const conclusion = decision.conclusion || '';
  const style = CONCLUSION_STYLE[conclusion] || { icon: 'ℹ️', cls: 'conc-info' };

  const vFlag = verify.verified ? '✅ Passed' : '❌ Failed';
  const total = fmtNum(decision.total_amount);
  const reimb = fmtNum(decision.total_reimbursable);
  const med = fmtNum(decision.total_medical_insurance);
  const com = fmtNum(decision.total_commercial);

  // Amount summary cards
  const amountSummary = `
    <div class="amount-summary">
      <div class="amount-card"><div class="label">Total (tax incl.)</div><div class="value">${escapeHtml(total)}</div></div>
      <div class="amount-card highlight"><div class="label">Total Reimbursable</div><div class="value">${escapeHtml(reimb)}</div></div>
      <div class="amount-card"><div class="label">└ Medical Insurance</div><div class="value">${escapeHtml(med)}</div></div>
      <div class="amount-card"><div class="label">└ Commercial Insurance</div><div class="value">${escapeHtml(com)}</div></div>
    </div>`;

  // Item detail table
  const items = Array.isArray(decision.items) ? decision.items : [];
  let itemRows = '';
  if (items.length) {
    itemRows = items.map(it => {
      const name = escapeHtml(it.name || '');
      const amount = fmtNum(it.amount);
      const cat = escapeHtml(it.category || '');
      const m = fmtNum(it.medical_reimbursable);
      const c = fmtNum(it.commercial_reimbursable);
      return `<tr>
        <td>${name}</td>
        <td style="text-align:right">${escapeHtml(amount)}</td>
        <td style="text-align:center">${cat}</td>
        <td style="text-align:right">${escapeHtml(m)}</td>
        <td style="text-align:right">${escapeHtml(c)}</td>
      </tr>`;
    }).join('');
  } else {
    itemRows = `<tr><td colspan="5" style="text-align:center;color:#94a3b8">No details</td></tr>`;
  }

  const itemTable = `
    <h3>📋 Item Details</h3>
    <table class="detail-table">
      <thead><tr>
        <th>Drug</th><th>Amount</th><th>Category</th><th>Medical Reimb.</th><th>Commercial Reimb.</th>
      </tr></thead>
      <tbody>${itemRows}</tbody>
    </table>`;

  return `
    <div class="conc-block ${style.cls}">
      <div class="conc-title">${style.icon} Claim Decision: ${escapeHtml(labelConc(conclusion))}</div>
      <div class="conc-sub">
        Authenticity: ${vFlag} | Invoice No. ${escapeHtml(extract.fphm || '')} | Date ${escapeHtml(extract.date || '')}
      </div>
    </div>
    <h3>💰 Amount Summary</h3>
    ${amountSummary}
    ${itemTable}
  `;
}

/* ============================================================
 * 8.6 Follow-up interaction handleFollowup(message, boxId)
 * ============================================================ */
async function handleFollowup(message, boxId) {
  if (isStreamingSingle && boxId === 'chat-messages-single') return;
  if (isStreamingBatch && boxId === 'chat-messages-batch') return;
  if (!message) return;

  if (boxId === 'chat-messages-single') isStreamingSingle = true;
  if (boxId === 'chat-messages-batch') isStreamingBatch = true;
  const sendBtnId = boxId === 'chat-messages-batch' ? 'send-batch-followup' : 'send-single';
  setSendLoading(sendBtnId, true);

  appendUserBubble(boxId, message);
  const assistantBubble = appendAssistantBubble(boxId,
    '🤔 Thinking…<span class="cursor"></span>');
  const body = assistantBubble.querySelector('.bubble-body');

  const reasoningParts = [];
  const contentParts = [];
  let hadError = false;

  try {
    const resp = await apiFetch('/api/followup', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: message, session_id: sessionId }),
    });
    let hasBuilt = false;  // first chunk builds DOM, rest update textContent
    await streamSSE(resp, (ev) => {
      const t = ev && ev.type;
      if (t === 'reasoning') {
        reasoningParts.push(ev.text || '');
        if (!hasBuilt) {
          body.innerHTML = renderStreamingBubble(reasoningParts.join(''), '', { showCursor: true });
          hasBuilt = true;
        } else {
          // Incremental update: find reasoning div, update only textContent
          const det = body.querySelector('details.thinking div');
          if (det) det.textContent = reasoningParts.join('');
        }
        scrollToBottom(boxId);
      } else if (t === 'content') {
        contentParts.push(ev.text || '');
        if (!hasBuilt) {
          body.innerHTML = renderStreamingBubble('', contentParts.join(''), { showCursor: true });
          hasBuilt = true;
        } else {
          // Find content div and update; if not yet created, do a rebuild
          const contentDiv = body.querySelector('.bubble-content');
          if (contentDiv) {
            contentDiv.innerHTML = renderLiteMarkdown(contentParts.join(''));
          } else {
            body.innerHTML = renderStreamingBubble(reasoningParts.join(''), contentParts.join(''), { showCursor: true });
          }
        }
        // Once content arrives, collapse reasoning to avoid pushing content off-screen
        const det = body.querySelector('details.thinking');
        if (det) det.removeAttribute('open');
        scrollToBottom(boxId);
      } else if (t === 'done') {
        const finalContent = contentParts.join('');
        if (!finalContent) {
          body.innerHTML = renderStreamingBubble(
            reasoningParts.join(''),
            '⚠️ The model returned no content (the reasoning chain may have exhausted the token budget). Try simplifying your question or increasing LLM_MAX_TOKENS in config.py.',
            { showCursor: false }
          );
        } else {
          body.innerHTML = renderStreamingBubble(
            reasoningParts.join(''),
            finalContent,
            { showCursor: false }
          );
        }
        const ddet = body.querySelector('details.thinking');
        if (ddet) ddet.removeAttribute('open');
        scrollToBottom(boxId);
      } else if (t === 'error') {
        hadError = true;
        body.innerHTML = renderStreamingBubble(
          reasoningParts.join(''),
          contentParts.join('') + `\n\n⚠️ ${ev.text || 'Processing error'}`,
          { showCursor: false }
        );
        scrollToBottom(boxId);
      }
    });
    // Fallback: stream ended but no content at all
    if (!reasoningParts.length && !contentParts.length && !hadError) {
      body.innerHTML = '<span class="text-slate-500">No response received.</span>';
    }
  } catch (err) {
    body.innerHTML = `<span class="text-red-600">⚠️ Request failed: ${escapeHtml(err.message || String(err))}</span>`;
  } finally {
    if (boxId === 'chat-messages-single') isStreamingSingle = false;
    if (boxId === 'chat-messages-batch') isStreamingBatch = false;
    setSendLoading(sendBtnId, false);
  }
}

/** Batch tab follow-up: reuses handleFollowup but updates the batch chat area */
async function handleBatchFollowup() {
  const input = document.getElementById('input-batch');
  const message = (input.value || '').trim();
  if (!message) return;
  input.value = '';
  await handleFollowup(message, 'chat-messages-batch');
}

/* ============================================================
 * 8.7 Batch review interaction handleBatchProcess()
 * ============================================================ */
async function handleBatchProcess() {
  if (isStreamingBatch) return;
  const files = selectedBatchFiles;
  if (!files || !files.length) {
    appendErrorBubble('chat-messages-batch', 'Please select a folder containing invoice images first');
    return;
  }

  isStreamingBatch = true;
  setSendLoading('start-batch', true);

  appendUserBubble('chat-messages-batch',
    `📎 ${files.length} invoice images uploaded, starting batch review…`);
  const assistantBubble = appendAssistantBubble('chat-messages-batch',
    '🤔 Starting batch review…<span class="cursor"></span>');
  const body = assistantBubble.querySelector('.bubble-body');

  const formData = new FormData();
  for (const f of files) {
    // FastAPI endpoint signature files: List[UploadFile] = File(...) expects
    // the field name "files" ("files[]" is PHP/Express style; FastAPI doesn't
    // recognize it and returns 422 Unprocessable Entity)
    formData.append('files', f);
  }
  formData.append('do_verify', document.getElementById('do-verify-batch').checked ? 'true' : 'false');
  formData.append('session_id', sessionId);

  const statusLog = [];
  let finalResult = null;

  try {
    const resp = await apiFetch('/api/batch/process', { method: 'POST', body: formData });
    await streamSSE(resp, (ev) => {
      const t = ev && ev.type;
      if (t === 'status' || t === 'progress') {
        // Support both status / progress event names
        const text = ev.text || ev.status ||
          (ev.filename ? `[${(ev.index || 0) + 1}/${ev.total || '?'}] ${ev.filename} · ${ev.stage || ''}` : '');
        if (text) statusLog.push(text);
        body.innerHTML = statusLog.map(s => `<div class="status-line">${escapeHtml(s)}</div>`).join('') +
          '<span class="cursor"></span>';
        scrollToBottom('chat-messages-batch');
      } else if (t === 'done') {
        finalResult = ev.result || null;
        const aggregate = (finalResult && finalResult.aggregate) || {};
        const summary = aggregate.summary_text || 'Batch review complete.';
        body.innerHTML = `<div class="status-line">${renderLiteMarkdown(summary)}</div>`;
        // Render right-side batch card
        const cardHtml = renderBatchCard(finalResult);
        const card = document.getElementById('right-card-batch');
        if (card) card.innerHTML = `<div class="card-content">${cardHtml}</div>`;
        // Enable export button
        hasBatchResult = !!(finalResult && finalResult.ok);
        const exportBtn = document.getElementById('export-csv');
        if (exportBtn) exportBtn.disabled = !hasBatchResult;
        scrollToBottom('chat-messages-batch');
      } else if (t === 'error') {
        body.innerHTML += `<div class="text-red-600 mt-2">⚠️ ${escapeHtml(ev.text || 'Processing error')}</div>`;
        scrollToBottom('chat-messages-batch');
      }
    });
    if (!finalResult && statusLog.length === 0) {
      body.innerHTML = '<span class="text-slate-500">No response received.</span>';
    }
  } catch (err) {
    body.innerHTML = `<span class="text-red-600">⚠️ Request failed: ${escapeHtml(err.message || String(err))}</span>`;
  } finally {
    isStreamingBatch = false;
    setSendLoading('start-batch', false);
  }
}

/* ============================================================
 * 8.8 Batch card renderBatchCard(batchResult)
 * Mirrors app.py format_batch_card layout, rendered natively on frontend
 * Key: each successful non-duplicate invoice row has a drug sub-table below
 * (6 columns)
 * ============================================================ */
function renderBatchCard(batchResult) {
  if (!batchResult || !batchResult.ok) {
    let msg = '';
    if (batchResult && typeof batchResult === 'object') {
      msg = batchResult.message || batchResult.stage || '';
    }
    const tail = msg ? `: ${escapeHtml(msg)}` : '';
    return `<div class="conc-block conc-reject">❌ Batch processing failed${tail}</div>`;
  }

  const aggregate = batchResult.aggregate || {};
  const conclusion = aggregate.conclusion || '';
  const style = BATCH_CONCLUSION_STYLE[conclusion] || { icon: 'ℹ️', cls: 'conc-info' };

  const totalInvoices = aggregate.total_invoices ?? 0;
  const successCount = aggregate.success_count ?? 0;
  const failedCount = aggregate.failed_count ?? 0;
  const duplicateCount = aggregate.duplicate_count ?? 0;

  const totalAmount = fmtNum(aggregate.total_amount);
  const totalReimbursable = fmtNum(aggregate.total_reimbursable);
  const totalMedical = fmtNum(aggregate.total_medical_insurance);
  const totalCommercial = fmtNum(aggregate.total_commercial);
  const capApplied = !!(aggregate.cap_applied);
  const medicalAfterCap = fmtNum(aggregate.medical_after_cap ?? aggregate.total_medical_insurance);
  const capNote = aggregate.cap_note || '';

  // Top color block
  const header = `
    <div class="conc-block ${style.cls}">
      <div class="conc-title">${style.icon} Batch Claim Decision: ${escapeHtml(labelBatchConc(conclusion))}</div>
      <div class="conc-sub">
        Total ${escapeHtml(String(totalInvoices))} (Success ${escapeHtml(String(successCount))}, Failed ${escapeHtml(String(failedCount))}, Duplicate ${escapeHtml(String(duplicateCount))})
      </div>
    </div>`;

  // Amount summary cards
  let amountCards = `
    <div class="amount-summary">
      <div class="amount-card"><div class="label">Total Amount (tax incl.)</div><div class="value">${escapeHtml(totalAmount)}</div></div>
      <div class="amount-card highlight"><div class="label">Total Reimbursable</div><div class="value">${escapeHtml(totalReimbursable)}</div></div>
      <div class="amount-card"><div class="label">└ Medical Insurance</div><div class="value">${escapeHtml(totalMedical)}</div></div>
      <div class="amount-card"><div class="label">└ Commercial Insurance</div><div class="value">${escapeHtml(totalCommercial)}</div></div>`;
  if (capApplied) {
    amountCards += `
      <div class="amount-card"><div class="label">└ Medical (after cap)</div><div class="value">${escapeHtml(medicalAfterCap)}</div></div>`;
  }
  amountCards += `</div>`;

  // Per-invoice detail table
  const invoices = Array.isArray(batchResult.invoices) ? batchResult.invoices : [];
  let detailRows = '';
  for (const inv of invoices) {
    if (!inv || typeof inv !== 'object') continue;
    const idx = inv.index;
    let seq;
    if (typeof idx === 'number') seq = idx + 1;
    else if (idx != null) seq = idx;
    else seq = '';
    const filename = escapeHtml(inv.filename || '');
    const ok = !!inv.ok;
    const duplicateOf = inv.duplicate_of;
    const stage = escapeHtml(inv.stage || '');

    const extract = inv.extract || {};
    const fphm = escapeHtml(extract.fphm || '');
    const code = fmtNum(extract.code);

    const decision = inv.decision || {};
    const med = fmtNum(decision.total_medical_insurance);
    const com = fmtNum(decision.total_commercial);
    const reimb = fmtNum(decision.total_reimbursable);
    const invConc = escapeHtml(labelConc(decision.conclusion || ''));

    // Conclusion column: duplicate > failed > success
    let cellConc;
    if (duplicateOf != null) {
      cellConc = `<span style="color:#b06000">Duplicate ⚠️</span>`;
    } else if (!ok) {
      cellConc = `<span style="color:#c5221f">Failed (${stage})</span>`;
    } else {
      cellConc = invConc;
    }

    detailRows += `<tr>
      <td style="text-align:center">${escapeHtml(String(seq))}</td>
      <td>${filename}</td>
      <td>${fphm}</td>
      <td style="text-align:right">${escapeHtml(code)}</td>
      <td style="text-align:right">${escapeHtml(med)}</td>
      <td style="text-align:right">${escapeHtml(com)}</td>
      <td style="text-align:right">${escapeHtml(reimb)}</td>
      <td style="text-align:center">${cellConc}</td>
    </tr>`;

    // Successful non-duplicate invoices: expand a drug detail sub-table below
    // the main table row. Duplicate invoices (duplicate_of non-null) and
    // failed invoices (ok=false) are not expanded.
    if (ok && duplicateOf == null) {
      const items = Array.isArray(decision.items) ? decision.items : [];
      if (items.length) {
        let itemRows = '';
        for (const it of items) {
          if (!it || typeof it !== 'object') continue;
          const name = escapeHtml(it.name || '');
          const amount = fmtNum(it.amount);
          const cat = escapeHtml(it.category || '');
          const m = fmtNum(it.medical_reimbursable);
          const c = fmtNum(it.commercial_reimbursable);
          const reason = escapeHtml(it.reason || '');
          itemRows += `<tr>
            <td>${name}</td>
            <td style="text-align:right">${escapeHtml(amount)}</td>
            <td style="text-align:center">${cat}</td>
            <td style="text-align:right">${escapeHtml(m)}</td>
            <td style="text-align:right">${escapeHtml(c)}</td>
            <td>${reason}</td>
          </tr>`;
        }
        // Sub-table columns align with single item details, plus a "Reason"
        // column (6 columns total)
        detailRows += `<tr><td colspan="8" style="padding:0;border:none;background:transparent">
          <div class="item-table-title">└ Drug Details</div>
          <table class="item-table">
            <thead><tr>
              <th>Drug</th><th>Amount</th><th>Category</th>
              <th>Medical Reimb.</th><th>Commercial Reimb.</th><th>Reason</th>
            </tr></thead>
            <tbody>${itemRows}</tbody>
          </table>
        </td></tr>`;
      }
    }
  }

  const detailTable = `
    <h3>📋 Per-Invoice Details</h3>
    <table class="detail-table">
      <thead><tr>
        <th>#</th><th>Filename</th><th>Invoice No.</th>
        <th>Total (tax incl.)</th><th>Medical Reimb.</th><th>Commercial Reimb.</th>
        <th>Reimb. Total</th><th>Decision</th>
      </tr></thead>
      <tbody>${detailRows || `<tr><td colspan="8" style="text-align:center;color:#94a3b8">No details</td></tr>`}</tbody>
    </table>`;

  // Cap notice
  let capSection = '';
  if (capApplied && capNote) {
    capSection = `<div class="cap-note">⚠️ ${escapeHtml(capNote)}</div>`;
  }

  return `${header}
    <h3>💰 Amount Summary</h3>
    ${amountCards}
    ${detailTable}
    ${capSection}`;
}

/* ============================================================
 * 8.9 Tab switching
 * ============================================================ */
function switchTab(tabName) {
  const tabs = document.querySelectorAll('.tab-btn');
  tabs.forEach(btn => {
    if (btn.dataset.tab === tabName) {
      btn.classList.add('tab-active');
      btn.classList.remove('tab-inactive');
      btn.setAttribute('aria-selected', 'true');
    } else {
      btn.classList.remove('tab-active');
      btn.classList.add('tab-inactive');
      btn.setAttribute('aria-selected', 'false');
    }
  });
  const panels = document.querySelectorAll('.tab-panel');
  panels.forEach(p => p.classList.add('hidden'));
  const target = document.getElementById('panel-' + tabName);
  if (target) target.classList.remove('hidden');
}

/* ============================================================
 * 8.11 Health check
 * ============================================================ */
async function checkHealth() {
  const indicator = document.getElementById('health-indicator');
  const dot = document.getElementById('health-dot');
  const text = document.getElementById('health-text');
  if (!indicator) return;
  try {
    const r = await fetch('/api/health');
    if (r.ok) {
      indicator.classList.remove('health-fail');
      indicator.classList.add('health-ok');
      if (dot) dot.className = 'w-2.5 h-2.5 rounded-full bg-emerald-500';
      if (text) text.textContent = 'Backend connected';
    } else {
      indicator.classList.remove('health-ok');
      indicator.classList.add('health-fail');
      if (dot) dot.className = 'w-2.5 h-2.5 rounded-full bg-red-500';
      if (text) text.textContent = 'Disconnected';
    }
  } catch (_) {
    indicator.classList.remove('health-ok');
    indicator.classList.add('health-fail');
    if (dot) dot.className = 'w-2.5 h-2.5 rounded-full bg-red-500';
    if (text) text.textContent = 'Disconnected';
  }
}

/* ============================================================
 * Helper: button loading state
 * ============================================================ */
function setSendLoading(btnId, loading) {
  const btn = document.getElementById(btnId);
  if (!btn) return;
  btn.disabled = loading;
  if (loading) {
    btn.dataset.originalText = btn.textContent;
    btn.textContent = '…';
  } else {
    if (btn.dataset.originalText) {
      btn.textContent = btn.dataset.originalText;
    }
  }
}

/* ============================================================
 * Single image selection / clear
 * ============================================================ */
function clearSingleImage() {
  selectedSingleFile = null;
  const fileInput = document.getElementById('file-input-single');
  if (fileInput) fileInput.value = '';
  const wrap = document.getElementById('image-preview-wrap-single');
  if (wrap) wrap.classList.add('hidden');
  const img = document.getElementById('image-preview-single');
  if (img) img.src = '';
  const name = document.getElementById('image-name-single');
  if (name) name.textContent = '';
}

/* ============================================================
 * 8.10 Event binding (DOMContentLoaded)
 * ============================================================ */
document.addEventListener('DOMContentLoaded', () => {
  // ---- Auth: show login overlay if no token; bind login button ----
  if (getToken()) {
    hideLoginOverlay();
  } else {
    showLoginOverlay();
  }
  const loginBtn = document.getElementById('login-btn');
  if (loginBtn) loginBtn.addEventListener('click', doLogin);
  const loginPass = document.getElementById('login-pass');
  if (loginPass) loginPass.addEventListener('keydown', (e) => { if (e.key === 'Enter') doLogin(); });

  // Initialize session_id
  sessionId = getSessionId();
  updateSessionIdDisplay();

  // Health check
  checkHealth();
  setInterval(checkHealth, 30000);  // Re-check every 30 seconds

  // ---- Tab switching ----
  document.getElementById('tab-single').addEventListener('click', () => switchTab('single'));
  document.getElementById('tab-batch').addEventListener('click', () => switchTab('batch'));

  // ---- Single tab ----
  const sendBtn = document.getElementById('send-single');
  const inputSingle = document.getElementById('input-single');
  sendBtn.addEventListener('click', handleInvoiceProcess);
  // Enter to send (shift+enter for newline)
  inputSingle.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleInvoiceProcess();
    }
  });

  // Image upload change
  const fileInputSingle = document.getElementById('file-input-single');
  fileInputSingle.addEventListener('change', (e) => {
    const f = e.target.files && e.target.files[0];
    if (!f) return;
    selectedSingleFile = f;
    const wrap = document.getElementById('image-preview-wrap-single');
    wrap.classList.remove('hidden');
    const img = document.getElementById('image-preview-single');
    img.src = URL.createObjectURL(f);
    const name = document.getElementById('image-name-single');
    name.textContent = f.name;
  });
  // Remove image
  document.getElementById('clear-image-single').addEventListener('click', clearSingleImage);

  // ---- Batch tab ----
  document.getElementById('start-batch').addEventListener('click', handleBatchProcess);
  document.getElementById('send-batch-followup').addEventListener('click', handleBatchFollowup);
  // Batch follow-up enter key
  const inputBatch = document.getElementById('input-batch');
  inputBatch.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleBatchFollowup();
    }
  });

  // Folder selection
  const fileInputBatch = document.getElementById('file-input-batch');
  fileInputBatch.addEventListener('change', (e) => {
    const files = Array.from(e.target.files || []);
    // Filter images
    selectedBatchFiles = files.filter(f => f.type.startsWith('image/'));
    const cnt = document.getElementById('batch-file-count');
    if (selectedBatchFiles.length) {
      // Show file name list (restore the Gradio-era UX of visible file names)
      const names = selectedBatchFiles.map(f => f.name).sort();
      const preview = names.slice(0, 5).map(n => escapeHtml(n)).join(', ');
      const more = names.length > 5 ? ` and ${names.length} more` : '';
      cnt.innerHTML = `<div class="font-medium text-slate-700">${selectedBatchFiles.length} images selected:</div>` +
        `<div class="mt-0.5 text-slate-600 break-all">${preview}${escapeHtml(more)}</div>`;
    } else {
      cnt.textContent = '';
    }
  });

  // Export CSV
  document.getElementById('export-csv').addEventListener('click', async () => {
    if (!hasBatchResult) return;
    try {
      const resp = await apiFetch('/api/session/' + encodeURIComponent(sessionId) + '/csv');
      if (!resp.ok) return;
      const blob = await resp.blob();
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = 'batch_' + sessionId + '.csv';
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(a.href);
    } catch (_) { /* 401 already handled by apiFetch */ }
  });

  // ---- New session ----
  document.getElementById('new-session-single').addEventListener('click', () => {
    if (isStreamingSingle) return;
    if (!confirm('Start a new session? The current conversation history will be cleared.')) return;
    newSession();
  });
  document.getElementById('new-session-batch').addEventListener('click', () => {
    if (isStreamingBatch) return;
    if (!confirm('Start a new session? The current conversation history will be cleared.')) return;
    newSession();
  });

  // Copy session_id
  document.getElementById('copy-session').addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(sessionId);
      const btn = document.getElementById('copy-session');
      const orig = btn.textContent;
      btn.textContent = '✅';
      setTimeout(() => { btn.textContent = orig; }, 1200);
    } catch (_) {}
  });
});
