"use client";
import { useState } from "react";
import { Loader2, Plus } from "lucide-react";
import { addCustomRegistryModel } from "@/lib/api";

/**
 * Register a model this build has never heard of.
 *
 * Ryan, live: "users should be able to add future llms that dont have access at
 * the moment, we should make sure we are compatable with EVERYTHING."
 *
 * The backend for this already existed -- `add_custom_registry_model` in
 * registry.rs, with a typed wrapper in api.ts -- and NOTHING in the UI ever
 * called it. There was no way for a user to add a model at all. The persisted
 * entry also had no endpoint field, so even once called it could only name a
 * model, never say where to send the request; anything outside the built-in
 * provider table stayed unreachable. Both halves are fixed: registry.rs now
 * stores `base_url`/`api_key_env`, and determinex_providers.py reads the same
 * file at import and registers a real provider for each entry (see
 * tests/test_custom_providers.py).
 *
 * A base URL plus a model id is enough for effectively any provider, current or
 * future: vendors and local servers alike (vLLM, llama.cpp, LM Studio, Ollama,
 * OpenRouter, Together, Fireworks) all expose an OpenAI-compatible /v1 surface.
 *
 * The API key is taken as the NAME of an environment variable, never the secret.
 * The registry is plain JSON in the app data directory and is read by the Python
 * engine, so a key pasted in here would land in every backup of that directory.
 */

interface Props {
  /** Called after a successful add so the caller can refetch the registry. */
  onAdded?: (modelId: string) => void;
}

