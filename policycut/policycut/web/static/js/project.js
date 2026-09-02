/* PolicyCut — project setup page: upload source, author + interpret policy, start analysis. */
"use strict";

const PID = param("id");

const EXAMPLE_1 = "Pixelate every face, license plate, identity document and screen. Beep phone numbers, email addresses and street addresses.";
const EXAMPLE_2 = "Blur faces only. Mute phone numbers. Do not blur screens.";

const DEFAULT_PROMPTS = {
  face: ["human face"],
  license_plate: ["license plate", "vehicle registration plate"],
  id_document: ["identity card", "passport", "driver's license"],
  screen: ["computer monitor", "laptop screen", "smartphone screen", "tablet screen"],
};

const CAT_LABELS = {
  face: "Face",
  license_plate: "License plate",
  id_document: "ID document",
  screen: "Screen",
  phone: "Phone number",
  email: "Email address",
  address: "Street address",
};

const SOURCE_LABELS = { llm: "LLM", llm_repaired: "LLM repaired", keyword_fallback: "Keyword fallback" };

let project = null;
let parsedSpec = null; // last spec from /policy/parse (or rebuilt), source of prompts/paddings
let blobUrl = null;

/* ---------------- project + media ---------------- */

async function loadProject() {
  if (!PID) {
    qs("#error-banner").textContent = "Missing project id. Go back and open a project from the home page.";
    qs("#error-banner").classList.remove("hidden");
    return;
  }
  try {
    project = await API.get(`/projects/${PID}`);
  } catch (e) {
    qs("#error-banner").textContent = `Could not load project: ${e.message}`;
    qs("#error-banner").classList.remove("hidden");
    return;
  }
  qs("#proj-name").textContent = project.name;
  document.title = `PolicyCut — ${project.name}`;
  setStatusChip(project.status);
  if (project.error) {
    qs("#error-banner").textContent = `Last run failed: ${project.error}`;
    qs("#error-banner").classList.remove("hidden");
  }
  qs("#policy-text").value = project.policy_text || EXAMPLE_1;
  if (project.media) {
    renderMedia(project.media);
    // Best effort: normalized preview exists once analysis has run at least once.
    const v = qs("#preview-video");
    v.src = `${API.base}/projects/${PID}/preview/original`;
    v.addEventListener("error", () => {
      v.classList.add("hidden");
      qs("#preview-missing").classList.remove("hidden");
    }, { once: true });
  }
  updateAnalyzeEnabled();
}

function setStatusChip(status) {
  const chip = qs("#proj-status");
  chip.className = `chip ${status}`;
  const labels = { draft: "Draft", analyzing: "Analyzing", review_ready: "Review ready", rendering: "Rendering", complete: "Complete", error: "Error" };
  chip.innerHTML = `<span class="dot"></span>${esc(labels[status] || status)}`;
}

function renderMedia(m) {
  qs("#dropzone").classList.add("hidden");
  qs("#media-section").classList.remove("hidden");
  const rows = [
    ["File", m.filename],
    ["Duration", fmtTime(m.duration_s)],
    ["Resolution", `${m.width} × ${m.height}${m.rotation ? ` (rotated ${m.rotation}°)` : ""}`],
    ["Frame rate", `${Number(m.fps).toFixed(2)} fps`],
    ["Video codec", m.codec],
    ["Audio", m.has_audio ? (m.audio_codec || "yes") : "none"],
    ["Size", fmtBytes(m.size_bytes)],
  ];
  qs("#media-table").innerHTML = rows
    .map(([k, v]) => `<tr><td>${esc(k)}</td><td>${esc(v)}</td></tr>`)
    .join("");
}

async function uploadFile(file) {
  if (!file) return;
  const prog = qs("#upload-progress");
  prog.classList.remove("hidden");
  qs("#upload-label").textContent = `Uploading ${file.name} (${fmtBytes(file.size)})…`;
  try {
    const updated = await API.upload(`/projects/${PID}/source`, file, (f) => {
      const pct = Math.round(f * 100);
      qs("#upload-fill").style.width = `${pct}%`;
      qs("#upload-pct").textContent = `${pct}%`;
      if (f >= 1) qs("#upload-label").textContent = "Probing video on server…";
    });
    project = updated;
    prog.classList.add("hidden");
    renderMedia(project.media);
    // Local preview straight from the uploaded file — no server round-trip.
    if (blobUrl) URL.revokeObjectURL(blobUrl);
    blobUrl = URL.createObjectURL(file);
    const v = qs("#preview-video");
    v.classList.remove("hidden");
    qs("#preview-missing").classList.add("hidden");
    v.src = blobUrl;
    setStatusChip(project.status);
    updateAnalyzeEnabled();
    toast("Video uploaded", "success");
  } catch (e) {
    prog.classList.add("hidden");
    qs("#upload-fill").style.width = "0%";
    toast(`Upload failed: ${e.message}`, "error");
  }
}

