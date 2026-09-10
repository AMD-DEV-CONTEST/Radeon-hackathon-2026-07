import { createRequire } from "node:module";
import { readFile, rm } from "node:fs/promises";
import { dirname, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "..");
const piRoot = resolve(root, "node_modules", "@earendil-works", "pi-coding-agent");
const required = {
  "brace-expansion": { minimum: [5, 0, 9], nested: ["brace-expansion"] },
  undici: { minimum: [8, 9, 0], nested: ["undici"] }
};

function versionTuple(version) {
  const match = String(version).match(/^(\d+)\.(\d+)\.(\d+)/);
  if (!match) throw new Error(`Unsupported dependency version: ${version}`);
  return match.slice(1).map(Number);
}

function atLeast(actual, minimum) {
  for (let index = 0; index < minimum.length; index += 1) {
    if (actual[index] > minimum[index]) return true;
    if (actual[index] < minimum[index]) return false;
  }
  return true;
}

for (const [name, policy] of Object.entries(required)) {
  for (const nestedName of policy.nested) {
    await rm(resolve(piRoot, "node_modules", nestedName), { recursive: true, force: true });
  }
  const packagePath = resolve(root, "node_modules", name, "package.json");
  const metadata = JSON.parse(await readFile(packagePath, "utf8"));
  if (!atLeast(versionTuple(metadata.version), policy.minimum)) {
    throw new Error(`${name} ${metadata.version} is below the security floor ${policy.minimum.join(".")}`);
  }
  const requireFromPi = createRequire(resolve(piRoot, "package.json"));
  const resolvedEntry = requireFromPi.resolve(name);
  const expectedRoot = resolve(root, "node_modules", name) + sep;
  if (!resolvedEntry.startsWith(expectedRoot)) {
    throw new Error(`${name} resolves outside the secured root dependency: ${resolvedEntry}`);
  }
  console.log(JSON.stringify({ dependency: name, version: metadata.version, resolvedEntry }));
}
