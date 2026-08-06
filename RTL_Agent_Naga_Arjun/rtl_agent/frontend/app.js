/**
 * app.js — RTL Verification Agent v2 Frontend
 *
 * New in v2:
 *  • Two-tier verification: Tier 1 (lint) + Tier 2 (functional simulation)
 *  • Handles new SSE events: lint_iteration, testbench_generated,
 *    sim_iteration, sim_build_error, final_result
 *  • Global iteration progress bar across both tiers
 *  • Functional verification panel with per-iteration sim cards
 *  • Testbench viewer (collapsible) with copy/download
 *  • PASS / FAIL / PARTIAL result badges
 *  • Telemetry display (elapsed ms, tokens/sec) from Amendment 8
 */

'use strict';

// ─── State ───────────────────────────────────────────────────────────────────
const state = {
  currentSession: null,
  sseSource: null,
  streamingEl: null,
  iterations: [],         // DUT code versions [{code, filename, lines, iteration, status}]
  activeIterTab: 0,
  config: null,
  tbCode: null,           // current testbench code
  tbFilename: null,       // testbench .sv filename
  simIterations: [],      // [{iteration, passed, stdout, stderr, phase}]
  simRuns: [],            // [{iteration, passed, stdout, stderr, phase, log_file_path, vcd_file_path, vcd_data, vcd_size_bytes, error_summary, elapsed_ms}]
  activeSimRunIndex: -1,
  totalIterations: 0,
  maxTotal: 6,
  vcdData: null,
};

// ─── DOM refs ─────────────────────────────────────────────────────────────────
const $ = id => document.getElementById(id);
const specInput      = $('spec-input');
const runBtn         = $('run-btn');
const feedEl         = $('feed');
const feedEmptyEl    = $('feed-empty');
const historyEl      = $('history-list');
const codeViewer     = $('code-viewer');
const codePlaceholder = $('code-placeholder');
const iterTabs       = $('iter-tabs');
const veriStatusBar  = $('veri-status-bar');
const codeActionBar  = $('code-action-bar');
const toastContainer = $('toast-container');
const modeBadge      = $('mode-badge');
const copyBtn        = $('copy-btn');
const downloadBtn    = $('download-btn');
const linesEl        = $('code-lines');
const tier1Pill      = $('tier1-pill');
const tier2Pill      = $('tier2-pill');
const badgeTier1     = $('badge-tier1');
const badgeTier2     = $('badge-tier2');
const globalIterBar  = $('global-iter-bar');
const globalIterLabel = $('global-iter-label');
const simIterationsEl = $('sim-iterations');
const tbSection      = $('tb-section');
const tbViewer       = $('tb-viewer');
const simEmptyState  = $('sim-empty-state');

// ─── Init ─────────────────────────────────────────────────────────────────────
async function init() {
  await loadConfig();
  await loadHistory();

  runBtn.addEventListener('click', handleRun);
  specInput.addEventListener('keydown', e => {
    if (e.ctrlKey && e.key === 'Enter') handleRun();
  });

  copyBtn.addEventListener('click', handleCopy);
  downloadBtn.addEventListener('click', handleDownload);

  document.querySelectorAll('.example-chip').forEach(chip => {
    chip.addEventListener('click', () => {
      specInput.value = chip.dataset.spec;
      specInput.focus();
    });
  });
}

// ─── Config ──────────────────────────────────────────────────────────────────
async function loadConfig() {
  try {
    const res = await fetch('/api/config');
    state.config = await res.json();
    state.maxTotal = state.config.max_total_iterations || 6;
    
    const model = state.config.model || 'Qwen2.5-Coder-7B';
    const shortModel = model.split('/').pop().replace('-Instruct', '');
    const dm = state.config.deploy_mode || (state.config.mock_mode ? 'mock' : 'vllm');
    const isMock = (dm === 'mock' || state.config.mock_mode);

    const modelBadgeText = $('model-badge-text');
    if (modelBadgeText) {
      modelBadgeText.textContent = `${shortModel}`;
    }

    if (modeBadge) {
      if (isMock) {
        modeBadge.textContent = `MOCK MODE · ${shortModel}`;
        modeBadge.className   = 'mode-badge mock';
      } else if (dm === 'deepseek') {
        modeBadge.textContent = `LIVE · DeepSeek (${shortModel})`;
        modeBadge.className   = 'mode-badge real';
      } else if (dm === 'vllm') {
        modeBadge.textContent = `LIVE · AMD ROCm (${shortModel})`;
        modeBadge.className   = 'mode-badge real';
      } else {
        modeBadge.textContent = `LIVE · ${shortModel}`;
        modeBadge.className   = 'mode-badge real';
      }
    }
  } catch (_) {}
}

// ─── Run Handler ──────────────────────────────────────────────────────────────
async function handleRun() {
  const spec = specInput.value.trim();
  if (!spec) {
    toast('Please enter a hardware specification.', 'error');
    specInput.focus();
    return;
  }
  if (spec.length < 5) {
    toast('Specification is too short. Please enter more than 5 characters.', 'warning');
    specInput.focus();
    return;
  }
  if (state.sseSource) {
    state.sseSource.close();
    state.sseSource = null;
  }

  // Reset all state
  clearFeed();
  clearCodeViewer();
  clearFunctionalPanel();
  clearWaveformsAndTelemetry();
  resetAgentPipeline();
  state.iterations = [];
  state.currentSession = null;
  state.streamingEl = null;
  state.tbCode = null;
  state.tbFilename = null;
  state.simIterations = [];
  state.totalIterations = 0;

  setRunning(true);

  let sessionId;
  try {
    const res = await fetch('/api/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ spec }),
    });
    if (!res.ok) throw new Error(`Server returned ${res.status}`);
    const data = await res.json();
    sessionId = data.session_id;
    state.currentSession = sessionId;
  } catch (err) {
    toast(`Failed to start agent: ${err.message}`, 'error');
    setRunning(false);
    return;
  }

  connectSSE(sessionId);
}

// ─── SSE Connection ───────────────────────────────────────────────────────────
function connectSSE(sessionId) {
  const es = new EventSource(`/api/stream/${sessionId}`);
  state.sseSource = es;

  es.onmessage = e => {
    try {
      const event = JSON.parse(e.data);
      handleEvent(event);
    } catch (_) {}
  };

  es.onerror = () => {
    if (es.readyState === EventSource.CLOSED) return;
    es.close();
    setRunning(false);
  };
}

