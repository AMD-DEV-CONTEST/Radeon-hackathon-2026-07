/* PolicyCut — Projects home page. */
"use strict";

const STATUS_LABELS = {
  draft: "Draft",
  analyzing: "Analyzing",
  review_ready: "Review ready",
  rendering: "Rendering",
  complete: "Complete",
  error: "Error",
};

let projects = [];
let deleteTargetId = null;

/** Route "Open" by project status. Job ids for in-flight jobs are remembered
 *  in localStorage by the page that started them. */
function openUrl(p) {
  const jobKey = `pc_job_${p.id}`;
  const jobId = localStorage.getItem(jobKey);
  switch (p.status) {
    case "analyzing":
      return jobId ? `processing.html?id=${p.id}&job=${jobId}` : `project.html?id=${p.id}`;
    case "review_ready":
      return `review.html?id=${p.id}`;
    case "rendering":
    case "complete":
      return `export.html?id=${p.id}`;
    default: // draft, error
      return `project.html?id=${p.id}`;
  }
}

async function loadSystem() {
  const gpuChip = qs("#gpu-chip");
  const rocmChip = qs("#rocm-chip");
  try {
    const sys = await API.get("/system");
    const gpu = sys.gpu || {};
    if (gpu.available && gpu.name) {
      gpuChip.className = "chip ok";
      gpuChip.innerHTML = `<span class="dot"></span><span>${esc(gpu.name)}</span>`;
    } else {
      gpuChip.className = "chip";
      gpuChip.innerHTML = `<span class="dot"></span><span>No GPU detected</span>`;
    }
    if (gpu.rocm) {
      rocmChip.className = "chip ok";
      rocmChip.innerHTML = `<span class="dot"></span><span>ROCm ready</span>`;
    } else {
      rocmChip.className = "chip warn";
      rocmChip.innerHTML = `<span class="dot"></span><span>CPU fallback</span>`;
    }
  } catch (e) {
    gpuChip.className = "chip error";
    gpuChip.innerHTML = `<span class="dot"></span><span>System info unavailable</span>`;
    rocmChip.classList.add("hidden");
  }
}

function cardHtml(p) {
  const st = p.status || "draft";
  const dur = p.media ? fmtTime(p.media.duration_s) : "—";
  return `
  <div class="project-card" data-id="${esc(p.id)}">
    <div class="thumb-wrap">
      <div class="thumb-placeholder">&#127909;</div>
      <img src="${API.base}/projects/${esc(p.id)}/thumbnail" alt="" loading="lazy">
      <span class="chip ${esc(st)}"><span class="dot"></span>${esc(STATUS_LABELS[st] || st)}</span>
    </div>
    <div class="card-body">
      <div class="card-name" title="Click to rename">${esc(p.name)}</div>
      <div class="card-meta">
        <span title="Duration">&#9201; ${esc(dur)}</span>
        <span title="Last updated">&#8635; ${esc(fmtDate(p.updated_at))}</span>
      </div>
      <div class="card-actions">
        <button class="btn sm primary act-open">Open</button>
        <span class="grow"></span>
        <button class="btn sm danger act-del">Delete</button>
      </div>
    </div>
  </div>`;
}

function renderGrid() {
  const grid = qs("#card-grid");
  const empty = qs("#empty-state");
  const sorted = projects.slice().sort((a, b) => String(b.updated_at).localeCompare(String(a.updated_at)));
  grid.innerHTML = sorted.map(cardHtml).join("");
  empty.classList.toggle("hidden", sorted.length > 0);

  qsa(".project-card", grid).forEach((card) => {
    const id = card.dataset.id;
    const proj = projects.find((p) => p.id === id);
    if (!proj) return;

    // Thumbnail fallback: hide the <img>, the placeholder underneath shows.
    const img = qs("img", card);
    img.addEventListener("error", () => img.classList.add("hidden"));

    qs(".act-open", card).addEventListener("click", () => { location.href = openUrl(proj); });
    qs(".thumb-wrap", card).addEventListener("click", () => { location.href = openUrl(proj); });
    qs(".act-del", card).addEventListener("click", () => askDelete(proj));
    qs(".card-name", card).addEventListener("click", () => startRename(card, proj));
  });
}

function startRename(card, proj) {
  const nameEl = qs(".card-name", card);
  if (qs("input", nameEl)) return;
  const input = document.createElement("input");
  input.type = "text";
  input.value = proj.name;
  input.maxLength = 80;
  nameEl.textContent = "";
  nameEl.appendChild(input);
  input.focus();
  input.select();

  let done = false;
  const commit = async () => {
    if (done) return;
    done = true;
    const newName = input.value.trim();
    if (!newName || newName === proj.name) {
      nameEl.textContent = proj.name;
      return;
    }
    try {
      const updated = await API.patch(`/projects/${proj.id}`, { name: newName });
      proj.name = updated.name || newName;
      nameEl.textContent = proj.name;
      toast("Project renamed", "success");
    } catch (e) {
      nameEl.textContent = proj.name;
      toast(`Rename failed: ${e.message}`, "error");
    }
  };
  input.addEventListener("blur", commit);
  input.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") input.blur();
    if (ev.key === "Escape") { done = true; nameEl.textContent = proj.name; }
    ev.stopPropagation();
  });
}

function askDelete(proj) {
  deleteTargetId = proj.id;
  qs("#del-name").textContent = proj.name;
  qs("#modal-del").classList.remove("hidden");
}

async function doDelete() {
  const id = deleteTargetId;
  qs("#modal-del").classList.add("hidden");
  if (!id) return;
  try {
    await API.del(`/projects/${id}`);
    projects = projects.filter((p) => p.id !== id);
    localStorage.removeItem(`pc_job_${id}`);
    renderGrid();
    toast("Project deleted", "success");
  } catch (e) {
    toast(`Delete failed: ${e.message}`, "error");
  }
  deleteTargetId = null;
}

async function createProject() {
  const name = qs("#new-name").value.trim() || "Untitled project";
  const btn = qs("#new-create");
  btn.disabled = true;
  try {
    const p = await API.post("/projects", { name });
    location.href = `project.html?id=${p.id}`;
  } catch (e) {
    toast(`Could not create project: ${e.message}`, "error");
    btn.disabled = false;
  }
}

async function loadProjects() {
  try {
    const data = await API.get("/projects");
    projects = data.projects || [];
    renderGrid();
  } catch (e) {
    toast(`Could not load projects: ${e.message}`, "error");
  }
}

function init() {
  loadSystem();
  loadProjects();

  qs("#btn-new").addEventListener("click", () => {
    qs("#new-name").value = "";
    qs("#modal-new").classList.remove("hidden");
    qs("#new-name").focus();
  });
  qs("#new-cancel").addEventListener("click", () => qs("#modal-new").classList.add("hidden"));
  qs("#new-create").addEventListener("click", createProject);
  qs("#new-name").addEventListener("keydown", (e) => { if (e.key === "Enter") createProject(); });

  qs("#del-cancel").addEventListener("click", () => qs("#modal-del").classList.add("hidden"));
  qs("#del-confirm").addEventListener("click", doDelete);

  qsa(".modal-backdrop").forEach((m) =>
    m.addEventListener("click", (e) => { if (e.target === m) m.classList.add("hidden"); })
  );

  // Refresh statuses periodically so in-flight jobs update the grid.
  setInterval(loadProjects, 10000);
}

document.addEventListener("DOMContentLoaded", init);
