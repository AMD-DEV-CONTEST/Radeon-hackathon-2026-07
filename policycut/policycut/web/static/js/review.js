/* PolicyCut — Review Workspace.
 *
 * Layout: left event list, center video + overlay canvas, right property
 * panel, bottom two-lane timeline. All event mutations are optimistic-free:
 * they PATCH with expected_revision and reload on 409 conflicts.
 */
"use strict";

const PID = param("id");

const STATUS_COLORS = { pending: "#f5a623", confirmed: "#3fb950", ignored: "#6b7280" };
const CAT_LABELS = {
  face: "Face", license_plate: "License plate", id_document: "ID document",
  screen: "Screen", phone: "Phone", email: "Email", address: "Address", manual: "Manual",
};

let project = null;
let events = [];
let revision = 0;
let fps = 30;
let duration = 0;

let selectedId = null;
let filter = "all";
let videoMode = "overlay"; // "overlay" | "original"

let video, overlayCanvas, overlayCtx, tlCanvas, tlCtx, videoWrap;

/* add-region state */
let addingRegion = false;
let dragStart = null;       // {x, y} css px on canvas
let dragRect = null;        // {x, y, w, h} css px
let pendingRegion = null;   // normalized {x, y, w, h}

/* timeline state */
let tlZoom = 1;
let tlOffset = 0;           // left edge, seconds
let tlDrag = null;          // {mode:"scrub"|"edge-l"|"edge-r", id}

/* autosave */
let pendingChanges = null;  // {id, changes}
let saveTimer = null;

/* play-context watcher */
let ctxWatcher = null;

/* ======================= data ======================= */

function evById(id) { return events.find((e) => e.id === id); }
function sortedEvents() { return events.slice().sort((a, b) => a.start_s - b.start_s || a.id.localeCompare(b.id)); }
function pendingCount() { return events.filter((e) => e.status === "pending").length; }

async function reloadEvents() {
  const data = await API.get(`/projects/${PID}/events`);
  events = data.events || [];
  revision = data.revision || 0;
  if (selectedId && !evById(selectedId)) selectedId = null;
  renderList();
  renderProps();
  renderBadges();
}

function setSaveState(state) {
  const el = qs("#save-state");
  if (state === "saving") { el.textContent = "Saving…"; el.className = "save-state saving"; }
  else if (state === "saved") { el.textContent = "Saved"; el.className = "save-state saved"; }
  else { el.textContent = state; el.className = "save-state"; }
}

async function apiMutate(fn) {
  setSaveState("saving");
  try {
    const out = await fn();
    revision += 1;
    setSaveState("saved");
    return out;
  } catch (e) {
    if (e.status === 409) {
      await reloadEvents();
      setSaveState("saved");
      toast("Events changed elsewhere — view reloaded", "error");
    } else {
      setSaveState("save failed");
      toast(e.message, "error");
    }
    throw e;
  }
}

async function patchEvent(id, changes) {
  try {
    const updated = await apiMutate(() =>
      API.patch(`/projects/${PID}/events/${id}`, Object.assign({}, changes, { expected_revision: revision }))
    );
    const i = events.findIndex((e) => e.id === id);
    if (i >= 0 && updated && updated.id) events[i] = updated;
    renderList();
    if (selectedId === id) renderProps();
    renderBadges();
  } catch (_) { /* handled in apiMutate */ }
}

function queuePatch(id, changes) {
  if (pendingChanges && pendingChanges.id !== id) flushPatch();
  pendingChanges = pendingChanges || { id, changes: {} };
  Object.assign(pendingChanges.changes, changes);
  // optimistic local update so the overlay/timeline track the inputs live
  const ev = evById(id);
  if (ev) Object.assign(ev, changes);
  setSaveState("saving");
  clearTimeout(saveTimer);
  saveTimer = setTimeout(flushPatch, 550);
}

function flushPatch() {
  clearTimeout(saveTimer);
  if (!pendingChanges) return;
  const { id, changes } = pendingChanges;
  pendingChanges = null;
  patchEvent(id, changes);
}

async function createEvent(fields) {
  try {
    const created = await apiMutate(() =>
      API.post(`/projects/${PID}/events`, Object.assign({}, fields, { expected_revision: revision }))
    );
    if (created && created.id) {
      events.push(created);
      selectEvent(created.id, { seek: false });
    } else {
      await reloadEvents();
    }
    renderList();
    renderBadges();
    toast("Manual event added", "success");
  } catch (_) {}
}

async function deleteEvent(id) {
  try {
    await apiMutate(() => API.del(`/projects/${PID}/events/${id}?expected_revision=${revision}`));
    events = events.filter((e) => e.id !== id);
    if (selectedId === id) selectedId = null;
    renderList(); renderProps(); renderBadges();
    toast("Manual event deleted", "success");
  } catch (_) {}
}

/* ======================= left: event list ======================= */

