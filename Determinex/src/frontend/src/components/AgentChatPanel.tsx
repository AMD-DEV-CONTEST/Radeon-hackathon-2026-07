"use client";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import {
  AlertTriangle,
  Bot,
  CheckCircle2,
  Circle,
  Columns,
  FileDiff,
  FileText,
  Loader2,
  Lock,
  MessageSquare,
  Pencil,
  Plus,
  Radio,
  RefreshCw,
  Rows,
  Save,
  Send,
  ShieldCheck,
  Zap,
  XCircle,
} from "lucide-react";
import { isTauri, invokeSafe, invokeWrite } from "@/lib/api";
import { useErrorToast } from "@/components/ErrorToast";

type CodingAgentInfo = {
  name: string;
  probe: string;
  installed: boolean;
  installHint: string;
  aliases: string[];
  // From the registry, which is the only place that knows. Optional so an older backend still
  // renders instead of the picker vanishing.
  supportsModel?: boolean;
  supportsChatMode?: boolean;
  /** Curated shortlist in the fast/balanced/deep vocabulary. Empty = free text is correct. */
  models?: { tier: string; model: string; label: string }[];
};

// Cheap, free, no-model-call status (see determinex_agents.py._cheap_status).
// "loggedIn" here means an auth-status file/subcommand said so -- for
// gemini-cli specifically that's "stored credentials found", NOT a live
// verification. Only agent_probe_test (a real call) can prove the agent is
// actually working right now.
type AgentStatusEntry = {
  name: string;
  installed: boolean;
  authKnown: boolean;
  loggedIn: boolean;
  // Named state, because `loggedIn` was carrying four different facts and this panel was reading
  // it as the broadest one. See READINESS below.
  readiness?: string;
  readinessEvidence?: string;
  lastProbeStatus?: string;
  lastProbeAt?: string;
  plan: string;
  detail: string;
  installHint: string;
};

type ProbeStatus = "ok" | "quota_exhausted" | "auth_error" | "timeout" | "error";

type AgentProbeOutputEvent = { agent: string; stream: string; chunk: string };
type AgentProbeCompleteEvent = {
  agent: string;
  status: ProbeStatus;
  detail: string;
  rawTail: string;
};

type ChatSessionSummary = {
  sessionId: string;
  workspace: string;
  participants: string[];
  turnMode: string;
  createdAt: string;
  lastActive: string;
  turnCount: number;
};

type ChatTurnDto = {
  turnId: string;
  sessionId: string;
  seq: number;
  speaker: string;
  speakerKind: string;
  addressedTo: string[];
  mode: string;
  taskPrompt: string;
  rawOutput: string;
  returncode: number;
  verified: boolean;
  oracle: string;
  nFailures: number;
  note: string;
  startedAt: string;
  finishedAt: string;
};

type AgentChatOutputEvent = {
  sessionId: string;
  turnId: string;
  agent: string;
  stream: string;
  chunk: string;
};

type AgentChatTurnCompleteEvent = {
  sessionId: string;
  turnId: string;
  agent: string;
  verified: boolean;
  oracle: string;
  nFailures: number;
  note: string;
  error: string | null;
};

type AgentChatQueueEvent = {
  sessionId: string;
  pending: string[];
  running: string | null;
};

/** Sentinel option value that switches the local picker to free text. Not a
 *  model name, so it can never be mistaken for one. */
const CUSTOM_MODEL_SENTINEL = "__determinex_custom__";

type LiveTurn = { agent: string; text: string };
type ViewMode = "inline" | "lanes";

type Props = {
  workspacePath?: string;
};

// ── Per-agent color identity ────────────────────────────────────────────────
// Ryan: "each ai should also be color coordinated." Fixed colors for the
// known registered agents (scripts/determinex_agents.py._AGENTS), plus a
// stable hash-based fallback palette for anything registered later (a
// plugin agent, a future CLI) so color-coding never silently falls back to
// one flat color again.
const AGENT_COLORS: Record<string, { text: string; border: string; bg: string; dot: string }> = {
  "claude-code": {
    text: "text-orange-300",
    border: "border-orange-400/30",
    bg: "bg-orange-950/15",
    dot: "bg-orange-400",
  },
  codex: {
    text: "text-sky-300",
    border: "border-sky-400/30",
    bg: "bg-sky-950/15",
    dot: "bg-sky-400",
  },
  "gemini-cli": {
    text: "text-indigo-300",
    border: "border-indigo-400/30",
    bg: "bg-indigo-950/15",
    dot: "bg-indigo-400",
  },
  "local-ollama": {
    text: "text-emerald-300",
    border: "border-emerald-400/30",
    bg: "bg-emerald-950/15",
    dot: "bg-emerald-400",
  },
  aider: {
    text: "text-amber-300",
    border: "border-amber-400/30",
    bg: "bg-amber-950/15",
    dot: "bg-amber-400",
  },
  "cursor-agent": {
    text: "text-pink-300",
    border: "border-pink-400/30",
    bg: "bg-pink-950/15",
    dot: "bg-pink-400",
  },
  corpus: {
    text: "text-fuchsia-300",
    border: "border-fuchsia-400/30",
    bg: "bg-fuchsia-950/15",
    dot: "bg-fuchsia-400",
  },
};
const FALLBACK_PALETTE = [
  { text: "text-teal-300", border: "border-teal-400/30", bg: "bg-teal-950/15", dot: "bg-teal-400" },
  {
    text: "text-violet-300",
    border: "border-violet-400/30",
    bg: "bg-violet-950/15",
    dot: "bg-violet-400",
  },
  { text: "text-rose-300", border: "border-rose-400/30", bg: "bg-rose-950/15", dot: "bg-rose-400" },
];
// See the "corpus" exception note above export function AgentChatPanel.
const CORPUS_AGENT: CodingAgentInfo = {
  name: "corpus",
  probe: "",
  installed: true, // always available -- no external toolchain, just Determinex's own corpus store
  installHint: "",
  aliases: [],
  // Not a model and not a CLI: corpus answers from Determinex's own stored lessons, so there is
  // nothing to point at a provider and no conversational mode to switch into.
  supportsModel: false,
  supportsChatMode: false,
};

// ── Readiness, one row per distinguishable state ────────────────────────────────────────────────
//
// `loggedIn` was one boolean carrying four facts, and 2026-07-31 produced three of them on one
// machine: a credential that works, a credential with no auth method selected, and a credential the
// PROVIDER refuses ("IneligibleTierError: This client is no longer supported for Gemini Code Assist
// for individuals"). The last one is the reason this exists -- no local check can discover it, the
// token refreshes fine, and telling the user to log in again cannot fix it. Each state gets its own
// colour and its own words because each has a different remedy.
const READINESS: Record<string, { dot: string; label: string; tone: string }> = {
  verified: { dot: "bg-emerald-400", label: "verified", tone: "text-emerald-300" },
  credentials_unverified: { dot: "bg-sky-400", label: "not tested", tone: "text-sky-300" },
  provider_refused: { dot: "bg-red-400", label: "provider refused", tone: "text-red-300" },
  quota_exhausted: { dot: "bg-amber-400", label: "out of quota", tone: "text-amber-300" },
  failed: { dot: "bg-red-400", label: "failed", tone: "text-red-300" },
  no_auth_method: { dot: "bg-amber-400", label: "no auth method", tone: "text-amber-300" },
  no_credentials: { dot: "bg-gray-600", label: "not signed in", tone: "text-gray-400" },
  not_installed: { dot: "bg-gray-700", label: "not installed", tone: "text-gray-500" },
};

