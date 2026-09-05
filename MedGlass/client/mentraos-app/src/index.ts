/**
 * MedGlass — MentraOS app for Mentra Live (camera glasses).
 *
 * Flow:
 *   Mentra Live glasses -> phone (Mentra app) -> MentraOS Cloud
 *      -> /webhook (this server) -> AppSession WebSocket
 *      -> MedGlass edge server (Python) for vision + SOAP generation
 *
 * Button-driven session lifecycle (no display on Mentra Live, so the RGB LED
 * is the in-glasses status light):
 *   - Long-press (idle)   -> START session: green LED stays on ("recording")
 *   - Short-press (active)-> capture photo -> medication OCR -> spoken findings
 *   - Long-press (active) -> END session: generate patient note, LED blinks then off
 *
 * Feedback:
 *   - audio.speak(...)          TTS prompts and summaries (no display on Live)
 *   - led.solid("green", …)     kickoff "recording" light, visible in-glasses
 *   - led.solid("white", …)     while the patient is speaking (VAD)
 *   - led.blink(...)            captured / medication / note-complete
 *   - layouts.show*Card         rendered in the phone's Mentra app
 *
 * The app also reverse-proxies the MedGlass results dashboard (/dashboard,
 * /notes, /static/*) to the edge server so it can be opened from the phone
 * browser through the same public ngrok URL.
 */

import { AppServer, AppSession, StreamType, ViewType } from "@mentra/sdk";
import type { ButtonPress } from "@mentra/sdk";
import type { Express, Request, Response } from "express";
import http from "http";
import { WebSocket, WebSocketServer } from "ws";

const MEDGLASS_URL = process.env.MEDGLASS_URL || "http://127.0.0.1:8100";
const USE_OWN_WHISPER = process.env.MEDGLASS_USE_OWN_WHISPER === "1";
// Public base URL (your ngrok domain) used to link the phone to the dashboard.
const PUBLIC_BASE_URL = (process.env.PUBLIC_BASE_URL || "").replace(/\/+$/, "");
const LED_KEEPALIVE_MS = 20000;
const LED_SOLID_MS = 30000;

interface SessionContext {
  lines: string[];
  active: boolean;
  speaking: boolean;
  keepAlive?: ReturnType<typeof setInterval>;
  session?: AppSession;
}

function requireEnv(name: string): string {
  const v = process.env[name];
  if (!v) {
    throw new Error(
      `Missing ${name} in .env — see client/mentraos-app/.env.example`,
    );
  }
  return v;
}

// ---------------------------------------------------------------- helpers

async function postJson(url: string, body: unknown): Promise<any> {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`POST ${url} -> ${res.status}: ${text.slice(0, 300)}`);
  }
  return res.json();
}

async function safeLed(fn: () => Promise<unknown>): Promise<void> {
  try {
    await fn();
  } catch (err) {
    console.warn("led:", err);
  }
}

function truncate(text: string, n: number): string {
  const t = text.replace(/\s+/g, " ").trim();
  return t.length > n ? `${t.slice(0, n - 1)}…` : t;
}

// ------------------------------------------------------- edge reverse proxy