function renderBadges() {
  const n = pendingCount();
  const badge = qs("#pending-badge");
  badge.textContent = String(n);
  badge.classList.toggle("zero", n === 0);
}

function renderList() {
  const box = qs("#event-list");
  const list = sortedEvents().filter((e) => filter === "all" || e.status === filter);

  const counts = { all: events.length, pending: 0, confirmed: 0, ignored: 0 };
  events.forEach((e) => { counts[e.status] = (counts[e.status] || 0) + 1; });
  qsa("#filter-tabs button").forEach((b) => {
    const f = b.dataset.f;
    b.textContent = `${f[0].toUpperCase()}${f.slice(1)} (${counts[f] || 0})`;
    b.classList.toggle("active", f === filter);
  });

  if (!list.length) {
    box.innerHTML = `<div class="muted small" style="padding:14px;">No ${filter === "all" ? "" : filter + " "}events.</div>`;
    return;
  }
  box.innerHTML = list.map((e) => {
    const icon = e.kind === "visual" ? "&#9635;" : "&#9834;";
    const conf = Math.round((e.confidence != null ? e.confidence : 1) * 100);
    const warn = (e.warnings && e.warnings.length) ? `<span class="ev-warn" title="${esc(e.warnings.join(", "))}">&#9888;</span>` : "";
    const label = e.kind === "audio" && e.text_preview ? e.text_preview : (CAT_LABELS[e.category] || e.category);
    return `<div class="event-row${e.id === selectedId ? " selected" : ""}" data-id="${esc(e.id)}">
      <span class="ev-icon" title="${e.kind}">${icon}</span>
      <div class="ev-main">
        <div class="ev-cat">${esc(label)}${e.source === "manual" ? ' <span class="muted small">(manual)</span>' : ""}</div>
        <div class="ev-range">${fmtTime(e.start_s)} &ndash; ${fmtTime(e.end_s)}</div>
      </div>
      <span class="ev-conf">${conf}%</span>
      ${warn}
      <span class="status-dot ${esc(e.status)}" title="${esc(e.status)}"></span>
    </div>`;
  }).join("");

  qsa(".event-row", box).forEach((row) => {
    row.addEventListener("click", () => selectEvent(row.dataset.id, { seek: true }));
  });
}

function selectEvent(id, opts) {
  flushPatch();
  selectedId = id;
  const ev = evById(id);
  renderList();
  renderProps();
  if (ev && opts && opts.seek) {
    seekTo(ev.start_s + 0.001);
  }
  const row = qs(`.event-row[data-id="${id}"]`);
  if (row && row.scrollIntoView) row.scrollIntoView({ block: "nearest" });
}

/* ======================= right: property panel ======================= */

