import { AgentConfig } from './config';
import { OrchestratorApi, Task } from './api';
import { agentSession } from './session';
import { codexAgentSession } from './codex-session';
import { claudeCodeAgentSession } from './claude-code-session';

type SessionFn = (
  task: Task,
  agentId: string,
  cfg: AgentConfig,
  api: OrchestratorApi,
) => Promise<void>;

// Primary key: agentType. Extended key: "agentType:taskType" for type-specific overrides.
const REGISTRY: Record<string, SessionFn> = {
  claude_code: claudeCodeAgentSession,
  codex:       codexAgentSession,
  // Future: 'claude_code:document_analysis': lightweightSession,
};

export function getAdapter(agentType: string, taskType?: string): SessionFn {
  if (taskType) {
    const specific = REGISTRY[`${agentType}:${taskType}`];
    if (specific) return specific;
  }
  return REGISTRY[agentType] ?? agentSession;
}
