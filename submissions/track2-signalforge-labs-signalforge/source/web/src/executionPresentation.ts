import type {
  ExecutionChecklistItem,
  ExecutionPhase,
  ExecutionPlan,
  ExecutionStatus,
  ExecutionStep
} from "./types";

export const executionPresentationSchema = "signalforge/execution-presentation/v1" as const;

export type ProofReferenceKind =
  | "evidence"
  | "calculation"
  | "review"
  | "release"
  | "contract"
  | "authorization"
  | "context"
  | "lineage";

export type ProofReference = {
  id: string;
  kind: ProofReferenceKind;
  authority: string;
};

export type ChecklistPresentation = {
  id: string;
  label: string;
  status: ExecutionStatus;
  statusLabel: string;
  authority: string;
  authorityLabel: string;
  required: boolean;
  requirementLabel: "Required" | "Supporting";
  safeDetail: string;
  completedAt?: string;
  references: ProofReference[];
  attention: boolean;
};

export type StepPresentation = {
  id: string;
  parentID?: string;
  phaseID: string;
  kind: string;
  label: string;
  objective: string;
  summary: string;
  status: ExecutionStatus;
  statusLabel: string;
  roleID?: string;
  authorityLabel: string;
  wave?: number;
  dependencies: string[];
  mandatory: boolean;
  requirementLabel: "Required" | "Supporting";
  route?: string;
  routeLabel: string;
  routeReasonCode?: string;
  capabilities: string[];
  evidenceRequirements: string[];
  attempt: number;
  maxAttempts: number;
  durationMS: number;
  startedAt?: string;
  completedAt?: string;
  failureCode?: string;
  degradationCode?: string;
  references: ProofReference[];
  checklist: ChecklistPresentation[];
  attention: boolean;
};

export type WavePresentation = {
  id: string;
  wave?: number;
  label: string;
  parallel: boolean;
  steps: StepPresentation[];
};

export type PhasePresentation = {
  id: string;
  order: number;
  label: string;
  objective: string;
  summary: string;
  status: ExecutionStatus;
  statusLabel: string;
  mandatory: boolean;
  requirementLabel: "Required" | "Supporting";
  terminalSteps: number;
  totalSteps: number;
  waves: WavePresentation[];
  steps: StepPresentation[];
  attention: boolean;
};

export type ExecutionPresentation = {
  schemaVersion: typeof executionPresentationSchema;
  sourceSchemaVersion: ExecutionPlan["schema_version"];
  runID: string;
  requestID: string;
  planID?: string;
  projectionSHA256: string;
  presentationSHA256: string;
  sequence: number;
  status: ExecutionStatus;
  statusLabel: string;
  percentage: number;
  headline: string;
  terminalSteps: number;
  totalSteps: number;
  maxParallelSpecialists: number;
  currentWave?: number;
  routes: string[];
  limitations: string[];
  createdAt: string;
  startedAt?: string;
  completedAt?: string;
  phases: PhasePresentation[];
  attention: boolean;
};

const terminalStatuses = new Set<ExecutionStatus>([
  "passed", "failed", "degraded", "skipped", "cancelled", "withheld", "unavailable"
]);

const attentionStatuses = new Set<ExecutionStatus>([
  "failed", "degraded", "repairing", "cancelled", "withheld", "unavailable"
]);

const phaseLabels: Record<string, string> = {
  interpretation: "Interpretation",
  planning: "Planning",
  context: "Evidence and specialists",
  tools: "Deterministic tools",
  review: "Independent review",
  synthesis: "Synthesis",
  memory: "Optional memory",
  release: "Release gate"
};

const statusLabels: Record<ExecutionStatus, string> = {
  pending: "Waiting",
  ready: "Ready",
  running: "In progress",
  passed: "Verified",
  failed: "Stopped safely",
  degraded: "Bounded subset",
  repairing: "Repairing",
  skipped: "Not required",
  cancelled: "Cancelled",
  withheld: "Withheld",
  unavailable: "Unavailable"
};

const routeLabels: Record<string, string> = {
  "local-rocm": "Local Radeon inference",
  local_rocm: "Local Radeon inference",
  "radeon-vllm": "Radeon Cloud specialist",
  radeon_api: "Radeon Cloud specialist",
  local_deterministic: "Local deterministic engine",
  local_rocm_to_radeon_api: "Local primary, Radeon fallback",
  radeon_api_to_local_rocm: "Radeon primary, local fallback",
  bounded_repair: "Bounded contract repair"
};

const authorityLabels: Record<string, string> = {
  contract: "Contract authority",
  planner: "Planning authority",
  retrieval: "Evidence authority",
  specialist: "Specialist contract",
  engine: "Deterministic engine",
  capability: "Capability authorization",
  reviewer: "Independent reviewer",
  release_gate: "Release authority",
  runtime: "Runtime authority"
};

