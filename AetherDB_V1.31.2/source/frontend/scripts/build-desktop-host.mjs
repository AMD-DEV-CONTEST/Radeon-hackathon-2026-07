import { randomBytes } from "node:crypto";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";

const platform = process.env.AETHERDB_HOST_PLATFORM || process.platform;
const frontendRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const tauriConfig = JSON.parse(
  readFileSync(join(frontendRoot, "src-tauri", "tauri.conf.json"), "utf8"),
);
const bundleMap = {
  win32: ["nsis"],
  darwin: ["app", "dmg"],
  linux: ["deb", "appimage"],
};
const bundles = bundleMap[platform];
if (!bundles) {
  console.error(`Unsupported desktop build platform: ${platform}`);
  process.exit(1);
}

console.log(`AetherDB desktop bundles for ${platform}: ${bundles.join(",")}`);
if (process.argv.includes("--print")) {
  process.exit(0);
}
const noBundle = process.argv.includes("--no-bundle");

const buildId = process.env.AETHERDB_BUILD_ID
  || `aether-${tauriConfig.version}-${new Date().toISOString().replace(/\D/g, "").slice(0, 14)}-${randomBytes(6).toString("hex")}`;
if (!/^[A-Za-z0-9._-]{3,128}$/.test(buildId)) {
  console.error("AETHERDB_BUILD_ID must contain only letters, numbers, dots, underscores, or hyphens");
  process.exit(1);
}

const pnpm = process.platform === "win32" ? "pnpm.cmd" : "pnpm";
const tauriArgs = noBundle
  ? ["tauri", "build", "--no-bundle"]
  : ["tauri", "build", "--bundles", bundles.join(",")];
const executable = process.platform === "win32"
  ? (process.env.ComSpec || "cmd.exe")
  : pnpm;
const commandArgs = process.platform === "win32"
  ? ["/d", "/s", "/c", `${pnpm} ${tauriArgs.join(" ")}`]
  : tauriArgs;
const result = spawnSync(executable, commandArgs, {
  cwd: frontendRoot,
  env: { ...process.env, AETHERDB_BUILD_ID: buildId },
  stdio: "inherit",
});
if (result.error) {
  console.error(result.error.message);
  process.exit(1);
}
if ((result.status ?? 1) !== 0) {
  process.exit(result.status ?? 1);
}

const targetRoot = resolve(process.env.CARGO_TARGET_DIR || join(frontendRoot, "src-tauri", "target"));
const binaryName = process.platform === "win32" ? "worldview.exe" : "worldview";
const releaseRoot = join(targetRoot, "release");
const binaryPath = join(releaseRoot, binaryName);
if (!existsSync(binaryPath)) {
  console.error(`Built Tauri executable is missing: ${binaryPath}`);
  process.exit(1);
}
const manifest = {
  schema_version: 1,
  product: "AetherDB",
  version: tauriConfig.version,
  build_id: buildId,
  protocol_version: "1.0",
  component: "desktop-host",
};
writeFileSync(
  join(releaseRoot, "build-manifest.json"),
  `${JSON.stringify(manifest, null, 2)}\n`,
  "utf8",
);
console.log(`AetherDB unified build ID: ${buildId}`);
