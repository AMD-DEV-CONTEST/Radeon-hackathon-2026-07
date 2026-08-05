import { invoke } from "@tauri-apps/api/core";
import type { WorkReadiness } from "@/lib/work-readiness";
import type { PathInfo } from "@/components/ConceptLab";

// ── Error handling contract ────────────────────────────────────────────────────
//
// Functions in this file follow one of two patterns:
//
// 1. THROWS on error (isTauri-required commands):
//    nativeOrchestratePlan, nativeOrchestrateCodegen, nativeOrchestrateAudit,
//    writeSpecFile, runHiveSession, getHiveSessionStatus, killHiveSession,
//    streamHiveSessionLog, listHiveSessions, getRoleAssignments, setRoleAssignments.
//    These throw if Tauri is absent or the IPC call fails. Callers must try/catch.
//
// 2. RETURNS empty/null on error (soft-fail commands):
//    getThreads, getApiKeyStatus, getFileSystemTree, getModelsRegistry,
//    getToolRegistry, getWorkspaceFiles, getHealthTelemetry, fetchTodos,
//    getOllamaModels, checkOllamaStatus, readFileContent (returns null),
//    discoverIdea, converseIdea, generateSpec, refineSpec, startSession,
//    exploreWorkspace, diagnoseWorkspace, invokeSafe.
//    These return empty structs or null when Tauri is absent. Safe to call
//    during SSR/browser-only dev — callers should handle the empty case.
//
// ─────────────────────────────────────────────────────────────────────────────

// Evaluated lazily at each call site — never baked in at module load time.
// Next.js evaluates modules during SSR/hydration before window.__TAURI_INTERNALS__
// is injected by Tauri, so a module-level constant would permanently bake to false.
export function isTauri(): boolean {
  if (typeof window === "undefined") return false;
  const internals = window.__TAURI_INTERNALS__;
  return (
    typeof internals === "object" &&
    internals !== null &&
    typeof internals["transformCallback"] === "function"
  );
}

// True only for `next dev` (what `tauri dev` runs under the hood) -- false for
// `next build`'s static export, which is what actually ships to a real end
// user. Next.js statically replaces process.env.NODE_ENV at build time, so
// the `false` branch of anything gated on this is dead-code-eliminated from
// the production bundle, not just hidden at runtime. Used to keep Determinex's
// own internal release-tracking tooling (Mission Control, Roadmap) reachable
// while building Determinex itself, without shipping it to end users working
// on their own projects.
export function isInternalBuild(): boolean {
  return process.env.NODE_ENV !== "production";
}

// ── Shared response shapes ─────────────────────────────────────────────────────

interface ThreadsResponse {
  threads: { id: string; title: string; updated: string }[];
}
interface KeyStatusResponse {
  openai: boolean;
  anthropic: boolean;
  gemini: boolean;
  groq: boolean;
  deepseek: boolean;
  mistral: boolean;
  openrouter: boolean;
  kimi: boolean;
}
/** One node of the workspace tree, as the CONSUMERS read it.
 *
 * `tree: any[]` is why the isDir mismatch below survived: with `any`, TypeScript could not
 * see that the field every consumer branches on was never present on the payload. Typed now,
 * so the next field the backend renames fails at compile time instead of rendering a folder
 * as a file for months.
 */
export interface FsTreeNode {
  name: string;
  path: string;
  /** Derived from the backend's `type` by `normalizeTree` -- see getFileSystemTree. */
  isDir: boolean;
  /** What the backend actually sends: "file" | "folder". Kept so the mapping stays visible. */
  type?: string;
  children?: FsTreeNode[];
}

interface FsTreeResponse {
  tree: FsTreeNode[];
}
interface WorkspaceFilesResponse {
  files: { name: string; modified: string; type: string }[];
}
// eslint-disable-next-line @typescript-eslint/no-explicit-any
interface ToolRegistryResponse {
  tools: any[];
  total: number;
  online: number;
  coverage: string;
}
// eslint-disable-next-line @typescript-eslint/no-explicit-any
interface ModelsRegistryResponse {
  tiers: any[];
  tandem_presets: any[];
}
interface HealthTelemetryResponse {
  status: string;
  pack_task_active: boolean;
  vector_wisdom_nodes: number;
  api_keys_active: string[];
}
// eslint-disable-next-line @typescript-eslint/no-explicit-any
interface TodosResponse {
  todos: any[];
}

export interface MoAResult {
  thread_id: string;
  plan: { title: string; steps: string[]; audit_targets: string[] };
  code: {
    language: string;
    code: string;
    files_affected: string[];
    edit_type: string;
    target: string;
  };
  audit: { verdict: string; issues: string[]; confidence: number; review_notes?: string };
  accepted: boolean;
}