/** Reverse-proxy a path on the MedGlass edge server through this (public) app. */
function makeProxy(edgePath: (req: Request) => string) {
  return async (req: Request, res: Response) => {
    try {
      const qs = req.url.includes("?")
        ? req.url.slice(req.url.indexOf("?"))
        : "";
      const url = `${MEDGLASS_URL}${edgePath(req)}${qs}`;
      const headers: Record<string, string> = {
        accept: req.headers.accept || "*/*",
        "content-type": req.headers["content-type"] || "application/json",
      };
      // Forward the browser's session cookie + CSRF header so login-gated
      // pages and mutations work through the tunnel (we must NOT inject the
      // dashboard token here or login is bypassed entirely).
      if (req.headers.cookie) headers["cookie"] = String(req.headers.cookie);
      const csrf = req.headers["x-csrf-token"];
      if (csrf) headers["X-CSRF-Token"] = String(csrf);
      // Forward the real client IP (set by ngrok) so the edge can rate-limit
      // and allow-list per actual client, not per proxy.
      if (req.headers["x-forwarded-for"]) {
        headers["X-Forwarded-For"] = String(req.headers["x-forwarded-for"]);
      }
      const method = (req.method || "GET").toUpperCase();
      const body = ["POST", "PUT", "PATCH", "DELETE"].includes(method)
        ? JSON.stringify(req.body ?? {})
        : undefined;
      const upstream = await fetch(url, { method, headers, body });
      const buf = Buffer.from(await upstream.arrayBuffer());
      res.status(upstream.status);
      const setCookies: string[] = [];
      upstream.headers.forEach((v, k) => {
        const lk = k.toLowerCase();
        if (lk === "set-cookie") {
          setCookies.push(v);
          return;
        }
        if (!["content-encoding", "transfer-encoding", "content-length",
              "connection", "keep-alive"].includes(lk)) {
          res.setHeader(k, v);
        }
      });
      if (setCookies.length) res.setHeader("set-cookie", setCookies);
      res.setHeader("content-length", buf.length);
      res.send(buf);
    } catch (err) {
      res.status(502).json({ error: `edge server unreachable: ${(err as Error).message}` });
    }
  };
}

function installDashboardProxy(app: Express): void {
  // Live consultation page + the endpoints it uses.
  app.get("/", makeProxy(() => "/"));
  app.get("/live", makeProxy(() => "/live"));
  app.post("/login", makeProxy(() => "/login"));
  app.post("/logout", makeProxy(() => "/logout"));
  app.post("/generate_note", makeProxy(() => "/generate_note"));
  app.get("/generate_note/stream", makeProxy(() => "/generate_note/stream"));
  app.post("/ingest/*", makeProxy((req) => `/ingest/${(req.params as any)[0]}`));
  app.post("/vision/process", makeProxy(() => "/vision/process"));
  app.post("/hud/update", makeProxy(() => "/hud/update"));
  app.get("/session/*", makeProxy((req) => `/session/${(req.params as any)[0]}`));
  app.post("/session/*", makeProxy((req) => `/session/${(req.params as any)[0]}`));
  // Results dashboard + notes + EHR downloads + case photos.
  app.get("/dashboard", makeProxy(() => "/dashboard"));
  app.get("/notes", makeProxy(() => "/notes"));
  app.get("/notes/*", makeProxy((req) => `/notes/${(req.params as any)[0]}`));
  app.delete("/notes/*", makeProxy((req) => `/notes/${(req.params as any)[0]}`));
  app.get("/photos/*", makeProxy((req) => `/photos/${(req.params as any)[0]}`));
  app.get("/tasks", makeProxy(() => "/tasks"));
  app.post("/tasks", makeProxy(() => "/tasks"));
  // Account, security (MFA) and admin endpoints.
  app.get("/me", makeProxy(() => "/me"));
  app.post("/me/mfa/enable", makeProxy(() => "/me/mfa/enable"));
  app.post("/me/mfa/confirm", makeProxy(() => "/me/mfa/confirm"));
  app.post("/me/mfa/cancel", makeProxy(() => "/me/mfa/cancel"));
  app.post("/me/mfa/disable", makeProxy(() => "/me/mfa/disable"));
  app.get("/users", makeProxy(() => "/users"));
  app.post("/users", makeProxy(() => "/users"));
  app.delete("/users/*", makeProxy((req) => `/users/${(req.params as any)[0]}`));
  app.post("/admin/purge", makeProxy(() => "/admin/purge"));
  app.get("/tts", makeProxy(() => "/tts"));
  app.get("/static/*", makeProxy((req) => `/static/${(req.params as any)[0]}`));
  if (PUBLIC_BASE_URL) {
    console.log(`Results dashboard: ${PUBLIC_BASE_URL}/dashboard`);
  }
}

