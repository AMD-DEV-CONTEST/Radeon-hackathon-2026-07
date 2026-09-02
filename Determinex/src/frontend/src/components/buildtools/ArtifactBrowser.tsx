"use client";
import { useEffect, useState, useCallback } from "react";
import { Folder, Archive, RefreshCw, Loader2 } from "lucide-react";
import { invokeSafe, isTauri } from "@/lib/api";

type ArtifactEntry = {
  name: string;
  path: string;
  size_bytes: number;
  file_count: number;
  modified: string | null;
};

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let val = bytes / 1024;
  let i = 0;
  while (val >= 1024 && i < units.length - 1) {
    val /= 1024;
    i += 1;
  }
  return `${val.toFixed(1)} ${units[i]}`;
}

export function ArtifactBrowser() {
  const [entries, setEntries] = useState<ArtifactEntry[] | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    const workspacePath =
      typeof window !== "undefined" ? window.localStorage.getItem("explorerRoot") || "" : "";
    const result = await invokeSafe<ArtifactEntry[]>("get_build_artifacts", { workspacePath });
    setEntries(result ?? []);
    setLoading(false);
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const totalBytes = (entries ?? []).reduce((sum, e) => sum + e.size_bytes, 0);

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <div
        className="shrink-0 flex items-center gap-3 border-b px-4 py-2.5"
        style={{ borderColor: "var(--determinex-border)", background: "rgba(0,0,0,0.2)" }}
      >
        <Archive size={12} className="text-gray-600" />
        <span className="text-eyebrow uppercase font-black tracking-widest text-gray-600">
          Build Artifacts
        </span>
        {entries && entries.length > 0 && (
          <span className="ml-auto text-meta font-mono text-gray-700">
            {formatBytes(totalBytes)} total
          </span>
        )}
        <button
          onClick={() => void refresh()}
          className={`text-gray-600 hover:text-gray-400 transition-colors ${loading ? "animate-spin text-cyan-400" : ""}`}
          title="Rescan real build-output directories"
        >
          <RefreshCw size={13} />
        </button>
      </div>

      {!isTauri() && (
        <div className="shrink-0 px-4 pt-2 text-meta text-amber-500/70 italic">
          Browser mode cannot scan real build-output directories.
        </div>
      )}

      <div className="flex-1 overflow-y-auto no-scrollbar py-2">
        {loading && entries === null ? (
          <div className="flex h-full items-center justify-center">
            <Loader2 size={18} className="animate-spin text-gray-600" />
          </div>
        ) : entries && entries.length > 0 ? (
          entries.map((e) => (
            <div
              key={e.path}
              className="flex items-center gap-2 px-4 py-2 hover:bg-white/[0.02] transition-colors"
              title={e.path}
            >
              <Folder size={12} className="text-amber-500/60 shrink-0" />
              <span className="text-label font-mono text-gray-400 flex-1 truncate">{e.name}</span>
              <span className="text-meta font-mono text-gray-600">
                {e.file_count.toLocaleString()} files
              </span>
              <span className="text-meta font-mono text-gray-600">{formatBytes(e.size_bytes)}</span>
              {e.modified && <span className="text-meta text-gray-700">{e.modified}</span>}
            </div>
          ))
        ) : (
          <div className="flex h-full min-h-[180px] flex-col items-center justify-center gap-1 opacity-40 px-6 text-center">
            <p className="text-label text-gray-500">
              No build output yet. Run a build from Work and its compiled artifacts show up here.
            </p>
            <p className="max-w-[320px] text-meta text-gray-700">
              Run a real build (cargo build, npm run build) to populate target/, .next/, or dist/.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