// ─── Event Dispatcher ─────────────────────────────────────────────────────────
function handleEvent(ev) {
  // Update global total iteration counter in every relevant event
  if (ev.total_iterations !== undefined) {
    state.totalIterations = ev.total_iterations;
    updateGlobalBar(ev.total_iterations, ev.max_total || state.maxTotal);
  }

  switch (ev.type) {
    case 'connected':
      break;

    case 'agent_status':
      updateAgentPipeline(ev.agent, ev.status);
      addFeedEvent('agent', '🤖', `[Agent] ${ev.agent}`, ev.status, 'thought');
      break;

    case 'agent_start':
      state.maxTotal = ev.max_total_iterations || 6;
      addFeedEvent('iteration', '🚀', 'AGENT STARTED',
        `Model: ${ev.model} · Lint≤${ev.max_lint_iterations} · Sim≤${ev.max_functional_iterations} · Total≤${ev.max_total_iterations}`,
        'iteration');
      initGlobalBar(ev.max_total_iterations);
      setTierBadge('tier1', 'running');
      break;

    case 'lint_iteration':
      if (ev.phase === 'tier1_lint') {
        addIterDivider(`Lint Iter ${ev.iteration} · Total ${ev.total_iterations}/${ev.max_total}`);
      } else if (ev.phase === 'tier1_lint_result') {
        // handled by tool_result below
      } else if (ev.phase === 'tier2_relint') {
        addFeedEvent('tool', '🔄', 'RE-LINT (Tier 2 fix)',
          ev.passed ? 'Re-lint passed — proceeding to re-simulation' : 'Re-lint FAILED after functional fix',
          ev.passed ? 'success' : 'error');
      }
      break;

    case 'thought':
      addFeedEvent('thought', '🧠', 'THINKING', ev.message, 'thought');
      break;

    case 'telemetry_update': {
      if (ev.ttft_ms > 0) {
        const ttftEl = $('stat-ttft');
        if (ttftEl) ttftEl.textContent = `${ev.ttft_ms} ms`;
      }
      if (ev.tokens_per_sec > 0) {
        const tpsEl = $('stat-tps');
        if (tpsEl) tpsEl.textContent = `${ev.tokens_per_sec}`;
      }
      if (ev.total_tokens > 0) {
        const tokEl = $('stat-tokens');
        if (tokEl) tokEl.textContent = `${ev.total_tokens.toLocaleString()}`;
      }
      if (ev.elapsed_sec > 0) {
        const elEl = $('stat-elapsed');
        if (elEl) elEl.textContent = `${ev.elapsed_sec}s`;
      }
      break;
    }

    case 'waveform_ready': {
      state.vcdData = ev.vcd_data;
      registerSimRun({
        iteration: ev.iteration || state.simRuns.length || 1,
        passed: ev.passed !== undefined ? ev.passed : true,
        vcd_data: ev.vcd_data,
        vcd_size_bytes: ev.vcd_size_bytes,
        vcd_file_path: ev.vcd_file_path,
        log_file_path: ev.log_file_path,
      });
      break;
    }

    case 'waveform_warning': {
      const badge = $('vcd-size-badge');
      if (badge) badge.textContent = 'VCD truncated';
      toast(ev.message, 'warning');
      break;
    }

    case 'llm_start':
      startLLMStream();
      break;

    case 'llm_token':
      appendLLMToken(ev.token);
      break;

    case 'llm_done':
      endLLMStream(ev.elapsed_ms, ev.tokens_generated, ev.ttft_ms, ev.tokens_per_sec);
      break;

    case 'code_generated': {
      const tier = ev.tier || 'tier1';
      const idx = state.iterations.length;
      state.iterations.push({
        code: ev.code,
        filename: ev.filename,
        lines: ev.lines,
        iteration: ev.iteration || ev.total_iterations,
        status: 'pending',
        tier,
      });
      addIterTab(ev.iteration || ev.total_iterations, 'pending', tier);
      showCodeVersion(idx);
      const telemetry = ev.elapsed_ms
        ? ` · ${(ev.elapsed_ms / 1000).toFixed(1)}s · ${ev.tokens_generated || '?'} tokens`
        : '';
      addFeedEvent('code', '📄', 'RTL GENERATED',
        `${tier === 'tier2_correction' ? '[Tier 2 fix] ' : ''}SystemVerilog extracted · ${ev.lines} lines · ${ev.filename}${telemetry}`,
        'code');
      break;
    }

    case 'tool_call':
      setVeriStatus('running');
      addFeedEvent('tool', '⚙️', 'TOOL CALL',
        `Executing: verilator --lint-only --Wall --timing ${ev.file}`,
        'tool');
      break;

    case 'tool_result': {
      const lastIdx = state.iterations.length - 1;
      if (ev.success) {
        setVeriStatus('pass');
        setTierPill('tier1', 'pass');
        if (lastIdx >= 0) state.iterations[lastIdx].status = 'clean';
        updateIterTabStatus(lastIdx, 'clean');
        const feedEl2 = addFeedEvent('tool', '✅', 'VERILATOR PASS', '', 'success');
        addVeriOutput(feedEl2, ev.stdout || '0 errors, 0 warnings', true);
      } else {
        setVeriStatus('fail');
        if (lastIdx >= 0) state.iterations[lastIdx].status = 'error';
        updateIterTabStatus(lastIdx, 'error');
        const feedEl2 = addFeedEvent('tool', '⚠️', 'VERILATOR ERRORS', '', 'error');
        addVeriOutput(feedEl2, ev.stderr || ev.stdout || 'Unknown error', false);
        codeViewer.classList.add('shake');
        setTimeout(() => codeViewer.classList.remove('shake'), 500);
      }
      break;
    }

    // ── v2 Tier 2 events ──────────────────────────────────────────────────
    case 'testbench_generated': {
      state.tbCode = ev.code;
      state.tbFilename = ev.filename;
      renderTestbench(ev.code, ev.filename);
      setTierBadge('tier2', 'running');
      setTierPill('tier2', 'running');
      const tbTelemetry = ev.elapsed_ms
        ? ` · ${(ev.elapsed_ms / 1000).toFixed(1)}s · ${ev.tokens_generated || '?'} tokens`
        : '';
      addFeedEvent('code', '🧪', 'TESTBENCH GENERATED',
        `Self-checking testbench written · ${ev.filename}${tbTelemetry}`,
        'code');
      break;
    }

    case 'sim_build_error': {
      // Amendment 2: structural bug in --binary compile — distinct event
      registerSimRun({
        iteration: ev.iteration,
        passed: false,
        phase: 'build',
        stdout: ev.sim_stdout,
        stderr: ev.sim_stderr,
        timed_out: ev.timed_out,
        elapsed_ms: ev.elapsed_ms,
        log_file_path: ev.log_file_path,
        vcd_file_path: ev.vcd_file_path,
        error_summary: ev.error_summary,
      });
      addSimIterCard({
        iteration: ev.iteration,
        passed: false,
        phase: 'build',
        stdout: ev.sim_stdout,
        stderr: ev.sim_stderr,
        timed_out: ev.timed_out,
        elapsed_ms: ev.elapsed_ms,
        label: '🔨 BUILD ERROR (structural)',
        log_file_path: ev.log_file_path,
      });
      addFeedEvent('error', '🔨', 'SIM BUILD FAILED',
        `verilator --binary compile error (structural bug). Routing to Tier 1 correction.\n${(ev.sim_stderr || '').slice(0, 160)}`,
        'error');
      break;
    }

    case 'sim_iteration': {
      state.simIterations.push(ev);
      registerSimRun({
        iteration: ev.iteration,
        passed: ev.passed,
        phase: ev.phase || 'run',
        stdout: ev.sim_stdout,
        stderr: ev.sim_stderr,
        timed_out: ev.timed_out,
        elapsed_ms: ev.elapsed_ms,
        log_file_path: ev.log_file_path,
        vcd_file_path: ev.vcd_file_path,
        error_summary: ev.error_summary,
      });
      addSimIterCard({
        iteration: ev.iteration,
        passed: ev.passed,
        phase: ev.phase || 'run',
        stdout: ev.sim_stdout,
        stderr: ev.sim_stderr,
        timed_out: ev.timed_out,
        elapsed_ms: ev.elapsed_ms,
        label: ev.passed ? '✅ SIMULATION PASS' : '❌ SIMULATION FAIL',
        log_file_path: ev.log_file_path,
      });
      if (ev.passed) {
        setTierPill('tier2', 'pass');
        setTierBadge('tier2', 'pass');
      } else {
        setTierPill('tier2', 'fail');
      }
      addFeedEvent(
        ev.passed ? 'success' : 'error',
        ev.passed ? '✅' : '❌',
        ev.passed ? 'SIMULATION PASS' : 'SIMULATION FAIL',
        ev.passed
          ? `Testbench reported: PASS: all checks passed · ${(ev.elapsed_ms / 1000).toFixed(2)}s`
          : `Testbench reported: ${(ev.sim_stdout || '').split('\n')[0].slice(0, 120)}`,
        ev.passed ? 'success' : 'error'
      );
      break;
    }

    case 'final_result': {
      const lintOk  = ev.lint_status === 'PASSED';
      const simOk   = ev.functional_status === 'PASSED';
      const bothOk  = lintOk && simOk;
      const partial = lintOk && !simOk && ev.functional_status !== 'NOT_RUN';

      setTierPill('tier1', lintOk ? 'pass' : 'fail');
      setTierBadge('tier1', lintOk ? 'pass' : 'fail');
      setTierPill('tier2', simOk ? 'pass' : (ev.functional_status === 'NOT_RUN' ? 'idle' : 'fail'));
      setTierBadge('tier2', simOk ? 'pass' : (ev.functional_status === 'NOT_RUN' ? 'idle' : 'fail'));

      const resultClass = bothOk ? 'success' : partial ? 'warning' : 'error';
      const resultIcon  = bothOk ? '🎉' : partial ? '⚠️' : '❌';
      const resultLabel = bothOk ? 'FULLY VERIFIED' : partial ? 'PARTIAL RESULT' : 'VERIFICATION FAILED';

      addFeedEvent(resultClass, resultIcon, resultLabel,
        `Lint: ${ev.lint_status} · Sim: ${ev.functional_status} · ${ev.total_iterations} total iteration(s)`,
        resultClass);

      if (bothOk) {
        toast(`✓ Both tiers PASSED in ${ev.total_iterations} iteration(s)! Download your .sv file.`, 'success');
      } else if (partial) {
        toast(`Lint passed but simulation failed after ${ev.total_iterations} iteration(s). Check sim log.`, 'error');
      } else {
        toast(`Verification failed after ${ev.total_iterations} iteration(s).`, 'error');
      }

      const lastIdx = state.iterations.length - 1;
      if (lastIdx >= 0) showCodeVersion(lastIdx);
      setRunning(false);
      loadHistory();
      break;
    }

    // ── Legacy v1 events (kept for backward compatibility) ────────────────
    case 'success': {
      setTierPill('tier1', 'pass');
      setTierBadge('tier1', 'pass');
      addFeedEvent('success', '🎉', 'DESIGN VERIFIED', ev.message, 'success');
      const lastIdx = state.iterations.length - 1;
      if (lastIdx >= 0) showCodeVersion(lastIdx);
      toast(`RTL verified in ${ev.iterations} iteration(s)!`, 'success');
      setRunning(false);
      loadHistory();
      break;
    }

    case 'error':
      addFeedEvent('error', '❌', 'ERROR', ev.message, 'error');
      toast(ev.message, 'error');
      setRunning(false);
      break;

    case 'max_iterations_reached':
      addFeedEvent('error', '🔄', 'MAX ITERATIONS REACHED', ev.message, 'error');
      toast(ev.message, 'error');
      setRunning(false);
      loadHistory();
      break;

    case 'stream_end':
      state.sseSource?.close();
      setRunning(false);
      break;
  }
}

