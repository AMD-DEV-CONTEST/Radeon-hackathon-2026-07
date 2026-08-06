import type { StatusTone } from "../../../../components/ui/StatusBadge";
import type { TranslationKey } from "../../../../i18n/messages";
import type {
  ProviderRuntimeResource,
  ProviderRuntimeSnapshot,
} from "../models/providerRuntime";

export interface RuntimePresentationState {
  readonly state: "ready" | "unavailable" | "unknown" | "loading";
  readonly label: TranslationKey;
  readonly description: TranslationKey;
  readonly tone: StatusTone;
  readonly snapshot: ProviderRuntimeSnapshot | null;
}

export function presentProviderRuntime(
  resource: ProviderRuntimeResource,
): RuntimePresentationState {
  if (resource.status === "error") {
    return {
      state: "unknown",
      label: "runtime.state.unknown",
      description: "runtime.reason.unknown",
      tone: "info",
      snapshot: null,
    };
  }

  if (!resource.data) {
    return {
      state: "loading",
      label: "runtime.state.loading",
      description: "runtime.reason.loading",
      tone: "info",
      snapshot: null,
    };
  }

  if (resource.status === "refreshing") {
    return {
      state: "loading",
      label: "runtime.state.refreshing",
      description: "runtime.reason.refreshing",
      tone: "info",
      snapshot: resource.data,
    };
  }

  if (resource.data.visibility === "ready") {
    return {
      state: "ready",
      label:
        resource.data.health === "synthetic"
          ? "runtime.health.synthetic"
          : "runtime.state.ready",
      description: "runtime.reason.ready",
      tone:
        resource.data.health === "healthy" ? "success" : "info",
      snapshot: resource.data,
    };
  }

  return {
    state: "unavailable",
    label: "runtime.state.unavailable",
    description: runtimeReasonKey(resource.data.runtimeStatus),
    tone:
      resource.data.runtimeStatus === "invalid_configuration"
        ? "critical"
        : "warning",
    snapshot: resource.data,
  };
}

export function providerKey(
  snapshot: ProviderRuntimeSnapshot,
): TranslationKey {
  if (snapshot.provider === null) {
    return "runtime.value.notConfigured";
  }
  return `runtime.provider.${snapshot.provider}` as TranslationKey;
}

export function executionKey(
  snapshot: ProviderRuntimeSnapshot,
): TranslationKey {
  return `runtime.execution.${snapshot.execution}` as TranslationKey;
}

export function healthKey(
  snapshot: ProviderRuntimeSnapshot,
): TranslationKey {
  return `runtime.health.${snapshot.health}` as TranslationKey;
}

export function selectionSourceKey(
  snapshot: ProviderRuntimeSnapshot,
): TranslationKey {
  return `runtime.selection.${snapshot.selectionSource}` as TranslationKey;
}

function runtimeReasonKey(
  status: ProviderRuntimeSnapshot["runtimeStatus"],
): TranslationKey {
  return `runtime.reason.${status}` as TranslationKey;
}
