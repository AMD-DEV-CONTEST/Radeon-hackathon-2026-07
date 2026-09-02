import { spawnSync } from "node:child_process";

const PROMPTFOO_VERSION = "0.121.19";
const LIBSQL_VERSION = "0.5.29";
const binding = getLibsqlBinding();
const args = [
  "--yes",
  "--package",
  `promptfoo@${PROMPTFOO_VERSION}`,
  "--package",
  `${binding}@${LIBSQL_VERSION}`,
  "promptfoo",
  ...process.argv.slice(2),
];

const result = spawnSync("npx", args, {
  stdio: "inherit",
  env: {
    ...process.env,
    NPM_CONFIG_OMIT: "optional",
    PROMPTFOO_DISABLE_TELEMETRY: process.env.PROMPTFOO_DISABLE_TELEMETRY || "true",
  },
});

if (result.error) {
  console.error(`Unable to start Promptfoo: ${result.error.message}`);
  process.exit(2);
}
process.exit(typeof result.status === "number" ? result.status : 1);

function getLibsqlBinding() {
  const key = `${process.platform}-${process.arch}`;
  const bindings = {
    "darwin-arm64": "@libsql/darwin-arm64",
    "darwin-x64": "@libsql/darwin-x64",
    "linux-arm64": "@libsql/linux-arm64-gnu",
    "linux-x64": "@libsql/linux-x64-gnu",
    "win32-x64": "@libsql/win32-x64-msvc",
  };
  const packageName = bindings[key];
  if (!packageName) {
    throw new Error(`Unsupported Promptfoo/libsql platform: ${key}`);
  }
  return packageName;
}