// --------------------------------------------------------- websocket proxy
// Tunnels the browser live-consultation WebSockets (/ws/audio, /ws/video)
// through to the edge server so the live page works from a phone too.

const EDGE_WS_BASE = MEDGLASS_URL.replace(/^http/, "ws");
const edgeWss = new WebSocketServer({ noServer: true });

function pipeWebSockets(client: WebSocket, edge: WebSocket): void {
  edge.on("message", (data, isBinary) => {
    try { client.send(data, { binary: isBinary }); } catch { /* closed */ }
  });
  client.on("message", (data, isBinary) => {
    try { edge.send(data, { binary: isBinary }); } catch { /* closed */ }
  });
  const teardown = () => {
    try { client.close(); } catch { /* closed */ }
    try { edge.close(); } catch { /* closed */ }
  };
  edge.on("close", teardown);
  edge.on("error", teardown);
  client.on("close", teardown);
  client.on("error", teardown);
}

function installWebSocketProxy(httpServer: http.Server): void {
  httpServer.on("upgrade", (req, socket, head) => {
    const url = req.url || "";
    if (!url.startsWith("/ws/audio") && !url.startsWith("/ws/video")) {
      socket.destroy();
      return;
    }
    edgeWss.handleUpgrade(req, socket, head, (clientWs) => {
      const edgeUrl = `${EDGE_WS_BASE}${url}`;
      const edgeWs = new WebSocket(edgeUrl);
      // If the edge server never opens, don't leave the client hanging.
      const guard = setTimeout(() => teardownWebSocket(edgeWs), 10000);
      edgeWs.once("open", () => {
        clearTimeout(guard);
        pipeWebSockets(clientWs, edgeWs);
      });
      edgeWs.once("error", () => {
        clearTimeout(guard);
        teardownWebSocket(clientWs);
      });
    });
  });
  console.log(`WebSocket proxy active (${EDGE_WS_BASE}/ws/*)`);
}

function teardownWebSocket(ws: WebSocket): void {
  try { ws.close(); } catch { /* closed */ }
  try { ws.terminate(); } catch { /* closed */ }
}

// ------------------------------------------------------------------ app

class MedGlassServer extends AppServer {
  private contexts = new Map<string, SessionContext>();

