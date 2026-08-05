"use client";
import { useState } from "react";
import { ChevronDown, ChevronRight, PanelLeft, PanelRight, X } from "lucide-react";
import type { SurfaceGroup, SurfaceMember } from "@/lib/surfaceGroups";

/**
 * The expandable panel behind each of the nine rail icons.
 *
 * Ryan, live 2026-07-27: "lets take the subs to those nine in an expandable
 * side window that comes out when you click on it ... when you click on them,
 * it brings out what they are, what they do, etc. and you can choose to move it
 * to the other two main boxes on the screen."
 *
 * Three things this fixes about the old rail:
 *   1. It names the surfaces instead of showing 18 unlabelled icons and three
 *      overlapping menus.
 *   2. It explains a panel BEFORE you spend screen space on it. Every member
 *      carries `what` it is and `does` for you (enforced by
 *      surfaceGroups.test.ts), so nothing here is an unexplained icon.
 *   3. The destination is the user's choice, not hard-coded by the entry point.
 *      The old rail decided for you: some ids swapped the left workspace,
 *      others opened a floating dock, and the same panel could do either
 *      depending on which of the four menus you happened to use.
 */

export type SurfaceDestination = "panel" | "dock";

interface Props {
  group: SurfaceGroup;
  /** Currently-open surface id, if any, so the drawer can mark it. */
  activeSurfaceId?: string | null;
  onOpen: (member: SurfaceMember, destination: SurfaceDestination) => void;
  onClose: () => void;
  /** Hides Determinex's own release tooling in shipped end-user builds. */
  showInternal?: boolean;
}

function MemberRow({
  member,
  active,
  onOpen,
}: {
  member: SurfaceMember;
  active: boolean;
  onOpen: (m: SurfaceMember, d: SurfaceDestination) => void;
}) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div
      data-testid={`surface-member-${member.id}`}
      className={`overflow-hidden rounded-lg border transition-colors ${
        active
          ? "border-[var(--determinex-accent)]/40 bg-[var(--determinex-accent)]/8"
          : "border-white/8 bg-white/[0.02] hover:border-white/15"
      }`}
    >
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
        className="flex w-full items-center gap-2 px-3 py-2 text-left"
      >
        {expanded ? (
          <ChevronDown size={11} className="shrink-0 text-gray-600" />
        ) : (
          <ChevronRight size={11} className="shrink-0 text-gray-600" />
        )}
        <span
          className={`flex-1 text-label font-bold ${active ? "text-[var(--determinex-accent)]" : "text-white/80"}`}
        >
          {member.label}
        </span>
        {active && (
          <span className="shrink-0 text-eyebrow font-black uppercase tracking-widest text-[var(--determinex-accent)]">
            Open
          </span>
        )}
      </button>

      {expanded && (
        <div className="space-y-2.5 border-t border-white/5 px-3 py-2.5">
          <p className="text-label leading-relaxed text-gray-400">{member.what}</p>
          <p className="text-label leading-relaxed text-gray-500">{member.does}</p>

          {/* A modal surface has no destination to choose -- offering PANEL and
              DOCK for something that opens a dialog is a meaningless choice, and
              the buttons did nothing for these three. One honest action instead. */}
          {member.kind === "modal" ? (
            <div className="pt-0.5">
              <button
                type="button"
                onClick={() => onOpen(member, "panel")}
                data-testid={`surface-open-${member.id}`}
                className="flex w-full items-center justify-center gap-1.5 rounded-md border border-[var(--determinex-accent)]/30 bg-[var(--determinex-accent)]/10 px-2 py-1.5 text-eyebrow font-bold uppercase tracking-widest text-[var(--determinex-accent)] transition-colors hover:bg-[var(--determinex-accent)]/20"
              >
                Open
              </button>
            </div>
          ) : (
            /* Ryan's "you can choose to move it to the other two main boxes" --
             the same surface, two destinations, decided here rather than by
             whichever menu you came from. */
            <div className="flex gap-1.5 pt-0.5">
              <button
                type="button"
                onClick={() => onOpen(member, "panel")}
                data-testid={`surface-open-${member.id}-panel`}
                title="Open in the left workspace panel"
                className="flex flex-1 items-center justify-center gap-1.5 rounded-md border border-white/10 bg-white/[0.03] px-2 py-1.5 text-eyebrow font-bold uppercase tracking-widest text-gray-300 transition-colors hover:border-white/20 hover:bg-white/[0.07]"
              >
                <PanelLeft size={10} /> Panel
              </button>
              <button
                type="button"
                onClick={() => onOpen(member, "dock")}
                data-testid={`surface-open-${member.id}-dock`}
                title="Open in the movable dock over the main area"
                className="flex flex-1 items-center justify-center gap-1.5 rounded-md border border-[var(--determinex-accent)]/30 bg-[var(--determinex-accent)]/10 px-2 py-1.5 text-eyebrow font-bold uppercase tracking-widest text-[var(--determinex-accent)] transition-colors hover:bg-[var(--determinex-accent)]/20"
              >
                <PanelRight size={10} /> Dock
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function SurfaceDrawer({
  group,
  activeSurfaceId,
  onOpen,
  onClose,
  showInternal = false,
}: Props) {
  const members = group.members.filter((m) => showInternal || !m.internalOnly);

  return (
    <div
      data-testid="surface-drawer"
      className="flex h-full w-[248px] shrink-0 flex-col border-r border-white/8 bg-[var(--dtx-code-bg)]"
    >
      <div className="flex items-start gap-2 border-b border-white/8 px-3 py-3">
        <div className="min-w-0 flex-1">
          <div className="text-meta font-black uppercase tracking-widest text-white/85">
            {group.label}
          </div>
          <p className="mt-0.5 text-meta leading-relaxed text-gray-600">{group.blurb}</p>
        </div>
        <button
          type="button"
          onClick={onClose}
          title="Close"
          data-testid="surface-drawer-close"
          aria-label={`Close the ${group.label} drawer`}
          /* Was a bare 12x12 glyph -- under WCAG 2.2 AA's 24px floor and hard to
             hit. Padded, not enlarged. */
          className="-m-1 flex h-6 w-6 shrink-0 items-center justify-center rounded text-gray-600 transition-colors hover:bg-white/5 hover:text-gray-300"
        >
          <X size={12} />
        </button>
      </div>

      {/* Scrollbar deliberately visible. Three menus in this app hid theirs and
          silently swallowed their own tails -- that is how Review and Merge
          became unreachable. */}
      {/* Members render under their `section` heading when the group declares any. The
          System drawer holds ten surfaces since the tool-introspection ones were folded in,
          and ten in a flat list is the clutter moved rather than removed -- headings are why
          one rail icon can hold them without becoming the next dumping ground. Groups with
          no sections render exactly as before. */}
      <div className="flex-1 space-y-1.5 overflow-y-auto p-2">
        {members.some((m) => m.section)
          ? [...new Map(members.map((m) => [m.section ?? "", true])).keys()].map((section) => (
              <div key={section} className="space-y-1.5">
                <div className="px-1 pb-0.5 pt-2 text-eyebrow font-black uppercase tracking-widest text-gray-600">
                  {section}
                </div>
                {members
                  .filter((m) => (m.section ?? "") === section)
                  .map((m) => (
                    <MemberRow
                      key={m.id}
                      member={m}
                      active={activeSurfaceId === m.id}
                      onOpen={onOpen}
                    />
                  ))}
              </div>
            ))
          : members.map((m) => (
              <MemberRow key={m.id} member={m} active={activeSurfaceId === m.id} onOpen={onOpen} />
            ))}
      </div>
    </div>
  );
}
