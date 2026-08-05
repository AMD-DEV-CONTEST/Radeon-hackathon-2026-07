"use client";
import { useCallback, useEffect, useState } from "react";
import { Cpu, Loader2, CheckCircle2, XCircle, RefreshCw, Container, Sparkles } from "lucide-react";
import {
  listHiveSessions,
  type HiveSessionSummary,
  checkOllamaStatus,
  checkDockerStatus,
  type DockerStatus,
  isTauri,
} from "@/lib/api";

function ServiceCard({
  label,
  ok,
  detail,
  icon: Icon,
}: {
  label: string;
  ok: boolean;
  detail?: string;
  icon: typeof Cpu;
}) {
  return (
    <div
      className={`flex items-center gap-3 rounded-xl border p-4 ${
        ok ? "border-emerald-500/25 bg-emerald-950/10" : "border-white/10 bg-black/30"
      }`}
    >
      <div
        className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${
          ok ? "bg-emerald-500/15 text-emerald-400" : "bg-white/5 text-gray-500"
        }`}
      >
        <Icon size={16} />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="text-body font-bold text-white">{label}</span>
          {ok ? (
            <CheckCircle2 size={12} className="text-emerald-400" />
          ) : (
            <XCircle size={12} className="text-gray-600" />
          )}
        </div>
        <div className="truncate text-meta text-gray-600">
          {ok ? "Running" : detail || "Not running"}
        </div>
      </div>
    </div>
  );
}

export function ExecutionWorkspace() {
  const [sessions, setSessions] = useState<HiveSessionSummary[]>([]);
  const [loadingSessions, setLoadingSessions] = useState(true);
  const [ollama, setOllama] = useState<{ ok: boolean; error?: string } | null>(null);
  const [docker, setDocker] = useState<DockerStatus | null>(null);
  const [loadingServices, setLoadingServices] = useState(true);

  const refreshSessions = useCallback(async () => {
    try {
      const all = await listHiveSessions();
      setSessions(all.filter((s) => s.status === "in_progress"));
    } catch {
      setSessions([]);
    } finally {
      setLoadingSessions(false);
    }
  }, []);

  const refreshServices = useCallback(async () => {
    setLoadingServices(true);
    const [o, d] = await Promise.all([checkOllamaStatus(), checkDockerStatus()]);
    setOllama(o);
    setDocker(d);
    setLoadingServices(false);
  }, []);

  // Sessions are polled (a hive build can start/finish while this panel sits open);
  // services are checked once per open plus on manual refresh -- Docker/Ollama
  // don't change state on their own the way a running build does.
  useEffect(() => {
    if (!isTauri()) {
      setLoadingSessions(false);
      setLoadingServices(false);
      return;
    }
    let cancelled = false;
    let inFlight = false;
    const tick = async () => {
      if (inFlight || cancelled) return;
      inFlight = true;
      try {
        await refreshSessions();
      } finally {
        inFlight = false;
      }
    };
    void tick();
    void refreshServices();
    const id = setInterval(tick, 8000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [refreshSessions, refreshServices]);

  if (!isTauri()) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-2 bg-[var(--dtx-code-bg)] text-center opacity-40">
        <p className="text-label text-gray-500">Browser mode cannot read live runtime state</p>
        <p className="text-label text-gray-600">
          Open the Tauri desktop app for real session and service status.
        </p>
      </div>
    );
  }

  return (
    <div className="flex h-full w-full flex-col overflow-y-auto bg-[var(--dtx-code-bg)] p-6 no-scrollbar">
      <div className="mb-6 border-b border-white/10 pb-6">
        <div className="flex items-center gap-2 text-meta font-black uppercase tracking-widest text-rose-300">
          <Cpu size={14} /> Runtime
        </div>
        <h2 className="mt-2 text-3xl font-black tracking-tight text-white">Active Work</h2>
        <p className="mt-2 max-w-2xl text-sm leading-relaxed text-gray-500">
          Hive sessions currently running for this workspace, and whether the local services they
          depend on are reachable.
        </p>
      </div>

      <section className="mb-8">
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-meta font-black uppercase tracking-widest text-gray-500">
            Active Hive Sessions
          </h3>
          <button
            type="button"
            onClick={() => void refreshSessions()}
            className="text-gray-600 transition-colors hover:text-gray-300"
            title="Refresh"
          >
            <RefreshCw size={12} />
          </button>
        </div>
        {loadingSessions ? (
          <div className="flex items-center gap-2 text-label text-gray-600">
            <Loader2 size={14} className="animate-spin" /> Checking for running sessions...
          </div>
        ) : sessions.length === 0 ? (
          <div className="rounded-xl border border-dashed border-white/10 bg-white/[0.02] px-4 py-6 text-center text-label text-gray-600">
            No hive sessions currently running.
          </div>
        ) : (
          <div className="space-y-2">
            {sessions.map((s) => (
              <div
                key={s.session_id}
                className="flex items-center justify-between rounded-xl border border-emerald-500/20 bg-emerald-950/10 px-4 py-3"
              >
                <div className="min-w-0">
                  <div className="truncate text-body font-bold text-white">{s.project_name}</div>
                  <div className="font-mono text-meta text-gray-600">
                    {s.session_id.slice(0, 8)}… · {s.lang}
                  </div>
                </div>
                <div className="shrink-0 text-right">
                  <div className="text-label font-black text-emerald-400">
                    {s.complete_count}/{s.step_count}
                  </div>
                  <div className="text-meta text-gray-600">steps</div>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      <section>
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-meta font-black uppercase tracking-widest text-gray-500">
            Local Services
          </h3>
          <button
            type="button"
            onClick={() => void refreshServices()}
            className="text-gray-600 transition-colors hover:text-gray-300"
            title="Refresh"
          >
            <RefreshCw size={12} />
          </button>
        </div>
        {loadingServices ? (
          <div className="flex items-center gap-2 text-label text-gray-600">
            <Loader2 size={14} className="animate-spin" /> Checking local services...
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <ServiceCard
              label="Ollama"
              ok={Boolean(ollama?.ok)}
              detail={ollama?.error}
              icon={Sparkles}
            />
            <ServiceCard
              label="Docker"
              ok={Boolean(docker?.running)}
              detail={docker?.message}
              icon={Container}
            />
          </div>
        )}
      </section>
    </div>
  );
}
