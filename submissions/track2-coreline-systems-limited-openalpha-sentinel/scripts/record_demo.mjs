#!/usr/bin/env node

import { execFile, spawn } from "node:child_process";
import { mkdir, mkdtemp, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import process from "node:process";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);
const root = path.resolve(import.meta.dirname, "..");
const appUrl = process.env.OPENALPHA_UI_URL || "http://127.0.0.1:8765/";
const chromePath = process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const debugPort = Number(process.env.CHROME_DEBUG_PORT || "9450");
const speed = Number(process.env.OAS_DEMO_SPEED || "1");
const headless = process.env.OAS_HEADLESS === "1";
const recordEnabled = process.env.OAS_SKIP_RECORDING !== "1";
const skipMutations = process.env.OAS_SKIP_MUTATIONS === "1";
const skipGpuMonitor = process.env.OAS_SKIP_GPU_MONITOR === "1";
const recordingSeconds = Number(process.env.OAS_RECORDING_SECONDS || "220");
const outputDir = path.join(root, "data", "video");
const stamp = new Date().toISOString().replaceAll(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z");
const outputPath = process.env.OAS_VIDEO_OUTPUT || path.join(outputDir, `OpenAlpha-Sentinel-Demo-${stamp}.mov`);
const manifestPath = outputPath.replace(/\.mov$/i, ".json");
const profile = await mkdtemp(path.join(os.tmpdir(), "openalpha-recording-"));

if (!Number.isFinite(speed) || speed <= 0) throw new Error("OAS_DEMO_SPEED must be a positive number");
if (!Number.isInteger(debugPort) || debugPort < 1 || debugPort > 65535) throw new Error("CHROME_DEBUG_PORT is invalid");
if (!Number.isInteger(recordingSeconds) || recordingSeconds < 180 || recordingSeconds > 300) {
  throw new Error("OAS_RECORDING_SECONDS must be an integer between 180 and 300");
}

await mkdir(outputDir, { recursive: true });
await writeFile(path.join(profile, "First Run"), "");

const startedAt = new Date();
let socket;
let chrome;
let recorder;
let recorderCompletion;
let sequence = 0;
const pending = new Map();

function delay(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

async function hold(milliseconds) {
  await delay(Math.max(80, Math.round(milliseconds * speed)));
}

function elapsed() {
  const seconds = Math.max(0, Math.round((Date.now() - startedAt.getTime()) / 1000));
  return `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
}

async function waitForHttp(url, timeout = 30000) {
  const deadline = Date.now() + timeout;
  let lastError;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url, { signal: AbortSignal.timeout(2500) });
      if (response.ok) return response;
      lastError = new Error(`${url} returned ${response.status}`);
    } catch (error) {
      lastError = error;
    }
    await delay(250);
  }
  throw new Error(`Timed out waiting for ${url}: ${lastError?.message || "unknown error"}`);
}

async function waitForDebugger() {
  await waitForHttp(`http://127.0.0.1:${debugPort}/json/version`, 20000);
  const deadline = Date.now() + 10000;
  while (Date.now() < deadline) {
    const response = await fetch(`http://127.0.0.1:${debugPort}/json/list`);
    const targets = await response.json();
    const target = targets.find((item) => item.type === "page" && item.url.startsWith(appUrl));
    if (target) return target;
    await delay(100);
  }
  throw new Error("Chrome opened, but the OpenAlpha page target was not found");
}

function command(method, params = {}) {
  sequence += 1;
  const id = sequence;
  return new Promise((resolve, reject) => {
    pending.set(id, { resolve, reject });
    socket.send(JSON.stringify({ id, method, params }));
  });
}

async function evaluate(expression) {
  const result = await command("Runtime.evaluate", {
    expression,
    awaitPromise: true,
    returnByValue: true,
  });
  if (result.exceptionDetails) {
    const detail = result.exceptionDetails.exception?.description || result.exceptionDetails.text;
    throw new Error(detail || "Page evaluation failed");
  }
  return result.result?.value;
}

async function waitForPage(expression, timeout = 30000, label = expression) {
  const deadline = Date.now() + timeout;
  let lastError;
  while (Date.now() < deadline) {
    try {
      if (await evaluate(`Boolean(${expression})`)) return;
    } catch (error) {
      lastError = error;
    }
    await delay(200);
  }
  throw new Error(`Timed out waiting for ${label}${lastError ? `: ${lastError.message}` : ""}`);
}

function installRecordingUi() {
  document.getElementById("oas-recording-root")?.remove();
  document.getElementById("oas-recording-style")?.remove();

  const style = document.createElement("style");
  style.id = "oas-recording-style";
  style.textContent = `
    body.oas-recording .sidebar {
      min-height: calc(100vh - 120px) !important;
      bottom: 120px !important;
    }
    body.oas-recording .view {
      min-height: calc(100vh - 120px) !important;
      padding-top: 30px !important;
      padding-bottom: 30px !important;
    }
    body.oas-recording .chat-workspace {
      height: calc(100vh - 246px) !important;
      min-height: 360px !important;
    }
    body.oas-recording dialog[open] {
      transform: translateY(-50px);
      max-height: calc(100vh - 145px) !important;
    }
    #oas-recording-root {
      position: fixed;
      z-index: 2147483647;
      inset: 0;
      pointer-events: none;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      letter-spacing: 0;
    }
    #oas-caption {
      position: fixed;
      z-index: 2147483647;
      right: 0;
      bottom: 0;
      left: 0;
      display: grid;
      height: 120px;
      padding: 17px 28px;
      grid-template-columns: 170px minmax(0, 1fr) 176px;
      align-items: center;
      gap: 22px;
      color: #f8fbf9;
      background: #121916;
      border-top: 4px solid #35ba8e;
      box-shadow: 0 -10px 30px rgb(0 0 0 / 18%);
    }
    #oas-caption-scene {
      color: #74d8b5;
      font-size: 12px;
      font-weight: 750;
      line-height: 1.35;
      text-transform: uppercase;
    }
    #oas-caption-text {
      color: #fff;
      font-size: 19px;
      font-weight: 540;
      line-height: 1.35;
    }
    #oas-caption-meta {
      color: #b9c7c1;
      font-size: 11px;
      line-height: 1.5;
      text-align: right;
    }
    #oas-caption-meta strong {
      display: block;
      color: #fff;
      font-size: 12px;
    }
    #oas-cursor {
      position: fixed;
      z-index: 2147483646;
      top: 0;
      left: 0;
      width: 22px;
      height: 22px;
      border: 3px solid #fff;
      border-radius: 50%;
      background: #e6493d;
      box-shadow: 0 2px 10px rgb(0 0 0 / 40%);
      opacity: 0;
      transform: translate(-50%, -50%);
      transition: top 420ms cubic-bezier(.2,.8,.2,1), left 420ms cubic-bezier(.2,.8,.2,1), opacity 160ms;
    }
    #oas-focus-ring {
      position: fixed;
      z-index: 2147483645;
      border: 3px solid rgb(230 73 61 / 82%);
      border-radius: 7px;
      box-shadow: 0 0 0 4px rgb(255 255 255 / 75%);
      opacity: 0;
      transition: top 420ms cubic-bezier(.2,.8,.2,1), left 420ms cubic-bezier(.2,.8,.2,1), width 420ms, height 420ms, opacity 160ms;
    }
    #oas-proof {
      position: fixed;
      z-index: 2147483644;
      inset: 0 0 120px 0;
      display: none;
      overflow: hidden;
      color: #eef5f1;
      background: #101513;
    }
    #oas-proof.is-visible { display: block; }
    .oas-proof-shell {
      display: grid;
      height: 100%;
      padding: 34px 44px 28px;
      grid-template-rows: auto minmax(0, 1fr) auto;
      gap: 24px;
    }
    .oas-proof-header { display: flex; align-items: end; justify-content: space-between; gap: 24px; }
    .oas-proof-kicker { margin: 0 0 7px; color: #51d2a2; font-size: 12px; font-weight: 800; text-transform: uppercase; }
    .oas-proof-title { margin: 0; color: #fff; font-size: 32px; line-height: 1.1; }
    .oas-proof-chip { padding: 7px 10px; color: #d7f9ec; background: #153e32; border: 1px solid #2e7b63; border-radius: 4px; font-size: 12px; }
    .oas-proof-grid { display: grid; min-height: 0; grid-template-columns: .9fr 1.1fr; gap: 18px; }
    .oas-proof-panel { min-width: 0; padding: 20px; overflow: hidden; background: #1a211e; border: 1px solid #35413c; border-radius: 6px; }
    .oas-proof-panel h2 { margin: 0 0 15px; color: #fff; font-size: 17px; }
    .oas-proof-panel pre { margin: 0; color: #cce8dc; font: 12px/1.55 ui-monospace, SFMono-Regular, Menlo, monospace; white-space: pre-wrap; overflow-wrap: anywhere; }
    .oas-proof-metric { display: flex; align-items: baseline; gap: 8px; margin-bottom: 12px; }
    .oas-proof-metric strong { color: #fff; font-size: 34px; }
    .oas-proof-metric span { color: #9fb0a9; font-size: 12px; }
    .oas-bars { display: flex; height: 126px; align-items: end; gap: 5px; border-bottom: 1px solid #51615a; }
    .oas-bar { min-width: 5px; flex: 1; background: #e85f50; border-radius: 2px 2px 0 0; }
    .oas-proof-note { margin-top: 12px; color: #9fb0a9; font-size: 11px; line-height: 1.5; }
    .oas-proof-footer { display: flex; justify-content: space-between; gap: 20px; color: #9fb0a9; font-size: 11px; }
    .oas-benchmark-table { width: 100%; border-collapse: collapse; color: #eef5f1; font-size: 13px; }
    .oas-benchmark-table th, .oas-benchmark-table td { padding: 11px 10px; border-bottom: 1px solid #35413c; text-align: left; }
    .oas-benchmark-table th { color: #9fb0a9; font-size: 11px; text-transform: uppercase; }
    .oas-benchmark-table td:last-child { color: #74d8b5; font-weight: 750; }
    .oas-close-shell { display: grid; height: 100%; padding: 48px; place-content: center; text-align: center; background: #f4f7f5; color: #17201c; }
    .oas-close-mark { display: grid; width: 68px; height: 68px; margin: 0 auto 20px; place-items: center; color: #fff; background: #13745a; border-radius: 7px; font-size: 21px; font-weight: 800; }
    .oas-close-shell h1 { margin: 0 0 10px; font-size: 48px; }
    .oas-close-shell .oas-tagline { margin: 0 0 28px; color: #52615a; font-size: 20px; }
    .oas-close-shell .oas-repo { display: inline-block; margin: 0 auto 20px; padding: 10px 14px; color: #174f3f; background: #e4f2ed; border: 1px solid #b9d9cd; border-radius: 5px; font: 14px ui-monospace, SFMono-Regular, Menlo, monospace; }
    .oas-close-shell .oas-limit { max-width: 850px; margin: 0 auto; color: #6a756f; font-size: 13px; line-height: 1.6; }
  `;
  document.head.append(style);
  document.body.classList.add("oas-recording");

  const root = document.createElement("div");
  root.id = "oas-recording-root";
  root.innerHTML = `
    <div id="oas-proof"></div>
    <div id="oas-focus-ring"></div>
    <div id="oas-cursor"></div>
    <div id="oas-caption">
      <div id="oas-caption-scene">OpenAlpha Sentinel</div>
      <div id="oas-caption-text">Preparing the local demonstration.</div>
      <div id="oas-caption-meta"><strong>LOCALHOST</strong>127.0.0.1:8765<br>Coreline Systems Limited</div>
    </div>`;
  document.body.append(root);

  window.__oasCaption = (scene, text) => {
    document.getElementById("oas-caption-scene").textContent = scene;
    document.getElementById("oas-caption-text").textContent = text;
  };
  window.__oasRootTo = (selector) => {
    const destination = selector ? document.querySelector(selector) : document.body;
    const recordingRoot = document.getElementById("oas-recording-root");
    if (destination && recordingRoot) destination.append(recordingRoot);
  };
  window.__oasMove = (selector) => {
    const element = document.querySelector(selector);
    if (!element) return false;
    element.scrollIntoView({ block: "center", inline: "center", behavior: "smooth" });
    const rect = element.getBoundingClientRect();
    const cursor = document.getElementById("oas-cursor");
    const ring = document.getElementById("oas-focus-ring");
    cursor.style.left = `${rect.left + rect.width / 2}px`;
    cursor.style.top = `${rect.top + rect.height / 2}px`;
    cursor.style.opacity = "1";
    ring.style.left = `${Math.max(3, rect.left - 4)}px`;
    ring.style.top = `${Math.max(3, rect.top - 4)}px`;
    ring.style.width = `${Math.min(innerWidth - rect.left - 3, rect.width + 8)}px`;
    ring.style.height = `${Math.min(innerHeight - rect.top - 123, rect.height + 8)}px`;
    ring.style.opacity = "1";
    return true;
  };
  window.__oasProof = (html) => {
    const proof = document.getElementById("oas-proof");
    proof.innerHTML = html || "";
    proof.classList.toggle("is-visible", Boolean(html));
    document.getElementById("oas-cursor").style.opacity = "0";
    document.getElementById("oas-focus-ring").style.opacity = "0";
  };

  const nativeFetch = window.fetch.bind(window);
  window.__oasChatResponses = [];
  window.fetch = async (...args) => {
    const response = await nativeFetch(...args);
    const target = String(args[0] instanceof Request ? args[0].url : args[0]);
    if (target.includes("/api/chat")) {
      response.clone().json().then((payload) => window.__oasChatResponses.push(payload)).catch(() => {});
    }
    return response;
  };
}

async function setCaption(scene, text) {
  console.log(`[${elapsed()}] ${scene}`);
  await evaluate(`window.__oasCaption(${JSON.stringify(scene)}, ${JSON.stringify(text)})`);
}

async function move(selector) {
  const found = await evaluate(`window.__oasMove(${JSON.stringify(selector)})`);
  if (!found) throw new Error(`Could not find ${selector}`);
  await hold(650);
}

async function click(selector) {
  await move(selector);
  const clicked = await evaluate(`(() => { const element = document.querySelector(${JSON.stringify(selector)}); if (!element) return false; element.click(); return true; })()`);
  if (!clicked) throw new Error(`Could not click ${selector}`);
  await hold(550);
}

async function clickByText(containerSelector, text) {
  const selector = await evaluate(`(() => {
    const items = [...document.querySelectorAll(${JSON.stringify(containerSelector)})];
    const index = items.findIndex((item) => item.textContent.includes(${JSON.stringify(text)}));
    if (index < 0) return "";
    items[index].dataset.oasTarget = "true";
    return "[data-oas-target=true]";
  })()`);
  if (!selector) throw new Error(`Could not find ${text} in ${containerSelector}`);
  await click(selector);
  await evaluate(`document.querySelector(${JSON.stringify(selector)})?.removeAttribute("data-oas-target")`);
}

async function typeText(selector, text, totalMilliseconds = 1800) {
  await move(selector);
  await evaluate(`(async () => {
    const input = document.querySelector(${JSON.stringify(selector)});
    if (!input) throw new Error("Input not found");
    input.focus();
    input.value = "";
    const text = ${JSON.stringify(text)};
    const delay = ${Math.max(1, Math.round(totalMilliseconds / Math.max(1, text.length)))};
    for (const character of text) {
      input.value += character;
      input.dispatchEvent(new Event("input", { bubbles: true }));
      await new Promise((resolve) => setTimeout(resolve, delay * ${speed}));
    }
  })()`);
}

async function selectValue(selector, value) {
  await move(selector);
  const selected = await evaluate(`(() => {
    const input = document.querySelector(${JSON.stringify(selector)});
    if (!input) return false;
    input.value = ${JSON.stringify(value)};
    input.dispatchEvent(new Event("change", { bubbles: true }));
    return true;
  })()`);
  if (!selected) throw new Error(`Could not select ${selector}`);
}

async function navigate(view) {
  const selector = `.nav-item[data-view="${view}"]`;
  await click(selector);
  await waitForPage(`!document.querySelector('[data-view-panel="${view}"]').hidden`, 10000, `${view} view`);
}

function shellQuote(value) {
  return `'${String(value).replaceAll("'", `'"'"'`)}'`;
}

function startGpuMonitor() {
  if (skipGpuMonitor) {
    return Promise.resolve({ samples: [], stderr: "GPU monitor skipped by OAS_SKIP_GPU_MONITOR" });
  }
  const remoteCommand = [
    "for i in $(seq 1 48); do",
    "printf \"%s\\t\" \"$(date -u +%H:%M:%S.%3N)\";",
    "rocm-smi --showuse --showmeminfo vram --json;",
    "sleep 0.15;",
    "done",
  ].join(" ");
  const localCommand = [
    'source "$PWD/scripts/lib/server.sh"',
    'server_init "$PWD"',
    `server_remote_capture bash -lc ${shellQuote(remoteCommand)}`,
  ].join("\n");
  const child = spawn("/bin/bash", ["-lc", localCommand], { cwd: root, stdio: ["ignore", "pipe", "pipe"] });
  let stdout = "";
  let stderr = "";
  child.stdout.on("data", (chunk) => { stdout += String(chunk); });
  child.stderr.on("data", (chunk) => { stderr += String(chunk); });
  return new Promise((resolve, reject) => {
    child.once("error", reject);
    child.once("exit", (code) => {
      if (code !== 0) {
        reject(new Error(`GPU monitor exited ${code}: ${stderr.trim()}`));
        return;
      }
      const samples = [];
      for (const line of stdout.split(/\r?\n/)) {
        const separator = line.indexOf("\t");
        if (separator < 0) continue;
        try {
          const timestamp = line.slice(0, separator);
          const payload = JSON.parse(line.slice(separator + 1));
          const card = payload.card0 || payload.Card0 || Object.values(payload)[0];
          const gpuUse = Number(card?.["GPU use (%)"]);
          const vramUsed = Number(card?.["VRAM Total Used Memory (B)"]);
          if (Number.isFinite(gpuUse) && Number.isFinite(vramUsed)) samples.push({ timestamp, gpuUse, vramUsed });
        } catch {
          // Ignore a partial line rather than fabricating a sample.
        }
      }
      resolve({ samples, stderr });
    });
  });
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function liveProofHtml(samples, backend) {
  const maxUse = samples.length ? Math.max(...samples.map((item) => item.gpuUse)) : 0;
  const minVram = samples.length ? Math.min(...samples.map((item) => item.vramUsed)) : 0;
  const maxVram = samples.length ? Math.max(...samples.map((item) => item.vramUsed)) : 0;
  const bars = samples.slice(-32).map((sample) => (
    `<span class="oas-bar" style="height:${Math.max(2, sample.gpuUse)}%" title="${sample.gpuUse}%"></span>`
  )).join("");
  return `
    <div class="oas-proof-shell">
      <header class="oas-proof-header">
        <div><p class="oas-proof-kicker">Same-request evidence</p><h1 class="oas-proof-title">Local Radeon inference</h1></div>
        <span class="oas-proof-chip">LIVE SAMPLE + API RESPONSE</span>
      </header>
      <div class="oas-proof-grid">
        <section class="oas-proof-panel">
          <h2>Application response path</h2>
          <pre>GET /api/health
status       ok
llm_backend  llama.cpp-rocm
offline      false

POST /api/chat
backend      ${escapeHtml(backend || "not returned")}
endpoint     127.0.0.1:8765
session      local application memory</pre>
          <p class="oas-proof-note">The browser captured the backend field from the real chat response. No remote model API is configured for this run.</p>
        </section>
        <section class="oas-proof-panel">
          <h2>ROCm SMI during the two recorded questions</h2>
          <div class="oas-proof-metric"><strong>${maxUse}%</strong><span>highest sampled GPU use</span></div>
          <div class="oas-bars" aria-label="GPU activity samples">${bars}</div>
          <p class="oas-proof-note">${samples.length} timestamped samples. VRAM used ranged from ${(minVram / 2 ** 30).toFixed(2)} to ${(maxVram / 2 ** 30).toFixed(2)} GiB. This is an activity trace, not an active peak-VRAM measurement.</p>
        </section>
      </div>
      <footer class="oas-proof-footer"><span>Device details and SSH endpoints are intentionally omitted.</span><span>Coreline Systems Limited</span></footer>
    </div>`;
}

function benchmarkProofHtml() {
  return `
    <div class="oas-proof-shell">
      <header class="oas-proof-header">
        <div><p class="oas-proof-kicker">Preserved raw artifacts</p><h1 class="oas-proof-title">Pinned ROCm load and benchmark</h1></div>
        <span class="oas-proof-chip">ROCm 7.2.1 / gfx1100</span>
      </header>
      <div class="oas-proof-grid">
        <section class="oas-proof-panel">
          <h2>Clean model-load trace</h2>
          <pre>model          Qwen3-8B Q4_K_M
model SHA-256 d98cdcbd03e17ce...c5745785
llama.cpp      1b99711a5f2582ec...c223cf5
device         ROCm0 AMD Radeon Graphics
VRAM           49,136 MiB

load_tensors: offloaded 37/37 layers to GPU
ROCm0 model buffer size = 4455.34 MiB
ROCm0 KV buffer size    = 1152.00 MiB
llama_server: model loaded</pre>
        </section>
        <section class="oas-proof-panel">
          <h2>Fixed five-repetition llama-bench snapshot</h2>
          <pre style="margin-bottom:13px">llama-bench -ngl 99 -p 512 -n 256 -r 5</pre>
          <table class="oas-benchmark-table">
            <thead><tr><th>Test</th><th>Backend</th><th>Layers</th><th>Measured throughput</th></tr></thead>
            <tbody>
              <tr><td>pp512</td><td>ROCm</td><td>99</td><td>3033.77 +/- 154.27 tok/s</td></tr>
              <tr><td>tg256</td><td>ROCm</td><td>99</td><td>93.47 +/- 0.08 tok/s</td></tr>
            </tbody>
          </table>
          <p class="oas-proof-note">Raw files are retained under docs/submission/generated. No CPU comparison, TTFT percentile, active peak VRAM, or quality delta is claimed.</p>
        </section>
      </div>
      <footer class="oas-proof-footer"><span>Numbers shown exactly match the preserved benchmark transcript.</span><span>Research and education only.</span></footer>
    </div>`;
}

function closingHtml() {
  return `
    <div class="oas-close-shell">
      <div class="oas-close-mark">OA</div>
      <h1>OpenAlpha Sentinel</h1>
      <p class="oas-tagline">Continuous discovery. Traceable evidence. Local Radeon inference.</p>
      <div class="oas-repo">github.com/coreline-systems/AMD-AI-DevMaster-Hackathon</div>
      <p class="oas-limit">Coreline Systems Limited. OpenAlpha Sentinel does not execute third-party repositories, connect to brokerage accounts, or promise returns. Research and education only.</p>
    </div>`;
}

async function showProof(html) {
  await evaluate(`window.__oasRootTo(null); window.__oasProof(${JSON.stringify(html)})`);
}

async function hideProof() {
  await evaluate("window.__oasProof('')");
}

async function capturePage(name) {
  const screenshot = await command("Page.captureScreenshot", {
    format: "png",
    captureBeyondViewport: false,
    fromSurface: true,
  });
  await writeFile(path.join(outputDir, `${path.basename(outputPath, ".mov")}-${name}.png`), Buffer.from(screenshot.data, "base64"));
}

async function stopProcess(child, signal = "SIGTERM", timeout = 10000) {
  if (!child || child.exitCode !== null || child.signalCode !== null) return;
  child.kill(signal);
  await Promise.race([
    new Promise((resolve) => child.once("exit", resolve)),
    delay(timeout),
  ]);
  if (child.exitCode === null && child.signalCode === null) child.kill("SIGKILL");
}

async function runDemo() {
  const healthResponse = await waitForHttp(new URL("api/health", appUrl).href, 20000);
  const health = await healthResponse.json();
  if (health.status !== "ok" || health.llm_backend !== "llama.cpp-rocm") {
    throw new Error(`Expected healthy llama.cpp-rocm application, got ${JSON.stringify(health)}`);
  }

  const flags = [
    `--remote-debugging-port=${debugPort}`,
    `--user-data-dir=${profile}`,
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-default-apps",
    "--disable-sync",
    "--disable-features=SigninPromo,ChromeWhatsNewUI",
  ];
  if (headless) flags.push("--headless=new", "--hide-scrollbars", "--window-size=1200,775");
  else flags.push("--kiosk");
  flags.push(appUrl);
  chrome = spawn(chromePath, flags, { stdio: "ignore" });

  const target = await waitForDebugger();
  socket = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    socket.addEventListener("open", resolve, { once: true });
    socket.addEventListener("error", reject, { once: true });
  });
  socket.addEventListener("message", (event) => {
    const message = JSON.parse(String(event.data));
    if (!message.id || !pending.has(message.id)) return;
    const item = pending.get(message.id);
    pending.delete(message.id);
    if (message.error) item.reject(new Error(message.error.message));
    else item.resolve(message.result || {});
  });

  await command("Page.enable");
  await command("Runtime.enable");
  await command("Page.bringToFront");
  if (!headless) {
    await execFileAsync("/usr/bin/osascript", [
      "-e",
      `tell application "System Events" to set frontmost of first process whose unix id is ${chrome.pid} to true`,
    ]);
  }
  await waitForPage(
    `document.readyState === 'complete' && document.getElementById('metric-cards')?.textContent !== '--' && document.querySelector('#overview-cards [data-card-id]') && document.getElementById('runtime-status')?.textContent.includes('Local API online')`,
    30000,
    "populated Overview and local API",
  );
  await evaluate(`(${installRecordingUi.toString()})()`);

  if (recordEnabled) {
    recorder = spawn(
      "/usr/sbin/screencapture",
      ["-v", `-V${recordingSeconds}`, "-m", "-x", outputPath],
      { stdio: "ignore" },
    );
    recorderCompletion = new Promise((resolve, reject) => {
      recorder.once("error", reject);
      recorder.once("exit", (code, signal) => {
        if (code === 0) resolve();
        else reject(new Error(`screencapture exited with code ${code} and signal ${signal}`));
      });
    });
    await delay(1600);
  }

  await setCaption(
    "01 / Product and boundary",
    "OpenAlpha Sentinel is a private research agent that turns open-source quantitative strategy material into traceable research cards. It runs locally and does not trade or provide investment advice.",
  );
  await hold(12000);

  await setCaption(
    "02 / Deterministic snapshot",
    "This populated workbench is reproducible without an external feed. Replaying the bundled snapshot normalizes, hashes, deduplicates, and indexes the same three evidence-backed records.",
  );
  if (!skipMutations) {
    await click("#seed-demo-button");
    await waitForPage("!document.getElementById('seed-demo-button').disabled", 30000, "snapshot replay");
  }
  await hold(9000);

  await navigate("cards");
  await setCaption(
    "03 / Evidence-linked cards",
    "The local index keeps strategy family, market, license, source revision, and update time together. Unsupported details are not silently promoted into facts.",
  );
  await hold(7000);

  await navigate("sources");
  await setCaption(
    "04 / Provenance registry",
    "Sources remain separate from model summaries. Each record preserves an origin, immutable revision, and the number of cards derived from that source.",
  );
  await hold(7000);

  await navigate("jobs");
  await setCaption(
    "05 / Bounded collection jobs",
    "Collection is an explicit pipeline with status, stage, progress, and attempts. External discovery is separate from local retrieval and local model inference.",
  );
  await hold(7000);

  await navigate("watch-rules");
  const existingRuleCount = await evaluate("document.querySelectorAll('#rules-surface tbody tr').length");
  await setCaption(
    "06 / Recurring research watch",
    "A watch rule stores a bounded query and schedule locally, so recurring research can run without repeating the search by hand. Continuous operation still requires the worker process to stay active.",
  );
  await click('[data-open-dialog="watch-dialog"]');
  await waitForPage("document.getElementById('watch-dialog').open", 10000, "watch dialog");
  await evaluate("window.__oasRootTo('#watch-dialog')");
  await typeText('#watch-form [name="name"]', "Licensed mean-reversion research", 900);
  await selectValue("#watch-kind", "github");
  await selectValue('#watch-form [name="interval_minutes"]', "360");
  await typeText("#watch-config-value", "mean reversion language:python license:mit", 1100);
  await hold(5000);
  if (skipMutations || existingRuleCount > 0) {
    await click('#watch-dialog [data-close-dialog]');
    await waitForPage("!document.getElementById('watch-dialog').open", 10000, "watch dialog close");
  } else {
    await click('#watch-form button[type="submit"]');
    await waitForPage("!document.getElementById('watch-dialog').open", 30000, "watch rule save");
  }
  await evaluate("window.__oasRootTo(null)");
  if (!skipMutations) {
    await waitForPage("document.getElementById('rules-surface').textContent.includes('Licensed mean-reversion research')", 30000, "saved watch rule");
  }
  await hold(6500);

  await navigate("cards");
  await setCaption(
    "07 / Card detail",
    "A strategy card is a research record, not a return claim. This pairs-trading note visibly carries its license, source, author-reported logic, and the missing transaction-cost disclosure as a risk flag.",
  );
  await clickByText("#cards-surface [data-card-id]", "Cointegrated ETF Pairs Research");
  await waitForPage("document.getElementById('card-dialog').open", 15000, "strategy detail dialog");
  await waitForPage(
    "document.querySelector('#card-dialog-content .detail-evidence-item') && document.getElementById('card-dialog-title').textContent.includes('Cointegrated ETF Pairs Research')",
    15000,
    "strategy evidence detail",
  );
  await evaluate("window.__oasRootTo('#card-dialog')");
  await hold(12000);
  await evaluate("document.getElementById('card-dialog-content').scrollTo({ top: document.getElementById('card-dialog-content').scrollHeight, behavior: 'smooth' })");
  await setCaption(
    "08 / Immutable evidence",
    "The detail view links the summary back to an immutable source revision and an evidence excerpt. Readers can inspect the origin instead of trusting a generated answer in isolation.",
  );
  await hold(10000);
  await click('#card-dialog form[method="dialog"] button');
  await waitForPage("!document.getElementById('card-dialog').open", 10000, "card dialog close");
  await evaluate("window.__oasRootTo(null)");

  await navigate("chat");
  await setCaption(
    "09 / Cited question",
    "Now the real application retrieves local evidence and sends the grounded prompt to the local Qwen3 model through llama.cpp on ROCm. The answer must cite the retrieved source.",
  );
  const firstQuestion = "Explain the entry and exit rules of the Daily Equity Mean Reversion strategy, including its remaining research risks. Answer in concise plain text without Markdown formatting.";
  await typeText("#chat-input", firstQuestion, 2200);
  const firstMonitor = startGpuMonitor();
  await hold(1800);
  await click('#chat-form button[type="submit"]');
  await waitForPage("document.querySelector('#chat-messages .typing-indicator')", 10000, "first chat request start");
  await waitForPage("!document.querySelector('#chat-messages .typing-indicator') && document.querySelector('#chat-sources .evidence-item') && window.__oasChatResponses.length >= 1", 100000, "first cited Radeon answer");
  await setCaption(
    "10 / Cited local answer",
    "The generated answer states the entry and exit conditions, then separates remaining risks from established evidence. The citation rail points to the exact indexed source.",
  );
  const firstGpu = await firstMonitor;
  await hold(10000);

  await setCaption(
    "11 / Follow-up context",
    "This follow-up depends on the previous turn. Conversation context narrows retrieval, while the agent still calls out assumptions that need independent validation instead of inventing certainty.",
  );
  const secondQuestion = "Which of those assumptions still need independent validation? Answer in concise plain text without Markdown formatting.";
  await typeText("#chat-input", secondQuestion, 1300);
  const secondMonitor = startGpuMonitor();
  await hold(1800);
  await click('#chat-form button[type="submit"]');
  await waitForPage("document.querySelector('#chat-messages .typing-indicator')", 10000, "follow-up request start");
  await waitForPage("!document.querySelector('#chat-messages .typing-indicator') && window.__oasChatResponses.length >= 2", 100000, "follow-up Radeon answer");
  const secondGpu = await secondMonitor;
  await hold(10000);
  await capturePage("chat");

  const chatResponses = await evaluate("window.__oasChatResponses");
  const backends = chatResponses.map((item) => item.backend).filter(Boolean);
  if (!backends.length || backends.some((backend) => backend !== "llama.cpp-rocm")) {
    throw new Error(`Recorded chat did not consistently use llama.cpp-rocm: ${JSON.stringify(backends)}`);
  }
  const gpuSamples = [...firstGpu.samples, ...secondGpu.samples];
  if (!skipGpuMonitor && !gpuSamples.length) throw new Error("No valid ROCm SMI samples were captured");
  if (!skipGpuMonitor && Math.max(...gpuSamples.map((item) => item.gpuUse)) <= 0) {
    throw new Error("ROCm SMI samples did not observe GPU activity during either request");
  }

  await showProof(liveProofHtml(gpuSamples, backends[0]));
  await setCaption(
    "12 / Radeon request",
    "The chat response reports backend llama.cpp-rocm, and ROCm SMI sampled GPU use during these two requests. The displayed VRAM range is only a point-in-time trace, not a peak-memory claim.",
  );
  await hold(18000);
  await capturePage("gpu-proof");

  await showProof(benchmarkProofHtml());
  await setCaption(
    "13 / ROCm benchmark",
    "The preserved clean-load trace reports all 37 of 37 layers on ROCm0. Under the fixed five-repetition snapshot, prompt processing measured 3033.77 plus or minus 154.27 tokens per second, and generation measured 93.47 plus or minus 0.08.",
  );
  await hold(18000);

  await hideProof();
  await navigate("local-controls");
  await setCaption(
    "14 / Local controls and audit",
    "Network collection has an explicit offline switch and allowlist, while preferences and audit events stay in local storage. Indexed retrieval and model generation do not require a hosted AI service.",
  );
  await hold(10000);

  await showProof(closingHtml());
  await setCaption(
    "15 / Scope and close",
    "OpenAlpha Sentinel provides an evidence-first view of open-source strategy knowledge on an AMD Radeon GPU. It does not execute repositories, connect to brokers, or promise returns.",
  );
  await hold(16000);
  await capturePage("closing");

  if (recorderCompletion) {
    console.log(`[${elapsed()}] Waiting for the fixed-duration recorder to finalize`);
    await recorderCompletion;
  }

  const endedAt = new Date();
  const manifest = {
    schema_version: 1,
    started_at: startedAt.toISOString(),
    ended_at: endedAt.toISOString(),
    duration_seconds: recordEnabled
      ? recordingSeconds
      : Number(((endedAt - startedAt) / 1000).toFixed(3)),
    application: {
      url: appUrl,
      status: health.status,
      llm_backend: health.llm_backend,
    },
    chat_backends: backends,
    gpu_activity: {
      sample_count: gpuSamples.length,
      max_sampled_gpu_use_percent: gpuSamples.length ? Math.max(...gpuSamples.map((item) => item.gpuUse)) : null,
      min_sampled_vram_bytes: gpuSamples.length ? Math.min(...gpuSamples.map((item) => item.vramUsed)) : null,
      max_sampled_vram_bytes: gpuSamples.length ? Math.max(...gpuSamples.map((item) => item.vramUsed)) : null,
      limitation: "Point-in-time samples during two requests; not an active peak-VRAM measurement.",
    },
    benchmark: {
      prompt_processing_tokens_per_second: "3033.77 +/- 154.27",
      generation_tokens_per_second: "93.47 +/- 0.08",
      repetitions: 5,
      gpu_layers: "37/37 in the preserved clean-load trace",
    },
    raw_video: recordEnabled ? outputPath : null,
  };
  await writeFile(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`);
  return manifest;
}

let manifest;
try {
  manifest = await runDemo();
} catch (error) {
  if (socket?.readyState === WebSocket.OPEN) {
    try {
      const diagnostic = await evaluate(`({
        hash: location.hash,
        activeView: document.querySelector('[data-view-panel]:not([hidden])')?.dataset.viewPanel,
        openDialogs: [...document.querySelectorAll('dialog[open]')].map((item) => item.id),
        cardDialogTitle: document.getElementById('card-dialog-title')?.textContent,
        cardDialogText: document.getElementById('card-dialog-content')?.textContent.slice(0, 300),
        toasts: [...document.querySelectorAll('.toast')].map((item) => item.textContent),
      })`);
      console.error(`Browser diagnostic: ${JSON.stringify(diagnostic)}`);
    } catch {
      // Preserve the original failure if the page is already unavailable.
    }
  }
  throw error;
} finally {
  if (recorder) await stopProcess(recorder, "SIGINT", 15000);
  if (socket?.readyState === WebSocket.OPEN) socket.close();
  await stopProcess(chrome, "SIGTERM", 10000);
}

console.log(JSON.stringify({
  video: manifest.raw_video,
  manifest: manifestPath,
  duration_seconds: manifest.duration_seconds,
  chat_backends: manifest.chat_backends,
  max_sampled_gpu_use_percent: manifest.gpu_activity.max_sampled_gpu_use_percent,
}, null, 2));
