"use client";

/**
 * RuntimeCapabilityCard — what this machine can actually do, and what it has actually spent.
 *
 * WHY THIS EXISTS
 * ---------------
 * Two facts had no user-visible surface at all:
 *
 *  1. The accelerator. Detection probed `nvidia-smi` and nothing else, so an AMD or Apple machine
 *     reported CPU-only and was driven at the lowest tier — 0 resident models, 1 parallel step —
 *     while holding more memory than the top tier requires. Multi-vendor detection now answers the
 *     question; until this card existed, nothing showed the answer.
 *  2. The usage ledger. `determinex_usage_ledger` was referenced by passport.rs but its call and
 *     cost figures never reached the UI, so "local is free" was a claim rather than a reading.
 *
 * HONESTY RULES THIS CARD FOLLOWS
 * -------------------------------
 * A failed probe is NOT rendered as a measurement. The backend deliberately carries the reason
 * instead of a zero, because a zero reads as "measured, and it was nothing" — the exact defect this
 * repo keeps finding. So there are three distinct states, and they look different: loading, a real
 * reading, and unavailable-with-reason. There is no fourth state where an absent value renders as 0.
 */

import { useCallback, useEffect, useState } from "react";
import { Cpu, HardDrive, Activity, AlertTriangle, RefreshCw } from "lucide-react";

import { invokeSafe } from "@/lib/api";

type Accelerator = {
  vendor: string;
  label: string;
  torch_device: string;
  vram_gb: number;
  device_count: number;
  ram_gb: number;
  tier: number;
  tier_label: string;
  max_local_models: number;
  max_parallel_steps: number;
  models_kept_resident: string[];
  /** "vram" | "system_ram" | "none" — which pool the tier came from. Optional so an older
   *  backend that predates the field renders without it rather than showing "undefined". */
  capacity_basis?: string;
  /** Display-only platform detail, e.g. "Qualcomm Snapdragon, ARM64". Empty on x86. */
  platform_note?: string;
};

type Usage = {
  exists?: boolean;
  window_hours?: number;
  total_calls?: number;
  total_est_usd?: number;
  providers?: Record<string, { calls: number; est_usd: number; models: string[] }>;
};

type Payload = {
  accelerator: Accelerator | null;
  accelerator_error?: string;
  usage: Usage | null;
  usage_error?: string;
};

type Response = { payload?: Payload } | null;

type Phase = "loading" | "ready" | "unavailable";

