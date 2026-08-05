"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import { Trash2, RefreshCw, FolderOpen, Radio } from "lucide-react";
import {
  invokeWrite,
  isTauri,
  listHiveSessions,
  streamHiveSessionLog,
  type HiveSessionSummary,
} from "@/lib/api";

/**
 * Live output for a hive session.
 *
 * This panel used to be five hard-coded channel tabs (compiler/tests/oracle/
 * linter/system) over an empty object nothing ever wrote to -- honestly
 * labelled "No live output loaded.", and permanently so, because the component
 * contained no source of log lines at all.
 *
 * There IS a real source: `stream_session_log` starts a tail on the Rust side
 * and emits `hive-log-<session_id>` events. It is per-session, which is why
 * this needed a session picker before it could work — the old design had no way
 * to say WHICH session's output to show, and that missing choice is most of why
 * it stayed a shell.
 *
 * The five channels are gone. A session emits one stream; splitting it into
 * five tabs implied a routing that does not exist. Lines are coloured by
 * content instead, which is honest about being a heuristic over one stream.
 */

type LogLine = { text: string; level: "info" | "warn" | "error" | "success" };

const MAX_LINES = 2000;

function levelFor(text: string): LogLine["level"] {
  const t = text.toLowerCase();
  if (/\b(error|failed|panic|traceback|fatal)\b/.test(t)) return "error";
  if (/\b(warn|warning|deprecated)\b/.test(t)) return "warn";
  if (/\b(pass|passed|ok|success|complete|verified)\b/.test(t)) return "success";
  return "info";
}

const LINE_COLORS: Record<LogLine["level"], string> = {
  info: "text-gray-400",
  warn: "text-amber-400",
  error: "text-red-400",
  success: "text-emerald-400",
};

export function OutputPanel() {
  const [sessions, setSessions] = useState<HiveSessionSummary[]>([]);
  const [sessionId, setSessionId] = useState<string>("");
  const [lines, setLines] = useState<LogLine[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const unlisten = useRef<UnlistenFn | null>(null);

  const loadSessions = useCallback(async () => {
    if (!isTauri()) return;
    try {
      const s = await listHiveSessions();
      setSessions(s);
      setSessionId((cur) => cur || s[0]?.session_id || "");
      setLoaded(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setLoaded(true);
    }
  }, []);

  useEffect(() => {
    loadSessions();
  }, [loadSessions]);

  // Re-subscribe whenever the chosen session changes. Tearing the previous
  // listener down first matters: the event name is per-session, so leaving one
  // attached would interleave two sessions' output into the same pane.
  useEffect(() => {
    let cancelled = false;
    const stop = () => {
      unlisten.current?.();
      unlisten.current = null;
    };
    stop();
    setLines([]);
    setStreaming(false);
    if (!sessionId || !isTauri()) return;

    (async () => {
      try {
        const res = await streamHiveSessionLog(sessionId);
        if (cancelled) return;
        const un = await listen<{ line?: string }>(res.event, (ev) => {
          const text = ev.payload?.line ?? "";
          if (!text) return;
          setLines((prev) => {
            const next = [...prev, { text, level: levelFor(text) }];
            // Bounded: a long build emits tens of thousands of lines, and
            // keeping them all grows the DOM until the panel stalls.
            return next.length > MAX_LINES ? next.slice(-MAX_LINES) : next;
          });
        });
        if (cancelled) {
          un();
          return;
        }
        unlisten.current = un;
        setStreaming(true);
        setError(null);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      }
    })();

    return () => {
      cancelled = true;
      stop();
    };
  }, [sessionId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [lines]);

  if (!isTauri()) {
    return (
      <div className="flex h-full items-center justify-center p-6">
        <p className="text-label text-gray-600">Session output needs the desktop runtime.</p>
      </div>
    );
  }

  return (
    <div
      className="flex h-full flex-col overflow-hidden"
      style={{ fontFamily: "var(--determinex-font-mono, monospace)" }}
    >
      <div className="flex shrink-0 items-center gap-2 border-b border-white/8 px-3 py-2">
        <select
          value={sessionId}
          onChange={(e) => setSessionId(e.target.value)}
          data-testid="output-session-picker"
          className="max-w-[280px] flex-1 truncate rounded border border-white/10 bg-black/40 px-2 py-1 text-label text-gray-300 outline-none"
        >
          {sessions.length === 0 && <option value="">No sessions yet</option>}
          {sessions.map((s) => (
            <option key={s.session_id} value={s.session_id}>
              {s.project_name || s.session_id.slice(0, 8)} · {s.status} · {s.lang}
            </option>
          ))}
        </select>

        <span
          data-testid="output-stream-state"
          className={`flex items-center gap-1 text-eyebrow font-bold uppercase tracking-widest ${
            streaming ? "text-emerald-400" : "text-gray-600"
          }`}
        >
          <Radio size={9} className={streaming ? "animate-pulse" : ""} />
          {streaming ? "live" : "idle"}
        </span>

        <div className="flex-1" />
        <span className="font-mono text-meta text-gray-700">{lines.length}</span>
        <button
          onClick={loadSessions}
          title="Reload session list"
          className="rounded p-1 text-gray-500 transition-colors hover:text-gray-200"
        >
          <RefreshCw size={11} />
        </button>
        <button
          onClick={() =>
            sessionId &&
            // Void-returning and it does Err (missing session directory), so the
            // rejection has to land somewhere the user can see.
            void invokeWrite("reveal_session_output", { sessionId }).catch((e) =>
              setError(`Could not open the output folder: ${e}`)
            )
          }
          disabled={!sessionId}
          title="Open this session's output folder"
          className="rounded p-1 text-gray-500 transition-colors hover:text-gray-200 disabled:opacity-40"
        >
          <FolderOpen size={11} />
        </button>
        <button
          onClick={() => setLines([])}
          title="Clear the view (does not touch the log on disk)"
          className="rounded p-1 text-gray-500 transition-colors hover:text-gray-200"
        >
          <Trash2 size={11} />
        </button>
      </div>

      {error && (
        <p className="shrink-0 border-b border-red-500/25 bg-red-950/20 px-3 py-1.5 font-mono text-label text-red-300">
          {error}
        </p>
      )}

      <div className="flex-1 space-y-0.5 overflow-y-auto p-3">
        {lines.length === 0 ? (
          <p className="text-label text-gray-700">
            {!loaded
              ? "Loading sessions…"
              : sessions.length === 0
                ? "No hive sessions yet. Run a build from Work and its output appears here."
                : streaming
                  ? "Attached — waiting for output."
                  : "Not attached to this session's log."}
          </p>
        ) : (
          lines.map((l, i) => (
            <div
              key={i}
              className={`whitespace-pre-wrap text-label leading-relaxed ${LINE_COLORS[l.level]}`}
            >
              {l.text}
            </div>
          ))
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
