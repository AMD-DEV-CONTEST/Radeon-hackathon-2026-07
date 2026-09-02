"use client";
import { useCallback, useEffect, useState } from "react";
import {
  BadgeCheck,
  Circle,
  ExternalLink,
  Fuel,
  GitBranch,
  Loader2,
  Plug,
  Plus,
  Trash2,
  User,
  Wallet,
} from "lucide-react";
import { isTauri, invokeSafe, invokeWrite } from "@/lib/api";
import { GitHubSignIn } from "./GitHubSignIn";

type CliLoginStatus = Record<string, boolean>;

type PassportProfile = {
  provider: string;
  username: string;
  displayName: string;
  avatarUrl: string;
  profileUrl: string;
  fetchedAt: string;
};

type UsageProviderSummary = {
  calls: number;
  tokens_in: number;
  tokens_out: number;
  est_usd: number;
  models: string[];
};

type UsageSummary = {
  exists: boolean;
  window_hours: number | null;
  providers: Record<string, UsageProviderSummary>;
  total_est_usd: number;
  total_calls: number;
};

type CliSubscriptionEntry = { available: boolean; reason: string };
type CliSubscriptionStatus = Record<string, CliSubscriptionEntry>;

const CLI_LABELS: Record<string, string> = {
  "claude-code": "Claude Code",
  codex: "Codex",
  "gemini-cli": "Gemini CLI",
};

const CONNECTABLE_PROVIDERS = [
  { id: "github", label: "GitHub" },
  { id: "huggingface", label: "HuggingFace" },
];

