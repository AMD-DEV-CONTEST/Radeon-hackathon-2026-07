import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";

import { describe, expect, it } from "vitest";

/**
 * Every component must take its colours, fonts and sizes from the skin.
 *
 * WHY THIS EXISTS
 * Measured 2026-07-29: 681 literal hex colours across the components, 28 files using the
 * GitHub palette (#0d1117 x97, #30363d x168, #161b22 x55) against 32 using the skin
 * variables. A skin applies its palette as CSS custom properties on the root element, so
 * a literal hex IGNORES ALL 27 SKINS -- picking a theme changed half the app and left the
 * other half alone. Same for a hardcoded font stack: skins define their own.
 *
 * That was invisible because it is not a type error and not a test failure; it only shows
 * up by switching skin and looking. This test is the thing that looks.
 *
 * It is a FLOOR, not a freeze: the counts below are allowances that may be lowered as
 * one-off colours are tokenised, and lowering them is the intended direction. Raising one
 * requires saying so here, in a diff, with a reason.
 */

const SRC = join(process.cwd(), "src");

// Files where a literal colour is the correct thing to write.
const COLOUR_EXEMPT = new Set([
  "theme/skinPacks.ts", // defines the skins themselves
  "app/globals.css", // the token fallbacks
]);

const EXEMPT_DIRS = new Set(["__tests__", "wireframes"]);

// The chrome palette that must never come back: these are the values that made half the
// UI ignore the skin. Zero tolerance, unlike the long tail of one-off accents.
const BANNED_CHROME = ["#0d1117", "#161b22", "#30363d", "#21262d", "#010409", "#8b949e"];

/**
 * Remaining one-off literal colours across all components. Measured 2026-07-29:
 *
 *   681  before any tokenisation
 *   196  after round 1 (chrome + primary semantics, 474 values)
 *   137  after round 2 (surfaces, text ramp, single-use semantics, 59 values)
 *
 * What is left is skin-independent BY DESIGN, and tokenising it would be wrong:
 *
 *   ~96  LoadingThemes/* -- each animation paints ONE specific skin's identity. Pointing
 *        them at the active skin would make every loader look the same and destroy the
 *        reason per-skin loaders exist.
 *   ~13  PolicyBlockOverlay's amber ramp -- eight distinct shades forming a gradient.
 *        Collapsing a ramp onto a single --dtx-warn flattens it into a solid block; a ramp
 *        needs derived ramp tokens, which is a design change, not a substitution.
 *
 * Set to the exact measured number, not a round one above it, so this is a ratchet: it
 * fails on the FIRST new literal rather than after a budget's worth. Lowering it is the
 * intended direction; raising it requires saying so here, with a reason.
 */
const ONE_OFF_ALLOWANCE = 137;

function walk(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      if (EXEMPT_DIRS.has(entry)) continue;
      walk(full, out);
    } else if (/\.(tsx|ts)$/.test(entry)) {
      out.push(full);
    }
  }
  return out;
}

function sources(): { rel: string; text: string }[] {
  return walk(SRC)
    .map((full) => ({
      rel: relative(SRC, full).split("\\").join("/"),
      text: readFileSync(full, "utf8"),
    }))
    .filter((f) => !COLOUR_EXEMPT.has(f.rel));
}

/** Strip comments: a comment naming an old colour is documentation, not styling. */
function codeOnly(text: string): string {
  return text.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/[^\n]*/g, "");
}

describe("skin congruity", () => {
  const files = sources();

  it("finds source files to check", () => {
    // Without this, a broken walk would make every assertion below pass vacuously.
    expect(files.length).toBeGreaterThan(80);
  });

  it("no component reintroduces the GitHub chrome palette", () => {
    const offenders: string[] = [];
    for (const { rel, text } of files) {
      const code = codeOnly(text).toLowerCase();
      const found = BANNED_CHROME.filter((hex) => code.includes(hex));
      if (found.length) offenders.push(`${rel}: ${found.join(", ")}`);
    }
    expect(
      offenders,
      "these hardcode chrome colours, so they ignore the active skin:\n" + offenders.join("\n")
    ).toEqual([]);
  });

  it("no component hardcodes a font stack", () => {
    // Skins define fonts.sans / fonts.mono / fonts.display. A literal "JetBrains Mono"
    // renders the same in every skin, including the ones that deliberately change type.
    const offenders: string[] = [];
    for (const { rel, text } of files) {
      const matches = codeOnly(text).match(/fontFamily:\s*["'][^"']*["']/g) ?? [];
      const bad = matches.filter((m) => !m.includes("var(--"));
      if (bad.length) offenders.push(`${rel}: ${bad.join(" | ")}`);
    }
    expect(offenders, "hardcoded font stacks:\n" + offenders.join("\n")).toEqual([]);
  });

  it("no component sets an arbitrary pixel font size", () => {
    // The type scale is role-named (text-eyebrow/meta/label/body/title/display/hero) and
    // multiplied by --dtx-font-scale, which is what makes the density setting work. A
    // text-[13px] opts out of both.
    const offenders: string[] = [];
    for (const { rel, text } of files) {
      const matches = codeOnly(text).match(/text-\[\d+(?:\.\d+)?px\]/g) ?? [];
      if (matches.length) offenders.push(`${rel}: ${[...new Set(matches)].join(", ")}`);
    }
    expect(
      offenders,
      "arbitrary font sizes bypass the density scale:\n" + offenders.join("\n")
    ).toEqual([]);
  });

  it("the long tail of one-off literal colours does not grow", () => {
    let total = 0;
    const perFile: [string, number][] = [];
    for (const { rel, text } of files) {
      const n = (codeOnly(text).match(/#[0-9a-fA-F]{6}\b/g) ?? []).length;
      if (n) perFile.push([rel, n]);
      total += n;
    }
    const worst = perFile.sort((a, b) => b[1] - a[1]).slice(0, 5);
    expect(
      total,
      `literal hex colours rose to ${total} (allowance ${ONE_OFF_ALLOWANCE}). ` +
        `Worst: ${worst.map(([f, n]) => `${f}=${n}`).join(", ")}. ` +
        "Use a --dtx-* token, or lower/raise this allowance deliberately."
    ).toBeLessThanOrEqual(ONE_OFF_ALLOWANCE);
  });

  it("the exempt list points at files that exist", () => {
    // An exemption for a renamed file silently widens the check.
    for (const rel of COLOUR_EXEMPT) {
      expect(
        () => readFileSync(join(SRC, rel), "utf8"),
        `exempt file missing: ${rel}`
      ).not.toThrow();
    }
  });
});
