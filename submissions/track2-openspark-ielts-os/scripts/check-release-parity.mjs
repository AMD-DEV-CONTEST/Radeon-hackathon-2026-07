import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const destinations = ["dist", "ios/App/App/public"];
const shellFiles = ["index.html", "app.js", "styles.css", "service-worker.js", "remote-update.js"];

const sourceHtml = await readFile(path.join(root, "index.html"), "utf8");
const sourceWorker = await readFile(path.join(root, "service-worker.js"), "utf8");
const sourceApp = await readFile(path.join(root, "app.js"), "utf8");
const helperFiles = ["app-reliability.js", "learning-core.js"].filter((name) => new RegExp(`<script\\s+src="\\./${name.replace(".", "\\.")}\\?v=\\d+"`).test(sourceHtml));

for (const file of [...shellFiles, ...helperFiles]) {
  const source = await readFile(path.join(root, file));
  for (const destination of destinations) {
    const output = await readFile(path.join(root, destination, file));
    assert.deepEqual(output, source, `${file} differs between source and ${destination}`);
  }
}

for (const match of sourceHtml.matchAll(/<script\s+src="\.\/([^"?]+)\?v=(\d+)"/g)) {
  assert.match(sourceWorker, new RegExp(`"\\./${match[1].replace(".", "\\.")}\\?v=${match[2]}"`), `${match[1]} version differs between HTML and APP_SHELL`);
}
const cacheVersion = sourceWorker.match(/CACHE_NAME = "ielts-os-demo-v(\d+)"/)?.[1];
const registrationVersion = sourceApp.match(/serviceWorker\.register\("\.\/service-worker\.js\?v=(\d+)"/)?.[1];
assert.ok(cacheVersion && registrationVersion, "service-worker versions must be present");
assert.equal(registrationVersion, cacheVersion, "service-worker registration/cache version mismatch");

console.log(`Release parity matched for ${shellFiles.length + helperFiles.length} files.`);
