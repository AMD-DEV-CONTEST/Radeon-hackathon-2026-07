"use client";
import { useState, useEffect, useRef, useMemo, useCallback } from "react";
import {
  Search,
  X,
  Zap,
  Code2,
  Activity,
  ShieldCheck,
  GitBranch,
  RefreshCcw,
  Terminal,
  Brain,
  FileCode,
  Package,
  GraduationCap,
  Settings,
  Key,
  Cpu,
  Palette,
  Stethoscope,
  FolderOpen,
  LayoutGrid,
  ChevronRight,
} from "lucide-react";

export type PaletteCommand = {
  id: string;
  label: string;
  description?: string;
  category: string;
  icon: typeof Zap;
  shortcut?: string;
  action: () => void;
};

type Props = {
  open: boolean;
  onClose: () => void;
  commands: PaletteCommand[];
};

const CATEGORY_ORDER = ["Navigation", "Models", "Settings", "Actions"];

function highlight(text: string, query: string): React.ReactNode {
  if (!query) return text;
  const idx = text.toLowerCase().indexOf(query.toLowerCase());
  if (idx < 0) return text;
  return (
    <>
      {text.slice(0, idx)}
      <mark className="bg-[var(--determinex-accent)]/25 text-[var(--determinex-accent)] rounded-sm">
        {text.slice(idx, idx + query.length)}
      </mark>
      {text.slice(idx + query.length)}
    </>
  );
}