export function AddCustomModel({ onAdded }: Props) {
  const [open, setOpen] = useState(false);
  const [modelId, setModelId] = useState("");
  const [label, setLabel] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKeyEnv, setApiKeyEnv] = useState("");
  const [contextWindow, setContextWindow] = useState("128000");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  const reset = () => {
    setModelId("");
    setLabel("");
    setBaseUrl("");
    setApiKeyEnv("");
    setContextWindow("128000");
    setError(null);
  };

  const submit = async () => {
    const id = modelId.trim();
    if (!id) {
      setError("A model id is required — it is the string sent to the provider.");
      return;
    }
    if (baseUrl.trim() && !/^https?:\/\//i.test(baseUrl.trim())) {
      setError("The base URL must start with http:// or https://");
      return;
    }
    setSaving(true);
    setError(null);
    setDone(null);
    try {
      const res = await addCustomRegistryModel({
        id,
        provider: baseUrl.trim() ? "custom" : "litellm",
        name: label.trim() || id,
        desc: baseUrl.trim()
          ? `User-added, via ${baseUrl.trim()}`
          : "User-added, routed on its model id",
        elo_rating: 0,
        context_window: Number(contextWindow) || 0,
        speed_ms_per_token: null,
        tier_id: "custom",
        base_url: baseUrl.trim() || null,
        api_key_env: apiKeyEnv.trim() || null,
      });
      // add_custom_registry_model returns { status, message } -- surface the
      // message rather than assuming success, since "already exists" also comes
      // back as status "success" and the user should see which happened.
      const message =
        res && typeof res === "object" && "message" in res
          ? String((res as { message: unknown }).message)
          : "Added.";
      setDone(message);
      onAdded?.(id);
      reset();
    } catch (e) {
      setError(`Could not add the model: ${e}`);
    } finally {
      setSaving(false);
    }
  };

  if (!open) {
    return (
      <button
        type="button"
        data-testid="add-custom-model-open"
        onClick={() => setOpen(true)}
        className="flex w-full items-center justify-center gap-1.5 border-t border-[var(--dtx-code-border)] px-4 py-2.5 text-meta font-bold uppercase tracking-widest text-gray-400 transition-colors hover:bg-[var(--dtx-code-panel)] hover:text-white"
      >
        <Plus size={11} /> Add a model
      </button>
    );
  }

  return (
    <div
      className="space-y-2 border-t border-[var(--dtx-code-border)] bg-[var(--dtx-code-bg-deep)] p-3"
      data-testid="add-custom-model-form"
    >
      <p className="text-meta leading-relaxed text-gray-500">
        Any OpenAI-compatible endpoint works, including a model that does not exist yet. Leave the
        base URL empty for a provider Determinex already knows (then the id alone routes it, e.g.{" "}
        <span className="font-mono text-gray-400">anthropic/claude-next</span>).
      </p>

      <Field label="Model id" hint="sent verbatim to the provider">
        <input
          data-testid="custom-model-id"
          value={modelId}
          onChange={(e) => setModelId(e.target.value)}
          placeholder="some-model-from-2027"
          className="w-full rounded border border-[var(--dtx-code-border)] bg-[var(--dtx-code-bg)] px-2 py-1.5 font-mono text-label text-gray-200 outline-none focus:border-cyan-500"
        />
      </Field>

      <Field label="Display name" hint="optional">
        <input
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          placeholder={modelId || "Future Vendor 9000"}
          className="w-full rounded border border-[var(--dtx-code-border)] bg-[var(--dtx-code-bg)] px-2 py-1.5 text-label text-gray-200 outline-none focus:border-cyan-500"
        />
      </Field>

      <Field label="Base URL" hint="OpenAI-compatible, optional">
        <input
          data-testid="custom-model-base-url"
          value={baseUrl}
          onChange={(e) => setBaseUrl(e.target.value)}
          placeholder="http://localhost:8000/v1"
          className="w-full rounded border border-[var(--dtx-code-border)] bg-[var(--dtx-code-bg)] px-2 py-1.5 font-mono text-label text-gray-200 outline-none focus:border-cyan-500"
        />
      </Field>

      <Field label="API key env var" hint="the NAME, never the key">
        <input
          data-testid="custom-model-key-env"
          value={apiKeyEnv}
          onChange={(e) => setApiKeyEnv(e.target.value)}
          placeholder="FUTURE_VENDOR_KEY"
          className="w-full rounded border border-[var(--dtx-code-border)] bg-[var(--dtx-code-bg)] px-2 py-1.5 font-mono text-label text-gray-200 outline-none focus:border-cyan-500"
        />
      </Field>

      <Field label="Context window" hint="tokens">
        <input
          value={contextWindow}
          onChange={(e) => setContextWindow(e.target.value.replace(/[^0-9]/g, ""))}
          inputMode="numeric"
          className="w-full rounded border border-[var(--dtx-code-border)] bg-[var(--dtx-code-bg)] px-2 py-1.5 font-mono text-label text-gray-200 outline-none focus:border-cyan-500"
        />
      </Field>

      {error && (
        <p className="rounded border border-red-400/30 bg-red-950/20 px-2 py-1.5 text-meta text-red-300">
          {error}
        </p>
      )}
      {done && (
        <p className="rounded border border-emerald-400/30 bg-emerald-950/20 px-2 py-1.5 text-meta text-emerald-300">
          {done} Restart the engine for it to pick up a new endpoint.
        </p>
      )}

      <div className="flex gap-1.5 pt-0.5">
        <button
          type="button"
          onClick={() => {
            setOpen(false);
            reset();
            setDone(null);
          }}
          className="flex-1 rounded border border-white/10 px-2 py-1.5 text-eyebrow font-bold uppercase tracking-widest text-gray-400 hover:bg-white/5"
        >
          Cancel
        </button>
        <button
          type="button"
          data-testid="custom-model-save"
          onClick={submit}
          disabled={saving}
          className="flex flex-1 items-center justify-center gap-1.5 rounded border border-cyan-500/40 bg-cyan-950/30 px-2 py-1.5 text-eyebrow font-bold uppercase tracking-widest text-cyan-300 hover:bg-cyan-950/60 disabled:opacity-50"
        >
          {saving ? <Loader2 size={10} className="animate-spin" /> : <Plus size={10} />} Add
        </button>
      </div>
    </div>
  );
}

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-1 flex items-baseline gap-1.5">
        <span className="text-eyebrow font-black uppercase tracking-widest text-gray-400">
          {label}
        </span>
        {hint && <span className="text-meta text-gray-600">{hint}</span>}
      </span>
      {children}
    </label>
  );
}
