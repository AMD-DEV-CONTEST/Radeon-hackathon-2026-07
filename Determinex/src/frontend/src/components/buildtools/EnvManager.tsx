"use client";
import { useCallback, useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { Eye, EyeOff, AlertTriangle, Copy, Check, RefreshCw, ShieldAlert } from "lucide-react";
import { isTauri } from "@/lib/api";

/**
 * Real `.env` viewer for the open workspace.
 *
 * This panel used to be a shell: an empty in-memory array with a local add/
 * delete that vanished on remount -- honestly labelled, but useless. It now
 * reads the workspace's actual `.env`.
 *
 * Constraints, from the rules that actually matter (see
 * src-tauri/src/env_manager.rs): the listing is MASKED and the backend never
 * returns whole values in bulk; a value is fetched one key at a time, only on
 * an explicit reveal; and it is read-only, because writing `.env` risks
 * destroying working credentials and nothing here needs it.
 *
 * The dev/staging/prod switcher is gone. There is one `.env`; three tabs over
 * one file implied an environment system that does not exist.
 */

type EnvEntry = { key: string; preview: string; length: number; looksSecret: boolean };

export function EnvManager({ workspacePath = "" }: { workspacePath?: string }) {
  const [entries, setEntries] = useState<EnvEntry[]>([]);
  const [revealed, setRevealed] = useState<Record<string, string>>({});
  const [copied, setCopied] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);

  const load = useCallback(async () => {
    if (!workspacePath || !isTauri()) return;
    setLoading(true);
    setError(null);
    try {
      const rows = await invoke<EnvEntry[]>("list_env_vars", { workspace: workspacePath });
      setEntries(rows);
      // Never carry a revealed value across a reload.
      setRevealed({});
      setLoaded(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [workspacePath]);

  useEffect(() => {
    load();
  }, [load]);

  const toggleReveal = async (key: string) => {
    if (revealed[key] !== undefined) {
      setRevealed(({ [key]: _drop, ...rest }) => rest);
      return;
    }
    try {
      const value = await invoke<string>("reveal_env_var", { workspace: workspacePath, key });
      setRevealed((r) => ({ ...r, [key]: value }));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const copy = async (key: string) => {
    try {
      // Fetch on demand rather than requiring the value be on screen first:
      // copying should not force the user to expose a secret to the room just
      // to paste it somewhere.
      const value =
        revealed[key] ??
        (await invoke<string>("reveal_env_var", { workspace: workspacePath, key }));
      await navigator.clipboard.writeText(value);
      setCopied(key);
      setTimeout(() => setCopied(null), 1500);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const secretCount = entries.filter((e) => e.looksSecret).length;

  if (!isTauri()) {
    return (
      <div className="flex h-full items-center justify-center p-6">
        <p className="text-center text-label text-gray-600">
          Reading .env needs the desktop runtime.
        </p>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <div className="flex shrink-0 items-center gap-2 border-b border-white/8 px-4 py-2.5">
        <span className="text-meta font-black uppercase tracking-widest text-gray-400">.env</span>
        <span className="font-mono text-meta text-gray-600">
          {entries.length} variable{entries.length === 1 ? "" : "s"}
          {secretCount > 0 && ` · ${secretCount} credential-shaped`}
        </span>
        <div className="flex-1" />
        <button
          onClick={load}
          disabled={loading}
          title="Reload from disk"
          data-testid="env-reload"
          className="rounded p-1 text-gray-500 transition-colors hover:text-gray-200 disabled:opacity-40"
        >
          <RefreshCw size={11} className={loading ? "animate-spin" : ""} />
        </button>
      </div>

      {error && (
        <div className="flex shrink-0 items-start gap-2 border-b border-red-500/25 bg-red-950/20 px-4 py-2">
          <AlertTriangle size={11} className="mt-0.5 shrink-0 text-red-400" />
          <p className="font-mono text-label leading-relaxed text-red-300">{error}</p>
        </div>
      )}

      <div className="flex-1 overflow-y-auto p-2">
        {!workspacePath ? (
          <p className="p-4 text-label text-gray-600">Open a workspace to read its .env.</p>
        ) : entries.length === 0 ? (
          <p className="p-4 text-label text-gray-600">
            {loaded ? "No .env in this workspace, or it has no variables." : "Reading .env…"}
          </p>
        ) : (
          <div className="space-y-1">
            {entries.map((e) => {
              const shown = revealed[e.key];
              return (
                <div
                  key={e.key}
                  data-testid={`env-row-${e.key}`}
                  className="flex items-center gap-2 rounded-lg border border-white/8 bg-white/[0.02] px-3 py-2"
                >
                  {e.looksSecret && (
                    <ShieldAlert size={11} className="shrink-0 text-amber-400/80" />
                  )}
                  <span className="w-52 shrink-0 truncate font-mono text-label font-bold text-white/80">
                    {e.key}
                  </span>
                  <code className="flex-1 truncate font-mono text-label text-gray-500">
                    {shown ?? e.preview}
                  </code>
                  <span className="shrink-0 font-mono text-meta text-gray-700">{e.length}</span>
                  <button
                    onClick={() => toggleReveal(e.key)}
                    title={shown ? "Hide" : "Reveal this value"}
                    aria-label={shown ? `Hide ${e.key}` : `Reveal ${e.key}`}
                    className="shrink-0 text-gray-600 transition-colors hover:text-gray-200"
                  >
                    {shown ? <EyeOff size={11} /> : <Eye size={11} />}
                  </button>
                  <button
                    onClick={() => copy(e.key)}
                    title="Copy value"
                    aria-label={`Copy ${e.key}`}
                    className="shrink-0 text-gray-600 transition-colors hover:text-gray-200"
                  >
                    {copied === e.key ? (
                      <Check size={11} className="text-emerald-400" />
                    ) : (
                      <Copy size={11} />
                    )}
                  </button>
                </div>
              );
            })}
          </div>
        )}
      </div>

      <p className="shrink-0 border-t border-white/5 px-4 py-1.5 font-mono text-meta text-gray-700">
        Read-only. Values are masked until revealed and are never written back.
      </p>
    </div>
  );
}