  protected async onSession(
    session: AppSession,
    sessionId: string,
    userId: string,
  ): Promise<void> {
    const ctx: SessionContext = { lines: [], active: false, speaking: false, session };
    this.contexts.set(sessionId, ctx);

    session.logger.info(`MedGlass session started (user ${userId})`);
    await session.audio.speak("MedGlass ready. Press and hold the button to start a session.");
    session.layouts.showTextWall("MedGlass ready\nPress and hold to start", { view: ViewType.MAIN });
    await safeLed(() => session.led.turnOff());

    // ---- speech -> cloud STT -> edge server transcript -----------------
    // Final transcripts are only ingested while the session is active, so a
    // conversation before "start" is never included in the note.
    session.events.onTranscription(async (data) => {
      try {
        if (data.isFinal) {
          if (!ctx.active) {
            session.layouts.showDoubleTextWall("Session idle",
              "Press and hold to start recording", {
                view: ViewType.MAIN,
                durationMs: 1500,
              });
            return;
          }
          ctx.lines.push(data.text);
          session.layouts.showDoubleTextWall("Heard", truncate(data.text, 90), {
            view: ViewType.MAIN,
            durationMs: 3500,
          });
          await postJson(`${MEDGLASS_URL}/ingest/transcript`, {
            session_id: sessionId,
            text: data.text,
            confidence: data.confidence ?? null,
            speaker: data.speakerId ?? null,
          });
        } else if (ctx.active) {
          session.layouts.showDoubleTextWall("Listening…", truncate(data.text, 90), {
            view: ViewType.MAIN,
            durationMs: 1500,
          });
        }
      } catch (err) {
        session.logger.error(err, "transcription handler failed");
      }
    });

    // ---- voice activity -> white LED while speaking, green while active ---
    session.events.onVoiceActivity((vad) => {
      ctx.speaking = vad.status === true || vad.status === "true";
      void safeLed(() => this.sessionLight(session, ctx));
    });

    // ---- optional raw audio -> MedGlass whisper (GPU story) ------------
    if (USE_OWN_WHISPER) {
      session.subscribe(StreamType.AUDIO_CHUNK);
      session.events.onAudioChunk((chunk) => {
        if (!ctx.active) return;
        try {
          const pcm = Buffer.from(chunk.arrayBuffer);
          void postJson(`${MEDGLASS_URL}/ingest/audio`, {
            session_id: sessionId,
            pcm_b64: pcm.toString("base64"),
            sample_rate: chunk.sampleRate ?? 16000,
          }).catch((err) => session.logger.warn("audio ingest failed", err));
        } catch (err) {
          session.logger.warn(err, "audio chunk handling failed");
        }
      });
    }

    // ---- buttons -------------------------------------------------------
    // Long-press toggles the session; short-press captures a photo while
    // the session is active.
    session.events.onButtonPress(async (press: ButtonPress) => {
      try {
        if (press.pressType === "short") {
          if (ctx.active) {
            await this.captureAndAnalyze(session, sessionId);
          } else {
            await session.audio.speak("Press and hold to start a session.");
          }
        } else {
          if (ctx.active) {
            await this.endSession(session, sessionId, ctx);
          } else {
            await this.startSession(session, sessionId, ctx);
          }
        }
      } catch (err) {
        session.logger.error(err, "button handler failed");
        await session.audio.speak("Sorry, something went wrong.");
      }
    });

    session.layouts.showDashboardCard("MedGlass", "press and hold to start");
  }

  protected async onStop(
    sessionId: string,
    userId: string,
    reason: string,
  ): Promise<void> {
    const ctx = this.contexts.get(sessionId);
    const sess = ctx?.session;
    if (ctx?.keepAlive) clearInterval(ctx.keepAlive);
    this.contexts.delete(sessionId);
    // Make sure the recording light never stays lit after the app is stopped.
    if (sess) {
      try {
        await sess.led.turnOff();
      } catch { /* LED may already be off */ }
    }
    try {
      await fetch(`${MEDGLASS_URL}/session/${sessionId}/reset`, {
        method: "POST",
      });
    } catch {
      /* server may be down */
    }
  }

  // ---- session start / stop -------------------------------------------

  private async sessionLight(session: AppSession, ctx: SessionContext): Promise<void> {
    if (!ctx.active) {
      await session.led.turnOff();
      return;
    }
    await session.led.solid(ctx.speaking ? "white" : "green", LED_SOLID_MS);
  }

  private async startSession(
    session: AppSession,
    sessionId: string,
    ctx: SessionContext,
  ): Promise<void> {
    session.logger.info("session started (long-press)");
    ctx.lines = [];
    ctx.active = true;
    ctx.speaking = false;
    try {
      await fetch(`${MEDGLASS_URL}/session/${sessionId}/reset`, { method: "POST" });
    } catch { /* server may be down */ }

    // Internal LED on session start: steady green = recording light.
    // (The Mentra SDK exposes a single RGB LED, so this doubles as the
    // in-glasses "front" recording indicator while the session is active.)
    await safeLed(() => session.led.solid("green", LED_SOLID_MS));

    // Keep the green "recording" light alive while active.
    if (ctx.keepAlive) clearInterval(ctx.keepAlive);
    ctx.keepAlive = setInterval(() => {
      if (ctx.active && !ctx.speaking) {
        void safeLed(() => session.led.solid("green", LED_SOLID_MS));
      }
    }, LED_KEEPALIVE_MS);

    await session.audio.speak("Session started. Recording.");
    session.layouts.showTextWall("Session active\nRecording…", { view: ViewType.MAIN });
  }