export function buildExecutionPresentation(plan: ExecutionPlan): ExecutionPresentation {
  const phases = [...plan.phases]
    .sort((left, right) => left.order - right.order)
    .map((phase) => presentPhase(phase, plan.steps));
  const active = phases
    .flatMap((phase) => phase.steps)
    .find((step) => step.status === "running" || step.status === "repairing");
  const percentage = Math.round(plan.progress_ratio * 100);
  const limitations = unique([
    ...(plan.degradation_summary ?? []).map(humanize),
    ...phases
      .filter((phase) => phase.attention)
      .map((phase) => `${phase.label}: ${phase.statusLabel}`)
  ]);

  const presentation = {
    schemaVersion: executionPresentationSchema,
    sourceSchemaVersion: plan.schema_version,
    runID: plan.run_id,
    requestID: plan.request_id,
    planID: plan.plan_id,
    projectionSHA256: plan.projection_sha256,
    sequence: plan.last_sequence,
    status: plan.status,
    statusLabel: statusLabel(plan.status),
    percentage,
    headline: active?.label ?? (terminalStatuses.has(plan.status)
      ? statusLabel(plan.status)
      : "Preparing the governed plan"),
    terminalSteps: plan.terminal_steps,
    totalSteps: plan.total_steps,
    maxParallelSpecialists: plan.max_parallel_specialists || 0,
    currentWave: plan.current_wave,
    routes: unique((plan.route_summary ?? []).map(routeLabel)),
    limitations,
    createdAt: plan.created_at,
    startedAt: plan.started_at,
    completedAt: plan.completed_at,
    phases,
    attention: attentionStatuses.has(plan.status) || phases.some((phase) => phase.attention)
  };
  return {
    ...presentation,
    presentationSHA256: sha256Hex(JSON.stringify(presentation))
  };
}

function presentPhase(phase: ExecutionPhase, allSteps: ExecutionStep[]): PhasePresentation {
  const steps = allSteps
    .filter((step) => step.parent_phase_id === phase.phase_id)
    .map(presentStep);

  return {
    id: phase.phase_id,
    order: phase.order,
    label: phaseLabels[phase.phase_id] ?? phase.safe_label,
    objective: phase.safe_objective,
    summary: phase.safe_summary,
    status: phase.status,
    statusLabel: statusLabel(phase.status),
    mandatory: phase.mandatory,
    requirementLabel: phase.mandatory ? "Required" : "Supporting",
    terminalSteps: steps.filter((step) => terminalStatuses.has(step.status)).length,
    totalSteps: steps.length,
    waves: groupWaves(steps),
    steps,
    attention: attentionStatuses.has(phase.status) || steps.some((step) => step.attention)
  };
}

function presentStep(step: ExecutionStep): StepPresentation {
  const checklist = step.checklist.map(presentChecklist);
  const directReferences = (step.reference_ids ?? []).map((id) => ({
    id,
    kind: referenceKind(step.kind, step.role_id ?? "runtime"),
    authority: step.role_id ?? "runtime"
  }));
  const authority = step.role_id ?? "runtime";

  return {
    id: step.step_id,
    parentID: step.parent_step_id,
    phaseID: step.parent_phase_id,
    kind: step.kind,
    label: step.safe_label,
    objective: step.safe_objective,
    summary: step.safe_summary,
    status: step.status,
    statusLabel: statusLabel(step.status),
    roleID: step.role_id,
    authorityLabel: authorityLabel(authority),
    wave: step.wave,
    dependencies: step.depends_on ?? [],
    mandatory: step.mandatory,
    requirementLabel: step.mandatory ? "Required" : "Supporting",
    route: step.route,
    routeLabel: routeLabel(step.route ?? step.route_reason_code ?? "governed_runtime"),
    routeReasonCode: step.route_reason_code,
    capabilities: step.authorized_capability_ids ?? [],
    evidenceRequirements: step.evidence_requirement_classes ?? [],
    attempt: step.attempt,
    maxAttempts: step.max_attempts,
    durationMS: step.duration_ms ?? 0,
    startedAt: step.started_at,
    completedAt: step.completed_at,
    failureCode: step.failure_code,
    degradationCode: step.degradation_code,
    references: uniqueReferences([
      ...directReferences,
      ...checklist.flatMap((item) => item.references)
    ]),
    checklist,
    attention: attentionStatuses.has(step.status) || checklist.some((item) => item.attention)
  };
}

function presentChecklist(item: ExecutionChecklistItem): ChecklistPresentation {
  const safeDetail = item.safe_detail ??
    `${authorityLabel(item.authority)} check is ${statusLabel(item.status).toLowerCase()}.`;
  return {
    id: item.check_id,
    label: item.label,
    status: item.status,
    statusLabel: statusLabel(item.status),
    authority: item.authority,
    authorityLabel: authorityLabel(item.authority),
    required: item.required,
    requirementLabel: item.required ? "Required" : "Supporting",
    safeDetail,
    completedAt: item.completed_at,
    references: (item.reference_ids ?? []).map((id) => ({
      id,
      kind: checklistReferenceKind(item, id),
      authority: item.authority
    })),
    attention: attentionStatuses.has(item.status)
  };
}