function renderProps() {
  const ev = evById(selectedId);
  qs("#prop-empty").classList.toggle("hidden", !!ev);
  const body = qs("#prop-body");
  body.classList.toggle("hidden", !ev);
  if (!ev) { body.innerHTML = ""; return; }

  const step = (1 / fps).toFixed(4);
  const isVisual = ev.kind === "visual";
  const isManual = ev.source === "manual";
  const conf = Math.round((ev.confidence != null ? ev.confidence : 1) * 100);
  const actionType = (ev.action && ev.action.type) || (isVisual ? "pixelate" : "mute");
  const strength = (ev.action && ev.action.strength) || 65;

  const catOptions = ["face", "license_plate", "id_document", "screen", "manual"]
    .map((c) => `<option value="${c}"${ev.category === c ? " selected" : ""}>${CAT_LABELS[c]}</option>`).join("");
  const visualActions = ["blur", "pixelate", "solid"]
    .map((a) => `<option value="${a}"${actionType === a ? " selected" : ""}>${a[0].toUpperCase()}${a.slice(1)}</option>`).join("");
  const audioActions = ["mute", "beep"]
    .map((a) => `<option value="${a}"${actionType === a ? " selected" : ""}>${a[0].toUpperCase()}${a.slice(1)}</option>`).join("");

  body.innerHTML = `
    <h3>Selected event</h3>
    <div class="row" style="margin-bottom:6px;">
      <span class="status-dot ${esc(ev.status)}"></span>
      <strong style="text-transform:capitalize;">${esc(CAT_LABELS[ev.category] || ev.category)}</strong>
      <span class="muted small">${esc(ev.kind)} &middot; ${esc(ev.source)}</span>
    </div>
    ${ev.kind === "audio" && ev.text_preview ? `<div class="small muted" style="margin-bottom:6px;">${esc(ev.text_preview)}</div>` : ""}
    ${ev.manual_fixed_region ? `<div class="small amber-text" style="margin-bottom:6px;">Manual fixed region</div>` : ""}
    <div class="row" style="margin-bottom:10px;">
      <button class="btn sm ${ev.status === "confirmed" ? "active" : ""}" id="p-confirm">&#10003; Confirm</button>
      <button class="btn sm ${ev.status === "ignored" ? "active" : ""}" id="p-ignore">&#8709; Ignore</button>
      ${isManual ? `<button class="btn sm danger" id="p-delete">Delete</button>` : ""}
    </div>
    <div class="prop-grid">
      <label class="field">Start (s)
        <input type="number" id="p-start" min="0" step="${step}" value="${Number(ev.start_s).toFixed(3)}">
      </label>
      <label class="field">End (s)
        <input type="number" id="p-end" min="0" step="${step}" value="${Number(ev.end_s).toFixed(3)}">
      </label>
      ${isVisual ? `
      <label class="field">Category
        <select id="p-category">${catOptions}</select>
      </label>
      <label class="field">Action
        <select id="p-action">${visualActions}</select>
      </label>
      <label class="field full">Strength <span class="strength-val" id="p-strength-val">${strength}</span>
        <input type="range" id="p-strength" min="1" max="100" value="${strength}">
      </label>` : `
      <label class="field">Action
        <select id="p-action">${audioActions}</select>
      </label>
      <label class="field">Confidence
        <span style="padding:7px 0;" class="mono">${conf}%</span>
      </label>`}
    </div>
    ${isVisual ? `<div class="small muted" style="margin-top:6px;">Confidence <span class="mono">${conf}%</span>${ev.track_id ? ` &middot; track <span class="mono">${esc(ev.track_id)}</span>` : ""}</div>` : ""}
    ${(ev.warnings && ev.warnings.length) ? `<ul class="warning-list" style="margin-top:8px;">${ev.warnings.map((w) => `<li>${esc(w)}</li>`).join("")}</ul>` : ""}
    <hr class="sep">
    <div class="col">
      <button class="btn sm" id="p-context">&#9654; Play context (&plusmn;2s)</button>
      <button class="btn sm" id="btn-lowest-conf">Jump to lowest confidence</button>
    </div>`;

  qs("#p-confirm", body).addEventListener("click", () => patchEvent(ev.id, { status: "confirmed" }));
  qs("#p-ignore", body).addEventListener("click", () => patchEvent(ev.id, { status: "ignored" }));
  const del = qs("#p-delete", body);
  if (del) del.addEventListener("click", () => deleteEvent(ev.id));

  qs("#p-start", body).addEventListener("input", (e) => {
    const v = parseFloat(e.target.value);
    if (isFinite(v) && v >= 0 && v < ev.end_s) queuePatch(ev.id, { start_s: v });
  });
  qs("#p-end", body).addEventListener("input", (e) => {
    const v = parseFloat(e.target.value);
    if (isFinite(v) && v > ev.start_s) queuePatch(ev.id, { end_s: Math.min(v, duration || v) });
  });
  const catSel = qs("#p-category", body);
  if (catSel) catSel.addEventListener("change", (e) => patchEvent(ev.id, { category: e.target.value }));
  qs("#p-action", body).addEventListener("change", (e) => {
    const action = isVisual
      ? { type: e.target.value, strength: Number((qs("#p-strength", body) || {}).value) || strength }
      : { type: e.target.value };
    patchEvent(ev.id, { action });
  });
  const sl = qs("#p-strength", body);
  if (sl) sl.addEventListener("input", (e) => {
    qs("#p-strength-val", body).textContent = e.target.value;
    queuePatch(ev.id, { action: { type: qs("#p-action", body).value, strength: Number(e.target.value) } });
  });
  qs("#p-context", body).addEventListener("click", () => playContext(ev));
  qs("#btn-lowest-conf", body).addEventListener("click", jumpLowestConfidence);
}

function playContext(ev) {
  if (ctxWatcher) { video.removeEventListener("timeupdate", ctxWatcher); ctxWatcher = null; }
  const stopAt = Math.min(duration || ev.end_s + 2, ev.end_s + 2);
  seekTo(Math.max(0, ev.start_s - 2));
  video.play().catch(() => {});
  ctxWatcher = () => {
    if (video.currentTime >= stopAt) {
      video.pause();
      video.removeEventListener("timeupdate", ctxWatcher);
      ctxWatcher = null;
    }
  };
  video.addEventListener("timeupdate", ctxWatcher);
}

function jumpLowestConfidence() {
  let pool = events.filter((e) => e.kind === "visual" && e.status === "pending");
  if (!pool.length) pool = events.filter((e) => e.kind === "visual");
  if (!pool.length) { toast("No visual events", "info"); return; }
  const target = pool.reduce((a, b) => ((a.confidence != null ? a.confidence : 1) <= (b.confidence != null ? b.confidence : 1) ? a : b));
  selectEvent(target.id, { seek: true });
}

/* ======================= center: video + overlay ======================= */

function videoUrl(mode) {
  return `${API.base}/projects/${PID}/preview/${mode === "overlay" ? "overlay" : "original"}`;
}

function seekTo(t) {
  if (!isFinite(t)) return;
  video.currentTime = Math.max(0, Math.min(t, (duration || t)));
}