export function CommandPalette({ open, onClose, commands }: Props) {
  const [query, setQuery] = useState("");
  const [selectedIdx, setSelectedIdx] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const filtered = useMemo(() => {
    const q = query.toLowerCase().trim();
    if (!q) return commands;
    return commands.filter(
      (c) =>
        c.label.toLowerCase().includes(q) ||
        (c.description ?? "").toLowerCase().includes(q) ||
        c.category.toLowerCase().includes(q)
    );
  }, [query, commands]);

  // Group by category in CATEGORY_ORDER then alphabetical for unknown
  const grouped = useMemo(() => {
    const map = new Map<string, PaletteCommand[]>();
    for (const cmd of filtered) {
      const arr = map.get(cmd.category) ?? [];
      arr.push(cmd);
      map.set(cmd.category, arr);
    }
    const result: { category: string; items: PaletteCommand[]; startIdx: number }[] = [];
    let idx = 0;
    const ordered = [
      ...CATEGORY_ORDER.filter((c) => map.has(c)),
      ...[...map.keys()].filter((c) => !CATEGORY_ORDER.includes(c)).sort(),
    ];
    for (const cat of ordered) {
      const items = map.get(cat)!;
      result.push({ category: cat, items, startIdx: idx });
      idx += items.length;
    }
    return result;
  }, [filtered]);

  const flatItems = useMemo(() => grouped.flatMap((g) => g.items), [grouped]);

  useEffect(() => {
    if (open) {
      setQuery("");
      setSelectedIdx(0);
      setTimeout(() => inputRef.current?.focus(), 40);
    }
  }, [open]);

  useEffect(() => {
    setSelectedIdx(0);
  }, [query]);

  const execute = useCallback(
    (idx: number) => {
      const cmd = flatItems[idx];
      if (!cmd) return;
      cmd.action();
      onClose();
    },
    [flatItems, onClose]
  );

  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose();
        return;
      }
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setSelectedIdx((i) => Math.min(flatItems.length - 1, i + 1));
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setSelectedIdx((i) => Math.max(0, i - 1));
      }
      if (e.key === "Enter") {
        e.preventDefault();
        execute(selectedIdx);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open, flatItems.length, selectedIdx, execute, onClose]);

  // Scroll selected item into view
  useEffect(() => {
    const el = listRef.current?.querySelector(`[data-idx="${selectedIdx}"]`);
    el?.scrollIntoView({ block: "nearest" });
  }, [selectedIdx]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[300] flex items-start justify-center pt-[15vh] pointer-events-none">
      {/* Backdrop */}
      <div
        className="absolute inset-0 pointer-events-auto"
        style={{ background: "rgba(0,0,0,0.6)", backdropFilter: "blur(4px)" }}
        onClick={onClose}
      />

      {/* Palette */}
      <div
        className="pointer-events-auto relative w-[520px] max-w-[95vw] rounded-2xl border overflow-hidden shadow-2xl"
        style={{
          background: "rgba(8,8,18,0.98)",
          borderColor: "var(--determinex-border)",
          boxShadow:
            "0 0 0 1px rgba(255,255,255,0.05), 0 40px 80px -12px rgba(0,0,0,0.9), 0 0 60px -10px var(--determinex-accent-glow)",
        }}
      >
        {/* Search input */}
        <div
          className="flex items-center gap-3 border-b px-4"
          style={{ borderColor: "var(--determinex-border)" }}
        >
          <Search size={14} className="shrink-0 text-gray-600" />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Type a command or search..."
            className="flex-1 bg-transparent py-3.5 text-body text-white/85 placeholder:text-gray-700 outline-none font-mono"
          />
          {query && (
            <button
              onClick={() => setQuery("")}
              className="text-gray-600 hover:text-gray-400 transition-colors"
            >
              <X size={13} />
            </button>
          )}
          <kbd className="shrink-0 rounded border border-white/10 bg-white/[0.04] px-1.5 py-0.5 text-meta font-mono text-gray-600">
            ESC
          </kbd>
        </div>

        {/* Results */}
        <div ref={listRef} className="max-h-[360px] overflow-y-auto no-scrollbar py-2">
          {grouped.length === 0 ? (
            <div className="flex flex-col items-center gap-2 py-10 text-center">
              <Search size={20} className="text-gray-700" />
              <p className="text-label text-gray-600">No commands match &ldquo;{query}&rdquo;</p>
            </div>
          ) : (
            grouped.map(({ category, items, startIdx }) => (
              <div key={category} className="mb-1">
                <div className="px-4 pb-1 pt-2 text-eyebrow uppercase font-black tracking-widest text-gray-700">
                  {category}
                </div>
                {items.map((cmd, i) => {
                  const absIdx = startIdx + i;
                  const CmdIcon = cmd.icon;
                  const isSelected = absIdx === selectedIdx;
                  return (
                    <button
                      key={cmd.id}
                      data-idx={absIdx}
                      onClick={() => execute(absIdx)}
                      onMouseEnter={() => setSelectedIdx(absIdx)}
                      className={`flex w-full items-center gap-3 px-4 py-2.5 text-left transition-all ${
                        isSelected
                          ? "bg-[var(--determinex-accent)]/10 text-white"
                          : "text-gray-400 hover:bg-white/[0.03]"
                      }`}
                    >
                      <div
                        className={`h-7 w-7 shrink-0 rounded-lg flex items-center justify-center border ${
                          isSelected
                            ? "border-[var(--determinex-accent)]/30 bg-[var(--determinex-accent)]/15"
                            : "border-white/5 bg-white/[0.03]"
                        }`}
                      >
                        <CmdIcon
                          size={13}
                          className={
                            isSelected ? "text-[var(--determinex-accent)]" : "text-gray-600"
                          }
                        />
                      </div>
                      <div className="flex-1 min-w-0">
                        <div
                          className={`text-label font-semibold ${isSelected ? "text-white/90" : "text-gray-400"}`}
                        >
                          {highlight(cmd.label, query)}
                        </div>
                        {cmd.description && (
                          <div className="text-meta text-gray-700 mt-0.5 truncate">
                            {cmd.description}
                          </div>
                        )}
                      </div>
                      {cmd.shortcut && (
                        <kbd className="shrink-0 rounded border border-white/8 bg-white/[0.04] px-1.5 py-0.5 text-meta font-mono text-gray-600">
                          {cmd.shortcut}
                        </kbd>
                      )}
                      {isSelected && (
                        <ChevronRight
                          size={12}
                          className="shrink-0 text-[var(--determinex-accent)]/50"
                        />
                      )}
                    </button>
                  );
                })}
              </div>
            ))
          )}
        </div>

        {/* Footer hint */}
        <div
          className="border-t px-4 py-2 flex items-center gap-3 text-meta text-gray-700"
          style={{ borderColor: "var(--determinex-border)" }}
        >
          <span>
            <kbd className="font-mono border border-white/8 rounded px-1">&#8593;&#8595;</kbd>{" "}
            Navigate
          </span>
          <span>
            <kbd className="font-mono border border-white/8 rounded px-1">Enter</kbd> Open
          </span>
          <span>
            <kbd className="font-mono border border-white/8 rounded px-1">Esc</kbd> Close
          </span>
          <span className="ml-auto">{flatItems.length} commands</span>
        </div>
      </div>
    </div>
  );
}
