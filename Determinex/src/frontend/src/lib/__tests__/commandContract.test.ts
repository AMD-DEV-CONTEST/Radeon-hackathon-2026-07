import { describe, expect, it } from "vitest";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { resolve, join } from "node:path";

/**
 * The IPC contract test.
 *
 * Every frontend `invoke("x")` must correspond to a command actually registered
 * in the Rust `generate_handler!`. Nothing enforced that, and the cost was real:
 * VerifiedSearch shipped calling `verified_search`, a command that never
 * existed on the Rust side. `invokeSafe` swallowed the rejection into null, so
 * the panel was dead from the day it shipped and nobody found out until someone
 * clicked it a year later.
 *
 * This is the cheap half of what tauri-specta would give us. specta generates
 * typed bindings from the Rust signatures, which makes a nonexistent command a
 * COMPILE error and also pins argument names and shapes — strictly better, and
 * still the right end state (see docs/audits/IDE_SHELL_AUDIT_20260727.md §A1).
 * That is a 159-command migration; this test closes the specific hole that
 * actually bit us, today, in CI, at no risk.
 *
 * It reads the real sources rather than a maintained list, so it cannot drift.
 */

const SRC = resolve(__dirname, "../..");
const TAURI_SRC = resolve(__dirname, "../../../src-tauri/src");

function walk(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    const p = join(dir, entry);
    if (statSync(p).isDirectory()) {
      if (entry === "node_modules" || entry === ".next") continue;
      walk(p, out);
    } else if (/\.(ts|tsx|rs)$/.test(entry)) {
      out.push(p);
    }
  }
  return out;
}

/** Commands registered in lib.rs's generate_handler! block. */
function registeredCommands(): Set<string> {
  const lib = readFileSync(join(TAURI_SRC, "lib.rs"), "utf8");
  const start = lib.indexOf("generate_handler!");
  expect(start, "generate_handler! not found in lib.rs").toBeGreaterThan(-1);
  // The macro body ends at the closing `]` of its bracket list.
  const body = lib.slice(start, lib.indexOf("])", start));
  const names = new Set<string>();
  for (const m of body.matchAll(/(?:([a-z_0-9]+)::)?([a-z_0-9]+)\s*,/g)) {
    names.add(m[2]);
  }
  names.delete("generate_handler");
  return names;
}

/** Every command name the frontend actually invokes. */
function invokedCommands(): Map<string, string[]> {
  const found = new Map<string, string[]>();
  const pattern =
    /(?:invoke|invokeSafe|invokeIdeCommand|invokeUnifiedProductCommand)\s*(?:<[\s\S]*?>)?\s*\(\s*["'`]([a-zA-Z_0-9]+)["'`]/g;
  for (const file of walk(SRC)) {
    if (file.includes("__tests__") || file.endsWith(".rs")) continue;
    const text = readFileSync(file, "utf8");
    for (const m of text.matchAll(pattern)) {
      const list = found.get(m[1]) ?? [];
      list.push(file.replace(SRC, "src"));
      found.set(m[1], list);
    }
  }
  return found;
}

/**
 * Commands the frontend reaches through a governed Python surface rather than a
 * Rust handler of the same name. invokeIdeCommand maps its verb onto a Rust
 * command that IS registered, so these are checked against that instead.
 */
const PYTHON_SURFACE_VERBS = new Set<string>();

describe("IPC command contract", () => {
  const registered = registeredCommands();
  const invoked = invokedCommands();

  it("finds a plausible number of registered commands", () => {
    // Guards the parser itself: a regex change that silently matched nothing
    // would make every other assertion here vacuously pass.
    expect(registered.size).toBeGreaterThan(100);
  });

  it("finds the frontend's invoke calls", () => {
    expect(invoked.size).toBeGreaterThan(50);
  });

  it("every invoked command is registered in Rust", () => {
    const missing = [...invoked.entries()]
      .filter(([name]) => !registered.has(name) && !PYTHON_SURFACE_VERBS.has(name))
      .map(([name, files]) => `${name}  (called from ${[...new Set(files)].join(", ")})`);

    expect(
      missing,
      "These commands are invoked from the frontend but are NOT in lib.rs's " +
        "generate_handler!. invokeSafe turns the rejection into null, so the " +
        "call fails silently at runtime:\n  " +
        missing.join("\n  ")
    ).toEqual([]);
  });

  it("registers no duplicate command names", () => {
    // Two handlers with one name is a Tauri runtime panic, not a compile error.
    const lib = readFileSync(join(TAURI_SRC, "lib.rs"), "utf8");
    const body = lib.slice(
      lib.indexOf("generate_handler!"),
      lib.indexOf("])", lib.indexOf("generate_handler!"))
    );
    const all = [...body.matchAll(/(?:([a-z_0-9]+)::)?([a-z_0-9]+)\s*,/g)].map((m) => m[2]);
    const dupes = all.filter((n, i) => all.indexOf(n) !== i && n !== "generate_handler");
    expect([...new Set(dupes)], `duplicate command registrations: ${dupes.join(", ")}`).toEqual([]);
  });

  it("every #[tauri::command] is either registered or deliberately not", () => {
    // A command defined but never registered is unreachable dead surface. This
    // is reported, not failed: some are genuinely staged for later wiring.
    const defined = new Set<string>();
    for (const file of walk(TAURI_SRC)) {
      if (!file.endsWith(".rs")) continue;
      const text = readFileSync(file, "utf8");
      for (const m of text.matchAll(/#\[tauri::command\][\s\S]{0,200}?fn\s+([a-z_0-9]+)/g)) {
        defined.add(m[1]);
      }
    }
    const unregistered = [...defined].filter((n) => !registered.has(n));
    if (unregistered.length > 0) {
      console.warn(
        `[contract] ${unregistered.length} #[tauri::command] fn(s) are not registered: ` +
          unregistered.sort().join(", ")
      );
    }
    expect(defined.size).toBeGreaterThan(100);
  });
});
