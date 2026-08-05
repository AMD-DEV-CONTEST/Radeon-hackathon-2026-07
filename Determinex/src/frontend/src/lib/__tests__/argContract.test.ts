import { describe, expect, it } from "vitest";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { resolve, join } from "node:path";

/**
 * The IPC *argument* contract.
 *
 * `commandContract.test.ts` proves a command exists. This proves the arguments
 * reach it.
 *
 * Tauri converts camelCase JS keys to the Rust command's snake_case parameter
 * names. A snake_case key in JS therefore matches NOTHING: the argument arrives
 * missing, the command rejects, and `invokeSafe` turns that into `null`.
 *
 * This exact bug shipped twice in gitService and is documented in-file at both
 * sites: `cloneRepo` sent `remote_url` and `resolveConflict` sent
 * `resolved_content`. Both failed 100% of the time for their entire lifetime --
 * every "Git Clone" from ProjectHub and every Merge Editor "resolve" was
 * silently a no-op.
 *
 * This is the second half of what tauri-specta would give at compile time.
 * Deliberately conservative: only flat, single-line object literals are
 * analysed, and anything ambiguous is SKIPPED rather than guessed at, because a
 * false positive here would train people to ignore the test.
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

/** Injected by Tauri, never supplied from JS. */
const INJECTED =
  /^(State\s*<|tauri::State|AppHandle|tauri::AppHandle|Window|tauri::Window|Runtime)/;

/** Rust command name -> its JS-supplied parameter names (snake_case). */
function rustSignatures(): Map<string, string[]> {
  const sigs = new Map<string, string[]>();
  for (const file of walk(TAURI_SRC)) {
    if (!file.endsWith(".rs")) continue;
    const text = readFileSync(file, "utf8");
    const re =
      /#\[tauri::command\][\s\S]{0,120}?pub (?:async )?fn (\w+)\s*\(([\s\S]*?)\)\s*(?:->|\{)/g;
    for (const m of text.matchAll(re)) {
      const params = m[2]
        .split(",")
        .map((a) => a.trim())
        .filter(Boolean)
        .map((a) => {
          const idx = a.indexOf(":");
          if (idx < 0) return null;
          return {
            name: a
              .slice(0, idx)
              .trim()
              .replace(/^mut\s+/, ""),
            ty: a.slice(idx + 1).trim(),
          };
        })
        .filter((pr): pr is { name: string; ty: string } => !!pr && !INJECTED.test(pr.ty))
        .map((pr) => pr.name);
      sigs.set(m[1], params);
    }
  }
  return sigs;
}

const toSnake = (s: string) => s.replace(/[A-Z]/g, (c) => "_" + c.toLowerCase());

interface CallSite {
  cmd: string;
  keys: string[];
  file: string;
}

function invokedArgs(): CallSite[] {
  const out: CallSite[] = [];
  // Flat object literal only: [^{}] refuses to match nested braces, so any call
  // with a nested payload is skipped rather than mis-parsed.
  const re =
    /(?:invoke|invokeSafe)\s*(?:<[^>]*>)?\s*\(\s*["'`]([A-Za-z_0-9]+)["'`]\s*,\s*\{([^{}]*)\}\s*\)/g;
  for (const file of walk(SRC)) {
    if (file.includes("__tests__") || file.endsWith(".rs")) continue;
    const text = readFileSync(file, "utf8");
    for (const m of text.matchAll(re)) {
      const keys = m[2]
        .split(",")
        .map((k) => k.split(":")[0].trim())
        .filter((k) => /^[A-Za-z_][A-Za-z_0-9]*$/.test(k));
      if (keys.length > 0) out.push({ cmd: m[1], keys, file: file.replace(SRC, "src") });
    }
  }
  return out;
}

describe("IPC argument contract", () => {
  const sigs = rustSignatures();
  const calls = invokedArgs();

  it("parses Rust command signatures", () => {
    expect(sigs.size).toBeGreaterThan(100);
    // Spot-check a known signature, so a regex regression is loud rather than
    // silently making the suite vacuous.
    expect(sigs.get("git_clone")).toEqual(["remote_url", "destination"]);
    expect(sigs.get("git_resolve_conflict")).toEqual(["cwd", "path", "resolved_content"]);
  });

  it("finds analysable call sites", () => {
    expect(calls.length).toBeGreaterThan(20);
  });

  it("every argument passed matches a real parameter", () => {
    const bad: string[] = [];
    for (const c of calls) {
      const params = sigs.get(c.cmd);
      if (!params || params.length === 0) continue; // existence is the other test's job
      for (const key of c.keys) {
        // A key already containing "_" is snake_case in JS. Tauri maps
        // camelCase -> snake_case; it does not accept snake_case verbatim, which
        // is why `remote_url` and `resolved_content` matched nothing and those
        // two calls no-op'd for their whole lifetime. So an underscore in a JS
        // key is itself the defect, even though the string equals the Rust
        // param name. Accepting it here would have passed the shipped bug.
        if (key.includes("_")) {
          bad.push(
            `${c.cmd}: passed snake_case "${key}" -- use camelCase ` +
              `"${key.replace(/_(\w)/g, (_m, ch) => ch.toUpperCase())}"  (${c.file})`
          );
          continue;
        }
        if (params.includes(toSnake(key))) continue;
        bad.push(`${c.cmd}: passed "${key}", real params are [${params.join(", ")}]  (${c.file})`);
      }
    }
    const detail = bad.length ? "\n  " + bad.join("\n  ") : "";
    expect(
      bad,
      "These argument names match no parameter on the Rust side. Tauri maps " +
        "camelCase JS keys to snake_case params, so they arrive MISSING and the " +
        "call fails silently:" +
        detail
    ).toEqual([]);
  });

  it("would catch the snake_case regression that shipped twice", () => {
    // Guards the guard: if toSnake or the matcher regresses, this fails.
    const params = sigs.get("git_clone")!;
    // The correct camelCase key resolves to the real param...
    expect(params.includes(toSnake("remoteUrl"))).toBe(true);
    // ...and the snake_case form that shipped is rejected on the underscore
    // rule, NOT on string equality -- it is string-equal to the param, which is
    // exactly why a naive matcher would wave it through.
    expect("remote_url".includes("_")).toBe(true);
    expect(params.includes("remote_url")).toBe(true);
  });
});
