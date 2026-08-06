/**
 * Run a WebGPU validation page in headless Chrome and hand back what it reported.
 *
 * The kernels are browser code, so the only honest way to test them is in a browser
 * with a real adapter. This module is the part that is identical for every model:
 * find Chrome, serve the repo, launch the page, wait for its POST, and refuse to
 * call a software adapter a GPU. What the numbers mean is left to the caller.
 *
 * Deliberately dependency-free: a Node static server plus a Chrome subprocess. The
 * page POSTs its result back to the same server rather than the runner scraping the
 * DOM, which avoids Chrome's virtual clock (`--virtual-time-budget` stalls on GPU
 * fences, and would make the latency numbers fictional anyway).
 */

import { createServer } from "node:http";
import { spawn } from "node:child_process";
import { readFile, mkdtemp, rm } from "node:fs/promises";
import { createReadStream } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join, normalize, extname } from "node:path";
import { tmpdir } from "node:os";

export const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");

const CHROME_CANDIDATES = [
  process.env.CHROME_PATH,
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  "/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary",
  "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
  "/usr/bin/google-chrome",
  "/usr/bin/chromium",
  `${process.env.HOME}/.local/chrome/opt/google/chrome/chrome`,
].filter(Boolean);

/**
 * Adapter strings that mean "this ran on the CPU". Chrome reports SwiftShader as
 * vendor "google" / architecture "swiftshader"; Mesa's software rasterizers show up
 * as llvmpipe or lavapipe.
 */
export const SOFTWARE_ADAPTER = /swiftshader|llvmpipe|lavapipe|software|microsoft basic/i;

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".bin": "application/octet-stream",
};

async function findChrome() {
  for (const p of CHROME_CANDIDATES) {
    try {
      await readFile(p);
      return p;
    } catch {
      /* try next */
    }
  }
  throw new Error(
    `no Chrome found. Set CHROME_PATH, or install Chrome.\nTried:\n  ${CHROME_CANDIDATES.join("\n  ")}`
  );
}

/** Static server for the repo, plus a POST sink the page reports into. */
function serve() {
  let deliver;
  const reported = new Promise((resolve) => (deliver = resolve));

  const server = createServer((req, res) => {
    const path = req.url.split("?")[0];

    if (req.method === "POST" && path === "/__result") {
      let body = "";
      req.on("data", (d) => (body += d));
      req.on("end", () => {
        res.writeHead(204).end();
        try {
          deliver(JSON.parse(body));
        } catch (err) {
          deliver({ error: `unparseable result payload: ${err.message}` });
        }
      });
      return;
    }

    // refuse anything that climbs out of the repo
    const rel = normalize(decodeURIComponent(path));
    if (rel.includes("..")) {
      res.writeHead(403).end();
      return;
    }
    const file = join(ROOT, rel);
    const stream = createReadStream(file);
    stream.on("error", () => res.writeHead(404).end("not found"));
    stream.on("open", () => {
      res.writeHead(200, { "content-type": MIME[extname(file)] ?? "application/octet-stream" });
      stream.pipe(res);
    });
  });

  return new Promise((resolve) => {
    server.listen(0, "127.0.0.1", () => resolve({ server, port: server.address().port, reported }));
  });
}

function launchChrome(bin, url, profileDir, allowCpu) {
  // On Linux/ROCm, WebGPU reaches the GPU through Vulkan. These flags are inert on
  // macOS, where Dawn already talks to Metal.
  const flags = [
    "--headless=new",
    "--no-sandbox",
    "--disable-gpu-sandbox",
    "--enable-unsafe-webgpu",
    "--enable-features=Vulkan",
    "--use-angle=vulkan",
  ];
  // Only offered on request: it swaps the real adapter for a CPU rasterizer.
  if (allowCpu) flags.push("--enable-unsafe-swiftshader");
  flags.push(`--user-data-dir=${profileDir}`, url);

  return spawn(bin, flags, { stdio: ["ignore", "ignore", "pipe"] });
}

/**
 * Serve the repo, open `page` in headless Chrome, and resolve with its report.
 *
 * `software` is true when the run landed on a CPU rasterizer. It is returned rather
 * than thrown because the caller may have been passed `--allow-cpu`; when it has
 * not, a software adapter is a failed run, since every numeric check still passes
 * while proving nothing about the hardware.
 *
 * @param {{page: string, allowCpu?: boolean, timeoutMs?: number, label?: string}} options
 * @returns {Promise<{result: object, software: boolean}>}
 */
export async function runValidationPage({
  page,
  allowCpu = false,
  timeoutMs = 120_000,
  label = "webgpu",
}) {
  const bin = await findChrome();
  const { server, port, reported } = await serve();
  const profileDir = await mkdtemp(join(tmpdir(), `${label}-chrome-`));

  const url = `http://127.0.0.1:${port}${page}`;
  console.log(`chrome:  ${bin}`);
  console.log(`page:    ${url}\n`);

  const chrome = launchChrome(bin, url, profileDir, allowCpu);
  let chromeErr = "";
  chrome.stderr.on("data", (d) => (chromeErr += d));

  try {
    const result = await Promise.race([
      reported,
      new Promise((_, reject) =>
        setTimeout(
          () =>
            reject(
              new Error(
                `page did not report within ${timeoutMs / 1000}s\n${chromeErr.slice(-2000)}`
              )
            ),
          timeoutMs
        )
      ),
    ]);

    const { vendor = "", architecture = "" } = result.adapter ?? {};
    return { result, software: SOFTWARE_ADAPTER.test(`${vendor} ${architecture}`) };
  } finally {
    // Wait for Chrome to actually exit before deleting its profile: kill() only sends
    // the signal, and a still-flushing process recreates files under the directory
    // mid-delete, which surfaces as ENOTEMPTY and masks an otherwise passing run.
    const exited = new Promise((resolve) => chrome.once("exit", resolve));
    chrome.kill();
    await Promise.race([exited, new Promise((r) => setTimeout(r, 5000))]);
    server.close();
    // Cleanup must never decide the exit status — the result above already did.
    await rm(profileDir, { recursive: true, force: true, maxRetries: 5 }).catch(() => {});
  }
}

/**
 * The shared preamble every runner prints: the adapter, and whether it is real.
 *
 * Returns true when the run should be failed for having landed on the CPU.
 */
export function reportAdapter(result, { software, allowCpu }) {
  const { vendor, architecture, f16, subgroups } = result.adapter;
  console.log(`adapter: ${vendor} / ${architecture}  f16=${f16}  subgroups=${subgroups}\n`);

  if (software && !allowCpu) {
    console.error(
      `FAIL — "${vendor} / ${architecture}" is a software adapter, so this run says ` +
        `nothing about the GPU.\n` +
        `       Check the Vulkan ICD (vulkaninfo should list an amdgpu/radeon device) ` +
        `and that Chrome can reach /dev/dri/renderD*.\n` +
        `       Pass --allow-cpu if a CPU run is genuinely what you want.`
    );
    return true;
  }
  return false;
}

/** The checks table, rendered the same way for every model. */
export function reportChecks(checks) {
  console.table(
    checks.map((c) => ({
      check: c.label,
      measured: typeof c.value === "number" ? Number(c.value.toPrecision(4)) : c.value,
      budget: c.budget,
      result: c.advisory ? "n/a" : c.ok ? "pass" : "FAIL",
    }))
  );
}
