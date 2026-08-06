/* PolicyCut — processing page: live job progress via SSE with polling fallback. */
"use strict";

const PID = param("id");
let JOB_ID = param("job");

const ANALYSIS_STAGES = [
  ["NORMALIZING", "Normalizing media"],
  ["PARSING_POLICY", "Loading policy"],
  ["TRANSCRIBING", "Transcribing audio"],
  ["DETECTING_PII", "Detecting audio PII"],
  ["DETECTING_VISUAL", "Detecting visual targets"],
  ["TRACKING", "Tracking objects"],
  ["BUILDING_PREVIEW", "Building review preview"],
  ["REVIEW_READY", "Review ready"],
];

const RENDER_STAGES = [
  ["RENDERING", "Rendering redacted frames"],
  ["MUXING", "Muxing audio & video"],
  ["AUDITING", "Building audit trail"],
  ["COMPLETE", "Complete"],
];

let stages = ANALYSIS_STAGES;
let job = null;
let stream = null;
let tickTimer = null;

function stageIndex(name) {
  return stages.findIndex(([key]) => key === name);
}

function renderStages() {
  const cur = job ? stageIndex(job.stage) : -1;
  const failed = job && (job.status === "error");
  qs("#stage-list").innerHTML = stages.map(([key, label], i) => {
    let cls = "", icon = "";
    if (job && (job.status === "done" || i < cur || (i === cur && i === stages.length - 1 && job.status === "done"))) {
      cls = "done"; icon = "&#10003;";
    }
    if (i === cur && job && job.status === "running") { cls = "active"; icon = ""; }
    if (i === cur && failed) { cls = "errored"; icon = "&#10005;"; }
    if (job && job.status === "done") { cls = "done"; icon = "&#10003;"; }
    return `<li class="${cls}"><span class="st-icon">${icon}</span><span>${esc(label)}</span></li>`;
  }).join("");
}

function renderMetricsTable() {
  const body = qs("#metrics-table tbody");
  const metrics = (job && job.metrics) || {};
  const order = stages.map(([k]) => k).filter((k) => metrics[k]);
  // include any extra metric keys not in the canonical list
  Object.keys(metrics).forEach((k) => { if (!order.includes(k)) order.push(k); });
  if (!order.length) {
    body.innerHTML = `<tr><td colspan="5" class="muted">No stage metrics yet.</td></tr>`;
    return;
  }
  body.innerHTML = order.map((k) => {
    const m = metrics[k] || {};
    const fps = m.fps != null ? m.fps : m.effective_fps;
    return `<tr>
      <td>${esc(k)}</td>
      <td class="mono">${m.wall_s != null ? Number(m.wall_s).toFixed(1) : "—"}</td>
      <td class="mono">${fps != null ? Number(fps).toFixed(1) : "—"}</td>
      <td class="mono">${m.peak_vram_mb != null ? Math.round(m.peak_vram_mb) : "—"}</td>
      <td class="mono">${esc(m.precision || "—")}</td>
    </tr>`;
  }).join("");
}

function renderProgress() {
  if (!job) return;
  const pct = Math.round((job.progress || 0) * 100);
  qs("#overall-fill").style.width = `${pct}%`;
  qs("#overall-pct").textContent = `${pct}%`;
  const stageLabel = (stages.find(([k]) => k === job.stage) || [null, job.stage])[1];
  qs("#current-msg").textContent = job.message || stageLabel || "Working…";
}

function renderClock() {
  if (!job) return;
  let elapsed = 0;
  if (job.started_at) {
    const end = job.finished_at ? new Date(job.finished_at).getTime() : Date.now();
    elapsed = Math.max(0, (end - new Date(job.started_at).getTime()) / 1000);
  }
  const mm = Math.floor(elapsed / 60);
  const ss = String(Math.floor(elapsed % 60)).padStart(2, "0");
  qs("#m-elapsed").textContent = `${mm}:${ss}`;

  const p = job.progress || 0;
  if (job.status === "running" && p > 0.03 && elapsed > 2) {
    const eta = elapsed * (1 - p) / p;
    const em = Math.floor(eta / 60);
    const es2 = String(Math.floor(eta % 60)).padStart(2, "0");
    qs("#m-eta").textContent = `${em}:${es2}`;
  } else if (job.status === "done") {
    qs("#m-eta").textContent = "0:00";
  } else {
    qs("#m-eta").textContent = "—";
  }
}

