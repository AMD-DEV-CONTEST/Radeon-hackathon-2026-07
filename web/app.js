const DEFAULTS = {
  W1: {
    text: "wasteland style bar interior, post-apocalyptic saloon, dark moody atmosphere, neon glow, metal bar counter, dusty bottles, grunge textures, cinematic lighting, highly detailed 2d game concept art background",
    negative: "blurry, low quality, deformed, watermark, text, oversaturated",
    width: 1024, height: 1024,
    seed: () => Math.floor(Math.random() * 1e9),
    steps: 20, cfg: 7,
  },
  W2: { resolution: 512 },
  W3: { resolution: 512, strength: 2.0, roughness_scale: 1.0, metalness: 0.6 },
  W4: {
    prompt: "dark ambient electronic music, industrial, heavy metal clanking percussion, ominous, slow tempo, underground bar atmosphere",
    duration: 8.0,
    seed: () => Math.floor(Math.random() * 1e9),
  },
  W5: { kind: "glass_clink", duration: 4.0, seed: () => Math.floor(Math.random() * 1e9) },
  W6: {
    text: "full body 2d game character sprite, side view, running action pose, clean background, cel shading, game asset, consistent character design",
    negative: "blurry, low quality, deformed, watermark, text, multiple characters, extra limbs",
    action: "run", frames: 8, width: 512, height: 512,
    seed: () => Math.floor(Math.random() * 1e9),
    steps: 20, cfg: 7, denoise: 0.45, strength: 0.9,
  },
  W7: { geometry_resolution: 256, threshold: 25, chunk_size: 8192 },
};

const FIELD_LABELS = {
  text: "设定文本（prompt）",
  negative: "负面提示词",
  prompt: "风格描述（prompt）",
  width: "宽度", height: "高度",
  seed: "随机种子", steps: "采样步数", cfg: "CFG",
  resolution: "深度图分辨率",
  strength: "法线强度 / 姿态强度", roughness_scale: "粗糙度系数", metalness: "金属度",
  duration: "时长（秒）",
  kind: "音效类型",
  action: "动作指令", frames: "帧数", denoise: "重绘强度",
  geometry_resolution: "几何分辨率", threshold: "阈值", chunk_size: "采样块大小",
};

const SELECT_OPTIONS = {
  kind: ["glass_clink", "murmur", "ambient_bar"],
  action: ["run", "attack"],
};

let workflows = [];
let currentWorkflow = null;
let pollTimer = null;

async function api(path, opts) {
  const resp = await fetch(path, opts);
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(text.slice(0, 300) || resp.statusText);
  }
  return resp.json();
}

async function loadWorkflows() {
  workflows = await api("/api/workflows");
  currentWorkflow = workflows[0]?.name;
  renderWorkflowSelect();
  renderFields();
}

function renderWorkflowSelect() {
  const box = document.getElementById("workflow-select");
  box.innerHTML = "";
  workflows.forEach((wf) => {
    const el = document.createElement("div");
    el.className = "workflow-option" + (wf.name === currentWorkflow ? " active" : "");
    el.innerHTML = `<strong>${wf.title}</strong><small>${wf.description}</small>`;
    el.onclick = () => { currentWorkflow = wf.name; renderWorkflowSelect(); renderFields(); };
    box.appendChild(el);
  });
}

