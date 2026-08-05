"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import { Search, CaseSensitive, Copy, Check, FileText, Loader2 } from "lucide-react";
import { findInFiles, isTauri, type FileSearchHit } from "@/lib/api";

type Props = {
  workspacePath?: string;
};

type GroupedHits = { file: string; short: string; hits: FileSearchHit[] };

const DEBOUNCE_MS = 250;

function shortName(path: string): string {
  const parts = path.split(/[\\/]/);
  return parts[parts.length - 1] || path;
}

function groupByFile(hits: FileSearchHit[]): GroupedHits[] {
  const map = new Map<string, FileSearchHit[]>();
  for (const hit of hits) {
    const bucket = map.get(hit.file);
    if (bucket) bucket.push(hit);
    else map.set(hit.file, [hit]);
  }
  return Array.from(map.entries()).map(([file, fileHits]) => ({
    file,
    short: shortName(file),
    hits: fileHits,
  }));
}

export function FileSearchPanel({ workspacePath = "C:\\Dev\\Determinex" }: Props) {
  const [query, setQuery] = useState("");
  const [caseSensitive, setCaseSensitive] = useState(false);
  const [hits, setHits] = useState<FileSearchHit[]>([]);
  const [truncated, setTruncated] = useState(false);
  const [searching, setSearching] = useState(false);
  const [searchedFor, setSearchedFor] = useState<string | null>(null);
  const [copiedKey, setCopiedKey] = useState<string | null>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const requestIdRef = useRef(0);
  const tauriMode = isTauri();

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);

    const trimmed = query.trim();
    if (!trimmed) {
      setHits([]);
      setTruncated(false);
      setSearching(false);
      setSearchedFor(null);
      return;
    }

    setSearching(true);
    debounceRef.current = setTimeout(async () => {
      const myId = ++requestIdRef.current;
      const result = await findInFiles(workspacePath, trimmed, caseSensitive);
      if (myId !== requestIdRef.current) return; // stale response, a newer query superseded it
      setHits(result.hits);
      setTruncated(result.truncated);
      setSearchedFor(trimmed);
      setSearching(false);
    }, DEBOUNCE_MS);

    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query, caseSensitive, workspacePath]);

  const grouped = useMemo(() => groupByFile(hits), [hits]);

  const copy = (key: string, text: string) => {
    void navigator.clipboard.writeText(text);
    setCopiedKey(key);
    setTimeout(() => setCopiedKey((k) => (k === key ? null : k)), 1200);
  };

  return (
    <div
      className="flex h-full min-h-0 flex-col overflow-hidden"
      style={{ background: "var(--dtx-code-bg-deep)" }}
    >
      <div className="flex shrink-0 flex-col gap-2 border-b border-white/8 bg-black/60 px-4 py-3">
        <div className="flex items-center gap-2">
          <Search size={13} className="shrink-0 text-gray-500" />
          <input
            autoFocus
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Find in files (literal text, not regex)…"
            className="w-full bg-transparent text-xs text-gray-200 outline-none placeholder:text-gray-600"
          />
          {searching && <Loader2 size={12} className="shrink-0 animate-spin text-gray-500" />}
        </div>
        <div className="flex items-center justify-between">
          <button
            type="button"
            onClick={() => setCaseSensitive((v) => !v)}
            title="Match case"
            className={`flex items-center gap-1 rounded-md border px-2 py-1 text-meta font-bold transition ${
              caseSensitive
                ? "border-emerald-400/40 bg-emerald-500/10 text-emerald-300"
                : "border-white/8 bg-white/[0.03] text-gray-500 hover:text-gray-300"
            }`}
          >
            <CaseSensitive size={11} />
            Match Case
          </button>
          <span className="text-meta font-mono text-gray-600">
            {searchedFor && !searching
              ? `${hits.length} match${hits.length === 1 ? "" : "es"} in ${grouped.length} file${grouped.length === 1 ? "" : "s"}`
              : workspacePath}
          </span>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-2">
        {!tauriMode && (
          <div className="p-4 text-center text-label text-gray-500">
            Real workspace search requires the desktop runtime.
          </div>
        )}

        {tauriMode && !query.trim() && (
          <div className="p-4 text-center text-label text-gray-600">
            Type to search every tracked, non-secret file under {workspacePath}.
          </div>
        )}

        {tauriMode && query.trim() && !searching && searchedFor && hits.length === 0 && (
          <div className="p-4 text-center text-label text-gray-600">
            No matches for &quot;{searchedFor}&quot;.
          </div>
        )}

        {truncated && (
          <div className="mb-2 rounded border border-amber-400/20 bg-amber-500/10 px-2 py-1 text-meta text-amber-300">
            Result cap reached — narrow your query for a complete list.
          </div>
        )}

        {grouped.map((group) => (
          <div key={group.file} className="mb-2">
            <div className="flex items-center gap-1.5 px-1 py-1 text-label font-bold text-gray-400">
              <FileText size={11} className="shrink-0 text-gray-600" />
              <span className="truncate" title={group.file}>
                {group.short}
              </span>
              <span className="text-gray-700">— {group.hits.length}</span>
            </div>
            {group.hits.map((hit) => {
              const key = `${hit.file}:${hit.line_number}`;
              return (
                <div
                  key={key}
                  className="group flex items-start gap-2 rounded px-2 py-1 pl-6 text-label hover:bg-white/[0.03]"
                >
                  <span className="shrink-0 select-none font-mono text-gray-600">
                    {hit.line_number}
                  </span>
                  <span
                    className="min-w-0 flex-1 truncate font-mono text-gray-300"
                    title={hit.line}
                  >
                    {hit.line}
                  </span>
                  <button
                    type="button"
                    onClick={() => copy(key, `${hit.file}:${hit.line_number}`)}
                    title="Copy file:line"
                    className="shrink-0 text-gray-600 opacity-0 transition hover:text-emerald-300 group-hover:opacity-100"
                  >
                    {copiedKey === key ? (
                      <Check size={11} className="text-emerald-400" />
                    ) : (
                      <Copy size={11} />
                    )}
                  </button>
                </div>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}
