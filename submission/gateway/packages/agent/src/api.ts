import { AgentConfig } from './config';

export interface Task {
  id: string;
  title: string;
  task_type: string;
  status: string;
  attempt_no: number;
  payload: Record<string, unknown>;
  acceptance_check: Record<string, unknown> | null;
  dependencies: string[];
  priority: number;
  required_capabilities: Record<string, unknown> | string[] | null;
}

export class OrchestratorApi {
  constructor(private cfg: AgentConfig) {}

  private url(path: string): string {
    return `${this.cfg.orchestratorUrl.replace(/\/$/, '')}${path}`;
  }

  private async post<T>(path: string, body: unknown): Promise<T> {
    const res = await fetch(this.url(path), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(30_000),
    });
    if (!res.ok) {
      const text = await res.text().catch(() => '');
      throw new Error(`POST ${path} → ${res.status}: ${text}`);
    }
    const text = await res.text();
    return text ? (JSON.parse(text) as T) : ({} as T);
  }

  async register(fingerprint: Record<string, unknown>, capabilities?: Record<string, unknown>): Promise<string> {
    const agentType = this.cfg.agentType;
    const caps = capabilities ?? {
      agent: agentType,
      [agentType]: true,
      coding: true,
    };

    const body = {
      name: this.cfg.agentName,
      agent_type: this.cfg.agentType,
      host_id: this.cfg.agentName,
      model_policy: this.cfg.model,
      max_concurrency: this.cfg.maxConcurrency,
      network_capabilities: ['outbound-http'],
      capabilities: caps,
      ...fingerprint,
    };
    const res = await this.post<{ agent_id: string }>('/agents/register', body);
    return res.agent_id;
  }

  async poll(agentId: string): Promise<Task | null> {
    const res = await this.post<{ task: Task | null }>('/tasks/poll', { agent_id: agentId });
    return res.task ?? null;
  }

  async heartbeat(taskId: string, agentId: string): Promise<void> {
    await this.post(`/tasks/${taskId}/heartbeat`, { agent_id: agentId });
  }

  async agentHeartbeat(agentId: string): Promise<void> {
    await this.post(`/agents/${agentId}/heartbeat`, {});
  }

  async complete(
    taskId: string,
    agentId: string,
    summary: string,
    artifactUris: string[],
    acceptanceResult: string,
  ): Promise<void> {
    await this.post(`/tasks/${taskId}/complete`, {
      agent_id: agentId,
      summary,
      artifact_uris: artifactUris,
      acceptance_result: acceptanceResult,
    });
  }

  async createArtifact(
    taskId: string,
    artifactType: 'patch' | 'log' | 'test_result' | 'screenshot' | 'report' | 'workspace_snapshot' | 'other',
    uri: string,
    metadata: Record<string, unknown> = {},
  ): Promise<string> {
    const res = await this.post<{ artifact_id: string }>('/artifacts', {
      task_id: taskId,
      artifact_type: artifactType,
      uri,
      metadata,
    });
    return res.artifact_id;
  }

  async fail(
    taskId: string,
    agentId: string,
    errorType: string,
    errorMessage: string,
    blockedUntil?: string,
  ): Promise<void> {
    await this.post(`/tasks/${taskId}/fail`, {
      agent_id: agentId,
      error_type: errorType,
      error_message: errorMessage,
      ...(blockedUntil ? { blocked_until: blockedUntil } : {}),
    });
  }
}