export function PassportPanel() {
  const [cliStatus, setCliStatus] = useState<CliLoginStatus | null>(null);
  const [profiles, setProfiles] = useState<PassportProfile[] | null>(null);
  const [usage, setUsage] = useState<UsageSummary | null>(null);
  const [cliUsage, setCliUsage] = useState<CliSubscriptionStatus | null>(null);
  const [usageWindow, setUsageWindow] = useState<24 | 168 | null>(24);

  const [connectProvider, setConnectProvider] = useState("github");
  const [tokenInput, setTokenInput] = useState("");
  const [connecting, setConnecting] = useState(false);
  const [connectError, setConnectError] = useState<string | null>(null);

  const refreshCliStatus = useCallback(async () => {
    const res = await invokeSafe<CliLoginStatus>("passport_cli_login_status", {});
    setCliStatus(res ?? {});
  }, []);

  const refreshProfiles = useCallback(async () => {
    const res = await invokeSafe<PassportProfile[]>("passport_list", {});
    setProfiles(res ?? []);
  }, []);

  const refreshUsage = useCallback(async (windowHours: 24 | 168 | null) => {
    const res = await invokeSafe<UsageSummary>("passport_usage_summary", { windowHours });
    setUsage(res);
  }, []);

  const refreshCliUsage = useCallback(async () => {
    const res = await invokeSafe<CliSubscriptionStatus>("passport_cli_subscription_status", {});
    setCliUsage(res);
  }, []);

  useEffect(() => {
    void refreshCliStatus();
    void refreshProfiles();
    void refreshCliUsage();
  }, [refreshCliStatus, refreshProfiles, refreshCliUsage]);

  useEffect(() => {
    void refreshUsage(usageWindow);
  }, [usageWindow, refreshUsage]);

  const connect = async () => {
    if (!tokenInput.trim()) return;
    setConnecting(true);
    setConnectError(null);
    try {
      const profile = await invokeSafe<PassportProfile>("passport_connect", {
        provider: connectProvider,
        token: tokenInput.trim(),
      });
      if (profile) {
        setTokenInput("");
        void refreshProfiles();
      } else {
        setConnectError("Connection failed -- check the token and try again.");
      }
    } finally {
      setConnecting(false);
    }
  };

  const disconnect = async (provider: string) => {
    setConnectError(null);
    try {
      // Void-returning, so under invokeSafe a refused disconnect looked exactly
      // like a successful one -- the row simply stayed connected after the
      // refresh with no explanation, which reads as a UI glitch rather than a
      // backend refusal.
      await invokeWrite("passport_disconnect", { provider });
    } catch (e) {
      setConnectError(`Could not disconnect ${provider}: ${e}`);
    }
    void refreshProfiles();
  };

  const connectedIds = new Set((profiles ?? []).map((p) => p.provider));

  return (
    <div className="relative flex h-full min-h-0 flex-col overflow-hidden p-5">
      <div className="relative z-10 flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto no-scrollbar">
        <div className="border-b border-white/10 pb-4">
          <div className="mb-2 flex items-center gap-2 text-meta font-black uppercase tracking-widest text-amber-400">
            <BadgeCheck size={13} /> Identity &amp; Access
          </div>
          <h2
            className="text-hero font-black leading-tight text-[var(--determinex-text)]"
            style={{ fontFamily: "var(--determinex-font-display)" }}
          >
            Passport
          </h2>
          <p className="mt-1 text-label leading-relaxed text-gray-600">
            Where your agents&apos; access lives. Native CLI logins (Claude Code, Codex, Gemini CLI)
            already run their own browser-based sign-in on this machine -- shown here as status
            only, never read or moved. Connected services below use a token you provide once to pull
            in a real profile, then get injected as an env var into that one agent&apos;s process at
            spawn time -- never into a chat message or a cloud model&apos;s context.
          </p>
        </div>

        {!isTauri() ? (
          <div className="flex flex-1 flex-col items-center justify-center gap-2 text-center opacity-40">
            <p className="text-label text-gray-500">
              Browser mode cannot read local credential state
            </p>
          </div>
        ) : (
          <>
            {/* Native CLI login status */}
            <section className="space-y-1.5">
              <div className="text-eyebrow font-black uppercase tracking-widest text-gray-600">
                Native CLI Sessions
              </div>
              {cliStatus === null ? (
                <Loader2 size={14} className="animate-spin text-gray-600" />
              ) : (
                Object.entries(cliStatus).map(([name, loggedIn]) => (
                  <div
                    key={name}
                    className="flex items-center gap-3 rounded-xl border border-white/8 bg-white/[0.02] px-3 py-2.5"
                  >
                    {loggedIn ? (
                      <BadgeCheck size={14} className="shrink-0 text-emerald-400" />
                    ) : (
                      <Circle size={14} className="shrink-0 text-gray-700" />
                    )}
                    <div className="min-w-0 flex-1">
                      <div className="font-mono text-label font-bold text-white">
                        {CLI_LABELS[name] ?? name}
                      </div>
                      <div className="text-meta text-gray-600">
                        {loggedIn ? "signed in on this machine" : "not signed in"}
                      </div>
                    </div>
                  </div>
                ))
              )}
            </section>

            {/* Real OAuth sign-in, above the paste-a-token flow it replaces.
                Device Flow needs no client secret, which a desktop app cannot
                keep anyway. The token lands in the same GITHUB_TOKEN row a
                pasted PAT uses, so everything downstream is unchanged. */}
            <section className="space-y-1.5">
              <div className="text-eyebrow font-black uppercase tracking-widest text-gray-600">
                Sign in
              </div>
              <GitHubSignIn
                connected={(profiles ?? []).some((p) => p.provider?.toLowerCase() === "github")}
                onChange={refreshProfiles}
              />
            </section>

            {/* Connected service profiles */}
            <section className="space-y-1.5">
              <div className="text-eyebrow font-black uppercase tracking-widest text-gray-600">
                Connected Services
              </div>
              {(profiles ?? []).map((p) => (
                <div
                  key={p.provider}
                  className="flex items-center gap-3 rounded-xl border border-emerald-500/20 bg-emerald-950/10 px-3 py-2.5"
                >
                  {p.avatarUrl ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={p.avatarUrl} alt="" className="h-8 w-8 shrink-0 rounded-full" />
                  ) : (
                    <User size={16} className="shrink-0 text-gray-500" />
                  )}
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-1.5 font-mono text-label font-bold text-white">
                      {p.displayName || p.username}
                      {p.profileUrl && (
                        <a
                          href={p.profileUrl}
                          target="_blank"
                          rel="noreferrer"
                          className="text-gray-600 hover:text-gray-400"
                        >
                          <ExternalLink size={10} />
                        </a>
                      )}
                    </div>
                    <div className="text-meta text-gray-600">
                      {p.provider} · @{p.username}
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => void disconnect(p.provider)}
                    className="shrink-0 rounded-md p-1.5 text-gray-600 hover:bg-red-950/30 hover:text-red-400"
                    title="Disconnect"
                  >
                    <Trash2 size={12} />
                  </button>
                </div>
              ))}

              <div className="rounded-xl border border-white/8 bg-white/[0.02] p-3">
                <div className="mb-2 flex items-center gap-1.5 text-eyebrow font-black uppercase tracking-widest text-gray-500">
                  <Plug size={11} /> Connect a service
                </div>
                <div className="flex gap-1.5">
                  {CONNECTABLE_PROVIDERS.map((p) => (
                    <button
                      key={p.id}
                      type="button"
                      onClick={() => setConnectProvider(p.id)}
                      className={`rounded-lg border px-2.5 py-1 text-eyebrow font-bold uppercase tracking-wide ${
                        connectProvider === p.id
                          ? "border-amber-400/40 bg-amber-950/30 text-amber-300"
                          : "border-white/8 text-gray-500"
                      }`}
                    >
                      {p.id === "github" && <GitBranch size={10} className="mr-1 inline -mt-px" />}
                      {p.label}
                      {connectedIds.has(p.id) && " ✓"}
                    </button>
                  ))}
                </div>
                <div className="mt-2 flex gap-2">
                  <input
                    type="password"
                    value={tokenInput}
                    onChange={(e) => setTokenInput(e.target.value)}
                    placeholder={`${connectProvider === "github" ? "GitHub personal access token" : "HuggingFace access token"}`}
                    className="flex-1 rounded-lg border border-white/8 bg-black/30 px-2.5 py-1.5 text-label text-white/80 placeholder:text-gray-700 outline-none focus:border-amber-400/40"
                  />
                  <button
                    type="button"
                    onClick={() => void connect()}
                    disabled={connecting || !tokenInput.trim()}
                    className="flex shrink-0 items-center gap-1.5 rounded-lg border border-amber-400/25 bg-amber-950/20 px-3 py-1.5 text-eyebrow font-black uppercase tracking-widest text-amber-300 hover:bg-amber-900/30 disabled:opacity-40"
                  >
                    {connecting ? (
                      <Loader2 size={11} className="animate-spin" />
                    ) : (
                      <Plus size={11} />
                    )}
                  </button>
                </div>
                {connectError && <p className="mt-1.5 text-meta text-red-400">{connectError}</p>}
              </div>
            </section>

            {/* Gas Gauge */}
            <section className="space-y-1.5">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-1.5 text-eyebrow font-black uppercase tracking-widest text-gray-600">
                  <Fuel size={11} /> Usage
                </div>
                <div className="flex gap-1">
                  {(
                    [
                      [24, "24h"],
                      [168, "7d"],
                      [null, "all"],
                    ] as const
                  ).map(([val, label]) => (
                    <button
                      key={label}
                      type="button"
                      onClick={() => setUsageWindow(val)}
                      className={`rounded-md px-2 py-0.5 text-eyebrow font-bold uppercase ${
                        usageWindow === val
                          ? "bg-white/10 text-white"
                          : "text-gray-600 hover:text-gray-400"
                      }`}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              </div>

              {usage && usage.exists ? (
                <div className="rounded-xl border border-white/8 bg-white/[0.02] p-3">
                  <div className="mb-2 flex items-center gap-1.5">
                    <Wallet size={14} className="text-amber-400" />
                    <span className="font-mono text-body font-black text-white">
                      ${usage.total_est_usd.toFixed(4)}
                    </span>
                    <span className="text-meta text-gray-600">
                      est. spend · {usage.total_calls} call{usage.total_calls === 1 ? "" : "s"}
                    </span>
                  </div>
                  <div className="space-y-1">
                    {Object.entries(usage.providers).map(([provider, stats]) => (
                      <div key={provider} className="flex items-center justify-between text-meta">
                        <span className="font-mono text-gray-400">{provider}</span>
                        <span className="text-gray-600">
                          {stats.calls} calls ·{" "}
                          {(stats.tokens_in + stats.tokens_out).toLocaleString()} tok · $
                          {stats.est_usd.toFixed(4)}
                        </span>
                      </div>
                    ))}
                  </div>
                  <p className="mt-2 text-meta text-gray-700">
                    Covers calls made through this project&apos;s own generation pipeline
                    (logs/api_ledger/providers.jsonl). See below for CLI subscriptions.
                  </p>
                </div>
              ) : (
                <p className="text-meta text-gray-500">
                  No usage recorded yet. Spend and token counts appear here once an agent makes its
                  first billable call.
                </p>
              )}

              {cliUsage && (
                <div className="rounded-xl border border-white/8 bg-white/[0.015] p-3">
                  <p className="mb-1.5 text-eyebrow font-bold uppercase tracking-widest text-gray-600">
                    CLI subscriptions (Claude Code / Codex / Gemini CLI)
                  </p>
                  <p className="text-meta leading-relaxed text-gray-700">
                    {Object.values(cliUsage)[0]?.reason ??
                      "Not exposed via a simple API with the credentials already on this machine."}
                  </p>
                </div>
              )}
            </section>
          </>
        )}
      </div>
    </div>
  );
}
