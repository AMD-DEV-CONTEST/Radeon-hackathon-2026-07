/**
 * Run the WebGPU VAD validation page in headless Chrome and report the result.
 *
 * The browser plumbing — static server, Chrome flags, the software-adapter refusal —
 * lives in lib/headless-webgpu.mjs and is shared with the Whisper runner. What is
 * left here is what "passed" means for the VAD: agreement with ONNX Runtime, no
 * decision flips at the 0.5 threshold, and a p95 under one 32 ms frame.
 *
 * The adapter has to be a real GPU. Chrome will silently fall back to SwiftShader — a
 * CPU rasterizer — and then every check still passes while proving nothing about the
 * hardware. So the real Vulkan/Metal flags are the default and a software adapter is a
 * hard failure unless `--allow-cpu` is passed deliberately.
 *
 * Run:  node scripts/validate_webgpu.mjs
 *       CHROME_PATH=/path/to/chrome node scripts/validate_webgpu.mjs
 *       node scripts/validate_webgpu.mjs --allow-cpu   # opt in to the CPU fallback
 */

import { reportAdapter, reportChecks, runValidationPage } from "./lib/headless-webgpu.mjs";

const PAGE = "/frontend/webgpu/vad/validate.html?auto=1";

/** Opt in to a software adapter. Off by default — see the header comment. */
const ALLOW_CPU = process.argv.includes("--allow-cpu");

const { result, software } = await runValidationPage({
  page: PAGE,
  allowCpu: ALLOW_CPU,
  label: "vad",
});

if (result.error) {
  console.error(`FAIL — page threw: ${result.error}`);
  if (result.stack) console.error(result.stack);
  process.exit(1);
}

const onCpu = reportAdapter(result, { software, allowCpu: ALLOW_CPU });
reportChecks(result.checks);

const { mean, p50, p95 } = result.latencyMs;
console.log(`\nframes: ${result.frames}   decision flips: ${result.flips}`);
console.log(
  `latency: mean ${mean.toFixed(3)} ms   p50 ${p50.toFixed(3)} ms   p95 ${p95.toFixed(3)} ms   per 32 ms of audio`
);

const { vendor, architecture } = result.adapter;
if (result.passed && !onCpu) {
  console.log(
    `\nPASS — WebGPU kernels match ONNX Runtime on ${vendor} / ${architecture}` +
      (software ? " (software adapter, --allow-cpu)" : "")
  );
} else if (!result.passed) {
  console.log("\nFAIL — see the failing checks above");
}

if (!result.passed || onCpu) process.exitCode = 1;
