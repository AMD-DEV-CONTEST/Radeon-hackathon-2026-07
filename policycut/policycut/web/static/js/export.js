/* PolicyCut — export page: pre-render summary, render job progress, artifacts + audit stats. */
"use strict";

const PID = param("id");

const RENDER_STAGES = [
  ["RENDERING", "Rendering redacted frames"],
  ["MUXING", "Muxing audio & video"],
  ["AUDITING", "Building audit trail"],
  ["COMPLETE", "Complete"],
];

let project = null;
let events = [];
let job = null;
let stream = null;

/* ---------------- summary ---------------- */

function outputResolution(m) {
  if (!m) return "—";
  let w = m.width, h = m.height;
  if (m.rotation === 90 || m.rotation === 270) { const t = w; w = h; h = t; }
  if (h > 1080) {
    w = Math.round((w * 1080) / h / 2) * 2;
    h = 1080;
  }
  return `${w} × ${h}`;
}

function count(pred) { return events.filter(pred).length; }

function renderSummary() {
  const tiles = [
    [count((e) => e.kind === "visual"), "Visual events"],
    [count((e) => e.kind === "audio"), "Audio events"],
    [count((e) => e.status === "confirmed"), "Confirmed"],
    [count((e) => e.status === "ignored"), "Ignored"],
    [count((e) => e.status === "pending"), "Pending"],
    [count((e) => e.source === "manual"), "Manual"],
  ];
  qs("#summary-tiles").innerHTML = tiles
    .map(([v, k]) => `<div class="stat-tile"><div class="v">${v}</div><div class="k">${esc(k)}</div></div>`)
    .join("");

  const m = project.media;
  const rows = [
    ["Applied at render", `${count((e) => e.status === "confirmed")} confirmed event(s) — pending and ignored events are not redacted`],
    ["Source", m ? `${esc(m.filename)} · ${fmtTime(m.duration_s)} · ${m.width} × ${m.height} @ ${Number(m.fps).toFixed(2)} fps` : "—"],
    ["Output resolution", outputResolution(m)],
    ["Output format", "MP4 · H.264 + AAC · metadata stripped"],
  ];
  qs("#summary-table").innerHTML = rows
    .map(([k, v]) => `<tr><td>${esc(k)}</td><td>${v}</td></tr>`)
    .join("");
}

function pendingAutoCount() {
  return count((e) => e.source === "auto" && e.status === "pending");
}

function updateGates() {
  const pending = pendingAutoCount();
  const blocked = pending > 0;
  qs("#pending-banner").classList.toggle("hidden", !blocked);
  qs("#pending-link").href = `review.html?id=${PID}`;
  qs("#btn-render").disabled = blocked || (project.status === "rendering") || (project.status === "analyzing");

  const stale = !!project.exports_stale && project.status === "complete";
  qs("#stale-banner").classList.toggle("hidden", !stale);
}

/* ---------------- render job ---------------- */

function renderStageList() {
  const cur = job ? RENDER_STAGES.findIndex(([k]) => k === job.stage) : -1;
  qs("#render-stages").innerHTML = RENDER_STAGES.map(([key, label], i) => {
    let cls = "", icon = "";
    if (job && (job.status === "done" || i < cur)) { cls = "done"; icon = "&#10003;"; }
    if (job && job.status === "running" && i === cur) { cls = "active"; }
    if (job && job.status === "error" && i === cur) { cls = "errored"; icon = "&#10005;"; }
    return `<li class="${cls}"><span class="st-icon">${icon}</span><span>${esc(label)}</span></li>`;
  }).join("");
}

function onJobUpdate(j) {
  job = j;
  qs("#render-progress").classList.remove("hidden");
  const pct = Math.round((j.progress || 0) * 100);
  qs("#render-fill").style.width = `${pct}%`;
  qs("#render-pct").textContent = `${pct}%`;
  qs("#render-msg").textContent = j.message || j.stage || "Working…";
  renderStageList();
}

async function onJobDone(j) {
  if (j) job = j;
  renderStageList();
  if (job && job.status === "done") {
    qs("#render-msg").textContent = "Render complete.";
    toast("Render complete", "success");
    await refresh();
    showResults();
  } else if (job) {
    const b = qs("#error-banner");
    b.textContent = job.status === "cancelled"
      ? "Render was cancelled."
      : (job.error || "Render failed — see server logs.");
    b.classList.remove("hidden");
    qs("#btn-render").disabled = false;
    await refresh();
  }
}

async function startRender() {
  qs("#error-banner").classList.add("hidden");
  const btn = qs("#btn-render");
  btn.disabled = true;
  try {
    const j = await API.post(`/projects/${PID}/jobs/render`, {});
    localStorage.setItem(`pc_job_${PID}`, j.id);
    attach(j.id);
    onJobUpdate(j);
  } catch (e) {
    btn.disabled = false;
    if (e.status === 409) {
      toast(e.message || "Cannot render: pending events or another job running", "error");
      await refresh();
    } else {
      toast(`Could not start render: ${e.message}`, "error");
    }
  }
}