/* ---------------- policy interpretation ---------------- */

async function interpretPolicy() {
  const text = qs("#policy-text").value.trim();
  if (!text) { toast("Write a policy first", "error"); return; }
  const btn = qs("#btn-interpret");
  btn.disabled = true;
  btn.textContent = "Interpreting…";
  try {
    const res = await API.post(`/projects/${PID}/policy/parse`, { text });
    parsedSpec = res.spec;
    renderRules(parsedSpec, res.source);
    updateAnalyzeEnabled();
  } catch (e) {
    toast(`Policy interpretation failed: ${e.message}`, "error");
  } finally {
    btn.disabled = false;
    btn.textContent = "Interpret Policy";
  }
}

function renderRules(spec, source) {
  qs("#rules-section").classList.remove("hidden");
  const badge = qs("#parse-source");
  badge.textContent = SOURCE_LABELS[source] || source || "—";
  badge.className = "src-badge" + (source === "keyword_fallback" ? " fallback" : "");

  const vBox = qs("#rules-visual");
  vBox.innerHTML = (spec.visual_targets || []).map((t, i) => `
    <div class="rule-row" data-kind="visual" data-i="${i}">
      <input type="checkbox" class="rule-on" checked title="Enable rule">
      <span class="rule-kind">Visual</span>
      <span class="rule-cat">${esc(CAT_LABELS[t.category] || t.category)}</span>
      <select class="rule-action">
        <option value="blur"${t.action.type === "blur" ? " selected" : ""}>Blur</option>
        <option value="pixelate"${t.action.type === "pixelate" ? " selected" : ""}>Pixelate</option>
        <option value="solid"${t.action.type === "solid" ? " selected" : ""}>Solid</option>
      </select>
      <input type="range" class="rule-strength grow" min="1" max="100" value="${Number(t.action.strength) || 65}" title="Strength">
      <span class="strength-val">${Number(t.action.strength) || 65}</span>
    </div>`).join("");

  const aBox = qs("#rules-audio");
  aBox.innerHTML = (spec.audio_targets || []).map((t, i) => `
    <div class="rule-row" data-kind="audio" data-i="${i}">
      <input type="checkbox" class="rule-on" checked title="Enable rule">
      <span class="rule-kind">Audio</span>
      <span class="rule-cat">${esc(CAT_LABELS[t.category] || t.category)}</span>
      <select class="rule-action">
        <option value="mute"${t.action.type === "mute" ? " selected" : ""}>Mute</option>
        <option value="beep"${t.action.type === "beep" ? " selected" : ""}>Beep</option>
      </select>
      <span class="grow"></span>
    </div>`).join("");

  qs("#rules-unsupported").innerHTML = (spec.unsupported_terms || []).map((t) => `
    <div class="rule-row unsupported">&#9888; Unsupported target: ${esc(t)} <span class="grow"></span>
      <span class="small" style="font-weight:400;">will be skipped</span></div>`).join("");

  if (!(spec.visual_targets || []).length && !(spec.audio_targets || []).length) {
    vBox.innerHTML = `<div class="rule-row"><span class="muted">No supported targets found in this policy. Add faces, plates, IDs, screens, phone numbers, emails or addresses.</span></div>`;
  }

  // live wiring
  qsa(".rule-row", qs("#rules-section")).forEach((row) => {
    const cb = qs(".rule-on", row);
    if (cb) cb.addEventListener("change", () => {
      row.classList.toggle("disabled", !cb.checked);
      markPolicyDirty();
    });
    const strength = qs(".rule-strength", row);
    if (strength) strength.addEventListener("input", () => {
      qs(".strength-val", row).textContent = strength.value;
      markPolicyDirty();
    });
    const action = qs(".rule-action", row);
    if (action) action.addEventListener("change", markPolicyDirty);
  });
  markPolicyDirty();
}

function markPolicyDirty() {
  const el = qs("#policy-saved");
  el.textContent = "Not saved";
  el.className = "save-state saving";
}