// ─── Global Iteration Bar (Amendment 1) ───────────────────────────────────────
function initGlobalBar(maxTotal) {
  globalIterBar.innerHTML = '';
  for (let i = 1; i <= maxTotal; i++) {
    const pip = document.createElement('div');
    pip.className = 'global-pip';
    pip.id = `gpip-${i}`;
    globalIterBar.appendChild(pip);
  }
  if (globalIterLabel) globalIterLabel.textContent = `0 / ${maxTotal}`;
}

function updateGlobalBar(current, maxTotal) {
  for (let i = 1; i <= maxTotal; i++) {
    const pip = $(`gpip-${i}`);
    if (!pip) continue;
    pip.className = 'global-pip ' + (i < current ? 'done' : i === current ? 'active' : '');
  }
  if (globalIterLabel) globalIterLabel.textContent = `${current} / ${maxTotal}`;
}

// ─── Tier Badge & Pill ────────────────────────────────────────────────────────
function setTierBadge(tier, status) {
  const el = tier === 'tier1' ? badgeTier1 : badgeTier2;
  if (!el) return;
  el.className = `tier-badge ${status}`;
}

function setTierPill(tier, status) {
  const el = tier === 'tier1' ? tier1Pill : tier2Pill;
  if (!el) return;
  const labels = { idle: 'IDLE', running: 'RUNNING', pass: 'PASSED', fail: 'FAILED', warning: 'PARTIAL' };
  el.className = `tier-status-pill ${status}`;
  el.textContent = labels[status] || status.toUpperCase();
}

// ─── Multi-Agent Pipeline Tracker ───────────────────────────────────────────
function resetAgentPipeline() {
  const agents = ['architect', 'coder', 'verifier'];
  agents.forEach(a => {
    const pill = $(`agent-pill-${a}`);
    const sub = $(`status-sub-${a}`);
    if (pill) pill.className = 'agent-pill idle';
    if (sub) sub.textContent = 'Idle';
  });
}