  private async endSession(
    session: AppSession,
    sessionId: string,
    ctx: SessionContext,
  ): Promise<void> {
    session.logger.info("session ended (long-press) -> generating note");
    ctx.active = false;
    ctx.speaking = false;
    if (ctx.keepAlive) {
      clearInterval(ctx.keepAlive);
      ctx.keepAlive = undefined;
    }
    // Keep the recording light on while the note is generated, then make
    // sure it goes off no matter what happens (note failure, network error).
    const genKeepalive = setInterval(() => {
      void safeLed(() => session.led.solid("green", LED_SOLID_MS));
    }, 15000);
    await safeLed(() => session.led.solid("green", LED_SOLID_MS));
    await session.audio.speak("Generating your clinical note.");
    session.layouts.showTextWall("Generating patient note…", { view: ViewType.MAIN });

    let result: any = {};
    try {
      result = await postJson(`${MEDGLASS_URL}/generate_note`, {
        session_id: sessionId,
        source: "mentra",
        stream: false,
      });
    } catch (err) {
      session.logger.error(err, "note generation failed");
      await session.audio.speak("Sorry, the note could not be generated.");
    } finally {
      clearInterval(genKeepalive);
      // Lights out as soon as the session is over — no more capture light.
      await safeLed(() => session.led.turnOff());
    }

    const note: string = result.note ?? "";
    const sections: Record<string, string> = result.sections ?? {};

    // Speak a short, NON-PHI confirmation. The actual patient note is pushed to
    // the phone dashboard + edge storage below; we never send patient content
    // through the cloud TTS channel (HIPAA minimum-necessary).
    const detCount = (result.photos?.length ?? 0)
      + (result.visual_findings ?? []).filter((f: any) => f.kind === "medication").length;
    const summary = detCount > 0
      ? `Note complete. ${detCount} item${detCount === 1 ? "" : "s"} captured and processed. View it on your phone.`
      : "Note complete. View it on your phone.";
    await session.audio.speak(summary);

    // Full note -> phone dashboard cards + persistent storage.
    const labels: Record<string, string> = {
      S: "Subjective",
      O: "Objective",
      A: "Assessment",
      P: "Plan",
    };
    for (const key of ["S", "O", "A", "P"]) {
      if (sections[key]) {
        session.layouts.showDashboardCard(labels[key], truncate(sections[key], 80));
      }
    }
    session.layouts.showReferenceCard("Patient Note", truncate(note, 600), {
      view: ViewType.MAIN,
    });
    if (PUBLIC_BASE_URL) {
      session.layouts.showReferenceCard("Results Dashboard",
        `${PUBLIC_BASE_URL}/dashboard`, { view: ViewType.MAIN });
    }
    await session.simpleStorage.set(`medglass_note_${Date.now()}`, note);

    await safeLed(() => session.led.blink("green", 400, 200, 3));
    // Both LEDs off: the note is built and recorded — no more capture light.
    await safeLed(() => session.led.turnOff());

    // Reset the live session so the next start begins with a clean slate.
    try {
      await fetch(`${MEDGLASS_URL}/session/${sessionId}/reset`, { method: "POST" });
    } catch { /* server may be down */ }
  }

  // ---- photo: medication OCR ------------------------------------------

