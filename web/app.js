const $ = (selector) => document.querySelector(selector);

const state = {
  sample: null,
  investigation: null,
  health: null,
  busy: false,
};

const ACTIVE_MESSAGE_STATES = new Set(['awaiting_approval', 'completed', 'degraded']);
const TERMINAL_STATES = new Set(['awaiting_approval', 'completed', 'degraded']);

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>'"]/g, (character) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;',
  })[character]);
}

function requestId(prefix) {
  const id = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `${prefix}-${id}`.slice(0, 64);
}

function normalizeStatus(value) {
  return String(value || 'idle').toLowerCase().replace(/[^a-z0-9_-]/g, '');
}

function humanize(value) {
  return String(value || 'unknown').replaceAll('_', ' ').replaceAll('-', ' ')
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function formatTime(value) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function list(value) {
  return Array.isArray(value) ? value : [];
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
  });
  let payload = {};
  try {
    payload = await response.json();
  } catch (_) {
    throw new Error(`The server returned an unreadable response (${response.status}).`);
  }
  if (!response.ok) {
    const error = new Error(payload.error || `Request failed (${response.status}).`);
    error.code = payload.code;
    throw error;
  }
  return payload;
}

function unwrapInvestigation(payload) {
  return payload?.investigation || payload;
}

function setBusy(busy, label = '') {
  state.busy = busy;
  document.body.classList.toggle('busy', busy);
  $('#create-button').disabled = busy || Boolean(state.investigation);
  $('#sample-button').disabled = busy || Boolean(state.investigation);
  $('#new-button').disabled = busy;
  $('#next-button').disabled = busy || !canRunNext();
  $('#message-input').disabled = busy || !canMessage();
  $('#message-button').disabled = busy || !canMessage();
  document.querySelectorAll('[data-decision]').forEach((button) => {
    button.disabled = busy || button.dataset.locked === 'true';
  });
  if (label) $('#global-error').textContent = label;
}

function showError(error) {
  const message = error?.code ? `${error.message} [${error.code}]` : error?.message || String(error);
  $('#global-error').textContent = message;
  $('#global-error').hidden = false;
}

function clearError() {
  $('#global-error').hidden = true;
  $('#global-error').textContent = '';
}

function runtimeView(runtime = {}) {
  const mode = runtime.mode || runtime.runtime_mode || (runtime.degraded ? 'degraded' : 'offline-safe');
  const model = runtime.model || runtime.llm_model || runtime.engine || 'Deterministic baseline';
  if (runtime.degraded || runtime.fallback) return { label: `Degraded fallback · ${model}`, engine: model, tone: 'fallback' };
  if (mode === 'local-radeon') return { label: `Private Radeon · ${model}`, engine: model, tone: 'local' };
  if (mode === 'remote-api') return { label: `Shared Radeon API · ${model}`, engine: model, tone: 'remote' };
  if (mode === 'local-unverified') return { label: `Local runtime unverified · ${model}`, engine: model, tone: 'warning' };
  if (mode === 'degraded') return { label: 'Deterministic fallback active', engine: model, tone: 'fallback' };
  return { label: 'Offline safe mode', engine: model, tone: 'fallback' };
}

function renderRuntime() {
  const investigation = state.investigation;
  const runtime = investigation?.runtime || state.health || {};
  const view = runtimeView(runtime);
  $('#runtime-label').textContent = view.label;
  $('#engine').textContent = view.engine;
  $('#runtime-dot').className = `dot ${view.tone}`;

  const warning = $('#runtime-warning');
  if (view.tone === 'remote') {
    warning.textContent = 'Shared API detected. Competition-critical inference must run on the local Radeon runtime.';
    warning.hidden = false;
  } else if (view.tone === 'warning') {
    warning.textContent = 'The model endpoint is local, but Radeon and ROCm runtime evidence has not been verified.';
    warning.hidden = false;
  } else {
    warning.hidden = true;
  }
}

function setIncidentFields(incident) {
  if (!incident) return;
  $('#incident-title').textContent = incident.title || 'Untitled incident';
  $('#service').textContent = incident.service || 'Unknown service';
  $('#severity').textContent = incident.severity || 'UNSET';
  $('#summary').value = incident.summary || '';
  $('#evidence').value = JSON.stringify(list(incident.evidence), null, 2);
}

function currentIncident() {
  if (!state.sample) throw new Error('Sample incident is not available yet.');
  const evidence = JSON.parse($('#evidence').value);
  if (!Array.isArray(evidence)) throw new Error('Initial signals must be a JSON array.');
  return {
    ...state.sample,
    summary: $('#summary').value.trim(),
    evidence,
  };
}

function canRunNext() {
  const investigation = state.investigation;
  if (!investigation || TERMINAL_STATES.has(investigation.status)) return false;
  return list(investigation.plan).some((step) => ['pending', 'running'].includes(step.status));
}

