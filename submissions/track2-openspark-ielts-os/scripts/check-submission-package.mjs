import assert from "node:assert/strict";
import { existsSync, readFileSync, statSync } from "node:fs";

const required = [
  "README.md",
  "SPECIFICATION.md",
  "poster.pdf",
  "demo/IELTS-OS-OpenSpark-Demo.mp4",
  "demo/IELTS-OS-OpenSpark-Demo.en.srt",
  "scripts/record-demo.py",
];

for (const file of required) assert.ok(existsSync(file), `missing submission file: ${file}`);
assert.ok(statSync("poster.pdf").size > 10_000, "poster PDF is unexpectedly small");
assert.ok(statSync("demo/IELTS-OS-OpenSpark-Demo.mp4").size > 1_000_000, "demo video is unexpectedly small");

const readme = readFileSync("README.md", "utf8");
const gitignore = readFileSync(".gitignore", "utf8");
const envExample = readFileSync(".env.radeon.example", "utf8");
assert.match(readme, /demo\/IELTS-OS-OpenSpark-Demo\.mp4/);
assert.match(readme, /SPECIFICATION\.md/);
assert.match(readme, /poster\.pdf/);
assert.match(gitignore, /^\.env\*$/m);
assert.doesNotMatch(envExample, /rc-[A-Za-z0-9]{20,}/, "real Radeon key found in example env");
assert.ok(!existsSync("api-server.mjs"), "obsolete cloud proxy must not ship");

console.log("Submission package and secret-safety checks passed.");
