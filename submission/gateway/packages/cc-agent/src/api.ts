export interface Task {
  id: string;
  title: string;
  task_type: string;
  status: string;
  attempt_no: number;
  payload: Record<string, unknown>;
  dependencies: string[];
  priority: number;
  required_capabilities: Record<string, unknown> | string[] | null;
  acceptance_check: Record<string, unknown> | null;
}

export class OrchestratorApi {
  constructor(private readonly baseUrl: string) {}

  private url(path: string): string {
    return `${this.baseUrl.replace(/\/$/, '')}${path}`;
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

  async register(agentName: string): Promise<string> {
    const body = {
      name: agentName,
      agent_type: 'claude_code',
      host_id: agentName,
      model_policy: 'claude-subscription',
      max_concurrency: 1,
      network_capabilities: ['outbound-http'],
      capabilities: {
        agent: 'claude',
        claude: true,
        coding: true,
        review: true,
        provider_auth: true,
      },
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

  async complete(
    taskId: string,
    agentId: string,
    summary: string,
    artifacts: string[],
    acceptanceResult: string = 'pass',
  ): Promise<void> {
    await this.post(`/tasks/${taskId}/complete`, {
      agent_id: agentId,
      summary,
      artifact_uris: artifacts,
      acceptance_result: acceptanceResult,
    });
  }

  async fail(taskId: string, agentId: string, errorType: string, errorMessage: string, blockedUntil?: string): Promise<void> {
    const body: Record<string, unknown> = {
      agent_id: agentId,
      error_type: errorType,
      error_message: errorMessage,
    };
    if (blockedUntil) {
      body['blocked_until'] = blockedUntil;
    }
    await this.post(`/tasks/${taskId}/fail`, body);
  }
}
