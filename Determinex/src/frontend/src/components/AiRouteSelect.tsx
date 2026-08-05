"use client";

import { Bot, CheckCircle2, Cloud, Cpu, Zap, AlertTriangle } from "lucide-react";
import {
  AI_ROUTE_OPTIONS,
  routeKeyReady,
  routeReadinessLabel,
  type ApiKeyStatus,
} from "@/lib/aiRouting";

import { useAiRouter } from "@/contexts/AiRouterContext";

export function AiRouteSelect({
  value,
  onChange,
  keyStatus = {},
  compact = false,
}: {
  value?: string;
  onChange?: (value: string) => void;
  keyStatus?: ApiKeyStatus;
  compact?: boolean;
}) {
  const router = useAiRouter();
  const activeValue = value !== undefined ? value : router.selectedModel;
  const activeOnChange = onChange !== undefined ? onChange : router.changeModel;
  const { allowedOptions } = router;

  return (
    <label className="flex flex-col gap-2">
      <span className="text-meta font-black uppercase tracking-widest text-gray-500">AI route</span>
      <select
        value={activeValue}
        onChange={(event) => activeOnChange(event.target.value)}
        data-testid="ai-route-select"
        className={`w-full rounded-lg border border-white/10 bg-black/60 px-3 text-xs text-gray-200 outline-none transition focus:border-cyan-400/60 ${
          compact ? "py-2" : "py-2.5"
        }`}
      >
        {allowedOptions.map((option) => (
          <option key={option.id} value={option.id}>
            {option.label} - {routeReadinessLabel(option.id, keyStatus)}
          </option>
        ))}
      </select>
    </label>
  );
}

export function AiRouteSummary({
  value,
  keyStatus = {},
  onChange,
  onOpenSettings,
}: {
  value?: string;
  keyStatus?: ApiKeyStatus;
  onChange?: (value: string) => void;
  onOpenSettings?: () => void;
}) {
  const router = useAiRouter();
  const activeValue = value !== undefined ? value : router.selectedModel;
  const activeOnChange = onChange !== undefined ? onChange : router.changeModel;
  const { allowedOptions } = router;

  const option = allowedOptions.find((candidate) => candidate.id === activeValue);
  const ready = routeKeyReady(activeValue, keyStatus);
  const Icon =
    option?.kind === "free_cloud"
      ? Zap
      : option?.kind === "cloud"
        ? Cloud
        : option?.kind === "local"
          ? Cpu
          : Bot;

  return (
    <div
      data-testid="ai-selection-block"
      className="rounded-xl border border-white/10 bg-black/35 px-3 py-2 shadow-lg animate-fade-in"
    >
      <div className="flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-cyan-400/20 bg-cyan-400/10 text-cyan-300">
            <Icon size={15} />
          </div>
          <div className="min-w-0">
            <div className="truncate text-meta font-black uppercase tracking-widest text-white">
              {option?.label ?? activeValue}
            </div>
            <div className="truncate text-meta font-mono text-gray-600">
              {option?.providerLabel ?? "Custom"} · {option?.note ?? "custom route"}
            </div>
          </div>
        </div>
        <button
          type="button"
          onClick={onOpenSettings}
          className={`flex shrink-0 items-center gap-1 rounded-full border px-2 py-1 text-eyebrow font-black uppercase tracking-widest ${
            ready
              ? "border-emerald-500/25 bg-emerald-950/30 text-emerald-400"
              : "border-amber-500/25 bg-amber-950/25 text-amber-300"
          }`}
        >
          {ready && <CheckCircle2 size={10} />}
          {routeReadinessLabel(activeValue, keyStatus)}
        </button>
      </div>

      {router.routeWarnings.length > 0 && (
        <div className="mt-2 text-meta text-amber-400/90 font-mono leading-relaxed bg-amber-950/20 border border-amber-500/10 rounded p-1.5 flex items-start gap-1">
          <AlertTriangle className="h-3 w-3 shrink-0 mt-0.5" />
          <span>{router.routeWarnings[0]}</span>
        </div>
      )}

      {onChange && (
        <div className="mt-2">
          <select
            value={activeValue}
            onChange={(event) => activeOnChange(event.target.value)}
            data-testid="ai-selection-block-select"
            className="w-full rounded-lg border border-white/10 bg-black/60 px-2 py-1.5 text-label text-gray-200 outline-none focus:border-cyan-400/60"
          >
            {allowedOptions.map((route) => (
              <option key={route.id} value={route.id}>
                {route.label} - {routeReadinessLabel(route.id, keyStatus)}
              </option>
            ))}
          </select>
        </div>
      )}
    </div>
  );
}