function updateAgentPipeline(agent, status) {
  if (!agent) return;
  const key = agent.toLowerCase();
  const pill = $(`agent-pill-${key}`);
  const sub = $(`status-sub-${key}`);
  if (!pill) return;

  if (sub) sub.textContent = status;

  const s = (status || '').toLowerCase();
  if (status.includes('✓') || s.includes('clean') || s.includes('passed') || s.includes('complete')) {
    pill.className = 'agent-pill passed';
  } else if (status.includes('✗') || s.includes('failed')) {
    pill.className = 'agent-pill failed';
  } else {
    pill.className = 'agent-pill active';
  }
}

// ─── Functional Verification Panel ────────────────────────────────────────────
function clearFunctionalPanel() {
  if (simIterationsEl) simIterationsEl.innerHTML = '';
  if (simEmptyState) {
    simEmptyState.style.display = '';
    simIterationsEl?.appendChild(simEmptyState);
  }
  if (tbSection) tbSection.style.display = 'none';
  if (tbViewer) tbViewer.innerHTML = '';
  setTierPill('tier1', 'idle');
  setTierPill('tier2', 'idle');
  setTierBadge('tier1', 'idle');
  setTierBadge('tier2', 'idle');
  resetAgentPipeline();
}

function renderTestbench(code, filename) {
  if (!tbSection) return;
  if (simEmptyState) simEmptyState.style.display = 'none';
  tbSection.style.display = '';

  const copyTbBtn = $('copy-tb-btn');
  const downloadTbBtn = $('download-tb-btn');
  if (copyTbBtn) copyTbBtn.style.display = '';
  if (downloadTbBtn) {
    downloadTbBtn.style.display = '';
    downloadTbBtn.dataset.filename = filename || '';
    downloadTbBtn.dataset.sessionId = state.currentSession || '';
  }

  // Render syntax-highlighted testbench code
  if (tbViewer) {
    tbViewer.innerHTML = '';
    const pre = document.createElement('pre');
    const codeEl = document.createElement('code');
    codeEl.className = 'language-verilog';
    codeEl.textContent = code;
    pre.appendChild(codeEl);
    tbViewer.appendChild(pre);
    if (window.hljs) hljs.highlightElement(codeEl);
  }
}