function attach(jobId) {
  if (stream) stream.close();
  stream = API.sse(`/jobs/${jobId}/events`, onJobUpdate, onJobDone, (e) => {
    const b = qs("#error-banner");
    b.textContent = `Lost contact with the render job: ${e.message}`;
    b.classList.remove("hidden");
  });
}

/* ---------------- results ---------------- */

function artifactUrl(kind) {
  return `${API.base}/projects/${PID}/artifacts/${kind}`;
}

async function showResults() {
  qs("#results").classList.remove("hidden");
  qs("#render-progress").classList.add("hidden");
  const v = qs("#result-video");
  // cache-bust so a re-render replaces the previous playback
  v.src = `${artifactUrl("video")}?t=${Date.now()}`;
  qs("#dl-video").href = artifactUrl("video");
  qs("#dl-srt").href = artifactUrl("srt");
  qs("#dl-audit").href = artifactUrl("audit");
  qs("#dl-zip").href = artifactUrl("zip");
  if (project.media && !project.media.has_audio) qs("#dl-srt").classList.add("hidden");

  try {
    const audit = await API.get(`/projects/${PID}/artifacts/audit`);
    renderAuditStats(audit);
  } catch (e) {
    qs("#hash-table").innerHTML = `<tr><td>Audit</td><td class="muted">not available (${esc(e.message)})</td></tr>`;
  }
}

function renderAuditStats(audit) {
  const sm = audit.stage_metrics || {};
  let wall = 0, vram = 0;
  Object.values(sm).forEach((m) => {
    if (m && isFinite(m.wall_s)) wall += Number(m.wall_s);
    if (m && isFinite(m.peak_vram_mb)) vram = Math.max(vram, Number(m.peak_vram_mb));
  });
  const dur = (audit.input && audit.input.duration_s) || (project.media && project.media.duration_s) || 0;
  const rtf = wall > 0 && dur > 0 ? (dur / wall) : null;

  const tiles = [
    [wall ? `${wall.toFixed(1)}s` : "—", "Total wall time"],
    [vram ? `${Math.round(vram)} MB` : "—", "Peak VRAM"],
    [rtf ? `${rtf.toFixed(2)}×` : "—", "Realtime factor"],
    [(audit.counts && audit.counts.confirmed != null) ? audit.counts.confirmed : "—", "Events applied"],
  ];
  qs("#perf-tiles").innerHTML = tiles
    .map(([v2, k]) => `<div class="stat-tile"><div class="v">${esc(String(v2))}</div><div class="k">${esc(k)}</div></div>`)
    .join("");

  const env = audit.environment || {};
  const fmtRes = (r) => {
    if (r == null) return "—";
    if (Array.isArray(r)) return r.join(" × ");
    if (typeof r === "object" && r.width != null) return `${r.width} × ${r.height}`;
    return String(r);
  };
  const rows = [
    ["Input SHA-256", `<span class="mono small">${esc((audit.input && audit.input.sha256) || "—")}</span>`],
    ["Output SHA-256", `<span class="mono small">${esc((audit.output && audit.output.sha256) || "—")}</span>`],
    ["Output", `${esc(fmtRes(audit.output && audit.output.resolution))} · ${audit.output && audit.output.duration_s != null ? fmtTime(audit.output.duration_s) : "—"}`],
    ["GPU", esc(env.gpu_name || "CPU")],
    ["Generated", esc(audit.generated_at || "—")],
  ];
  qs("#hash-table").innerHTML = rows
    .map(([k, v2]) => `<tr><td>${esc(k)}</td><td>${v2}</td></tr>`)
    .join("");
}

/* ---------------- boot ---------------- */

async function refresh() {
  project = await API.get(`/projects/${PID}`);
  const data = await API.get(`/projects/${PID}/events`);
  events = data.events || [];
  qs("#proj-name").textContent = project.name;
  document.title = `PolicyCut — Export ${project.name}`;
  renderSummary();
  updateGates();
}

async function init() {
  if (!PID) {
    qs("#error-banner").textContent = "Missing project id.";
    qs("#error-banner").classList.remove("hidden");
    return;
  }
  qs("#back-review").href = `review.html?id=${PID}`;
  qs("#btn-render").addEventListener("click", startRender);
  qs("#btn-rerender").addEventListener("click", startRender);

  try {
    await refresh();
  } catch (e) {
    qs("#error-banner").textContent = `Could not load project: ${e.message}`;
    qs("#error-banner").classList.remove("hidden");
    return;
  }

  if (project.status === "complete") {
    showResults();
  } else if (project.status === "rendering") {
    // reattach to an in-flight render if we know its id
    const jobId = localStorage.getItem(`pc_job_${PID}`);
    if (jobId) {
      qs("#btn-render").disabled = true;
      attach(jobId);
    } else {
      // unknown job id: poll the project until the render settles
      const timer = setInterval(async () => {
        try {
          await refresh();
          if (project.status !== "rendering") {
            clearInterval(timer);
            if (project.status === "complete") showResults();
          }
        } catch (_) {}
      }, 2000);
    }
  }
}

document.addEventListener("DOMContentLoaded", init);
