"use client";
import React, { createContext, useContext, useState, useEffect, useCallback } from "react";
import { invoke } from "@tauri-apps/api/core";
import {
  getApiKeyStatus,
  getToolRegistry,
  checkOllamaStatus,
  getModelsRegistry,
  invokeSafe,
  isTauri,
  getOllamaBaseUrl,
  saveOllamaBaseUrl,
} from "@/lib/api";
import { useErrorToast } from "@/components/ErrorToast";
import {
  readStoredNetworkPolicy,
  storeNetworkPolicy,
  type NetworkPolicyMode,
} from "@/lib/networkPolicy";
import {
  applyDensity,
  clampZoom,
  nextZoom,
  readStoredDensity,
  readStoredZoom,
  UI_DENSITY_STORAGE_KEY,
  UI_ZOOM_STORAGE_KEY,
  type UiDensity,
} from "@/lib/uiDensity";

// ── Types ────────────────────────────────────────────────────────────────────

interface ToolEntry {
  name: string;
  status: string;
  type: string;
  requires: string | null;
}
export interface ApiKeys {
  openai_key: string;
  anthropic_key: string;
  gemini_key: string;
  groq_key: string;
  deepseek_key: string;
  mistral_key: string;
  openrouter_key: string;
  kimi_key: string;
}

interface SettingsContextValue {
  // Modal visibility
  showSettings: boolean;
  setShowSettings: React.Dispatch<React.SetStateAction<boolean>>;

  // Settings tab
  settingsTab: "keys" | "roles" | "diagnostics" | "skin" | "network";
  setSettingsTab: React.Dispatch<
    React.SetStateAction<"keys" | "roles" | "diagnostics" | "skin" | "network">
  >;

  // Network policy
  networkPolicy: NetworkPolicyMode;
  setNetworkPolicy: (mode: NetworkPolicyMode) => void;
  /**
   * Set when the backend did not confirm the requested policy, in which case
   * `networkPolicy` has been rolled back to what is actually in force. Never
   * let the UI advertise a privacy posture the backend has not applied.
   */
  networkPolicyError: string | null;
  dismissNetworkPolicyError: () => void;

  // UI density + zoom. The type scale defaults to a readable 13px body; these
  // make it the user's choice rather than another hard-coded decision.
  uiDensity: UiDensity;
  setUiDensity: (d: UiDensity) => void;
  uiZoom: number;
  setUiZoom: (z: number) => void;

  // API key state
  keyStatus: Record<string, boolean>;
  apiKeys: ApiKeys;
  setApiKeys: React.Dispatch<React.SetStateAction<ApiKeys>>;

  // Ollama endpoint (not a secret -- a configurable local/remote base URL)
  ollamaBaseUrl: string;
  setOllamaBaseUrl: React.Dispatch<React.SetStateAction<string>>;
  saveOllamaEndpoint: (url: string) => Promise<void>;

  // Tool registry
  toolCatalog: ToolEntry[];
  toolCoverage: string;
  refreshToolRegistry: () => Promise<void>;

  // Service login (connect external provider)
  showServiceLogin: string | null;
  setShowServiceLogin: React.Dispatch<React.SetStateAction<string | null>>;
  serviceKeyInput: string;
  setServiceKeyInput: React.Dispatch<React.SetStateAction<string>>;

  // Diagnostics
  diagnosticResult: string[] | null;
  isDiagnosing: boolean;
  runDiagnostics: () => Promise<void>;
}

const SettingsContext = createContext<SettingsContextValue | null>(null);

export function useSettings(): SettingsContextValue {
  const ctx = useContext(SettingsContext);
  if (!ctx) throw new Error("useSettings must be used inside <SettingsProvider>");
  return ctx;
}

// ── Provider ─────────────────────────────────────────────────────────────────

