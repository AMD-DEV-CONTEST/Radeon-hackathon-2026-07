// CLAUDE LANE — Local model settings panel.
// Locked under: locks/sentinel/LOCAL_MODEL_SETTINGS_PANEL_LOCK_001.json
//
// UI for configuring a local model. Provider, model id, digest, capabilities,
// task classes. dry_run_default defaults to true. Network providers are
// blocked. Stale id warning is rendered statically based on the known
// stale set. The Save button posts through the Tauri bridge; no live
// model call is performed on save.

"use client";
import * as React from "react";

import { IdeRepairResponse, invokeIdeCommand } from "@/lib/ide-repair-api";
import { invokeSafe } from "@/lib/api";

type StoredLocalModelConfig = {
  provider: string;
  model_id: string;
  digest: string;
  capabilities: string;
  task_classes: string;
  dry_run_default: boolean;
};

/**
 * Consumed OUTSIDE the TypeScript import graph: a Python lock test reads this
 * array out of the source text and asserts the closed set matches the Rust side.
 * knip cannot see that, so without this tag it reports the export as unused --
 * and deleting it would break the lock while the type-checker stayed green.
 * @public
 */
export const LOCAL_MODEL_SETTINGS_PANEL_STATUS_TOKENS = [
  "LOCAL_MODEL_SETTINGS_PANEL_READY",
  "LOCAL_MODEL_CONFIG_DRY_RUN_DEFAULT",
  "LOCAL_MODEL_NETWORK_PROVIDER_BLOCKED",
  "LOCAL_MODEL_SAVE_NO_LIVE_CALL",
  "LOCAL_MODEL_STALE_ID_WARNING_VISIBLE",
] as const;

const PROVIDERS = [
  { value: "no_model", label: "No model (offline)" },
  { value: "ollama", label: "Ollama (local)" },
  { value: "local_hf", label: "Local Hugging Face" },
  { value: "executable_adapter", label: "Executable adapter (local)" },
] as const;

// Mirrors STALE_MODEL_IDS from scripts/models/model_router.py.
const STALE_MODEL_IDS = [
  "determinex-engineer-v10-dsl",
  "determinex-engineer-v9-dsl",
  "determinex-engineer-v8",
  "determinex-observer-v5-dsl",
  "determinex-observer-v5",
  "determinex-observer-v4",
  "determinex-observer-v3",
  "determinex-sentinel-v4",
  "determinex-sentinel-v3",
  "determinex-sentinel-v2",
];

// Network provider tokens we refuse outright in the UI.
const NETWORK_PROVIDER_TOKENS = [
  "anthropic",
  "openai",
  "google",
  "deepseek",
  "gemini",
  "openrouter",
  "vllm-remote",
  "cloud",
  "network",
];

