/**
 * Profile the Whisper encoder's 36 dispatches on a real adapter.
 *
 * Optimization without a profile is guessing, and the guesses here would have been
 * wrong in a specific way: the attention kernel *looks* like the expensive one because
 * it is the only kernel with three phases and a workgroup-memory array, while the
 * linear kernels look cheap because each is six lines. Which is actually true depends
 * on N_CTX, and at 1500 positions it is not the one intuition picks.
 *
 * Uses the same headless harness as the validation runners, so the adapter is real and
 * a software fallback is still a hard failure — a CPU profile would rank the kernels
 * by a completely different cost model and send the work in the wrong direction.
 *
 * Run:  CHROME_PATH=/usr/bin/google-chrome node scripts/profile_whisper_webgpu.mjs
 */

import { reportAdapter, runValidationPage } from "./lib/headless-webgpu.mjs";

const PAGE = "/frontend/webgpu/whisper/bench.html?auto=1";
const ALLOW_CPU = process.argv.includes("--allow-cpu");

const { result, software } = await runValidationPage({
  page: PAGE,
  allowCpu: ALLOW_CPU,
  timeoutMs: 300_000,
  label: "whisper-bench",
});

if (result.error) {
  console.error(`FAIL — page threw: ${result.error}`);
  if (result.stack) console.error(result.stack);
  process.exit(1);
}

const onCpu = reportAdapter(result, { software, allowCpu: ALLOW_CPU });

console.log(`width: ${result.nCtx} positions x ${result.d} channels`);
console.log(`fence overhead (subtracted): ${result.fenceMs.toFixed(2)} ms\n`);

console.table(
  result.kernels.map((k) => ({
    kernel: k.kernel,
    dispatches: k.count,
    "total ms": Number(k.ms.toFixed(2)),
    "share %": Number(((k.ms / result.totalMs) * 100).toFixed(1)),
    "ms each": Number((k.ms / k.count).toFixed(2)),
  }))
);

console.log(`\ntotal: ${result.totalMs.toFixed(2)} ms for one 30 s window`);

// Anything under a few percent is not worth a rewrite; say so rather than leaving a
// ranked list that implies every row is actionable.
const top = result.kernels.filter((k) => k.ms / result.totalMs >= 0.05);
console.log(
  `\n${top.length} kernel(s) above 5% of the total: ` +
    top.map((k) => `${k.kernel} (${((k.ms / result.totalMs) * 100).toFixed(0)}%)`).join(", ")
);

if (onCpu) process.exitCode = 1;
