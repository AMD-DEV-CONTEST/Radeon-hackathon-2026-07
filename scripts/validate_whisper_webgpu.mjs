/**
 * Run the WebGPU Whisper-tiny encoder validation page in headless Chrome.
 *
 * The browser plumbing — static server, Chrome flags, the software-adapter refusal —
 * lives in lib/headless-webgpu.mjs and is shared with the VAD runner. What is left
 * here is what "passed" means for the encoder: three checkpoints (mel, post_conv,
 * hidden) compared against both PyTorch and a CPU transcription of the same kernels,
 * zero argmax flips, and the wall time of a full 30 s window.
 *
 * Two comparisons rather than one, because they fail for different reasons:
 *
 *   GPU vs CPU     a WGSL or driver bug — wrong binding order, missing barrier,
 *                  a dispatch that does not cover its output
 *   GPU vs torch   a modelling mistake both paths share, since the weights are
 *                  float16 copies of an fp16 checkpoint and lose nothing
 *
 * The adapter has to be a real GPU. Chrome will silently fall back to SwiftShader — a
 * CPU rasterizer — and then every check still passes while proving nothing about the
 * hardware, and the latency number becomes meaningless besides.
 *
 * Run:  node scripts/validate_whisper_webgpu.mjs
 *       CHROME_PATH=/path/to/chrome node scripts/validate_whisper_webgpu.mjs
 *       node scripts/validate_whisper_webgpu.mjs --allow-cpu
 */

import { reportAdapter, reportChecks, runValidationPage } from "./lib/headless-webgpu.mjs";

const PAGE = "/frontend/webgpu/whisper/validate.html?auto=1";

/** Opt in to a software adapter. Off by default — see the header comment. */
const ALLOW_CPU = process.argv.includes("--allow-cpu");

/**
 * Longer than the VAD's two minutes: this page brings up two devices, compiles 13
 * pipelines twice, and times 23 encodes of a 30 s window. On a CPU adapter the same
 * work is minutes rather than seconds, and a timeout there should read as "too slow",
 * not as "the page crashed".
 */
const TIMEOUT_MS = 300_000;

const { result, software } = await runValidationPage({
  page: PAGE,
  allowCpu: ALLOW_CPU,
  timeoutMs: TIMEOUT_MS,
  label: "whisper",
});

if (result.error) {
  console.error(`FAIL — page threw: ${result.error}`);
  if (result.stack) console.error(result.stack);
  process.exit(1);
}

const onCpu = reportAdapter(result, { software, allowCpu: ALLOW_CPU });
reportChecks(result.checks);

const exp = (v) => v.toExponential(2);
console.table([
  {
    tensor: "mel",
    "|gpu-torch|": exp(result.gpuVsTorch.mel),
    "|gpu-cpu|": exp(result.gpuVsSim.mel),
  },
  {
    tensor: "post_conv",
    "|gpu-torch|": exp(result.gpuVsTorch.postConv),
    "|gpu-cpu|": exp(result.gpuVsSim.postConv),
  },
  {
    tensor: "hidden",
    "|gpu-torch|": exp(result.gpuVsTorch.hidden),
    "|gpu-cpu|": exp(result.gpuVsSim.hidden),
  },
]);

const t = result.throughput;
console.log(`\nclips: ${result.clips} x ${result.nCtx} positions   argmax flips: ${result.flips}`);
console.log(`load + compile: ${result.loadMs.toFixed(0)} ms`);
console.log(
  `encode (${t.nCtx} positions, ${(t.audioMs / 1000).toFixed(0)} s of audio): ` +
    `mean ${t.mean.toFixed(2)} ms   p50 ${t.p50.toFixed(2)} ms   p95 ${t.p95.toFixed(2)} ms`
);
console.log(
  `realtime factor: ${t.rtf.toFixed(5)}x (p95) — ${(1 / t.rtf).toFixed(0)}x faster than realtime`
);

const { vendor, architecture } = result.adapter;
if (result.passed && !onCpu) {
  console.log(
    `\nPASS — WebGPU encoder matches PyTorch on ${vendor} / ${architecture}` +
      (software ? " (software adapter, --allow-cpu)" : "")
  );
} else if (!result.passed) {
  console.log("\nFAIL — see the failing checks above");
}

if (!result.passed || onCpu) process.exitCode = 1;
