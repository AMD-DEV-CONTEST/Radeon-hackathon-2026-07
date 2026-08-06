/* MedGlass patient-notes dashboard (default page).
 * Lists archived notes, searches/filters, opens a detail drawer with
 * S/O/A/P sections, photos, transcript, FHIR R4, JSON and EHR downloads.
 */
(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);

  const FMTS = [
    { fmt: "md", label: "Markdown", icon: "i-download" },
    { fmt: "txt", label: "Text", icon: "i-download" },
    { fmt: "json", label: "JSON", icon: "i-doc" },
    { fmt: "fhir", label: "FHIR R4", icon: "i-export" },
    { fmt: "ccda", label: "CDA/CCD", icon: "i-export" },
  ];
  const SECTION_TITLES = { S: "Subjective", O: "Objective", A: "Assessment", P: "Plan" };
  const SOURCE_LABELS = { mentra: "Provider", web: "Web", api: "API", simulator: "Simulator" };
  const ICON = (name) => `<svg><use href="#${name}"/></svg>`;

  let notes = [];
  let assignments = {};
  let showDone = false;   // when true, completed next-steps are revealed

  function escapeHtml(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  function csrfHeaders(extra) {
    const match = document.cookie.match(/(?:^|;\s*)mg_csrf=([^;]*)/);
    return Object.assign(
      { "Content-Type": "application/json" },
      match ? { "X-CSRF-Token": decodeURIComponent(match[1]) } : {},
      extra || {},
    );
  }

  // ---------------------------------------------------------- accordions

  function initCollapse(rootId) {
    const root = $(rootId);
    if (!root) return;
    const head = root.querySelector(".collapse-head");
    const body = root.querySelector(".collapse-body");
    const key = "mg.collapse." + rootId;
    const saved = localStorage.getItem(key);
    const open = saved === null ? true : saved === "1";
    root.classList.toggle("open", open);
    head.setAttribute("aria-expanded", open ? "true" : "false");
    body.hidden = !open;
    head.addEventListener("click", () => {
      const now = !root.classList.contains("open");
      root.classList.toggle("open", now);
      body.hidden = !now;
      head.setAttribute("aria-expanded", now ? "true" : "false");
      localStorage.setItem(key, now ? "1" : "0");
    });
  }

  function fmtDate(iso) {
    try {
      const d = new Date(iso);
      const now = new Date();
      const sameDay = d.toDateString() === now.toDateString();
      const opts = sameDay
        ? { hour: "2-digit", minute: "2-digit" }
        : { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" };
      return d.toLocaleString([], opts);
    } catch (_) {
      return iso;
    }
  }

  function shortId(sid) {
    return sid && sid.length > 18 ? sid.slice(0, 8) + "…" + sid.slice(-6) : sid || "";
  }

  function preview(rec) {
    const sections = rec.sections || {};
    const src = sections.S || sections.O || rec.note || "";
    const s = src.replace(/\s+/g, " ").trim();
    return s.length > 170 ? s.slice(0, 169) + "…" : s;
  }

  function sectionPreview(rec) {
    const s = ((rec.sections || {}).S || "").replace(/\s+/g, " ").trim();
    return s.length > 110 ? s.slice(0, 109) + "…" : s;
  }

  // -------------------------------------------------------------- rendering

  function card(rec) {
    const tags = ["S", "O", "A", "P"]
      .filter((k) => (rec.sections || {})[k])
      .map((k) => `<span class="tag ${k}">${k}</span>`).join("");
    return `
      <article class="note-card" data-id="${escapeHtml(rec.id)}">
        <div class="card-top">
          <span class="source-badge src-${escapeHtml(rec.source || "api")}">${escapeHtml(SOURCE_LABELS[rec.source] || rec.source || "api")}</span>
          <span class="note-time">${fmtDate(rec.created_at)}</span>
        </div>
        <div class="note-patient">${escapeHtml(rec.patient_id || "Unnamed patient")}</div>
        <div class="note-preview">${escapeHtml(sectionPreview(rec)) || "&nbsp;"}</div>
        <div class="note-session">session ${escapeHtml(shortId(rec.session_id))}</div>
        <div class="note-tags">${tags}</div>
        <div class="note-actions">
          <a class="btn sm" href="/notes/${escapeHtml(rec.id)}/download?fmt=md" download title="Markdown">${ICON("i-download")} .md</a>
          <a class="btn sm" href="/notes/${escapeHtml(rec.id)}/download?fmt=fhir" download title="HL7 FHIR R4">${ICON("i-export")} FHIR</a>
          <span class="spacer"></span>
          <button class="icon-btn danger" data-del title="Delete note">${ICON("i-trash")}</button>
        </div>
      </article>`;
  }

  function renderList() {
    const el = $("note-list");
    const q = ($("search").value || "").trim().toLowerCase();
    const filtered = q
      ? notes.filter((n) => {
          const hay = [n.note, n.transcript, n.id, n.session_id, n.source,
            JSON.stringify(n.sections || {}), n.provider, n.patient_id].join(" ");
          return hay.toLowerCase().includes(q);
        })
      : notes;
    const countEl = $("notes-count");
    if (countEl) countEl.textContent = String(filtered.length);

    if (!filtered.length) {
      el.innerHTML = q
        ? `<div class="empty"><div class="empty-ic">${ICON("i-search")}</div><h3>No matches</h3>Nothing found for “${escapeHtml(q)}”.</div>`
        : `<div class="empty"><div class="empty-ic">${ICON("i-empty")}</div><h3>No notes yet</h3>Generate a note from the live consultation page or with the Mentra glasses (long-press the button).</div>`;
      return;
    }
    el.innerHTML = filtered.map(card).join("");
    el.querySelectorAll(".note-card").forEach((item) => {
      item.addEventListener("click", (ev) => {
        if (ev.target.closest("a") || ev.target.closest("[data-del]")) return;
        openDetail(item.dataset.id);
      });
      item.querySelector("[data-del]").addEventListener("click", (ev) => {
        ev.stopPropagation();
        askDelete(item.dataset.id);
      });
    });
  }

  function renderStats() {
    const s = planStats();
    $("stat-total").textContent = s.followUps;
    $("stat-week").textContent = s.tests;
    $("stat-photos").textContent = s.rx;
    $("stat-exported").textContent = s.open;
  }

  // ----------------------------------------------- care-team next steps

  function planItems(rec) {
    const raw = (rec.sections || {}).P || "";
    if (!raw) return [];
    let parts = raw.split(/\n+/).map((s) => s.trim()).filter(Boolean);
    if (parts.length === 1) {
      parts = parts[0].split(/\s+(?=\d+[.)]\s|[-•]\s)/).map((s) => s.trim()).filter(Boolean);
    }
    const items = [];
    for (let p of parts) {
      p = p.replace(/^\s*\d+\s*[.)]\s*/, "").replace(/^[-•]\s*/, "").replace(/\s+/g, " ").trim();
      if (!p || /^(plan|p|note|"p:")$/i.test(p)) continue;
      if (!items.some((x) => x.toLowerCase() === p.toLowerCase())) items.push(p);
    }
    return items;
  }

  function planStats() {
    const open = [], followUps = [], tests = [], rx = [];
    notes.forEach((n) => {
      planItems(n).forEach((it, idx) => {
        // Completed (checked-off) items drop out of every count.
        const a = (assignments[n.id] || {})[idx];
        if (a && a.done) return;
        open.push(it);
        if (/follow[- ]?up|revisit|return|again|review|re-?check/i.test(it)) followUps.push(it);
        if (/test|scan|imaging|lab|panel|biopsy|culture/i.test(it)) tests.push(it);
        if (/prescri|epipen|medication|dose|titrat|immunotherap/i.test(it)) rx.push(it);
      });
    });
    return { open: open.length, followUps: followUps.length, tests: tests.length, rx: rx.length };
  }

  async function renderNextSteps() {
    const panel = $("next-steps");
    const body = $("next-steps-body");
    const toggle = $("btn-toggle-done");
    if (!notes.length) { panel.hidden = true; return; }
    panel.hidden = false;
    const rows = [];
    notes.forEach((n) => planItems(n).forEach((it, i) => rows.push({ note: n, text: it, idx: i })));
    const withDone = rows.map((r) => {
      const a = (assignments[r.note.id] || {})[r.idx];
      return Object.assign({}, r, { done: !!(a && a.done) });
    });
    const completed = withDone.filter((r) => r.done).length;
    if (toggle) {
      toggle.textContent = showDone
        ? `Hide completed (${completed})`
        : `Show completed (${completed})`;
    }
    if (!withDone.length) {
      body.innerHTML = `<p class="next-empty">No pending follow-up plans in the current notes.</p>`;
      return;
    }
    // Completed steps are hidden by default; the toggle reveals them.
    const visible = showDone ? withDone : withDone.filter((r) => !r.done);
    if (!visible.length) {
      body.innerHTML =
        `<p class="next-empty">All caught up — ${completed} step${completed === 1 ? "" : "s"} completed. ` +
        `Use "Show completed" to review them.</p>`;
      return;
    }
    const list = visible.map((r) => {
      const a = (assignments[r.note.id] || {})[r.idx];
      const done = r.done;
      return `
        <li class="task-row${done ? " done" : ""}" data-note="${escapeHtml(r.note.id)}" data-idx="${r.idx}">
          <button class="task-done" data-note="${escapeHtml(r.note.id)}" data-idx="${r.idx}"
                  title="${done ? "Mark as open" : "Mark as done"}" aria-pressed="${done}">
            ${done ? ICON("i-check") : ""}
          </button>
          <span class="task-text">${escapeHtml(r.text)}</span>
          <span class="task-date">${fmtDate(r.note.created_at)}</span>
          <select class="task-role" data-note="${escapeHtml(r.note.id)}" data-idx="${r.idx}">
            <option value="">Unassigned</option>
            <option value="nurse"${a && a.role === "nurse" ? " selected" : ""}>Nurse</option>
            <option value="provider"${a && a.role === "provider" ? " selected" : ""}>Provider</option>
          </select>
        </li>`;
    }).join("");
    body.innerHTML = `<ul class="next-list">${list}</ul>`;
    body.querySelectorAll(".task-role").forEach((sel) => {
      sel.addEventListener("change", () => {
        const note = sel.dataset.note, idx = Number(sel.dataset.idx);
        const role = sel.value || null;
        fetch("/tasks", {
          method: "POST",
          headers: csrfHeaders(),
          body: JSON.stringify({ note_id: note, item: idx, role }),
        })
          .then((r) => (r.ok ? r.json() : Promise.reject(r)))
          .then((data) => { assignments = data.tasks || {}; renderNextSteps(); })
          .catch(() => { sel.value = (assignments[note] || {})[idx] ? (assignments[note][idx]).role : ""; });
      });
    });
    body.querySelectorAll(".task-done").forEach((btn) => {
      btn.addEventListener("click", () => {
        const note = btn.dataset.note, idx = Number(btn.dataset.idx);
        const nowDone = !((assignments[note] || {})[idx] || {}).done;
        fetch("/tasks", {
          method: "POST",
          headers: csrfHeaders(),
          body: JSON.stringify({ note_id: note, item: idx, done: nowDone }),
        })
          .then((r) => (r.ok ? r.json() : Promise.reject(r)))
          .then((data) => { assignments = data.tasks || {}; renderStats(); renderNextSteps(); })
          .catch(() => { /* offline */ });
      });
    });
  }

  async function loadTasks() {
    try {
      const res = await fetch("/tasks");
      if (res.status === 401) return;
      if (!res.ok) return;
      const data = await res.json();
      assignments = data.tasks || {};
    } catch (_) { /* offline */ }
  }

  // ---------------------------------------------------------------- drawer

  function renderNoteHtml(rec) {
    const sections = rec.sections || {};
    let html = "";
    for (const k of ["S", "O", "A", "P"]) {
      if (sections[k]) {
        html += `<div class="sec">${SECTION_TITLES[k]}</div><div class="sec-text">${escapeHtml(sections[k])}</div>`;
      }
    }
    if (!html && rec.note) html = `<div class="sec-text">${escapeHtml(rec.note)}</div>`;
    return html || `<div class="live-empty">No note body.</div>`;
  }

  function renderFhirBody(bundle) {
    const comp = (bundle.entry || []).find((e) => e.resource.resourceType === "Composition");
    if (!comp) return "No Composition found.";
    const typeCoding = ((comp.type && comp.type.coding) || [])[0];
    const rows = [
      ["Type", typeCoding ? `${typeCoding.display} (${typeCoding.code})` : ""],
      ["Status", comp.status],
      ["Date", comp.date],
      ["Subject", comp.subject ? comp.subject.reference : ""],
      ["Author", comp.author ? comp.author.map((a) => a.display || a.reference).join(", ") : ""],
    ].filter(([, v]) => v).map(([k, v]) =>
      `<div class="meta-cell"><div class="k">${escapeHtml(k)}</div><div class="v">${escapeHtml(v)}</div></div>`).join("");
    let html = `<div class="meta-grid" style="margin-bottom:12px">${rows}</div>`;
    html += `<div class="fhir-sections">`;
    for (const s of comp.section || []) {
      const code = ((s.code && s.code.coding) || [])[0];
      html += `<div class="sec">${escapeHtml(s.title || "")}</div>`;
      html += `<div class="sec-text">${s.text ? s.text.div : ""}</div>`;
      html += code ? `<div class="note-session" style="margin:2px 0 10px">${escapeHtml(code.code)} ${escapeHtml(code.display || "")}</div>` : "";
    }
    html += `</div>`;
    return html;
  }

  function renderPhotos(rec) {
    const photos = rec.photos || [];
    const sec = $("drawer-photos-sec");
    const grid = $("drawer-photos");
    if (!photos.length) { sec.hidden = true; return; }
    sec.hidden = false;
    $("drawer-photos-count").textContent = `${photos.length}`;
    grid.innerHTML = photos.map((p, i) => `
      <figure class="photo-card" data-i="${i}">
        <img src="${escapeHtml(p.original || "")}" alt="case photo ${i + 1}" loading="lazy">
        <figcaption>${escapeHtml((p.detections || []).map((d) =>
          `${d.kind}${d.detail ? ": " + d.detail : ""}`).join("; ") || "photo")}</figcaption>
      </figure>`).join("");
    grid.querySelectorAll(".photo-card").forEach((card) => {
      card.addEventListener("click", () => openPhotoViewer(photos, Number(card.dataset.i)));
    });
  }

  function openPhotoViewer(photos, index) {
    const viewer = $("photo-viewer");
    const img = $("photo-viewer-img");
    const p = photos[index];
    viewer.hidden = false;
    img.src = p.original || "";
    $("photo-viewer-close").onclick = (ev) => { ev.stopPropagation(); viewer.hidden = true; };
    viewer.onclick = (ev) => { if (ev.target === viewer) viewer.hidden = true; };
  }

  function openDrawer(id) {
    $("drawer").classList.add("open");
    $("drawer-backdrop").classList.add("show");
    $("drawer-title").textContent = "Loading…";
  }

  function closeDrawer() {
    $("drawer").classList.remove("open");
    $("drawer-backdrop").classList.remove("show");
  }

  function openDetail(id) {
    openDrawer(id);
    fetch(`/notes/${id}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(r)))
      .then((rec) => {
        $("drawer-title").textContent = `Patient Note · ${shortId(rec.id)}`;
        $("drawer-meta").innerHTML =
          `<span>${fmtDate(rec.created_at)}</span>` +
          `<span>${escapeHtml(SOURCE_LABELS[rec.source] || rec.source || "api")}</span>` +
          `<span>session ${escapeHtml(shortId(rec.session_id))}</span>`;
        $("drawer-actions").innerHTML = FMTS.map((f) =>
          `<a class="btn sm" href="/notes/${escapeHtml(id)}/download?fmt=${f.fmt}" download>${ICON(f.icon)} ${escapeHtml(f.label)}</a>`).join("") +
          `<button class="btn sm" id="btn-speak" title="Read the note aloud (local TTS)">${ICON("i-live")} Speak note</button>`;
        const speakBtn = $("btn-speak");
        if (speakBtn) speakBtn.addEventListener("click", () => speakNote(rec));
        $("drawer-note").innerHTML = renderNoteHtml(rec);
        $("drawer-facts").innerHTML = [
          ["Patient", rec.patient_id],
          ["Provider", rec.provider],
          ["Visual findings", (rec.visual_findings || []).map((v) => `${v.kind}: ${v.detail || ""}`).join("; ") || "none"],
        ].filter(([, v]) => v).map(([k, v]) =>
          `<div class="meta-cell"><div class="k">${escapeHtml(k)}</div><div class="v">${escapeHtml(v)}</div></div>`).join("");
        renderPhotos(rec);
        $("drawer-transcript").textContent = rec.transcript || "(none)";
        $("drawer-json").textContent = JSON.stringify(rec, null, 2);
        $("drawer-fhir").textContent = "Loading…";
        fetch(`/notes/${id}/download?fmt=fhir`)
          .then((r) => (r.ok ? r.json() : Promise.reject(r)))
          .then((bundle) => { $("drawer-fhir").innerHTML = renderFhirBody(bundle); })
          .catch((err) => { $("drawer-fhir").textContent = `FHIR export failed: ${err.message}`; });
      })
      .catch((err) => {
        $("drawer-note").innerHTML = `<div class="live-empty">Failed to load note: ${escapeHtml(err.message)}</div>`;
      });
  }

  // ------------------------------------------------------ local TTS readback

  async function speakNote(rec) {
    const btn = $("btn-speak");
    if (!btn) return;
    const text = [
      rec.note || "",
      (rec.transcript ? " " + rec.transcript : ""),
    ].join("").trim();
    if (!text) return;
    btn.disabled = true;
    const label = btn.innerHTML;
    btn.innerHTML = "Speaking…";
    try {
      const res = await fetch("/tts?text=" + encodeURIComponent(text.slice(0, 1800)));
      if (!res.ok) throw new Error(res.statusText);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      await new Promise((resolve) => {
        audio.onended = resolve;
        audio.onerror = resolve;
        audio.play().catch(() => resolve());
      });
      URL.revokeObjectURL(url);
    } catch (_) {
      /* local TTS unavailable; silent */
    } finally {
      btn.disabled = false;
      btn.innerHTML = label;
    }
  }

  // ------------------------------------------------------- delete confirm

  let pendingDelete = null;
  function askDelete(id) {
    pendingDelete = id;
    $("confirm-backdrop").hidden = false;
    $("confirm").hidden = false;
  }

  function closeConfirm() {
    pendingDelete = null;
    $("confirm-backdrop").hidden = true;
    $("confirm").hidden = true;
  }

  function doDelete(id) {
    fetch(`/notes/${id}`, { method: "DELETE", headers: csrfHeaders() })
      .then((r) => (r.ok ? (closeConfirm(), renderList()) : Promise.reject(r)))
      .catch(() => load());
  }

  // ------------------------------------------------------------------ load

  // Signature of the last rendered list so the periodic refresh only touches
  // the DOM when the data actually changed (otherwise the list visibly
  // "refreshes" / flickers by itself every poll).
  let lastListSig = null;

  async function load() {
    try {
      const res = await fetch("/notes");
      if (res.status === 401) { location.href = "/"; return; }
      if (!res.ok) throw new Error(res.statusText);
      const data = await res.json();
      const items = data.notes || [];
      const sig = JSON.stringify(items);
      notes = items;
      if (sig === lastListSig) return;   // unchanged -> no re-render
      lastListSig = sig;
      renderStats();
      renderNextSteps();
      renderList();
    } catch (err) {
      $("note-list").innerHTML =
        `<div class="empty"><h3>Failed to load notes</h3>${escapeHtml(err.message)}</div>`;
    }
  }

  // ------------------------------------------------------------------- boot
  const sessionFilter = new URLSearchParams(location.search).get("session");
  if (sessionFilter) {
    $("search").value = sessionFilter;
  }
  $("search").addEventListener("input", renderList);
  $("drawer-close").addEventListener("click", closeDrawer);
  $("drawer-backdrop").addEventListener("click", closeDrawer);
  $("confirm-cancel").addEventListener("click", closeConfirm);
  $("confirm-backdrop").addEventListener("click", closeConfirm);
  $("confirm-ok").addEventListener("click", () => {
    if (pendingDelete) doDelete(pendingDelete);
  });
  $("btn-settings").addEventListener("click", (e) => {
    e.stopPropagation();
    $("settings-menu").hidden = !$("settings-menu").hidden;
  });
  document.addEventListener("click", (e) => {
    if (!$("settings-menu").hidden && !e.target.closest(".settings-wrap")) {
      $("settings-menu").hidden = true;
    }
  });
  $("btn-logout").addEventListener("click", async () => {
    try { await fetch("/logout", { method: "POST", headers: csrfHeaders() }); } catch (_) { /* noop */ }
    location.href = "/";
  });

  // -------------------------------------------------- identity + MFA setup

  async function loadIdentity() {
    try {
      const res = await fetch("/me");
      if (!res.ok) return;
      const me = await res.json();
      const userEl = $("settings-user");
      if (userEl) userEl.textContent = me.username || "";
      const roleEl = $("settings-role");
      if (roleEl) roleEl.textContent = me.role || "";
      const chipUser = $("user-name");
      if (chipUser) chipUser.textContent = me.username || "";
      const chipRole = $("user-role");
      if (chipRole) chipRole.textContent = me.role === "admin" ? "Administrator" : "Clinician";
      const mfaLabel = $("mfa-label");
      if (mfaLabel) mfaLabel.textContent = me.totp_enabled ? "Disable two-factor auth" : "Set up two-factor auth";
    } catch (_) { /* offline */ }
  }

  function closeMfa() {
    $("mfa-backdrop").hidden = true;
    $("mfa-modal").hidden = true;
  }

  $("btn-mfa").addEventListener("click", async () => {
    const label = $("mfa-label");
    const enabling = label && label.textContent.indexOf("Set up") === 0;
    try {
      if (enabling) {
        const res = await fetch("/me/mfa/enable", { method: "POST", headers: csrfHeaders() });
        if (!res.ok) return;
        const data = await res.json();
        $("mfa-secret").textContent = data.secret;
        $("mfa-code").value = "";
        $("mfa-err").hidden = true;
        $("mfa-backdrop").hidden = false;
        $("mfa-modal").hidden = false;
        setTimeout(() => $("mfa-code").focus(), 50);
      } else {
        await fetch("/me/mfa/disable", { method: "POST", headers: csrfHeaders() });
        loadIdentity();
      }
    } catch (_) { /* offline */ }
  });
  $("mfa-cancel").addEventListener("click", async () => {
    await fetch("/me/mfa/cancel", { method: "POST", headers: csrfHeaders() });
    closeMfa();
    loadIdentity();
  });
  $("mfa-confirm").addEventListener("click", async () => {
    const code = $("mfa-code").value.trim();
    if (code.length !== 6) { $("mfa-err").hidden = false; return; }
    try {
      const res = await fetch("/me/mfa/confirm", {
        method: "POST", headers: csrfHeaders(),
        body: JSON.stringify({ code }),
      });
      if (!res.ok) { $("mfa-err").hidden = false; return; }
      closeMfa();
      loadIdentity();
    } catch (_) { /* offline */ }
  });
  $("mfa-backdrop").addEventListener("click", () => {
    fetch("/me/mfa/cancel", { method: "POST", headers: csrfHeaders() });
    closeMfa();
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { closeConfirm(); closeDrawer(); closeMfa(); $("settings-menu").hidden = true; }
  });

  initCollapse("next-steps");
  initCollapse("notes-section");
  loadIdentity();

  // Toggle completed next-steps in/out of view.
  const doneToggle = $("btn-toggle-done");
  if (doneToggle) {
    doneToggle.addEventListener("click", (ev) => {
      ev.stopPropagation();   // don't collapse the panel
      showDone = !showDone;
      renderNextSteps();
    });
  }

  // Auth guard: if the session is gone, never show cached/back-button content.
  fetch("/me").then((r) => {
    if (r.status === 401) location.replace("/");
  }).catch(() => { /* offline */ });

  loadTasks().then(load);
  setInterval(() => { loadTasks().then(load); }, 15000);
})();
