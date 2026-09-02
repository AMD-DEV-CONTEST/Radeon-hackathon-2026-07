import { describe, expect, it, afterAll } from "vitest";
import { mkdtempSync, writeFileSync, rmSync, mkdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { RuleTester } from "eslint";
import tsParser from "@typescript-eslint/parser";

import determinex from "../../../eslint-rules/index.mjs";
import { collectVoidCommands, resetVoidCommandCache } from "../../../eslint-rules/voidCommands.mjs";

/**
 * Guard for the guard.
 *
 * The last contract test written in this repo (argContract) shipped with a
 * matcher that would itself have accepted the bug it existed to catch. A lint
 * rule that silently matches nothing is worse than no rule, because the clean
 * run is read as proof.
 *
 * So this pins both halves: the Rust parse actually classifies return types, and
 * the rule actually reports -- and, just as important, actually stays quiet on
 * the value-returning commands, since a rule that fires on everything gets
 * disabled within a day.
 */

const RUST = `
use tauri::State;

#[tauri::command]
pub async fn git_commit(cwd: String, message: String) -> Result<(), String> {
    Ok(())
}

#[tauri::command]
fn pty_write(id: String, data: String) -> Result<(), String> { Ok(()) }

// No return type at all -- also indistinguishable from a rejection.
#[tauri::command]
fn fire_and_forget(id: String) { }

// Bare unit return.
#[tauri::command]
fn bare_unit() -> () { }

#[tauri::command]
pub async fn get_status(cwd: String) -> Result<GitStatus, String> {
    Ok(GitStatus::default())
}

// A tuple return is NOT unit and must not be flagged.
#[tauri::command]
fn get_pair() -> Result<((), String), String> { Ok(((), String::new())) }

// Multi-line signature with a nested paren in a default, plus an extra
// attribute between the command marker and the fn -- both shapes appear in the
// real sources and both must still parse.
#[tauri::command]
#[specta::specta]
pub async fn stage_diff_for_review(
    app: tauri::AppHandle,
    diff: StagedDiff,
) -> Result<(), String> {
    Ok(())
}

#[tauri::command]
fn returns_plain_string() -> String { String::new() }
`;

// Built at module scope, not in beforeAll: ESLint's RuleTester registers its own
// describe/it blocks, so `ruleTester.run` has to be called during collection --
// which means the fixture path must already exist by then.
const fixture = mkdtempSync(join(tmpdir(), "determinex-void-rule-"));
mkdirSync(join(fixture, "nested"), { recursive: true });
writeFileSync(join(fixture, "commands.rs"), RUST, "utf8");
// Proves the walk recurses; git.rs and oauth_github.rs live in the real tree
// alongside subdirectories.
writeFileSync(
  join(fixture, "nested", "more.rs"),
  "#[tauri::command]\nfn nested_void() -> Result<(), String> { Ok(()) }\n",
  "utf8"
);
resetVoidCommandCache();

afterAll(() => {
  rmSync(fixture, { recursive: true, force: true });
  resetVoidCommandCache();
});

describe("collectVoidCommands", () => {
  it("classifies every void shape and nothing else", () => {
    const names = collectVoidCommands(fixture);
    expect([...names].sort()).toEqual([
      "bare_unit",
      "fire_and_forget",
      "git_commit",
      "nested_void",
      "pty_write",
      "stage_diff_for_review",
    ]);
  });

  it("does not flag commands that return a value", () => {
    const names = collectVoidCommands(fixture);
    for (const valued of ["get_status", "get_pair", "returns_plain_string"]) {
      expect(names.has(valued), `${valued} must not be treated as void`).toBe(false);
    }
  });

  it("returns an empty set rather than throwing when src-tauri is absent", () => {
    resetVoidCommandCache();
    expect(collectVoidCommands(join(fixture, "does-not-exist")).size).toBe(0);
    resetVoidCommandCache();
  });
});

// RuleTester emits its own describe/it per case, so this runs at top level.
//
// The TypeScript parser, not RuleTester's default espree: every real call site is
// .ts/.tsx, and espree cannot parse `invokeSafe<null>("cmd")` -- it reads the
// type argument as a chain of comparisons, so the call disappears and the case
// silently passes as "no error found". Testing the rule against a parser the
// codebase does not use would have been the exact false-confidence this file
// exists to prevent.
new RuleTester({
  languageOptions: {
    parser: tsParser,
    ecmaVersion: 2022,
    sourceType: "module",
  },
}).run(
  "no-invokesafe-on-void-command",
  // The rule is authored in plain .mjs (ESLint loads the config directly, so it
  // cannot be TypeScript); its inferred `meta.type: string` does not narrow to
  // ESLint's RuleType union.
  determinex.rules["no-invokesafe-on-void-command"] as never,
  {
    valid: [
      // Value-returning command: invokeSafe's null is unambiguous there.
      { code: 'invokeSafe("get_status", { cwd })', options: [{ tauriSrc: fixture }] },
      // The write transport is the fix, so it must never be flagged.
      { code: 'invokeWrite("git_commit", { cwd })', options: [{ tauriSrc: fixture }] },
      { code: 'invoke("git_commit", { cwd })', options: [{ tauriSrc: fixture }] },
      // A computed command name cannot be checked statically; reporting it
      // would be a false positive, and false positives get rules turned off.
      { code: "invokeSafe(cmdName, {})", options: [{ tauriSrc: fixture }] },
      { code: "invokeSafe(`${action}_session`, {})", options: [{ tauriSrc: fixture }] },
      // Unknown command: not our business here (commandContract covers it).
      { code: 'invokeSafe("no_such_command", {})', options: [{ tauriSrc: fixture }] },
    ],
    invalid: [
      {
        code: 'invokeSafe("git_commit", { cwd, message })',
        options: [{ tauriSrc: fixture }],
        errors: [{ messageId: "voidViaInvokeSafe", data: { cmd: "git_commit" } }],
      },
      {
        // Generic type argument must not hide the call.
        code: 'await invokeSafe<null>("stage_diff_for_review", { diff })',
        options: [{ tauriSrc: fixture }],
        errors: [{ messageId: "voidViaInvokeSafe" }],
      },
      {
        // No return type at all is the same defect.
        code: 'invokeSafe("fire_and_forget", { id })',
        options: [{ tauriSrc: fixture }],
        errors: [{ messageId: "voidViaInvokeSafe" }],
      },
      {
        // Namespaced call site (api.invokeSafe(...)).
        code: 'api.invokeSafe("pty_write", { id, data })',
        options: [{ tauriSrc: fixture }],
        errors: [{ messageId: "voidViaInvokeSafe" }],
      },
    ],
  }
);
