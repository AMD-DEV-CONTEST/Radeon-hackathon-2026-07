import { describe, expect, it } from "vitest";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, resolve } from "node:path";

/**
 * Return-shape contract: a Rust response struct and the TypeScript interface that
 * consumes it must declare the same fields.
 *
 * This is the third and last piece of what `tauri-specta` would generate for us.
 * `commandContract` pins command NAMES, `argContract` pins ARGUMENT names, and
 * nothing pinned RETURN shapes -- so a field renamed on one side only was a
 * silent break, exactly like the seven argument bugs `argContract` found.
 *
 * Why this test instead of specta: `tauri-specta` is at 2.0.0-rc.25. Adopting it
 * means an RC dependency plus replacing `generate_handler!` wholesale across 153
 * commands and deriving `specta::Type` on ~94 structs -- and 36 of those commands
 * return an untyped `serde_json::Value`, which specta emits as `unknown`, so a
 * quarter of the surface would gain no shape safety anyway. Typing the returns is
 * the prerequisite either way; this test makes each one pay off immediately,
 * without an RC crate in a build about to ship.
 *
 * It only covers commands whose Rust side is a real struct. That set is small on
 * purpose and is meant to grow: every `Value` return converted should add a row
 * here.
 */

const TAURI_SRC = resolve(__dirname, "../../../src-tauri/src");

function rustSources(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    const p = join(dir, entry);
    if (statSync(p).isDirectory()) {
      if (entry === "target" || entry === "gen") continue;
      rustSources(p, out);
    } else if (entry.endsWith(".rs")) {
      out.push(p);
    }
  }
  return out;
}

/** Field names of a `pub struct Name { ... }` from the Rust sources. */
function rustStructFields(structName: string): string[] {
  for (const file of rustSources(TAURI_SRC)) {
    const src = readFileSync(file, "utf8");
    const re = new RegExp(`struct\\s+${structName}\\s*\\{([\\s\\S]*?)\\n\\}`, "m");
    const m = re.exec(src);
    if (!m) continue;
    // A `rename_all` changes the WIRE names without changing the field names, so
    // comparing raw field names would be meaningless. The first version of this
    // test refused to compare such a struct at all, which meant the idiomatic
    // serde spelling could not be used -- the test dictating the code. It now
    // applies the same conversion serde does.
    const decl = src.slice(Math.max(0, m.index - 400), m.index);
    const rename = /rename_all\s*=\s*"([a-zA-Z]+)"/.exec(decl)?.[1];
    const fields = [...m[1].matchAll(/^\s*pub\s+([a-z_0-9]+)\s*:/gm)].map((f) => f[1]);
    if (!rename) return fields;
    if (rename !== "camelCase") {
      throw new Error(
        `${structName} uses rename_all = "${rename}", which this test does not ` +
          `know how to convert. Teach it the conversion rather than skipping the struct.`
      );
    }
    return fields.map((f) => f.replace(/_([a-z0-9])/g, (_, c) => c.toUpperCase()));
  }
  throw new Error(`Rust struct ${structName} not found under ${TAURI_SRC}`);
}

/** Field names of an `export interface Name { ... }` in a TS source file. */
function tsInterfaceFields(relPath: string, interfaceName: string): string[] {
  const src = readFileSync(resolve(__dirname, "../..", relPath), "utf8");
  const re = new RegExp(`interface\\s+${interfaceName}\\s*\\{([\\s\\S]*?)\\n\\}`, "m");
  const m = re.exec(src);
  if (!m) throw new Error(`TS interface ${interfaceName} not found in ${relPath}`);
  return [...m[1].matchAll(/^\s*([a-zA-Z_0-9]+)\??\s*:/gm)].map((f) => f[1]);
}

const PAIRS: Array<{
  command: string;
  rustStruct: string;
  tsFile: string;
  tsInterface: string;
  /** Rust fields the TS interface deliberately does not read. */
  allowExtraInRust?: string[];
}> = [
  {
    command: "probe_hardware",
    rustStruct: "HardwareProbeResponse",
    tsFile: "lib/api.ts",
    tsInterface: "HardwareProbe",
  },
  {
    command: "check_docker_status",
    rustStruct: "DockerStatusResponse",
    tsFile: "lib/api.ts",
    tsInterface: "DockerStatus",
  },
  {
    // camelCase on the wire -- exercises the rename_all handling above.
    command: "get_work_readiness",
    rustStruct: "WorkReadinessResponse",
    tsFile: "lib/work-readiness.ts",
    tsInterface: "WorkReadiness",
    // Rust reports per-role detail the TS interface does not declare. Extra data
    // is additive and safe; a field the TS EXPECTS and Rust omits is not.
    allowExtraInRust: ["checks"],
  },
  {
    command: "list_hive_sessions",
    rustStruct: "SessionSummary",
    tsFile: "lib/api.ts",
    tsInterface: "HiveSessionSummary",
  },
  {
    command: "get_role_assignments",
    rustStruct: "RoleAssignments",
    tsFile: "lib/api.ts",
    tsInterface: "RoleAssignments",
  },
];

