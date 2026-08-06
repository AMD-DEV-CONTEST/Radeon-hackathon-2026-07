import { existsSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const frontendRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const projectRoot = resolve(frontendRoot, "..");
const configured = process.env.AETHERDB_PYTHON;
const candidates = [
  configured,
  process.platform === "win32"
    ? join(projectRoot, "venv", "Scripts", "python.exe")
    : join(projectRoot, "venv", "bin", "python"),
  process.platform === "win32" ? "python" : "python3",
].filter(Boolean);

const python = candidates.find((candidate) =>
  candidate === "python" || candidate === "python3" || existsSync(candidate),
);
if (!python) {
  console.error("No Python runtime found. Set AETHERDB_PYTHON to the project build environment.");
  process.exit(1);
}

const args = [join(projectRoot, "scripts", "build_desktop_sidecar.py")];
if (process.env.AETHERDB_BUILD_CACHE_ROOT) {
  args.push("--work-root", process.env.AETHERDB_BUILD_CACHE_ROOT);
}
const result = spawnSync(python, args, {
  cwd: projectRoot,
  env: process.env,
  stdio: "inherit",
});
if (result.error) {
  console.error(result.error.message);
  process.exit(1);
}
process.exit(result.status ?? 1);