function addSimIterCard({ iteration, passed, phase, stdout, stderr, timed_out, elapsed_ms, label, log_file_path }) {
  if (!simIterationsEl) return;
  if (simEmptyState) simEmptyState.style.display = 'none';

  const card = document.createElement('div');
  card.className = `sim-iter-card ${passed ? 'pass' : phase === 'build' ? 'build-error' : 'fail'}`;

  const badge = passed ? 'PASS' : phase === 'build' ? 'BUILD ERROR' : timed_out ? 'TIMEOUT' : 'FAIL';
  const badgeClass = passed ? 'pass' : 'fail';
  const elapsedStr = elapsed_ms ? ` · ${(elapsed_ms / 1000).toFixed(2)}s` : '';
  const cardIdx = state.simRuns.length - 1;

  const logText = ((stdout || '') + (stderr ? '\n' + stderr : '')).trim().slice(0, 400);

  card.innerHTML = `
    <div class="sim-card-header">
      <span class="sim-card-label">${escHtml(label || `Sim #${iteration}`)}</span>
      <div style="display:flex;gap:6px;align-items:center;">
        <span class="sim-badge ${badgeClass}">${badge}</span>
        <button class="btn-ghost" style="padding:1px 6px;font-size:9.5px;" onclick="openSimLogViewer(${cardIdx >= 0 ? cardIdx : 0})">📄 Log</button>
      </div>
      <span class="sim-elapsed">${escHtml(elapsedStr)}</span>
    </div>
    <pre class="sim-log ${passed ? 'pass' : 'fail'}">${escHtml(logText || '(no output)')}</pre>
  `;
  simIterationsEl.appendChild(card);
  card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

window.toggleTestbench = function() {
  if (!tbViewer) return;
  const visible = tbViewer.style.display !== 'none';
  tbViewer.style.display = visible ? 'none' : '';
  const btn = $('tb-toggle-btn');
  if (btn) btn.textContent = visible ? '📋 Show Testbench Code' : '📋 Hide Testbench Code';
};

window.copyTestbench = async function() {
  if (!state.tbCode) return;
  try {
    await navigator.clipboard.writeText(state.tbCode);
    toast('Testbench copied!', 'info');
  } catch (_) { toast('Copy failed.', 'error'); }
};

window.downloadTestbench = function() {
  const btn = $('download-tb-btn');
  if (!btn) return;
  const filename = btn.dataset.filename;
  const sessionId = btn.dataset.sessionId;
  if (!filename || !sessionId) return;
  const a = document.createElement('a');
  a.href = `/api/download/${sessionId}/${filename}`;
  a.download = filename;
  a.click();
};

// ─── Feed Rendering ───────────────────────────────────────────────────────────
function clearFeed() {
  feedEl.innerHTML = '';
  if (feedEmptyEl) feedEmptyEl.style.display = 'none';
}

function addFeedEvent(category, icon, label, message, cssClass) {
  if (feedEmptyEl) feedEmptyEl.style.display = 'none';

  const el = document.createElement('div');
  el.className = 'feed-event';
  el.innerHTML = `
    <div class="ev-icon ${cssClass}">${icon}</div>
    <div class="ev-body">
      <div class="ev-type-label ${cssClass}">${label}</div>
      <div class="ev-message ${cssClass === 'success' ? 'success' : cssClass === 'error' ? 'error' : ''}">${escHtml(message)}</div>
    </div>`;
  feedEl.appendChild(el);
  feedEl.parentElement.scrollTop = feedEl.parentElement.scrollHeight;
  return el;
}

function addVeriOutput(parentEl, text, pass) {
  const bodyEl = parentEl.querySelector('.ev-body');
  const pre = document.createElement('pre');
  pre.className = 'veri-output ' + (pass ? 'pass' : 'fail');
  pre.textContent = text;
  bodyEl.appendChild(pre);
}

function addIterDivider(label) {
  const el = document.createElement('div');
  el.className = 'iter-divider';
  el.textContent = label;
  feedEl.appendChild(el);
}

// LLM Token Streaming
function startLLMStream() {
  if (feedEmptyEl) feedEmptyEl.style.display = 'none';

  const el = document.createElement('div');
  el.className = 'feed-event';
  el.innerHTML = `
    <div class="ev-icon llm">🤖</div>
    <div class="ev-body">
      <div class="ev-type-label llm">LLM GENERATING</div>
      <div class="ev-message" id="llm-stream-text" style="font-family:var(--font-code);font-size:11px;color:var(--text-muted);max-height:200px;overflow:hidden;display:-webkit-box;-webkit-line-clamp:8;-webkit-box-orient:vertical;"></div>
    </div>`;
  feedEl.appendChild(el);
  state.streamingEl = el.querySelector('#llm-stream-text');
  feedEl.parentElement.scrollTop = feedEl.parentElement.scrollHeight;
}

function appendLLMToken(token) {
  if (!state.streamingEl) return;
  const text = document.createTextNode(token);
  state.streamingEl.appendChild(text);
  feedEl.parentElement.scrollTop = feedEl.parentElement.scrollHeight;
}

function endLLMStream(elapsed_ms, tokens, ttft_ms, tps) {
  if (state.streamingEl) {
    // Telemetry line — TTFT is the key prefix-cache metric
    if (elapsed_ms) {
      const meta = document.createElement('span');
      meta.style.cssText = 'display:block;margin-top:4px;color:var(--text-dim);font-size:10px;font-family:var(--font-code);';
      const ttftStr = ttft_ms ? ` · TTFT: ${ttft_ms.toFixed(0)}ms` : '';
      const tpsStr  = tps     ? ` · ${tps.toFixed(0)} tok/s` : '';
      meta.textContent = `${(elapsed_ms / 1000).toFixed(2)}s${ttftStr}${tpsStr} · ${tokens || 0} tokens`;
      state.streamingEl.appendChild(meta);
    }
    state.streamingEl = null;
  }
}

// ─── Code Viewer ──────────────────────────────────────────────────────────────
function clearCodeViewer() {
  codeViewer.innerHTML = '';
  if (codePlaceholder) codePlaceholder.style.display = 'flex';
  iterTabs.innerHTML = '';
  if (linesEl) linesEl.textContent = '—';
  copyBtn.disabled = true;
  downloadBtn.disabled = true;
  setVeriStatus('idle');
}

function addIterTab(iteration, status, tier) {
  const tab = document.createElement('div');
  tab.className = 'iter-tab';
  tab.dataset.idx = state.iterations.length - 1;
  const prefix = tier === 'tier2_correction' ? '★' : '';
  tab.textContent = `${prefix}v${iteration}`;
  tab.title = tier === 'tier2_correction' ? 'Functionally corrected DUT' : `Lint iteration ${iteration}`;
  tab.addEventListener('click', () => {
    showCodeVersion(parseInt(tab.dataset.idx));
  });
  iterTabs.appendChild(tab);
}

function updateIterTabStatus(idx, status) {
  const tabs = iterTabs.querySelectorAll('.iter-tab');
  if (tabs[idx]) {
    tabs[idx].classList.remove('clean', 'error', 'pending');
    tabs[idx].classList.add(status);
  }
}

function showCodeVersion(idx) {
  if (idx < 0 || idx >= state.iterations.length) return;
  state.activeIterTab = idx;
  const iter = state.iterations[idx];

  iterTabs.querySelectorAll('.iter-tab').forEach((t, i) => {
    t.classList.toggle('active', i === idx);
  });

  if (codePlaceholder) codePlaceholder.style.display = 'none';

  codeViewer.innerHTML = '';
  const pre = document.createElement('pre');
  const code = document.createElement('code');
  code.className = 'language-verilog';
  code.textContent = iter.code;
  pre.appendChild(code);
  codeViewer.appendChild(pre);

  if (window.hljs) hljs.highlightElement(code);

  if (linesEl) linesEl.textContent = iter.lines;
  copyBtn.disabled = false;
  downloadBtn.disabled = !iter.filename;
  downloadBtn.dataset.filename = iter.filename || '';
  downloadBtn.dataset.sessionId = state.currentSession || '';
}

// ─── Verilator Status Bar ─────────────────────────────────────────────────────
function setVeriStatus(status) {
  const icons  = { idle: '◈', running: '⟳', pass: '✓', fail: '✗' };
  const labels = {
    idle:    'Awaiting lint',
    running: 'Running verilator...',
    pass:    'verilator: 0 errors · 0 warnings',
    fail:    'verilator: Errors found — see agent feed',
  };
  veriStatusBar.className = `veri-status-bar ${status}`;
  veriStatusBar.id = 'veri-status-bar';
  veriStatusBar.innerHTML = `<span class="veri-icon">${icons[status]}</span>${labels[status]}`;
}

// ─── Run State ────────────────────────────────────────────────────────────────
function setRunning(running) {
  runBtn.disabled = running;
  if (running) {
    runBtn.classList.add('running');
    runBtn.innerHTML = `
      <div class="btn-inner">
        <div class="spinner visible"></div>
        <span>Agent Running...</span>
      </div>`;
  } else {
    runBtn.classList.remove('running');
    runBtn.innerHTML = `
      <div class="btn-inner">
        <span>▶&nbsp;&nbsp;Run Agent</span>
      </div>`;
  }
}

// ─── Actions ──────────────────────────────────────────────────────────────────
async function handleCopy() {
  const idx = state.activeIterTab;
  if (idx < 0 || idx >= state.iterations.length) return;
  try {
    await navigator.clipboard.writeText(state.iterations[idx].code);
    toast('Code copied to clipboard!', 'info');
  } catch (_) {
    toast('Copy failed — use Ctrl+A on the code panel.', 'error');
  }
}

function handleDownload() {
  const filename = downloadBtn.dataset.filename;
  const sessionId = downloadBtn.dataset.sessionId;
  if (!filename || !sessionId) return;
  const a = document.createElement('a');
  a.href = `/api/download/${sessionId}/${filename}`;
  a.download = filename;
  a.click();
}

// ─── History ──────────────────────────────────────────────────────────────────
async function loadHistory() {
  try {
    const res = await fetch('/api/sessions');
    const sessions = await res.json();
    renderHistory(sessions);
  } catch (_) {}
}

function renderHistory(sessions) {
  const entries = Object.values(sessions).reverse().slice(0, 20);
  if (!entries.length) {
    historyEl.innerHTML = '<div class="history-empty">No sessions yet</div>';
    return;
  }
  historyEl.innerHTML = '';
  entries.forEach(s => {
    const el = document.createElement('div');
    el.className = 'history-item' + (s.session_id === state.currentSession ? ' active' : '');
    const dotClass = s.status === 'success' ? 'success'
                   : s.status === 'partial' ? 'warning'
                   : s.status === 'running' ? 'running'
                   : s.status === 'error' || s.status === 'failed' ? 'error'
                   : 'queued';
    const elapsed = s.completed_at ? ((s.completed_at - s.started_at)).toFixed(1) + 's' : 'running...';
    const lintBadge = s.lint_status === 'PASSED' ? '✓L' : s.lint_status === 'FAILED' ? '✗L' : '—L';
    const simBadge  = s.functional_status === 'PASSED' ? '✓S' : s.functional_status === 'FAILED' ? '✗S' : '—S';
    el.innerHTML = `
      <div class="history-dot ${dotClass}"></div>
      <div class="history-info">
        <div class="history-spec" title="${escHtml(s.spec)}">${escHtml(s.spec.slice(0, 38))}${s.spec.length > 38 ? '…' : ''}</div>
        <div class="history-meta">${s.mock_mode ? '[mock] ' : ''}${elapsed} · ${lintBadge} ${simBadge} · ${s.total_iterations || 0} iter</div>
      </div>`;
    historyEl.appendChild(el);
  });
}

// ─── Toast ────────────────────────────────────────────────────────────────────
function toast(msg, type = 'info') {
  const icons = { success: '✓', error: '✗', info: '◈' };
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.innerHTML = `<span>${icons[type]}</span><span>${escHtml(msg)}</span>`;
  toastContainer.appendChild(el);
  setTimeout(() => el.remove(), 4500);
}

// ─── Waveforms, Logs & Telemetry ──────────────────────────────────────────────
function clearWaveformsAndTelemetry() {
  state.vcdData = null;
  state.simRuns = [];
  state.activeSimRunIndex = -1;

  const ttftEl = $('stat-ttft');
  const tpsEl = $('stat-tps');
  const tokEl = $('stat-tokens');
  const elEl = $('stat-elapsed');
  if (ttftEl) ttftEl.textContent = '—';
  if (tpsEl) tpsEl.textContent = '—';
  if (tokEl) tokEl.textContent = '—';
  if (elEl) elEl.textContent = '—';

  const badge = $('vcd-size-badge');
  if (badge) badge.textContent = 'No trace';
  const dlBtn = $('download-vcd-btn');
  if (dlBtn) dlBtn.disabled = true;
  const viewLogBtn = $('view-sim-log-btn');
  if (viewLogBtn) viewLogBtn.disabled = true;

  const iterBar = $('waveform-iter-bar');
  if (iterBar) iterBar.style.display = 'none';
  const diagBanner = $('sim-diag-banner');
  if (diagBanner) diagBanner.style.display = 'none';

  const placeholder = $('waveform-placeholder');
  if (placeholder) {
    placeholder.textContent = 'Run a verification loop to view simulation waveforms';
    placeholder.style.display = 'block';
  }
  const target = $('wavedrom-target');
  if (target) {
    target.style.display = 'none';
    target.innerHTML = '';
  }
}

function registerSimRun(simData) {
  const existingIdx = state.simRuns.findIndex(r => r.iteration === simData.iteration);
  if (existingIdx >= 0) {
    state.simRuns[existingIdx] = { ...state.simRuns[existingIdx], ...simData };
  } else {
    state.simRuns.push(simData);
  }
  renderWaveformIterTabs();
  selectSimRun(existingIdx >= 0 ? existingIdx : state.simRuns.length - 1);
}

function renderWaveformIterTabs() {
  const bar = $('waveform-iter-bar');
  const tabs = $('waveform-iter-tabs');
  if (!bar || !tabs) return;

  bar.style.display = state.simRuns.length > 0 ? 'flex' : 'none';
  tabs.innerHTML = '';

  state.simRuns.forEach((run, idx) => {
    const btn = document.createElement('button');
    btn.className = `wf-iter-tab ${run.passed ? 'pass' : 'fail'} ${idx === state.activeSimRunIndex ? 'active' : ''}`;
    btn.textContent = `Iter #${run.iteration} ${run.passed ? '✓' : '✗'}`;
    btn.onclick = () => selectSimRun(idx);
    tabs.appendChild(btn);
  });
}

