"use client";

import { useCallback, useState, useEffect } from "react";
import { invoke as tauriInvoke } from "@tauri-apps/api/core";
import { isTauri, invokeSafe, saveApiKeys } from "@/lib/api";
import {
  NETWORK_POLICY_COPY,
  type NetworkPolicyMode,
  hasCompletedSetup,
  markSetupCompleted,
  SETUP_RERUN_EVENT,
  storeNetworkPolicy,
  readStoredNetworkPolicy,
} from "@/lib/networkPolicy";
import { motion, AnimatePresence } from "framer-motion";
import {
  Shield,
  Zap,
  Cloud,
  Cpu,
  Server,
  Check,
  ArrowRight,
  Loader2,
  HardDrive,
  AlertTriangle,
  X,
  KeyRound,
  ExternalLink,
} from "lucide-react";

// Official console pages to obtain each provider's key -- Ryan: "links
// provided... spelled out what they need to add." Previously the setup
// wizard's key inputs were 7 blank password fields with nowhere to send a
// first-time user to actually get a key.
const PROVIDER_KEY_URLS: Record<string, string> = {
  anthropic_key: "https://console.anthropic.com/settings/keys",
  openai_key: "https://platform.openai.com/api-keys",
  gemini_key: "https://aistudio.google.com/apikey",
  groq_key: "https://console.groq.com/keys",
  deepseek_key: "https://platform.deepseek.com/api_keys",
  mistral_key: "https://console.mistral.ai/api-keys/",
  kimi_key: "https://platform.moonshot.ai/console/api-keys",
};

const invoke = async (cmd: string, args?: Record<string, unknown>) => {
  if (isTauri()) {
    return tauriInvoke(cmd, args);
  }
  const result = await invokeSafe(cmd, args);
  if (result !== null) return result;
  // Mocks for dev mode
  if (cmd === "probe_hardware")
    return {
      total_vram_mb: 6144,
      vram_budget_mb: 4144,
      reserved_vram_mb: 2000,
      hardware_source: "mock",
      hardware_fallback: false,
      recommended_tier: "engineer=qwen2.5-coder:3b-instruct",
    };
  if (cmd === "ensure_ollama_installed") return { status: "installed (mock)", version: "0.1.27" };
  if (cmd === "pull_required_models") return { models_pulled: [], models_failed: [] };
  if (cmd === "list_toolchains")
    return { rust: true, go: false, python: true, java: false, dotnet: false };
  if (cmd === "install_toolchain")
    return {
      language: args?.language,
      alreadyAvailable: false,
      attempted: true,
      installer: "winget",
      command: "(mock)",
      succeeded: false,
      output: "",
      notes: ["browser preview mode -- open the desktop app to actually install a toolchain"],
    };
  return {};
};

// The small, practically-relevant subset of determinex_oracle's ~40 language aliases worth
// surfacing during setup -- the full alias list (c/cpp/cs/csharp/cxx/...) is one toolchain
// shown under several names; showing all of them here would just be noise at the moment a
// user is deciding whether to bother installing anything yet.
const SETUP_TOOLCHAIN_LANGUAGES: { key: string; label: string }[] = [
  { key: "rust", label: "Rust" },
  { key: "go", label: "Go" },
  { key: "python", label: "Python" },
  { key: "java", label: "Java (JVM)" },
  { key: "dotnet", label: "C# / .NET" },
];

type ToolchainInstallResult = {
  language: string;
  alreadyAvailable: boolean;
  attempted: boolean;
  installer: string;
  command: string;
  succeeded: boolean;
  output: string;
  notes: string[];
};

type SetupStep =
  | "checking"
  | "probing"
  | "welcome"
  | "providers"
  | "hardware"
  | "installing"
  | "ready"
  | "error";

/** One row of `determinex_provider_setup.build_report()`. */
type SetupOption = {
  id: string;
  title: string;
  what_it_means: string;
  effort: number;
  effort_label: string;
  ready: boolean;
  action_label: string;
  action: string;
  url: string;
  detail: string;
  private: boolean;
  /** verified | credentials_unverified | provider_refused | quota_exhausted | no_credentials | not_installed */
  readiness: string;
  signin: boolean;
  /** "start_here" (never needs a key) vs "advanced" (bring your own key). */
  group: string;
  /** Names the sign-in option that already covers this vendor, if any. */
  covered_by: string;
};

type ProviderSetupReport = {
  options: SetupOption[];
  ready_count: number;
  recommended: SetupOption | null;
  headline: string;
};

type ReaderPrescreen = {
  question: string;
  note: string;
  needed: boolean;
  /** technical | mixed | prose — how much detail this user asked to be shown. */
  level: string;
  choices: { id: string; label: string; blurb: string; recommended?: boolean }[];
};

/** The colour of a readiness state. `ready` is earned by a live call, never by a saved key. */
const READINESS_TONE: Record<string, string> = {
  verified: "border-emerald-500/40 bg-emerald-500/10",
  credentials_unverified: "border-amber-500/30 bg-amber-500/5",
  provider_refused: "border-rose-500/30 bg-rose-500/5",
  quota_exhausted: "border-rose-500/30 bg-rose-500/5",
  no_credentials: "border-slate-700/50 bg-slate-800/40",
  not_installed: "border-slate-700/50 bg-slate-800/40",
};

interface HardwareProbe {
  total_vram_mb?: number | null;
  vram_budget_mb: number;
  reserved_vram_mb?: number;
  hardware_source?: string;
  hardware_fallback?: boolean;
  recommended_tier: string;
}

type SetupApiKeys = {
  openai_key: string;
  anthropic_key: string;
  gemini_key: string;
  groq_key: string;
  deepseek_key: string;
  mistral_key: string;
  kimi_key: string;
};

/** Peel the `{ok, data, error}` envelope the Rust onboarding commands return. */
function unwrap<T>(res: unknown): T | null {
  const env = res as { ok?: boolean; data?: T } | null;
  if (env && typeof env === "object" && "ok" in env) return env.ok ? (env.data ?? null) : null;
  return (res as T) ?? null;
}