function renderFields() {
  const wf = workflows.find((w) => w.name === currentWorkflow);
  const fields = document.getElementById("dynamic-fields");
  fields.innerHTML = "";
  document.getElementById("image-upload").classList.toggle("hidden", !wf || !wf.accepts_image);
  document.getElementById("submit-btn").disabled = !wf;
  const serverSel = document.getElementById("server-image");
  if (serverSel) serverSel.value = "";
  if (wf && wf.accepts_image) loadServerFiles();
  if (!wf) return;

  wf.inputs.forEach((key) => {
    const label = document.createElement("label");
    label.textContent = FIELD_LABELS[key] || key;
    fields.appendChild(label);
    let input;
    let tbtn = null;
    if (SELECT_OPTIONS[key]) {
      input = document.createElement("select");
      SELECT_OPTIONS[key].forEach((opt) => {
        const o = document.createElement("option");
        o.value = opt; o.textContent = opt;
        if (DEFAULTS[currentWorkflow]?.[key] === opt) o.selected = true;
        input.appendChild(o);
      });
    } else if (key === "text" || key === "negative" || key === "prompt") {
      input = document.createElement("textarea");
      const v = DEFAULTS[currentWorkflow][key];
      input.value = typeof v === "function" ? v() : v;
      tbtn = document.createElement("button");
      tbtn.type = "button";
      tbtn.className = "ghost small translate-btn";
      tbtn.textContent = "中文→英文";
      tbtn.onclick = () => manualTranslate(key);
    } else {
      input = document.createElement("input");
      input.type = "number";
      const v = DEFAULTS[currentWorkflow][key];
      input.value = typeof v === "function" ? v() : v;
      input.step = ["cfg", "strength", "roughness_scale", "metalness", "duration", "denoise"].includes(key) ? "0.1" : "1";
    }
    input.name = key;
    fields.appendChild(input);
    if (tbtn) fields.appendChild(tbtn);
  });
}

async function submitJob(ev) {
  ev.preventDefault();
  const params = {};
  document.querySelectorAll("#dynamic-fields input, #dynamic-fields textarea, #dynamic-fields select").forEach((el) => {
    const key = el.name;
    if (SELECT_OPTIONS[key]) params[key] = el.value;
    else if (el.tagName === "TEXTAREA") params[key] = el.value;
    else params[key] = Number(el.value);
  });
  // 提示词字段：中文自动翻译成英文（英文原样保留）
  for (const key of ["text", "negative", "prompt"]) {
    if (params[key] && /[\u4e00-\u9fff]/.test(params[key])) {
      try { params[key] = await translateText(params[key]); } catch (_) { }
    }
  }
  const fd = new FormData();
  fd.append("workflow", currentWorkflow);
  fd.append("params", JSON.stringify(params));
  fd.append("batch", (document.getElementById("batch-name").value || "").trim());
  const fileInput = document.getElementById("image-file");
  const serverSel = document.getElementById("server-image");
  const serverChoice = serverSel ? serverSel.value : "";
  if (serverChoice) {
    const [loc, ...rest] = serverChoice.split("|");
    fd.append("image_filename", rest.join("|"));
    fd.append("image_location", loc);
  } else if (fileInput.files.length) {
    fd.append("image", fileInput.files[0]);
  } else {
    const wf = workflows.find((w) => w.name === currentWorkflow);
    if (wf && wf.accepts_image) {
      alert("请选择本地图片或服务器已有图片");
      return;
    }
  }
  try {
    const job = await api("/api/jobs", { method: "POST", body: fd });
    refreshJobs();
    showDetail(job);
    startPolling(job.id);
  } catch (err) {
    alert("提交失败: " + err.message);
  }
}

function startPolling(jobId) {
  clearInterval(pollTimer);
  pollTimer = setInterval(async () => {
    try {
      const job = await api(`/api/jobs/${jobId}`);
      showDetail(job);
      refreshJobs();
      if (job.status === "done" || job.status === "error") clearInterval(pollTimer);
    } catch (_) { }
  }, 2000);
}

