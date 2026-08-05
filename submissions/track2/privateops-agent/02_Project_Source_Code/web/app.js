const byId = (id) => document.getElementById(id);
const { readLanguage, writeLanguage, responseLanguage, demoPrompt, translate, translateKnown } = globalThis.PrivateOpsI18n;
const { readTheme, writeTheme, readProviderProfiles, writeProviderProfiles, initialProviderMode, classifyEvidence, activeSection } = globalThis.PrivateOpsUiState;
const { render: renderMarkdown } = globalThis.PrivateOpsMarkdown;
const state = {
  pendingPrompt: "",
  latestResponse: null,
  latestPermission: null,
  latestStatus: null,
  auditEntries: null,
  benchmarkData: null,
  radeonEvidence: null,
  requestStatusKey: "request.ready",
  currentLanguage: readLanguage(globalThis.localStorage),
  currentTheme: readTheme(globalThis.localStorage),
  providerProfiles: readProviderProfiles(globalThis.localStorage),
  providerMode: "remote",
  apiFeedback: null,
};
state.providerMode = state.providerProfiles.activeMode;
const t = (key, params = {}) => translate(state.currentLanguage, key, params);
const known = (value) => translateKnown(state.currentLanguage, value || "");

function setRequestStatus(key, rawMessage = "") {
  state.requestStatusKey = key;
  byId("requestStatus").textContent = key ? t(key) : rawMessage;
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) {
    const error = new Error(data.error?.message || `Request failed: ${response.status}`);
    error.code = data.error?.code || "";
    throw error;
  }
  return data;
}

