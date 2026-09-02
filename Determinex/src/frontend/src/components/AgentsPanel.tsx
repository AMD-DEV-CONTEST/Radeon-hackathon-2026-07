"use client";
import { useCallback, useEffect, useState } from "react";
import { Bot, CheckCircle2, Circle, Loader2, Play, ShieldCheck, XCircle } from "lucide-react";
import { isTauri, invokeSafe } from "@/lib/api";

type CodingAgentInfo = {
  name: string;
  probe: string;
  installed: boolean;
  installHint: string;
  aliases: string[];
};

type CodingAgentRunResult = {
  agent: string;
  verified: boolean;
  ran: boolean;
  raw: string;
  oracle: string;
  nFailures: number;
  note: string;
  nextMoves: string[];
};

type Props = {
  workspacePath?: string;
  initialTask?: string;
};

export function AgentsPanel({ workspacePath = "", initialTask }: Props) {
  const [agents, setAgents] = useState<CodingAgentInfo[] | null>(null);
  const [activeAgent, setActiveAgent] = useState<string | null>(null);
  const [task, setTask] = useState(initialTask ?? "");
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<CodingAgentRunResult | null>(null);

  const refresh = useCallback(async () => {
    const res = await invokeSafe<CodingAgentInfo[]>("list_coding_agents", {});
    setAgents(res ?? []);
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // A question handed off from the Guide ("Ask an Agent" on a step) should
  // land pre-filled and ready to send, not silently dropped because this
  // panel already had its own empty task state -- and it should auto-open
  // the first installed agent so there's one click (Run) instead of two
  // (pick an agent, THEN notice the task box). Re-seeds on every new
  // initialTask, not just first mount, since the addon instance persists
  // across repeated "Ask an Agent" clicks on different steps.
  useEffect(() => {
    if (!initialTask) return;
    setTask(initialTask);
    if (agents && agents.length > 0) {
      const firstInstalled = agents.find((a) => a.installed);
      if (firstInstalled) setActiveAgent(firstInstalled.name);
    }
  }, [initialTask, agents]);

  const runAgent = async (name: string) => {
    if (!task.trim() || !workspacePath) return;
    setRunning(true);
    setResult(null);
    try {
      const res = await invokeSafe<CodingAgentRunResult>("run_coding_agent", {
        agent: name,
        task: task.trim(),
        workspace: workspacePath,
      });
      setResult(res);
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="relative flex h-full min-h-0 flex-col overflow-hidden p-5">
      <div className="relative z-10 flex min-h-0 flex-1 flex-col gap-4">
        <div className="border-b border-white/10 pb-4">
          <div className="mb-2 flex items-center gap-2 text-meta font-black uppercase tracking-widest text-violet-400">
            <Bot size={13} /> Agent Registry
          </div>
          <h2
            className="text-hero font-black leading-tight text-[var(--determinex-text)]"
            style={{ fontFamily: "var(--determinex-font-display)" }}
          >
            Coding Agents
          </h2>
          <p className="mt-1 text-label leading-relaxed text-gray-600">
            Any installed agent CLI (Claude Code, Codex, Gemini CLI, aider, cursor-agent) can run a
            task against this workspace. The agent&apos;s own &quot;done&quot; is never trusted
            alone -- Determinex re-runs the workspace&apos;s real compiler/tests afterward and only
            reports success if that oracle actually passes.
          </p>
          {initialTask && (
            <p className="mt-2 rounded-lg border border-violet-400/20 bg-violet-950/15 px-2.5 py-2 text-meta leading-relaxed text-violet-300/80">
              Handed off from the Guide. This is still a real agent task, not a chat -- pick an
              agent and Run to have it actually go look; the &quot;verified&quot; badge after still
              means the workspace&apos;s compiler/tests, which won&apos;t mean much for a plain
              question.
            </p>
          )}
        </div>

        {!isTauri() ? (
          <div className="flex flex-1 flex-col items-center justify-center gap-2 text-center opacity-40">
            <p className="text-label text-gray-500">
              Browser mode cannot probe installed CLI agents
            </p>
          </div>
        ) : agents === null ? (
          <div className="flex flex-1 items-center justify-center">
            <Loader2 size={18} className="animate-spin text-gray-600" />
          </div>
        ) : (
          <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto no-scrollbar">
            <div className="space-y-1.5 shrink-0">
              {agents.map((a) => {
                const isActive = activeAgent === a.name;
                return (
                  <div key={a.name} className="rounded-xl border border-white/8 bg-white/[0.02]">
                    <button
                      type="button"
                      onClick={() => {
                        if (!a.installed) return;
                        setActiveAgent(isActive ? null : a.name);
                        setResult(null);
                      }}
                      disabled={!a.installed}
                      className="flex w-full items-center gap-3 px-3 py-2.5 text-left transition-colors disabled:cursor-not-allowed hover:bg-white/[0.03]"
                    >
                      {a.installed ? (
                        <CheckCircle2 size={14} className="shrink-0 text-emerald-400" />
                      ) : (
                        <Circle size={14} className="shrink-0 text-gray-700" />
                      )}
                      <div className="min-w-0 flex-1">
                        <div className="font-mono text-label font-bold text-white">{a.name}</div>
                        <div className="truncate text-meta text-gray-600">
                          {a.installed ? `probe: ${a.probe}` : a.installHint}
                        </div>
                      </div>
                      {a.installed && (
                        <span className="shrink-0 rounded-full border border-emerald-500/20 bg-emerald-950/30 px-2 py-0.5 font-mono text-meta text-emerald-400">
                          INSTALLED
                        </span>
                      )}
                    </button>

                    {isActive && (
                      <div className="space-y-2 border-t border-white/5 px-3 py-3">
                        <textarea
                          value={task}
                          onChange={(e) => setTask(e.target.value)}
                          placeholder={`Task for ${a.name} to run against this workspace...`}
                          rows={2}
                          className="w-full resize-none rounded-lg border border-white/8 bg-black/30 px-2.5 py-2 text-label text-white/80 placeholder:text-gray-700 outline-none focus:border-violet-400/40"
                        />
                        <button
                          type="button"
                          onClick={() => void runAgent(a.name)}
                          disabled={running || !task.trim() || !workspacePath}
                          className="flex items-center gap-1.5 rounded-lg border border-violet-400/25 bg-violet-950/20 px-3 py-1.5 text-eyebrow font-black uppercase tracking-widest text-violet-300 transition hover:bg-violet-900/30 disabled:opacity-40"
                        >
                          {running ? (
                            <Loader2 size={11} className="animate-spin" />
                          ) : (
                            <Play size={11} />
                          )}
                          Run, then verify
                        </button>
                        {!workspacePath && (
                          <p className="text-meta text-amber-400/80">No workspace open.</p>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>

            {result && (
              <div
                className={`rounded-xl border p-4 ${
                  result.verified
                    ? "border-emerald-500/25 bg-emerald-950/10"
                    : "border-red-500/25 bg-red-950/10"
                }`}
              >
                <div className="mb-2 flex items-center gap-2">
                  {result.verified ? (
                    <ShieldCheck size={14} className="text-emerald-400" />
                  ) : (
                    <XCircle size={14} className="text-red-400" />
                  )}
                  <span
                    className={`text-meta font-black uppercase tracking-widest ${result.verified ? "text-emerald-400" : "text-red-400"}`}
                  >
                    {result.verified ? "Oracle verified" : "Not verified"}
                  </span>
                </div>
                <p className="text-label text-gray-400 font-mono leading-relaxed">{result.note}</p>
                {result.oracle && (
                  <p className="mt-1 text-meta text-gray-600 font-mono">
                    oracle: {result.oracle} ({result.nFailures} failures)
                  </p>
                )}
                {result.raw && (
                  <pre className="mt-2 max-h-40 overflow-y-auto rounded-lg bg-black/40 p-2 text-meta text-gray-500 font-mono whitespace-pre-wrap">
                    {result.raw.slice(0, 4000)}
                  </pre>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
