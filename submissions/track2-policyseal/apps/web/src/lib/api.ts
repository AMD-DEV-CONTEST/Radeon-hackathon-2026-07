import type {
  ApiErrorBody,
  Approval,
  CopilotReply,
  CopilotThread,
  DisclosureContext,
  DisclosureTask,
  ExceptionSubmission,
  HealthResponse,
  ReviewData,
  Revision,
  Simulation,
  StageEvent,
} from "./types";

export class PolicySealApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "PolicySealApiError";
    this.status = status;
    this.code = code;
  }
}

async function decodeError(response: Response): Promise<PolicySealApiError> {
  let body: ApiErrorBody | undefined;
  try {
    body = (await response.json()) as ApiErrorBody;
  } catch {
    body = undefined;
  }
  return new PolicySealApiError(
    response.status,
    body?.detail?.code ?? "request_failed",
    body?.detail?.message ?? `Request failed with status ${response.status}.`,
  );
}

async function requestJson<T>(
  path: string,
  init: RequestInit = {},
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      Accept: "application/json",
      ...(init.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      ...init.headers,
    },
    signal,
  });
  if (!response.ok) {
    throw await decodeError(response);
  }
  return (await response.json()) as T;
}

export function getHealth(signal?: AbortSignal): Promise<HealthResponse> {
  return requestJson<HealthResponse>("/api/health", {}, signal);
}

export function listTasks(signal?: AbortSignal): Promise<DisclosureTask[]> {
  return requestJson<DisclosureTask[]>("/api/tasks", {}, signal);
}

export function getTask(taskId: string, signal?: AbortSignal): Promise<DisclosureTask> {
  return requestJson<DisclosureTask>(`/api/tasks/${encodeURIComponent(taskId)}`, {}, signal);
}

export function createTask(
  file: File,
  context: DisclosureContext,
  requesterId: string,
  signal?: AbortSignal,
): Promise<DisclosureTask> {
  const form = new FormData();
  form.set("file", file);
  form.set("context_json", JSON.stringify(context));
  form.set("requester_id", requesterId);
  return requestJson<DisclosureTask>("/api/tasks", { method: "POST", body: form }, signal);
}

export function analyzeRevision(revisionId: string, signal?: AbortSignal): Promise<Revision> {
  return requestJson<Revision>(
    `/api/revisions/${encodeURIComponent(revisionId)}/analyze`,
    { method: "POST" },
    signal,
  );
}

export function getReview(revisionId: string, signal?: AbortSignal): Promise<ReviewData> {
  return requestJson<ReviewData>(
    `/api/revisions/${encodeURIComponent(revisionId)}/review`,
    {},
    signal,
  );
}

export function simulateContext(
  taskId: string,
  context: DisclosureContext,
  signal?: AbortSignal,
): Promise<Simulation> {
  return requestJson<Simulation>(
    `/api/tasks/${encodeURIComponent(taskId)}/simulations`,
    { method: "POST", body: JSON.stringify({ context }) },
    signal,
  );
}

export function confirmFormalContext(
  taskId: string,
  simulationId: string,
  actor: string,
  signal?: AbortSignal,
): Promise<Revision> {
  return requestJson<Revision>(
    `/api/tasks/${encodeURIComponent(taskId)}/formal-context`,
    { method: "POST", body: JSON.stringify({ simulation_id: simulationId, actor }) },
    signal,
  );
}

export function requestApproval(
  revisionId: string,
  actor: string,
  signal?: AbortSignal,
): Promise<Approval> {
  return requestJson<Approval>(
    `/api/revisions/${encodeURIComponent(revisionId)}/approval-requests`,
    { method: "POST", body: JSON.stringify({ actor }) },
    signal,
  );
}

export function getRevisionApproval(
  revisionId: string,
  signal?: AbortSignal,
): Promise<Approval> {
  return requestJson<Approval>(
    `/api/revisions/${encodeURIComponent(revisionId)}/approval-request`,
    {},
    signal,
  );
}

export function resolveApproval(
  approval: Approval,
  operation: "approve" | "reject",
  actor: string,
  signal?: AbortSignal,
): Promise<Approval> {
  const body =
    operation === "approve"
      ? { actor, expected_binding_sha256: approval.binding_sha256 }
      : { actor, reason_code: "policy_reviewer_rejected" };
  return requestJson<Approval>(
    `/api/approval-requests/${encodeURIComponent(approval.id)}/${operation}`,
    { method: "POST", body: JSON.stringify(body) },
    signal,
  );
}

export function startCopilotThread(
  taskId: string,
  revisionId: string,
  displayReference?: string,
  signal?: AbortSignal,
): Promise<CopilotThread> {
  return requestJson<CopilotThread>(
    "/api/copilot/threads",
    {
      method: "POST",
      body: JSON.stringify({
        task_id: taskId,
        revision_id: revisionId,
        display_reference: displayReference,
      }),
    },
    signal,
  );
}

export function sendCopilotMessage(
  threadId: string,
  taskId: string,
  message: string,
  signal?: AbortSignal,
): Promise<CopilotReply> {
  return requestJson<CopilotReply>(
    `/api/copilot/threads/${encodeURIComponent(threadId)}/messages`,
    { method: "POST", body: JSON.stringify({ task_id: taskId, message }) },
    signal,
  );
}

export function submitExceptionDraft(
  draftId: string,
  actor: string,
  signal?: AbortSignal,
): Promise<ExceptionSubmission> {
  return requestJson<ExceptionSubmission>(
    `/api/copilot/exception-drafts/${encodeURIComponent(draftId)}/submit`,
    { method: "POST", body: JSON.stringify({ actor }) },
    signal,
  );
}

export function businessDownloadUrl(revisionId: string, approvalId?: string): string {
  const base = `/api/revisions/${encodeURIComponent(revisionId)}/download`;
  return approvalId ? `${base}?approval_id=${encodeURIComponent(approvalId)}` : base;
}

export function evidenceDownloadUrl(revisionId: string): string {
  return `/api/revisions/${encodeURIComponent(revisionId)}/evidence`;
}

export async function downloadArtifact(path: string): Promise<void> {
  const response = await fetch(path, { headers: { Accept: "application/octet-stream" } });
  if (!response.ok) throw await decodeError(response);
  const disposition = response.headers.get("content-disposition") ?? "";
  const filename = disposition.match(/filename="?([^";]+)"?/i)?.[1] ?? "policyseal-output";
  const url = URL.createObjectURL(await response.blob());
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

export async function fetchStageEvents(
  revisionId: string,
  afterSequence = 0,
  signal?: AbortSignal,
): Promise<StageEvent[]> {
  const response = await fetch(`/api/revisions/${encodeURIComponent(revisionId)}/events`, {
    headers: {
      Accept: "text/event-stream",
      ...(afterSequence > 0 ? { "Last-Event-ID": String(afterSequence) } : {}),
    },
    signal,
  });
  if (!response.ok) {
    throw await decodeError(response);
  }
  const text = await response.text();
  return text
    .split("\n\n")
    .map((block) => block.split("\n").find((line) => line.startsWith("data: ")))
    .filter((line): line is string => Boolean(line))
    .map((line) => JSON.parse(line.slice(6)) as StageEvent)
    .sort((left, right) => left.sequence - right.sequence);
}