function canMessage() {
  return Boolean(state.investigation && ACTIVE_MESSAGE_STATES.has(state.investigation.status));
}

function evidenceButton(id) {
  const safeId = escapeHtml(id);
  return `<button class="citation" type="button" data-evidence-id="${safeId}">${safeId}</button>`;
}

function renderEvidence(investigation) {
  const evidence = list(investigation?.evidence).length
    ? list(investigation.evidence)
    : list(investigation?.incident?.evidence);
  $('#evidence-count').textContent = `${evidence.length} signals`;
  $('#evidence-source-count').textContent = `${evidence.length} ITEMS`;
  const ledger = $('#evidence-ledger');
  if (!evidence.length) {
    ledger.className = 'evidence-ledger empty-state';
    ledger.textContent = 'No evidence collected.';
    return;
  }
  ledger.className = 'evidence-ledger';
  ledger.innerHTML = evidence.map((item) => `
    <article class="evidence-item" id="evidence-${escapeHtml(item.id)}" tabindex="-1">
      <div class="evidence-meta">
        <strong>${escapeHtml(item.id)}</strong>
        <span>${escapeHtml(item.source || item.source_label || 'unknown')}</span>
        <time>${escapeHtml(formatTime(item.timestamp))}</time>
      </div>
      <p>${escapeHtml(item.content || item.summary || JSON.stringify(item.value ?? item))}</p>
    </article>
  `).join('');
}

function renderPlan(investigation) {
  const steps = list(investigation?.plan);
  const complete = steps.filter((step) => ['completed', 'failed', 'skipped'].includes(step.status)).length;
  $('#progress').textContent = `${complete} / ${steps.length || 4} steps`;
  const plan = $('#plan');
  if (!steps.length) {
    plan.className = 'plan empty-state';
    plan.textContent = 'The investigation plan will appear here.';
    return;
  }
  plan.className = 'plan';
  plan.innerHTML = steps.map((step, index) => {
    const status = normalizeStatus(step.status);
    const tool = step.tool ? `<span class="tool-name">${escapeHtml(step.tool)}</span>` : '<span class="tool-name">Synthesis</span>';
    return `
      <article class="plan-step ${status}">
        <span class="step-index" aria-hidden="true">${index + 1}</span>
        <div><div class="step-line"><strong>${escapeHtml(step.goal || step.title || `Step ${index + 1}`)}</strong><span class="step-status">${escapeHtml(humanize(status))}</span></div>${tool}</div>
      </article>`;
  }).join('');
}

function renderTrace(investigation) {
  const events = list(investigation?.trace);
  $('#trace-count').textContent = `${events.length} EVENTS`;
  const trace = $('#trace');
  if (!events.length) {
    trace.className = 'trace empty-state';
    trace.textContent = 'No tools have run.';
    return;
  }
  trace.className = 'trace';
  trace.innerHTML = events.map((event) => {
    const argumentsText = event.arguments && Object.keys(event.arguments).length
      ? `<code>${escapeHtml(JSON.stringify(event.arguments))}</code>` : '';
    const evidence = list(event.evidence_ids).map(evidenceButton).join('');
    const duration = Number.isFinite(event.duration_ms) ? `${event.duration_ms} ms` : '';
    return `
      <article class="trace-event ${normalizeStatus(event.status)}">
        <div class="trace-meta"><span>${escapeHtml(humanize(event.kind))}</span><time>${escapeHtml(formatTime(event.timestamp))}</time><span>${escapeHtml(duration)}</span></div>
        <strong>${escapeHtml(event.tool || event.summary || event.step_id || 'Agent event')}</strong>
        ${event.tool && event.summary ? `<p>${escapeHtml(event.summary)}</p>` : ''}
        ${argumentsText}
        ${event.error ? `<p class="inline-error">${escapeHtml(event.error)}</p>` : ''}
        ${evidence ? `<div class="citation-row">${evidence}</div>` : ''}
      </article>`;
  }).join('');
}

function renderHypotheses(investigation) {
  const hypotheses = list(investigation?.hypotheses);
  $('#hypothesis-count').textContent = String(hypotheses.length);
  const container = $('#hypotheses');
  if (!hypotheses.length) {
    container.className = 'hypotheses empty-state';
    container.textContent = 'No hypotheses yet.';
    return;
  }
  container.className = 'hypotheses';
  container.innerHTML = hypotheses.map((item) => {
    const confidence = Number(item.confidence);
    const confidenceLabel = Number.isFinite(confidence) ? `${Math.round(confidence * 100)}%` : 'PROVISIONAL';
    return `
      <article class="hypothesis">
        <div class="item-head"><strong>${escapeHtml(item.title)}</strong><span class="confidence">${escapeHtml(confidenceLabel)}</span></div>
        <p>${escapeHtml(item.rationale || item.reason)}</p>
        <div class="citation-row">${list(item.evidence_ids).map(evidenceButton).join('')}</div>
      </article>`;
  }).join('');
}