function toggleSource() {
  const t = video.currentTime;
  const wasPaused = video.paused;
  videoMode = videoMode === "overlay" ? "original" : "overlay";
  qs("#t-toggle-src").textContent = videoMode === "overlay" ? "Overlay" : "Original";
  video.src = videoUrl(videoMode);
  video.addEventListener("loadedmetadata", function once() {
    video.removeEventListener("loadedmetadata", once);
    video.currentTime = t;
    if (!wasPaused) video.play().catch(() => {});
  });
  video.load();
}

/** Content rect of the (letterboxed) video inside its element, css px. */
function contentRect() {
  const W = videoWrap.clientWidth, H = videoWrap.clientHeight;
  const vw = video.videoWidth || 16, vh = video.videoHeight || 9;
  const scale = Math.min(W / vw, H / vh);
  const cw = vw * scale, ch = vh * scale;
  return { x: (W - cw) / 2, y: (H - ch) / 2, w: cw, h: ch };
}

/** Interpolated normalized box of a visual event at time t (clamped to keyframes). */
function boxAt(ev, t) {
  const bs = ev.boxes || [];
  if (!bs.length) return null;
  if (bs.length === 1 || t <= bs[0].t) return bs[0];
  const last = bs[bs.length - 1];
  if (t >= last.t) return last;
  for (let i = 0; i < bs.length - 1; i++) {
    const a = bs[i], b = bs[i + 1];
    if (t >= a.t && t <= b.t) {
      const span = b.t - a.t;
      const f = span > 1e-9 ? (t - a.t) / span : 0;
      return {
        t,
        x: a.x + (b.x - a.x) * f,
        y: a.y + (b.y - a.y) * f,
        w: a.w + (b.w - a.w) * f,
        h: a.h + (b.h - a.h) * f,
      };
    }
  }
  return last;
}

function drawOverlay() {
  const dpr = window.devicePixelRatio || 1;
  const W = videoWrap.clientWidth, H = videoWrap.clientHeight;
  if (overlayCanvas.width !== Math.round(W * dpr) || overlayCanvas.height !== Math.round(H * dpr)) {
    overlayCanvas.width = Math.round(W * dpr);
    overlayCanvas.height = Math.round(H * dpr);
  }
  const ctx = overlayCtx;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, W, H);

  const rect = contentRect();
  const t = video.currentTime;

  for (const ev of events) {
    if (ev.kind !== "visual") continue;
    if (t < ev.start_s - 1e-3 || t > ev.end_s + 1e-3) continue;
    const b = boxAt(ev, t);
    if (!b) continue;
    const x = rect.x + b.x * rect.w;
    const y = rect.y + b.y * rect.h;
    const w = b.w * rect.w;
    const h = b.h * rect.h;
    const isSel = ev.id === selectedId;
    const isManual = ev.source === "manual" || ev.manual_fixed_region;
    const color = STATUS_COLORS[ev.status] || STATUS_COLORS.pending;

    ctx.save();
    ctx.strokeStyle = isSel ? "#ffffff" : color;
    ctx.lineWidth = isSel ? 3 : 1.5;
    if (isManual) ctx.setLineDash([6, 4]);
    ctx.strokeRect(x, y, w, h);
    if (isSel) {
      ctx.setLineDash([]);
      ctx.strokeStyle = color;
      ctx.lineWidth = 1;
      ctx.strokeRect(x - 2, y - 2, w + 4, h + 4);
    }
    // label
    if (isSel || isManual) {
      const label = isManual ? "Manual fixed region" : (CAT_LABELS[ev.category] || ev.category);
      ctx.font = "11px -apple-system, sans-serif";
      const tw = ctx.measureText(label).width + 10;
      const ly = Math.max(rect.y, y - 18);
      ctx.fillStyle = "rgba(15,17,21,0.85)";
      ctx.fillRect(x, ly, tw, 16);
      ctx.fillStyle = isSel ? "#ffffff" : color;
      ctx.fillText(label, x + 5, ly + 12);
    }
    ctx.restore();
  }

  // in-progress manual drag rectangle
  if (dragRect) {
    ctx.save();
    ctx.strokeStyle = "#e8442e";
    ctx.lineWidth = 2;
    ctx.setLineDash([6, 4]);
    ctx.strokeRect(dragRect.x, dragRect.y, dragRect.w, dragRect.h);
    ctx.fillStyle = "rgba(232,68,46,0.12)";
    ctx.fillRect(dragRect.x, dragRect.y, dragRect.w, dragRect.h);
    ctx.restore();
  }
}

/* ---------- add region mode ---------- */

function setAddingRegion(on) {
  addingRegion = on;
  videoWrap.classList.toggle("adding", on);
  qs("#t-add-region").classList.toggle("active", on);
  if (!on) { dragStart = null; dragRect = null; qs("#region-form").classList.add("hidden"); }
}

