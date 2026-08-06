/* MedGlass demo client.
 * One button starts the browser mic (16 kHz PCM16). Captured transcripts feed
 * the SOAP note engine server-side; this page links out to the Notes dashboard
 * (most recent session) instead of rendering transcript or note content here.
 *
 * Demo-mode notes:
 *  - Recording is mic-only (no camera / live video stream).
 *  - "Add photo" inserts a stock patient photo — there is no live capture.
 */
(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const state = {
    audioWs: null,
    audioCtx: null, processor: null, mute: null,
    stream: null,
    chunksSent: 0,
    tick: null,
    captureMode: "none",
    workletNode: null,
    pendingPhotos: [],
    patientName: "",
    sessionId: "",
    _lastPhoto: "",
  };

  const WS = location.protocol === "https:" ? "wss" : "ws";
  const BASE = `${WS}://${location.host}`;

  // Real stock patient photos (bundled locally so they never depend on a CDN
  // or CORS). Picked at random each time "Add photo" is tapped.
  const STOCK_PHOTOS = ["1", "2", "3", "4", "5", "6", "7", "8"];
  const STOCK_URL = (i) => `/static/stock/patient-${i}.jpg`;

  // ---------------------------------------------------------------- helpers
  function msg(text, cls) {
    const el = $("demo-msg");
    el.hidden = false;
    el.className = "demo-msg" + (cls ? " " + cls : "");
    el.textContent = text;
  }

  // Speak a line via the server's local TTS (espeak-ng), same mechanism as the
  // dashboard "Speak note". Returned as a WAV and played on its own <audio>
  // element so it never interferes with the mic's AudioContext.
  let sayQueue = Promise.resolve();
  function say(text) {
    const p = sayQueue.then(async () => {
      try {
        const res = await fetch("/tts?text=" + encodeURIComponent(text));
        if (!res.ok) return;
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const audio = new Audio(url);
        await new Promise((resolve) => {
          audio.onended = resolve;
          audio.onerror = resolve;
          audio.play().catch(() => resolve());
        });
        URL.revokeObjectURL(url);
      } catch (_) { /* TTS unavailable; keep session alive */ }
    });
    // Keep the queue going even if this line fails.
    sayQueue = p.catch(() => {});
    return p;
  }

  function csrfHeaders() {
    const match = document.cookie.match(/(?:^|;\s*)mg_csrf=([^;]*)/);
    return match ? { "X-CSRF-Token": decodeURIComponent(match[1]) } : {};
  }

  function permissionHint(e) {
    const n = (e && e.name) || "";
    if (n === "NotAllowedError" || n === "SecurityError") {
      return "permission was blocked. Allow microphone access for this site, then retry.";
    }
    if (n === "NotFoundError") return "no device found. Plug in a mic, then retry.";
    if (n === "NotReadableError") return "the mic is already in use by another app.";
    return (e && e.message) || "unknown error.";
  }

  function resampleTo16k(input, inRate) {
    const ratio = inRate / 16000;
    const nOut = Math.floor(input.length / ratio);
    const out = new Float32Array(nOut);
    for (let i = 0; i < nOut; i++) {
      const pos = i * ratio;
      const i0 = Math.floor(pos);
      const i1 = Math.min(i0 + 1, input.length - 1);
      const frac = pos - i0;
      out[i] = input[i0] * (1 - frac) + input[i1] * frac;
    }
    return out;
  }

  function toPcm16(f32) {
    const pcm = new Int16Array(f32.length);
    for (let i = 0; i < f32.length; i++) {
      const s = Math.max(-1, Math.min(1, f32[i]));
      pcm[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
    }
    return pcm;
  }

  // -------------------------------------------------------------------- mic
  async function openMic() {
    if (state.stream) return true;
    try {
      state.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (e) {
      msg(`Microphone unavailable — ${permissionHint(e)}`, "warn");
      return false;
    }
    // Open WebSocket FIRST so it's ready when audio samples arrive. Bind it to
    // the current demo session so this recording's transcript stays isolated.
    state.audioWs = new WebSocket(
      `${BASE}/ws/audio?session_id=${encodeURIComponent(state.sessionId)}`);
    state.audioWs.binaryType = "arraybuffer";
    state.audioWs.onopen = () => { $("audio-state").textContent = "recording"; };
    state.audioWs.onclose = () => { $("audio-state").textContent = "not recording"; };
    state.audioWs.onmessage = (ev) => {
      const m = JSON.parse(ev.data);
      if (m.type === "transcript") {
        const box = $("live-transcript");
        const body = $("live-transcript-body");
        if (box && body) {
          box.hidden = false;
          body.textContent = m.cumulative || body.textContent || "";
          body.scrollTop = body.scrollHeight;
        }
      } else if (m.type === "error") {
        msg(`transcription error: ${m.message}`, "err");
      }
    };

    // Use the device's natural sample rate (not a forced 16 kHz) and resample
    // below — forcing a non-native rate is flaky across browsers/OSes.
    const Ctx = window.AudioContext || window.webkitAudioContext;
    state.audioCtx = new Ctx();
    // Resume now; if autoplay policy keeps it suspended, keep retrying for a
    // few seconds (and on the next gesture) so the mic actually starts.
    await state.audioCtx.resume();
    let resumeTries = 0;
    const ensureRunning = () => {
      if (!state.audioCtx) return;
      if (state.audioCtx.state !== "running" && resumeTries < 12) {
        resumeTries += 1;
        state.audioCtx.resume().catch(() => {});
        setTimeout(ensureRunning, 500);
      }
    };
    setTimeout(ensureRunning, 500);
    document.addEventListener("pointerdown", ensureRunning, { once: true });
    document.addEventListener("keydown", ensureRunning, { once: true });

    const src = state.audioCtx.createMediaStreamSource(state.stream);
    state.chunksSent = 0;
    state.captureMode = "none";
    await startCapture(src);

    // Diagnostic: if the mic is "open" but no samples have been sent after a
    // few seconds, surface it instead of silently saving an empty transcript.
    setTimeout(() => {
      if (state.stream && state.chunksSent === 0) {
        msg("Microphone is open but no audio is reaching the app. Check your " +
            "mic device/permission, then stop and start the session again.", "warn");
      }
    }, 6000);
    // Live proof-of-life: show how many audio chunks have left the browser.
    state.tick = setInterval(() => {
      if (!state.stream) return;
      const ctxState = state.audioCtx ? state.audioCtx.state : "?";
      $("audio-state").textContent =
        `recording · ${state.chunksSent} chunks (${state.captureMode}) · ctx:${ctxState}`;
    }, 1000);
    return true;
  }

  function sendPcmChunk(f32) {
    if (!state.audioWs || state.audioWs.readyState !== 1) return;
    const resampled = resampleTo16k(f32, state.audioCtx.sampleRate);
    const pcm = toPcm16(resampled);
    state.audioWs.send(pcm.buffer);
    state.chunksSent += 1;
  }

  // Capture mic audio via AudioWorklet (modern + reliable). Falls back to the
  // deprecated ScriptProcessorNode where worklets aren't available (non-secure
  // origins). Both paths stream 4096-sample blocks to sendPcmChunk.
  async function startCapture(src) {
    const ctx = state.audioCtx;
    if (ctx.audioWorklet && ctx.audioWorklet.addModule) {
      try {
        await ctx.audioWorklet.addModule("/static/pcm-worklet.js?v=4");
        const node = new AudioWorkletNode(ctx, "pcm-sender");
        node.port.onmessage = (e) => sendPcmChunk(e.data);
        src.connect(node);
        // The worklet writes silence, but connecting to destination guarantees
        // the graph is pulled (processed) in every browser.
        const mute = ctx.createGain();
        mute.gain.value = 0;
        node.connect(mute);
        mute.connect(ctx.destination);
        state.workletNode = node;
        state.mute = mute;
        state.captureMode = "worklet";
        return;
      } catch (err) {
        console.warn("AudioWorklet unavailable, falling back:", err);
      }
    }
    // Fallback: ScriptProcessorNode routed through a zero-gain output so the
    // graph actually runs (onaudioprocess fires) without audible feedback.
    state.processor = ctx.createScriptProcessor(4096, 1, 1);
    state.processor.onaudioprocess = (e) => sendPcmChunk(e.inputBuffer.getChannelData(0));
    src.connect(state.processor);
    const mute = ctx.createGain();
    mute.gain.value = 0;
    state.processor.connect(mute);
    mute.connect(ctx.destination);
    state.mute = mute;
    state.captureMode = "scriptprocessor";
  }

  async function closeMic() {
    if (state.stream) {
      state.stream.getTracks().forEach((t) => t.stop());
      state.stream = null;
    }
    if (state.workletNode) {
      state.workletNode.disconnect();
      state.workletNode = null;
    }
    if (state.processor) {
      state.processor.disconnect();
      state.processor = null;
    }
    if (state.mute) {
      state.mute.disconnect();
      state.mute = null;
    }
    if (state.audioCtx) { await state.audioCtx.close(); state.audioCtx = null; }
    if (state.audioWs) { state.audioWs.close(); state.audioWs = null; }
    if (state.tick) { clearInterval(state.tick); state.tick = null; }
    $("audio-state").textContent = "not recording";
  }

  // ------------------------------------------------------------------- photo
  // "Add photo" captures from the real camera (one frame) when one is
  // available, otherwise falls back to a bundled stock patient photo.
  // Defaults to the BACK (outward) camera; a short live preview is shown in
  // the camera panel so the user can see what they're capturing, then it
  // hides and the recording session keeps running.
  async function openCameraStream() {
    // Prefer the rear/outward camera (phones), fall back to any camera.
    try {
      return await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: "environment" },
                 width: { ideal: 1280 }, height: { ideal: 720 } },
        audio: false,
      });
    } catch (_) { /* fall through */ }
    try {
      return await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
    } catch (_) {
      return null;
    }
  }

  async function captureFromCamera() {
    const stream = await openCameraStream();
    if (!stream) return null;
    const preview = $("cam-preview");
    const off = $("cam-off");
    try {
      if (preview) {
        preview.srcObject = stream;
        preview.hidden = false;
        if (off) off.hidden = true;
        try { await preview.play(); } catch (_) { /* autoplay policies */ }
      }
      // Give the sensor (and the user) a moment to settle on a usable frame.
      await new Promise((r) => setTimeout(r, 1200));
      const vw = (preview && preview.videoWidth) || 0;
      const vh = (preview && preview.videoHeight) || 0;
      if (!vw || !vh) return null;
      const c = document.createElement("canvas");
      c.width = vw; c.height = vh;
      c.getContext("2d").drawImage(preview, 0, 0, vw, vh);
      return { b64: c.toDataURL("image/jpeg", 0.85).split(",")[1],
               src: c.toDataURL("image/jpeg", 0.6), live: true };
    } finally {
      stream.getTracks().forEach((t) => t.stop());
      if (preview) { preview.srcObject = null; preview.hidden = true; }
      if (off) off.hidden = false;
    }
  }

  async function loadStockPhoto() {
    let pick = STOCK_PHOTOS[Math.floor(Math.random() * STOCK_PHOTOS.length)];
    if (state._lastPhoto && STOCK_PHOTOS.length > 1) {
      while (pick === state._lastPhoto) {
        pick = STOCK_PHOTOS[Math.floor(Math.random() * STOCK_PHOTOS.length)];
      }
    }
    state._lastPhoto = pick;
    const url = STOCK_URL(pick);
    let b64 = "";
    try {
      const r = await fetch(url);
      if (r.ok) {
        const blob = await r.blob();
        b64 = await new Promise((res, rej) => {
          const fr = new FileReader();
          fr.onload = () => res(String(fr.result).split(",")[1]);
          fr.onerror = rej;
          fr.readAsDataURL(blob);
        });
      }
    } catch (_) { /* keep empty */ }
    return { b64, src: url };
  }

  async function addPhoto() {
    const btn = $("btn-photo");
    // Photos belong to the active session (never a shared/default one).
    if (!state.sessionId) {
      msg("Start a session first, then add a photo.", "warn");
      return;
    }
    // Flicker the button while we snap.
    btn.classList.remove("flicker");
    void btn.offsetWidth;
    btn.classList.add("flicker");
    setTimeout(() => btn.classList.remove("flicker"), 1100);

    // Prefer a live camera frame, else a random bundled stock photo.
    const snap = (await captureFromCamera()) || (await loadStockPhoto());
    if (!snap.b64) {
      msg("Could not load a photo.", "warn");
      return;
    }
    // Queue locally; photos are only uploaded when the session ends.
    state.pendingPhotos.push(snap);
    renderPendingPhotos();
    msg(`${snap.live ? "Live photo" : "Stock photo"} queued — ` +
        `${state.pendingPhotos.length} photo(s) will be saved when the session ends.`, "ok");
    say("Photo captured.");
  }

  function renderPendingPhotos() {
    const strip = $("photo-strip");
    strip.innerHTML = "";
    state.pendingPhotos.forEach((p, i) => {
      const shot = document.createElement("div");
      shot.className = "shot";
      shot.title = p.live ? "Live photo (pending)" : "Stock patient photo (pending)";
      const img = document.createElement("img");
      img.src = p.src;
      img.alt = "Patient photo";
      const del = document.createElement("button");
      del.className = "shot-del";
      del.type = "button";
      del.title = "Remove this photo";
      del.innerHTML = "&times;";
      del.addEventListener("click", (e) => {
        e.stopPropagation();
        state.pendingPhotos.splice(i, 1);
        renderPendingPhotos();
        msg(state.pendingPhotos.length
          ? `Photo removed — ${state.pendingPhotos.length} photo(s) still queued.`
          : "Photo removed.", "warn");
      });
      shot.appendChild(img);
      shot.appendChild(del);
      strip.appendChild(shot);
    });
  }

  // ----------------------------------------------------------------- session
  async function startSession() {
    msg("", "");
    $("demo-msg").hidden = true;

    // Fresh session id every time so each recording gets a new random patient
    // name and keeps its own transcript/photos (nothing bleeds into shared
    // state or a cached name).
    state.sessionId = "demo-" + Date.now() + "-" +
      Math.random().toString(36).slice(2, 8);
    state.patientName = "";
    state.pendingPhotos = [];
    $("photo-strip").innerHTML = "";

    // Fetch a unique patient name for this session (randomized server-side).
    const nameP = fetch(`/session/name?session_id=${encodeURIComponent(state.sessionId)}`)
      .then((r) => r.ok ? r.json() : null)
      .then((d) => state.patientName = d?.patient_id || "")
      .catch(() => {});

    const micOk = await openMic();
    $("btn-start").querySelector("span").textContent = micOk ? "Stop session" : "Start session";
    if (!micOk) {
      msg("Could not access the microphone. Allow device access for this site, then retry.", "err");
    } else {
      msg("Session started.", "ok");
      const box = $("live-transcript");
      if (box) {
        $("live-transcript-body").textContent = "";
        box.hidden = false;
      }
      await nameP;
      say(state.patientName
        ? `Session started. Patient ${state.patientName}.`
        : "Session started.");
    }
  }

  async function stopSession(save = true) {
    await closeMic();
    $("btn-start").querySelector("span").textContent = "Start session";
    $("audio-state").textContent = "not recording";
    const box = $("live-transcript");
    if (box) box.hidden = true;
    if (save) await saveSession();
    say("Session ended. Note saved.");
  }

  // Persist the session as a Patient Note so it shows up on the dashboard.
  // Pending photos are uploaded first, then the note is generated. Uses the
  // per-session patient name so the recorded note matches the name announced.
  async function saveSession() {
    msg("Saving session…", "");
    $("demo-msg").hidden = false;
    // Upload queued photos (only now, at end of session).
    const pending = state.pendingPhotos.slice();
    state.pendingPhotos = [];
    let savedPhotos = 0;
    for (const p of pending) {
      try {
        const res = await fetch("/vision/process", {
          method: "POST",
          headers: Object.assign({ "Content-Type": "application/json" }, csrfHeaders()),
          body: JSON.stringify({ session_id: state.sessionId, image_b64: p.b64 }),
        });
        if (res.ok) savedPhotos += 1;
      } catch (_) { /* keep going; note can still save */ }
    }
    try {
      const res = await fetch("/generate_note", {
        method: "POST",
        headers: Object.assign({ "Content-Type": "application/json" }, csrfHeaders()),
        body: JSON.stringify({ session_id: state.sessionId, source: "web", stream: false,
                               patient_id: state.patientName || "" }),
      });
      const data = await res.json().catch(() => ({}));
      if (res.ok) {
        $("demo-msg").className = "demo-msg ok";
        $("demo-msg").innerHTML = `Session saved` +
          (savedPhotos ? ` with ${savedPhotos} photo(s)` : "") +
          ` — view it in <a href="/dashboard">Patient Notes</a>.`;
      } else {
        msg(data.error || "Could not save the session.", "err");
      }
    } catch (_) {
      msg("Could not save the session (service unreachable).", "warn");
    }
  }

  // ------------------------------------------------------------------- boot
  async function loadIdentity() {
    try {
      const res = await fetch("/me");
      if (!res.ok) return;
      const me = await res.json();
      const u = $("settings-user");
      if (u) u.textContent = me.username || "";
      const cu = $("user-name");
      if (cu) cu.textContent = me.username || "";
      const cr = $("user-role");
      if (cr) cr.textContent = me.role === "admin" ? "Administrator" : "Clinician";
    } catch (_) { /* offline */ }
  }
  // Auth guard: if the session is gone, never show cached/back-button content.
  fetch("/me").then((r) => {
    if (r.status === 401) location.replace("/");
  }).catch(() => { /* offline */ });
  loadIdentity();
  $("btn-start").addEventListener("click", () => {
    if (state.stream) stopSession();
    else startSession();
  });
  $("btn-photo").addEventListener("click", addPhoto);
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
    const match = document.cookie.match(/(?:^|;\s*)mg_csrf=([^;]*)/);
    try {
      await fetch("/logout", {
        method: "POST",
        headers: match ? { "X-CSRF-Token": decodeURIComponent(match[1]) } : {},
      });
    } catch (_) { /* noop */ }
    location.href = "/";
  });
  window.addEventListener("beforeunload", () => { stopSession(false); });
})();