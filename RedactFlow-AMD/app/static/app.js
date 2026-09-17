const state = { plan: null, result: null };

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

function toast(message) {
  const node = $('#toast');
  node.textContent = message;
  node.classList.add('show');
  window.setTimeout(() => node.classList.remove('show'), 2200);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.detail || 'Request failed');
  return payload;
}

async function refreshHealth() {
  const status = $('#systemStatus');
  try {
    const health = await api('/health');
    status.className = 'status ready';
    status.querySelector('span').textContent = `${health.privacy_mode} / ${health.llm_backend}`;
  } catch {
    status.className = 'status error';
    status.querySelector('span').textContent = 'local runtime unavailable';
  }
}

async function refreshDocuments() {
  const documents = await api('/api/documents');
  const list = $('#documentList');
  list.innerHTML = documents.length ? documents.map((doc) => `
    <div class="document-item">
      <strong title="${escapeHtml(doc.name)}">${escapeHtml(doc.name)}</strong>
      <span>${doc.characters.toLocaleString()} chars</span>
      <span>${doc.id}</span>
    </div>`).join('') : '<p class="empty-copy">The vault is empty.</p>';
}

function escapeHtml(value) {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

async function addDocument(name, content) {
  await api('/api/documents', { method: 'POST', body: JSON.stringify({ name, content }) });
  await refreshDocuments();
  toast('Document added to the local vault');
}

$('#addDocument').addEventListener('click', async () => {
  const button = $('#addDocument');
  button.disabled = true;
  try {
    await addDocument($('#documentName').value.trim(), $('#documentContent').value.trim());
  } catch (error) {
    toast(error.message);
  } finally {
    button.disabled = false;
  }
});

$('#fileInput').addEventListener('change', async (event) => {
  for (const file of event.target.files) {
    const content = await file.text();
    await addDocument(file.name, content);
  }
  event.target.value = '';
});

$('#loadDemo').addEventListener('click', () => {
  $('#documentName').value = 'vendor-release-note.txt';
  $('#taskInput').value = 'Prepare a safe public release copy. Ground the decision in the local source, identify sensitive values, redact them, and preserve an audit memory without storing raw secrets.';
  toast('Demo task loaded');
});

$('#createPlan').addEventListener('click', async () => {
  const button = $('#createPlan');
  button.disabled = true;
  try {
    state.plan = await api('/api/plans', {
      method: 'POST',
      body: JSON.stringify({ task: $('#taskInput').value.trim() }),
    });
    renderPlan();
    $('#approvalSection').hidden = false;
    $('#resultSection').hidden = true;
    toast('Auditable plan created');
  } catch (error) {
    toast(error.message);
  } finally {
    button.disabled = false;
  }
});

function renderPlan() {
  $('#planState').textContent = state.plan.status;
  $('#planList').innerHTML = state.plan.steps.map((step, index) => `
    <li class="plan-step">
      <span class="step-index">${String(index + 1).padStart(2, '0')}</span>
      <div class="step-copy">
        <strong>${escapeHtml(step.title)}</strong>
        <p>${escapeHtml(step.description)}</p>
      </div>
      <span class="permission-badge ${step.permission}">${step.permission}</span>
    </li>`).join('');

  const controlled = state.plan.steps.filter((step) => step.requires_approval);
  $('#permissionList').innerHTML = controlled.map((step) => `
    <div class="permission-control">
      <div><strong>${escapeHtml(step.tool)}</strong><span>${escapeHtml(step.description)}</span></div>
      <label class="switch">
        <input type="checkbox" value="${escapeHtml(step.tool)}">
        <i></i>
      </label>
    </div>`).join('');
}

$('#executePlan').addEventListener('click', async () => {
  const approvedTools = $$('#permissionList input:checked').map((input) => input.value);
  const button = $('#executePlan');
  button.disabled = true;
  try {
    state.result = await api('/api/execute', {
      method: 'POST',
      body: JSON.stringify({ plan_id: state.plan.id, approved_tools: approvedTools }),
    });
    renderResult();
    await refreshMemories();
  } catch (error) {
    toast(error.message);
  } finally {
    button.disabled = false;
  }
});

function renderResult() {
  const result = state.result;
  $('#resultSection').hidden = false;
  $('#resultStatus').textContent = result.status;
  $('#resultSummary').textContent = result.summary;
  $('#releaseFiles').innerHTML = Object.entries(result.redacted_documents).map(([name, content], index) => `
    <article class="release-file">
      <header><strong>${escapeHtml(name)}</strong><button data-download="${index}">DOWNLOAD TXT</button></header>
      <pre>${escapeHtml(content)}</pre>
    </article>`).join('') || '<p class="empty-copy">Approve both controlled actions to create release copies.</p>';

  $$('[data-download]').forEach((button) => button.addEventListener('click', () => {
    const [name, content] = Object.entries(result.redacted_documents)[Number(button.dataset.download)];
    const link = document.createElement('a');
    link.href = URL.createObjectURL(new Blob([content], { type: 'text/plain' }));
    link.download = `redacted-${name}`;
    link.click();
    URL.revokeObjectURL(link.href);
  }));

  $('#evidencePane').innerHTML = result.evidence.length ? result.evidence.map((hit) => `
    <article class="evidence-hit">
      <header><strong>${escapeHtml(hit.name)}</strong><span>${hit.score.toFixed(3)}</span></header>
      <blockquote>${escapeHtml(hit.excerpt)}</blockquote>
    </article>`).join('') : '<p class="empty-copy">No lexical match for this task.</p>';
  $('#findingsPane').innerHTML = result.findings.length ? result.findings.map((finding) => `
    <article class="finding">
      <header><strong>${escapeHtml(finding.kind)}</strong><span>${finding.start}:${finding.end}</span></header>
      <code>${escapeHtml(finding.value)}</code>
      <p>Replacement: ${escapeHtml(finding.replacement)}</p>
    </article>`).join('') : '<p class="empty-copy">No sensitive values detected.</p>';
  toast(result.status === 'completed' ? 'Release package prepared locally' : 'Execution paused at the permission boundary');
}

async function refreshMemories() {
  const memories = await api('/api/memories');
  $('#memoryPane').innerHTML = memories.length ? memories.map((memory) => `
    <article class="memory">
      <header><strong>${escapeHtml(memory.kind)}</strong><span>${escapeHtml(memory.created_at)}</span></header>
      <p>${escapeHtml(JSON.stringify(memory.payload))}</p>
    </article>`).join('') : '<p class="empty-copy">No local audit memories yet.</p>';
}

$$('.tab').forEach((button) => button.addEventListener('click', () => {
  $$('.tab').forEach((tab) => tab.classList.toggle('active', tab === button));
  $$('.tab-pane').forEach((pane) => pane.classList.toggle('active', pane.id === button.dataset.tab));
}));

refreshHealth();
refreshDocuments();
refreshMemories();

