const BASE = "/api";

export async function getSettings() {
  const res = await fetch(`${BASE}/settings`);
  if (!res.ok) throw new Error(`Settings fetch failed: ${res.status}`);
  return res.json();
}

export async function updateSettings({ apiToken, model }) {
  const body = {};
  if (apiToken !== undefined) body.api_token = apiToken;
  if (model !== undefined) body.model = model;
  const res = await fetch(`${BASE}/settings`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`Settings update failed: ${res.status}`);
  return res.json();
}

export async function getPresets() {
  const res = await fetch(`${BASE}/presets`);
  if (!res.ok) throw new Error(`Presets fetch failed: ${res.status}`);
  return res.json();
}

export async function createJob({
  imageFile,
  presetId,
  subjectPrompt,
  customMotionPrompt,
  width,
  height,
  seconds,
  frameRate,
}) {
  const form = new FormData();
  form.append("image", imageFile);
  form.append("preset_id", presetId);
  form.append("subject_prompt", subjectPrompt);
  form.append("custom_motion_prompt", customMotionPrompt || "");
  form.append("width", String(width));
  form.append("height", String(height));
  form.append("seconds", String(seconds));
  form.append("frame_rate", String(frameRate));

  const res = await fetch(`${BASE}/jobs`, { method: "POST", body: form });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Job submission failed: ${res.status}`);
  }
  return res.json();
}

export async function createDrawJob({
  canvasDataURI,
  presetId,
  subjectPrompt,
  customMotionPrompt,
  width,
  height,
  seconds,
  frameRate,
}) {
  const res = await fetch(`${BASE}/jobs/draw`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      canvas_data_uri: canvasDataURI,
      preset_id: presetId,
      subject_prompt: subjectPrompt,
      custom_motion_prompt: customMotionPrompt || "",
      width,
      height,
      seconds,
      frame_rate: frameRate,
    }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Draw job submission failed: ${res.status}`);
  }
  return res.json();
}

export async function getJob(jobId) {
  const res = await fetch(`${BASE}/jobs/${jobId}`);
  if (!res.ok) throw new Error(`Job status check failed: ${res.status}`);
  return res.json();
}

export function getJobVideoUrl(jobId) {
  return `${BASE}/jobs/${jobId}/video`;
}

export function getJobThumbUrl(jobId) {
  return `${BASE}/jobs/${jobId}/thumb`;
}