// ── Orchestration ─────────────────────────────────────────────────────────────

export async function injectSandboxContext(
  content: string,
  threadId: string,
  contexts: string[] = [],
  modelOverride: string = "auto"
) {
  if (!isTauri()) return null;
  return invoke("orchestrate_plan", {
    payload: {
      user_prompt: content,
      thread_id: threadId,
      contexts,
      model_override: modelOverride,
    },
  });
}

export async function saveApiKeys(payload: {
  openai_key: string;
  anthropic_key: string;
  gemini_key: string;
  groq_key: string;
  deepseek_key: string;
  mistral_key: string;
  openrouter_key?: string;
  kimi_key?: string;
}) {
  if (!isTauri()) return;
  return await invoke("save_api_keys", { keys: payload });
}

export async function getThreads(): Promise<ThreadsResponse> {
  try {
    if (isTauri()) return await invoke<ThreadsResponse>("get_threads");
    return { threads: [] };
  } catch (error) {
    console.error("Failed to fetch threads:", error);
    return { threads: [] };
  }
}

export async function getApiKeyStatus(): Promise<KeyStatusResponse> {
  try {
    if (isTauri()) return await invoke<KeyStatusResponse>("get_api_key_status");
    return {
      openai: false,
      anthropic: false,
      gemini: false,
      groq: false,
      deepseek: false,
      mistral: false,
      openrouter: false,
      kimi: false,
    };
  } catch (error) {
    console.error("Failed to get key status:", error);
    return {
      openai: false,
      anthropic: false,
      gemini: false,
      groq: false,
      deepseek: false,
      mistral: false,
      openrouter: false,
      kimi: false,
    };
  }
}

/** The backend calls it `type: "file" | "folder"`; every consumer reads `isDir`.
 *
 * Those two never met, so `isDir` was `undefined` on every node -- always falsy, so EVERY
 * DIRECTORY rendered with a file icon, clicking one tried to open it as a file, the delete
 * confirmation said "file" instead of "folder (and everything inside it)", and the git-status
 * roll-up for a folder never ran. Eight behaviours, one missing field, and nothing threw.
 *
 * Normalised HERE rather than at the eight call sites: this is the boundary the payload
 * crosses, and a second place that re-derives it is a second place to forget.
 */
function normalizeTree(nodes: unknown): FsTreeNode[] {
  if (!Array.isArray(nodes)) return [];
  return nodes.map((raw) => {
    const n = raw as FsTreeNode;
    const isDir = typeof n.isDir === "boolean" ? n.isDir : n.type === "folder";
    return { ...n, isDir, children: n.children ? normalizeTree(n.children) : undefined };
  });
}

export async function getFileSystemTree(target_path: string = ""): Promise<FsTreeResponse> {
  if (!target_path.trim()) return { tree: [] };
  try {
    if (isTauri()) {
      const res = await invoke<FsTreeResponse>("get_file_system_tree", {
        targetPath: target_path,
      });
      return { ...res, tree: normalizeTree(res?.tree) };
    }
    return { tree: [] };
  } catch (error) {
    console.error("Failed to fetch file system tree:", error);
    return { tree: [] };
  }
}

export async function abortOrchestration() {
  if (!isTauri()) return { status: "noop" };
  try {
    await invoke("orchestrator_shutdown");
    return { status: "shutdown" };
  } catch (error) {
    console.error("Failed to abort:", error);
    throw error;
  }
}

export async function promoteToGarden(
  threadId: string,
  history: string,
  modelOverride: string = "gpt-4o"
) {
  if (!isTauri()) return null;
  return invoke("orchestrate_plan", {
    payload: { user_prompt: history, thread_id: threadId, model_override: modelOverride },
  });
}

export async function unleashThePack(contextPayload: string, topology: Record<string, string>) {
  if (!isTauri()) return null;
  return invoke("orchestrate_plan", {
    payload: { user_prompt: contextPayload, thread_id: `pack-${Date.now()}`, topology },
  });
}

export async function getModelsRegistry(): Promise<ModelsRegistryResponse> {
  try {
    if (isTauri()) return await invoke<ModelsRegistryResponse>("get_models_registry");
    return { tiers: [], tandem_presets: [] };
  } catch (error) {
    console.error("Failed to fetch models registry:", error);
    return { tiers: [], tandem_presets: [] };
  }
}