export function SettingsProvider({ children }: { children: React.ReactNode }) {
  const showError = useErrorToast();
  const [showSettings, setShowSettings] = useState(false);
  const [settingsTab, setSettingsTab] = useState<
    "keys" | "roles" | "diagnostics" | "skin" | "network"
  >("keys");
  const [networkPolicyState, setNetworkPolicyState] = useState<NetworkPolicyMode>("cloaked");
  const [keyStatus, setKeyStatus] = useState<Record<string, boolean>>({});
  const [apiKeys, setApiKeys] = useState<ApiKeys>({
    openai_key: "",
    anthropic_key: "",
    gemini_key: "",
    groq_key: "",
    deepseek_key: "",
    mistral_key: "",
    openrouter_key: "",
    kimi_key: "",
  });
  const [ollamaBaseUrl, setOllamaBaseUrl] = useState<string>("");
  const [toolCatalog, setToolCatalog] = useState<ToolEntry[]>([]);
  const [toolCoverage, setToolCoverage] = useState("0/0");
  const [showServiceLogin, setShowServiceLogin] = useState<string | null>(null);
  const [serviceKeyInput, setServiceKeyInput] = useState("");
  const [diagnosticResult, setDiagnosticResult] = useState<string[] | null>(null);
  const [isDiagnosing, setIsDiagnosing] = useState(false);

  // Privacy posture is the one setting that must never be optimistically
  // reported. This used invokeSafe (which swallows failures into null) in a
  // fire-and-forget .catch(console.error), so if the backend never applied the
  // policy the UI still showed "Offline / Local only" and localStorage agreed
  // -- the user believed network egress was blocked when it was not. For a
  // product whose central claim is privacy sovereignty, a silently unapplied
  // policy is the most dangerous failure in the app.
  //
  // Now: raw invoke so a rejection is real, and on failure the displayed policy
  // is rolled back to what is actually in force, with an error the UI shows.
  const [networkPolicyError, setNetworkPolicyError] = useState<string | null>(null);

  // Read in an effect, not in the useState initializer: localStorage does not
  // exist during SSR, and reading it while rendering desyncs server and client
  // markup (the same trap usePanelWidth documents).
  const [uiDensity, setUiDensityState] = useState<UiDensity>("comfortable");
  const [uiZoom, setUiZoomState] = useState(1);
  useEffect(() => {
    const d = readStoredDensity();
    const z = readStoredZoom();
    setUiDensityState(d);
    setUiZoomState(z);
    applyDensity(d, z);
  }, []);

  const setUiDensity = useCallback(
    (d: UiDensity) => {
      setUiDensityState(d);
      applyDensity(d, uiZoom);
      try {
        window.localStorage.setItem(UI_DENSITY_STORAGE_KEY, d);
      } catch {
        /* storage disabled -- the setting still applies for this session */
      }
    },
    [uiZoom]
  );

  const setUiZoom = useCallback(
    (z: number) => {
      const clamped = clampZoom(z);
      setUiZoomState(clamped);
      applyDensity(uiDensity, clamped);
      try {
        window.localStorage.setItem(UI_ZOOM_STORAGE_KEY, String(clamped));
      } catch {
        /* storage disabled */
      }
    },
    [uiDensity]
  );

  // Ctrl/Cmd +/-/0 is muscle memory in every editor. Bound here rather than in a
  // panel so it works from anywhere in the app.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.ctrlKey || e.metaKey)) return;
      const dir =
        e.key === "+" || e.key === "="
          ? "in"
          : e.key === "-"
            ? "out"
            : e.key === "0"
              ? "reset"
              : null;
      if (!dir) return;
      e.preventDefault();
      setUiZoom(nextZoom(uiZoom, dir));
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [uiZoom, setUiZoom]);

  useEffect(() => {
    const policy = readStoredNetworkPolicy();
    setNetworkPolicyState(policy);
    if (!isTauri()) return;
    invoke("sync_network_policy", { policy }).catch((e: unknown) => {
      setNetworkPolicyError(
        `Could not apply the saved "${policy}" network policy at startup: ${
          e instanceof Error ? e.message : String(e)
        }. Treat the network as UNRESTRICTED until this is resolved.`
      );
    });
  }, []);

  const setNetworkPolicy = useCallback((mode: NetworkPolicyMode) => {
    const previous = readStoredNetworkPolicy();
    setNetworkPolicyState(mode);
    storeNetworkPolicy(mode);
    setNetworkPolicyError(null);
    if (!isTauri()) return;
    invoke("sync_network_policy", { policy: mode }).catch((e: unknown) => {
      // Roll back rather than display a posture that is not in force.
      setNetworkPolicyState(previous);
      storeNetworkPolicy(previous);
      setNetworkPolicyError(
        `Could not switch the network policy to "${mode}": ${
          e instanceof Error ? e.message : String(e)
        }. Still on "${previous}".`
      );
    });
  }, []);

  // Refresh key status + tool registry (called on settings open and after saves).
  const refreshToolRegistry = useCallback(async () => {
    try {
      const reg = await getToolRegistry();
      setToolCatalog(reg.tools || []);
      setToolCoverage(reg.coverage || "0/0");
    } catch {
      /* ignore */
    }
  }, []);

  // Reload when the settings modal opens (mirrors the original useEffect([showSettings])).
  useEffect(() => {
    getApiKeyStatus()
      .then((data) => setKeyStatus(data as unknown as Record<string, boolean>))
      .catch((e) => showError(`Failed to load API key status: ${e}`));
    getOllamaBaseUrl()
      .then((url) => setOllamaBaseUrl(url || ""))
      .catch(() => {});
    refreshToolRegistry();
  }, [showSettings, refreshToolRegistry]);

  const saveOllamaEndpoint = useCallback(async (url: string) => {
    await saveOllamaBaseUrl(url);
    setOllamaBaseUrl(url);
  }, []);

  const runDiagnostics = useCallback(async () => {
    setIsDiagnosing(true);
    setDiagnosticResult(["Running systems check..."]);
    try {
      const dbg: string[] = [];
      const ollama = await checkOllamaStatus(ollamaBaseUrl || undefined);
      if (ollama?.ok) {
        dbg.push(`✓ Ollama online`);
      } else {
        dbg.push(`✗ Ollama offline/error: ${ollama?.error || "Unknown"}`);
      }
      const models = await getModelsRegistry();
      const tiers = models?.tiers?.length || 0;
      dbg.push(tiers > 0 ? `✓ Models registry alive (${tiers} tiers)` : `✗ Models registry empty`);
      const tools = await getToolRegistry();
      const online = tools?.online || 0;
      const total = tools?.total || 0;
      dbg.push(`ℹ Tool registry: ${online}/${total} tools active`);
      const keys = await getApiKeyStatus();
      const total_providers = Object.keys(keys).length;
      const activeKeys = Object.values(keys).filter((v) => v === true).length;
      dbg.push(`ℹ API Keys: ${activeKeys}/${total_providers} configured`);
      setDiagnosticResult(dbg);
    } catch (e) {
      setDiagnosticResult((prev) => [...(prev ?? []), `✗ Diagnostic failure: ${e}`]);
    } finally {
      setIsDiagnosing(false);
    }
  }, [ollamaBaseUrl]);

  return (
    <SettingsContext.Provider
      value={{
        showSettings,
        setShowSettings,
        settingsTab,
        setSettingsTab,
        networkPolicy: networkPolicyState,
        setNetworkPolicy,
        networkPolicyError,
        dismissNetworkPolicyError: () => setNetworkPolicyError(null),
        uiDensity,
        setUiDensity,
        uiZoom,
        setUiZoom,
        keyStatus,
        apiKeys,
        setApiKeys,
        ollamaBaseUrl,
        setOllamaBaseUrl,
        saveOllamaEndpoint,
        toolCatalog,
        toolCoverage,
        refreshToolRegistry,
        showServiceLogin,
        setShowServiceLogin,
        serviceKeyInput,
        setServiceKeyInput,
        diagnosticResult,
        isDiagnosing,
        runDiagnostics,
      }}
    >
      {children}
    </SettingsContext.Provider>
  );
}