function selectSimRun(idx) {
  if (idx < 0 || idx >= state.simRuns.length) return;
  state.activeSimRunIndex = idx;
  const run = state.simRuns[idx];

  // Update tabs active state
  const tabs = $('waveform-iter-tabs');
  if (tabs) {
    Array.from(tabs.children).forEach((el, i) => {
      el.classList.toggle('active', i === idx);
    });
  }

  // Update View Log & Download buttons
  const viewLogBtn = $('view-sim-log-btn');
  const dlVcdBtn = $('download-vcd-btn');
  const sizeBadge = $('vcd-size-badge');

  if (viewLogBtn) viewLogBtn.disabled = false;
  if (dlVcdBtn) dlVcdBtn.disabled = !run.vcd_data && !run.vcd_file_path;

  if (sizeBadge) {
    if (run.vcd_size_bytes) {
      sizeBadge.textContent = `${(run.vcd_size_bytes / 1024).toFixed(1)} KB VCD`;
    } else if (run.vcd_data) {
      sizeBadge.textContent = `${(run.vcd_data.length / 1024).toFixed(1)} KB`;
    } else {
      sizeBadge.textContent = run.passed ? 'Verified' : 'No trace';
    }
  }

  // Failure banner
  const diagBanner = $('sim-diag-banner');
  const diagTitle = $('diag-title');
  const diagSummary = $('diag-summary');
  const diagLogPath = $('diag-log-path');

  if (!run.passed) {
    if (diagBanner) diagBanner.style.display = 'block';
    if (diagTitle) diagTitle.textContent = `❌ Iteration #${run.iteration} Simulation Failure`;
    if (diagLogPath) diagLogPath.textContent = run.log_file_path ? `Log: ${run.log_file_path.split(/[\\/]/).pop()}` : '';
    if (diagSummary) diagSummary.textContent = run.error_summary || run.stderr || run.stdout || 'Simulation assertions failed.';
  } else {
    if (diagBanner) diagBanner.style.display = 'none';
  }

  // Waveform rendering
  if (run.vcd_data) {
    state.vcdData = run.vcd_data;
    renderWaveform(run.vcd_data);
  } else {
    renderWaveform(null);
  }
}

window.openSimLogViewer = async function(idx) {
  const runIdx = (typeof idx === 'number') ? idx : (state.activeSimRunIndex >= 0 ? state.activeSimRunIndex : state.simRuns.length - 1);
  const run = state.simRuns[runIdx];
  const modal = $('sim-log-modal');
  const badge = $('modal-iter-badge');
  const meta = $('modal-log-meta');
  const content = $('modal-log-content');

  if (!modal) return;
  modal.style.display = 'flex';

  if (!run) {
    if (content) content.textContent = 'No simulation logs captured yet.';
    return;
  }

  if (badge) {
    badge.textContent = `Iteration #${run.iteration} · ${run.passed ? 'PASSED ✓' : 'FAILED ✗'}`;
    badge.style.color = run.passed ? 'var(--green)' : 'var(--red)';
  }

  let logText = '';
  if (run.log_file_path && state.currentSession) {
    const filename = run.log_file_path.split(/[\\/]/).pop();
    if (meta) meta.textContent = `File: ${run.log_file_path} · Elapsed: ${run.elapsed_ms || 0}ms`;
    try {
      const res = await fetch(`/api/logs/${state.currentSession}/raw/${filename}`);
      if (res.ok) {
        logText = await res.text();
      }
    } catch (_) {}
  }

  if (!logText) {
    logText = `================================================================================\n` +
              `SIMULATION DIAGNOSTIC LOG (Iteration ${run.iteration})\n` +
              `Status: ${run.passed ? 'PASSED' : 'FAILED'}\n` +
              `Phase: ${run.phase || 'run'}\n` +
              `Elapsed: ${run.elapsed_ms || 0} ms\n` +
              `Log Path: ${run.log_file_path || 'saved to logs/'}\n` +
              `================================================================================\n\n` +
              `--- STDOUT ---\n${run.stdout || '(none)'}\n\n` +
              `--- STDERR / DIAGNOSTICS ---\n${run.stderr || run.error_summary || '(none)'}`;
  }

  if (content) {
    content.textContent = logText;
  }
};

