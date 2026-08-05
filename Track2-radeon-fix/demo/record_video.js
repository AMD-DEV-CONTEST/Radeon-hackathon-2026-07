#!/usr/bin/env node
/* Record a 1920x1080 MP4 demo from the real radeon-fix session transcript,
   including the generated-code panel and mid-run screenshots. */

const fs = require("fs");
const path = require("path");
const { execFileSync } = require("child_process");

const ROOT = __dirname;
const SESSION = process.env.SESSION_FILE || path.join(ROOT, "demo-assets", "demo-session.txt");
const TIMING = process.env.TIMING_FILE || path.join(ROOT, "demo-assets", "demo.timing");
const TRAJECTORY = process.env.TRAJECTORY_FILE || path.join(ROOT, "demo-assets", "trajectory.json");
const TEMPLATE = path.join(ROOT, "replay.template.html");
const OUT_HTML = path.join(ROOT, "replay.html");
const VIDEO_DIR = path.join(ROOT, "video");
const SHOT_DIR = path.join(ROOT, "screenshots");

function parseSegments(sessionPath, timingPath) {
  const raw = fs.readFileSync(sessionPath, "utf8");
  const timing = fs
    .readFileSync(timingPath, "utf8")
    .split("\n")
    .filter((line) => line.trim())
    .map((line) => {
      const [delay, chars] = line.trim().split(/\s+/).map(Number);
      return { delay, chars };
    });

  const headerEnd = raw.indexOf("\n");
  let body = headerEnd >= 0 ? raw.slice(headerEnd + 1) : raw;
  const doneIdx = body.indexOf("Script done on ");
  if (doneIdx >= 0) body = body.slice(0, doneIdx);

  const bodyBytes = Buffer.from(body, "utf8");
  const segments = [];
  let offset = 0;
  for (const item of timing) {
    if (item.chars <= 0) continue;
    const end = Math.min(offset + item.chars, bodyBytes.length);
    if (end <= offset) {
      offset += item.chars;
      continue;
    }
    const text = bodyBytes.slice(offset, end).toString("utf8");
    segments.push({ delay: item.delay, text });
    offset = end;
  }
  return segments;
}

function parseActions(trajectoryPath) {
  const trajectory = JSON.parse(fs.readFileSync(trajectoryPath, "utf8"));
  const actions = [];
  for (const message of trajectory.conversations || []) {
    if (message.from !== "gpt" && message.from !== "assistant") continue;
    try {
      const parsed = JSON.parse(String(message.value || "").trim());
      if (parsed && typeof parsed === "object" && parsed.action) actions.push(parsed);
    } catch {
      // not a JSON action envelope
    }
  }
  const finalPatch = (trajectory.metadata && trajectory.metadata.final_patch) || "";
  return { actions, finalPatch };
}

function ffmpegPath() {
  if (process.env.FFMPEG) return process.env.FFMPEG;
  const candidates = [
    "/Users/haomiaodemac/Library/Caches/ms-playwright/ffmpeg-1011/ffmpeg-mac",
  ];
  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) return candidate;
  }
  return "ffmpeg";
}

function chromiumPath() {
  if (process.env.CHROMIUM_PATH) return process.env.CHROMIUM_PATH;
  const candidates = [
    "/Users/haomiaodemac/Library/Caches/ms-playwright/chromium_headless_shell-1208/chrome-headless-shell-mac-arm64/chrome-headless-shell",
  ];
  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) return candidate;
  }
  return undefined;
}

async function main() {
  fs.mkdirSync(VIDEO_DIR, { recursive: true });
  fs.mkdirSync(SHOT_DIR, { recursive: true });

  const segments = parseSegments(SESSION, TIMING);
  const { actions, finalPatch } = parseActions(TRAJECTORY);
  const template = fs.readFileSync(TEMPLATE, "utf8");
  const html = template
    .replace("__SESSION_DATA__", JSON.stringify(segments))
    .replace("__ACTIONS_DATA__", JSON.stringify(actions))
    .replace("__PATCH_DATA__", JSON.stringify(finalPatch));
  fs.writeFileSync(OUT_HTML, html);

  const { chromium } = require("playwright");
  const executablePath = chromiumPath();
  const browser = await chromium.launch(executablePath ? { executablePath } : {});
  const context = await browser.newContext({
    viewport: { width: 1920, height: 1080 },
    recordVideo: { dir: VIDEO_DIR, size: { width: 1920, height: 1080 } },
  });
  const page = await context.newPage();
  await page.setContent(html, { waitUntil: "load" });

  const started = Date.now();
  let codeShotTaken = false;

  async function shot(name) {
    const elapsed = Math.round((Date.now() - started) / 1000);
    const file = path.join(SHOT_DIR, `${name}.png`);
    try {
      await page.screenshot({ path: file });
      const state = await page.evaluate(() => ({
        codeChars: document.getElementById("code").textContent.length,
        termChars: document.getElementById("output").textContent.length,
        caption: document.getElementById("caption-text").textContent,
        step: document.querySelector("#caption .step").textContent,
      }));
      console.log(
        `[shot] ${name} at ${elapsed}s | codeChars=${state.codeChars} termChars=${state.termChars} step=${state.step} | ${state.caption}`
      );
    } catch (error) {
      console.log(`[shot] ${name} skipped: ${error.message}`);
    }
  }

  await shot("frame-01-intro");
  const poll = setInterval(async () => {
    const hasCode = await page.evaluate(
      () => document.getElementById("code-meta").textContent !== "waiting…"
    );
    if (hasCode && !codeShotTaken) {
      codeShotTaken = true;
      await shot("frame-02-code-generation");
      clearInterval(poll);
    }
  }, 1000);

  const midway = setTimeout(() => shot("frame-03-midway"), 90000);
  const late = setTimeout(() => shot("frame-04-late"), 165000);
  await page.waitForSelector('body[data-done="true"]', { timeout: 360000 });
  await page.waitForTimeout(4500);
  clearInterval(poll);
  clearTimeout(midway);
  clearTimeout(late);
  await shot("frame-05-final");

  await context.close();
  await browser.close();

  const webmFiles = fs
    .readdirSync(VIDEO_DIR)
    .filter((file) => file.endsWith(".webm"));
  if (webmFiles.length === 0) throw new Error("no webm video produced");
  const webm = webmFiles
    .map((file) => path.join(VIDEO_DIR, file))
    .sort((a, b) => fs.statSync(b).mtimeMs - fs.statSync(a).mtimeMs)[0];
  const mp4 = path.join(ROOT, "radeon-fix-demo.mp4");

  const ffmpeg = ffmpegPath();
  try {
    execFileSync(
      ffmpeg,
      ["-y", "-i", webm, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart", mp4],
      { stdio: "inherit" }
    );
  } catch (error) {
    execFileSync(
      ffmpeg,
      ["-y", "-i", webm, "-c:v", "mpeg4", "-q:v", "4", "-movflags", "+faststart", mp4],
      { stdio: "inherit" }
    );
  }
  console.log("Wrote", mp4);
  console.log("Screenshots:", fs.readdirSync(SHOT_DIR).join(", "));
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
