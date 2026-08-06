import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const read = (path) => readFileSync(resolve(root, path), "utf8");
const manifest = JSON.parse(read("site10x.manifest.json"));
const index = read("index.html");
const styles = read("styles.min.css");
const app = read("app.min.js");
const failures = [];
const requireCondition = (condition, message) => {
  if (!condition) failures.push(message);
};

execFileSync(process.execPath, ["--check", resolve(root, "app.js")], {
  stdio: "pipe"
});
execFileSync(process.execPath, ["--check", resolve(root, "preview.mjs")], {
  stdio: "pipe"
});

const declaredRoutes = manifest.routes.map((route) =>
  typeof route === "string" ? route : route.path
);
const renderedRoutes = Array.from(
  index.matchAll(/data-route="([^"]+)"/g),
  (match) => match[1]
);

requireCondition(
  declaredRoutes.length === 46,
  "The full GTM employee workspace must declare all 46 operator, operations, governance, and source routes."
);
requireCondition(
  declaredRoutes.every((route) => renderedRoutes.includes(route)),
  "Every declared route must have a rendered route panel."
);
requireCondition(
  manifest.interactionScenarios.length === 12,
  "The browser evidence contract must retain 12 interaction scenarios."
);
requireCondition(
  (index.match(/<h1(?:\s|>)/g) ?? []).length === 1,
  "The document must contain exactly one h1."
);
requireCondition(
  !/(?:src|href)=["'](?:https?:)?\/\//i.test(index),
  "Runtime resources must remain self-only."
);
requireCondition(
  Array.isArray(manifest.sameOriginApiRoutes) &&
    manifest.sameOriginApiRoutes.length === 60 &&
    !/(?:fetch|XMLHttpRequest|WebSocket|EventSource)\s*\(\s*["'`]https?:/i.test(app) &&
    !/(?:fetch|XMLHttpRequest|WebSocket|EventSource)\s*\(\s*["'`]\/\/(?!\/)/i.test(app),
  "Runtime requests must be declared same-origin API calls; absolute or protocol-relative requests are forbidden."
);
requireCondition(
  !/\b(?:innerHTML|outerHTML|insertAdjacentHTML)\b/.test(app),
  "Application source must not inject HTML strings."
);
requireCondition(
  !/transition(?:-property)?\s*:\s*all\b/i.test(styles),
  "CSS must not transition all properties."
);
requireCondition(
  /prefers-reduced-motion:\s*reduce[\s\S]*transition:\s*none\s*!important/i.test(styles),
  "Reduced-motion CSS must disable transitions."
);
requireCondition(
  index.includes("data-product-surface"),
  "The first usable work surface must be marked."
);
requireCondition(
  index.includes("Open mission control") &&
    index.includes("See the channel intelligence"),
  "Primary actions must remain visible."
);

if (failures.length) {
  process.stderr.write(`${failures.map((failure) => `- ${failure}`).join("\n")}\n`);
  process.exitCode = 1;
} else {
  const bytes =
    Buffer.byteLength(index) +
    Buffer.byteLength(styles) +
    Buffer.byteLength(app);
  process.stdout.write(
    [
      "ProofLaunch submission workspace validated.",
      `Routes: ${declaredRoutes.length}`,
      `Interactions: ${manifest.interactionScenarios.length}`,
      `Static resource bytes: ${bytes}`,
      `Same-origin API contracts: ${manifest.sameOriginApiRoutes.length}`
    ].join("\n") + "\n"
  );
}
