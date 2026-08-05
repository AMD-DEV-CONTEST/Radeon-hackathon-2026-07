// Drives scripts/reinstall-phone.sh through a shim PATH and asserts every
// broken stage makes it exit non-zero (fail-closed, no masked failures).
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, writeFileSync, chmodSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const ROOT = new URL("..", import.meta.url).pathname;
const shimDir = mkdtempSync(join(tmpdir(), "ielts-shims-"));

const shim = (name, body) => {
  const path = join(shimDir, name);
  writeFileSync(path, `#!/bin/sh\n${body}\n`);
  chmodSync(path, 0o755);
};

shim("npx", "exit 0");
shim("xcodebuild", `
if [ "$XCODEBUILD_MODE" = "fail" ]; then echo "BUILD FAILED"; exit 1; fi
if [ "$XCODEBUILD_MODE" = "noapp" ]; then echo "BUILD SUCCEEDED"; exit 0; fi
mkdir -p "$TMPDIR/ielts-os-derived-data/Build/Products/Debug-iphoneos/App.app/Frameworks"
touch "$TMPDIR/ielts-os-derived-data/Build/Products/Debug-iphoneos/App.app/embedded.mobileprovision"
touch "$TMPDIR/ielts-os-derived-data/Build/Products/Debug-iphoneos/App.app/Frameworks/Capacitor.framework"
echo "BUILD SUCCEEDED"
exit 0`);
shim("security", "printf '%s' '<?xml version=\"1.0\"?><plist version=\"1.0\"><dict><key>ExpirationDate</key><date>2026-08-05T00:00:00Z</date></dict></plist>'");
shim("codesign", "echo 'CandidateCDHash sha256=deadbeef' >&2; exit 0");
shim("sleep", "exit 0");
shim("xcrun", `
case "$XCRUN_MODE" in
  install-fails) echo "install ERROR"; exit 1;;
  launch-fails) case "$*" in *"process launch"*) exit 1;; esac; exit 0;;
  process-missing) exit 0;;
  ok) case "$*" in *"info processes"*) echo "12345 com.francischi.ieltsos";; esac; exit 0;;
esac`);

const run = (name, env, expectFail) => {
  const caseTmp = mkdtempSync(join(tmpdir(), "ielts-case-"));
  let code = 0;
  try {
    execFileSync("/bin/zsh", [join(ROOT, "scripts/reinstall-phone.sh")], {
      env: { ...process.env, PATH: `${shimDir}:/usr/bin:/bin`, TMPDIR: caseTmp, ...env },
      stdio: "pipe",
    });
  } catch (error) {
    code = error.status ?? 1;
  }
  if (expectFail) assert.notEqual(code, 0, `${name}: installer must exit non-zero`);
  else assert.equal(code, 0, `${name}: installer must succeed when every stage works`);
  console.log(`${name}: exit ${code} (expected ${expectFail ? "non-zero" : "0"})`);
};

run("build-fails", { XCODEBUILD_MODE: "fail", XCRUN_MODE: "ok" }, true);
run("app-missing-after-build", { XCODEBUILD_MODE: "noapp", XCRUN_MODE: "ok" }, true);
run("install-fails", { XCODEBUILD_MODE: "ok", XCRUN_MODE: "install-fails" }, true);
run("launch-fails", { XCODEBUILD_MODE: "ok", XCRUN_MODE: "launch-fails" }, true);
run("process-missing", { XCODEBUILD_MODE: "ok", XCRUN_MODE: "process-missing" }, true);
run("all-stages-ok", { XCODEBUILD_MODE: "ok", XCRUN_MODE: "ok" }, false);

console.log("Installer failure checks passed.");