function canvasPos(e) {
  const r = overlayCanvas.getBoundingClientRect();
  return { x: e.clientX - r.left, y: e.clientY - r.top };
}

function wireRegionDrawing() {
  overlayCanvas.addEventListener("mousedown", (e) => {
    if (!addingRegion) return;
    e.preventDefault();
    qs("#region-form").classList.add("hidden");
    dragStart = canvasPos(e);
    dragRect = { x: dragStart.x, y: dragStart.y, w: 0, h: 0 };
  });
  window.addEventListener("mousemove", (e) => {
    if (!addingRegion || !dragStart) return;
    const p = canvasPos(e);
    dragRect = {
      x: Math.min(dragStart.x, p.x),
      y: Math.min(dragStart.y, p.y),
      w: Math.abs(p.x - dragStart.x),
      h: Math.abs(p.y - dragStart.y),
    };
  });
  window.addEventListener("mouseup", () => {
    if (!addingRegion || !dragStart) return;
    dragStart = null;
    if (!dragRect || dragRect.w < 6 || dragRect.h < 6) { dragRect = null; return; }
    const rect = contentRect();
    // clamp to content rect, normalize
    const x0 = Math.max(dragRect.x, rect.x), y0 = Math.max(dragRect.y, rect.y);
    const x1 = Math.min(dragRect.x + dragRect.w, rect.x + rect.w);
    const y1 = Math.min(dragRect.y + dragRect.h, rect.y + rect.h);
    if (x1 - x0 < 4 || y1 - y0 < 4) { dragRect = null; return; }
    pendingRegion = {
      x: (x0 - rect.x) / rect.w,
      y: (y0 - rect.y) / rect.h,
      w: (x1 - x0) / rect.w,
      h: (y1 - y0) / rect.h,
    };
    const t = video.currentTime;
    qs("#rf-start").value = Math.max(0, t - 1).toFixed(2);
    qs("#rf-end").value = Math.min(duration || t + 1, t + 1).toFixed(2);
    const form = qs("#region-form");
    form.classList.remove("hidden");
    const fx = Math.min(Math.max(8, dragRect.x + dragRect.w + 10), videoWrap.clientWidth - 270);
    const fy = Math.min(Math.max(8, dragRect.y), Math.max(8, videoWrap.clientHeight - 300));
    form.style.left = `${fx}px`;
    form.style.top = `${fy}px`;
  });

  qs("#rf-cancel").addEventListener("click", () => {
    dragRect = null; pendingRegion = null;
    qs("#region-form").classList.add("hidden");
  });
  qs("#rf-add").addEventListener("click", async () => {
    if (!pendingRegion) return;
    const start = parseFloat(qs("#rf-start").value);
    const end = parseFloat(qs("#rf-end").value);
    if (!isFinite(start) || !isFinite(end) || end <= start) {
      toast("End must be after start", "error");
      return;
    }
    const r = pendingRegion;
    const effect = qs("#rf-effect").value;
    await createEvent({
      kind: "visual",
      category: qs("#rf-category").value,
      start_s: Math.max(0, start),
      end_s: Math.min(duration || end, end),
      action: { type: effect, strength: 65 },
      source: "manual",
      manual_fixed_region: true,
      boxes: [
        { t: Math.max(0, start), x: r.x, y: r.y, w: r.w, h: r.h },
        { t: Math.min(duration || end, end), x: r.x, y: r.y, w: r.w, h: r.h },
      ],
    });
    dragRect = null; pendingRegion = null;
    qs("#region-form").classList.add("hidden");
    setAddingRegion(false);
  });
}

async function addAudioInterval() {
  const t = video.currentTime;
  await createEvent({
    kind: "audio",
    category: "manual",
    start_s: Math.max(0, t - 1),
    end_s: Math.min(duration || t + 1, t + 1),
    action: { type: "mute" },
    source: "manual",
  });
}

/* ======================= transport ======================= */

function frameStep(dir) {
  video.pause();
  seekTo(video.currentTime + dir / fps);
}

function gotoAdjacentEvent(dir) {
  const list = sortedEvents();
  if (!list.length) return;
  const t = video.currentTime;
  let target = null;
  if (dir > 0) target = list.find((e) => e.start_s > t + 0.01);
  else {
    for (const e of list) { if (e.start_s < t - 0.01) target = e; else break; }
  }
  if (!target) target = dir > 0 ? list[list.length - 1] : list[0];
  selectEvent(target.id, { seek: true });
}