  private async captureAndAnalyze(
    session: AppSession,
    sessionId: string,
  ): Promise<void> {
    session.logger.info("capturing photo");
    // Short-press response: quick blink = "photo" shutter feedback.
    await safeLed(() => session.led.blink("white", 150, 150, 2));
    await session.audio.speak("Capturing.");

    const photo = await session.camera.requestPhoto({
      size: "medium",
      compress: "medium",
    });
    session.logger.info(`photo captured: ${photo.size} bytes (${photo.mimeType})`);

    // The front recording light goes out during the shutter; bring it right
    // back so it stays on for the rest of the session (the vision POST below
    // can take a few seconds on the CPU-only edge server).
    await safeLed(() => session.led.solid("green", LED_SOLID_MS));

    const result = await postJson(`${MEDGLASS_URL}/vision/process`, {
      session_id: sessionId,
      image_b64: photo.buffer.toString("base64"),
    });

    const meds = (result.detections ?? []).filter(
      (d: any) => d.kind === "medication" && d.ocr_text,
    );
    if (meds.length > 0) {
      const label = meds.map((m: any) => m.ocr_text).join("; ");
      // Show the label on the phone's display; the in-glasses voice line stays
      // generic so medication details are not spoken via cloud TTS.
      await session.audio.speak("Medication detected.");
      session.layouts.showReferenceCard("Medication", label, {
        view: ViewType.MAIN,
        durationMs: 8000,
      });
      await safeLed(() => session.led.blink("blue", 300, 300, 3));
    } else {
      await session.audio.speak("Photo captured.");
    }

    // Still recording — restore the steady recording light so the front
    // indicator stays on until the session is ended.
    await safeLed(() => session.led.solid("green", LED_SOLID_MS));
  }
}

// ------------------------------------------------------------------ main

const PACKAGE_NAME = requireEnv("PACKAGE_NAME");
const API_KEY = requireEnv("API_KEY");

const server = new MedGlassServer({
  packageName: PACKAGE_NAME,
  apiKey: API_KEY,
  port: Number(process.env.PORT || 3000),
  healthCheck: true,
});

// Serve the MedGlass results dashboard + live page + WebSockets through the
// same public URL so they work from the phone browser.
installDashboardProxy(server.getExpressApp());

// Bind the SDK's express app on an http server we own, so we can also proxy
// the /ws/* WebSockets (the SDK's own start() does not expose its server).
const PORT = Number(process.env.PORT || 3000);
const app = server.getExpressApp();
// The SDK registers its own `express.json()` with a 100 KB default body limit
// before we add the dashboard proxy routes, so large JSON payloads (a base64
// photo from the live page) hit "request entity too large". We pre-parse the
// JSON body ourselves at the http-server level (with a generous limit) and
// mark it as already parsed, which makes the SDK's parser skip it.
const PROXIED_JSON_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);
const MAX_JSON_BODY = 50 * 1024 * 1024; // 50 MB

function isProxiedJsonBody(req: http.IncomingMessage): boolean {
  if (!PROXIED_JSON_METHODS.has((req.method || "GET").toUpperCase())) return false;
  const ct = (req.headers["content-type"] || "").toLowerCase();
  return ct.includes("application/json");
}

function handleRequest(req: http.IncomingMessage, res: http.ServerResponse): void {
  if (!isProxiedJsonBody(req)) {
    app(req, res);
    return;
  }
  const chunks: Buffer[] = [];
  let size = 0;
  let overLimit = false;
  req.on("data", (chunk: Buffer) => {
    size += chunk.length;
    if (size > MAX_JSON_BODY) overLimit = true;
    if (!overLimit) chunks.push(chunk);
  });
  req.on("end", () => {
    if (overLimit) {
      res.statusCode = 413;
      res.end("request entity too large");
      return;
    }
    const raw = Buffer.concat(chunks).toString("utf8");
    try {
      (req as any).body = raw ? JSON.parse(raw) : {};
    } catch {
      (req as any).body = {};
    }
    (req as any)._body = true;
    app(req, res);
  });
  req.on("error", () => {
    res.statusCode = 400;
    res.end("bad request");
  });
}

const httpServer = http.createServer(handleRequest);
installWebSocketProxy(httpServer);
httpServer.listen(PORT, () => {
  console.log(`MedGlass MentraOS app running on port ${PORT}`);
  console.log(`Edge server: ${MEDGLASS_URL}`);
  if (PUBLIC_BASE_URL) {
    console.log(`Results dashboard (phone): ${PUBLIC_BASE_URL}/dashboard`);
  }
});