export function LocalModelSettingsPanel() {
  const [provider, setProvider] = React.useState<string>("no_model");
  const [modelId, setModelId] = React.useState<string>("");
  const [digest, setDigest] = React.useState<string>("");
  const [capabilities, setCapabilities] = React.useState<string>("");
  const [taskClasses, setTaskClasses] = React.useState<string>("BUILD_DIAGNOSIS,PATCH_GENERATION");
  const [dryRunDefault, setDryRunDefault] = React.useState<boolean>(true);
  const [liveOptInUnderstood, setLiveOptInUnderstood] = React.useState<boolean>(false);
  const [saveResp, setSaveResp] = React.useState<IdeRepairResponse | null>(null);

  React.useEffect(() => {
    (async () => {
      const stored = await invokeSafe<StoredLocalModelConfig | null>("get_local_model_config", {});
      if (!stored) return;
      setProvider(stored.provider || "no_model");
      setModelId(stored.model_id || "");
      setDigest(stored.digest || "");
      setCapabilities(stored.capabilities || "");
      setTaskClasses(stored.task_classes || "BUILD_DIAGNOSIS,PATCH_GENERATION");
      setDryRunDefault(stored.dry_run_default ?? true);
    })();
  }, []);

  const isStale = STALE_MODEL_IDS.includes(modelId.trim());
  const networkBlocked = NETWORK_PROVIDER_TOKENS.includes(provider.trim().toLowerCase());

  const canSave = !networkBlocked && !isStale;

  const save = React.useCallback(async () => {
    if (!canSave) return;
    // No live model call. Save writes config only, via a plain Tauri command
    // (save_local_model_config) -- never invokes a model.
    const config: StoredLocalModelConfig = {
      provider,
      model_id: modelId,
      digest,
      capabilities,
      task_classes: taskClasses,
      dry_run_default: dryRunDefault,
    };
    const r = await invokeIdeCommand("get_repair_flow_state", {});
    try {
      await invokeSafe("save_local_model_config", { config });
      setSaveResp({
        ...r,
        command: "local_model_settings:save",
        payload: config,
        notes: [...r.notes, "no live model call performed on save", "config persisted"],
      });
    } catch (e) {
      setSaveResp({
        ...r,
        command: "local_model_settings:save",
        payload: config,
        notes: [...r.notes, "no live model call performed on save", `save failed: ${e}`],
      });
    }
  }, [canSave, provider, modelId, digest, capabilities, taskClasses, dryRunDefault]);

  return (
    <section
      data-testid="local-model-settings-panel"
      className="rounded border p-3 text-sm space-y-3"
    >
      <header>
        <h3 className="font-medium">Local Model Settings</h3>
        <p className="text-xs opacity-70" data-testid="local-model-dry-run-default-note">
          Dry-run is the default. No live model call is made on save.
        </p>
      </header>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-2 text-xs">
        <label className="space-y-1">
          <span className="opacity-70">Provider</span>
          <select
            value={provider}
            onChange={(e) => setProvider(e.target.value)}
            className="w-full rounded border bg-transparent px-1 py-1"
            data-testid="local-model-provider-select"
          >
            {PROVIDERS.map((p) => (
              <option key={p.value} value={p.value}>
                {p.label}
              </option>
            ))}
          </select>
        </label>

        <label className="space-y-1">
          <span className="opacity-70">Model ID</span>
          <input
            type="text"
            value={modelId}
            onChange={(e) => setModelId(e.target.value)}
            placeholder="e.g. determinex-engineer-v11-dsl"
            className="w-full rounded border bg-transparent px-1 py-1 font-mono"
            data-testid="local-model-id-input"
          />
        </label>

        <label className="space-y-1">
          <span className="opacity-70">Digest / revision</span>
          <input
            type="text"
            value={digest}
            onChange={(e) => setDigest(e.target.value)}
            placeholder="sha256:… or git rev"
            className="w-full rounded border bg-transparent px-1 py-1 font-mono"
            data-testid="local-model-digest-input"
          />
        </label>

        <label className="space-y-1">
          <span className="opacity-70">Capabilities (csv)</span>
          <input
            type="text"
            value={capabilities}
            onChange={(e) => setCapabilities(e.target.value)}
            placeholder="diagnose,code_generation"
            className="w-full rounded border bg-transparent px-1 py-1"
            data-testid="local-model-capabilities-input"
          />
        </label>

        <label className="space-y-1 md:col-span-2">
          <span className="opacity-70">Task classes allowed (csv)</span>
          <input
            type="text"
            value={taskClasses}
            onChange={(e) => setTaskClasses(e.target.value)}
            className="w-full rounded border bg-transparent px-1 py-1"
            data-testid="local-model-task-classes-input"
          />
        </label>

        <label className="flex items-center gap-2 text-xs md:col-span-2">
          <input
            type="checkbox"
            checked={dryRunDefault}
            onChange={(e) => setDryRunDefault(e.target.checked)}
            data-testid="local-model-dry-run-default-toggle"
          />
          dry_run_default (recommended)
        </label>

        <label className="flex items-start gap-2 text-xs md:col-span-2">
          <input
            type="checkbox"
            checked={liveOptInUnderstood}
            onChange={(e) => setLiveOptInUnderstood(e.target.checked)}
            data-testid="local-model-live-opt-in-warning-checkbox"
          />
          <span data-testid="local-model-live-opt-in-warning">
            I understand: enabling live mode lets the model produce advisory output. Output remains
            untrusted and source mutation is still gated.
          </span>
        </label>
      </div>

      {networkBlocked && (
        <div
          className="rounded border border-red-500/30 bg-red-500/5 p-2 text-xs"
          data-testid="local-model-network-blocked-note"
        >
          Network/cloud providers are blocked. Pick a local provider.
        </div>
      )}
      {isStale && (
        <div
          className="rounded border border-red-500/30 bg-red-500/5 p-2 text-xs"
          data-testid="local-model-stale-id-warning"
        >
          Model ID {modelId} is in the known-stale set. Pick the current generation.
        </div>
      )}

      <div className="flex items-center gap-2">
        <button
          type="button"
          disabled={!canSave}
          onClick={() => void save()}
          className="rounded border px-2 py-1 text-xs disabled:opacity-50"
          data-testid="local-model-save-button"
        >
          Save (no live call)
        </button>
        <span className="text-xs opacity-70" data-testid="local-model-save-no-live-note">
          Save writes config only. No model is invoked.
        </span>
      </div>

      {saveResp && (
        <pre
          className="overflow-auto rounded bg-muted/50 p-2 text-xs"
          data-testid="local-model-save-result"
        >
          {JSON.stringify(saveResp, null, 2)}
        </pre>
      )}
    </section>
  );
}