function wireTransport() {
  const playBtn = qs("#t-play");
  playBtn.addEventListener("click", () => { video.paused ? video.play().catch(() => {}) : video.pause(); });
  video.addEventListener("play", () => { playBtn.innerHTML = "&#10074;&#10074;"; });
  video.addEventListener("pause", () => { playBtn.innerHTML = "&#9654;"; });

  qs("#t-frame-back").addEventListener("click", () => frameStep(-1));
  qs("#t-frame-fwd").addEventListener("click", () => frameStep(1));
  qs("#t-prev-ev").addEventListener("click", () => gotoAdjacentEvent(-1));
  qs("#t-next-ev").addEventListener("click", () => gotoAdjacentEvent(1));

  qs("#t-rate-05").addEventListener("click", () => setRate(0.5));
  qs("#t-rate-10").addEventListener("click", () => setRate(1));

  const tc = qs("#t-timecode");
  tc.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      const t = parseTimecode(tc.value);
      if (isFinite(t)) seekTo(t); else toast("Invalid timecode — use MM:SS.mmm", "error");
      tc.blur();
    }
    e.stopPropagation();
  });

  qs("#t-toggle-src").addEventListener("click", toggleSource);
  qs("#t-add-region").addEventListener("click", () => setAddingRegion(!addingRegion));
  qs("#t-add-audio").addEventListener("click", addAudioInterval);
}

function setRate(r) {
  video.playbackRate = r;
  qs("#t-rate-05").classList.toggle("active", r === 0.5);
  qs("#t-rate-10").classList.toggle("active", r === 1);
}

function updateTimeUI() {
  const tc = qs("#t-timecode");
  if (document.activeElement !== tc) tc.value = fmtTime(video.currentTime);
  qs("#t-duration").textContent = `/ ${fmtTime(duration || video.duration || 0)}`;
}

/* ======================= keyboard ======================= */

function isTypingTarget(el) {
  if (!el) return false;
  const tag = (el.tagName || "").toLowerCase();
  return tag === "input" || tag === "textarea" || tag === "select" || el.isContentEditable;
}

function wireKeyboard() {
  document.addEventListener("keydown", (e) => {
    if (isTypingTarget(e.target)) return;
    switch (e.key) {
      case " ":
        e.preventDefault();
        video.paused ? video.play().catch(() => {}) : video.pause();
        break;
      case ",": frameStep(-1); break;
      case ".": frameStep(1); break;
      case "[": gotoAdjacentEvent(-1); break;
      case "]": gotoAdjacentEvent(1); break;
      case "c": case "C":
        if (selectedId) patchEvent(selectedId, { status: "confirmed" });
        break;
      case "i": case "I":
        if (selectedId) patchEvent(selectedId, { status: "ignored" });
        break;
      case "Escape":
        if (addingRegion) setAddingRegion(false);
        break;
    }
  });
}

/* ======================= timeline ======================= */

const TL = {
  rulerH: 20,
  laneH: 36,
  laneGap: 6,
  labelW: 20,
};

function tlDims() {
  const cssW = tlCanvas.clientWidth;
  const visDur = Math.max(0.001, (duration || 1) / tlZoom);
  return { cssW, visDur };
}

function tlX(t) {
  const { cssW, visDur } = tlDims();
  return TL.labelW + ((t - tlOffset) / visDur) * (cssW - TL.labelW);
}

function tlT(x) {
  const { cssW, visDur } = tlDims();
  return tlOffset + ((x - TL.labelW) / (cssW - TL.labelW)) * visDur;
}

function laneY(kind) {
  return kind === "visual" ? TL.rulerH + 4 : TL.rulerH + 4 + TL.laneH + TL.laneGap;
}

function clampOffset() {
  const { visDur } = tlDims();
  tlOffset = Math.max(0, Math.min(tlOffset, Math.max(0, (duration || 0) - visDur)));
}

