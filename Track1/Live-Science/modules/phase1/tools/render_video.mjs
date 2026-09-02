#!/usr/bin/env node

import { chromium } from "playwright";
import { createServer } from "node:http";
import { spawnSync } from "node:child_process";
import {
  copyFileSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  rmSync,
} from "node:fs";
import { dirname, extname, join, resolve } from "node:path";
import { tmpdir } from "node:os";

function parseArgs(argv) {
  const result = {
    app: "app/index.html",
    output: "video.mp4",
    poster: "poster.png",
    keepFrames: false,
  };

  for (let i = 2; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === "--keep-frames") {
      result.keepFrames = true;
      continue;
    }
    if (!arg.startsWith("--")) throw new Error(`Unknown argument: ${arg}`);
    const value = argv[++i];
    if (!value) throw new Error(`Missing value for ${arg}`);
    if (arg === "--app") result.app = value;
    else if (arg === "--output") result.output = value;
    else if (arg === "--poster") result.poster = value;
    else throw new Error(`Unknown option: ${arg}`);
  }
  return result;
}

function contentType(pathname) {
  const ext = extname(pathname).toLowerCase();
  return (
    {
      ".html": "text/html; charset=utf-8",
      ".js": "text/javascript; charset=utf-8",
      ".mjs": "text/javascript; charset=utf-8",
      ".css": "text/css; charset=utf-8",
      ".json": "application/json; charset=utf-8",
      ".svg": "image/svg+xml",
      ".png": "image/png",
      ".jpg": "image/jpeg",
      ".jpeg": "image/jpeg",
      ".webp": "image/webp",
      ".woff": "font/woff",
      ".woff2": "font/woff2",
      ".ttf": "font/ttf",
      ".otf": "font/otf",
    }[ext] ?? "application/octet-stream"
  );
}

async function startStaticServer(rootDir) {
  const { readFile } = await import("node:fs/promises");
  const normalizedRoot = resolve(rootDir);

  const server = createServer(async (req, res) => {
    try {
      const rawPath = decodeURIComponent((req.url ?? "/").split("?")[0]);
      const relativePath = rawPath === "/" ? "index.html" : rawPath.replace(/^\/+/, "");
      const candidate = resolve(rootDir, relativePath);
      const allowed = candidate === normalizedRoot || candidate.startsWith(`${normalizedRoot}/`);
      if (!allowed) {
        res.writeHead(403);
        res.end("Forbidden");
        return;
      }
      const data = await readFile(candidate);
      res.writeHead(200, {
        "Content-Type": contentType(candidate),
        "Cache-Control": "no-store",
      });
      res.end(data);
    } catch {
      res.writeHead(404);
      res.end("Not found");
    }
  });

  await new Promise((done) => server.listen(0, "127.0.0.1", done));
  const address = server.address();
  if (!address || typeof address === "string") {
    throw new Error("Could not start local server");
  }
  return { server, url: `http://127.0.0.1:${address.port}/` };
}

function requireCommand(name) {
  const result = spawnSync(name, ["-version"], { encoding: "utf8" });
  if (result.error || result.status !== 0) {
    throw new Error(`${name} is required but was not found or could not run.`);
  }
}

function run(command, args) {
  const result = spawnSync(command, args, { stdio: "inherit" });
  if (result.status !== 0) {
    throw new Error(`${command} exited with status ${result.status}`);
  }
}

const args = parseArgs(process.argv);
const appPath = resolve(args.app);
const appDir = dirname(appPath);
const appEntry = appPath.split("/").pop();
if (!existsSync(appPath)) throw new Error(`App entry not found: ${appPath}`);
requireCommand("ffmpeg");

const { server, url } = await startStaticServer(appDir);
const frameRoot = mkdtempSync(join(tmpdir(), "live-science-frames-"));
const browser = await chromium.launch({ headless: true });