// The live probe event carries the classifier's status; map it to the same vocabulary so a probe
// on screen and the remembered verdict never describe the same thing two different ways.
const PROBE_TO_READINESS: Record<string, string> = {
  ok: "verified",
  provider_refused: "provider_refused",
  quota_exhausted: "quota_exhausted",
  auth_error: "failed",
  timeout: "failed",
  error: "failed",
};

function colorFor(name: string) {
  const known = AGENT_COLORS[name];
  if (known) return known;
  let hash = 0;
  for (let i = 0; i < name.length; i++) hash = (hash * 31 + name.charCodeAt(i)) >>> 0;
  return FALLBACK_PALETTE[hash % FALLBACK_PALETTE.length];
}

// Every entry registered in scripts/determinex_agents.py._AGENTS shows up
// here via list_coding_agents -- including "local-ollama", which rides on
// aider's --model flag rather than a bespoke local runner. One deliberate
// exception: "corpus" (see refreshAgents below) is NOT a real CLI agent --
// it has no probe binary, no install step, no auth/quota concept, and is
// handled entirely on the Rust side (agent_chat.rs's is_corpus_participant)
// before any CLI resolution happens, so it's synthesized here rather than
// registered in _AGENTS, which would wrongly imply it's a spawnable CLI.
export function AgentChatPanel({ workspacePath = "" }: Props) {
  const showError = useErrorToast();
  const [agents, setAgents] = useState<CodingAgentInfo[] | null>(null);
  const [cloakActive, setCloakActive] = useState<boolean | null>(null);
  const [sessions, setSessions] = useState<ChatSessionSummary[] | null>(null);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [transcript, setTranscript] = useState<ChatTurnDto[]>([]);
  const [live, setLive] = useState<Record<string, LiveTurn>>({});
  const [pending, setPending] = useState<string[]>([]);
  const [viewMode, setViewMode] = useState<ViewMode>("lanes");

  const [selectedParticipants, setSelectedParticipants] = useState<string[]>([]);
  const [turnMode, setTurnMode] = useState<"mention" | "broadcast">("broadcast");
  const [creating, setCreating] = useState(false);
  // Surfaces failures from the void-returning agent_chat_* writes. Those
  // resolve to null on success, so invokeSafe could not distinguish them from a
  // rejection and every failure here used to be invisible.
  const [sessionError, setSessionError] = useState<string | null>(null);

  // ANY LLM (Ryan, live: "fix it to where ANY llm can be used"): per-agent
  // model override, keyed by agent name. Empty/absent = that agent's own
  // default (local-ollama's env-var tag, or each cloud CLI's own default
  // model). Applied to the active session immediately on change; carried
  // into agent_chat_create_session's follow-up calls for a not-yet-created
  // session.
  const [modelOverrides, setModelOverrides] = useState<Record<string, string>>({});
  // Agents whose local-model picker has been switched from the installed-tags
  // dropdown to free text, so an un-pulled or not-yet-released tag can be named.
  const [customLocalModel, setCustomLocalModel] = useState<Set<string>>(new Set());
  const [ollamaModels, setOllamaModels] = useState<string[]>([]);

  useEffect(() => {
    void invokeSafe<{ id: string }[]>("get_ollama_models", {}).then((res) => {
      if (res) setOllamaModels(res.map((m) => m.id));
    });
  }, []);

  const setModelOverride = useCallback(
    (agent: string, model: string) => {
      setModelOverrides((prev) => {
        const next = { ...prev };
        if (model.trim()) next[agent] = model;
        else delete next[agent];
        return next;
      });
      if (activeSessionId) {
        void invokeWrite("agent_chat_set_model", {
          sessionId: activeSessionId,
          agent,
          model,
        }).catch((e) => setSessionError(`${agent}'s model could not be set to "${model}": ${e}`));
      }
    },
    [activeSessionId]
  );

  const [composer, setComposer] = useState("");
  const [sending, setSending] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Mission plan -- the one doc every participant's prompt is built from
  // (see build_context_prompt() in determinex_agent_chat.py). Its own
  // panel, not nested in the chat scroll: "it works from the chat but not
  // nested in it... a universal place they all run to for their marching
  // orders or we will have chaos and duplication."
  const [plan, setPlan] = useState("");
  const [planDraft, setPlanDraft] = useState("");
  const [planEditing, setPlanEditing] = useState(false);
  const [planOpen, setPlanOpen] = useState(true);
  const [planSaving, setPlanSaving] = useState(false);
  const [planResyncing, setPlanResyncing] = useState(false);

  // null = still asking. `invokeSafe` resolves to null on FAILURE, and `res ?? []` collapsed
  // that into the same empty list as a successful "no agents installed" -- so a failed or
  // still-running lookup rendered exactly like a machine with nothing installed: a blank
  // participant list, a Start Session button greyed out for no stated reason, and nothing
  // anywhere saying which of the three it was. Keeping them apart is the whole fix.
  const [agentsError, setAgentsError] = useState<string | null>(null);

  const refreshAgents = useCallback(async () => {
    setAgentsError(null);
    setAgents(null);
    // TIME-BOXED. `invokeSafe` rejects nothing and waits forever, so when the IPC channel
    // itself is wedged the promise never settles and the panel sits on "Looking for agents..."
    // indefinitely -- a spinner with no end is the same lie as a blank list, just slower to
    // notice.
    //
    // 45s, not 20s: the subprocess itself takes ~0.25s, but app boot fires a dozen
    // Python-spawning commands at once and a measured COLD `list_coding_agents` over IPC took
    // 5.3s against 0.3s warm. A 20s box turned a slow-but-fine boot into "did not answer in
    // time", which is a different wrong answer rather than a fix. The point of the box is to
    // guarantee the spinner ENDS, not to be a performance assertion.
    const res = await Promise.race([
      invokeSafe<CodingAgentInfo[]>("list_coding_agents", {}),
      new Promise<undefined>((resolve) => setTimeout(() => resolve(undefined), 45000)),
    ]);
    if (res === undefined) {
      setAgentsError("The agent list did not answer in time.");
      setAgents([CORPUS_AGENT]);
      return;
    }
    if (res === null) {
      setAgentsError("Could not read the list of installed agents.");
      setAgents([CORPUS_AGENT]);
      return;
    }
    setAgents([...res, CORPUS_AGENT]);
  }, []);

  // ── Roster status (Ryan: "I want to see everything who's online, what
  // their credits are at"). Two tiers, kept deliberately separate:
  //   - statusMap: cheap, free, auto-refreshed on an interval (no model
  //     calls -- safe to poll).
  //   - probeResults/probeLive: a REAL call, manual "Test" trigger only
  //     (agent_probe_test costs actual quota -- never auto-fired).
  const [statusMap, setStatusMap] = useState<Record<string, AgentStatusEntry>>({});
  const [probing, setProbing] = useState<Record<string, boolean>>({});
  const [probeLive, setProbeLive] = useState<Record<string, string>>({});
  const [probeResult, setProbeResult] = useState<Record<string, AgentProbeCompleteEvent>>({});

  const refreshStatus = useCallback(async () => {
    const res = await invokeSafe<AgentStatusEntry[]>("agent_status_roster", {});
    if (!res) return;
    setStatusMap(Object.fromEntries(res.map((s) => [s.name, s])));
  }, []);

  useEffect(() => {
    void refreshStatus();
    const id = setInterval(() => void refreshStatus(), 30_000);
    return () => clearInterval(id);
  }, [refreshStatus]);

  useEffect(() => {
    if (!isTauri()) return;
    let unlistenOut: (() => void) | null = null;
    let unlistenDone: (() => void) | null = null;
    let cancelled = false;
    (async () => {
      unlistenOut = await listen<AgentProbeOutputEvent>("agent-probe-output", (event) => {
        if (cancelled) return;
        const { agent, chunk } = event.payload;
        setProbeLive((prev) => ({ ...prev, [agent]: (prev[agent] ?? "") + chunk }));
      });
      unlistenDone = await listen<AgentProbeCompleteEvent>("agent-probe-complete", (event) => {
        if (cancelled) return;
        const { agent } = event.payload;
        setProbing((prev) => ({ ...prev, [agent]: false }));
        setProbeResult((prev) => ({ ...prev, [agent]: event.payload }));
      });
    })();
    return () => {
      cancelled = true;
      unlistenOut?.();
      unlistenDone?.();
    };
  }, []);

  const runProbe = useCallback(
    async (name: string) => {
      if (probing[name]) return;
      setProbing((prev) => ({ ...prev, [name]: true }));
      setProbeLive((prev) => ({ ...prev, [name]: "" }));
      setProbeResult((prev) => {
        const next = { ...prev };
        delete next[name];
        return next;
      });
      try {
        // Raw invoke (not invokeSafe) deliberately here: invokeSafe's whole
        // contract is "swallow errors, return null" -- but a probe that
        // fails to even SPAWN (bad argv, not installed) errors out of the
        // Rust command before it ever reaches its own event::emit, so
        // nothing would clear the spinner or say what happened. Found live:
        // gemini-cli's Test button spun on "waiting for response..."
        // forever with no error shown -- the exact "believe it errored out"
        // failure mode this whole roster exists to prevent.
        await invoke("agent_probe_test", { agent: name, workspace: workspacePath });
      } catch (e) {
        setProbing((prev) => ({ ...prev, [name]: false }));
        setProbeResult((prev) => ({
          ...prev,
          [name]: { agent: name, status: "error", detail: String(e), rawTail: "" },
        }));
      }
    },
    [probing, workspacePath]
  );

  const refreshSessions = useCallback(async () => {
    const res = await invokeSafe<ChatSessionSummary[]>("agent_chat_list_sessions", {
      workspace: workspacePath,
    });
    setSessions(res ?? []);
  }, [workspacePath]);

  const refreshTranscript = useCallback(async (sessionId: string) => {
    const res = await invokeSafe<ChatTurnDto[]>("agent_chat_get_transcript", { sessionId });
    setTranscript(res ?? []);
  }, []);

  const refreshPlan = useCallback(async (sessionId: string) => {
    const res = await invokeSafe<string>("agent_chat_get_plan", { sessionId });
    setPlan(res ?? "");
  }, []);

  useEffect(() => {
    void refreshAgents();
    void refreshSessions();
    void invokeSafe<boolean>("agent_chat_cloak_status", {}).then((v) => setCloakActive(v ?? false));
  }, [refreshAgents, refreshSessions]);

  // Live streaming + turn-completion. A completed turn's authoritative
  // content lives in the persisted transcript (record-turn on the Rust/
  // Python side already wrote it) -- re-fetching on every completion keeps
  // exactly one source of truth instead of trying to reconcile a
  // client-side draft with the server's final version.
  useEffect(() => {
    if (!isTauri() || !activeSessionId) return;
    let unlistenOutput: (() => void) | null = null;
    let unlistenComplete: (() => void) | null = null;
    let unlistenQueue: (() => void) | null = null;
    let cancelled = false;

    (async () => {
      unlistenOutput = await listen<AgentChatOutputEvent>("agent-chat-output", (event) => {
        if (cancelled || event.payload.sessionId !== activeSessionId) return;
        const { turnId, agent, chunk } = event.payload;
        setLive((prev) => {
          const existing = prev[turnId];
          return {
            ...prev,
            [turnId]: { agent, text: (existing?.text ?? "") + chunk },
          };
        });
      });

      unlistenComplete = await listen<AgentChatTurnCompleteEvent>(
        "agent-chat-turn-complete",
        (event) => {
          if (cancelled || event.payload.sessionId !== activeSessionId) return;
          setLive((prev) => {
            const next = { ...prev };
            delete next[event.payload.turnId];
            return next;
          });
          void refreshTranscript(activeSessionId);
          void refreshSessions();
        }
      );

      unlistenQueue = await listen<AgentChatQueueEvent>("agent-chat-queue-update", (event) => {
        if (cancelled || event.payload.sessionId !== activeSessionId) return;
        setPending(event.payload.pending);
      });
    })();

    return () => {
      cancelled = true;
      unlistenOutput?.();
      unlistenComplete?.();
      unlistenQueue?.();
    };
  }, [activeSessionId, refreshTranscript, refreshSessions]);

  useEffect(() => {
    if (!activeSessionId) return;
    void refreshTranscript(activeSessionId);
    void refreshPlan(activeSessionId);
    setPlanEditing(false);
  }, [activeSessionId, refreshTranscript, refreshPlan]);

  useEffect(() => {
    if (viewMode === "inline") {
      scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
    }
  }, [transcript, live, viewMode]);

  const toggleParticipant = (name: string) => {
    setSelectedParticipants((prev) =>
      prev.includes(name) ? prev.filter((p) => p !== name) : [...prev, name]
    );
  };

  const createSession = async () => {
    if (selectedParticipants.length === 0 || !workspacePath) return;
    setCreating(true);
    setSessionError(null);
    try {
      const sessionId = `chat-${Date.now()}`;
      // agent_chat_create_session returns Result<(), String>, so under Tauri a
      // SUCCESSFUL call resolves to null -- which is also what invokeSafe
      // returns when the command REJECTS. The old guard was
      // `if (ok !== null || isTauri())`: the first half was therefore always
      // false on success, and the second half always true in the desktop app,
      // so the branch ran unconditionally. A failed creation still switched the
      // UI to the new session id, and every later call against it failed with
      // "unknown chat session" -- the panel looked open and was talking to
      // nothing.
      await invokeWrite("agent_chat_create_session", {
        sessionId,
        workspace: workspacePath,
        participants: selectedParticipants,
        turnMode,
      });
      setActiveSessionId(sessionId);
      setTranscript([]);
      setLive({});
      setPending([]);
      void refreshSessions();
      // Push any model overrides picked before the session existed --
      // agent_chat_set_model needs a real sessionId, which only exists
      // from this point on.
      for (const [agent, model] of Object.entries(modelOverrides)) {
        if (selectedParticipants.includes(agent)) {
          try {
            await invokeWrite("agent_chat_set_model", { sessionId, agent, model });
          } catch (e) {
            setSessionError(`Session created, but ${agent}'s model override did not apply: ${e}`);
          }
        }
      }
    } catch (e) {
      setSessionError(`Could not start the session: ${e}`);
    } finally {
      setCreating(false);
    }
  };

  const send = async () => {
    if (!composer.trim() || !activeSessionId || sending) return;
    setSending(true);
    const message = composer.trim();
    setComposer("");
    try {
      // invokeSafe never throws (returns null on failure) -- but a null here
      // means the message was NEVER queued (unknown session, IPC failure,
      // etc.), not just "still processing". Previously the composer was
      // cleared unconditionally and nothing told the user their message
      // went nowhere -- restore it and surface the failure instead.
      const ok = await invokeSafe<boolean>("agent_chat_send", {
        sessionId: activeSessionId,
        message,
        sender: "user",
      });
      if (ok !== true) {
        setComposer(message);
        showError("Message wasn't sent -- the chat session may be stale. Try again.");
        void refreshSessions();
      }
    } finally {
      setSending(false);
    }
  };

  const startEditingPlan = () => {
    setPlanDraft(plan);
    setPlanEditing(true);
  };

  const savePlan = async () => {
    if (!activeSessionId) return;
    setPlanSaving(true);
    setSessionError(null);
    try {
      await invokeWrite("agent_chat_set_plan", { sessionId: activeSessionId, content: planDraft });
      setPlan(planDraft);
      setPlanEditing(false);
    } catch (e) {
      // Leaves the editor open with the draft intact, rather than closing it and
      // showing a plan the agents were never given.
      setSessionError(`Mission Plan not saved: ${e}`);
    } finally {
      setPlanSaving(false);
    }
  };

  // Pulls fresh content from the workspace's root/project stewardship docs
  // (CLAUDE.md/PROJECT.md) into the plan -- appends rather than overwrites,
  // so it never destroys the live Positions board or anything already
  // written here.
  const resyncPlan = async () => {
    if (!activeSessionId || !workspacePath) return;
    setPlanResyncing(true);
    try {
      const updated = await invokeSafe<string>("agent_chat_resync_plan", {
        sessionId: activeSessionId,
        workspace: workspacePath,
      });
      if (updated !== null) setPlan(updated);
    } finally {
      setPlanResyncing(false);
    }
  };

  // @mention autocomplete: matches a trailing "@fragment" at the end of the
  // composer text against the active session's participants.
  const activeSession = sessions?.find((s) => s.sessionId === activeSessionId) ?? null;
  const mentionMatch = /@([a-zA-Z0-9_-]*)$/.exec(composer);
  const mentionSuggestions = useMemo(() => {
    if (!mentionMatch || !activeSession) return [];
    const fragment = mentionMatch[1].toLowerCase();
    return activeSession.participants.filter((p) => p.toLowerCase().startsWith(fragment));
  }, [mentionMatch, activeSession]);

  const applyMention = (name: string) => {
    if (!mentionMatch) return;
    const start = composer.length - mentionMatch[0].length;
    setComposer(`${composer.slice(0, start)}@${name} `);
  };

  const liveEntries = Object.entries(live);

  return (
    <div className="relative flex h-full min-h-0 flex-col overflow-hidden p-5">
      <div className="relative z-10 flex min-h-0 flex-1 flex-col gap-4">
        <div className="border-b border-white/10 pb-4">
          <div className="mb-2 flex items-center justify-between gap-2">
            <div className="flex items-center gap-2 text-meta font-black uppercase tracking-widest text-fuchsia-400">
              <MessageSquare size={13} /> Multi-Agent Session
            </div>
            {cloakActive !== null && (
              <div
                title={
                  cloakActive
                    ? "Cloak room is ON: cloud agents (Claude Code, Codex, Gemini CLI) run against a fully obfuscated shadow workspace, never the real one. local-ollama always sees the real workspace."
                    : "Cloak room is OFF: every participant, including cloud agents, edits the real workspace directly. Set DETERMINEX_CLOAK=1 before launch to enable it."
                }
                className={`flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-eyebrow font-black uppercase tracking-widest ${
                  cloakActive
                    ? "border-emerald-400/30 bg-emerald-950/20 text-emerald-300"
                    : "border-white/8 bg-white/[0.02] text-gray-500"
                }`}
              >
                <Lock size={10} />
                Cloak {cloakActive ? "ON" : "OFF"}
              </div>
            )}
          </div>
          <h2
            className="text-hero font-black leading-tight text-[var(--determinex-text)]"
            style={{ fontFamily: "var(--determinex-font-display)" }}
          >
            Agent Chat Room
          </h2>
          <p className="mt-1 text-label leading-relaxed text-gray-600">
            Claude Code, Codex, Gemini CLI, and a local model can all edit this workspace inside one
            shared conversation. Turns run one at a time, never concurrently -- each agent&apos;s
            edits are checked against the real compiler/test oracle before the next agent goes. All
            participants read the same Mission Plan below, so nobody duplicates or contradicts
            another&apos;s work.
          </p>
        </div>

        {sessionError && (
          <div className="flex shrink-0 items-start gap-2 rounded-lg border border-red-400/30 bg-red-950/20 px-3 py-2 text-label leading-relaxed text-red-300">
            <span className="flex-1">{sessionError}</span>
            <button
              type="button"
              onClick={() => setSessionError(null)}
              className="shrink-0 text-red-400/70 hover:text-red-300"
            >
              Dismiss
            </button>
          </div>
        )}

        {isTauri() && (
          <AgentRosterBar
            agents={agents ?? []}
            statusMap={statusMap}
            probing={probing}
            probeLive={probeLive}
            probeResult={probeResult}
            onTest={runProbe}
          />
        )}

        {!isTauri() ? (
          <div className="flex flex-1 flex-col items-center justify-center gap-2 text-center opacity-40">
            <p className="text-label text-gray-500">Browser mode cannot host live agent CLIs</p>
          </div>
        ) : (
          <>
            {/* Session picker */}
            {sessions && sessions.length > 0 && (
              <div className="flex shrink-0 flex-wrap gap-1.5">
                {sessions.map((s) => (
                  <button
                    key={s.sessionId}
                    type="button"
                    onClick={() => setActiveSessionId(s.sessionId)}
                    className={`rounded-full border px-2.5 py-1 font-mono text-meta transition-colors ${
                      activeSessionId === s.sessionId
                        ? "border-fuchsia-400/40 bg-fuchsia-950/30 text-fuchsia-300"
                        : "border-white/8 bg-white/[0.02] text-gray-500 hover:bg-white/[0.05]"
                    }`}
                  >
                    {s.participants.join("+")} ({s.turnCount})
                  </button>
                ))}
                <button
                  type="button"
                  onClick={() => setActiveSessionId(null)}
                  className="rounded-full border border-white/8 bg-white/[0.02] px-2.5 py-1 font-mono text-meta text-gray-500 hover:bg-white/[0.05]"
                >
                  <Plus size={9} className="inline -mt-px" /> new
                </button>
              </div>
            )}

            {!activeSessionId ? (
              <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto no-scrollbar">
                <div className="flex items-center gap-1.5 text-eyebrow font-black uppercase tracking-widest text-gray-600">
                  <Plus size={11} /> New Session
                </div>
                <div className="space-y-1.5">
                  {/* Say WHICH empty this is. All three used to render as the same blank gap
                      above a Start Session button that was disabled without explanation. */}
                  {agents === null && (
                    <div className="flex items-center gap-2 rounded-lg border border-white/8 bg-white/[0.02] px-3 py-2 text-meta text-gray-500">
                      <Loader2 size={11} className="animate-spin" />
                      Looking for agents installed on this computer...
                    </div>
                  )}
                  {agentsError && (
                    <div className="flex items-center justify-between gap-2 rounded-lg border border-amber-400/25 bg-amber-950/20 px-3 py-2 text-meta text-amber-200">
                      <span>{agentsError}</span>
                      <button
                        type="button"
                        onClick={() => void refreshAgents()}
                        className="rounded-md border border-amber-400/30 px-2 py-0.5 font-bold uppercase tracking-wide hover:bg-amber-400/10"
                      >
                        Retry
                      </button>
                    </div>
                  )}
                  {agents !== null && !agentsError && agents.length <= 1 && (
                    <div className="rounded-lg border border-white/8 bg-white/[0.02] px-3 py-2 text-meta leading-relaxed text-gray-500">
                      No coding agents are installed yet. Install Claude Code, Codex, Gemini CLI
                      or Ollama and they will appear here automatically.
                    </div>
                  )}
                  {(agents ?? []).map((a) => {
                    const checked = selectedParticipants.includes(a.name);
                    const c = colorFor(a.name);
                    // ANY LLM: only the 4 real chat participants take a
                    // model override -- aider/cursor-agent have neither
                    // model_flag nor {model} wiring.
                    const isLocal = a.name === "local-ollama";
                    // From the registry, not from a list typed here. This was
                    // `["claude-code","codex","gemini-cli"].includes(a.name)`, which meant aider got
                    // no model picker despite its own --help documenting `--model MODEL`, and any
                    // agent added later would silently get none either. `supports_model` is computed
                    // where the answer actually lives (a model_flag, or a {model} slot in the argv
                    // template). Defaulted for an older backend rather than assumed true.
                    const supportsModel = a.supportsModel ?? isLocal;
                    return (
                      <div
                        key={a.name}
                        className={`flex w-full flex-col gap-1.5 rounded-xl border px-3 py-2.5 transition-colors ${
                          checked
                            ? `${c.border} ${c.bg}`
                            : "border-white/8 bg-white/[0.02] hover:bg-white/[0.03]"
                        }`}
                      >
                        <button
                          type="button"
                          onClick={() => a.installed && toggleParticipant(a.name)}
                          disabled={!a.installed}
                          className="flex w-full items-center gap-3 text-left disabled:cursor-not-allowed disabled:opacity-40"
                        >
                          <span className={`h-2 w-2 shrink-0 rounded-full ${c.dot}`} />
                          {checked ? (
                            <CheckCircle2 size={14} className={`shrink-0 ${c.text}`} />
                          ) : (
                            <Circle size={14} className="shrink-0 text-gray-700" />
                          )}
                          <div className="min-w-0 flex-1">
                            <div className="font-mono text-label font-bold text-white">
                              {a.name}
                            </div>
                            <div className="truncate text-meta text-gray-600">
                              {a.name === "corpus"
                                ? "hard-won lessons + this session's oracle history"
                                : a.installed
                                  ? `probe: ${a.probe}`
                                  : a.installHint}
                            </div>
                          </div>
                        </button>
                        {checked && supportsModel && (
                          <div className="pl-5">
                            {isLocal && !customLocalModel.has(a.name) ? (
                              <select
                                value={modelOverrides[a.name] ?? ""}
                                onChange={(e) => {
                                  // A closed list of installed tags cannot name a
                                  // model that is not pulled yet, or one that does
                                  // not exist yet -- so there is an explicit escape
                                  // to free text. Ryan: "users should be able to add
                                  // future llms that dont have access at the moment."
                                  if (e.target.value === CUSTOM_MODEL_SENTINEL) {
                                    setCustomLocalModel((prev) => new Set(prev).add(a.name));
                                    return;
                                  }
                                  setModelOverride(a.name, e.target.value);
                                }}
                                className="w-full rounded-md border border-white/8 bg-black/30 px-2 py-1 font-mono text-meta text-gray-400 outline-none focus:border-fuchsia-400/40"
                              >
                                <option value="">
                                  default (env DETERMINEX_LOCAL_BUILDER_MODEL)
                                </option>
                                {ollamaModels.map((m) => (
                                  <option key={m} value={m}>
                                    {m}
                                  </option>
                                ))}
                                <option value={CUSTOM_MODEL_SENTINEL}>type a model name...</option>
                              </select>
                            ) : (a.models?.length ?? 0) > 0 && !customLocalModel.has(a.name) ? (
                              // THREE NAMED CHOICES, not a memory test. This was a free-text
                              // box whose placeholder read "e.g. gemini-2.5-pro" -- so using a
                              // different model required knowing that Claude has three current
                              // models, Google four and OpenAI several, and typing one exactly.
                              // The same three words appear for every provider so the
                              // vocabulary is learned once and transfers. The escape to free
                              // text stays, because a closed list cannot name a model that does
                              // not exist yet -- Ryan: "users should be able to add future llms
                              // that dont have access at the moment."
                              <select
                                value={modelOverrides[a.name] ?? ""}
                                onChange={(e) => {
                                  if (e.target.value === CUSTOM_MODEL_SENTINEL) {
                                    setCustomLocalModel((prev) => new Set(prev).add(a.name));
                                    return;
                                  }
                                  setModelOverride(a.name, e.target.value);
                                }}
                                className="w-full rounded-md border border-white/8 bg-black/30 px-2 py-1 text-meta text-gray-400 outline-none focus:border-fuchsia-400/40"
                              >
                                <option value="">Default — whatever {a.name} normally uses</option>
                                {a.models?.map((m) => (
                                  <option key={m.model} value={m.model}>
                                    {m.label}
                                  </option>
                                ))}
                                <option value={CUSTOM_MODEL_SENTINEL}>type a model name...</option>
                              </select>
                            ) : (
                              <input
                                type="text"
                                value={modelOverrides[a.name] ?? ""}
                                onChange={(e) => setModelOverride(a.name, e.target.value)}
                                placeholder={`model name for ${a.name} (optional)`}
                                className="w-full rounded-md border border-white/8 bg-black/30 px-2 py-1 font-mono text-meta text-gray-400 placeholder:text-gray-700 outline-none focus:border-fuchsia-400/40"
                              />
                            )}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>

                <div className="flex items-center gap-2">
                  <span className="text-eyebrow font-black uppercase tracking-widest text-gray-600">
                    Turn-taking
                  </span>
                  <button
                    type="button"
                    onClick={() => setTurnMode("broadcast")}
                    className={`rounded-lg border px-2.5 py-1 text-eyebrow font-bold uppercase tracking-wide ${
                      turnMode === "broadcast"
                        ? "border-fuchsia-400/40 bg-fuchsia-950/30 text-fuchsia-300"
                        : "border-white/8 text-gray-500"
                    }`}
                  >
                    Broadcast
                  </button>
                  <button
                    type="button"
                    onClick={() => setTurnMode("mention")}
                    className={`rounded-lg border px-2.5 py-1 text-eyebrow font-bold uppercase tracking-wide ${
                      turnMode === "mention"
                        ? "border-fuchsia-400/40 bg-fuchsia-950/30 text-fuchsia-300"
                        : "border-white/8 text-gray-500"
                    }`}
                  >
                    @Mention only
                  </button>
                </div>

                <button
                  type="button"
                  onClick={() => void createSession()}
                  disabled={creating || selectedParticipants.length === 0 || !workspacePath}
                  className="flex items-center justify-center gap-1.5 rounded-lg border border-fuchsia-400/25 bg-fuchsia-950/20 px-3 py-2 text-eyebrow font-black uppercase tracking-widest text-fuchsia-300 transition hover:bg-fuchsia-900/30 disabled:opacity-40"
                >
                  {creating ? <Loader2 size={11} className="animate-spin" /> : <Plus size={11} />}
                  Start Session
                </button>
                {!workspacePath && (
                  <p className="text-meta text-amber-400/80">No workspace open.</p>
                )}
              </div>
            ) : (
              <div className="flex min-h-0 flex-1 flex-col gap-3">
                {/* Mission Plan -- its own surface, not nested in the chat scroll. */}
                <div className="shrink-0 rounded-xl border border-white/10 bg-white/[0.02]">
                  <div className="flex w-full items-center justify-between px-3 py-2">
                    <button
                      type="button"
                      onClick={() => setPlanOpen((o) => !o)}
                      className="flex flex-1 items-center gap-1.5 text-left text-eyebrow font-black uppercase tracking-widest text-gray-400"
                    >
                      <FileText size={11} /> Mission Plan
                      <span className="text-gray-700">
                        — every participant reads this exact doc
                      </span>
                    </button>
                    <button
                      type="button"
                      onClick={() => void resyncPlan()}
                      disabled={planResyncing || !workspacePath}
                      title="Pull fresh content from this workspace's CLAUDE.md/PROJECT.md into the plan"
                      className="flex items-center gap-1 rounded-md px-1.5 py-0.5 text-eyebrow font-bold uppercase tracking-wide text-gray-600 hover:bg-white/5 hover:text-gray-400 disabled:opacity-30"
                    >
                      {planResyncing ? (
                        <Loader2 size={10} className="animate-spin" />
                      ) : (
                        <RefreshCw size={10} />
                      )}
                      Resync
                    </button>
                    <button
                      type="button"
                      onClick={() => setPlanOpen((o) => !o)}
                      className="ml-2 text-meta text-gray-600"
                    >
                      {planOpen ? "hide" : "show"}
                    </button>
                  </div>
                  {planOpen && (
                    <div className="border-t border-white/5 px-3 py-2.5">
                      {planEditing ? (
                        <>
                          <textarea
                            value={planDraft}
                            onChange={(e) => setPlanDraft(e.target.value)}
                            rows={6}
                            className="w-full resize-y rounded-lg border border-white/8 bg-black/30 px-2.5 py-2 font-mono text-label text-white/80 outline-none focus:border-fuchsia-400/40"
                          />
                          <div className="mt-2 flex gap-2">
                            <button
                              type="button"
                              onClick={() => void savePlan()}
                              disabled={planSaving}
                              className="flex items-center gap-1.5 rounded-lg border border-emerald-400/25 bg-emerald-950/20 px-2.5 py-1.5 text-eyebrow font-black uppercase tracking-widest text-emerald-300 hover:bg-emerald-900/30 disabled:opacity-40"
                            >
                              {planSaving ? (
                                <Loader2 size={10} className="animate-spin" />
                              ) : (
                                <Save size={10} />
                              )}
                              Save
                            </button>
                            <button
                              type="button"
                              onClick={() => setPlanEditing(false)}
                              className="rounded-lg border border-white/8 px-2.5 py-1.5 text-eyebrow font-bold uppercase tracking-widest text-gray-500 hover:bg-white/5"
                            >
                              Cancel
                            </button>
                          </div>
                        </>
                      ) : (
                        <>
                          <pre className="max-h-32 overflow-y-auto whitespace-pre-wrap font-mono text-label leading-relaxed text-gray-400">
                            {plan}
                          </pre>
                          <button
                            type="button"
                            onClick={startEditingPlan}
                            className="mt-2 flex items-center gap-1.5 rounded-lg border border-white/8 px-2.5 py-1.5 text-eyebrow font-bold uppercase tracking-widest text-gray-500 hover:bg-white/5"
                          >
                            <Pencil size={10} /> Edit
                          </button>
                        </>
                      )}
                    </div>
                  )}
                </div>

                <div className="flex shrink-0 items-center justify-between gap-2">
                  {pending.length > 0 ? (
                    <div className="flex items-center gap-1.5 rounded-lg border border-fuchsia-400/15 bg-fuchsia-950/10 px-2.5 py-1.5 text-meta text-fuchsia-300/80">
                      <Radio size={11} className="animate-pulse" />
                      up next:{" "}
                      {pending
                        .map((name) => (
                          <span key={name} className={colorFor(name).text}>
                            {name}
                          </span>
                        ))
                        .reduce(
                          (acc, el, i) => (i === 0 ? [el] : [...acc, " → ", el]),
                          [] as ReactNode[]
                        )}
                    </div>
                  ) : (
                    <span />
                  )}
                  {/* Ryan: "i want it all inline for those that want it, i want it
                      split out for those that want it" -- same underlying state
                      (transcript + live), two renderings. */}
                  <div className="flex shrink-0 gap-1 rounded-lg border border-white/8 p-0.5">
                    <button
                      type="button"
                      onClick={() => setViewMode("inline")}
                      title="Inline — live agent activity nested in the chat scroll"
                      className={`flex items-center gap-1 rounded-md px-2 py-1 text-eyebrow font-bold uppercase tracking-wide ${
                        viewMode === "inline"
                          ? "bg-white/10 text-white"
                          : "text-gray-600 hover:text-gray-400"
                      }`}
                    >
                      <Rows size={11} /> Inline
                    </button>
                    <button
                      type="button"
                      onClick={() => setViewMode("lanes")}
                      title="Lanes — each agent's live work in its own colored lane, separate from the chat"
                      className={`flex items-center gap-1 rounded-md px-2 py-1 text-eyebrow font-bold uppercase tracking-wide ${
                        viewMode === "lanes"
                          ? "bg-white/10 text-white"
                          : "text-gray-600 hover:text-gray-400"
                      }`}
                    >
                      <Columns size={11} /> Lanes
                    </button>
                  </div>
                </div>

                {/* Lanes mode: each agent's live work gets its own colored
                    lane, separate from (not nested in) the chat transcript. */}
                {viewMode === "lanes" && liveEntries.length > 0 && (
                  <div className="flex shrink-0 gap-2 overflow-x-auto no-scrollbar pb-1">
                    {liveEntries.map(([turnId, l]) => {
                      const c = colorFor(l.agent);
                      return (
                        <div
                          key={turnId}
                          className={`w-64 shrink-0 rounded-xl border p-2.5 ${c.border} ${c.bg}`}
                        >
                          <div className="mb-1 flex items-center gap-1.5">
                            <span className={`h-1.5 w-1.5 rounded-full ${c.dot}`} />
                            <span className={`font-mono text-meta font-bold ${c.text}`}>
                              {l.agent}
                            </span>
                            <Loader2 size={10} className="ml-auto animate-spin text-gray-600" />
                          </div>
                          <pre className="max-h-32 overflow-y-auto whitespace-pre-wrap font-mono text-meta text-gray-500">
                            {l.text.slice(-2000)}
                          </pre>
                        </div>
                      );
                    })}
                  </div>
                )}

                <div
                  ref={scrollRef}
                  className="min-h-0 flex-1 space-y-2.5 overflow-y-auto no-scrollbar"
                >
                  {transcript.map((t) => (
                    <TurnBubble key={t.turnId} turn={t} workspacePath={workspacePath} />
                  ))}
                  {viewMode === "inline" &&
                    liveEntries.map(([turnId, l]) => {
                      const c = colorFor(l.agent);
                      return (
                        <div key={turnId} className={`rounded-xl border p-3 ${c.border} ${c.bg}`}>
                          <div className="mb-1 flex items-center gap-1.5">
                            <span className={`h-1.5 w-1.5 rounded-full ${c.dot}`} />
                            <Bot size={12} className={c.text} />
                            <span className={`font-mono text-meta font-bold ${c.text}`}>
                              {l.agent}
                            </span>
                            <Loader2 size={10} className="animate-spin text-gray-600" />
                          </div>
                          <pre className="max-h-40 overflow-y-auto whitespace-pre-wrap font-mono text-meta text-gray-500">
                            {l.text.slice(-4000)}
                          </pre>
                        </div>
                      );
                    })}
                </div>

                <div className="relative shrink-0">
                  {mentionSuggestions.length > 0 && (
                    <div className="absolute bottom-full mb-1 flex gap-1 rounded-lg border border-white/10 bg-black/80 p-1.5">
                      {mentionSuggestions.map((name) => (
                        <button
                          key={name}
                          type="button"
                          onClick={() => applyMention(name)}
                          className={`rounded-md bg-white/5 px-2 py-0.5 font-mono text-meta hover:bg-white/10 ${colorFor(name).text}`}
                        >
                          @{name}
                        </button>
                      ))}
                    </div>
                  )}
                  <div className="flex items-end gap-2">
                    <textarea
                      value={composer}
                      onChange={(e) => setComposer(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" && !e.shiftKey) {
                          e.preventDefault();
                          void send();
                        }
                      }}
                      placeholder="Message the room... @name to address one agent directly"
                      rows={2}
                      className="w-full resize-none rounded-lg border border-white/8 bg-black/30 px-2.5 py-2 text-label text-white/80 placeholder:text-gray-700 outline-none focus:border-fuchsia-400/40"
                    />
                    <button
                      type="button"
                      onClick={() => void send()}
                      disabled={sending || !composer.trim()}
                      className="flex shrink-0 items-center gap-1.5 rounded-lg border border-fuchsia-400/25 bg-fuchsia-950/20 px-3 py-2.5 text-eyebrow font-black uppercase tracking-widest text-fuchsia-300 transition hover:bg-fuchsia-900/30 disabled:opacity-40"
                    >
                      {sending ? (
                        <Loader2 size={11} className="animate-spin" />
                      ) : (
                        <Send size={11} />
                      )}
                    </button>
                  </div>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

// Always-visible roster strip: "who's online, what's their plan/credits at"
// -- answers that literally, not with a fabricated dollar number. Two tiers
// of truth per chip: the passive dot+plan (free, auto-refreshed every 30s)
// and, only on explicit click, a real live probe (genuine model call) whose
// result can say things no status file can, like a depleted-billing error.
function AgentRosterBar({
  agents,
  statusMap,
  probing,
  probeLive,
  probeResult,
  onTest,
}: {
  agents: CodingAgentInfo[];
  statusMap: Record<string, AgentStatusEntry>;
  probing: Record<string, boolean>;
  probeLive: Record<string, string>;
  probeResult: Record<string, AgentProbeCompleteEvent>;
  onTest: (name: string) => void;
}) {
  // aider/cursor-agent/local-ollama clutter this strip when not installed
  // and have no meaningful "online" concept beyond installed -- the roster
  // is about the three real chat participants with real auth state.
  // Every registered agent, not a hardcoded three. The strip used to list claude-code, codex and
  // gemini-cli only, so aider, cursor-agent and local-ollama had no readiness dot and no Test button
  // -- you could add them to a session from the picker below and never find out whether they worked.
  // `corpus` is excluded because it is not a spawnable CLI (no probe, no auth, handled entirely in
  // agent_chat.rs), so "readiness" and a live probe are meaningless for it.
  const roster = agents.filter((a) => a.name !== "corpus");
  if (roster.length === 0) return null;

  return (
    <div className="flex shrink-0 flex-wrap gap-1.5 border-b border-white/10 pb-3">
      {roster.map((a) => {
        const c = colorFor(a.name);
        const s = statusMap[a.name];
        const result = probeResult[a.name];
        const isProbing = !!probing[a.name];

        // Driven by the persisted readiness state, not by `loggedIn` and not by the live event.
        //
        // The old fallback was `loggedIn ? emerald : ...`, which painted gemini-cli green while
        // Google was refusing the client outright -- valid credentials, revoked product access, and
        // the dot could not tell the difference because the field it read could not either. The
        // live `result` still wins while a probe is on screen, but it is an event: it vanished on
        // the next render and the dot went back to green. Readiness is remembered, so the answer
        // survives a re-render and a restart.
        const readiness = result
          ? (PROBE_TO_READINESS[result.status] ?? "failed")
          : (s?.readiness ?? (a.installed ? "credentials_unverified" : "not_installed"));
        const dotClass = READINESS[readiness]?.dot ?? "bg-gray-700";
        const readinessLabel = READINESS[readiness]?.label ?? readiness;

        return (
          <div
            key={a.name}
            className={`flex min-w-0 flex-col gap-1 rounded-xl border px-2.5 py-2 ${c.border} ${c.bg}`}
          >
            <div className="flex items-center gap-1.5">
              <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${dotClass}`} />
              <span className={`font-mono text-label font-bold ${c.text}`}>{a.name}</span>
              <span
                className={`shrink-0 text-meta font-bold ${READINESS[readiness]?.tone ?? "text-gray-500"}`}
                title={s?.readinessEvidence || ""}
              >
                {readinessLabel}
              </span>
              <span className="truncate text-meta text-gray-600">
                {a.installed ? s?.plan || "" : ""}
              </span>
              <button
                type="button"
                onClick={() => onTest(a.name)}
                disabled={!a.installed || isProbing}
                title="Fire a real minimal prompt at this agent and show exactly what comes back"
                className="ml-auto flex shrink-0 items-center gap-1 rounded-md border border-white/8 px-1.5 py-0.5 text-eyebrow font-bold uppercase tracking-wide text-gray-500 hover:bg-white/5 disabled:opacity-30"
              >
                {isProbing ? <Loader2 size={9} className="animate-spin" /> : <Zap size={9} />}
                Test
              </button>
            </div>
            {!isProbing && !result && (s?.readinessEvidence || s?.detail) && (
              // The evidence, not just the verdict. A state of "provider refused" is only actionable
              // if it also says what the provider said and when.
              <p
                className="truncate text-meta text-gray-600"
                title={s?.readinessEvidence || s?.detail}
              >
                {s?.readinessEvidence || s?.detail}
              </p>
            )}
            {isProbing && (
              <pre className="max-h-16 max-w-[220px] overflow-y-auto whitespace-pre-wrap font-mono text-meta text-gray-500">
                {(probeLive[a.name] ?? "").slice(-500) || "waiting for response…"}
              </pre>
            )}
            {result && !isProbing && (
              <div
                className={`flex items-start gap-1 text-meta ${
                  result.status === "ok"
                    ? "text-emerald-400"
                    : result.status === "quota_exhausted" || result.status === "timeout"
                      ? "text-amber-400"
                      : "text-red-400"
                }`}
              >
                {result.status === "ok" ? (
                  <ShieldCheck size={10} className="mt-px shrink-0" />
                ) : (
                  <AlertTriangle size={10} className="mt-px shrink-0" />
                )}
                <span className="max-w-[200px]">
                  <span className="font-bold uppercase tracking-wide">
                    {result.status.replace("_", " ")}
                  </span>
                  {result.detail ? `: ${result.detail}` : ""}
                </span>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

// A chat turn never writes to the workspace -- it proposes. Measured 2026-07-31: one conversational
// turn in six, asked only "What is the capital of France?", silently rewrote a source file, so the
// write was made structurally unavailable rather than merely discouraged. The agent emits a
// validated before/after payload and the user approves it here.
//
// The payload is stripped out of the displayed text: it carries whole file contents, which would
// bury the agent's actual reply under a wall of JSON in a 48-line-tall bubble.
const PROPOSAL_BEGIN = "<<<DETERMINEX_PROPOSED_EDITS";
const PROPOSAL_END = "DETERMINEX_PROPOSED_EDITS>>>";

type ProposedFile = { path: string; before: string; after: string };

function parseProposals(text: string): ProposedFile[] {
  const out: ProposedFile[] = [];
  let cursor = 0;
  for (;;) {
    const start = text.indexOf(PROPOSAL_BEGIN, cursor);
    if (start < 0) return out;
    const bodyStart = start + PROPOSAL_BEGIN.length;
    const end = text.indexOf(PROPOSAL_END, bodyStart);
    if (end < 0) return out;
    cursor = end + PROPOSAL_END.length;
    try {
      const payload = JSON.parse(text.slice(bodyStart, end).trim());
      if (payload?.schema !== "determinex-chat-proposed-edits-v1") continue;
      for (const f of payload.files ?? []) {
        if (
          typeof f?.path === "string" &&
          typeof f?.before === "string" &&
          typeof f?.after === "string"
        ) {
          out.push(f as ProposedFile);
        }
      }
    } catch {
      // A malformed block must not blank the turn it is attached to.
      continue;
    }
  }
}

function stripProposals(text: string): string {
  let out = text;
  for (;;) {
    const start = out.indexOf(PROPOSAL_BEGIN);
    if (start < 0) return out.trimEnd();
    const end = out.indexOf(PROPOSAL_END, start);
    if (end < 0) return out.slice(0, start).trimEnd();
    out = out.slice(0, start) + out.slice(end + PROPOSAL_END.length);
  }
}

function ProposedEdits({
  turn,
  workspacePath,
  files,
}: {
  turn: ChatTurnDto;
  workspacePath: string;
  files: ProposedFile[];
}) {
  const [state, setState] = useState<"idle" | "applying" | "applied">("idle");
  const [error, setError] = useState<string | null>(null);

  async function approve() {
    setState("applying");
    setError(null);
    try {
      const applied = await invoke<string[]>("agent_chat_apply_proposal", {
        sessionId: turn.sessionId,
        turnId: turn.turnId,
        workspace: workspacePath,
      });
      setState("applied");
      if (applied.length === 0) setError("nothing was applied");
    } catch (e) {
      // Surfaced verbatim on purpose: the two refusals a user can hit here are "the file changed
      // since this was proposed" and "that path leaves the workspace", and both are things they
      // need to read rather than a generic failure toast.
      setState("idle");
      setError(String(e));
    }
  }

  return (
    <div className="mt-2 rounded-lg border border-amber-500/25 bg-amber-950/10 p-2">
      <div className="mb-1.5 flex items-center gap-1.5">
        <FileDiff size={11} className="text-amber-400" />
        <span className="font-mono text-meta font-bold text-amber-300">
          {state === "applied" ? "changes applied" : "proposed changes — not written"}
        </span>
      </div>
      <ul className="mb-2 space-y-0.5">
        {files.map((f) => (
          <li key={f.path} className="font-mono text-meta text-gray-400">
            {f.path}{" "}
            <span className="text-gray-600">
              ({f.before.split("\n").length} → {f.after.split("\n").length} lines)
            </span>
          </li>
        ))}
      </ul>
      {state !== "applied" && (
        <button
          type="button"
          onClick={approve}
          disabled={state === "applying" || !workspacePath}
          className="rounded-md border border-amber-500/30 bg-amber-500/10 px-2 py-1 font-mono text-meta text-amber-200 hover:bg-amber-500/20 disabled:opacity-40"
        >
          {state === "applying" ? "applying…" : "Apply these changes"}
        </button>
      )}
      {error && <p className="mt-1 font-mono text-meta text-red-300">{error}</p>}
    </div>
  );
}

function TurnBubble({ turn, workspacePath = "" }: { turn: ChatTurnDto; workspacePath?: string }) {
  const isUser = turn.speakerKind === "user";
  const c = colorFor(turn.speaker);
  const proposals = isUser ? [] : parseProposals(turn.rawOutput);
  return (
    <div
      className={`rounded-xl border p-3 ${
        isUser
          ? "border-white/10 bg-white/[0.03]"
          : turn.verified
            ? `${c.border} bg-emerald-950/10`
            : "border-red-500/20 bg-red-950/10"
      }`}
    >
      <div className="mb-1.5 flex items-center gap-1.5">
        {isUser ? (
          <span className="font-mono text-meta font-bold text-gray-300">you</span>
        ) : (
          <>
            <span className={`h-1.5 w-1.5 rounded-full ${c.dot}`} />
            <Bot size={12} className={c.text} />
            <span className={`font-mono text-meta font-bold ${c.text}`}>{turn.speaker}</span>
            {turn.verified ? (
              <ShieldCheck size={11} className="text-emerald-400" />
            ) : (
              <XCircle size={11} className="text-red-400" />
            )}
            <span className="text-meta text-gray-600">{turn.note}</span>
          </>
        )}
        {turn.addressedTo.length > 0 && (
          <span className="text-meta text-gray-600">
            → {turn.addressedTo.map((a) => `@${a}`).join(" ")}
          </span>
        )}
      </div>
      <pre className="max-h-48 overflow-y-auto whitespace-pre-wrap font-mono text-meta leading-relaxed text-gray-400">
        {(isUser ? turn.taskPrompt : stripProposals(turn.rawOutput)).slice(0, 4000)}
      </pre>
      {proposals.length > 0 && (
        <ProposedEdits turn={turn} workspacePath={workspacePath} files={proposals} />
      )}
      {!isUser && turn.oracle && (
        <p className="mt-1 text-meta text-gray-600 font-mono">
          oracle: {turn.oracle} ({turn.nFailures} failures)
        </p>
      )}
    </div>
  );
}