function drawTimeline() {
  const dpr = window.devicePixelRatio || 1;
  const W = tlCanvas.clientWidth, H = tlCanvas.clientHeight || 108;
  if (tlCanvas.width !== Math.round(W * dpr) || tlCanvas.height !== Math.round(H * dpr)) {
    tlCanvas.width = Math.round(W * dpr);
    tlCanvas.height = Math.round(H * dpr);
  }
  const ctx = tlCtx;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, W, H);
  if (!duration) return;

  const { visDur } = tlDims();

  // lane backgrounds
  ctx.fillStyle = "#141720";
  ctx.fillRect(TL.labelW, laneY("visual"), W - TL.labelW, TL.laneH);
  ctx.fillRect(TL.labelW, laneY("audio"), W - TL.labelW, TL.laneH);
  ctx.fillStyle = "#9aa3b2";
  ctx.font = "10px -apple-system, sans-serif";
  ctx.fillText("V", 6, laneY("visual") + TL.laneH / 2 + 3);
  ctx.fillText("A", 6, laneY("audio") + TL.laneH / 2 + 3);

  // ruler
  const steps = [0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 15, 30, 60];
  const pxPerSec = (W - TL.labelW) / visDur;
  let step = steps[steps.length - 1];
  for (const s of steps) { if (s * pxPerSec >= 64) { step = s; break; } }
  ctx.strokeStyle = "#262a33";
  ctx.fillStyle = "#9aa3b2";
  ctx.beginPath();
  const first = Math.floor(tlOffset / step) * step;
  for (let t = first; t <= tlOffset + visDur + step; t += step) {
    const x = tlX(t);
    if (x < TL.labelW - 1 || x > W + 1) continue;
    ctx.moveTo(x, TL.rulerH - 6);
    ctx.lineTo(x, H);
    const m = Math.floor(t / 60), s = t - m * 60;
    const lbl = `${String(m).padStart(2, "0")}:${s.toFixed(step < 1 ? 2 : 0).padStart(step < 1 ? 5 : 2, "0")}`;
    ctx.fillText(lbl, x + 3, 11);
  }
  ctx.stroke();

  // event bars
  for (const ev of events) {
    const y = laneY(ev.kind);
    let x1 = tlX(ev.start_s), x2 = tlX(ev.end_s);
    if (x2 < TL.labelW || x1 > W) continue;
    x1 = Math.max(x1, TL.labelW);
    if (x2 - x1 < 3) x2 = x1 + 3;
    const color = STATUS_COLORS[ev.status] || STATUS_COLORS.pending;
    const isSel = ev.id === selectedId;
    ctx.save();
    ctx.fillStyle = color + "44";
    ctx.strokeStyle = isSel ? "#ffffff" : color;
    ctx.lineWidth = isSel ? 2 : 1;
    if (ev.source === "manual") ctx.setLineDash([4, 3]);
    const bh = TL.laneH - 10;
    ctx.fillRect(x1, y + 5, x2 - x1, bh);
    ctx.strokeRect(x1, y + 5, x2 - x1, bh);
    if (x2 - x1 > 34) {
      ctx.setLineDash([]);
      ctx.fillStyle = isSel ? "#ffffff" : color;
      ctx.font = "10px -apple-system, sans-serif";
      ctx.fillText((CAT_LABELS[ev.category] || ev.category).slice(0, Math.floor((x2 - x1) / 6)), x1 + 4, y + 5 + bh / 2 + 3);
    }
    ctx.restore();
  }

  // playhead
  const px = tlX(video.currentTime);
  if (px >= TL.labelW && px <= W) {
    ctx.strokeStyle = "#e8442e";
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(px, 2);
    ctx.lineTo(px, H);
    ctx.stroke();
    ctx.fillStyle = "#e8442e";
    ctx.beginPath();
    ctx.moveTo(px - 5, 2); ctx.lineTo(px + 5, 2); ctx.lineTo(px, 10);
    ctx.closePath();
    ctx.fill();
  }
}

function tlHit(x, y) {
  for (const ev of sortedEvents().reverse()) {
    const ly = laneY(ev.kind);
    if (y < ly + 2 || y > ly + TL.laneH - 2) continue;
    let x1 = tlX(ev.start_s), x2 = tlX(ev.end_s);
    if (x2 - x1 < 3) x2 = x1 + 3;
    if (x < x1 - 5 || x > x2 + 5) continue;
    if (Math.abs(x - x1) <= 5) return { ev, mode: "edge-l" };
    if (Math.abs(x - x2) <= 5) return { ev, mode: "edge-r" };
    return { ev, mode: "body" };
  }
  return null;
}

function wireTimeline() {
  tlCanvas.addEventListener("mousedown", (e) => {
    const r = tlCanvas.getBoundingClientRect();
    const x = e.clientX - r.left, y = e.clientY - r.top;
    const hit = tlHit(x, y);
    if (hit && (hit.mode === "edge-l" || hit.mode === "edge-r")) {
      flushPatch();
      tlDrag = { mode: hit.mode, id: hit.ev.id };
      selectEvent(hit.ev.id, { seek: false });
    } else if (hit) {
      selectEvent(hit.ev.id, { seek: false });
      seekTo(Math.max(hit.ev.start_s, Math.min(hit.ev.end_s, tlT(x))));
    } else {
      tlDrag = { mode: "scrub" };
      seekTo(tlT(x));
    }
  });

  window.addEventListener("mousemove", (e) => {
    const r = tlCanvas.getBoundingClientRect();
    const x = e.clientX - r.left, y = e.clientY - r.top;
    if (tlDrag) {
      if (tlDrag.mode === "scrub") { seekTo(tlT(x)); return; }
      const ev = evById(tlDrag.id);
      if (!ev) { tlDrag = null; return; }
      let t = tlT(x);
      if (ev.kind === "visual") t = Math.round(t * fps) / fps; // snap to frame
      const minDur = 1 / fps;
      if (tlDrag.mode === "edge-l") ev.start_s = Math.max(0, Math.min(t, ev.end_s - minDur));
      else ev.end_s = Math.min(duration || t, Math.max(t, ev.start_s + minDur));
      tlDrag.changed = true;
    } else if (e.target === tlCanvas) {
      const hit = tlHit(x, y);
      tlCanvas.style.cursor = hit && hit.mode !== "body" ? "ew-resize" : (hit ? "pointer" : "default");
    }
  });

  window.addEventListener("mouseup", () => {
    if (!tlDrag) return;
    const drag = tlDrag;
    tlDrag = null;
    if (drag.mode !== "scrub" && drag.changed) {
      const ev = evById(drag.id);
      if (ev) {
        patchEvent(ev.id, { start_s: Number(ev.start_s.toFixed(4)), end_s: Number(ev.end_s.toFixed(4)) });
      }
    }
  });

  tlCanvas.addEventListener("wheel", (e) => {
    e.preventDefault();
    const { visDur, cssW } = tlDims();
    const delta = (Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : e.deltaY);
    tlOffset += delta * (visDur / (cssW - TL.labelW));
    clampOffset();
  }, { passive: false });

  qs("#tl-zoom").addEventListener("input", (e) => {
    const t = video.currentTime;
    tlZoom = Number(e.target.value) || 1;
    const { visDur } = tlDims();
    tlOffset = t - visDur / 2;
    clampOffset();
  });
}