export async function getToolRegistry(): Promise<ToolRegistryResponse> {
  try {
    if (isTauri()) return await invoke<ToolRegistryResponse>("get_tool_registry");
    return { tools: [], total: 0, online: 0, coverage: "0/0" };
  } catch (error) {
    console.error("Failed to fetch tool registry:", error);
    return { tools: [], total: 0, online: 0, coverage: "0/0" };
  }
}

export async function saveServiceKey(service: string, key: string) {
  if (!isTauri()) return null;
  return invoke("save_service_key", { payload: { service, key } });
}

interface OrchestrateEnvelope {
  ok: boolean;
  data?: { plan?: { steps?: unknown[] }; [k: string]: unknown };
  error?: unknown;
}

export async function getWorkspaceFiles(): Promise<WorkspaceFilesResponse> {
  try {
    if (isTauri()) return await invoke<WorkspaceFilesResponse>("get_workspace_files");
    return { files: [] };
  } catch (error) {
    console.error("Failed to fetch workspace files:", error);
    return { files: [] };
  }
}

export async function getHealthTelemetry(): Promise<HealthTelemetryResponse> {
  try {
    if (isTauri()) return await invoke<HealthTelemetryResponse>("get_health_telemetry");
    return {
      status: "dev-mode",
      pack_task_active: false,
      vector_wisdom_nodes: -1,
      api_keys_active: [],
    };
  } catch (error) {
    console.error("Failed to fetch backend health telemetry:", error);
    return {
      status: "offline",
      pack_task_active: false,
      vector_wisdom_nodes: -1,
      api_keys_active: [],
    };
  }
}

export async function fetchTodos(threadId: string): Promise<TodosResponse> {
  try {
    if (isTauri()) return await invoke<TodosResponse>("fetch_todos", { threadId });
    return { todos: [] };
  } catch (error) {
    console.error("Failed to fetch todos:", error);
    return { todos: [] };
  }
}

export async function addCustomRegistryModel(payload: Record<string, unknown>) {
  if (!isTauri()) return null;
  return invoke("add_custom_registry_model", { payload });
}

export async function readFileContent(filePath: string) {
  try {
    if (isTauri())
      return await invoke<{ content: string }>("read_file_content", { targetPath: filePath });
    return null;
  } catch (error) {
    console.error("Failed to read file:", error);
    throw error;
  }
}

// ── Native-First Orchestration (Tauri-only) ───────────────────────────────────

export async function nativeOrchestratePlan(
  userPrompt: string,
  threadId: string,
  modelOverride: string = "auto"
): Promise<MoAResult> {
  if (!isTauri()) throw new Error("nativeOrchestratePlan requires the Tauri runtime.");
  const result = await invoke<{ ok: boolean; data?: MoAResult; error?: unknown }>(
    "orchestrate_plan",
    { payload: { user_prompt: userPrompt, thread_id: threadId, model_override: modelOverride } }
  );
  if (!result.ok) throw result.error;
  return result.data!;
}

export async function nativeOrchestrateCodegen(
  plan: { title: string; steps: string[]; audit_targets: string[] },
  threadId: string,
  modelOverride: string = "auto"
): Promise<MoAResult> {
  if (!isTauri()) throw new Error("nativeOrchestrateCodegen requires the Tauri runtime.");
  const result = await invoke<{ ok: boolean; data?: MoAResult; error?: unknown }>(
    "orchestrate_codegen",
    { payload: { plan, thread_id: threadId, model_override: modelOverride } }
  );
  if (!result.ok) throw result.error;
  return result.data!;
}

export async function nativeOrchestrateAudit(
  code: { language: string; code: string; files_affected: string[] },
  threadId: string,
  modelOverride: string = "auto"
): Promise<MoAResult> {
  if (!isTauri()) throw new Error("nativeOrchestrateAudit requires the Tauri runtime.");
  const result = await invoke<{ ok: boolean; data?: MoAResult; error?: unknown }>(
    "orchestrate_audit",
    { payload: { code, thread_id: threadId, model_override: modelOverride } }
  );
  if (!result.ok) throw result.error;
  return result.data!;
}

// ── Vanguard Vault ────────────────────────────────────────────────────────────

export async function toggleVanguardTelemetry(enabled: boolean): Promise<boolean> {
  if (!isTauri()) {
    console.warn("[VANGUARD] Tauri runtime not present — toggle is a no-op in browser mode.");
    return enabled;
  }
  return invoke<boolean>("toggle_vanguard_telemetry", { enabled });
}

export async function getOllamaModels(
  baseUrl?: string
): Promise<
  { id: string; name: string; size_gb: number; param_size: string; is_determinex: boolean }[]
