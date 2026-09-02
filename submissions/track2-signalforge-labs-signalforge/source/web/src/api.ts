import type {
  CaseSummary,
  ExecutionPlan,
  IntelligenceRecord,
  FinancialSummary,
  PeerEvaluationSuite,
  ProductCatalog,
  Projection,
  ProtectedIntelligenceRecord,
  RunView,
  ScenarioControl,
  StoredCase,
  WorkspaceConfig
} from "./types";

type Problem = { error?: { code?: string } };

async function readJSON<T>(response: Response): Promise<T> {
  const payload = (await response.json()) as T & Problem;
  if (!response.ok) {
    throw new Error(payload.error?.code ?? `request_failed_${response.status}`);
  }
  return payload;
}

export async function getConfig(): Promise<WorkspaceConfig> {
  return readJSON(await fetch("/api/v1/config"));
}

export async function getCatalog(): Promise<ProductCatalog> {
  return readJSON(await fetch("/api/v1/catalog"));
}

export async function getFinancials(): Promise<FinancialSummary> {
  return readJSON(await fetch("/api/v1/financials"));
}

export async function getPeerEvaluations(): Promise<PeerEvaluationSuite> {
  return readJSON(await fetch("/api/v1/peer-evaluations"));
}

export async function getGoldenCase(): Promise<Projection> {
  return readJSON(await fetch("/api/v1/cases/golden"));
}

export async function createRun(question: string, scenario: ScenarioControl, retain: boolean): Promise<RunView> {
  return readJSON(await fetch("/api/v1/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, scenario, retain })
  }));
}

export async function getRun(runID: string): Promise<RunView> {
  return readJSON(await fetch(`/api/v1/runs/${encodeURIComponent(runID)}`));
}

export async function getExecutionPlan(runID: string): Promise<ExecutionPlan> {
  return readJSON(await fetch(`/api/v1/runs/${encodeURIComponent(runID)}/execution`));
}

export async function createFollowUp(runID: string, question: string, retain: boolean): Promise<RunView> {
  return readJSON(await fetch(`/api/v1/runs/${encodeURIComponent(runID)}/follow-ups`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, retain })
  }));
}

export async function listCases(): Promise<CaseSummary[]> {
  const payload = await readJSON<{ cases: CaseSummary[] }>(await fetch("/api/v1/cases"));
  return payload.cases;
}

export async function getCase(caseID: string): Promise<StoredCase> {
  return readJSON(await fetch(`/api/v1/cases/${encodeURIComponent(caseID)}`));
}

export async function deleteCase(caseID: string): Promise<void> {
  await readJSON(await fetch(`/api/v1/cases/${encodeURIComponent(caseID)}`, { method: "DELETE" }));
}

export function caseExportURL(caseID: string): string {
  return `/api/v1/cases/${encodeURIComponent(caseID)}/export`;
}

export function subscribeToRun(runID: string, onEvent: (event: MessageEvent<string>) => void, onError: () => void): EventSource {
  const source = new EventSource(`/api/v1/runs/${encodeURIComponent(runID)}/events`);
  source.addEventListener("progress", onEvent as EventListener);
  source.onerror = onError;
  return source;
}

export async function getIntelligence(runID: string): Promise<IntelligenceRecord> {
  return readJSON(await fetch(`/api/v1/runs/${encodeURIComponent(runID)}/intelligence`));
}

export async function getProtectedIntelligence(runID: string, token: string): Promise<ProtectedIntelligenceRecord> {
  return readJSON(await fetch(`/api/v1/runs/${encodeURIComponent(runID)}/intelligence/protected`, {
    headers: { "X-SignalForge-Audit-Token": token }
  }));
}

export async function purgeProtectedIntelligence(runID: string, token: string): Promise<void> {
  await readJSON(await fetch(`/api/v1/runs/${encodeURIComponent(runID)}/intelligence/protected`, {
    method: "DELETE",
    headers: { "X-SignalForge-Audit-Token": token }
  }));
}