function showDetail(job) {
  const detail = document.getElementById("job-detail");
  detail.classList.remove("hidden");
  document.getElementById("detail-title").textContent =
    `${workflows.find((w) => w.name === job.workflow)?.title || job.workflow} · ${job.id}`;
  const status = document.getElementById("detail-status");
  const badge = `<span class="badge ${job.status}">${job.status}</span>`;
  const btag = job.batch ? `<div style="color:var(--dim);font-size:12px;margin-top:4px">批次：${job.batch}</div>` : "";
  status.innerHTML = btag + badge + (job.error ? `<br><span style="color:var(--err)">${job.error}</span>` : "");
  const preview = document.getElementById("detail-preview");
  if (job.outputs && job.outputs.length) {
    preview.innerHTML = job.outputs.map((o, i) => {
      const url = `/api/jobs/${job.id}/file/${i}`;
      const label = `下载 ${o.filename}`;
      if (o.kind === "audio" || /\.(mp3|flac|opus|wav)$/i.test(o.filename)) {
        return `<audio controls src="${url}" preload="metadata" style="width:100%"></audio><br><a href="${url}" download>${label}</a>`;
      }
      if (o.kind === "mesh" || /\.(glb|gltf|obj)$/i.test(o.filename)) {
        return `<div style="padding:8px;border:1px solid #2a2d22;border-radius:6px;color:var(--ok);font-size:13px">🧊 3D 模型已生成<br><a href="${url}" download>${label}</a></div>`;
      }
      return `<img src="${url}" alt="result"><br><a href="${url}" download>${label}</a>`;
    }).join("<br>");
    if (job.workflow === "W6" && job.status === "done") {
      preview.innerHTML += `<br><a href="/api/jobs/${job.id}/sprite-config" download="sprite_config.json">下载 JSON 图集配置</a>`;
    }
    if (job.batch) {
      const sb = encodeURIComponent(job.batch);
      preview.innerHTML += `<br><a class="scene-btn" href="/scene.html?batch=${sb}">进入 3D 场景 →</a>`;
    }
  } else {
    preview.innerHTML = "";
  }
  document.getElementById("detail-params").textContent = JSON.stringify(job.params, null, 2);
}

async function translateText(text) {
  const data = await api("/api/translate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  return data.text;
}

async function manualTranslate(key) {
  const input = document.querySelector(`[name="${key}"]`);
  if (!input) return;
  const btn = input.parentElement.querySelector(".translate-btn");
  if (btn) { btn.disabled = true; btn.textContent = "翻译中…"; }
  try {
    input.value = await translateText(input.value);
  } catch (err) {
    alert("翻译失败: " + err.message);
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = "中文→英文"; }
  }
}

async function loadServerFiles() {
  try {
    const [inputFiles, outputFiles] = await Promise.all([
      api("/api/files?location=input"),
      api("/api/files?location=output"),
    ]);
    const sel = document.getElementById("server-image");
    if (!sel) return;
    const old = sel.value;
    sel.innerHTML = '<option value="">— 上传新文件 —</option>';
    const addGroup = (label, files, location) => {
      if (!files.length) return;
      const g = document.createElement("optgroup");
      g.label = label;
      files.forEach((f) => {
        const o = document.createElement("option");
        o.value = `${location}|${f.name}`;
        o.textContent = `${f.name} (${(f.size / 1024).toFixed(0)} KB)`;
        g.appendChild(o);
      });
      sel.appendChild(g);
    };
    addGroup("输入目录（上传的图）", inputFiles, "input");
    addGroup("输出目录（历史生成）", outputFiles, "output");
    sel.value = old;
  } catch (_) { }
}

async function refreshJobs() {
  const jobs = await api("/api/jobs?limit=10");
  const list = document.getElementById("job-list");
  list.innerHTML = "";
  jobs.forEach((job) => {
    const li = document.createElement("li");
    const name = workflows.find((w) => w.name === job.workflow)?.title || job.workflow;
    const btag = job.batch ? ` <span class="batch-tag">${job.batch}</span>` : "";
    li.innerHTML = `<span class="jid">#${job.id}</span> ${name}${btag} <span class="badge ${job.status}">${job.status}</span>`;
    li.onclick = () => showDetail(job);
    list.appendChild(li);
  });
}

document.getElementById("job-form").addEventListener("submit", submitJob);
document.getElementById("refresh-files").addEventListener("click", loadServerFiles);
loadWorkflows();
refreshJobs();