export function SetupWizard() {
  const [step, setStep] = useState<SetupStep>("checking");
  const [error, setError] = useState<string | null>(null);
  const [completed, setCompleted] = useState(false);
  const [policy, setPolicy] = useState<NetworkPolicyMode>("cloaked");
  const [hardware, setHardware] = useState<HardwareProbe | null>(null);
  const [toolchains, setToolchains] = useState<Record<string, boolean> | null>(null);
  const [installingToolchain, setInstallingToolchain] = useState<string | null>(null);
  const [toolchainResult, setToolchainResult] = useState<ToolchainInstallResult | null>(null);
  const [recommendedPolicy, setRecommendedPolicy] = useState<NetworkPolicyMode | null>(null);
  const [installPhase, setInstallPhase] = useState<string>("");
  // Fine-tuned model coverage, probed after initialize_system. Null means not probed yet.
  const [modelStatus, setModelStatus] = useState<{
    ollama_available: boolean;
    missing_count: number;
    total_count: number;
  } | null>(null);
  const [modelInstallState, setModelInstallState] = useState<
    "idle" | "installing" | "done" | "failed"
  >("idle");
  const [modelInstallError, setModelInstallError] = useState<string>("");
  // null = not probed yet. Drives the OpenRouter card, which previously asserted the key was
  // already present without ever looking.
  const [openRouterKeyPresent, setOpenRouterKeyPresent] = useState<boolean | null>(null);
  // What already works on this machine, so step 2 can lead with one action instead of seven
  // blank password fields. Null while unknown -- and "unknown" renders as a probe, never as
  // "you have nothing", which is the mistake that told a user with 38 local models to
  // download another gigabyte.
  const [setupReport, setSetupReport] = useState<ProviderSetupReport | null>(null);
  const [verifying, setVerifying] = useState<string | null>(null);
  const [verifyResult, setVerifyResult] = useState<Record<string, { ok: boolean; detail: string }>>(
    {}
  );
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [prescreen, setPrescreen] = useState<ReaderPrescreen | null>(null);
  const [apiKeys, setApiKeys] = useState<SetupApiKeys>({
    openai_key: "",
    anthropic_key: "",
    gemini_key: "",
    groq_key: "",
    deepseek_key: "",
    mistral_key: "",
    kimi_key: "",
  });

  const isNative = isTauri();

  const refreshSetupReport = useCallback(() => {
    invoke("provider_setup_report")
      .then((res) => setSetupReport(unwrap<ProviderSetupReport>(res)))
      .catch(() => setSetupReport(null));
  }, []);

  /** Make one real call. A green check that never called anything is the bug, not the goal. */
  const runVerify = useCallback(async (id: string) => {
    setVerifying(id);
    try {
      const res = unwrap<{ ok: boolean; detail: string }>(
        await invoke("provider_setup_verify", { payload: { id } })
      );
      setVerifyResult((prev) => ({
        ...prev,
        [id]: res ?? { ok: false, detail: "the check could not run" },
      }));
      if (res?.ok) refreshSetupReport();
    } catch (err) {
      setVerifyResult((prev) => ({ ...prev, [id]: { ok: false, detail: String(err) } }));
    } finally {
      setVerifying(null);
    }
  }, [refreshSetupReport]);

  const chooseReaderLevel = useCallback(async (level: string) => {
    // Record it, then get out of the way. A first-run screen that stalls on its own bookkeeping
    // is the barrier this whole screen exists to remove, so a failed write is not fatal --
    // the profile simply stays at the middle setting and the question comes back next time.
    setPrescreen((prev) => (prev ? { ...prev, needed: false, level } : prev));
    try {
      await invoke("user_profile_set", { payload: { level } });
    } catch (err) {
      console.warn("[SetupWizard] could not save reader level:", err);
    }
  }, []);

  const beginSetupProbe = useCallback(() => {
    setCompleted(false);
    setError(null);
    setPolicy(readStoredNetworkPolicy());

    // Proactively probe hardware to determine the best network policy recommendation
    setStep("probing");
    invoke("probe_hardware")
      .then((res) => {
        const hw = res as HardwareProbe;
        setHardware(hw);
        // Recommend a policy based on VRAM capability
        if (hw.vram_budget_mb < 8000) {
          setRecommendedPolicy("cloaked");
        } else {
          setRecommendedPolicy("offline");
        }
        setStep("welcome");
      })
      .catch((err) => {
        console.error("Hardware probe failed:", err);
        setHardware({
          total_vram_mb: null,
          vram_budget_mb: 4000,
          reserved_vram_mb: 0,
          hardware_source: "fallback",
          hardware_fallback: true,
          recommended_tier: "Fallback inference budget (4GB)",
        });
        setRecommendedPolicy("cloaked");
        setStep("welcome");
      });

    // Ask how to talk to this person BEFORE saying anything substantial to them. The answer
    // only changes wording and density, never capability, so a failed probe is not an error --
    // it just means we never ask and everyone gets the middle setting.
    //
    // Deliberately NOT a step: this probe and the hardware probe race, and whichever resolved
    // last would have won `setStep`. It is a gate rendered in front of whatever step is
    // current, so the ordering cannot matter.
    invoke("user_profile_get")
      .then((res) => setPrescreen(unwrap<ReaderPrescreen>(res)))
      .catch(() => setPrescreen(null));

    refreshSetupReport();

    // Toolchain visibility is best-effort and never blocks setup -- a slow/failed probe just
    // means the card below shows nothing rather than failing the whole wizard over what is an
    // optional convenience, not a requirement to use Determinex at all.
    invoke("list_toolchains")
      .then((res) => setToolchains(res as Record<string, boolean>))
      .catch(() => setToolchains(null));
  }, [refreshSetupReport]);

  const installToolchain = useCallback(async (language: string) => {
    setInstallingToolchain(language);
    setToolchainResult(null);
    try {
      const res = await invoke("install_toolchain", { language });
      setToolchainResult(res as ToolchainInstallResult);
      // Re-probe rather than trust this one result's own succeeded flag for the OTHER
      // languages' displayed status -- but do fold this language's own outcome into the
      // existing state immediately so the card reflects it without waiting on a full re-list.
      setToolchains((prev) =>
        prev ? { ...prev, [language]: (res as ToolchainInstallResult).succeeded } : prev
      );
    } catch (err) {
      setToolchainResult({
        language,
        alreadyAvailable: false,
        attempted: true,
        installer: "",
        command: "",
        succeeded: false,
        output: "",
        notes: [String(err)],
      });
    } finally {
      setInstallingToolchain(null);
    }
  }, []);

  useEffect(() => {
    if (hasCompletedSetup()) {
      setCompleted(true);
      return;
    }

    beginSetupProbe();
  }, [beginSetupProbe, isNative]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const handler = () => beginSetupProbe();
    window.addEventListener(SETUP_RERUN_EVENT, handler);
    return () => window.removeEventListener(SETUP_RERUN_EVENT, handler);
  }, [beginSetupProbe]);

  // Real key status for the OpenRouter card. Failure resolves to "not present" rather than
  // leaving the optimistic claim standing -- the whole point is to stop asserting a key exists
  // without having looked.
  useEffect(() => {
    let cancelled = false;
    // The local `invoke` wrapper is untyped (it also serves dev-mode mocks), so narrow here.
    invoke("get_api_key_status")
      .then((status) => {
        if (cancelled) return;
        const map = (status ?? {}) as Record<string, boolean>;
        setOpenRouterKeyPresent(Boolean(map.openrouter));
      })
      .catch(() => {
        if (!cancelled) setOpenRouterKeyPresent(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handlePolicySelect = async (mode: NetworkPolicyMode) => {
    setPolicy(mode);
    setStep("providers");
  };

  // Cheap and side-effect free. Asking lets the wizard say what is actually missing instead of
  // leaving the user to discover it when a build fails to route. Shared by both the online and the
  // offline paths -- it used to exist only in the online one.
  const probeDeterminexModels = useCallback(async () => {
    try {
      const status = (await invoke("check_determinex_models")) as {
        ollama_available: boolean;
        missing_count: number;
        total_count: number;
      };
      setModelStatus(status);
    } catch (probeErr) {
      // Never block setup on the probe itself.
      console.warn("[SetupWizard] model probe failed:", probeErr);
    }
  }, []);

  const handleStartInstall = async () => {
    setStep("installing");
    try {
      storeNetworkPolicy(policy);
      await invoke("sync_network_policy", { policy });
      if (Object.values(apiKeys).some((value) => value.trim().length > 0)) {
        setInstallPhase("Saving API keys to the local Config Vault...");
        await saveApiKeys(apiKeys);
      }

      if (policy === "online" || policy === "cloaked") {
        setInstallPhase("Checking for Ollama installation...");
        const ollamaResult = (await invoke("ensure_ollama_installed")) as {
          status: string;
          version: string;
        };
        setInstallPhase(`Ollama v${ollamaResult.version} — ${ollamaResult.status}`);

        setInstallPhase("Determining required models for your hardware...");
        const pullResult = (await invoke("pull_required_models")) as {
          models_pulled: string[];
          models_failed: string[];
        };

        if (pullResult.models_failed.length > 0) {
          setError(`Failed to download models: ${pullResult.models_failed.join(", ")}`);
          setStep("error");
          return;
        }

        // This used to read "Registering Determinex model swarm with Ollama...", which was not
        // true: initialize_system pulls the base qwen models and registers the fine-tuned
        // Determinex models only if their GGUFs already happen to be on disk. On a fresh
        // machine they never are, so the swarm was announced and nothing was registered. The
        // real provisioning path is the explicit, size-disclosed step below.
        setInstallPhase("Finalizing system configuration...");
        await invoke("initialize_system");

        await probeDeterminexModels();
      } else {
        setInstallPhase("Configuring IDE for Offline mode...");
        // Offline still needs the system initialised; it just must not reach the network.
        //
        // The `.catch(() => {})` that used to be here sat INSIDE this try, so the outer catch at
        // the bottom (which sets step="error") was unreachable for the offline branch: a genuine
        // initialize_system failure was swallowed and the wizard went straight to the green
        // "System Ready / Determinex is fully configured for your environment" screen.
        try {
          await invoke("initialize_system");
        } catch (offlineErr: unknown) {
          setError(offlineErr instanceof Error ? offlineErr.message : String(offlineErr));
          setStep("error");
          return;
        }

        // Also probe here. This used to run ONLY in the online/cloaked branch, so anyone choosing
        // Offline never saw the "N of M fine-tuned models are not installed" panel -- i.e. the
        // exact gap that panel exists to close was left open for offline installs, which are the
        // ones most likely to have no models at all.
        await probeDeterminexModels();
      }

      setStep("ready");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
      setStep("error");
    }
  };

  const finishSetup = () => {
    markSetupCompleted();
    setCompleted(true);
    window.location.reload();
  };

  if (completed || step === "checking") return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#0a0a0f]/90 backdrop-blur-md font-sans text-slate-200">
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,rgba(99,102,241,0.15)_0%,rgba(0,0,0,0)_70%)] pointer-events-none" />

      <motion.div
        initial={{ opacity: 0, y: 20, scale: 0.95 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        className="relative w-full max-w-4xl max-h-[90vh] overflow-y-auto bg-slate-900/80 border border-indigo-500/20 rounded-2xl shadow-2xl p-8 flex flex-col"
        style={{ boxShadow: "0 25px 50px -12px rgba(0,0,0,0.5), 0 0 0 1px rgba(99,102,241,0.1)" }}
      >
        <div className="flex items-center gap-3 mb-8">
          <div className="w-10 h-10 rounded-lg bg-indigo-500/20 border border-indigo-500/40 flex items-center justify-center">
            <Zap className="w-5 h-5 text-indigo-400" />
          </div>
          <div>
            <h1 className="text-2xl font-bold tracking-tight text-white">Determinex IDE Setup</h1>
            <p className="text-sm text-slate-400">
              Configure your local workspace and intelligence engine
            </p>
          </div>
        </div>

        {/* THE PRESCREEN, IN FRONT OF EVERYTHING.
            Ryan, 2026-08-03: "add a prescreen asking level of expertise for the user and just
            explain that you can be more technical, middle tech (mix) or no tech but better on
            prose, and lets drive the user session that way."
            It gates rather than being a step because it and the hardware probe resolve in a
            race, and a step would have been won by whichever finished last. It changes wording
            and density only -- never what the tool can do -- and it is asked exactly once. */}
        {prescreen?.needed ? (
          <motion.div
            key="prescreen"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            className="flex flex-col gap-5"
          >
            <div>
              <h2 className="text-lg font-semibold text-slate-200">{prescreen.question}</h2>
              <p className="mt-1 text-sm text-slate-400">{prescreen.note}</p>
            </div>
            <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
              {prescreen.choices.map((choice) => (
                <button
                  key={choice.id}
                  onClick={() => chooseReaderLevel(choice.id)}
                  className={`relative flex flex-col items-start rounded-xl border p-5 text-left transition-all ${
                    choice.recommended
                      ? "border-indigo-500/60 bg-indigo-900/40 hover:border-indigo-400 hover:bg-indigo-900/60"
                      : "border-slate-700/50 bg-slate-800/40 hover:border-indigo-500/50 hover:bg-slate-800/80"
                  }`}
                >
                  {choice.recommended && (
                    <div className="absolute -top-3 left-4 rounded-full bg-indigo-500 px-2 py-1 text-eyebrow font-bold uppercase tracking-wider text-white shadow-lg">
                      Recommended
                    </div>
                  )}
                  <span className="mt-1 font-semibold text-white">{choice.label}</span>
                  <span className="mt-2 text-xs leading-relaxed text-slate-400">
                    {choice.blurb}
                  </span>
                </button>
              ))}
            </div>
          </motion.div>
        ) : (
        <AnimatePresence mode="wait">
          {step === "probing" && (
            <motion.div
              key="probing"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="flex flex-col items-center justify-center py-12 gap-4"
            >
              <Loader2 className="w-8 h-8 text-indigo-400 animate-spin" />
              <p className="text-sm text-slate-400">Detecting system capabilities...</p>
            </motion.div>
          )}

          {step === "welcome" && (
            <motion.div
              key="welcome"
              initial={{ opacity: 0, x: 20 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -20 }}
              className="flex flex-col gap-6"
            >
              <div className="rounded-xl border border-white/10 bg-black/20 p-4 text-sm leading-relaxed text-slate-300">
                <strong className="text-white">What Determinex does:</strong> it&apos;s a
                local-first AI coding workbench -- an AI plans and writes code, then a real compiler
                or test run (never the AI&apos;s own word) decides whether it actually worked.
                Nothing below is required to get started; the defaults work out of the box.
                You&apos;re just choosing whether any of it is allowed to leave this machine.
              </div>
              <h2 className="text-lg font-semibold text-slate-200">
                Step 1: Network & Privacy Policy
              </h2>
              <p className="text-sm text-slate-400">
                How would you like Determinex to operate? This controls what data leaves your
                machine.
              </p>

              {recommendedPolicy && hardware && (
                <div className="bg-indigo-500/10 border border-indigo-500/30 rounded-xl p-4 flex gap-3 text-indigo-200">
                  <Zap className="w-5 h-5 shrink-0 text-indigo-400 mt-0.5" />
                  <div className="text-sm leading-relaxed">
                    <strong>Recommendation:</strong> Based on a{" "}
                    {hardware.total_vram_mb
                      ? `${Math.round((hardware.total_vram_mb / 1024) * 10) / 10} GB physical VRAM`
                      : `${Math.round((hardware.vram_budget_mb / 1024) * 10) / 10} GB fallback inference budget`}{" "}
                    probe, we recommend{" "}
                    <strong>{NETWORK_POLICY_COPY[recommendedPolicy].label}</strong>.
                    {recommendedPolicy === "offline"
                      ? " Your hardware provides ample headroom to run advanced reasoning models locally without slowing down your computer."
                      : " Running advanced models entirely locally on this hardware may severely slow down your computer. We highly recommend Cloaked mode to offload heavy tasks to the cloud while protecting your privacy."}
                  </div>
                </div>
              )}

              <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mt-2">
                {(
                  Object.entries(NETWORK_POLICY_COPY) as [
                    NetworkPolicyMode,
                    (typeof NETWORK_POLICY_COPY)[NetworkPolicyMode],
                  ][]
                ).map(([mode, info]) => {
                  const isRecommended = mode === recommendedPolicy;
                  return (
                    <button
                      key={mode}
                      onClick={() => handlePolicySelect(mode)}
                      className={`relative flex flex-col items-start p-5 rounded-xl border transition-all group text-left ${
                        isRecommended
                          ? "bg-indigo-900/40 border-indigo-500/60 hover:bg-indigo-900/60 hover:border-indigo-400 shadow-[0_0_15px_rgba(99,102,241,0.1)]"
                          : "border-slate-700/50 bg-slate-800/40 hover:bg-slate-800/80 hover:border-indigo-500/50"
                      }`}
                    >
                      {isRecommended && (
                        <div className="absolute -top-3 left-4 bg-indigo-500 text-white text-meta font-bold px-2 py-1 rounded-full uppercase tracking-wider shadow-lg">
                          Recommended
                        </div>
                      )}
                      <div className="flex items-center gap-2 mb-3 mt-1">
                        {mode === "offline" && (
                          <Shield
                            className={`w-5 h-5 ${isRecommended ? "text-emerald-300" : "text-emerald-400"}`}
                          />
                        )}
                        {mode === "cloaked" && (
                          <Server
                            className={`w-5 h-5 ${isRecommended ? "text-indigo-300" : "text-indigo-400"}`}
                          />
                        )}
                        {mode === "online" && (
                          <Cloud
                            className={`w-5 h-5 ${isRecommended ? "text-sky-300" : "text-sky-400"}`}
                          />
                        )}
                        <span
                          className={`font-semibold ${isRecommended ? "text-indigo-100" : "text-white"}`}
                        >
                          {info.label}
                        </span>
                      </div>
                      <p
                        className={`text-sm mb-2 ${isRecommended ? "text-indigo-200/80" : "text-slate-300"}`}
                      >
                        {info.summary}
                      </p>
                      <p className="text-xs text-slate-500 mt-auto">{info.detail}</p>
                    </button>
                  );
                })}
              </div>
            </motion.div>
          )}

          {step === "providers" && (
            <motion.div
              key="providers"
              initial={{ opacity: 0, x: 20 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -20 }}
              className="flex flex-col gap-6"
            >
              <div>
                <h2 className="text-lg font-semibold text-slate-200">Step 2: Choose your AI</h2>
                <p className="text-sm text-slate-400 mt-1">
                  {setupReport
                    ? setupReport.headline
                    : "Checking what already works on this computer..."}
                </p>
              </div>

              {/* WHAT ALREADY WORKS, FIRST.
                  This step used to be seven blank password fields in alphabetical order, with
                  no check of any kind -- so a machine with a Claude subscription, a ChatGPT
                  subscription and 38 local models opened on "paste an API key". Ryan:
                  "I'm giving the world a magic box. The magic believers will try it and
                  something simple shouldn't fuck it up for them."
                  The order below is by what the user must UNDERSTAND, not by model quality:
                  already working > runs on this computer > sign in to an app you have > key. */}
              {setupReport === null ? (
                <div className="flex items-center gap-3 rounded-xl border border-slate-700/50 bg-slate-800/40 p-4 text-sm text-slate-400">
                  <Loader2 className="w-4 h-4 animate-spin text-indigo-400" />
                  Looking for AI you can already use...
                </div>
              ) : (
                <div className="flex flex-col gap-3">
                  {setupReport.options
                    .filter((o) => o.group === "start_here")
                    .map((option) => {
                      const result = verifyResult[option.id];
                      const tone =
                        READINESS_TONE[option.readiness] ?? "border-slate-700/50 bg-slate-800/40";
                      return (
                        <div key={option.id} className={`rounded-xl border p-4 ${tone}`}>
                          <div className="flex items-start justify-between gap-4">
                            <div className="min-w-0">
                              <p className="flex items-center gap-2 text-sm font-semibold text-white">
                                {option.ready ? (
                                  <Check className="w-4 h-4 text-emerald-400 shrink-0" />
                                ) : option.private ? (
                                  <HardDrive className="w-4 h-4 text-emerald-400 shrink-0" />
                                ) : (
                                  <Cloud className="w-4 h-4 text-indigo-400 shrink-0" />
                                )}
                                {option.title}
                                {option.private && (
                                  <span className="rounded-full bg-emerald-500/15 px-2 py-0.5 text-eyebrow font-bold uppercase tracking-wider text-emerald-300">
                                    Stays on this computer
                                  </span>
                                )}
                              </p>
                              <p className="mt-1 text-xs leading-relaxed text-slate-400">
                                {option.what_it_means}
                              </p>
                              {option.detail && prescreen?.level !== "prose" && (
                                <p className="mt-1 truncate text-xs text-slate-500">
                                  {option.detail}
                                </p>
                              )}
                            </div>
                            <div className="shrink-0">
                              {option.ready ? (
                                <span
                                  data-testid="provider-ready"
                                  className="flex items-center gap-1.5 rounded-lg bg-emerald-500/15 px-3 py-1.5 text-xs font-semibold text-emerald-300"
                                >
                                  <Check className="w-3.5 h-3.5" /> Ready
                                </span>
                              ) : option.action === "verify" ? (
                                <button
                                  onClick={() => runVerify(option.id)}
                                  disabled={verifying === option.id}
                                  className="flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-semibold text-white transition-colors hover:bg-indigo-500 disabled:opacity-50"
                                >
                                  {verifying === option.id ? (
                                    <>
                                      <Loader2 className="w-3.5 h-3.5 animate-spin" /> Testing
                                    </>
                                  ) : (
                                    "Test it"
                                  )}
                                </button>
                              ) : option.url ? (
                                <a
                                  href={option.url}
                                  target="_blank"
                                  rel="noreferrer"
                                  className="flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-semibold text-white transition-colors hover:bg-indigo-500"
                                >
                                  {option.action_label} <ExternalLink className="w-3 h-3" />
                                </a>
                              ) : (
                                <span className="rounded-lg bg-slate-700/50 px-3 py-1.5 text-xs font-medium text-slate-300">
                                  {option.action_label}
                                </span>
                              )}
                            </div>
                          </div>
                          {/* The result of a REAL call -- including the real reason it refused.
                              Google spent a week telling users three different wrong stories
                              about one working key; whatever the provider actually said goes
                              here, verbatim. */}
                          {result && (
                            <p
                              className={`mt-3 flex items-start gap-2 rounded-lg px-3 py-2 text-xs leading-relaxed ${
                                result.ok
                                  ? "bg-emerald-500/10 text-emerald-200"
                                  : "bg-rose-500/10 text-rose-200"
                              }`}
                            >
                              {result.ok ? (
                                <Check className="mt-0.5 w-3.5 h-3.5 shrink-0" />
                              ) : (
                                <AlertTriangle className="mt-0.5 w-3.5 h-3.5 shrink-0" />
                              )}
                              <span>
                                {result.ok ? "It works — that was a real call." : result.detail}
                              </span>
                            </p>
                          )}
                        </div>
                      );
                    })}
                </div>
              )}

              <p className="text-xs leading-relaxed text-slate-500">
                You can change any of this later, and you don&apos;t need more than one.
              </p>


              {/* TIER 3, COLLAPSED. A first-time user should reach a working system without
                  ever meeting an API key. It is still here, in full, for the people who want
                  it -- hiding a capability would be a different kind of barrier. */}
              <button
                onClick={() => setShowAdvanced((v) => !v)}
                className="flex items-center gap-2 self-start text-xs font-semibold uppercase tracking-wider text-slate-500 transition-colors hover:text-slate-300"
              >
                <KeyRound className="w-3.5 h-3.5" />
                {showAdvanced ? "Hide" : "I already have an API key"}
              </button>

              {showAdvanced && (
                <div>
                  {/* The OpenRouter free-tier card lives HERE, not at the top of the step.
                      It used to be the first thing on the screen and its own copy said
                      "adding an OpenRouter key below" while no key field was visible at all --
                      it is a paragraph about a key, so it belongs with the keys. It also used
                      to render "Already Configured ✓" unconditionally, with no key check of
                      any kind, which is why it is now driven by get_api_key_status. */}
                  {openRouterKeyPresent === true ? (
                    <div className="mb-3 flex gap-3 rounded-xl border border-green-500/30 bg-green-500/10 p-4">
                      <Zap className="mt-0.5 w-5 h-5 flex-shrink-0 text-green-400" />
                      <div>
                        <p className="mb-1 text-sm font-semibold text-green-200">
                          OpenRouter key configured ✓
                        </p>
                        <p className="text-xs leading-relaxed text-green-300/80">
                          This unlocks OpenRouter&apos;s <strong>free tier</strong> at zero cost
                          — including Qwen3 Coder 480B (1M context) and Llama 3.3 70B. No credit
                          card required.
                        </p>
                      </div>
                    </div>
                  ) : (
                    <div className="mb-3 flex gap-3 rounded-xl border border-slate-700/50 bg-slate-800/40 p-4">
                      <Zap className="mt-0.5 w-5 h-5 flex-shrink-0 text-slate-400" />
                      <div>
                        <p className="mb-1 text-sm font-semibold text-slate-200">
                          OpenRouter — one key, many models, several of them free
                        </p>
                        <p className="text-xs leading-relaxed text-slate-400">
                          An OpenRouter key unlocks a set of <strong>free models</strong> at zero
                          cost, including Qwen3 Coder 480B (1M context) and Llama 3.3 70B. No
                          credit card required. Determinex runs entirely on local models without
                          it — this only adds cloud options.
                        </p>
                      </div>
                    </div>
                  )}
                  {setupReport?.options
                    .filter((o) => o.group === "advanced" && o.covered_by)
                    .map((o) => (
                      <p
                        key={o.id}
                        className="mb-3 rounded-lg border border-slate-700/50 bg-slate-800/40 px-3 py-2 text-xs leading-relaxed text-slate-400"
                      >
                        <strong className="text-slate-300">{o.title}:</strong>{" "}
                        {o.what_it_means}
                      </p>
                    ))}
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  {[
                    ["anthropic_key", "Anthropic / Claude"],
                    ["openai_key", "OpenAI / ChatGPT"],
                    ["gemini_key", "Google Gemini"],
                    ["groq_key", "Groq"],
                    ["deepseek_key", "DeepSeek"],
                    ["mistral_key", "Mistral"],
                    ["kimi_key", "Kimi (Moonshot AI)"],
                  ].map(([key, label]) => (
                    <label
                      key={key}
                      className="rounded-xl border border-slate-700/50 bg-slate-800/40 p-4 flex flex-col gap-2"
                    >
                      <span className="flex items-center justify-between gap-2">
                        <span className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-slate-300">
                          <KeyRound className="w-3.5 h-3.5 text-indigo-400" /> {label}
                        </span>
                        {PROVIDER_KEY_URLS[key] && (
                          <a
                            href={PROVIDER_KEY_URLS[key]}
                            target="_blank"
                            rel="noreferrer"
                            className="flex items-center gap-1 text-meta font-bold uppercase tracking-wide text-indigo-400 hover:text-indigo-300"
                          >
                            Get a key <ExternalLink className="w-2.5 h-2.5" />
                          </a>
                        )}
                      </span>
                      <input
                        type="password"
                        value={apiKeys[key as keyof SetupApiKeys]}
                        onChange={(event) =>
                          setApiKeys((current) => ({ ...current, [key]: event.target.value }))
                        }
                        placeholder={
                          policy === "offline"
                            ? "Skipped in Offline / Local Only"
                            : "Paste API key, optional"
                        }
                        disabled={policy === "offline"}
                        className="w-full rounded-lg border border-slate-700 bg-black/30 px-3 py-2 text-sm text-white placeholder:text-slate-600 outline-none focus:border-indigo-500 disabled:opacity-40"
                      />
                    </label>
                  ))}
                  </div>
                </div>
              )}

              <div className="flex justify-end gap-3 mt-2">
                <button
                  onClick={() => setStep("welcome")}
                  className="px-4 py-2 rounded-lg text-sm font-medium text-slate-400 hover:text-white transition-colors"
                >
                  Back
                </button>
                <button
                  onClick={() => setStep("hardware")}
                  className="px-6 py-2 rounded-lg text-sm font-medium bg-indigo-600 hover:bg-indigo-500 text-white transition-colors flex items-center gap-2"
                >
                  Continue <ArrowRight className="w-4 h-4" />
                </button>
              </div>
            </motion.div>
          )}

          {step === "hardware" && (
            <motion.div
              key="hardware"
              initial={{ opacity: 0, x: 20 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -20 }}
              className="flex flex-col gap-6"
            >
              <h2 className="text-lg font-semibold text-slate-200">
                Step 3: Hardware Diagnostics & Startup
              </h2>

              {!hardware ? (
                <div className="flex flex-col items-center justify-center py-12 gap-4">
                  <Loader2 className="w-8 h-8 text-indigo-400 animate-spin" />
                  <p className="text-sm text-slate-400">Probing system capabilities...</p>
                </div>
              ) : (
                <div className="flex flex-col gap-6">
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    <div className="p-4 rounded-xl bg-slate-800/50 border border-slate-700/50 flex flex-col gap-1">
                      <div className="flex items-center gap-2 text-slate-400 mb-1">
                        <Cpu className="w-4 h-4" />
                        <span className="text-xs font-semibold uppercase tracking-wider">
                          Physical VRAM
                        </span>
                      </div>
                      <span className="text-2xl font-bold text-white">
                        {hardware.total_vram_mb
                          ? `${Math.round((hardware.total_vram_mb / 1024) * 10) / 10} GB`
                          : "Unknown"}
                      </span>
                      <span className="text-xs text-slate-500">
                        {hardware.hardware_fallback
                          ? "Probe unavailable; using fallback budget"
                          : `Detected by ${hardware.hardware_source ?? "hardware probe"}`}
                      </span>
                    </div>

                    <div className="p-4 rounded-xl bg-slate-800/50 border border-slate-700/50 flex flex-col gap-1">
                      <div className="flex items-center gap-2 text-slate-400 mb-1">
                        <Cpu className="w-4 h-4" />
                        <span className="text-xs font-semibold uppercase tracking-wider">
                          Inference Budget
                        </span>
                      </div>
                      <span className="text-2xl font-bold text-white">
                        {Math.round((hardware.vram_budget_mb / 1024) * 10) / 10} GB
                      </span>
                      <span className="text-xs text-slate-500">
                        {hardware.reserved_vram_mb
                          ? `${Math.round((hardware.reserved_vram_mb / 1024) * 10) / 10} GB reserved for OS/GPU overhead`
                          : "Conservative usable budget"}
                      </span>
                    </div>

                    <div className="p-4 rounded-xl bg-slate-800/50 border border-slate-700/50 flex flex-col gap-1">
                      <div className="flex items-center gap-2 text-slate-400 mb-1">
                        <HardDrive className="w-4 h-4" />
                        <span className="text-xs font-semibold uppercase tracking-wider">
                          Recommended Tier
                        </span>
                      </div>
                      <span
                        className="text-lg font-bold text-white truncate"
                        title={hardware.recommended_tier}
                      >
                        {hardware.recommended_tier.split(" | ")[0].replace("engineer=", "")}
                      </span>
                      <span className="text-xs text-slate-500">Auto-selected loadout</span>
                    </div>
                  </div>

                  {toolchains && (
                    <div className="rounded-xl border border-slate-700/50 bg-slate-800/30 p-4">
                      <div className="text-xs font-semibold uppercase tracking-wider text-slate-300 mb-2">
                        Compiler toolchains
                      </div>
                      <p className="text-xs text-slate-500 mb-3">
                        Determinex verifies every change with a real compiler or test run, never an
                        LLM&apos;s own claim -- these are the toolchains that back that
                        verification. Nothing here is required to finish setup; install only what
                        you plan to build with.
                      </p>
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                        {SETUP_TOOLCHAIN_LANGUAGES.map(({ key, label }) => {
                          const available = toolchains[key];
                          const busy = installingToolchain === key;
                          return (
                            <div
                              key={key}
                              className="flex items-center justify-between rounded-lg bg-black/25 border border-white/5 px-3 py-2"
                            >
                              <div className="flex items-center gap-2">
                                {available ? (
                                  <Check className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                                ) : (
                                  <X className="w-3.5 h-3.5 text-slate-600 shrink-0" />
                                )}
                                <span className="text-xs text-slate-300">{label}</span>
                              </div>
                              {!available && (
                                <button
                                  type="button"
                                  onClick={() => void installToolchain(key)}
                                  disabled={busy}
                                  className="text-label font-medium text-indigo-400 hover:text-indigo-300 disabled:opacity-40 disabled:cursor-not-allowed flex items-center gap-1"
                                >
                                  {busy && <Loader2 className="w-3 h-3 animate-spin" />}
                                  {busy ? "Installing..." : "Install"}
                                </button>
                              )}
                            </div>
                          );
                        })}
                      </div>
                      {toolchainResult && (
                        <div
                          className={`mt-3 rounded-lg border px-3 py-2 text-label leading-relaxed ${
                            toolchainResult.succeeded
                              ? "border-emerald-500/20 bg-emerald-950/20 text-emerald-300"
                              : "border-amber-500/20 bg-amber-950/20 text-amber-300"
                          }`}
                        >
                          {toolchainResult.succeeded
                            ? `${toolchainResult.language}: installed and verified.`
                            : `${toolchainResult.language}: ${toolchainResult.notes[0] ?? "install did not complete"}`}
                        </div>
                      )}
                    </div>
                  )}

                  {policy === "offline" ? (
                    <div className="p-4 rounded-xl bg-amber-500/10 border border-amber-500/20 flex gap-3 text-amber-200/80">
                      <AlertTriangle className="w-5 h-5 shrink-0 text-amber-500" />
                      <div className="text-sm leading-relaxed">
                        You selected <strong>Offline Mode</strong>. Determinex will rely entirely on
                        the hardware shown above, and will skip downloading online models during
                        this setup.
                      </div>
                    </div>
                  ) : (
                    <div className="p-4 rounded-xl bg-sky-500/10 border border-sky-500/20 flex gap-3 text-sky-200/80">
                      <Cloud className="w-5 h-5 shrink-0 text-sky-400" />
                      <div className="text-sm leading-relaxed">
                        This will download local model weights over the network -- typically several
                        GB depending on the tier above -- before Determinex can run its local
                        builder/observer roles. It only happens once; nothing is uploaded, only
                        downloaded. Close this window now if you&apos;d rather not do that yet.
                      </div>
                    </div>
                  )}

                  <div className="rounded-xl border border-slate-700/50 bg-slate-800/30 p-4">
                    <div className="text-xs font-semibold uppercase tracking-wider text-slate-300 mb-2">
                      Setup will run
                    </div>
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-2 text-xs text-slate-400">
                      <div className="rounded-lg bg-black/25 border border-white/5 px-3 py-2">
                        Ollama install/start check
                      </div>
                      <div className="rounded-lg bg-black/25 border border-white/5 px-3 py-2">
                        Required local model pull/build
                      </div>
                      <div className="rounded-lg bg-black/25 border border-white/5 px-3 py-2">
                        Role routing and startup validation
                      </div>
                    </div>
                  </div>

                  <div className="flex justify-end gap-3 mt-4">
                    <button
                      onClick={() => setStep("welcome")}
                      className="px-4 py-2 rounded-lg text-sm font-medium text-slate-400 hover:text-white transition-colors"
                    >
                      Back
                    </button>
                    <button
                      onClick={handleStartInstall}
                      className="px-6 py-2 rounded-lg text-sm font-medium bg-indigo-600 hover:bg-indigo-500 text-white transition-colors flex items-center gap-2"
                    >
                      Start Setup <ArrowRight className="w-4 h-4" />
                    </button>
                  </div>
                </div>
              )}
            </motion.div>
          )}

          {step === "installing" && (
            <motion.div
              key="installing"
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              className="flex flex-col items-center justify-center py-16 gap-6 text-center"
            >
              <div className="relative">
                <div className="w-16 h-16 rounded-full border-2 border-indigo-500/20 border-t-indigo-500 animate-spin" />
                <div className="absolute inset-0 flex items-center justify-center">
                  <Zap className="w-6 h-6 text-indigo-400 animate-pulse" />
                </div>
              </div>
              <div className="flex flex-col gap-2">
                <h2 className="text-xl font-bold text-white">Configuring Environment</h2>
                <p className="text-sm text-indigo-300 font-mono">{installPhase}</p>
                <p className="text-xs text-slate-500 max-w-md mx-auto mt-2">
                  This may take several minutes if large model weights are being downloaded. Do not
                  close the window.
                </p>
              </div>
            </motion.div>
          )}

          {step === "error" && (
            <motion.div
              key="error"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              className="flex flex-col gap-4 items-center text-center py-8"
            >
              <div className="w-16 h-16 rounded-full bg-red-500/20 flex items-center justify-center mb-2">
                <X className="w-8 h-8 text-red-500" />
              </div>
              <h2 className="text-xl font-bold text-white">Setup Failed</h2>
              <p className="text-sm text-red-400 bg-red-950/50 border border-red-500/30 p-4 rounded-lg max-w-lg font-mono">
                {error}
              </p>
              <button
                onClick={() => setStep("welcome")}
                className="mt-6 px-6 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-white"
              >
                Try Again
              </button>
            </motion.div>
          )}

          {step === "ready" && (
            <motion.div
              key="ready"
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              className="flex flex-col items-center justify-center py-12 gap-6 text-center"
            >
              <div className="w-20 h-20 rounded-full bg-emerald-500/20 flex items-center justify-center mb-2">
                <Check className="w-10 h-10 text-emerald-500" />
              </div>
              <div className="flex flex-col gap-2">
                <h2 className="text-2xl font-bold text-white">System Ready</h2>
                <p className="text-sm text-slate-400">
                  Determinex is fully configured for your environment.
                </p>
              </div>

              {/* The fine-tuned models are a separate, explicit choice. They are several GB,
                  and the builder and monitor roles default to them -- so saying nothing here
                  is what previously left a "ready" install unable to route work. */}
              {modelStatus && modelStatus.missing_count > 0 && modelInstallState !== "done" && (
                <div className="w-full max-w-md rounded-xl border border-amber-400/30 bg-amber-400/10 p-4 text-left">
                  <p className="text-sm font-semibold text-amber-200">
                    {modelStatus.missing_count} of {modelStatus.total_count} fine-tuned models are
                    not installed
                  </p>
                  <p className="mt-1 text-xs text-slate-300">
                    {modelStatus.ollama_available
                      ? "The Builder and Monitor roles use these by default. Without them those roles cannot run, and the download is several GB — so it is your call, not a silent one. You can also do this later."
                      : "Ollama was not detected, so these cannot be registered yet. Install Ollama from ollama.com, then run this step again."}
                  </p>
                  {modelStatus.ollama_available && (
                    <button
                      type="button"
                      disabled={modelInstallState === "installing"}
                      onClick={async () => {
                        setModelInstallState("installing");
                        setModelInstallError("");
                        try {
                          await invoke("install_determinex_models");
                          setModelInstallState("done");
                          const refreshed = (await invoke("check_determinex_models")) as {
                            ollama_available: boolean;
                            missing_count: number;
                            total_count: number;
                          };
                          setModelStatus(refreshed);
                        } catch (err: unknown) {
                          setModelInstallState("failed");
                          setModelInstallError(err instanceof Error ? err.message : String(err));
                        }
                      }}
                      className="mt-3 rounded-lg bg-amber-500 px-4 py-2 text-xs font-bold text-slate-900 transition-colors hover:bg-amber-400 disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      {modelInstallState === "installing"
                        ? "Downloading models — this can take a while…"
                        : "Download and register now"}
                    </button>
                  )}
                  {modelInstallState === "failed" && (
                    <p className="mt-2 break-words text-xs text-rose-300">{modelInstallError}</p>
                  )}
                </div>
              )}
              {modelInstallState === "done" && modelStatus?.missing_count === 0 && (
                <p className="text-xs text-emerald-300">
                  All {modelStatus.total_count} fine-tuned models registered.
                </p>
              )}

              <button
                onClick={finishSetup}
                className="mt-4 px-8 py-3 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white font-bold tracking-wide flex items-center gap-2 transition-all hover:scale-105 active:scale-95 shadow-lg shadow-emerald-500/20"
              >
                Launch IDE <ArrowRight className="w-5 h-5" />
              </button>
            </motion.div>
          )}
        </AnimatePresence>
        )}
      </motion.div>
    </div>
  );
}