function renderActions(investigation) {
  const actions = list(investigation?.proposed_actions);
  const container = $('#actions');
  if (!actions.length) {
    container.className = 'actions empty-state';
    container.textContent = 'No proposed actions yet.';
    return;
  }
  container.className = 'actions';
  container.innerHTML = actions.map((item) => {
    const decision = item.approval_status || item.decision || 'pending';
    const decided = decision !== 'pending';
    return `
      <article class="action-item ${normalizeStatus(decision)}">
        <div class="item-head"><strong>${escapeHtml(item.priority || 'P?')} · ${escapeHtml(item.action)}</strong><span class="decision-status">${escapeHtml(humanize(decision))}</span></div>
        <p>${escapeHtml(item.reason || '')}</p>
        <p class="safety"><strong>Safety:</strong> ${escapeHtml(item.safety)}</p>
        ${item.command_preview ? `<pre aria-label="Command preview"><code>${escapeHtml(item.command_preview)}</code></pre>` : ''}
        <div class="decision-buttons">
          <button class="approve" type="button" data-decision="approved" data-locked="${decided}" data-action-id="${escapeHtml(item.id)}" ${decided ? 'disabled' : ''}>Approve dry-run</button>
          <button class="reject" type="button" data-decision="rejected" data-locked="${decided}" data-action-id="${escapeHtml(item.id)}" ${decided ? 'disabled' : ''}>Reject</button>
        </div>
      </article>`;
  }).join('');
}

function renderMessages(investigation) {
  const messages = list(investigation?.messages);
  const container = $('#messages');
  if (!messages.length) {
    container.className = 'messages empty-state';
    container.textContent = canMessage() ? 'Ask a cited follow-up using this session.' : 'Follow-up becomes available after synthesis.';
    return;
  }
  container.className = 'messages';
  container.innerHTML = messages.map((message) => `
    <article class="message ${normalizeStatus(message.role)}">
      <div class="message-meta"><strong>${escapeHtml(message.role === 'user' ? 'Operator' : 'Commander')}</strong><time>${escapeHtml(formatTime(message.timestamp))}</time></div>
      <p>${escapeHtml(message.content)}</p>
      <div class="citation-row">${list(message.evidence_ids).map(evidenceButton).join('')}</div>
    </article>`).join('');
  container.scrollTop = container.scrollHeight;
}

function renderAudit(investigation) {
  const auditEvents = list(investigation?.audit).length ? list(investigation.audit) : list(investigation?.trace);
  $('#session-version').textContent = `VERSION ${investigation?.version || 0}`;
  const container = $('#audit');
  if (!auditEvents.length) {
    container.className = 'audit empty-state';
    container.textContent = 'Session changes and operator decisions will appear here.';
    return;
  }
  container.className = 'audit';
  container.innerHTML = auditEvents.map((event) => `
    <div class="audit-row">
      <time>${escapeHtml(formatTime(event.timestamp))}</time>
      <strong>${escapeHtml(humanize(event.kind || event.event || event.status))}</strong>
      <span>${escapeHtml(event.summary || event.decision || event.request_id || '')}</span>
    </div>`).join('');
}

function renderInvestigation() {
  const investigation = state.investigation;
  const incident = investigation?.incident || state.sample;
  if (incident) setIncidentFields(incident);

  const status = normalizeStatus(investigation?.status || 'not-started');
  $('#investigation-status').className = `status-badge ${status}`;
  $('#investigation-status').textContent = investigation ? humanize(status) : 'Not started';
  $('#incident-editor').classList.toggle('locked', Boolean(investigation));
  $('#summary').disabled = Boolean(investigation);
  $('#evidence').disabled = Boolean(investigation);
  $('#create-button').hidden = Boolean(investigation);
  $('#degraded-warning').hidden = status !== 'degraded' && !investigation?.runtime?.degraded;

  renderRuntime();
  renderEvidence(investigation || { incident });
  renderPlan(investigation);
  renderTrace(investigation);
  renderHypotheses(investigation);
  renderActions(investigation);
  renderMessages(investigation);
  renderAudit(investigation);

  const brief = investigation?.executive_summary || investigation?.brief || investigation?.report?.executive_summary;
  $('#brief').textContent = brief || 'Complete the bounded plan to synthesize an evidence-backed incident brief.';

  const pendingStep = list(investigation?.plan).find((step) => step.status === 'pending');
  $('#next-button span').textContent = pendingStep ? `Run step ${pendingStep.order || list(investigation.plan).indexOf(pendingStep) + 1}` : 'Plan complete';
  setBusy(state.busy);
}

