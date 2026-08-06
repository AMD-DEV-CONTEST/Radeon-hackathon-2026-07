import path from "node:path";

const PROTECTED = new Set([
  "privateplate-v2",
  "privateplate-v2.attempt1-arg-fail"
]);

/**
 * Resolve the C0-B evidence directory for the current run.
 * Existing Qwen2.5-7B trees are protected from accidental writes.
 */
export function resolveC0bOutDir(root) {
  const evidenceRoot = path.join(root, "benchmarks/c0/stage-b");
  if (process.env.PRIVATEPLATE_C0B_OUT_DIR) {
    const resolved = path.resolve(process.env.PRIVATEPLATE_C0B_OUT_DIR);
    assertAllowedRunDirectory(resolved, evidenceRoot);
    return resolved;
  }
  if (process.env.PRIVATEPLATE_RUN_ID) {
    const runId = process.env.PRIVATEPLATE_RUN_ID;
    const resolved = path.join(evidenceRoot, runId);
    assertAllowedRunDirectory(resolved, evidenceRoot);
    return resolved;
  }
  throw new Error(
    "PRIVATEPLATE_RUN_ID or PRIVATEPLATE_C0B_OUT_DIR is required for C0-B writers."
  );
}

function assertAllowedRunDirectory(resolved, evidenceRoot) {
  const relative = path.relative(evidenceRoot, resolved);
  const runId = path.basename(resolved);
  if (
    relative !== runId ||
    path.isAbsolute(relative) ||
    // Allow compact UTC stamps like 20260727T113757Z (T/Z are uppercase).
    !/^privateplate-[a-z0-9][a-zA-Z0-9._-]*$/.test(runId)
  ) {
    throw new Error(
      "C0-B output must be one direct privateplate-* child of benchmarks/c0/stage-b."
    );
  }
  if (PROTECTED.has(runId)) {
    throw new Error(`Refusing to write into protected evidence tree: ${runId}`);
  }
}
