#!/usr/bin/env node
import { fileURLToPath } from "node:url";

import { writeCollectionSummary } from "./collection-summary.mjs";
import { resolveC0bOutDir } from "./resolve-out-dir.mjs";

const root = fileURLToPath(new URL("../../../", import.meta.url));
const payload = await writeCollectionSummary({
  outDir: resolveC0bOutDir(root)
});
console.log(JSON.stringify(payload, null, 2));
if (
  payload.capture_status !== "PASS" ||
  payload.finalization_status === "FAIL"
) {
  process.exitCode = 2;
}