> {
  try {
    const models = await invokeSafe<
      { id: string; name: string; size_gb: number; param_size: string; is_determinex: boolean }[]
    >("get_ollama_models", {
      // Tauri's command macro defaults to ArgumentCase::Camel and looks up each
      // param as param_name.to_lower_camel_case(), so a snake_case JS key
      // matches NOTHING (verified in tauri-macros-2.5.5 command/wrapper.rs).
      // This sent `base_url` for a `base_url: Option<String>` param, so it
      // silently arrived as None rather than erroring -- a custom Ollama base
      // URL was ignored entirely. Caught by argContract.test.ts.
      baseUrl,
    });
    return Array.isArray(models) ? models : [];
  } catch {
    return [];
  }
}

export async function checkOllamaStatus(baseUrl?: string) {
  try {
    const status = await invokeSafe<boolean | { ok: boolean; error?: string }>(
      "check_ollama_status",
      { baseUrl }
    );
    if (typeof status === "boolean") return { ok: status };
    return status ?? { ok: false, error: "Tauri runtime not available" };
  } catch (error) {
    return { ok: false, error: String(error) };
  }
}

export interface DockerStatus {
  running: boolean;
  version: string;
  message: string;
}

export async function checkDockerStatus(): Promise<DockerStatus> {
  try {
    const status = await invokeSafe<DockerStatus>("check_docker_status", {});
    return status ?? { running: false, version: "", message: "Native runtime not available." };
  } catch (error) {
    return { running: false, version: "", message: String(error) };
  }
}

export async function getOllamaBaseUrl(): Promise<string | null> {
  try {
    return await invokeSafe<string | null>("get_ollama_base_url", {});
  } catch {
    return null;
  }
}

export async function saveOllamaBaseUrl(url: string): Promise<void> {
  await invokeSafe("save_ollama_base_url", { url });
}

// ── Hive Mind DAG Orchestrator ────────────────────────────────────────────────

/** Write the MD spec to sessions/specs/spec_{ts}.md on disk. Returns the absolute path. */
export async function writeSpecFile(content: string): Promise<string> {
  return invoke<string>("write_spec_file", { content });
}

/**
 * Spawn the build loop. Returns { session_id, pid }. Pre-checks steps exist.
 * `amplify`/`amplifyK` opt into the Correctness Amplifier (best-of-K verified
 * search against the same Compiler Oracle per step) -- off unless passed.
 */
export async function runHiveSession(sessionId: string, amplify = false, amplifyK?: number) {
  const result = await invoke<{
    ok: boolean;
    data?: { session_id: string; pid: number };
    error?: string;
  }>("run_session", {
    payload: { session_id: sessionId, amplify, amplify_k: amplifyK },
  });
  if (!result.ok) throw new Error(result.error || "run_session failed");
  return result.data!;
}

export interface HardwareProbe {
  total_vram_mb: number | null;
  vram_budget_mb: number;
  reserved_vram_mb: number;
  hardware_source: string;
  hardware_fallback: boolean;
  recommended_tier: string;
}

export async function probeHardware(): Promise<HardwareProbe | null> {
  return invokeSafe<HardwareProbe>("probe_hardware");
}

/**
 * Hardware-adaptive candidate count for the Correctness Amplifier: more VRAM
 * headroom means more parallel candidates can be sampled per build step
 * before the local model queue becomes the bottleneck. Mirrors hardware.rs's
 * calculate_tier() thresholds. Falls back to 1 (no parallelism) when the
 * budget is unknown or below the minimum tier.
 */
export function recommendedAmplifyK(vramBudgetMb: number | null | undefined): number {
  if (!vramBudgetMb || vramBudgetMb < 4000) return 1;
  if (vramBudgetMb < 8000) return 2;
  if (vramBudgetMb < 12000) return 4;
  return 6;
}

/** Read manifest and return full session status + per-step breakdown. */
export async function getHiveSessionStatus(sessionId: string) {
  const result = await invoke<{ ok: boolean; data?: Record<string, unknown>; error?: string }>(
    "get_session_status",
    { payload: { session_id: sessionId } }
  );
  if (!result.ok) throw new Error(result.error || "get_session_status failed");
  return result.data!;
}

/** Read a file from a hive session's workspace. Returns content string or null. */
export async function readHiveWorkspaceFile(
  sessionId: string,
  relativePath: string
): Promise<string | null> {
  try {
    const result = await invoke<{ ok: boolean; content?: string; error?: string }>(
      "read_hive_workspace_file",
      { payload: { session_id: sessionId, relative_path: relativePath } }
    );
    return result.ok ? (result.content ?? null) : null;
  } catch {
    return null;
  }
}

