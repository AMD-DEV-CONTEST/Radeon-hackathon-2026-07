import type { RoleAssignments } from "@/lib/api";

export interface InstalledModel {
  id: string;
  name: string;
  size_gb: number;
  param_size: string;
  is_determinex: boolean;
}

export type WorkReadinessStatus = "unknown" | "checking" | "ready" | "attention" | "offline";

export interface WorkReadiness {
  status: WorkReadinessStatus;
  ready: boolean;
  label: string;
  summary: string;
  details: string[];
  missingRoles: string[];
  checkedAt?: number;
}

const ROLE_LABELS: Record<keyof RoleAssignments, string> = {
  oracle: "Oracle",
  architect: "Architect",
  builder: "Builder",
  monitor: "Monitor",
};

// One tag per role: the current one.
//
// These lists carried a legacy pre-rename tag as a second entry, so a box that had not
// re-tagged its models still resolved as ready. Removed 2026-07-29: `ollama list` shows
// the current determinex-* tags installed and current, which makes the fallbacks dead
// weight that keeps a retired name alive in the model resolver.
//
// A machine carrying ONLY the pre-rename tags will now read as not-ready, which is the
// correct answer -- it needs the models re-registered (register_models.ps1) rather than a
// resolver that quietly accepts an obsolete name forever.
const MODEL_ALIASES: Record<string, string[]> = {
  "local/fast": ["qwen2.5-coder:3b-instruct"],
  "local/coder": ["qwen2.5-coder:1.5b-instruct"],
  "local/smart": ["mistral"],
  "determinex/engineer": ["determinex-engineer-v11-dsl"],
  "determinex/observer": ["determinex-observer-v6-dsl"],
  "determinex/sentinel": ["determinex-sentinel-v5-dsl"],
  "determinex/qwen7b": ["qwen2.5-coder:7b-instruct"],
};

function isCloudModel(modelId: string): boolean {
  return /^(cloud|openai|anthropic|gemini|deepseek)\//.test(modelId);
}

function normalizeModelId(modelId: string): string {
  return modelId
    .trim()
    .replace(/^ollama\//, "")
    .replace(/:latest$/, "")
    .toLowerCase();
}

function modelMatches(installed: Set<string>, expected: string): boolean {
  const target = normalizeModelId(expected);
  return installed.has(target) || installed.has(`${target}:latest`);
}

// Was displayModelId(), which rewrote a legacy pre-rename tag to the current name for
// display. That is the overclaim pattern in miniature: if a config genuinely names an
// obsolete model, showing it under the current name hides the one fact the reader needs.
// The configured value is now shown verbatim.

export function expectedLocalModels(modelId: string): string[] {
  const trimmed = modelId.trim();
  if (!trimmed || isCloudModel(trimmed)) return [];
  if (MODEL_ALIASES[trimmed]) return MODEL_ALIASES[trimmed];
  return [trimmed.replace(/^ollama\//, "")];
}

/**
 * Resolve a router route id into a concrete Ollama tag for the local-only IDE
 * commands (preview_idea_oracle / build_idea).
 *
 * These go to scripts/ide/_tauri_driver.py, whose _build_local_config() writes
 * a pinned local-model config and returns None if the id is not a real local
 * model -- which the surface reports as BLOCKED_NO_MODEL. Router aliases are
 * NOT model tags, so passing the picker's value straight through blocked the
 * build. Verified against the driver directly:
 *
 *   'auto'                       -> None            (blocked)
 *   'local/fast'                 -> None            (blocked)
 *   ''                           -> WRITTEN         (driver's pinned default)
 *   'determinex-engineer-v11-dsl'-> WRITTEN
 *
 * "Auto" is the picker's default, so out of the box every verified build was
 * refused. Returning "" for anything that is not a concrete local tag lets the
 * driver fall back to its own pinned default instead of being handed a name
 * Ollama has never heard of.
 */
export function resolveLocalModelTag(modelId?: string): string {
  const trimmed = (modelId ?? "").trim();
  if (!trimmed || trimmed === "auto") return "";
  return expectedLocalModels(trimmed)[0] ?? "";
}

export function evaluateWorkReadiness(input: {
  ollamaOk: boolean;
  ollamaError?: string;
  roles: RoleAssignments;
  models: InstalledModel[];
}): WorkReadiness {
  if (!input.ollamaOk) {
    return {
      status: "offline",
      ready: false,
      label: "Ollama Offline",
      summary:
        input.ollamaError || "Ollama is not reachable. Start Ollama before generating specs.",
      details: [],
      missingRoles: Object.keys(input.roles),
      checkedAt: Date.now(),
    };
  }

  const installed = new Set(
    input.models.flatMap((model) => [model.id, model.name]).map((id) => normalizeModelId(id))
  );
  const missing: string[] = [];
  const cloud: string[] = [];
  const details: string[] = [];

  (Object.keys(input.roles) as (keyof RoleAssignments)[]).forEach((role) => {
    const assignment = input.roles[role];
    if (isCloudModel(assignment)) {
      cloud.push(`${ROLE_LABELS[role]} uses ${assignment}`);
      return;
    }

    const expected = expectedLocalModels(assignment);
    const found = expected.some((modelId) => modelMatches(installed, modelId));
    if (found) {
      details.push(`${ROLE_LABELS[role]} -> ${assignment}`);
    } else {
      missing.push(`${ROLE_LABELS[role]} needs ${expected.join(" or ") || assignment}`);
    }
  });

  if (missing.length > 0) {
    return {
      status: "attention",
      ready: false,
      label: "Attention",
      summary: `Missing local model coverage for ${missing.length} role${missing.length === 1 ? "" : "s"}.`,
      details: missing,
      missingRoles: missing,
      checkedAt: Date.now(),
    };
  }

  if (cloud.length > 0) {
    return {
      status: "attention",
      ready: false,
      label: "Cloud Selected",
      summary:
        "One or more Hive roles use cloud models. Confirm API keys or switch to local roles before generating.",
      details: cloud,
      missingRoles: cloud,
      checkedAt: Date.now(),
    };
  }

  return {
    status: "ready",
    ready: true,
    label: "Model Ready",
    summary: "All local Hive roles resolve to installed Ollama models.",
    details,
    missingRoles: [],
    checkedAt: Date.now(),
  };
}

export function specGenerationBlockMessage(readiness?: WorkReadiness): string | null {
  if (!readiness || readiness.ready) return null;
  const detailLine = readiness.details.length
    ? `\n\n${readiness.details.slice(0, 3).join("\n")}`
    : "";
  return `I need model readiness fixed before I write the spec. ${readiness.summary}${detailLine}`;
}