function groupWaves(steps: StepPresentation[]): WavePresentation[] {
  const grouped = new Map<string, StepPresentation[]>();
  for (const step of steps) {
    const key = step.wave && step.wave > 0 ? `wave-${step.wave}` : "governed-work";
    grouped.set(key, [...(grouped.get(key) ?? []), step]);
  }
  return [...grouped.entries()].map(([id, groupedSteps]) => {
    const wave = groupedSteps[0]?.wave && groupedSteps[0].wave > 0
      ? groupedSteps[0].wave
      : undefined;
    return {
      id,
      wave,
      label: wave ? `Parallel wave ${wave}` : "Governed work",
      parallel: Boolean(wave && groupedSteps.length > 1),
      steps: groupedSteps
    };
  });
}

function checklistReferenceKind(item: ExecutionChecklistItem, id: string): ProofReferenceKind {
  if (item.authority === "engine") {
    return item.status === "passed" && id.startsWith("receipt-")
      ? "calculation"
      : "lineage";
  }
  return referenceKind(item.authority, item.authority);
}

function referenceKind(value: string, authority: string): ProofReferenceKind {
  if (authority === "capability") return "authorization";
  if (authority === "engine" || value === "tool") return "calculation";
  if (authority === "retrieval") return "evidence";
  if (authority === "reviewer" || value === "review") return "review";
  if (authority === "release_gate" || value === "release") return "release";
  if (authority === "contract" || authority === "planner") return "contract";
  if (authority === "specialist" || value === "context") return "context";
  return "lineage";
}

export function statusLabel(status: ExecutionStatus): string {
  return statusLabels[status];
}

export function routeLabel(route: string): string {
  return routeLabels[route] ?? humanize(route);
}

export function authorityLabel(authority: string): string {
  return authorityLabels[authority] ?? humanize(authority);
}

export function humanize(value: string): string {
  return value
    .replace(/\/v\d+$/, "")
    .replaceAll(/[._/-]/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function unique(values: string[]): string[] {
  return [...new Set(values.filter(Boolean))];
}

function uniqueReferences(values: ProofReference[]): ProofReference[] {
  const seen = new Set<string>();
  return values.filter((value) => {
    const key = `${value.kind}:${value.id}`;
    if (!value.id || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

export function sha256Hex(value: string): string {
  const bytes = new TextEncoder().encode(value);
  const bitLength = bytes.length * 8;
  const paddedLength = Math.ceil((bytes.length + 1 + 8) / 64) * 64;
  const payload = new Uint8Array(paddedLength);
  payload.set(bytes);
  payload[bytes.length] = 0x80;
  const view = new DataView(payload.buffer);
  view.setUint32(paddedLength - 8, Math.floor(bitLength / 0x100000000), false);
  view.setUint32(paddedLength - 4, bitLength >>> 0, false);

  const state = new Uint32Array([
    0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
    0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19
  ]);
  const constants = new Uint32Array([
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2
  ]);
  const words = new Uint32Array(64);

  for (let offset = 0; offset < payload.length; offset += 64) {
    for (let index = 0; index < 16; index += 1) {
      words[index] = view.getUint32(offset + index * 4, false);
    }
    for (let index = 16; index < 64; index += 1) {
      const previous15 = words[index - 15];
      const previous2 = words[index - 2];
      const sigma0 = rotateRight(previous15, 7) ^ rotateRight(previous15, 18) ^ (previous15 >>> 3);
      const sigma1 = rotateRight(previous2, 17) ^ rotateRight(previous2, 19) ^ (previous2 >>> 10);
      words[index] = (words[index - 16] + sigma0 + words[index - 7] + sigma1) >>> 0;
    }

    let [a, b, c, d, e, f, g, h] = state;
    for (let index = 0; index < 64; index += 1) {
      const sum1 = rotateRight(e, 6) ^ rotateRight(e, 11) ^ rotateRight(e, 25);
      const choose = (e & f) ^ (~e & g);
      const temporary1 = (h + sum1 + choose + constants[index] + words[index]) >>> 0;
      const sum0 = rotateRight(a, 2) ^ rotateRight(a, 13) ^ rotateRight(a, 22);
      const majority = (a & b) ^ (a & c) ^ (b & c);
      const temporary2 = (sum0 + majority) >>> 0;
      h = g;
      g = f;
      f = e;
      e = (d + temporary1) >>> 0;
      d = c;
      c = b;
      b = a;
      a = (temporary1 + temporary2) >>> 0;
    }
    state[0] = (state[0] + a) >>> 0;
    state[1] = (state[1] + b) >>> 0;
    state[2] = (state[2] + c) >>> 0;
    state[3] = (state[3] + d) >>> 0;
    state[4] = (state[4] + e) >>> 0;
    state[5] = (state[5] + f) >>> 0;
    state[6] = (state[6] + g) >>> 0;
    state[7] = (state[7] + h) >>> 0;
  }

  return Array.from(state, (word) => word.toString(16).padStart(8, "0")).join("");
}

function rotateRight(value: number, count: number): number {
  return (value >>> count) | (value << (32 - count));
}
