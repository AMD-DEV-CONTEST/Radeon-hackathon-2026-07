/* ============================================================
 * app.js — Underwriting Risk Agent frontend logic
 *
 * Core features:
 *   1) Real streaming SSE: fetch + ReadableStream + TextDecoder
 *      Each SSE event triggers onEvent immediately, no setTimeout typewriter
 *      (reuses the streamSSE parser from claim app.js)
 *   2) Unbroken reasoning chain: reasoning / content chunks appended to DOM immediately
 *   3) Backend done event returns a structured report dict; frontend renderReportCard
 *      renders: risk color block + underwriting recommendation + abnormality detail
 *      table + risk detail table + medical reference list + summary + patient info
 *   4) Batch: progress events appended one by one; done renders summary card
 *      (counts + overall_risk_distribution + recommendation_distribution +
 *      summary_text) + per-report expandable cards
 *   5) CSV download: GET /api/underwriting/session/{id}/csv
 *
 * Backend endpoints:
 *   POST /api/underwriting/process   Single SSE: session/status/done
 *   POST /api/underwriting/batch     Batch SSE: session/progress/done
 *   POST /api/underwriting/followup  Follow-up SSE: reasoning/content/done/error
 *   GET  /api/underwriting/session/{id}/csv
 *   GET  /api/health
 * ============================================================ */

'use strict';

/* ============================================================
 * Auth token utilities (login module)
 * Token stored in localStorage; apiFetch auto-attaches Authorization
 * header and triggers login overlay on 401.
 * ============================================================ */
const TOKEN_KEY = 'underwriting_auth_token';
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

// Overall risk level → style mapping (Low=green / Medium=yellow / High=red)
// Keys match backend English enum values; RISK_LABEL provides display text.
const RISK_STYLE = {
  'Low': { icon: '🟢', cls: 'risk-low' },
  'Medium': { icon: '🟡', cls: 'risk-medium' },
  'High': { icon: '🔴', cls: 'risk-high' },
};
const RISK_LABEL = { 'Low': 'Low', 'Medium': 'Medium', 'High': 'High' };

// Underwriting recommendation → badge style mapping
const REC_STYLE = {
  'Standard':                    { icon: '✅', cls: 'rec-standard' },
  'Substandard - Extra Premium': { icon: '💰', cls: 'rec-loading' },
  'Substandard - Exclusion':     { icon: '⚠️', cls: 'rec-exclusion' },
  'Postpone':                    { icon: '⏳', cls: 'rec-defer' },
  'Decline':                     { icon: '❌', cls: 'rec-reject' },
};
const REC_LABEL = {
  'Standard': 'Standard',
  'Substandard - Extra Premium': 'Substandard - Extra Premium',
  'Substandard - Exclusion': 'Substandard - Exclusion',
  'Postpone': 'Postpone',
  'Decline': 'Decline',
};

// Severity → small badge style mapping
const SEV_STYLE = {
  'Mild': { cls: 'sev-light' },
  'Moderate': { cls: 'sev-medium' },
  'Severe': { cls: 'sev-severe' },
};
const SEV_LABEL = { 'Mild': 'Mild', 'Moderate': 'Moderate', 'Severe': 'Severe' };

// PDF file preview placeholder: PDFs cannot be previewed via <img> (blob URL
// renders as broken image), so use an inline SVG placeholder to avoid the
// broken image icon and provide a red "PDF" visual marker.
const PDF_THUMB = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='64' height='64'%3E%3Crect width='64' height='64' rx='6' fill='%23fee2e2'/%3E%3Ctext x='32' y='40' font-size='16' font-family='sans-serif' font-weight='bold' text-anchor='middle' fill='%23b91c1c'%3EPDF%3C/text%3E%3C/svg%3E";

/** Determine if a File is a PDF (by MIME or extension, double-check: some
 *  browsers may return empty type for .pdf files) */
function isPdfFile(f) {
  return !!(f && (f.type === 'application/pdf'
    || (f.name || '').toLowerCase().endsWith('.pdf')));
}

/** Map a backend risk level to display text */
function labelRisk(v) { return RISK_LABEL[v] || v || '-'; }
/** Map a backend recommendation to display text */
function labelRec(v) { return REC_LABEL[v] || v || '-'; }
/** Map a backend severity to display text */
function labelSev(v) { return SEV_LABEL[v] || v || '-'; }