/** Kill a running session's generate-dag or run-session subprocess. */
export async function killHiveSession(sessionId: string) {
  const result = await invoke<{ ok: boolean; error?: string }>("kill_session", {
    payload: { session_id: sessionId },
  });
  if (!result.ok) throw new Error(result.error || "kill_session failed");
  return result;
}

/** Start tailing the session log. Frontend listens for hive-log-{session_id} events. */
export async function streamHiveSessionLog(sessionId: string) {
  const result = await invoke<{
    ok: boolean;
    data?: { streaming: boolean; event: string };
    error?: string;
  }>("stream_session_log", { payload: { session_id: sessionId } });
  if (!result.ok) throw new Error(result.error || "stream_session_log failed");
  return result.data!;
}

export interface HiveSessionSummary {
  session_id: string;
  lang: string;
  project_name: string;
  status: "complete" | "failed" | "in_progress" | "pending";
  step_count: number;
  complete_count: number;
  failed_count: number;
  created_at: string;
  updated_at: string;
  project_root: string;
}

/** List all Hive build sessions on disk, sorted newest-first. */
export async function listHiveSessions(): Promise<HiveSessionSummary[]> {
  const result = await invoke<{ ok: boolean; data?: HiveSessionSummary[]; error?: string }>(
    "list_hive_sessions"
  );
  if (!result.ok) throw new Error(result.error || "list_hive_sessions failed");
  return result.data ?? [];
}

export interface RoleAssignments {
  oracle: string;
  architect: string;
  builder: string;
  monitor: string;
}

const DEFAULT_ROLES: RoleAssignments = {
  oracle: "local/fast",
  architect: "local/fast",
  builder: "determinex/engineer",
  monitor: "determinex/observer",
};

/** Read current role→model assignments from litellm_config.yaml. */
export async function getRoleAssignments(): Promise<RoleAssignments> {
  const result = isTauri()
    ? await invoke<{ ok: boolean; data?: RoleAssignments; error?: string }>("get_role_assignments")
    : await invokeSafe<{ ok: boolean; data?: RoleAssignments; error?: string }>(
        "get_role_assignments"
      );
  if (!result) return DEFAULT_ROLES;
  if (!result.ok) {
    if (!isTauri()) return DEFAULT_ROLES;
    throw new Error(result.error || "get_role_assignments failed");
  }
  return result.data ?? DEFAULT_ROLES;
}

/** Write role→model assignments back to litellm_config.yaml. */
export async function setRoleAssignments(assignments: RoleAssignments): Promise<void> {
  if (!isTauri()) return;
  const result = await invoke<{ ok: boolean; error?: string }>("set_role_assignments", {
    assignments,
  });
  if (!result.ok) throw new Error(result.error || "set_role_assignments failed");
}

export interface TerminalCommandResult {
  command: string;
  cwd: string;
  stdout: string;
  stderr: string;
  exit_code: number | null;
  timed_out: boolean;
}

/** Create a new empty file or directory. Throws if it already exists or Tauri is absent. */
export async function createPath(path: string, isDir: boolean): Promise<void> {
  if (!isTauri()) throw new Error("createPath requires the Tauri runtime.");
  await invoke("create_path", { path, isDir });
}

/** Rename/move a file or directory. Throws on failure (e.g. target already exists). */
export async function renamePath(from: string, to: string): Promise<void> {
  if (!isTauri()) throw new Error("renamePath requires the Tauri runtime.");
  await invoke("rename_path", { from, to });
}

/** Delete a file, or a directory and everything inside it. Irreversible. */
export async function deletePath(path: string): Promise<void> {
  if (!isTauri()) throw new Error("deletePath requires the Tauri runtime.");
  await invoke("delete_path", { path });
}

/** Reveal a path (file or folder) in the OS file manager, highlighted. */
export async function revealInExplorer(path: string): Promise<void> {
  if (!isTauri()) throw new Error("revealInExplorer requires the Tauri runtime.");
  await invoke("reveal_in_explorer", { relativePath: path });
}

// ── Repo Clinic real oracle diagnosis ─────────────────────────────────────────
// These call the same `repair_diagnose`/`get_governance_status` Tauri commands
// registered in ide_repair_bridge.rs, via the generic invokeSafe wrapper rather
// than the locked ide-repair-api.ts closed command set (FRONTEND_REPAIR_PANEL_
// SHELL_LOCK_001 pins that set to 11 specific advisory/mutation-gated commands;
// these two are read-only, no-model, no-mutation and don't belong in that gate).

export interface RepairExplanation {
  test_id: string;
  responsible: "CODE" | "TEST" | "ENVIRONMENT";
  why: string;
  expected: string | null;
  actual: string | null;
  delta: string;
  proof: string;
  confidence: number;
}