window.closeSimLogViewer = function() {
  const modal = $('sim-log-modal');
  if (modal) modal.style.display = 'none';
};

window.downloadCurrentSimLog = function() {
  const run = state.simRuns[state.activeSimRunIndex >= 0 ? state.activeSimRunIndex : state.simRuns.length - 1];
  if (!run) return;
  const content = $('modal-log-content')?.textContent || ((run.stdout || '') + '\n' + (run.stderr || ''));
  const blob = new Blob([content], { type: 'text/plain' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `sim_iter${run.iteration}_${state.currentSession || 'log'}.log`;
  a.click();
  URL.revokeObjectURL(url);
};

function downloadVCD() {
  const run = state.simRuns[state.activeSimRunIndex >= 0 ? state.activeSimRunIndex : state.simRuns.length - 1];
  const vcdText = run?.vcd_data || state.vcdData;
  if (!vcdText) {
    toast('No VCD data available to download.', 'info');
    return;
  }
  const blob = new Blob([vcdText], { type: 'text/plain' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `${state.currentSession || 'simulation'}_iter${run?.iteration || 1}_trace.vcd`;
  a.click();
  URL.revokeObjectURL(url);
}

function vcdToWaveDrom(vcdText, maxCycles = 24) {
  if (!vcdText) return null;
  const lines = vcdText.split('\n');
  const signals = {}; // id -> { name, type, width, isTop }
  const ignoredNames = new Set(['data_width', 'sel_width', 'clk_period', 'errors', 'cycle_count', 'i', 'j', 'k', 'unnamedblk1', 'unnamedblk2']);

  // Pass 1: Parse variable declarations and scopes
  let currentScope = '';
  for (const line of lines) {
    const trimmed = line.trim();
    if (trimmed.startsWith('$scope')) {
      const parts = trimmed.split(/\s+/);
      if (parts.length >= 3) currentScope = parts[2];
    } else if (trimmed.startsWith('$upscope')) {
      currentScope = '';
    } else if (trimmed.startsWith('$var')) {
      const parts = trimmed.split(/\s+/);
      // Format: $var <type> <width> <id> <name> [bounds] $end
      if (parts.length >= 5) {
        const type = parts[1];
        const width = parseInt(parts[2], 10) || 1;
        const id = parts[3];
        const rawName = parts.slice(4, -1).join(' ').trim();
        const cleanName = rawName.replace(/\s*\[.*?\]/g, '').trim();
        const lowerName = cleanName.toLowerCase();

        // Ignore compiler temp indices, parameters, and debug counts
        if (ignoredNames.has(lowerName) || cleanName.startsWith('__')) {
          continue;
        }

        // If duplicate ID exists, prefer top-level DUT port or shorter name
        if (!signals[id] || (!cleanName.includes('_reg') && signals[id].name.includes('_reg'))) {
          signals[id] = { name: cleanName, type, width, wave: [], values: [], isTop: !currentScope.includes('unnamed') };
        }
      }
    } else if (trimmed.startsWith('$enddefinitions')) {
      break;
    }
  }

  const sigIds = Object.keys(signals);
  if (sigIds.length === 0) return null;

  // Pass 2: Parse value changes
  let currentTime = 0;
  const timeSteps = [];
  const signalHistory = {}; // id -> [{ time, val }]
  for (const id of sigIds) {
    signalHistory[id] = [];
  }

  let parsingValues = false;
  for (const line of lines) {
    const trimmed = line.trim();
    if (trimmed.startsWith('$dumpvars') || trimmed.startsWith('$enddefinitions')) {
      parsingValues = true;
      continue;
    }
    if (!parsingValues) continue;

    if (trimmed.startsWith('#')) {
      currentTime = parseInt(trimmed.slice(1), 10);
      if (!isNaN(currentTime)) timeSteps.push(currentTime);
      continue;
    }

    // Scalar: '0!' or '1"' or 'x$' or 'z$'
    if (trimmed.length >= 2 && (trimmed[0] === '0' || trimmed[0] === '1' || trimmed[0] === 'x' || trimmed[0] === 'z' || trimmed[0] === 'X' || trimmed[0] === 'Z')) {
      const val = trimmed[0].toLowerCase();
      const id = trimmed.slice(1).trim();
      if (signalHistory[id]) {
        signalHistory[id].push({ time: currentTime, val });
      }
    }
    // Vector: 'b0010 $' or 'b0000 $'
    else if (trimmed.startsWith('b') || trimmed.startsWith('B')) {
      const spaceIdx = trimmed.indexOf(' ');
      if (spaceIdx !== -1) {
        const rawVal = trimmed.slice(1, spaceIdx).trim();
        const id = trimmed.slice(spaceIdx + 1).trim();
        if (signalHistory[id]) {
          let hexVal;
          try {
            const intVal = parseInt(rawVal, 2);
            hexVal = !isNaN(intVal) ? intVal.toString(16).toUpperCase() : rawVal;
          } catch (_) {
            hexVal = rawVal;
          }
          signalHistory[id].push({ time: currentTime, val: hexVal });
        }
      }
    }
  }

  // Sample into uniform cycle slots
  const uniqueTimes = [...new Set(timeSteps)].sort((a, b) => a - b).slice(0, maxCycles * 2);
  const sampleTimes = uniqueTimes.length > 0 ? uniqueTimes : [0, 5000, 10000, 15000, 20000, 25000, 30000, 35000];

  // Prioritize signal display order: clk, rst, inputs, outputs
  const sortedIds = sigIds.sort((a, b) => {
    const na = signals[a].name.toLowerCase();
    const nb = signals[b].name.toLowerCase();
    const getRank = (name) => {
      if (name.includes('clk') || name.includes('clock')) return 0;
      if (name.includes('rst') || name.includes('reset')) return 1;
      if (name.includes('sel') || name.includes('en') || name.includes('valid')) return 2;
      if (name.startsWith('in') || name.includes('din') || name === 'a' || name === 'b') return 3;
      if (name.startsWith('out') || name.includes('dout') || name.includes('result') || name.includes('count')) return 4;
      return 5;
    };
    return getRank(na) - getRank(nb);
  });

  const waveLanes = [];
  for (const id of sortedIds) {
    const sig = signals[id];
    let waveStr = '';
    const dataVals = [];
    let lastVal = 'x';

    for (let i = 0; i < sampleTimes.length; i++) {
      const t = sampleTimes[i];
      const history = signalHistory[id];
      const entry = history ? [...history].reverse().find(h => h.time <= t) : null;
      const currentVal = entry ? entry.val : lastVal;

      if (sig.name.toLowerCase().includes('clk') || sig.name.toLowerCase().includes('clock')) {
        waveStr += i % 2 === 0 ? 'p' : '.';
      } else if (currentVal === '1' || currentVal === '0') {
        waveStr += (currentVal === lastVal && i > 0) ? '.' : currentVal;
      } else if (currentVal !== 'x' && currentVal !== 'z') {
        if (currentVal !== lastVal || i === 0) {
          waveStr += '=';
          dataVals.push(currentVal);
        } else {
          waveStr += '.';
        }
      } else {
        waveStr += (currentVal === lastVal && i > 0) ? '.' : 'x';
      }
      lastVal = currentVal;
    }

    const lane = { name: sig.name, wave: waveStr };
    if (dataVals.length > 0) lane.data = dataVals;
    waveLanes.push(lane);
  }

  return {
    signal: waveLanes,
    head: { text: 'Verilator Simulation Waveform (AMD ROCm)', tick: 0 },
    config: { hscale: 1 }
  };
}

function renderSvgFallback(waveJson, target) {
  if (!waveJson || !waveJson.signal || !target) return;
  const signals = waveJson.signal;
  const stepWidth = 32;
  const laneHeight = 36;
  const labelWidth = 90;
  const numSteps = signals[0]?.wave?.length || 16;
  const totalWidth = labelWidth + (numSteps * stepWidth) + 40;
  const totalHeight = 40 + (signals.length * laneHeight) + 30;

  let svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${totalWidth} ${totalHeight}" style="width:100%;max-width:${totalWidth}px;height:auto;font-family:'JetBrains Mono',monospace;font-size:12px;background:#0d1117;border-radius:8px;padding:8px;">`;
  
  // Header
  svg += `<text x="${labelWidth}" y="24" fill="#58a6ff" font-weight="600" font-size="13">${waveJson.head?.text || 'Simulation Waveform'}</text>`;

  // Grid lines
  for (let s = 0; s < numSteps; s++) {
    const x = labelWidth + (s * stepWidth);
    svg += `<line x1="${x}" y1="35" x2="${x}" y2="${totalHeight - 20}" stroke="#21262d" stroke-width="1" stroke-dasharray="2,2"/>`;
    svg += `<text x="${x + stepWidth/2}" y="${totalHeight - 6}" fill="#8b949e" font-size="10" text-anchor="middle">${s}</text>`;
  }

  // Signal lanes
  signals.forEach((sig, idx) => {
    const y = 50 + (idx * laneHeight);
    svg += `<text x="${labelWidth - 10}" y="${y + 16}" fill="#e6edf3" font-weight="500" text-anchor="end">${sig.name}</text>`;

    let dataIdx = 0;
    let currVal = '0';
    for (let s = 0; s < sig.wave.length; s++) {
      const char = sig.wave[s];
      const x = labelWidth + (s * stepWidth);
      const isClk = sig.wave.includes('p');

      if (isClk) {
        // Clock pulse
        svg += `<path d="M ${x} ${y + 24} L ${x + stepWidth/2} ${y + 6} L ${x + stepWidth} ${y + 24}" fill="none" stroke="#7ee787" stroke-width="2"/>`;
      } else if (char === '1' || (char === '.' && currVal === '1')) {
        currVal = '1';
        svg += `<line x1="${x}" y1="${y + 6}" x2="${x + stepWidth}" y2="${y + 6}" stroke="#79c0ff" stroke-width="2"/>`;
      } else if (char === '0' || (char === '.' && currVal === '0')) {
        currVal = '0';
        svg += `<line x1="${x}" y1="${y + 24}" x2="${x + stepWidth}" y2="${y + 24}" stroke="#79c0ff" stroke-width="2"/>`;
      } else if (char === '=') {
        const valText = sig.data ? (sig.data[dataIdx++] || '') : '';
        svg += `<polygon points="${x+2},${y+15} ${x+6},${y+6} ${x+stepWidth-6},${y+6} ${x+stepWidth-2},${y+15} ${x+stepWidth-6},${y+24} ${x+6},${y+24}" fill="#1f293d" stroke="#d2a8ff" stroke-width="1.5"/>`;
        if (valText) {
          svg += `<text x="${x + stepWidth/2}" y="${y + 19}" fill="#f0f6fc" font-size="10" text-anchor="middle">${valText}</text>`;
        }
      } else {
        svg += `<line x1="${x}" y1="${y + 15}" x2="${x + stepWidth}" y2="${y + 15}" stroke="#8b949e" stroke-width="1.5" stroke-dasharray="3,3"/>`;
      }
    }
  });

  svg += `</svg>`;
  target.innerHTML = svg;
}

function renderWaveform(vcdText) {
  const placeholder = $('waveform-placeholder');
  const target = $('wavedrom-target');

  if (!vcdText) {
    if (placeholder) {
      placeholder.textContent = 'No waveform trace available.';
      placeholder.style.display = 'block';
    }
    if (target) target.style.display = 'none';
    return;
  }

  try {
    const waveJson = vcdToWaveDrom(vcdText);
    if (!waveJson || waveJson.signal.length === 0) {
      if (placeholder) {
        placeholder.textContent = 'No signal transitions captured in trace.';
        placeholder.style.display = 'block';
      }
      if (target) target.style.display = 'none';
      return;
    }

    if (placeholder) placeholder.style.display = 'none';
    if (target) {
      target.style.display = 'block';
      target.innerHTML = '';

      // Check if WaveDrom and WaveSkin are fully loaded
      const hasWaveSkin = typeof window.WaveSkin !== 'undefined' && window.WaveSkin && window.WaveSkin.default;
      if (window.WaveDrom && hasWaveSkin) {
        try {
          const script = document.createElement('script');
          script.type = 'WaveDrom';
          script.textContent = JSON.stringify(waveJson);
          target.appendChild(script);
          WaveDrom.ProcessAll();
          return;
        } catch (wdErr) {
          console.warn('WaveDrom ProcessAll error, falling back to SVG renderer:', wdErr);
        }
      }

      // Native crisp SVG Waveform fallback
      renderSvgFallback(waveJson, target);
    }
  } catch (err) {
    console.warn('WaveDrom render failed:', err);
    if (placeholder) {
      placeholder.textContent = `Waveform render notice: ${err.message}`;
      placeholder.style.display = 'block';
    }
  }
}



// ─── Utility ──────────────────────────────────────────────────────────────────
function escHtml(str) {
  return String(str ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// ─── Boot ─────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', init);