/* ============================================================
 * 8.1 Utility functions
 * ============================================================ */

/** Get or generate a session_id (12-char hex), persisted to localStorage */
function getSessionId() {
  try {
    let id = localStorage.getItem('underwriting_session_id');
    if (!id) {
      id = genSessionId();
      localStorage.setItem('underwriting_session_id', id);
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
  try { localStorage.setItem('underwriting_session_id', sessionId); } catch (_) {}
  updateSessionIdDisplay();

  // Clear single tab
  clearChat('chat-messages-single', 'right-card-single',
    'Hello, I\'m the <b>Underwriting Risk Agent</b>. Upload a medical record / health report image and click Send to start underwriting; or type a follow-up question…');
  // Clear batch tab
  clearChat('chat-messages-batch', 'right-card-batch',
    'Hello, this is <b>Batch Underwriting</b> mode. Select a folder containing multiple report images, then click "Start Batch Underwriting".');

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
    welcome.innerHTML = `<div class="bubble-meta">Underwriting Assistant</div>` +
      `<div class="bubble-body">${welcomeText}</div>`;
    box.appendChild(welcome);
  }
  const card = document.getElementById(cardId);
  if (card) {
    card.innerHTML = `<div class="text-xs text-slate-400 text-center py-8">` +
      `The ${cardId.includes('batch') ? 'summary card' : 'report card'} will appear here after underwriting completes</div>`;
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

/* ============================================================
 * 8.2 streamSSE core utility (critical! reuses claim app.js parser)
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
    html += `<br/><img class="bubble-thumb" src="${imageThumbUrl}" alt="Report image"/>`;
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
  div.innerHTML = `<div class="bubble-meta">Underwriting Assistant</div>` +
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
  div.innerHTML = `<div class="bubble-meta">Underwriting Assistant</div>` +
    `<div class="bubble-body">⚠️ ${escapeHtml(text)}</div>`;
  box.appendChild(div);
  scrollToBottom(boxId);
  return div;
}

// ---- Scroll tracking: pause auto-follow when user scrolls up ----
// _userScrolled[boxId]=true means the user scrolled away from the bottom;
// scrollToBottom should skip, to prevent streaming chunks (every few dozen ms)
// from yanking the scrollbar back down, making it "unstuckable".
const _userScrolled = {};
let _programmaticScroll = false;  // Marks program-triggered scrolls to avoid
                                   // misclassifying them as user scrolls

function _isNearBottom(box, threshold = 60) {
  // Whether near the bottom (within threshold px), used to decide whether to
  // resume auto-follow
  return (box.scrollHeight - box.scrollTop - box.clientHeight) < threshold;
}

function _onChatScroll(boxId) {
  // Program-triggered scrolls don't count as user scrolls (otherwise
  // scrollToBottom would misclassify itself as a user scroll)
  if (_programmaticScroll) return;
  const box = document.getElementById(boxId);
  if (!box) return;
  // Near bottom → clear flag and resume follow; scrolled up → flag to pause
  _userScrolled[boxId] = !_isNearBottom(box);
}

function scrollToBottom(boxId) {
  const box = document.getElementById(boxId);
  if (!box) return;
  // When the user has scrolled up to view history, don't force back to bottom
  // (fixes the "can't drag" issue during streaming follow-ups)
  if (_userScrolled[boxId]) return;
  _programmaticScroll = true;
  requestAnimationFrame(() => {
    box.scrollTop = box.scrollHeight;
    // Reset the flag on the next frame to ensure the scroll event triggered
    // by this programmatic scroll has been ignored
    requestAnimationFrame(() => { _programmaticScroll = false; });
  });
}

function updateSessionIdDisplay() {
  const el = document.getElementById('session-id-display');
  if (el) el.textContent = sessionId || '-';
}

/* ============================================================
 * 8.4 Single underwriting interaction handleUnderwritingProcess()
 * ============================================================ */
async function handleUnderwritingProcess() {
  if (isStreamingSingle) return;
  const input = document.getElementById('input-single');
  const message = (input.value || '').trim();
  const file = selectedSingleFile;

  if (!message && !file) {
    input.focus();
    return;
  }

  // Has image: run deterministic pipeline
  if (file) {
    await handleSingleUpload(message, file);
    return;
  }

  // No image: run follow-up
  if (message) {
    input.value = '';
    await handleFollowup(message, 'chat-messages-single');
  }
}

async function handleSingleUpload(message, file) {
  isStreamingSingle = true;
  setSendLoading('send-single', true);

  const pdf = isPdfFile(file);
  const userText = (message ? message + '\n\n' : '')
    + (pdf ? '📎 Report PDF uploaded, starting underwriting…' : '📎 Report image uploaded, starting underwriting…');
  // PDFs cannot be rendered as <img> thumbnails (blob URL breaks), use PDF
  // placeholder SVG instead; appendUserBubble skips img when imageThumbUrl is
  // falsy, but a placeholder is more intuitive here.
  const thumbUrl = pdf ? PDF_THUMB : URL.createObjectURL(file);
  appendUserBubble('chat-messages-single', userText.trim(), thumbUrl);

  // Clear input and image selection
  document.getElementById('input-single').value = '';
  clearSingleImage();

  const assistantBubble = appendAssistantBubble('chat-messages-single',
    '🤔 Starting underwriting…<span class="cursor"></span>');
  const body = assistantBubble.querySelector('.bubble-body');

  const formData = new FormData();
  formData.append('image', file);
  formData.append('session_id', sessionId);

  const statusLog = [];
  let finalResult = null;

  try {
    const resp = await apiFetch('/api/underwriting/process', { method: 'POST', body: formData });
    await streamSSE(resp, (ev) => {
      const t = ev && ev.type;
      if (t === 'session') {
        // Backend returns session_id (generated when frontend didn't provide
        // one), sync to local
        if (ev.session_id) {
          sessionId = ev.session_id;
          try { localStorage.setItem('underwriting_session_id', sessionId); } catch (_) {}
          updateSessionIdDisplay();
        }
      } else if (t === 'status') {
        statusLog.push(ev.text || '');
        body.innerHTML = statusLog.map(s => `<div class="status-line">${escapeHtml(s)}</div>`).join('') +
          '<span class="cursor"></span>';
        scrollToBottom('chat-messages-single');
      } else if (t === 'done') {
        finalResult = ev.result || null;
        // Render left-side chat area summary
        const summary = renderResultSummary(finalResult);
        body.innerHTML = summary;
        // Render right-side report card
        const cardHtml = renderReportCard(finalResult);
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

/** Left-side chat area summary text for single underwriting done event result */
function renderResultSummary(result) {
  if (!result) return '<span class="text-slate-500">Processing complete.</span>';
  if (!result.ok) {
    return `<div class="text-red-600">❌ Processing failed (${escapeHtml(result.stage || '')}): ` +
      `${escapeHtml(result.message || '')}</div>`;
  }
  const patient = result.patient || {};
  const overallRisk = result.overall_risk || '';
  const recommendation = result.recommendation || '';
  const riskStyle = RISK_STYLE[overallRisk] || { icon: 'ℹ️', cls: 'risk-info' };
  const recStyle = REC_STYLE[recommendation] || { icon: 'ℹ️', cls: 'rec-unknown' };

  const lines = [];
  lines.push(`<div class="status-line">${riskStyle.icon} Overall Risk Level: <b>${escapeHtml(labelRisk(overallRisk))}</b></div>`);
  lines.push(`<div class="status-line">${recStyle.icon} Underwriting Recommendation: <b>${escapeHtml(labelRec(recommendation))}</b></div>`);
  const abnCount = Array.isArray(result.abnormalities) ? result.abnormalities.length : 0;
  const refCount = Array.isArray(result.references) ? result.references.length : 0;
  lines.push(`<div class="status-line">${abnCount} abnormalities detected · ${refCount} medical references retrieved</div>`);
  if (result.summary) {
    lines.push(`<div class="status-line mt-2">${renderLiteMarkdown(result.summary)}</div>`);
  }
  return lines.join('');
}

/* ============================================================
 * 8.5 Report card renderReportCard(report)
 * Backend SSE done event returns a structured report; frontend renders the card:
 *   - Top risk color block (overall_risk: Low=green / Medium=yellow / High=red)
 *   - Underwriting recommendation (recommendation) badge + recommendation_reason
 *   - Patient info + report type + exam date
 *   - Report summary (summary)
 *   - Abnormality detail table (item / type / severity / evidence)
 *   - Risk detail table (disease / level / risk factors / reasoning)
 *   - Medical reference list (title / source / link)
 * ============================================================ */
function renderReportCard(report) {
  if (!report) return '';
  if (!report.ok) {
    return `<div class="risk-block risk-high">❌ Processing failed (${escapeHtml(report.stage || '')}): ${escapeHtml(report.message || '')}</div>`;
  }

  const patient = report.patient || {};
  const overallRisk = report.overall_risk || '';
  const recommendation = report.recommendation || '';
  const riskStyle = RISK_STYLE[overallRisk] || { icon: 'ℹ️', cls: 'risk-info' };
  const recStyle = REC_STYLE[recommendation] || { icon: 'ℹ️', cls: 'rec-unknown' };

  // Top risk color block
  const header = `
    <div class="risk-block ${riskStyle.cls}">
      <div class="risk-title">${riskStyle.icon} Overall Risk Level: ${escapeHtml(labelRisk(overallRisk))}</div>
      <div class="risk-sub">
        <span class="rec-badge ${recStyle.cls}">${recStyle.icon} Recommendation: ${escapeHtml(labelRec(recommendation))}</span>
      </div>
    </div>`;

  // Patient info + report type + exam date
  const patientRow = `
    <div class="patient-row">
      <div class="patient-field"><span class="field-label">Report Type:</span><span class="field-value">${escapeHtml(report.report_type || '-')}</span></div>
      <div class="patient-field"><span class="field-label">Name:</span><span class="field-value">${escapeHtml(patient.name || '-')}</span></div>
      <div class="patient-field"><span class="field-label">Gender:</span><span class="field-value">${escapeHtml(patient.gender || '-')}</span></div>
      <div class="patient-field"><span class="field-label">Age:</span><span class="field-value">${escapeHtml(patient.age || '-')}</span></div>
      <div class="patient-field"><span class="field-label">Exam Date:</span><span class="field-value">${escapeHtml(report.exam_date || '-')}</span></div>
    </div>`;

  // Underwriting recommendation reasoning
  let recReasonSection = '';
  if (report.recommendation_reason) {
    recReasonSection = `
      <h3>📝 Recommendation Reasoning</h3>
      <div class="summary-block">${escapeHtml(report.recommendation_reason)}</div>`;
  }

  // Overall risk comprehensive reasoning
  let overallReasoningSection = '';
  if (report.overall_reasoning) {
    overallReasoningSection = `
      <h3>🧭 Comprehensive Assessment</h3>
      <div class="summary-block">${escapeHtml(report.overall_reasoning)}</div>`;
  }

  // Report summary
  let summarySection = '';
  if (report.summary) {
    summarySection = `
      <h3>📋 Report Summary</h3>
      <div class="summary-block">${escapeHtml(report.summary)}</div>`;
  }

  // Abnormality detail table
  const abnormalities = Array.isArray(report.abnormalities) ? report.abnormalities : [];
  const abnRows = abnormalities.length
    ? abnormalities.map(a => {
        const name = escapeHtml(a.name || '');
        const type = escapeHtml(a.type || '');
        const sev = a.severity_hint || '';
        const sevCls = (SEV_STYLE[sev] || { cls: 'sev-unknown' }).cls;
        const evidence = escapeHtml(a.evidence || '');
        const detail = escapeHtml(a.detail || '');
        return `<tr>
          <td>${name}</td>
          <td style="text-align:center">${type}</td>
          <td style="text-align:center"><span class="sev-badge ${sevCls}">${escapeHtml(labelSev(sev))}</span></td>
          <td>${evidence}${detail ? `<div class="text-xs text-slate-500 mt-1">${detail}</div>` : ''}</td>
        </tr>`;
      }).join('')
    : `<tr><td colspan="4" style="text-align:center;color:#94a3b8">No significant abnormalities</td></tr>`;

  const abnTable = `
    <h3>🔬 Abnormality Details (${abnormalities.length})</h3>
    <table class="detail-table">
      <thead><tr>
        <th>Item</th><th>Type</th><th>Severity</th><th>Evidence</th>
      </tr></thead>
      <tbody>${abnRows}</tbody>
    </table>`;

  // Risk detail table
  const risks = Array.isArray(report.risks) ? report.risks : [];
  const riskRows = risks.length
    ? risks.map(r => {
        const name = escapeHtml(r.name || '');
        const level = r.risk_level || '';
        const levelCls = (RISK_STYLE[level] || { cls: 'risk-info' }).cls;
        const factors = Array.isArray(r.risk_factors) ? r.risk_factors : [];
        const factorsHtml = factors.length
          ? factors.map(f => `<span class="risk-factor-tag">${escapeHtml(f)}</span>`).join(' ')
          : '<span class="text-slate-400">-</span>';
        const evidence = escapeHtml(r.evidence || '');
        const reasoning = escapeHtml(r.reasoning || '');
        return `<tr>
          <td>${name}</td>
          <td style="text-align:center"><span class="sev-badge ${levelCls === 'risk-low' ? 'sev-light' : levelCls === 'risk-medium' ? 'sev-medium' : levelCls === 'risk-high' ? 'sev-severe' : 'sev-unknown'}">${escapeHtml(labelRisk(level))}</span></td>
          <td>${factorsHtml}</td>
          <td>${evidence}${reasoning ? `<div class="text-xs text-slate-500 mt-1">${reasoning}</div>` : ''}</td>
        </tr>`;
      }).join('')
    : `<tr><td colspan="4" style="text-align:center;color:#94a3b8">No risk items</td></tr>`;

  const riskTable = `
    <h3>⚠️ Risk Details (${risks.length})</h3>
    <table class="detail-table">
      <thead><tr>
        <th>Disease</th><th>Level</th><th>Risk Factors</th><th>Reasoning</th>
      </tr></thead>
      <tbody>${riskRows}</tbody>
    </table>`;

  // Medical reference list
  const references = Array.isArray(report.references) ? report.references : [];
  let refSection = '';
  if (references.length) {
    const refItems = references.map(r => {
      const title = escapeHtml(r.title || r.url || '(No title)');
      const url = r.url || '';
      const source = (r.source || '').toLowerCase();
      const disease = escapeHtml(r.disease || '');
      const snippet = escapeHtml(r.snippet || '');
      const sourceCls = source === 'health' ? 'src-health'
        : source === 'academic' ? 'src-academic'
        : source === 'exa' ? 'src-exa' : '';
      const titleHtml = url
        ? `<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${title}</a>`
        : title;
      return `<li class="ref-item">
        <div class="ref-title">${titleHtml}</div>
        <div class="ref-meta">
          ${source ? `<span class="ref-source ${sourceCls}">${escapeHtml(source)}</span>` : ''}
          ${disease ? `<span class="ref-disease">Disease: ${disease}</span>` : ''}
        </div>
        ${snippet ? `<div class="ref-snippet">${snippet}</div>` : ''}
      </li>`;
    }).join('');
    refSection = `
      <h3>📚 Medical References (${references.length})</h3>
      <ul class="ref-list">${refItems}</ul>`;
  } else {
    refSection = `
      <h3>📚 Medical References</h3>
      <div class="text-xs text-slate-400">No references available (search returned no results or was unavailable)</div>`;
  }

  return `${header}
    ${patientRow}
    ${summarySection}
    ${recReasonSection}
    ${overallReasoningSection}
    ${abnTable}
    ${riskTable}
    ${refSection}`;
}

/* ============================================================
 * 8.6 Follow-up interaction handleFollowup(message, boxId)
 * Calls /api/underwriting/followup; reasoning chain is appended chunk by
 * chunk in the "💭 Reasoning" collapsible section (reasoning events);
 * content is appended below (content events)
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
    const resp = await apiFetch('/api/underwriting/followup', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: message, session_id: sessionId }),
    });
    await streamSSE(resp, (ev) => {
      const t = ev && ev.type;
      if (t === 'session') {
        if (ev.session_id) {
          sessionId = ev.session_id;
          try { localStorage.setItem('underwriting_session_id', sessionId); } catch (_) {}
          updateSessionIdDisplay();
        }
      } else if (t === 'reasoning') {
        reasoningParts.push(ev.text || '');
        // Incremental update: when content hasn't arrived, only refresh the
        // reasoning text node to avoid full innerHTML rebuild per chunk
        // (escapeHtml of the entire reasoning chain + DOM subtree rebuild causes
        // rendering to lag behind, visually "stuck after a few lines").
        // textContent auto-escapes, equivalent to escapeHtml.
        const thinkDiv = body.querySelector('details.thinking > div');
        if (thinkDiv && !contentParts.length) {
          thinkDiv.textContent = reasoningParts.join('');
        } else {
          // First render or content has started arriving (structure changed):
          // full rebuild
          body.innerHTML = renderStreamingBubble(
            reasoningParts.join(''),
            contentParts.join(''),
            { showCursor: true }
          );
        }
        scrollToBottom(boxId);
      } else if (t === 'content') {
        contentParts.push(ev.text || '');
        body.innerHTML = renderStreamingBubble(
          reasoningParts.join(''),
          contentParts.join(''),
          { showCursor: true }
        );
        scrollToBottom(boxId);
      } else if (t === 'done') {
        // Stream ended: remove cursor, collapse reasoning block
        const finalContent = contentParts.join('');
        if (!finalContent) {
          // Fallback: stream ended but content was always empty — usually
          // because the reasoning chain exhausted the token budget
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
        // Collapse the details element
        const det = body.querySelector('details.thinking');
        if (det) det.removeAttribute('open');
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
 * 8.7 Batch underwriting interaction handleBatchProcess()
 * SSE progress events append status line by line ([1/3] a.jpg · stage)
 * done event renders summary card + per-report expandable details
 * ============================================================ */
async function handleBatchProcess() {
  if (isStreamingBatch) return;
  const files = selectedBatchFiles;
  if (!files || !files.length) {
    appendErrorBubble('chat-messages-batch', 'Please select a folder containing report images first');
    return;
  }

  isStreamingBatch = true;
  setSendLoading('start-batch', true);

  appendUserBubble('chat-messages-batch',
    `📎 ${files.length} report images uploaded, starting batch underwriting…`);
  const assistantBubble = appendAssistantBubble('chat-messages-batch',
    '🤔 Starting batch underwriting…<span class="cursor"></span>');
  const body = assistantBubble.querySelector('.bubble-body');

  const formData = new FormData();
  for (const f of files) {
    // FastAPI endpoint signature files: List[UploadFile] = File(...) expects
    // the field name "files"
    formData.append('files', f);
  }
  formData.append('session_id', sessionId);

  const statusLog = [];
  let finalResult = null;

  try {
    const resp = await apiFetch('/api/underwriting/batch', { method: 'POST', body: formData });
    await streamSSE(resp, (ev) => {
      const t = ev && ev.type;
      if (t === 'session') {
        if (ev.session_id) {
          sessionId = ev.session_id;
          try { localStorage.setItem('underwriting_session_id', sessionId); } catch (_) {}
          updateSessionIdDisplay();
        }
      } else if (t === 'progress') {
        // progress event fields: status/index/total/filename/stage/conclusion
        // Prefer status text; otherwise assemble [index+1/total] filename · stage
        let text = ev.status || '';
        if (!text) {
          const idx = (typeof ev.index === 'number') ? ev.index + 1 : '?';
          const total = ev.total || '?';
          const fname = ev.filename || '';
          const stage = ev.stage || '';
          text = `[${idx}/${total}] ${fname} · ${stage}`;
        }
        statusLog.push(text);
        body.innerHTML = statusLog.map(s => `<div class="status-line">${escapeHtml(s)}</div>`).join('') +
          '<span class="cursor"></span>';
        scrollToBottom('chat-messages-batch');
      } else if (t === 'done') {
        finalResult = ev.result || null;
        const aggregate = (finalResult && finalResult.aggregate) || {};
        const summary = aggregate.summary_text || 'Batch underwriting complete.';
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
 * 8.8 Batch summary card renderBatchCard(batchResult)
 * Renders:
 *   - Top counts (success / duplicate / failed)
 *   - overall_risk_distribution (Low / Medium / High distribution cards)
 *   - recommendation_distribution (recommendation distribution cards)
 *   - summary_text
 *   - Per-report expandable detail list (each report is an expandable card)
 * ============================================================ */
function renderBatchCard(batchResult) {
  if (!batchResult || !batchResult.ok) {
    let msg = '';
    if (batchResult && typeof batchResult === 'object') {
      msg = batchResult.message || batchResult.stage || '';
    }
    const tail = msg ? `: ${escapeHtml(msg)}` : '';
    return `<div class="risk-block risk-high">❌ Batch processing failed${tail}</div>`;
  }

  const total = batchResult.total || 0;
  const successCount = batchResult.success_count || 0;
  const duplicateCount = batchResult.duplicate_count || 0;
  const failCount = batchResult.fail_count || 0;
  const aggregate = batchResult.aggregate || {};
  const riskDist = aggregate.overall_risk_distribution || {};
  const recDist = aggregate.recommendation_distribution || {};
  const summaryText = aggregate.summary_text || '';

  // Top count block
  const header = `
    <div class="risk-block risk-info">
      <div class="risk-title">📁 Batch Underwriting Summary</div>
      <div class="risk-sub">
        <div class="count-row">
          <span class="count-pill">Total ${escapeHtml(String(total))}</span>
          <span class="count-pill c-ok">✅ Success ${escapeHtml(String(successCount))}</span>
          <span class="count-pill c-dup">⚠️ Duplicate ${escapeHtml(String(duplicateCount))}</span>
          <span class="count-pill c-fail">❌ Failed ${escapeHtml(String(failCount))}</span>
        </div>
      </div>
    </div>`;

  // Risk distribution cards
  const riskLow = riskDist['Low'] || 0;
  const riskMed = riskDist['Medium'] || 0;
  const riskHigh = riskDist['High'] || 0;
  const riskDistCards = `
    <h3>🟢🟡🔴 Overall Risk Distribution</h3>
    <div class="dist-summary">
      <div class="amount-card"><div class="label">🟢 Low Risk</div><div class="value">${escapeHtml(String(riskLow))}</div></div>
      <div class="amount-card"><div class="label">🟡 Medium Risk</div><div class="value">${escapeHtml(String(riskMed))}</div></div>
      <div class="amount-card"><div class="label">🔴 High Risk</div><div class="value">${escapeHtml(String(riskHigh))}</div></div>
      <div class="amount-card highlight"><div class="label">Total</div><div class="value">${escapeHtml(String(riskLow + riskMed + riskHigh))}</div></div>
    </div>`;

  // Recommendation distribution cards
  let recItems = '';
  const recKeys = Object.keys(recDist);
  if (recKeys.length) {
    const recCards = recKeys.map(k => {
      const style = REC_STYLE[k] || { icon: 'ℹ️', cls: 'rec-unknown' };
      return `<div class="amount-card">
        <div class="label">${style.icon} ${escapeHtml(labelRec(k))}</div>
        <div class="value">${escapeHtml(String(recDist[k] || 0))}</div>
      </div>`;
    }).join('');
    recItems = `
      <h3>📋 Recommendation Distribution</h3>
      <div class="dist-summary">${recCards}</div>`;
  }

  // Summary text
  let summarySection = '';
  if (summaryText) {
    summarySection = `
      <h3>📝 Batch Summary</h3>
      <div class="summary-block">${escapeHtml(summaryText)}</div>`;
  }

  // Per-report expandable detail list
  const reports = Array.isArray(batchResult.reports) ? batchResult.reports : [];
  let reportList = '';
  if (reports.length) {
    reportList = `<h3>📂 Per-Report Details (click to expand)</h3>`;
    for (const r of reports) {
      if (!r || typeof r !== 'object') continue;
      reportList += renderBatchReportItem(r);
    }
  }

  return `${header}
    ${summarySection}
    ${riskDistCards}
    ${recItems}
    ${reportList}`;
}

/** Render a single report entry within the batch result (expandable) */
function renderBatchReportItem(r) {
  const idx = r.index;
  let seq;
  if (typeof idx === 'number') seq = idx + 1;
  else if (idx != null) seq = idx;
  else seq = '?';
  const filename = escapeHtml(r.filename || '');
  const ok = !!r.ok;
  const duplicateOf = r.duplicate_of;
  const stage = escapeHtml(r.stage || '');
  const message = escapeHtml(r.message || '');
  const report = r.report;

  // Status label
  let statusPill;
  if (duplicateOf != null) {
    statusPill = `<span class="count-pill c-dup">⚠️ Duplicate (same as #${escapeHtml(String(duplicateOf + 1))})</span>`;
  } else if (!ok) {
    statusPill = `<span class="count-pill c-fail">❌ Failed (${stage})</span>`;
  } else {
    const rep = report || {};
    const overallRisk = rep.overall_risk || '';
    const recommendation = rep.recommendation || '';
    const riskStyle = RISK_STYLE[overallRisk] || { icon: 'ℹ️', cls: 'risk-info' };
    const recStyle = REC_STYLE[recommendation] || { icon: 'ℹ️', cls: 'rec-unknown' };
    statusPill = `<span class="count-pill c-ok">${riskStyle.icon} Risk ${escapeHtml(labelRisk(overallRisk))}</span>` +
      `<span class="count-pill">${recStyle.icon} ${escapeHtml(labelRec(recommendation))}</span>`;
  }

  // Failed/duplicate: summary + error info; success: expandable report card
  let body = '';
  if (ok && duplicateOf == null && report) {
    body = `<div class="batch-report-body">${renderReportCard(report)}</div>`;
  } else if (!ok) {
    body = `<div class="batch-report-body"><div class="text-red-600 text-sm">❌ Processing failed (${stage}): ${message}</div></div>`;
  } else if (duplicateOf != null) {
    body = `<div class="batch-report-body"><div class="text-sm text-slate-600">⚠️ Duplicate report, underwriting skipped${message ? ` (${message})` : ''}</div></div>`;
  }

  // Use <details> for expandable behavior
  return `<details class="batch-report-item">
    <summary>
      <span>[${escapeHtml(String(seq))}] ${filename}</span>
      <span class="batch-report-meta">${statusPill}</span>
    </summary>
    ${body}
  </details>`;
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

  // ---- Scroll tracking: listen for manual scrolls, pause auto scrollToBottom
  //      when scrolling up ----
  ['chat-messages-single', 'chat-messages-batch'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.addEventListener('scroll', () => _onChatScroll(id));
  });

  // ---- Tab switching ----
  document.getElementById('tab-single').addEventListener('click', () => switchTab('single'));
  document.getElementById('tab-batch').addEventListener('click', () => switchTab('batch'));

  // ---- Single tab ----
  const sendBtn = document.getElementById('send-single');
  const inputSingle = document.getElementById('input-single');
  sendBtn.addEventListener('click', handleUnderwritingProcess);
  // Enter to send (shift+enter for newline)
  inputSingle.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleUnderwritingProcess();
    }
  });

  // Image/PDF upload change
  const fileInputSingle = document.getElementById('file-input-single');
  fileInputSingle.addEventListener('change', (e) => {
    const f = e.target.files && e.target.files[0];
    if (!f) return;
    selectedSingleFile = f;
    const wrap = document.getElementById('image-preview-wrap-single');
    wrap.classList.remove('hidden');
    const img = document.getElementById('image-preview-single');
    // PDFs can't be previewed via <img>, use PDF placeholder SVG to avoid
    // broken image; images use blob URL
    img.src = isPdfFile(f) ? PDF_THUMB : URL.createObjectURL(f);
    const name = document.getElementById('image-name-single');
    name.textContent = (isPdfFile(f) ? '📄 ' : '') + f.name;
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
    // Filter images and PDFs (PDFs handled by backend pdf_loader)
    selectedBatchFiles = files.filter(f => f.type.startsWith('image/') || isPdfFile(f));
    const cnt = document.getElementById('batch-file-count');
    if (selectedBatchFiles.length) {
      const names = selectedBatchFiles.map(f => f.name).sort();
      const preview = names.slice(0, 5).map(n => escapeHtml(n)).join(', ');
      const more = names.length > 5 ? ` and ${names.length} more` : '';
      cnt.innerHTML = `<div class="font-medium text-slate-700">${selectedBatchFiles.length} files selected:</div>` +
        `<div class="mt-0.5 text-slate-600 break-all">${preview}${escapeHtml(more)}</div>`;
    } else {
      cnt.textContent = '';
    }
  });

  // Export CSV: calls /api/underwriting/session/{id}/csv to download
  document.getElementById('export-csv').addEventListener('click', async () => {
    if (!hasBatchResult) return;
    try {
      const resp = await apiFetch('/api/underwriting/session/' + encodeURIComponent(sessionId) + '/csv');
      if (!resp.ok) return;
      const blob = await resp.blob();
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = 'underwriting_' + sessionId + '.csv';
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