export function RuntimeCapabilityCard() {
  const [phase, setPhase] = useState<Phase>("loading");
  const [data, setData] = useState<Payload | null>(null);
  const [reason, setReason] = useState("");

  const load = useCallback(async () => {
    setPhase("loading");
    // invokeSafe never rejects — it resolves null. So a null result is the failure signal, and
    // treating it as an empty reading would be the bug this card exists to avoid.
    const res = await invokeSafe<Response>("get_runtime_capability_status");
    const payload = res && typeof res === "object" ? (res as { payload?: Payload }).payload : null;
    if (!payload) {
      setReason("The backend did not return a runtime capability reading.");
      setPhase("unavailable");
      return;
    }
    setData(payload);
    setPhase("ready");
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="rounded-xl border border-white/8 bg-white/[0.02] p-4 mt-6">
      <div className="flex items-start justify-between gap-3 mb-3">
        <div>
          <h4 className="text-body font-bold text-white/85 flex items-center gap-2">
            <Cpu size={15} className="text-cyan-400" /> Runtime capability
          </h4>
          <p className="text-label text-gray-500 mt-1">
            Measured on this machine. Nothing here is a default or a placeholder.
          </p>
        </div>
        <button
          onClick={() => void load()}
          disabled={phase === "loading"}
          className="shrink-0 flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.03] px-2.5 py-1.5 text-eyebrow font-black uppercase tracking-widest text-gray-400 disabled:opacity-50 hover:bg-white/[0.06]"
        >
          <RefreshCw size={9} className={phase === "loading" ? "animate-spin" : ""} /> Re-probe
        </button>
      </div>

      {phase === "loading" && (
        <p className="text-label text-gray-500">
          Probing accelerator and reading the usage ledger…
        </p>
      )}

      {phase === "unavailable" && (
        <p className="text-label text-amber-400/90 flex items-start gap-2">
          <AlertTriangle size={13} className="mt-0.5 shrink-0" />
          <span>{reason} No figures are shown, because none were measured.</span>
        </p>
      )}

      {phase === "ready" && data && (
        <div className="space-y-4">
          {/* Accelerator */}
          {data.accelerator ? (
            <div>
              <div className="flex items-center gap-2 text-body text-white/85 font-semibold">
                <HardDrive size={13} className="text-emerald-400" />
                {data.accelerator.label}
              </div>
              <dl className="grid grid-cols-2 gap-x-6 gap-y-1 mt-2 text-label">
                <div className="flex justify-between">
                  <dt className="text-gray-500">Tier</dt>
                  <dd className="text-gray-300">
                    {data.accelerator.tier} — {data.accelerator.tier_label}
                    {/* Tier 1 on 16 GB of VRAM and tier 1 on 24 GB of system RAM are different
                        machines. Naming the pool means a reader never has to infer which. */}
                    {data.accelerator.capacity_basis === "system_ram" && (
                      <span className="text-gray-500"> (from system RAM)</span>
                    )}
                  </dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-gray-500">PyTorch device</dt>
                  <dd className="text-gray-300 font-mono">{data.accelerator.torch_device}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-gray-500">System RAM</dt>
                  <dd className="text-gray-300">
                    {data.accelerator.ram_gb > 0
                      ? `${data.accelerator.ram_gb.toFixed(1)} GB`
                      : "not readable"}
                  </dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-gray-500">Concurrent build steps</dt>
                  <dd className="text-gray-300">{data.accelerator.max_parallel_steps}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-gray-500">Local models allowed</dt>
                  <dd className="text-gray-300">{data.accelerator.max_local_models}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-gray-500">Kept resident</dt>
                  <dd className="text-gray-300">
                    {data.accelerator.models_kept_resident.length > 0
                      ? data.accelerator.models_kept_resident.join(", ")
                      : "none"}
                  </dd>
                </div>
              </dl>
            </div>
          ) : (
            <p className="text-label text-amber-400/90 flex items-start gap-2">
              <AlertTriangle size={13} className="mt-0.5 shrink-0" />
              <span>
                Accelerator not detected
                {data.accelerator_error ? `: ${data.accelerator_error}` : "."} Determinex will run
                on CPU. No VRAM figure is shown, because none was read.
              </span>
            </p>
          )}

          {/* Usage ledger */}
          {data.usage && data.usage.exists ? (
            <div className="border-t border-white/5 pt-3">
              <div className="flex items-center gap-2 text-body text-white/85 font-semibold">
                <Activity size={13} className="text-violet-400" /> Usage
                {typeof data.usage.window_hours === "number" && (
                  <span className="text-meta text-gray-600 font-normal">
                    last {data.usage.window_hours}h
                  </span>
                )}
              </div>
              <dl className="grid grid-cols-2 gap-x-6 gap-y-1 mt-2 text-label">
                <div className="flex justify-between">
                  <dt className="text-gray-500">Calls</dt>
                  <dd className="text-gray-300">{data.usage.total_calls ?? 0}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-gray-500">Estimated spend</dt>
                  <dd className="text-gray-300">${(data.usage.total_est_usd ?? 0).toFixed(4)}</dd>
                </div>
              </dl>
              {data.usage.providers && Object.keys(data.usage.providers).length > 0 && (
                <ul className="mt-2 space-y-0.5">
                  {Object.entries(data.usage.providers).map(([name, p]) => (
                    <li key={name} className="text-meta text-gray-500 flex justify-between">
                      <span className="text-gray-400">{name}</span>
                      <span>
                        {p.calls} call{p.calls === 1 ? "" : "s"} · ${p.est_usd.toFixed(4)}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ) : (
            <p className="text-label text-gray-500 border-t border-white/5 pt-3">
              No usage ledger yet
              {data.usage_error ? `: ${data.usage_error}` : " — nothing has been recorded."}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
