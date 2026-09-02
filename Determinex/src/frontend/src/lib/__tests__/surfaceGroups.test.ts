import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { SURFACE_GROUPS, GROUP_BY_SURFACE, allSurfaceIds } from "../surfaceGroups";

/**
 * The taxonomy is only worth anything if it stays exhaustive. The mess it
 * replaced grew because panels were added to a type union and then wired into
 * whichever of four overlapping menus the author happened to remember -- so
 * Review and Merge ended up reachable from none of them.
 *
 * These tests read the REAL type unions out of page.tsx instead of a
 * hand-copied list, so adding a panel without giving it a home fails here
 * rather than silently producing another orphan.
 */
const PAGE_RAW = readFileSync(resolve(__dirname, "../../app/page.tsx"), "utf8");

/**
 * page.tsx with comments stripped.
 *
 * These parsers read declarations as TEXT, which makes them fragile to prose in a way that
 * is easy to miss. Documenting the removal of an addon inside the union block broke this
 * three separate times in one sitting:
 *
 *   1. the comment named the removed member in double quotes, so the member regex put it
 *      straight back into the parsed list;
 *   2. the rewrite used the word describing the hazard, in double quotes, and was itself
 *      parsed as a member;
 *   3. the next rewrite contained a semicolon, and the lazy `[\s\S]*?;` terminated the
 *      union block early -- 13 members parsed out of 21, so most of the union silently
 *      vanished from the check.
 *
 * Contorting comments to please a regex is the wrong end to fix. Comments are stripped
 * before any parsing, so prose can say whatever it needs to.
 */
const PAGE = PAGE_RAW.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/[^\n]*/g, "");

function unionMembers(typeName: string): string[] {
  // e.g.  type WorkspaceAddon =\n  | "terminal"\n  | "editor" ... ;
  const re = new RegExp(`type\\s+${typeName}\\s*=([\\s\\S]*?);`, "m");
  const block = PAGE.match(re);
  if (!block) throw new Error(`could not find type ${typeName} in page.tsx`);
  const members = [...block[1].matchAll(/"([a-z0-9-]+)"/g)].map((m) => m[1]);
  // A truncated parse is worse than a failed one: it silently shrinks the set every check
  // below iterates over. WorkspaceAddon has ~21 members and PrimaryWorkspace ~10.
  if (members.length < 8) {
    throw new Error(
      `type ${typeName} parsed to only ${members.length} members -- the declaration regex ` +
        `is truncating (a semicolon in a comment will do it)`
    );
  }
  return members;
}

/**
 * The ids that actually have a PANEL in page.tsx's `addonItems` registry.
 *
 * WHY THIS EXISTS, AND WHY THE UNION IS NOT ENOUGH
 * "never offers a surface that cannot open" below was written for precisely the bug its
 * own comment describes -- a taxonomy entry pointing at an addon with nothing to render.
 * But it checked membership of the WorkspaceAddon TYPE UNION, and a type union is just a
 * list of allowed strings: adding `| "idea"` satisfies it while no panel exists.
 *
 * Measured 2026-07-29: `idea` ("Idea Lab") was advertised in the taxonomy, present in the
 * union, absent from `addonItems` -- so `selectedAddon` resolved to null, the dock render
 * is guarded by `addonDockOpen && selectedAddon`, and clicking the menu item did
 * NOTHING. The guard written to prevent exactly that passed the whole time, because it
 * never looked at panels.
 *
 * This reads the registry entries instead: an id only counts when something renders it.
 */
function registryAddonIds(): string[] {
  const start = PAGE.indexOf("const addonItems");
  if (start < 0) throw new Error("could not find addonItems in page.tsx");
  // The registry is a top-level array literal; `panel:` appears once per entry, so pair
  // each id with the panel that follows it and keep only ids that have one.
  const tail = PAGE.slice(start);
  const ids: string[] = [];
  const entry = /id:\s*"([a-z0-9-]+)"[\s\S]*?panel:/g;
  let m: RegExpExecArray | null;
  while ((m = entry.exec(tail)) !== null) {
    ids.push(m[1]);
    // Stop runaway matching across the whole file if the registry ends.
    if (ids.length > 100) break;
  }
  if (ids.length < 15) {
    throw new Error(`addonItems parse found only ${ids.length} panels -- regex is broken`);
  }
  return ids;
}

