#!/usr/bin/env node

import { chromium } from "playwright";
import { createServer } from "node:http";
import {
  existsSync,
  mkdirSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { readFile } from "node:fs/promises";
import {
  basename,
  dirname,
  extname,
  parse as parsePath,
  resolve,
  sep,
} from "node:path";

const SAFE_ID = /^[A-Za-z0-9_-]+$/;
const ROUTES = new Set(["programmatic", "realizable", "hybrid"]);
const MOMENT_KINDS = new Set(["stable_state", "pre_event", "post_event"]);
const EVENT_TYPES = new Set([
  "object_appearance",
  "object_disappearance",
  "split",
  "merge",
  "connection",
  "collapse",
  "topology_change",
  "camera_change",
]);

function parseArgs(argv) {
  const result = { app: "app/index.html", output: "bridge" };
  for (let i = 2; i < argv.length; i += 1) {
    const arg = argv[i];
    if (!arg.startsWith("--")) throw new Error(`Unknown argument: ${arg}`);
    const value = argv[++i];
    if (!value) throw new Error(`Missing value for ${arg}`);
    if (arg === "--app") result.app = value;
    else if (arg === "--output") result.output = value;
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
  const normalizedRoot = resolve(rootDir);
  const server = createServer(async (req, res) => {
    try {
      const rawPath = decodeURIComponent((req.url ?? "/").split("?")[0]);
      const relativePath = rawPath === "/" ? "index.html" : rawPath.replace(/^\/+/, "");
      const candidate = resolve(normalizedRoot, relativePath);
      const allowed =
        candidate === normalizedRoot || candidate.startsWith(`${normalizedRoot}${sep}`);
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

  await new Promise((done, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", done);
  });
  const address = server.address();
  if (!address || typeof address === "string") {
    throw new Error("Could not start local static server.");
  }
  return { server, url: `http://127.0.0.1:${address.port}/` };
}

function closeServer(server) {
  return new Promise((done) => server.close(done));
}

function expectObject(value, label) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${label} must be an object.`);
  }
  return value;
}

function expectString(value, label, { nullable = false } = {}) {
  if (nullable && value === null) return null;
  if (typeof value !== "string") throw new Error(`${label} must be a string.`);
  return value;
}

function expectStringArray(value, label) {
  if (!Array.isArray(value)) throw new Error(`${label} must be an array.`);
  return value.map((item, index) =>
    expectString(item, `${label}[${index}]`),
  );
}

function normalizeMeta(source) {
  const meta = expectObject(source, "LIVE_SCIENCE_META");
  const result = {
    duration: meta.duration,
    fps: meta.fps,
    width: meta.width,
    height: meta.height,
  };
  if (!Number.isFinite(result.duration) || result.duration <= 0) {
    throw new Error("LIVE_SCIENCE_META.duration must be a positive number.");
  }
  if (!Number.isFinite(result.fps) || result.fps <= 0 || result.fps > 60) {
    throw new Error("LIVE_SCIENCE_META.fps must be in (0, 60].");
  }
  if (!Number.isInteger(result.width) || !Number.isInteger(result.height)) {
    throw new Error("LIVE_SCIENCE_META width and height must be integers.");
  }
  if (result.width < 1 || result.height < 1) {
    throw new Error("LIVE_SCIENCE_META width and height must be positive.");
  }
  return result;
}

function normalizeBridge(source, meta) {
  const bridge = expectObject(source, "LIVE_SCIENCE_BRIDGE");
  if (bridge.version !== 1) throw new Error("LIVE_SCIENCE_BRIDGE.version must be 1.");
  if (!ROUTES.has(bridge.route)) {
    throw new Error(`LIVE_SCIENCE_BRIDGE.route is invalid: ${String(bridge.route)}`);
  }

  const targetStyle = expectString(bridge.targetStyle, "targetStyle", { nullable: true });
  const reason = expectString(bridge.reason, "reason");
  const worldContinuity = expectStringArray(bridge.worldContinuity, "worldContinuity");
  if (!Array.isArray(bridge.keyMoments)) throw new Error("keyMoments must be an array.");
  if (!Array.isArray(bridge.events)) throw new Error("events must be an array.");

  const momentIds = new Set();
  const keyMoments = bridge.keyMoments.map((raw, index) => {
    const moment = expectObject(raw, `keyMoments[${index}]`);
    const prefix = `key moment ${String(moment.id ?? index)}`;
    const id = expectString(moment.id, `${prefix}.id`);
    if (!SAFE_ID.test(id)) {
      throw new Error(`${prefix}.id must match ${SAFE_ID}.`);
    }
    if (momentIds.has(id)) throw new Error(`Duplicate key moment ID: ${id}`);
    momentIds.add(id);

    const time = moment.time;
    if (!Number.isFinite(time) || time < 0 || time > meta.duration) {
      throw new Error(`${prefix}.time must be within [0, ${meta.duration}].`);
    }
    if (!MOMENT_KINDS.has(moment.kind)) {
      throw new Error(`${prefix}.kind is invalid: ${String(moment.kind)}`);
    }
    if (typeof moment.realizable !== "boolean") {
      throw new Error(`${prefix}.realizable must be a boolean.`);
    }
    const eventId = moment.eventId === null
      ? null
      : expectString(moment.eventId, `${prefix}.eventId`);
    return {
      id,
      time,
      kind: moment.kind,
      description: expectString(moment.description, `${prefix}.description`),
      eventId,
      visibleObjects: expectStringArray(moment.visibleObjects, `${prefix}.visibleObjects`),
      preserve: expectStringArray(moment.preserve, `${prefix}.preserve`),
      realizable: moment.realizable,
    };
  });

  const eventIds = new Set();
  const events = bridge.events.map((raw, index) => {
    const event = expectObject(raw, `events[${index}]`);
    const prefix = `event ${String(event.id ?? index)}`;
    const id = expectString(event.id, `${prefix}.id`);
    if (!id) throw new Error(`${prefix}.id cannot be empty.`);
    if (eventIds.has(id)) throw new Error(`Duplicate event ID: ${id}`);
    eventIds.add(id);
    if (!EVENT_TYPES.has(event.type)) {
      throw new Error(`${prefix}.type is invalid: ${String(event.type)}`);
    }
    return {
      id,
      type: event.type,
      objects: expectStringArray(event.objects, `${prefix}.objects`),
      preMomentId: expectString(event.preMomentId, `${prefix}.preMomentId`),
      postMomentId: expectString(event.postMomentId, `${prefix}.postMomentId`),
    };
  });

  const momentById = new Map(keyMoments.map((moment) => [moment.id, moment]));
  for (const event of events) {
    const pre = momentById.get(event.preMomentId);
    const post = momentById.get(event.postMomentId);
    if (!pre) throw new Error(`Event ${event.id} references missing preMomentId ${event.preMomentId}.`);
    if (!post) throw new Error(`Event ${event.id} references missing postMomentId ${event.postMomentId}.`);
    if (pre.kind !== "pre_event") {
      throw new Error(`Event ${event.id} pre moment ${pre.id} must have kind pre_event.`);
    }
    if (post.kind !== "post_event") {
      throw new Error(`Event ${event.id} post moment ${post.id} must have kind post_event.`);
    }
    if (post.time <= pre.time) {
      throw new Error(`Event ${event.id} post time must be later than pre time.`);
    }
    if (pre.eventId !== event.id || post.eventId !== event.id) {
      throw new Error(`Event ${event.id} pre/post moments must use eventId ${event.id}.`);
    }
  }
  for (const moment of keyMoments) {
    if (moment.eventId !== null && !eventIds.has(moment.eventId)) {
      throw new Error(`Key moment ${moment.id} references missing eventId ${moment.eventId}.`);
    }
  }

  let posterMomentId = null;
  if (bridge.posterMomentId !== null && bridge.posterMomentId !== undefined) {
    posterMomentId = expectString(bridge.posterMomentId, "posterMomentId");
    if (!SAFE_ID.test(posterMomentId)) {
      throw new Error(`posterMomentId must match ${SAFE_ID}.`);
    }
    if (!momentIds.has(posterMomentId)) {
      throw new Error(`posterMomentId references missing key moment ${posterMomentId}.`);
    }
  }

  if (bridge.route === "realizable" && keyMoments.length === 0) {
    throw new Error("A realizable route must define at least one key moment.");
  }
  if (bridge.route === "hybrid" && !keyMoments.some((moment) => moment.realizable)) {
    throw new Error("A hybrid route must have at least one realizable key moment.");
  }

  return {
    version: 1,
    route: bridge.route,
    targetStyle,
    reason,
    worldContinuity,
    posterMomentId,
    keyMoments,
    events,
  };
}

function assertSafeOutput(outputPath, appPath) {
  const filesystemRoot = parsePath(outputPath).root;
  const cwd = resolve(".");
  const appDir = dirname(appPath);
  if (outputPath === filesystemRoot || outputPath === cwd || outputPath === appDir) {
    throw new Error(`Refusing unsafe Bridge output directory: ${outputPath}`);
  }
  if (appPath === outputPath || appPath.startsWith(`${outputPath}${sep}`)) {
    throw new Error(`Bridge output directory must not contain the app: ${outputPath}`);
  }
}

async function renderMoment(page, outputDir, moment, meta) {
  const assets = {};
  for (const mode of ["presentation", "clean", "overlay"]) {
    await page.evaluate(
      async ({ time, renderMode }) => {
        await window.renderFrame(time, { mode: renderMode });
        await new Promise((done) =>
          requestAnimationFrame(() => requestAnimationFrame(done)),
        );
      },
      { time: moment.time, renderMode: mode },
    );
    const relativePath = `${mode}/${moment.id}.png`;
    const absolutePath = resolve(outputDir, relativePath);
    mkdirSync(dirname(absolutePath), { recursive: true });
    await page.screenshot({
      path: absolutePath,
      type: "png",
      animations: "disabled",
      omitBackground: mode === "overlay",
      captureBeyondViewport: false,
    });
    assets[mode] = relativePath;
  }
  console.log(`Exported ${moment.id} at ${moment.time}s (${meta.width}×${meta.height})`);
  return assets;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

async function createContactSheet(browser, outputDir, moments) {
  const columns = Math.min(3, Math.max(1, moments.length));
  const cards = moments.map((moment) => {
    const imageBytes = readFileSync(resolve(outputDir, moment.assets.presentation));
    const source = `data:image/png;base64,${imageBytes.toString("base64")}`;
    return `<figure><img src="${source}"><figcaption>${escapeHtml(moment.id)} · ${moment.time.toFixed(3)}s</figcaption></figure>`;
  }).join("");
  const html = `<!doctype html><meta charset="utf-8"><style>
    * { box-sizing: border-box; }
    html, body { margin: 0; background: #111827; color: #f8fafc; font: 18px/1.35 system-ui, sans-serif; }
    main { display: grid; grid-template-columns: repeat(${columns}, 420px); gap: 18px; padding: 20px; width: max-content; }
    figure { margin: 0; padding: 10px; border-radius: 10px; background: #1f2937; box-shadow: 0 3px 12px #0008; }
    img { display: block; width: 400px; height: auto; background: #000; }
    figcaption { padding: 9px 2px 1px; overflow-wrap: anywhere; }
  </style><main>${cards}</main>`;

  const page = await browser.newPage({ deviceScaleFactor: 1 });
  try {
    await page.setContent(html, { waitUntil: "load" });
    await page.waitForFunction(() =>
      [...document.images].every((image) => image.complete && image.naturalWidth > 0),
    );
    await page.screenshot({
      path: resolve(outputDir, "contact_sheet.png"),
      type: "png",
      fullPage: true,
      animations: "disabled",
    });
  } finally {
    await page.close();
  }
}

async function main() {
  const args = parseArgs(process.argv);
  const appPath = resolve(args.app);
  const outputDir = resolve(args.output);
  if (!existsSync(appPath)) throw new Error(`App entry not found: ${appPath}`);
  assertSafeOutput(outputDir, appPath);

  let serverInfo;
  let browser;
  let outputPrepared = false;
  let succeeded = false;
  try {
    serverInfo = await startStaticServer(dirname(appPath));
    browser = await chromium.launch({ headless: true });
    const page = await browser.newPage({
      viewport: { width: 1920, height: 1080 },
      deviceScaleFactor: 1,
    });
    const pageErrors = [];
    page.on("pageerror", (error) => pageErrors.push(`pageerror: ${String(error)}`));
    page.on("console", (message) => {
      if (message.type() === "error") pageErrors.push(`console.error: ${message.text()}`);
    });

    await page.goto(`${serverInfo.url}${encodeURIComponent(basename(appPath))}`, {
      waitUntil: "networkidle",
    });
    await page.waitForFunction(
      () =>
        window.__LIVE_SCIENCE_READY__ === true &&
        typeof window.renderFrame === "function" &&
        window.LIVE_SCIENCE_META &&
        window.LIVE_SCIENCE_BRIDGE,
      null,
      { timeout: 30_000 },
    );
    const snapshot = await page.evaluate(() => {
      try {
        return JSON.parse(JSON.stringify({
          meta: window.LIVE_SCIENCE_META,
          bridge: window.LIVE_SCIENCE_BRIDGE,
        }));
      } catch (error) {
        throw new Error(`Bridge metadata is not JSON-serializable: ${String(error)}`);
      }
    });
    const meta = normalizeMeta(snapshot.meta);
    const bridge = normalizeBridge(snapshot.bridge, meta);
    if (pageErrors.length > 0) {
      throw new Error(`Browser errors were detected:\n${pageErrors.slice(0, 20).join("\n")}`);
    }

    await page.setViewportSize({ width: meta.width, height: meta.height });
    rmSync(outputDir, { recursive: true, force: true });
    mkdirSync(outputDir, { recursive: true });
    outputPrepared = true;

    const exportable = bridge.route === "programmatic"
      ? []
      : bridge.keyMoments.filter(
        (moment) => bridge.route === "realizable" || moment.realizable,
      );
    const manifestMoments = [];
    for (const moment of bridge.keyMoments) {
      const shouldExport = exportable.includes(moment);
      const assets = shouldExport
        ? await renderMoment(page, outputDir, moment, meta)
        : null;
      manifestMoments.push({ ...moment, assets });
    }
    if (pageErrors.length > 0) {
      throw new Error(`Browser errors were detected:\n${pageErrors.slice(0, 20).join("\n")}`);
    }

    if (exportable.length > 0) {
      const exportedMoments = manifestMoments.filter((moment) => moment.assets !== null);
      await createContactSheet(browser, outputDir, exportedMoments);
    }

    const manifest = {
      version: 1,
      meta,
      route: bridge.route,
      targetStyle: bridge.targetStyle,
      reason: bridge.reason,
      worldContinuity: bridge.worldContinuity,
      posterMomentId: bridge.posterMomentId,
      keyMoments: manifestMoments,
      events: bridge.events,
      contactSheet: exportable.length > 0 ? "contact_sheet.png" : null,
    };
    writeFileSync(
      resolve(outputDir, "manifest.json"),
      `${JSON.stringify(manifest, null, 2)}\n`,
      "utf8",
    );
    succeeded = true;
    console.log(`Bridge manifest: ${resolve(outputDir, "manifest.json")}`);
    console.log(`Route: ${bridge.route}; key moments: ${bridge.keyMoments.length}; exported: ${exportable.length}`);
  } finally {
    if (browser) await browser.close();
    if (serverInfo) await closeServer(serverInfo.server);
    if (outputPrepared && !succeeded) rmSync(outputDir, { recursive: true, force: true });
  }
}

main().catch((error) => {
  console.error(`Bridge export failed: ${error instanceof Error ? error.message : String(error)}`);
  process.exitCode = 1;
});