/* keep the playhead visible while playing */
function followPlayhead() {
  if (tlDrag || video.paused) return;
  const { visDur } = tlDims();
  const t = video.currentTime;
  if (t > tlOffset + visDur * 0.95 || t < tlOffset) {
    tlOffset = Math.max(0, t - visDur * 0.1);
    clampOffset();
  }
}

/* ======================= top bar actions ======================= */

async function confirmAll() {
  flushPatch();
  const btn = qs("#btn-confirm-all");
  btn.disabled = true;
  try {
    const res = await API.post(`/projects/${PID}/review/confirm-all`, { expected_revision: revision });
    revision = res.revision != null ? res.revision : revision + 1;
    await reloadEvents();
    toast(`Confirmed ${res.confirmed} event${res.confirmed === 1 ? "" : "s"}`, "success");
  } catch (e) {
    if (e.status === 409) {
      await reloadEvents();
      toast("Events changed elsewhere — view reloaded", "error");
    } else {
      toast(e.message, "error");
    }
  } finally {
    btn.disabled = false;
  }
}

async function completeReview() {
  flushPatch();
  const pendingAuto = events.filter((e) => e.source === "auto" && e.status === "pending").length;
  if (pendingAuto > 0) {
    const ok = window.confirm(
      `${pendingAuto} auto-detected event(s) are still pending. Rendering requires every auto event to be confirmed or ignored.\n\nContinue to the export page anyway?`
    );
    if (!ok) return;
  }
  try {
    await API.post(`/projects/${PID}/review/complete`, {});
    location.href = `export.html?id=${PID}`;
  } catch (e) {
    toast(`Could not complete review: ${e.message}`, "error");
  }
}

/* ======================= init ======================= */

function rafLoop() {
  drawOverlay();
  followPlayhead();
  drawTimeline();
  updateTimeUI();
  requestAnimationFrame(rafLoop);
}

async function init() {
  video = qs("#video");
  overlayCanvas = qs("#overlay-canvas");
  overlayCtx = overlayCanvas.getContext("2d");
  tlCanvas = qs("#timeline-canvas");
  tlCtx = tlCanvas.getContext("2d");
  videoWrap = qs("#video-wrap");

  if (!PID) { toast("Missing project id", "error"); return; }

  try {
    project = await API.get(`/projects/${PID}`);
  } catch (e) {
    toast(`Could not load project: ${e.message}`, "error");
    return;
  }
  qs("#proj-name").textContent = project.name;
  document.title = `PolicyCut — Review ${project.name}`;
  if (project.media) {
    fps = Number(project.media.fps) || 30;
    duration = Number(project.media.duration_s) || 0;
  }

  video.src = videoUrl("overlay");
  video.addEventListener("error", function onErr() {
    if (videoMode === "overlay") {
      // overlay preview missing (analysis interrupted?) — fall back to original
      videoMode = "original";
      qs("#t-toggle-src").textContent = "Original";
      video.src = videoUrl("original");
      video.load();
      toast("Overlay preview unavailable — showing original video", "info");
      video.removeEventListener("error", onErr);
    }
  });
  video.addEventListener("loadedmetadata", () => {
    if (isFinite(video.duration) && video.duration > 0) duration = video.duration;
  });

  try {
    await reloadEvents();
  } catch (e) {
    toast(`Could not load events: ${e.message}`, "error");
  }

  wireTransport();
  wireKeyboard();
  wireRegionDrawing();
  wireTimeline();

  qsa("#filter-tabs button").forEach((b) =>
    b.addEventListener("click", () => { filter = b.dataset.f; renderList(); })
  );
  qs("#btn-confirm-all").addEventListener("click", confirmAll);
  qs("#btn-complete").addEventListener("click", completeReview);
  const lc2 = qs("#btn-lowest-conf2");
  if (lc2) lc2.addEventListener("click", jumpLowestConfidence);

  window.addEventListener("beforeunload", flushPatch);
  requestAnimationFrame(rafLoop);
}

document.addEventListener("DOMContentLoaded", init);