export interface RepairDiagnosis {
  language: string;
  oracle: string;
  healthy: boolean | null;
  n_failures: number;
  blame: Record<string, number>;
  moves: Record<string, number>;
  proven_slop: number;
  notes: string[];
  explanations: RepairExplanation[];
  source_mutation: boolean;
  note?: string;
}

/** Runs the real compiler/test oracle + adjudicator + test-validator against a workspace. No model call, no source mutation. */
export async function repairDiagnose(workspace: string): Promise<RepairDiagnosis | null> {
  const res = await invokeSafe<{ payload?: RepairDiagnosis }>("repair_diagnose", { workspace });
  return res?.payload ?? null;
}

export interface GovernanceStatus {
  authority_anchors?: Record<string, unknown>;
  all_closed?: boolean;
  violations?: string[];
  [key: string]: unknown;
}

/** Reads the deterministic no-overclaim governance anchors (never a live model call). */
export async function getGovernanceStatus(): Promise<GovernanceStatus | null> {
  const res = await invokeSafe<{ payload?: GovernanceStatus }>("get_governance_status", {});
  return res?.payload ?? null;
}

export interface FileSearchHit {
  file: string;
  line_number: number;
  line: string;
}
export interface FileSearchResponse {
  hits: FileSearchHit[];
  truncated: boolean;
}

/** Literal-substring "Find in Files" search, gitignore-aware, secrets-blocklisted. */
export async function findInFiles(
  root: string,
  query: string,
  caseSensitive = false
): Promise<FileSearchResponse> {
  try {
    const result = await invokeSafe<FileSearchResponse>("find_in_files", {
      root,
      query,
      caseSensitive,
    });
    return result ?? { hits: [], truncated: false };
  } catch (error) {
    console.error("Failed to search files:", error);
    return { hits: [], truncated: false };
  }
}

export async function runTerminalCommand(
  command: string,
  cwd?: string
): Promise<TerminalCommandResult | null> {
  return invokeSafe<TerminalCommandResult>("run_terminal_command", { command, cwd });
}

/**
 * The write path: for commands that return nothing, `invokeSafe` is unusable.
 *
 * A Tauri command declared `Result<(), String>` resolves to `null` on SUCCESS.
 * `invokeSafe` returns `null` on FAILURE. For those 26 commands the two
 * outcomes are the same value, so a caller cannot tell a failed commit from a
 * successful one, and any `catch` around an `invokeSafe` write is unreachable
 * code. That produced an editor save clearing its dirty flag on a write that
 * never landed, a privacy toggle reporting enforcement the backend had refused,
 * and a Review-queue apply that looked merely inert when it had been rejected.
 *
 * This throws on both counts — no runtime, or a rejected command — so the
 * failure reaches the caller. **Callers must surface it to the user**; that half
 * cannot be enforced mechanically, but using `invokeSafe` here now can be, and
 * is: `determinex/no-invokesafe-on-void-command` (see
 * `frontend/eslint-rules/voidCommands.mjs`).
 */
export async function invokeWrite(cmd: string, args?: Record<string, unknown>): Promise<void> {
  if (!isTauri()) throw new Error(`${cmd} needs the desktop runtime.`);
  await invoke(cmd, args);
}

/**
 * Escape hatch for invoke calls that don't yet have a typed wrapper.
 * Returns null in browser/mock environments (no Tauri runtime present).
 * Components should prefer this over importing invoke directly so the
 * isTauri guard is consistently applied.
 *
 * READS ONLY. For anything that mutates state, use `invokeWrite` above.
 */