/** Rebuild a PolicySpec from the UI rows (only enabled ones). */
function buildSpecFromUI() {
  if (!parsedSpec) return null;
  const visual = [];
  qsa('#rules-visual .rule-row').forEach((row) => {
    if (!qs(".rule-on", row).checked) return;
    const t = parsedSpec.visual_targets[Number(row.dataset.i)];
    if (!t) return;
    visual.push({
      category: t.category,
      prompts: (t.prompts && t.prompts.length) ? t.prompts : (DEFAULT_PROMPTS[t.category] || [t.category]),
      action: {
        type: qs(".rule-action", row).value,
        strength: Number(qs(".rule-strength", row).value) || 65,
      },
    });
  });
  const audio = [];
  qsa('#rules-audio .rule-row').forEach((row) => {
    if (!qs(".rule-on", row).checked) return;
    const t = parsedSpec.audio_targets[Number(row.dataset.i)];
    if (!t) return;
    audio.push({
      category: t.category,
      action: { type: qs(".rule-action", row).value },
      padding_before_ms: t.padding_before_ms != null ? t.padding_before_ms : 150,
      padding_after_ms: t.padding_after_ms != null ? t.padding_after_ms : 250,
    });
  });
  return {
    schema_version: parsedSpec.schema_version || "1.0",
    language: parsedSpec.language || "en",
    visual_targets: visual,
    audio_targets: audio,
    unsupported_terms: parsedSpec.unsupported_terms || [],
    review_required: true,
  };
}

async function savePolicy(silent) {
  const spec = buildSpecFromUI();
  if (!spec) {
    if (!silent) toast("Interpret the policy first", "error");
    return false;
  }
  const el = qs("#policy-saved");
  el.textContent = "Saving…";
  el.className = "save-state saving";
  try {
    await API.put(`/projects/${PID}/policy`, { spec });
    el.textContent = "Saved";
    el.className = "save-state saved";
    if (!silent) toast("Policy saved", "success");
    return true;
  } catch (e) {
    el.textContent = "Save failed";
    el.className = "save-state";
    toast(`Could not save policy: ${e.message}`, "error");
    return false;
  }
}

/* ---------------- analysis ---------------- */

function updateAnalyzeEnabled() {
  const busy = project && (project.status === "analyzing" || project.status === "rendering");
  qs("#btn-analyze").disabled = !(project && project.media) || !!busy;
}

async function startAnalysis() {
  const btn = qs("#btn-analyze");
  btn.disabled = true;
  btn.textContent = "Starting…";
  try {
    // Make sure a policy exists server-side: interpret from text if needed.
    if (!parsedSpec) {
      const text = qs("#policy-text").value.trim() || EXAMPLE_1;
      const res = await API.post(`/projects/${PID}/policy/parse`, { text });
      parsedSpec = res.spec;
      renderRules(parsedSpec, res.source);
    }
    const ok = await savePolicy(true);
    if (!ok) throw new Error("policy could not be saved");
    const job = await API.post(`/projects/${PID}/jobs/analysis`, {});
    localStorage.setItem(`pc_job_${PID}`, job.id);
    location.href = `processing.html?id=${PID}&job=${job.id}`;
  } catch (e) {
    toast(`Could not start analysis: ${e.message}`, "error");
    btn.disabled = false;
    btn.textContent = "Start Analysis →";
  }
}

/* ---------------- wiring ---------------- */

function init() {
  const dz = qs("#dropzone");
  const fi = qs("#file-input");
  dz.addEventListener("click", () => fi.click());
  fi.addEventListener("change", () => uploadFile(fi.files[0]));
  ["dragenter", "dragover"].forEach((ev) =>
    dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add("dragover"); })
  );
  ["dragleave", "drop"].forEach((ev) =>
    dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.remove("dragover"); })
  );
  dz.addEventListener("drop", (e) => {
    const f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
    if (f) uploadFile(f);
  });
  // allow dropping anywhere on the page too
  document.addEventListener("dragover", (e) => e.preventDefault());
  document.addEventListener("drop", (e) => e.preventDefault());

  qs("#btn-replace").addEventListener("click", () => {
    qs("#media-section").classList.add("hidden");
    qs("#dropzone").classList.remove("hidden");
    fi.value = "";
    fi.click();
  });

  qs("#btn-example1").addEventListener("click", () => { qs("#policy-text").value = EXAMPLE_1; });
  qs("#btn-example2").addEventListener("click", () => { qs("#policy-text").value = EXAMPLE_2; });
  qs("#btn-interpret").addEventListener("click", interpretPolicy);
  qs("#btn-save-policy").addEventListener("click", () => savePolicy(false));
  qs("#btn-analyze").addEventListener("click", startAnalysis);

  loadProject();
}

document.addEventListener("DOMContentLoaded", init);
