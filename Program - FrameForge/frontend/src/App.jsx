import { useEffect, useRef, useState } from "react";
import MotionPresetPicker from "./components/MotionPresetPicker";
import DrawCanvas from "./components/DrawCanvas";
import { getSettings, updateSettings, getPresets, createJob, createDrawJob, getJob, getJobVideoUrl, getJobThumbUrl } from "./lib/api";
import "./App.css";

const POLL_MS = 2500;

const ASPECT_PRESETS = [
  { label: "16:9", width: 1280, height: 720 },
  { label: "9:16", width: 720, height: 1280 },
  { label: "1:1", width: 1024, height: 1024 },
  { label: "4:3", width: 1024, height: 768 },
];

const LENGTH_CHIPS = [
  { label: "2s", seconds: 2.0 },
  { label: "4s", seconds: 4.0 },
  { label: "8s", seconds: 8.0 },
];

export default function App() {
  const [presets, setPresets] = useState([]);

  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settings, setSettings] = useState(null);
  const [apiKeyInput, setApiKeyInput] = useState("");
  const [settingsSaving, setSettingsSaving] = useState(false);
  const [settingsMsg, setSettingsMsg] = useState(null);
  const [backendInfo, setBackendInfo] = useState(null);

  const [sourceMode, setSourceMode] = useState("upload");
  const drawCanvasRef = useRef(null);

  const [imageFile, setImageFile] = useState(null);
  const [imagePreviewUrl, setImagePreviewUrl] = useState(null);
  const [selectedPresetId, setSelectedPresetId] = useState("dolly_in");
  const [subjectPrompt, setSubjectPrompt] = useState("");
  const [customMotionPrompt, setCustomMotionPrompt] = useState("");

  const [width, setWidth] = useState(1280);
  const [height, setHeight] = useState(720);
  const [seconds, setSeconds] = useState(4.0);
  const [frameRate, setFrameRate] = useState(24);
  const [motionIntensity, setMotionIntensity] = useState(1.0);
  const [seed, setSeed] = useState(-1);
  const [lockedSeed, setLockedSeed] = useState("");

  const [job, setJob] = useState(null);
  const [submitError, setSubmitError] = useState(null);
  const [submitNote, setSubmitNote] = useState(null);
  const pollRef = useRef(null);

  const [galleryJobs, setGalleryJobs] = useState([]);

  useEffect(() => {
    fetch("/api/gpu")
      .then(r => r.ok ? r.json() : null)
      .then(data => { if (data) setBackendInfo(data); })
      .catch(() => {});
    getSettings()
      .then((data) => setSettings(data))
      .catch(() => {});
    getPresets()
      .then((data) => setPresets(data.presets))
      .catch(() => {});
    refreshGallery();
  }, []);

  useEffect(() => {
    if (!job || job.status === "done" || job.status === "failed") {
      if (pollRef.current) clearInterval(pollRef.current);
      if (job && job.status === "done") refreshGallery();
      return;
    }
    pollRef.current = setInterval(async () => {
      try {
        const updated = await getJob(job.id);
        setJob(updated);
      } catch {
        // transient poll failure -- next tick will retry
      }
    }, POLL_MS);
    return () => clearInterval(pollRef.current);
  }, [job]);

  async function refreshGallery() {
    try {
      const res = await fetch("/api/jobs");
      if (!res.ok) return;
      const data = await res.json();
      const items = (data.jobs || []).filter(j => j.status === "done" && j.result_video_path);
      setGalleryJobs(items.reverse());
    } catch (e) {
      console.warn("failed to refresh gallery", e);
    }
  }

  function handleImageChange(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    setImageFile(file);
    setImagePreviewUrl(URL.createObjectURL(file));
  }

  function applyAspect(preset) {
    setWidth(preset.width);
    setHeight(preset.height);
  }

  function applyLength(sec) {
    setSeconds(sec);
  }

  async function handleSaveApiKey(e) {
    e.preventDefault();
    setSettingsSaving(true);
    setSettingsMsg(null);
    try {
      const result = await updateSettings({ apiToken: apiKeyInput });
      setSettings(result);
      setApiKeyInput("");
      setSettingsMsg("API key saved.");
    } catch (err) {
      setSettingsMsg(`Error: ${err.message}`);
    } finally {
      setSettingsSaving(false);
    }
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setSubmitError(null);
    setSubmitNote(null);

    const isLocalMode = settings?.video_generation_mode === "local" || settings?.use_local_gpu;
    if (!isLocalMode && !settings?.api_token_configured) {
      setSubmitError("Set your Replicate API key in Settings first.");
      return;
    }

    if (sourceMode === "upload" && !imageFile) {
      setSubmitError("Choose a source image first.");
      return;
    }
    if (sourceMode === "draw" && !drawCanvasRef.current) {
      setSubmitError("Drawing canvas not ready.");
      return;
    }
    if (!subjectPrompt.trim()) {
      setSubmitError("Describe the subject/scene before rendering.");
      return;
    }
    if (selectedPresetId === "custom" && !customMotionPrompt.trim()) {
      setSubmitError("Custom preset needs a motion description.");
      return;
    }

    try {
      let result;
      const payload = {
        presetId: selectedPresetId,
        subjectPrompt,
        customMotionPrompt,
        width,
        height,
        seconds,
        frameRate,
        seed: seed >= 0 ? seed : undefined,
        motionIntensity: motionIntensity,
      };

      if (sourceMode === "draw") {
        const canvas = drawCanvasRef.current;
        const dataURI = canvas._exportDataURI ? canvas._exportDataURI() : canvas.toDataURL("image/png");
        result = await createDrawJob({ ...payload, canvasDataURI: dataURI });
      } else {
        result = await createJob({ ...payload, imageFile });
      }
      setJob(result.job);
      setSubmitNote(result.dimension_adjustment_note);
    } catch (err) {
      setSubmitError(err.message);
    }
  }

  const selectedPreset = presets.find((p) => p.id === selectedPresetId);

  return (
    <div className="page">
      <header className="topbar">
        <div className="wordmark">FRAMEFORGE</div>
        <div className="topbar__subtitle">
          Image → Video • {settings?.video_generation_mode === "local" ? "Local GPU" : settings?.video_generation_mode === "replicate" ? "Replicate Cloud" : "Auto"}
          {backendInfo && (
            <span className="backend-badge">
              {backendInfo.backend.toUpperCase()}
            </span>
          )}
        </div>
        <button className="settings-toggle" onClick={() => setSettingsOpen(!settingsOpen)}>
          {settingsOpen ? "Close" : "Settings"}
        </button>
      </header>

      {!settings?.api_token_configured && !settingsOpen && settings?.video_generation_mode !== "local" && !settings?.use_local_gpu && (
        <div className="api-warning">
          <span className="api-warning__icon">⚠</span>
          No API key configured —{" "}
          <button className="api-warning__link" onClick={() => setSettingsOpen(true)}>
            add your Replicate token
          </button>{" "}
          to start generating.
        </div>
      )}

      {settingsOpen && (
        <div className="settings-panel">
          <form className="settings-form" onSubmit={handleSaveApiKey}>
            <label className="field-label" htmlFor="api-key">Replicate API Token</label>
            <div className="settings-form__row">
              <input
                id="api-key"
                type="password"
                className="text-input settings-form__input"
                placeholder={settings?.api_token_preview || "r8_..."}
                value={apiKeyInput}
                onChange={(e) => setApiKeyInput(e.target.value)}
              />
              <button type="submit" className="settings-form__save" disabled={settingsSaving || !apiKeyInput.trim()}>
                {settingsSaving ? "Saving…" : "Save"}
              </button>
            </div>
            <p className="settings-form__hint">
              Get a free token at{" "}
              <a href="https://replicate.com/account/api-tokens" target="_blank" rel="noreferrer">
                replicate.com/account/api-tokens
              </a>
            </p>
            {settingsMsg && <p className={settingsMsg.startsWith("Error") ? "error-text" : "note-text"}>{settingsMsg}</p>}
            {settings?.api_token_configured && <p className="note-text">✓ Token configured ({settings.api_token_preview})</p>}
          </form>

          {backendInfo && (
            <div className="gpu-info">
              <label className="field-label">GPU Backend</label>
              <div className="gpu-info__chips">
                <span className="chip chip--primary">{backendInfo.backend.toUpperCase()}</span>
                <span className="chip chip--secondary">{backendInfo.device_name || "Local GPU"}</span>
                {backendInfo.fp16_support && <span className="chip chip--success">FP16</span>}
              </div>
              <p className="note-text">Mode: <strong>{settings?.video_generation_mode}</strong> | Local GPU: <strong>{settings?.use_local_gpu ? "Yes" : "No"}</strong></p>
            </div>
          )}
        </div>
      )}

      <main className="layout">
        <section className="panel panel--source">
          <div className="panel__header">
            <h2 className="panel__title">01 — Source</h2>
            <div className="mode-toggle">
              <button className={`mode-toggle__btn ${sourceMode === "upload" ? "mode-toggle__btn--active" : ""}`} onClick={() => setSourceMode("upload")}>Upload</button>
              <button className={`mode-toggle__btn ${sourceMode === "draw" ? "mode-toggle__btn--active" : ""}`} onClick={() => setSourceMode("draw")}>Draw</button>
            </div>
          </div>

          {sourceMode === "upload" ? (
            <label className="dropzone">
              <input type="file" accept="image/*" onChange={handleImageChange} hidden />
              {imagePreviewUrl ? <img src={imagePreviewUrl} alt="Selected source" className="dropzone__preview" /> : <span className="dropzone__prompt">Click to choose an image</span>}
            </label>
          ) : (
            <DrawCanvas onCanvasReady={(canvas) => (drawCanvasRef.current = canvas)} />
          )}

          <label className="field-label" htmlFor="subject">Describe the subject / scene</label>
          <textarea id="subject" className="text-input" rows={3} placeholder="a woman standing in a sunlit garden, smiling" value={subjectPrompt} onChange={(e) => setSubjectPrompt(e.target.value)} />
        </section>

        <section className="panel panel--motion">
          <h2 className="panel__title">02 — Motion</h2>
          <MotionPresetPicker presets={presets} selectedId={selectedPresetId} onSelect={setSelectedPresetId} />

          <div className="control-stack">
            <label className="field-label">Aspect Ratio</label>
            <div className="chip-row">
              {ASPECT_PRESETS.map((p) => (
                <button key={p.label} className={`chip ${width === p.width && height === p.height ? "chip--active" : ""}`} onClick={() => applyAspect(p)}>{p.label}</button>
              ))}
            </div>

            <label className="field-label">Length</label>
            <div className="chip-row">
              {LENGTH_CHIPS.map((c) => (
                <button key={c.label} className={`chip ${seconds === c.seconds ? "chip--active" : ""}`} onClick={() => applyLength(c.seconds)}>{c.label}</button>
              ))}
            </div>

            <label className="field-label">Motion Intensity: {motionIntensity.toFixed(1)}x</label>
            <input type="range" min="0.2" max="2.0" step="0.1" value={motionIntensity} onChange={(e) => setMotionIntensity(parseFloat(e.target.value))} className="slider" />

            {selectedPresetId === "custom" && (
              <>
                <label className="field-label" htmlFor="custom-motion">Describe the camera motion</label>
                <textarea id="custom-motion" className="text-input" rows={2} placeholder="camera whip-pans left to right following the subject" value={customMotionPrompt} onChange={(e) => setCustomMotionPrompt(e.target.value)} />
              </>
            )}

            {selectedPreset && selectedPresetId !== "custom" && (
              <p className="preset-preview-text">
                <span className="mono">prompt add-on:</span> {selectedPreset.prompt_fragment}
              </p>
            )}
          </div>
        </section>

        <section className="panel panel--action">
          <h2 className="panel__title">03 — Render</h2>
          <div className="render-meta">
            <div className="render-meta__item"><span className="mono">{width}×{height}</span></div>
            <div className="render-meta__item"><span className="mono">{seconds}s</span></div>
            <div className="render-meta__item"><span className="mono">{frameRate}fps</span></div>
          </div>
          <button className="render-button" onClick={handleSubmit} disabled={job && isInFlight(job.status)}>
            {job && isInFlight(job.status) ? "Rendering…" : "Generate Video"}
          </button>

          {submitError && <p className="error-text">{submitError}</p>}
          {submitNote && !job?.error_message && <p className="note-text">{submitNote}</p>}

          {job && <JobStatusView job={job} />}
        </section>
      </main>

      <section className="gallery-section">
        <div className="gallery-header">
          <h2 className="panel__title">Results Gallery</h2>
          <button className="settings-toggle" onClick={refreshGallery}>Refresh</button>
        </div>
        {galleryJobs.length === 0 && <p className="note-text">No completed renders yet.</p>}
        <div className="gallery-grid">
          {galleryJobs.map((j) => (
            <div key={j.id} className="gallery-card">
              <a href={getJobVideoUrl(j.id)} target="_blank" rel="noreferrer">
                <img src={getJobThumbUrl(j.id)} alt="" className="gallery-thumb" />
              </a>
              <div className="gallery-meta">
                <span className="mono">{j.width}×{j.height}</span>
                <span className="mono">{j.frame_count}f</span>
                <span className="mono">seed {j.seed}</span>
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

function isInFlight(status) {
  return ["queued", "submitted", "running", "downloading"].includes(status);
}

function JobStatusView({ job }) {
  return (
    <div className="job-status">
      <div className={`job-status__row job-status__row--${job.status}`}>
        <span className="job-status__dot" />
        <span className="job-status__label">{job.status}</span>
        <span className="job-status__note">{job.progress_note}</span>
      </div>

      {job.status === "failed" && job.error_message && (
        <p className="error-text">{job.error_message}</p>
      )}

      {job.status === "done" && (
        <video className="result-video" controls src={getJobVideoUrl(job.id)} />
      )}
    </div>
  );
}