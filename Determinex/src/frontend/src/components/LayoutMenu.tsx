"use client";
import { useEffect, useRef, useState } from "react";
import { Check, LayoutGrid, RotateCcw, Save, Trash2 } from "lucide-react";
import { DENSITY_LABELS, type UiDensity } from "@/lib/uiDensity";
import { useSettings } from "@/contexts/SettingsContext";
import {
  captureLayout,
  deleteLayout,
  readLayouts,
  resetLayout,
  restoreLayout,
  type PanelLayout,
} from "@/lib/panelLayouts";

/**
 * Save and restore named panel arrangements.
 *
 * Per-surface widths were already persisted, which covers "Source Control should
 * always be wide". It does not cover "I have a reviewing arrangement and a
 * building arrangement" -- which is what every comparable tool offers and what
 * Ryan asked for twice: "they should be able to be moved or changed or deleted or
 * setup however the user wants."
 *
 * A layout is a snapshot of the localStorage keys the panel hooks already own, so
 * this is not a second source of truth -- a new persisted panel dimension is
 * captured automatically by prefix.
 */
export function LayoutMenu() {
  const { uiDensity, setUiDensity, uiZoom, setUiZoom } = useSettings();
  const [open, setOpen] = useState(false);
  const [layouts, setLayouts] = useState<PanelLayout[]>([]);
  const [naming, setNaming] = useState(false);
  const [name, setName] = useState("");
  const [note, setNote] = useState<string | null>(null);
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (open) setLayouts(readLayouts());
  }, [open]);

  // Click-away and Escape, so this cannot become another thing that traps focus.
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        setNaming(false);
      }
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const save = () => {
    const trimmed = name.trim();
    if (!trimmed) return;
    setLayouts(captureLayout(trimmed));
    setNaming(false);
    setName("");
    setNote(`Saved "${trimmed}".`);
  };

  return (
    <div className="relative h-full" ref={boxRef}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-label="Panel layouts"
        aria-expanded={open}
        data-testid="layout-menu-toggle"
        title="Save or restore a panel arrangement"
        className="flex h-full items-center gap-1.5 border-r border-white/8 px-2.5 text-meta text-gray-500 transition-colors hover:bg-white/[0.04] hover:text-gray-200"
      >
        <LayoutGrid size={10} />
        <span>Layout</span>
      </button>

      {open && (
        <div
          data-testid="layout-menu"
          className="absolute bottom-full left-0 mb-2 w-72 overflow-hidden rounded-xl border border-[var(--dtx-code-border)] bg-[var(--dtx-code-bg)] shadow-2xl"
        >
          <div className="border-b border-[var(--dtx-code-border)] px-3 py-2 text-eyebrow font-black uppercase tracking-widest text-gray-500">
            Panel layouts
          </div>

          {/* Density. The type scale ships at a readable default, and this is how a
              user changes it -- shipped without a picker in the first pass, which
              knip found as an unused DENSITY_LABELS export. A setting with no way
              to reach it is the same defect as a button that does nothing. */}
          <div className="border-b border-[var(--dtx-code-border)] p-2">
            <div className="mb-1.5 text-eyebrow font-black uppercase tracking-widest text-gray-600">
              Text size
            </div>
            <div className="flex gap-1">
              {(Object.keys(DENSITY_LABELS) as UiDensity[]).map((d) => (
                <button
                  key={d}
                  type="button"
                  onClick={() => setUiDensity(d)}
                  data-testid={`density-${d}`}
                  title={DENSITY_LABELS[d].hint}
                  aria-pressed={uiDensity === d}
                  className={`flex-1 rounded border px-2 py-1.5 text-eyebrow font-bold uppercase tracking-widest transition-colors ${
                    uiDensity === d
                      ? "border-[var(--determinex-accent)]/40 bg-[var(--determinex-accent)]/10 text-[var(--determinex-accent)]"
                      : "border-white/10 text-gray-500 hover:bg-white/[0.04] hover:text-gray-200"
                  }`}
                >
                  {DENSITY_LABELS[d].label}
                </button>
              ))}
            </div>
            <div className="mt-1.5 flex items-center gap-1">
              <span className="flex-1 text-eyebrow text-gray-600">
                Zoom {Math.round(uiZoom * 100)}% · Ctrl +/- / 0
              </span>
              <button
                type="button"
                onClick={() => setUiZoom(1)}
                aria-label="Reset zoom to 100%"
                className="rounded border border-white/10 px-2 py-1 text-eyebrow font-bold uppercase tracking-widest text-gray-500 hover:bg-white/[0.04] hover:text-gray-200"
              >
                Reset
              </button>
            </div>
          </div>

          <div className="max-h-56 overflow-y-auto">
            {layouts.length === 0 ? (
              <p className="px-3 py-3 text-label leading-relaxed text-gray-600">
                No saved layouts. Arrange the panels how you want them, then save the arrangement
                here and switch back to it any time.
              </p>
            ) : (
              layouts.map((l) => (
                <div
                  key={l.name}
                  className="flex items-center gap-1 border-b border-[var(--dtx-code-border)]/50 px-2 py-1.5 last:border-0"
                >
                  <button
                    type="button"
                    onClick={() => {
                      restoreLayout(l.name);
                      setNote(`Restored "${l.name}".`);
                    }}
                    data-testid={`layout-restore-${l.name}`}
                    className="flex min-w-0 flex-1 items-center gap-2 rounded px-1.5 py-1 text-left transition-colors hover:bg-white/[0.04]"
                  >
                    <Check size={10} className="shrink-0 text-emerald-400/70" />
                    <span className="min-w-0 flex-1 truncate text-label text-gray-200">
                      {l.name}
                    </span>
                    <span className="shrink-0 text-eyebrow text-gray-600">
                      {l.savedAt.slice(0, 10)}
                    </span>
                  </button>
                  <button
                    type="button"
                    onClick={() => setLayouts(deleteLayout(l.name))}
                    aria-label={`Delete the ${l.name} layout`}
                    title="Delete"
                    className="flex h-6 w-6 shrink-0 items-center justify-center rounded text-gray-600 transition-colors hover:bg-red-500/10 hover:text-red-400"
                  >
                    <Trash2 size={10} />
                  </button>
                </div>
              ))
            )}
          </div>

          {naming ? (
            <div className="flex items-center gap-1.5 border-t border-[var(--dtx-code-border)] p-2">
              <input
                autoFocus
                value={name}
                onChange={(e) => setName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") save();
                }}
                placeholder="Layout name"
                aria-label="Layout name"
                className="min-w-0 flex-1 rounded border border-[var(--dtx-code-border)] bg-black/40 px-2 py-1 text-label text-gray-200 outline-none focus:border-[var(--determinex-accent)]"
              />
              <button
                type="button"
                onClick={save}
                className="rounded border border-[var(--determinex-accent)]/40 px-2 py-1 text-eyebrow font-bold uppercase tracking-widest text-[var(--determinex-accent)] hover:bg-[var(--determinex-accent)]/10"
              >
                Save
              </button>
            </div>
          ) : (
            <div className="flex border-t border-[var(--dtx-code-border)]">
              <button
                type="button"
                onClick={() => setNaming(true)}
                data-testid="layout-save-current"
                className="flex flex-1 items-center justify-center gap-1.5 px-2 py-2 text-eyebrow font-bold uppercase tracking-widest text-gray-400 transition-colors hover:bg-white/[0.04] hover:text-white"
              >
                <Save size={10} /> Save current
              </button>
              <button
                type="button"
                onClick={() => {
                  resetLayout();
                  setLayouts(readLayouts());
                  setNote("Reset to defaults.");
                }}
                title="Clear every panel size back to the built-in defaults"
                className="flex items-center justify-center gap-1.5 border-l border-[var(--dtx-code-border)] px-2.5 py-2 text-eyebrow font-bold uppercase tracking-widest text-gray-500 transition-colors hover:bg-white/[0.04] hover:text-gray-200"
              >
                <RotateCcw size={10} /> Reset
              </button>
            </div>
          )}

          {note && (
            <p className="border-t border-[var(--dtx-code-border)] px-3 py-1.5 text-eyebrow text-emerald-300/80">
              {note}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