export async function invokeSafe<T>(
  cmd: string,
  args?: Record<string, unknown>
): Promise<T | null> {
  if (!isTauri()) {
    try {
      const res = await fetch(`http://127.0.0.1:7479/api/invoke/${cmd}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(args || {}),
      });
      if (!res.ok) {
        console.warn(`[HTTP Bridge] ${cmd} failed with status ${res.status}`);
        return null;
      }
      const data = await res.json();
      return data as T;
    } catch (e) {
      console.warn(`[HTTP Bridge] Failed to fetch ${cmd}`, e);
      return null;
    }
  }
  try {
    return await invoke<T>(cmd, args);
  } catch (e) {
    // This function's whole contract (documented at the top of this file) is
    // "returns null on error, never throws" -- but this branch used to call
    // invoke() unguarded, so under real Tauri (unlike the browser/SSR
    // fallback above) a rejected command propagated as an unhandled
    // rejection to every caller instead. Surfaced live via Agent Chat Room:
    // sending a message to a session that predated an app restart threw
    // "unknown chat session", which reached the user only as a raw Next.js
    // dev-overlay crash with the typed message silently gone -- in a
    // production build there would have been no visible failure at all.
    console.warn(`[invokeSafe] ${cmd} failed`, e);
    return null;
  }
}

export interface ProgramBenchSnapshot {
  run_id: string;
  generated_at: string;
  n_completed_tasks: number;
  progress?: { expected_total?: number; pct_done?: number; complete?: boolean };
  rolling_avg_score: number;
  total_passed: number;
  total_tests: number;
  pct_tests_passing: number;
  perfect_scores: number;
  zero_scores: number;
  top_families: { family: string; failures: number; tools_affected: number }[];
  recommended_patch?: {
    status?: string;
    family?: string;
    title?: string;
    confidence?: string | number;
    estimated_lift_pp?: number;
    validation?: string[];
  };
  // Real per-tool drilldown: archived ProgramBench locks (board mirror of
  // corpus/programbench/locked/). Each row is a strict lock at passed==runnable.
  locked_tools?: {
    name: string;
    score?: number;
    passed?: number;
    runnable_total?: number;
    evidence_path?: string;
  }[];
  locked_count?: number;
}

export async function getProgramBenchSnapshot(
  runId = "mass_run_v2_base",
  expectedTotal = 115
): Promise<ProgramBenchSnapshot | null> {
  return invokeSafe<ProgramBenchSnapshot>("get_programbench_snapshot", {
    runId,
    expectedTotal,
    advise: true,
  });
}

// ── ConceptLab / HiveBuildLoop typed wrappers ─────────────────────────────────

// Shared attachment type used by discover_idea and converse_idea
export interface IdeaAttachment {
  name: string;
  mime_type: string;
  data: string;
}

// discover_idea: scan workspace paths relevant to an idea.
// Paths are typed as unknown[] here since the full PathInfo shape is defined in the component
// that consumes it — callers should cast to their local type.
type DiscoverIdeaResult = {
  ok: boolean;
  data?: { paths: unknown[]; message: string };
  error?: string;
};
export async function discoverIdea(
  idea: string,
  attachments: IdeaAttachment[],
  modelOverride: string = "auto"
): Promise<DiscoverIdeaResult> {
  return (
    (await invokeSafe<DiscoverIdeaResult>("discover_idea", {
      payload: { idea, attachments, model_override: modelOverride },
    })) ?? {
      ok: false,
      error: "Tauri runtime not available",
    }
  );
}

// converse_idea: multi-turn ideation conversation
type ConverseIdeaResult = {
  ok: boolean;
  data?: {
    response: string;
    ready_to_spec: boolean;
    spec_summary: string | null;
    /** The directions that still fit what the user has said, re-computed on every reply.
     *  The grid used to be built once at discovery and never touched, so answering
     *  "terminal only, no browser" left "Web + Mobile App, 3-6 weeks, high" on screen --
     *  the cards asked for a decision and then ignored it. */
    paths?: PathInfo[];
    /** What was removed and WHY, so a card never just vanishes. An unexplained
     *  disappearance reads as a bug, not as the system listening. */
    ruled_out?: { name: string; why: string }[];
  };
  error?: string;
};
export async function converseIdea(payload: {
  idea: string;
  messages: { role: string; text: string }[];
  user_message: string;
  attachments: IdeaAttachment[];
  model_override?: string;
}): Promise<ConverseIdeaResult> {
  return (
    (await invokeSafe<ConverseIdeaResult>("converse_idea", { payload })) ?? {
      ok: false,
      error: "Tauri runtime not available",
    }
  );
}

// assess_idea_context: do we know enough to build this yet?
//
// Answered by whether a SOUND ORACLE can be synthesized from the answers so far, using the
// same synthesizer that later builds it -- so the interview's notion of "enough" cannot
// drift from the verifier's. This is what lets the Concept Lab keep asking past the old
// fixed 4-question bank instead of writing a spec from whatever it happened to have.
export type IdeaContextAssessment = {
  sufficient: boolean;
  satisfied: string[];
  missing: string[];
  questions: string[];
  rationale: string;
  stalled: boolean;
  oracle_would_be_vacuous: boolean;
};

export async function assessIdeaContext(payload: {
  idea: string;
  answers: string[];
  asked: string[];
  previous_satisfied?: string[];
}): Promise<{ ok: boolean; data?: IdeaContextAssessment; error?: string }> {
  return (
    (await invokeSafe<{ ok: boolean; data?: IdeaContextAssessment; error?: string }>(
      "assess_idea_context",
      { payload }
    )) ?? { ok: false, error: "Tauri runtime not available" }
  );
}

// generate_spec: build a Markdown spec from the ideation context
type GenerateSpecResult = { ok: boolean; data?: { spec: string }; error?: string };
export async function generateSpec(
  contextPrompt: string,
  modelOverride: string = "auto"
): Promise<GenerateSpecResult> {
  return (
    (await invokeSafe<GenerateSpecResult>("generate_spec", {
      payload: { idea: contextPrompt, model_override: modelOverride },
    })) ?? { ok: false, error: "Tauri runtime not available" }
  );
}

// refine_spec: apply a user change-request to an existing spec
type RefineSpecResult = { ok: boolean; data?: { response: string; spec: string }; error?: string };
export async function refineSpec(
  spec: string,
  request: string,
  modelOverride: string = "auto"
): Promise<RefineSpecResult> {
  return (
    (await invokeSafe<RefineSpecResult>("refine_spec", {
      payload: { spec, request, model_override: modelOverride },
    })) ?? {
      ok: false,
      error: "Tauri runtime not available",
    }
  );
}

// start_session: create and launch a Hive DAG session from a spec file
type StartSessionResult = { ok: boolean; data?: { session_id: string }; error?: string };
export async function startSession(
  specPath: string,
  lang: string,
  budget: number,
  modelOverride: string = "auto"
): Promise<StartSessionResult> {
  return (
    (await invokeSafe<StartSessionResult>("start_session", {
      payload: { spec_path: specPath, lang, budget, model_override: modelOverride },
    })) ?? { ok: false, error: "Tauri runtime not available" }
  );
}

// explore_workspace: list files in a Hive session workspace
type ExploreWorkspaceResult = {
  ok: boolean;
  data?: { file_count?: number; files?: { path: string; size_bytes: number }[] };
  error?: string;
};
export async function exploreWorkspace(workspacePath: string): Promise<ExploreWorkspaceResult> {
  return (
    (await invokeSafe<ExploreWorkspaceResult>("explore_workspace", {
      payload: { workspace_path: workspacePath },
    })) ?? { ok: false, error: "Tauri runtime not available" }
  );
}

// diagnose_workspace: explain a compiler error in workspace context
type DiagnoseWorkspaceResult = {
  ok: boolean;
  data?: { raw?: string; explanation?: string; relevant_files?: string[]; traceback?: string };
  error?: string;
};
export async function diagnoseWorkspace(
  workspacePath: string,
  issue: string
): Promise<DiagnoseWorkspaceResult> {
  return (
    (await invokeSafe<DiagnoseWorkspaceResult>("diagnose_workspace", {
      payload: { workspace_path: workspacePath, issue },
    })) ?? { ok: false, error: "Tauri runtime not available" }
  );
}

/**
 * Opens an internal route (/ide-repair, /proof-center) in a real second window.
 * `window.open(url, "_blank")` -- what every call site used before -- is a
 * plain web-popup API; Tauri's WebView2 host has no popup permission for it
 * by default, so it silently did nothing (found live 2026-07-19: clicking
 * "Repair" produced zero visible effect, no new window, no error, nothing).
 * Falls back to real window.open in browser-mode dev/testing.
 */
export async function openInternalWindow(
  label: string,
  path: string,
  title: string
): Promise<void> {
  if (!isTauri()) {
    window.open(path, "_blank");
    return;
  }
  const { WebviewWindow } = await import("@tauri-apps/api/webviewWindow");
  const existing = await WebviewWindow.getByLabel(label);
  if (existing) {
    await existing.setFocus();
    return;
  }
  const webview = new WebviewWindow(label, {
    url: path,
    title,
    width: 1200,
    height: 860,
    minWidth: 800,
    minHeight: 500,
  });
  // Requires core:webview:allow-create-webview-window -- without it this call
  // fails silently client-side unless a listener is attached. Surface it
  // instead of repeating the exact "nothing happens, no error" bug this
  // replaced.
  webview.once("tauri://error", (e) => {
    console.error(`Failed to open window "${label}":`, e);
  });
}

/**
 * Real native OS folder picker (Tauri's dialog plugin). Every "type a path by
 * hand" input in the app (ProjectHub's Add Project Cover, onboarding, etc.)
 * used to have no alternative -- this was a real, repeatedly-flagged gap, not
 * a cosmetic one. Returns null in browser mode or if the user cancels.
 */
export async function pickFolder(title = "Choose a folder"): Promise<string | null> {
  if (!isTauri()) return null;
  try {
    const { open } = await import("@tauri-apps/plugin-dialog");
    const selected = await open({ directory: true, multiple: false, title });
    return typeof selected === "string" ? selected : null;
  } catch (error) {
    console.error("Failed to open folder picker:", error);
    return null;
  }
}