function storeInvestigation(investigation) {
  state.investigation = investigation;
  if (investigation?.id) localStorage.setItem('lic-investigation-id', investigation.id);
  renderInvestigation();
}

async function loadSample() {
  clearError();
  const sample = await api('/api/sample', { headers: {} });
  state.sample = sample;
  if (!state.investigation) renderInvestigation();
}

async function loadRuntime() {
  state.health = await api('/api/health', { headers: {} });
  renderRuntime();
}

async function restoreInvestigation() {
  const id = localStorage.getItem('lic-investigation-id');
  if (!id) return;
  try {
    const payload = await api(`/api/investigations/${encodeURIComponent(id)}`, { headers: {} });
    storeInvestigation(unwrapInvestigation(payload));
  } catch (error) {
    localStorage.removeItem('lic-investigation-id');
    if (error.code !== 'not_found' && error.code !== 'investigation_not_found') showError(error);
  }
}

async function createInvestigation() {
  clearError();
  setBusy(true);
  $('#create-button span').textContent = 'Creating investigation...';
  try {
    const payload = await api('/api/investigations', {
      method: 'POST',
      body: JSON.stringify({ request_id: requestId('create'), incident: currentIncident() }),
    });
    storeInvestigation(unwrapInvestigation(payload));
  } catch (error) {
    showError(error);
  } finally {
    $('#create-button span').textContent = 'Create investigation';
    setBusy(false);
  }
}

async function runNextStep() {
  if (!canRunNext()) return;
  clearError();
  setBusy(true);
  $('#next-button span').textContent = 'Agent is investigating...';
  try {
    const investigation = state.investigation;
    const payload = await api(`/api/investigations/${encodeURIComponent(investigation.id)}/next`, {
      method: 'POST',
      body: JSON.stringify({ request_id: requestId('next'), expected_version: investigation.version }),
    });
    storeInvestigation(unwrapInvestigation(payload));
  } catch (error) {
    showError(error);
  } finally {
    setBusy(false);
    renderInvestigation();
  }
}

async function decideAction(actionId, decision) {
  clearError();
  setBusy(true);
  try {
    const investigation = state.investigation;
    const payload = await api(`/api/investigations/${encodeURIComponent(investigation.id)}/actions/${encodeURIComponent(actionId)}/decision`, {
      method: 'POST',
      body: JSON.stringify({ request_id: requestId('decision'), expected_version: investigation.version, decision }),
    });
    storeInvestigation(unwrapInvestigation(payload));
  } catch (error) {
    showError(error);
  } finally {
    setBusy(false);
  }
}

async function sendMessage(event) {
  event.preventDefault();
  const input = $('#message-input');
  const content = input.value.trim();
  if (!content || !canMessage()) return;
  clearError();
  setBusy(true);
  try {
    const investigation = state.investigation;
    const payload = await api(`/api/investigations/${encodeURIComponent(investigation.id)}/messages`, {
      method: 'POST',
      body: JSON.stringify({ request_id: requestId('message'), expected_version: investigation.version, content }),
    });
    input.value = '';
    storeInvestigation(unwrapInvestigation(payload));
  } catch (error) {
    showError(error);
  } finally {
    setBusy(false);
  }
}

function focusEvidence(id) {
  const target = document.getElementById(`evidence-${id}`);
  if (!target) return;
  document.querySelectorAll('.evidence-item.highlight').forEach((item) => item.classList.remove('highlight'));
  target.classList.add('highlight');
  target.scrollIntoView({ behavior: 'smooth', block: 'center' });
  target.focus({ preventScroll: true });
  window.setTimeout(() => target.classList.remove('highlight'), 2200);
}

function resetWorkspace() {
  state.investigation = null;
  localStorage.removeItem('lic-investigation-id');
  clearError();
  renderInvestigation();
  $('#summary').focus();
}

$('#sample-button').addEventListener('click', () => {
  if (state.sample && !state.investigation) {
    setIncidentFields(state.sample);
    renderEvidence({ incident: state.sample });
    clearError();
  }
});
$('#create-button').addEventListener('click', createInvestigation);
$('#next-button').addEventListener('click', runNextStep);
$('#new-button').addEventListener('click', resetWorkspace);
$('#message-form').addEventListener('submit', sendMessage);
document.addEventListener('click', (event) => {
  const citation = event.target.closest('[data-evidence-id]');
  if (citation) focusEvidence(citation.dataset.evidenceId);
  const decision = event.target.closest('[data-decision]');
  if (decision && !decision.disabled) decideAction(decision.dataset.actionId, decision.dataset.decision);
});

Promise.all([loadRuntime(), loadSample()])
  .then(restoreInvestigation)
  .catch((error) => {
    showError(error);
    $('#runtime-label').textContent = 'Runtime unavailable';
    $('#runtime-dot').className = 'dot fallback';
  });