function onJobUpdate(j) {
  job = j;
  if (job.type === "render" && stages !== RENDER_STAGES) {
    stages = RENDER_STAGES;
    qs("#page-title").textContent = "Rendering redacted video";
  }
  renderStages();
  renderProgress();
  renderMetricsTable();
  renderClock();
}

function onJobDone(j) {
  if (j) job = j;
  renderStages(); renderProgress(); renderMetricsTable(); renderClock();
  const status = job ? job.status : "error";
  if (status === "done") {
    qs("#current-msg").textContent = "Done — opening next step…";
    const target = job.type === "render" ? `export.html?id=${PID}` : `review.html?id=${PID}`;
    setTimeout(() => { location.href = target; }, 700);
    return;
  }
  qs("#btn-cancel").classList.add("hidden");
  qs("#btn-retry").classList.remove("hidden");
  if (status === "cancelled") {
    qs("#cancel-banner").classList.remove("hidden");
  } else {
    const msg = status === "server_restarted"
      ? "The server restarted while this job was running. Retry to run it again."
      : (job && job.error) || "Job failed.";
    const b = qs("#error-banner");
    b.textContent = msg;
    b.classList.remove("hidden");
  }
}

function attach() {
  if (stream) stream.close();
  qs("#error-banner").classList.add("hidden");
  qs("#cancel-banner").classList.add("hidden");
  qs("#btn-retry").classList.add("hidden");
  qs("#btn-cancel").classList.remove("hidden");
  stream = API.sse(`/jobs/${JOB_ID}/events`, onJobUpdate, onJobDone, (e) => {
    const b = qs("#error-banner");
    b.textContent = `Lost contact with the job: ${e.message}`;
    b.classList.remove("hidden");
    qs("#btn-retry").classList.remove("hidden");
  });
}

async function cancelJob() {
  if (!JOB_ID) return;
  qs("#btn-cancel").disabled = true;
  try {
    await API.post(`/jobs/${JOB_ID}/cancel`, {});
    toast("Cancel requested", "info");
  } catch (e) {
    toast(`Cancel failed: ${e.message}`, "error");
  } finally {
    qs("#btn-cancel").disabled = false;
  }
}

async function retryJob() {
  const type = (job && job.type) || "analysis";
  qs("#btn-retry").disabled = true;
  try {
    const newJob = await API.post(`/projects/${PID}/jobs/${type}`, {});
    JOB_ID = newJob.id;
    localStorage.setItem(`pc_job_${PID}`, newJob.id);
    history.replaceState(null, "", `processing.html?id=${PID}&job=${newJob.id}`);
    job = newJob;
    onJobUpdate(newJob);
    attach();
  } catch (e) {
    toast(`Retry failed: ${e.message}`, "error");
  } finally {
    qs("#btn-retry").disabled = false;
  }
}

async function init() {
  if (!PID) {
    qs("#error-banner").textContent = "Missing project id.";
    qs("#error-banner").classList.remove("hidden");
    return;
  }
  API.get(`/projects/${PID}`).then((p) => {
    qs("#proj-name").textContent = p.name;
    document.title = `PolicyCut — Processing ${p.name}`;
  }).catch(() => {});
  API.get("/system").then((sys) => {
    const gpu = (sys.gpu || {});
    const chip = qs("#gpu-chip");
    if (gpu.available && gpu.name) {
      chip.className = "chip ok";
      chip.innerHTML = `<span class="dot"></span><span>${esc(gpu.name)}</span>`;
      qs("#m-gpu").textContent = gpu.name;
    } else {
      chip.className = "chip warn";
      chip.innerHTML = `<span class="dot"></span><span>CPU fallback</span>`;
      qs("#m-gpu").textContent = "CPU";
    }
  }).catch(() => {});

  if (!JOB_ID) JOB_ID = localStorage.getItem(`pc_job_${PID}`) || "";
  if (!JOB_ID) {
    qs("#error-banner").innerHTML =
      `No job reference found. <a href="project.html?id=${esc(PID)}">Go back to the project</a> and start the analysis again.`;
    qs("#error-banner").classList.remove("hidden");
    qs("#btn-cancel").classList.add("hidden");
    return;
  }

  renderStages();
  renderMetricsTable();
  attach();

  qs("#btn-cancel").addEventListener("click", cancelJob);
  qs("#btn-retry").addEventListener("click", retryJob);
  tickTimer = setInterval(renderClock, 1000);
}

document.addEventListener("DOMContentLoaded", init);