try {
  const page = await browser.newPage({
    viewport: { width: 1920, height: 1080 },
    deviceScaleFactor: 1,
  });

  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(String(error)));
  page.on("console", (message) => {
    if (message.type() === "error") {
      pageErrors.push(`console.error: ${message.text()}`);
    }
  });

  await page.goto(`${url}${encodeURIComponent(appEntry)}`, {
    waitUntil: "networkidle",
  });
  await page.waitForFunction(
    () =>
      window.__LIVE_SCIENCE_READY__ === true &&
      typeof window.renderFrame === "function" &&
      window.LIVE_SCIENCE_META,
    null,
    { timeout: 30_000 },
  );

  const meta = await page.evaluate(() => {
    const source = window.LIVE_SCIENCE_META ?? {};
    return {
      duration: Number(source.duration),
      fps: Number(source.fps ?? 30),
      width: Number(source.width ?? 1920),
      height: Number(source.height ?? 1080),
    };
  });

  if (!Number.isFinite(meta.duration) || meta.duration <= 0) {
    throw new Error("LIVE_SCIENCE_META.duration must be a positive number.");
  }
  if (!Number.isFinite(meta.fps) || meta.fps <= 0 || meta.fps > 60) {
    throw new Error("LIVE_SCIENCE_META.fps must be in (0, 60].");
  }
  if (
    !Number.isFinite(meta.width) ||
    !Number.isFinite(meta.height) ||
    meta.width < 1 ||
    meta.height < 1
  ) {
    throw new Error("Invalid output dimensions.");
  }

  await page.setViewportSize({ width: meta.width, height: meta.height });
  const frameCount = Math.max(1, Math.ceil(meta.duration * meta.fps));
  const digits = Math.max(6, String(frameCount).length);
  const fallbackPosterFrame = Math.min(
    frameCount - 1,
    Math.max(0, Math.floor(frameCount * 0.82)),
  );
  let posterMoment = null;
  try {
    const bridge = await page.evaluate(() => {
      const source = window.LIVE_SCIENCE_BRIDGE;
      if (!source || typeof source !== "object") return null;
      return {
        posterMomentId: source.posterMomentId,
        keyMoments: Array.isArray(source.keyMoments)
          ? source.keyMoments.map((moment) => ({
              id: moment?.id,
              time: moment?.time,
            }))
          : null,
      };
    });
    if (bridge) {
      const posterId = bridge.posterMomentId;
      if (typeof posterId !== "string" || !/^[A-Za-z0-9_-]+$/.test(posterId)) {
        console.warn(
          "Warning: LIVE_SCIENCE_BRIDGE.posterMomentId is missing or invalid; using the default poster time.",
        );
      } else if (!Array.isArray(bridge.keyMoments)) {
        console.warn(
          "Warning: LIVE_SCIENCE_BRIDGE.keyMoments is invalid; using the default poster time.",
        );
      } else {
        const matches = bridge.keyMoments.filter((moment) => moment.id === posterId);
        if (matches.length !== 1) {
          console.warn(
            `Warning: posterMomentId ${posterId} does not uniquely reference a key moment; using the default poster time.`,
          );
        } else {
          const time = Number(matches[0].time);
          if (!Number.isFinite(time) || time < 0 || time > meta.duration) {
            console.warn(
              `Warning: posterMomentId ${posterId} has an out-of-range time; using the default poster time.`,
            );
          } else {
            posterMoment = { id: posterId, time };
          }
        }
      }
    }
  } catch (error) {
    console.warn(
      `Warning: could not inspect LIVE_SCIENCE_BRIDGE for poster selection (${String(error)}); using the default poster time.`,
    );
  }

  console.log(
    `Rendering ${frameCount} frames at ${meta.width}×${meta.height}, ${meta.fps} fps, ${meta.duration}s`,
  );

  for (let frame = 0; frame < frameCount; frame += 1) {
    const t = Math.min(frame / meta.fps, meta.duration);
    await page.evaluate(async (time) => {
      await window.renderFrame(time);
      await new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done)));
    }, t);

    const framePath = join(
      frameRoot,
      `frame_${String(frame).padStart(digits, "0")}.png`,
    );
    await page.screenshot({
      path: framePath,
      type: "png",
      animations: "disabled",
    });

    if (frame % Math.max(1, Math.floor(meta.fps * 5)) === 0) {
      console.log(`  frame ${frame + 1}/${frameCount}`);
    }
  }

  if (pageErrors.length > 0) {
    throw new Error(`Browser errors were detected:\n${pageErrors.slice(0, 20).join("\n")}`);
  }

  mkdirSync(dirname(resolve(args.output)), { recursive: true });
  run("ffmpeg", [
    "-y",
    "-framerate",
    String(meta.fps),
    "-i",
    join(frameRoot, `frame_%0${digits}d.png`),
    "-c:v",
    "libx264",
    "-preset",
    "medium",
    "-crf",
    "18",
    "-pix_fmt",
    "yuv420p",
    "-movflags",
    "+faststart",
    resolve(args.output),
  ]);

  if (posterMoment) {
    await page.evaluate(async (time) => {
      await window.renderFrame(time);
      await new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done)));
    }, posterMoment.time);
    await page.screenshot({
      path: resolve(args.poster),
      type: "png",
      animations: "disabled",
      captureBeyondViewport: false,
    });
    console.log(`Poster moment: ${posterMoment.id} at ${posterMoment.time}s`);
  } else {
    copyFileSync(
      join(
        frameRoot,
        `frame_${String(fallbackPosterFrame).padStart(digits, "0")}.png`,
      ),
      resolve(args.poster),
    );
  }

  if (pageErrors.length > 0) {
    throw new Error(`Browser errors were detected:\n${pageErrors.slice(0, 20).join("\n")}`);
  }

  if (args.keepFrames) {
    const persistentFrames = resolve("frames");
    rmSync(persistentFrames, { recursive: true, force: true });
    mkdirSync(persistentFrames, { recursive: true });
    run("cp", ["-R", `${frameRoot}/.`, persistentFrames]);
    console.log(`Frames kept at ${persistentFrames}`);
  }

  console.log(`Video: ${resolve(args.output)}`);
  console.log(`Poster: ${resolve(args.poster)}`);
} finally {
  await browser.close();
  await new Promise((done) => server.close(done));
  if (!args.keepFrames) rmSync(frameRoot, { recursive: true, force: true });
}