describe("surface taxonomy", () => {
  it("has exactly eight groups", () => {
    // Was nine. `learn` was dissolved into `system` 2026-08-04: Learning Studio, Brain
    // and Guide are all about Determinex rather than about your code, and Ryan -- seeing
    // that 76% of the IDE's controls were the tool inspecting itself -- said they "should
    // all be in the systems tab ... NOT in the surfaces for the user".
    expect(SURFACE_GROUPS).toHaveLength(8);
  });

  it("gives every surface exactly one home", () => {
    const ids = allSurfaceIds();
    const dupes = ids.filter((id, i) => ids.indexOf(id) !== i);
    expect(dupes, `surfaces listed in more than one group: ${dupes.join(", ")}`).toEqual([]);
  });

  it("covers every addon panel declared in page.tsx", () => {
    const declared = unionMembers("WorkspaceAddon");
    expect(declared.length).toBeGreaterThan(20); // sanity: the regex found a real union
    const missing = declared.filter((id) => !GROUP_BY_SURFACE[id]);
    expect(
      missing,
      `addon panels with no group -- add them to surfaceGroups.ts: ${missing.join(", ")}`
    ).toEqual([]);
  });

  it("never offers a surface that cannot open", () => {
    // The REVERSE of the two checks above, and the one that was missing.
    // `skin` sat in the taxonomy pointing at an addon id that was never in
    // `addonItems`, so the drawer advertised a panel, the user clicked it, and
    // nothing could render -- exactly the "list of things that do nothing" this
    // taxonomy replaced. The old checks only ran page.tsx -> taxonomy, so a
    // taxonomy entry with no panel behind it was invisible.
    // Registry, not type union: a union member with no panel renders nothing. See
    // registryAddonIds() for the instance this missed.
    const addons = new Set(registryAddonIds());
    const sidebars = new Set(unionMembers("PrimaryWorkspace"));
    const orphans = SURFACE_GROUPS.flatMap((g) =>
      g.members
        .filter((m) => {
          // A modal surface has no panel by design; what it must have is a
          // declared target, or the shell's handler falls through silently.
          if (m.kind === "modal") return !m.modal;
          return m.kind === "addon" ? !addons.has(m.id) : !sidebars.has(m.id);
        })
        .map((m) => `${m.id} (${m.kind})`)
    );
    expect(orphans, `taxonomy members with no panel behind them: ${orphans.join(", ")}`).toEqual(
      []
    );
  });

  it("covers every primary sidebar declared in page.tsx", () => {
    // "none" is a state, not a surface; "extensions" is covered as Tools.
    const declared = unionMembers("PrimaryWorkspace").filter((id) => id !== "none");
    const missing = declared.filter((id) => !GROUP_BY_SURFACE[id]);
    expect(
      missing,
      `sidebars with no group -- add them to surfaceGroups.ts: ${missing.join(", ")}`
    ).toEqual([]);
  });

  it("explains every member, because the drawer promises to", () => {
    for (const g of SURFACE_GROUPS) {
      for (const m of g.members) {
        expect(m.what.trim().length, `${m.id} missing "what"`).toBeGreaterThan(10);
        expect(m.does.trim().length, `${m.id} missing "does"`).toBeGreaterThan(10);
        expect(m.label.trim()).not.toBe("");
      }
    }
  });

  it("keeps groups small enough to scan", () => {
    for (const g of SURFACE_GROUPS) {
      expect(g.members.length, `${g.id} is empty`).toBeGreaterThan(0);
      // A group that grows past ~6 is a sign it needs splitting, which is how
      // the original rail got to 18 icons.
      //
      // Measured per SECTION, not per group. When the tool-introspection surfaces were
      // folded into `system` it reached ten members and this guard failed -- correctly,
      // because a flat list of ten is the clutter moved rather than removed. The fix was
      // to give that drawer headings, not to raise the number: an unsectioned group is
      // still held to six, and a sectioned one is held to six PER HEADING, which is what
      // "small enough to scan" actually means.
      const sections = new Map<string, number>();
      for (const m of g.members) {
        const key = m.section ?? "";
        sections.set(key, (sections.get(key) ?? 0) + 1);
      }
      for (const [name, count] of sections) {
        expect(
          count,
          `${g.id}${name ? ` section "${name}"` : ""} has too many members`
        ).toBeLessThanOrEqual(6);
      }
      // Every member sectioned, or none of them -- a half-sectioned drawer renders some
      // items under a heading and the rest floating above it.
      const sectioned = g.members.filter((m) => m.section).length;
      expect(
        sectioned === 0 || sectioned === g.members.length,
        `${g.id} mixes sectioned and unsectioned members`
      ).toBe(true);
    }
  });

  it("marks Determinex's own release tooling internal-only", () => {
    // These are about shipping Determinex, not the user's project, and must not
    // appear in an end-user build.
    expect(GROUP_BY_SURFACE["mission"]).toBeDefined();
    const mission = SURFACE_GROUPS.flatMap((g) => g.members).find((m) => m.id === "mission");
    const roadmap = SURFACE_GROUPS.flatMap((g) => g.members).find((m) => m.id === "roadmap");
    expect(mission?.internalOnly).toBe(true);
    expect(roadmap?.internalOnly).toBe(true);
  });
});