describe("Rust response structs match the TypeScript interfaces that read them", () => {
  it.each(PAIRS)(
    "$command: $rustStruct <-> $tsInterface",
    ({ rustStruct, tsFile, tsInterface, allowExtraInRust }) => {
      const allowed = new Set(allowExtraInRust ?? []);
      const rust = rustStructFields(rustStruct)
        .filter((f) => !allowed.has(f))
        .sort();
      const ts = tsInterfaceFields(tsFile, tsInterface).sort();

      expect(rust.length, `${rustStruct} parsed as having no fields`).toBeGreaterThan(0);
      expect(ts.length, `${tsInterface} parsed as having no fields`).toBeGreaterThan(0);

      const onlyRust = rust.filter((f) => !ts.includes(f));
      const onlyTs = ts.filter((f) => !rust.includes(f));
      expect(
        { onlyInRust: onlyRust, onlyInTypeScript: onlyTs },
        `${rustStruct} and ${tsInterface} have drifted`
      ).toEqual({ onlyInRust: [], onlyInTypeScript: [] });
    }
  );

  it("catches a field that exists on only one side", () => {
    // Guard for the guard: the comparison above must actually be capable of
    // failing. A matcher that passes on any input is worse than no test, which
    // this repo has already learned once from argContract.
    const rust = ["running", "version", "message"];
    const ts = ["running", "version"];
    const onlyRust = rust.filter((f) => !ts.includes(f));
    expect(onlyRust).toEqual(["message"]);
  });

  it("knows how many commands still return an untyped Value", () => {
    // A visible number, so converting one is recorded and regressing one is
    // noticed. 36 at the start of this work.
    //
    // Counted separately, because they are not the same thing:
    //   BARE `Result<Value, _>`  -- nothing about the response is typed.
    //   `Envelope<Value>`        -- the envelope IS typed; only `data` is
    //                              dynamic, which for model output and external
    //                              script output is the honest shape.
    // The three remaining bare ones each carry a comment saying why a struct
    // there would silently DROP fields from an evidence artifact or a script's
    // superset -- worse than leaving it dynamic.
    let untyped = 0;
    for (const file of rustSources(TAURI_SRC)) {
      const src = readFileSync(file, "utf8");
      for (const m of src.matchAll(
        /#\[tauri::command\][^\n]*\n(?:\s*#[^\n]*\n)*\s*(?:pub\s+)?(?:async\s+)?fn\s+\w+\s*\(/g
      )) {
        // Walk the parameter list, then read to the body brace.
        let i = m.index + m[0].length - 1;
        let depth = 0;
        for (; i < src.length; i++) {
          if (src[i] === "(") depth++;
          else if (src[i] === ")" && --depth === 0) break;
        }
        const brace = src.indexOf("{", i + 1);
        if (brace === -1) continue;
        if (/\b(serde_json::)?Value\b/.test(src.slice(i + 1, brace))) untyped++;
      }
    }
    // Fails if it GROWS, so a new command cannot quietly add to the backlog.
    // 36 -> 8 in this pass (3 bare + 5 typed-envelope-with-dynamic-data).
    //
    // 8 -> 12 (2026-08-03): the four onboarding commands in ipc_hive/onboarding.rs
    // (provider_setup_report / _verify, user_profile_get / _set). Each returns
    // `Envelope<Value>` carrying verbatim stdout from a Python helper -- which is the shape
    // the note above already calls honest for script output. A Rust struct here would be a
    // THIRD definition of a schema that already exists in Python and in TypeScript
    // (ProviderSetupReport, ReaderPrescreen), and serde would silently drop any field the
    // Rust copy had not been taught -- the exact harm the bare-Value note warns about.
    expect(untyped).toBeLessThanOrEqual(12);
  });
});
