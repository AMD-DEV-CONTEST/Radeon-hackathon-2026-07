#!/usr/bin/env node

import { spawn } from "node:child_process";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";

const root = path.resolve(import.meta.dirname, "..");
const outputDir = path.join(root, "docs", "submission", "generated");
const appUrl = process.env.OPENALPHA_UI_URL || "http://127.0.0.1:8765/";
const chromePath = process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const port = Number(process.env.CHROME_DEBUG_PORT || "9333");
const profile = `/tmp/openalpha-cdp-${process.pid}`;

await mkdir(outputDir, { recursive: true });

const chrome = spawn(chromePath, [
  "--headless=new",
  "--disable-gpu",
  "--hide-scrollbars",
  `--remote-debugging-port=${port}`,
  `--user-data-dir=${profile}`,
  "about:blank",
], { stdio: "ignore" });

function delay(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

async function waitForDebugger() {
  for (let attempt = 0; attempt < 50; attempt += 1) {
    try {
      const response = await fetch(`http://127.0.0.1:${port}/json/version`);
      if (response.ok) return;
    } catch {
      // Chrome has not opened the debugging socket yet.
    }
    await delay(100);
  }
  throw new Error("Chrome DevTools endpoint did not start");
}

await waitForDebugger();
const targetResponse = await fetch(
  `http://127.0.0.1:${port}/json/new?${encodeURIComponent(appUrl)}`,
  { method: "PUT" },
);
if (!targetResponse.ok) throw new Error(`Could not create Chrome page: ${targetResponse.status}`);
const target = await targetResponse.json();

const socket = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((resolve, reject) => {
  socket.addEventListener("open", resolve, { once: true });
  socket.addEventListener("error", reject, { once: true });
});

let sequence = 0;
const pending = new Map();
socket.addEventListener("message", (event) => {
  const message = JSON.parse(String(event.data));
  if (!message.id || !pending.has(message.id)) return;
  const { resolve, reject } = pending.get(message.id);
  pending.delete(message.id);
  if (message.error) reject(new Error(message.error.message));
  else resolve(message.result || {});
});

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
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.text || "Page evaluation failed");
  return result.result?.value;
}

async function capture(name, { width, height, mobile, locale = "en", view = "overview" }) {
  await command("Emulation.setDeviceMetricsOverride", {
    width,
    height,
    deviceScaleFactor: 1,
    mobile,
    screenWidth: width,
    screenHeight: height,
  });
  await command("Page.navigate", { url: appUrl });
  await delay(1800);
  await evaluate(`localStorage.setItem("oas.locale", ${JSON.stringify(locale)}); location.reload()`);
  await delay(1800);
  if (view !== "overview") {
    await evaluate(`document.querySelector('[data-view=${JSON.stringify(view)}]')?.click()`);
    await delay(700);
  }

  const dimensions = await evaluate(`({
    innerWidth: window.innerWidth,
    innerHeight: window.innerHeight,
    scrollWidth: document.documentElement.scrollWidth,
    bodyScrollWidth: document.body.scrollWidth
  })`);
  if (dimensions.innerWidth !== width) {
    throw new Error(`${name}: expected ${width}px viewport, got ${dimensions.innerWidth}px`);
  }
  if (dimensions.scrollWidth > width + 1 || dimensions.bodyScrollWidth > width + 1) {
    throw new Error(`${name}: horizontal overflow ${JSON.stringify(dimensions)}`);
  }

  const screenshot = await command("Page.captureScreenshot", {
    format: "png",
    captureBeyondViewport: false,
    fromSurface: true,
  });
  const output = path.join(outputDir, name);
  await writeFile(output, Buffer.from(screenshot.data, "base64"));
  console.log(`${path.relative(root, output)} ${JSON.stringify(dimensions)}`);
}

try {
  await command("Page.enable");
  await command("Runtime.enable");
  await capture("ui-overview-desktop.png", {
    width: 1440,
    height: 1000,
    mobile: false,
  });
  await capture("ui-overview-mobile.png", {
    width: 390,
    height: 844,
    mobile: true,
  });
  await capture("ui-local-controls.zh-CN.png", {
    width: 1440,
    height: 1000,
    mobile: false,
    locale: "zh",
    view: "local-controls",
  });
} finally {
  socket.close();
  chrome.kill("SIGTERM");
}