async function postJson(url, payload) {
  return requestJson(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

function clearAndAppend(container, nodes) {
  container.replaceChildren(...nodes);
  container.classList.toggle("empty-state", nodes.length === 0);
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function renderAnswer(answer) {
  const container = byId("answer");
  try {
    container.innerHTML = renderMarkdown(answer);
  } catch (_error) {
    container.textContent = answer;
  }
}

function applyTheme(theme, persist = false) {
  state.currentTheme = persist ? writeTheme(globalThis.localStorage, theme) : theme;
  document.documentElement.dataset.theme = state.currentTheme;
  document.querySelector('meta[name="theme-color"]').content = state.currentTheme === "light" ? "#f5f3ef" : "#11151f";
  const nextIsLight = state.currentTheme === "dark";
  byId("themeToggle").textContent = t(nextIsLight ? "theme.switchLight" : "theme.switchDark");
  byId("themeToggle").setAttribute("aria-label", t(nextIsLight ? "theme.ariaLight" : "theme.ariaDark"));
}

function renderPermission(decision) {
  state.latestPermission = decision;
  const card = byId("permissionCard");
  card.className = `permission ${decision.level}`;
  card.replaceChildren(
    element("strong", "", t(`permission.${decision.level}`)),
    element("span", "", known(decision.reason)),
  );
  state.pendingPrompt = decision.level === "confirm" ? byId("prompt").value.trim() : "";
  byId("confirmButton").classList.toggle("hidden", decision.level !== "confirm");
}

function renderEvidence(items = [], tools = []) {
  const classified = classifyEvidence(items, tools);
  const nodes = classified.kind === "rag" ? classified.items.map((item) => {
    const article = element("article", "evidence-item");
    const source = element("div", "evidence-source");
    source.append(element("span", "", item.source), element("span", "", `${item.evidence_id} · ${item.score}`));
    article.append(source, element("p", "", item.snippet));
    return article;
  }) : [];
  if (classified.kind === "tools") {
    const summary = element("div", "evidence-summary");
    summary.append(element("strong", "", t("evidence.toolsTitle")), element("span", "", t("evidence.toolsDetail")));
    nodes.push(summary);
    classified.items.forEach((tool) => {
      const output = tool.output || {};
      const count = Number.isFinite(Number(output.count))
        ? Number(output.count)
        : (output.items || output.entries || []).length;
      const detail = [t("evidence.itemCount", {count})];
      if (output.truncated) detail.push(t("evidence.truncated"));
      const row = element("div", "tool-evidence");
      row.append(element("b", "", t(`tool.name.${tool.name}`)), element("span", "", detail.join(" · ")));
      nodes.push(row);
    });
  }
  if (classified.kind === "general") nodes.push(element("div", "empty-state", t("evidence.general")));
  clearAndAppend(byId("evidenceList"), nodes);
}

function renderPlan(steps = [], tools = []) {
  const planNodes = steps.map((step) => {
    const item = element("li", step.status, known(step.title));
    const status = t(`plan.status.${step.status}`);
    item.append(element("small", "", `${status} · ${step.result ? known(step.result) : t("plan.pending")}`));
    return item;
  });
  clearAndAppend(byId("planList"), planNodes.length ? planNodes : [element("li", "empty-state", t("plan.empty"))]);
  const toolNodes = tools.map((tool) => {
    const chip = element("div", "tool-chip");
    chip.append(element("span", "", t(`tool.name.${tool.name}`)), element("b", "", t(`plan.status.${tool.status}`)));
    return chip;
  });
  clearAndAppend(byId("toolList"), toolNodes.length ? toolNodes : [element("div", "empty-state", t("tools.empty"))]);
}

async function refreshMemory() {
  const data = await requestJson("/api/memory");
  byId("memoryBox").textContent = JSON.stringify(data.memory, null, 2);
}

async function refreshAudit() {
  const data = await requestJson("/api/audit");
  state.auditEntries = data.entries || [];
  renderAudit();
}

function renderAudit() {
  const nodes = (state.auditEntries || []).slice(0, 8).map((entry) => {
    const row = element("article", "audit-item");
    const deleteButton = element("button", "audit-delete", t("audit.delete"));
    deleteButton.type = "button";
    deleteButton.setAttribute("aria-label", t("audit.deleteAria", {id: entry.audit_id}));
    deleteButton.addEventListener("click", () => deleteAudit(entry.audit_id, deleteButton));
    row.append(
      element("span", "audit-time", new Date(entry.created_at).toLocaleString(state.currentLanguage)),
      element("span", `audit-level ${entry.permission_level}`, t(`permission.${entry.permission_level}`)),
      element("span", "audit-prompt", known(entry.prompt)),
      element("span", "audit-id", entry.audit_id),
      deleteButton,
    );
    return row;
  });
  clearAndAppend(byId("auditList"), nodes.length ? nodes : [element("div", "empty-state", t("audit.empty"))]);
}

async function deleteAudit(auditId, button) {
  if (!globalThis.confirm(t("audit.deleteConfirm", {id: auditId}))) return;
  button.disabled = true;
  try {
    await requestJson(`/api/audit/${encodeURIComponent(auditId)}`, {method: "DELETE"});
    await refreshAudit();
    setRequestStatus("", t("audit.deleteSuccess"));
  } catch (error) {
    button.disabled = false;
    setRequestStatus("", t("audit.deleteFailure", {message: error.message}));
  }
}

async function refreshBenchmarks() {
  const data = await requestJson("/api/benchmarks");
  state.benchmarkData = data;
  renderBenchmarks();
}

function renderBenchmarks() {
  const data = state.benchmarkData || { runs: [] };
  const nodes = (data.runs || []).slice().reverse().map((run) => {
    const row = element("div", "benchmark-run");
    row.append(
      element("b", "", known(run.label)),
      element("span", run.verified ? "verified" : "", `${t(run.verified ? "benchmark.verified" : "benchmark.development")} · ${run.latency_ms} ${t("units.milliseconds")} · ${run.tokens_per_second} ${t("units.tokensPerSecond")}`),
    );
    return row;
  });
  clearAndAppend(byId("benchmarkList"), nodes.length ? nodes : [element("div", "empty-state", t("benchmark.empty"))]);
  const card = byId("comparisonCard");
  if (data.comparison?.ready) {
    card.replaceChildren(
      element("span", "", t("comparison.label")),
      element("strong", "", t("comparison.latency", { value: data.comparison.latency_speedup })),
      element("small", "", t("comparison.throughput", { value: data.comparison.throughput_speedup })),
    );
  } else if (state.radeonEvidence?.available) {
    card.replaceChildren(
      element("span", "", t("comparison.label")),
      element("strong", "", t("comparison.verifiedRecord")),
      element("small", "", t("comparison.verifiedDetail", {
        latency: state.radeonEvidence.metrics.latency_ms,
        throughput: state.radeonEvidence.metrics.tokens_per_second,
      })),
    );
  } else {
    card.replaceChildren(
      element("span", "", t("comparison.label")),
      element("strong", "", t("comparison.awaiting")),
      element("small", "", t("comparison.noClaim")),
    );
  }
}

function proofFact(labelKey, value) {
  const row = element("div");
  row.append(element("dt", "", t(labelKey)), element("dd", "", value));
  return row;
}

function proofMetric(labelKey, value) {
  const card = element("div", "proof-metric");
  card.append(element("span", "", t(labelKey)), element("strong", "", value));
  return card;
}

function renderRadeonEvidence(data) {
  state.radeonEvidence = data;
  const status = byId("radeonProofStatus");
  const facts = byId("radeonProofFacts");
  const metrics = byId("radeonMetrics");
  const stack = byId("radeonStack");
  const sources = byId("radeonSources");
  facts.replaceChildren();
  metrics.replaceChildren();
  stack.replaceChildren();
  sources.replaceChildren();

  if (!data?.available) {
    status.className = "proof-status unavailable";
    status.textContent = t("performance.proof.unavailable");
    byId("radeonBoundary").textContent = t("performance.proof.unavailableReason");
    renderBenchmarks();
    return;
  }

  status.className = "proof-status";
  const captured = new Date(data.captured_at).toLocaleString(state.currentLanguage, {
    dateStyle: "medium",
    timeStyle: "short",
  });
  const metadata = element("span", "", `${t("performance.proof.captured", {date: captured})} · ${t("performance.proof.instance", {id: data.instance_id})}`);
  status.replaceChildren(element("strong", "", t("performance.proof.verified")), metadata);

  facts.append(
    proofFact("performance.proof.gpu", data.gpu.name),
    proofFact("performance.proof.architecture", data.gpu.architecture),
    proofFact("performance.proof.rocm", data.runtime.rocm_version),
    proofFact("performance.proof.model", data.model.name),
    proofFact("performance.proof.location", known(data.model.location)),
  );
  metrics.append(
    proofMetric("performance.proof.modelLatency", `${data.metrics.latency_ms} ms`),
    proofMetric("performance.proof.throughput", `${data.metrics.tokens_per_second} tok/s`),
    proofMetric("performance.proof.tokens", `${data.metrics.prompt_tokens} / ${data.metrics.completion_tokens}`),
    proofMetric("performance.proof.agentLatency", `${data.metrics.agent_latency_ms} ms`),
  );
  stack.append(
    proofFact("performance.proof.vram", `${(data.gpu.vram_bytes / (1024 ** 3)).toFixed(1)} GiB`),
    proofFact("performance.proof.pytorch", data.runtime.pytorch_version),
    proofFact("performance.proof.hip", data.runtime.hip_version),
    proofFact("performance.proof.vllm", data.runtime.vllm_version),
    proofFact("performance.proof.provider", data.model.provider),
    proofFact("performance.proof.endpoint", data.model.endpoint),
  );
  const summaryLink = element("a", "proof-source primary", t("performance.proof.sourceJson"));
  summaryLink.href = "/api/rocm-evidence";
  summaryLink.target = "_blank";
  summaryLink.rel = "noopener";
  sources.append(summaryLink, ...data.sources.map((source) => {
    const item = element("span", "proof-source", source.name);
    item.title = source.path;
    return item;
  }));
  byId("radeonBoundary").textContent = t("performance.proof.boundary");
  renderBenchmarks();
}

async function loadRadeonEvidence() {
  try {
    renderRadeonEvidence(await requestJson("/api/rocm-evidence"));
  } catch (_error) {
    renderRadeonEvidence({available: false, reason: "request_failed"});
  }
}

function renderStatus() {
  const status = state.latestStatus;
  if (!status) return;
  byId("healthStatus").textContent = t("health.online");
  byId("healthStatus").className = "status-pill";
  byId("modeBadge").textContent = t(`mode.${status.runtime_mode || status.provider_mode}`);
  byId("runtimeFacts").replaceChildren();
  [
    ["runtime.framework", status.agent_framework],
    ["runtime.inference", status.inference_runtime],
    ["runtime.location", known(status.core_inference_location)],
    ["runtime.provider", status.provider],
    ["runtime.documents", status.indexed_documents],
    ["runtime.boundary", known(status.privacy_boundary)],
  ].forEach(([key, value]) => {
    const row = element("div");
    row.append(element("dt", "", t(key)), element("dd", "", value));
    byId("runtimeFacts").append(row);
  });
}

async function loadStatus() {
  try {
    const status = await requestJson("/api/status");
    state.latestStatus = status;
    renderStatus();
    populateProviderDefaults(status);
  } catch (error) {
    byId("healthStatus").textContent = t("health.offline");
    byId("healthStatus").className = "status-pill error";
  }
}

function providerFormConfig() {
  return {
    mode: state.providerMode,
    endpoint: byId("apiEndpoint").value.trim(),
    model: byId("apiModel").value.trim(),
    apiKey: byId("apiKey").value.trim(),
  };
}

function validProviderConfig(config) {
  if (!config.endpoint || !config.model) return false;
  const mode = config.mode;
  if (mode === "remote" && !config.apiKey) return false;
  try {
    const url = new URL(config.endpoint);
    if (url.protocol !== "http:" && url.protocol !== "https:") return false;
    if (mode === "rocm-local") return ["127.0.0.1", "localhost", "[::1]"].includes(url.hostname);
    return mode === "remote";
  } catch (_error) {
    return false;
  }
}

function populateProviderDefaults(status = {}) {
  const remote = state.providerProfiles.remote;
  if (!remote.endpoint && status.remote_model_allowed) remote.endpoint = status.model_endpoint || "";
  if (!remote.model && status.remote_model_allowed) remote.model = status.model_name || "";
  byId("rememberApi").checked = state.providerProfiles.remember;
  applyProviderMode(initialProviderMode(state.providerProfiles, status), false);
}

function providerProfileKey(mode) {
  return mode === "rocm-local" ? "local" : "remote";
}

function storeVisibleProviderProfile() {
  state.providerProfiles[providerProfileKey(state.providerMode)] = {
    endpoint: byId("apiEndpoint").value.trim(),
    model: byId("apiModel").value.trim(),
    apiKey: byId("apiKey").value.trim(),
  };
}

function renderProviderModeLabel() {
  const key = state.providerMode === "rocm-local" ? "api.keyOptional" : "api.keyRequired";
  byId("apiKeyLabel").dataset.i18n = key;
  byId("apiKeyLabel").textContent = t(key);
}

function applyProviderMode(mode, captureCurrent = true) {
  if (captureCurrent) storeVisibleProviderProfile();
  state.providerMode = mode === "rocm-local" ? "rocm-local" : "remote";
  state.providerProfiles.activeMode = state.providerMode;
  byId("providerModeRemote").checked = state.providerMode === "remote";
  byId("providerModeLocal").checked = state.providerMode === "rocm-local";
  const profile = state.providerProfiles[providerProfileKey(state.providerMode)];
  byId("apiEndpoint").value = profile.endpoint;
  byId("apiModel").value = profile.model;
  byId("apiKey").value = profile.apiKey;
  renderProviderModeLabel();
  setApiFeedback("");
}

function setApiFeedback(key, params = {}, className = "") {
  state.apiFeedback = key ? {key, params, className} : null;
  const feedback = byId("apiFeedback");
  feedback.textContent = key ? t(key, params) : "";
  feedback.className = `api-feedback${className ? ` ${className}` : ""}`;
}

function renderApiKeyVisibility() {
  const visible = byId("apiKey").type === "text";
  byId("apiKeyVisibility").textContent = t(visible ? "api.hideKey" : "api.showKey");
}

function persistProviderForm(config) {
  state.providerProfiles[providerProfileKey(config.mode)] = {
    endpoint: config.endpoint,
    model: config.model,
    apiKey: config.apiKey,
  };
  state.providerProfiles.activeMode = config.mode;
  const stored = writeProviderProfiles(globalThis.localStorage, state.providerProfiles, byId("rememberApi").checked);
  state.providerProfiles = stored;
  byId("rememberApi").checked = stored.remember;
}

async function testProviderApi() {
  const config = providerFormConfig();
  if (!validProviderConfig(config)) {
    setApiFeedback(config.mode === "remote" ? "api.validationRemote" : "api.validationLocal", {}, "error");
    return;
  }
  byId("testApiButton").disabled = true;
  setApiFeedback("api.testing");
  try {
    const result = await postJson("/api/provider/test", {
      mode: config.mode,
      endpoint: config.endpoint,
      model: config.model,
      api_key: config.apiKey,
    });
    persistProviderForm(config);
    setApiFeedback("api.testSuccess", {latency: result.latency_ms}, "success");
  } catch (error) {
    setApiFeedback("api.failure", {message: error.message}, "error");
  } finally {
    byId("testApiButton").disabled = false;
  }
}

async function applyProviderApi() {
  const config = providerFormConfig();
  if (!validProviderConfig(config)) {
    setApiFeedback(config.mode === "remote" ? "api.validationRemote" : "api.validationLocal", {}, "error");
    return;
  }
  byId("applyApiButton").disabled = true;
  setApiFeedback("api.applying");
  try {
    await postJson("/api/provider/config", {
      mode: config.mode,
      endpoint: config.endpoint,
      model: config.model,
      api_key: config.apiKey,
    });
    persistProviderForm(config);
    await loadStatus();
    setApiFeedback("api.applySuccess", {}, "success");
  } catch (error) {
    setApiFeedback("api.failure", {message: error.message}, "error");
  } finally {
    byId("applyApiButton").disabled = false;
  }
}

function toggleApiPanel(force) {
  const panel = byId("apiPanel");
  const open = force === undefined ? panel.classList.contains("hidden") : force;
  panel.classList.toggle("hidden", !open);
  panel.setAttribute("aria-hidden", String(!open));
  byId("apiToggle").setAttribute("aria-expanded", String(open));
  if (open) byId("apiEndpoint").focus();
}

async function runAgent(confirmationToken = "") {
  const prompt = byId("prompt").value.trim();
  if (!prompt) return;
  byId("askButton").disabled = true;
  setRequestStatus("request.loading");
  try {
    const data = await postJson("/api/chat", {
      prompt,
      confirmation_token: confirmationToken,
      response_language: responseLanguage(state.currentLanguage),
    });
    state.latestResponse = data;
    renderAnswer(data.answer);
    byId("answerMeta").textContent = `${data.provider} · ${data.metrics.latency_ms} ms · ${data.audit_id}`;
    renderPermission(data.permission);
    renderEvidence(data.evidence, data.tool_results);
    renderPlan(data.plan, data.tool_results);
    setRequestStatus("request.completed");
    await Promise.all([refreshMemory(), refreshAudit()]);
  } catch (error) {
    if (error.code === "provider_required") {
      state.latestResponse = null;
      byId("answer").dataset.i18n = "answer.apiRequired";
      renderAnswer(t("answer.apiRequired"));
      byId("answerMeta").textContent = "";
      toggleApiPanel(true);
      setRequestStatus("", t("answer.apiRequired"));
      return;
    }
    setRequestStatus("", error.message);
  } finally {
    byId("askButton").disabled = false;
  }
}

async function previewPermission() {
  const prompt = byId("prompt").value.trim();
  if (!prompt) return;
  renderPermission(await postJson("/api/permission", { prompt }));
}

async function confirmAction() {
  if (!state.pendingPrompt) return;
  try {
    const confirmation = await postJson("/api/confirm", { prompt: state.pendingPrompt });
    await runAgent(confirmation.token);
  } catch (error) {
    setRequestStatus("", error.message);
  }
}

async function loadRocmProfile() {
  const data = await requestJson("/api/rocm-profile");
  byId("gpuName").value = data.gpu_name || "";
  byId("rocmVersion").value = data.rocm_version || "";
  byId("modelEndpoint").value = data.model_endpoint || "http://127.0.0.1:8000/v1/chat/completions";
  byId("rocmNotes").value = data.notes || "";
}

async function saveRocmProfile() {
  await postJson("/api/rocm-profile", {
    gpu_name: byId("gpuName").value,
    rocm_version: byId("rocmVersion").value,
    model_endpoint: byId("modelEndpoint").value,
    notes: byId("rocmNotes").value,
  });
  setRequestStatus("request.profileSaved");
}

async function recordBenchmark() {
  try {
    await postJson("/api/benchmarks", {
      label: "Radeon Cloud verified run",
      provider_mode: "rocm-local",
      verified: true,
      gpu_name: byId("gpuName").value,
      rocm_version: byId("rocmVersion").value,
      model_name: "Qwen/Qwen2.5-7B-Instruct",
      rocminfo_excerpt: byId("rocminfoExcerpt").value,
      latency_ms: byId("latencyMs").value,
      tokens_per_second: byId("tokensPerSecond").value,
      notes: byId("rocmNotes").value,
    });
    await refreshBenchmarks();
    setRequestStatus("request.benchmarkRecorded");
  } catch (error) {
    setRequestStatus("", error.message);
  }
}

function applyLanguage(language, persist = false) {
  state.currentLanguage = persist ? writeLanguage(globalThis.localStorage, language) : language;
  document.documentElement.lang = state.currentLanguage;
  document.title = t("document.title");
  document.querySelectorAll("[data-i18n]").forEach((node) => {
    if (node.id === "answer" && state.latestResponse) return;
    node.textContent = t(node.dataset.i18n);
  });
  document.querySelectorAll("[data-i18n-placeholder]").forEach((node) => {
    node.placeholder = t(node.dataset.i18nPlaceholder);
  });
  document.querySelectorAll("[data-i18n-aria]").forEach((node) => {
    node.setAttribute("aria-label", t(node.dataset.i18nAria));
  });
  if (state.requestStatusKey) setRequestStatus(state.requestStatusKey);
  applyTheme(state.currentTheme);
  renderApiKeyVisibility();
  renderProviderModeLabel();
  if (state.apiFeedback) setApiFeedback(state.apiFeedback.key, state.apiFeedback.params, state.apiFeedback.className);
  renderStatus();
  if (state.latestPermission) renderPermission(state.latestPermission);
  if (state.latestResponse) {
    renderEvidence(state.latestResponse.evidence, state.latestResponse.tool_results);
    renderPlan(state.latestResponse.plan, state.latestResponse.tool_results);
  }
  if (state.auditEntries) renderAudit();
  if (state.benchmarkData) renderBenchmarks();
  if (state.radeonEvidence) renderRadeonEvidence(state.radeonEvidence);
}

function setActiveSection(id) {
  document.querySelectorAll(".nav-link").forEach((link) => {
    const active = link.getAttribute("href") === `#${id}`;
    link.classList.toggle("active", active);
    if (active) link.setAttribute("aria-current", "location");
    else link.removeAttribute("aria-current");
  });
}

function updateNavigation() {
  const sections = [...document.querySelectorAll(".nav-link")].map((link) => {
    const id = link.getAttribute("href").slice(1);
    const section = byId(id);
    return {id, top: section.getBoundingClientRect().top + globalThis.scrollY};
  });
  const current = document.querySelector(".nav-link.active")?.getAttribute("href")?.slice(1) || "";
  setActiveSection(activeSection(sections, globalThis.scrollY + Math.min(180, globalThis.innerHeight * .28), current));
}

function initializeNavigation() {
  document.querySelectorAll(".nav-link").forEach((link) => {
    link.addEventListener("click", () => setActiveSection(link.getAttribute("href").slice(1)));
  });
  let scheduled = false;
  const schedule = () => {
    if (scheduled) return;
    scheduled = true;
    globalThis.requestAnimationFrame(() => {
      scheduled = false;
      updateNavigation();
    });
  };
  globalThis.addEventListener("scroll", schedule, {passive: true});
  globalThis.addEventListener("resize", schedule);
  if ("IntersectionObserver" in globalThis) {
    const observer = new IntersectionObserver(schedule, {rootMargin: "-18% 0px -65% 0px"});
    document.querySelectorAll(".nav-link").forEach((link) => observer.observe(byId(link.getAttribute("href").slice(1))));
  }
  updateNavigation();
}

byId("askButton").addEventListener("click", () => runAgent());
byId("permissionButton").addEventListener("click", previewPermission);
byId("confirmButton").addEventListener("click", confirmAction);
byId("saveRocmButton").addEventListener("click", saveRocmProfile);
byId("recordBenchmarkButton").addEventListener("click", recordBenchmark);
byId("languageToggle").addEventListener("click", () => {
  applyLanguage(state.currentLanguage === "en" ? "zh-CN" : "en", true);
});
byId("themeToggle").addEventListener("click", () => applyTheme(state.currentTheme === "dark" ? "light" : "dark", true));
byId("apiToggle").addEventListener("click", () => toggleApiPanel());
byId("apiClose").addEventListener("click", () => toggleApiPanel(false));
byId("providerModeRemote").addEventListener("change", () => applyProviderMode("remote"));
byId("providerModeLocal").addEventListener("change", () => applyProviderMode("rocm-local"));
byId("apiKeyVisibility").addEventListener("click", () => {
  byId("apiKey").type = byId("apiKey").type === "password" ? "text" : "password";
  renderApiKeyVisibility();
});
byId("testApiButton").addEventListener("click", testProviderApi);
byId("applyApiButton").addEventListener("click", applyProviderApi);
byId("sampleButton").addEventListener("click", () => {
  byId("prompt").value = demoPrompt(state.currentLanguage);
  byId("prompt").focus();
});

applyTheme(state.currentTheme);
applyLanguage(state.currentLanguage);
populateProviderDefaults();
initializeNavigation();
Promise.all([loadStatus(), loadRocmProfile(), loadRadeonEvidence(), refreshMemory(), refreshAudit(), refreshBenchmarks()]);
