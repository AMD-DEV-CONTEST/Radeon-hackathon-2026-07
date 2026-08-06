import WebSocket from 'ws';
import { AgentConfig } from './config';
import { OrchestratorApi, Task } from './api';
import { agentSession } from './session';
import { codexAgentSession } from './codex-session';
import { claudeCodeAgentSession } from './claude-code-session';
import { makeLogger } from './logger';

export interface SessionInvite {
  type: 'session_invite';
  session_id: string;
  goal: string;
  role: string;
  stage?: string;
  stage_round?: number;
  max_rounds?: number;
  hub_agent_id?: string;
  conference_url: string;
  required_capabilities?: Record<string, unknown>;
  expires_at?: string;
}

export async function runConferenceRoom(
  invite: SessionInvite,
  agentId: string,
  cfg: AgentConfig,
  api: OrchestratorApi,
  log: ReturnType<typeof makeLogger>,
): Promise<void> {
  const { session_id, conference_url } = invite;
  const tokenSuffix = cfg.gatewayToken ? `?token=${encodeURIComponent(cfg.gatewayToken)}` : '';
  const wsUrl = conference_url.includes('?') ? conference_url : `${conference_url}${tokenSuffix}`;
  log.info('entering conference session_id=%s url=%s', session_id, wsUrl);

  return new Promise((resolve, reject) => {
    const ws = new WebSocket(wsUrl);
    let closed = false;

    const finish = (err?: Error) => {
      if (closed) return;
      closed = true;
      try { ws.terminate(); } catch { /* ignore */ }
      if (err) reject(err);
      else resolve();
    };

    ws.on('open', () => {
      log.info('conference ws connected session_id=%s', session_id);
      ws.send(JSON.stringify({
        type: 'session_join',
        session_id,
        agent_id: agentId,
        agent_name: cfg.agentName,
        role: invite.role,
      }));
    });

    let sessionContext: Record<string, unknown> = {};

    const sessionSend = (payload: Record<string, unknown>) => {
      if (!closed && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ session_id, agent_id: agentId, ...payload }));
      }
    };

    ws.on('message', (data: WebSocket.RawData) => {
      let msg: Record<string, unknown>;
      try { msg = JSON.parse(data.toString()) as Record<string, unknown>; }
      catch { return; }

      switch (msg['type'] as string) {
        case 'session_ready':
          log.info('conference ready session_id=%s — waiting for tasks', session_id);
          break;

        case 'session_join':
          log.info('agent joined: %s (role=%s)',
            msg['agent_name'] ?? msg['agent_id'], msg['role'] ?? 'participant');
          break;

        case 'context_snapshot':
          // Store session context — informs the agent of current state and decisions
          sessionContext = msg as Record<string, unknown>;
          log.info('context_snapshot goal=%s decisions=%d tasks=%d',
            String(msg['goal'] ?? '').slice(0, 60),
            Array.isArray(msg['decisions']) ? msg['decisions'].length : 0,
            Array.isArray(msg['tasks']) ? msg['tasks'].length : 0);
          break;

        case 'session_message':
          log.info('[hub→%s] %s: %s',
            cfg.agentName,
            msg['from'] ?? 'hub',
            String(msg['content'] ?? '').slice(0, 120));
          break;

        case 'task_assigned': {
          const assignedTaskId = (msg['task_id'] as string) || (msg['task'] as Record<string,unknown>)?.title as string || 'task';
          const inlineTask = msg['task'] as Record<string, unknown> | undefined;
          log.info('task_assigned task_id=%s inline=%s', assignedTaskId, inlineTask ? 'yes' : 'no');

          void (async () => {
            try {
              // Try polling orchestrator first; fall back to inline task from message
              const polled = await api.poll(agentId);
              const task: Task | null = polled || (inlineTask ? {
                id: `gw-${crypto.randomUUID()}` as string,
                title: (inlineTask['title'] as string) || (inlineTask['description'] as string) || assignedTaskId,
                description: (inlineTask['description'] as string) || (inlineTask['title'] as string) || '',
                task_type: (inlineTask['task_type'] as string) || 'feature-implementation',
                status: 'running',
                payload: {
                  instruction: inlineTask['description'] || inlineTask['title'] || '',
                  ...inlineTask,
                },
                acceptance_check: {},
                required_capabilities: {},
                dependencies: [],
                priority: 100,
                max_attempts: 1,
                attempt_no: 1,
                lease_owner: agentId,
                created_by: 'gateway',
              } as unknown as Task : null);
              if (polled) {
                log.info('using orchestrator task: %s', polled.title);
              } else if (inlineTask) {
                log.info('using inline task: %s', task?.title);
              }
              if (!task) {
                log.warn('no task found (orchestrator poll returned null, no inline task)');
                sessionSend({ type: 'blocker', reason: 'task_not_found' });
                return;
              }

              log.info('executing task_id=%s title=%s', task.id, task.title);

              sessionSend({
                type: 'task_progress',
                task_id: task.id,
                status: 'running',
                message: `Starting: ${task.title}`,
              });

              if (cfg.agentType === 'codex') {
                await codexAgentSession(task, agentId, cfg, api);
              } else if (cfg.agentType === 'claude_code') {
                await claudeCodeAgentSession(task, agentId, cfg, api);
              } else {
                await agentSession(task, agentId, cfg, api, invite.stage);
              }

              sessionSend({
                type: 'task_complete',
                task_id: task.id,
                summary: task.title,
                artifacts: [],
              });
              log.info('task_id=%s done', task.id);

            } catch (err) {
              log.error('task execution failed: %s', (err as Error).message);
              sessionSend({ type: 'blocker', reason: (err as Error).message });
            }
          })();
          break;
        }

        case 'session_done': {
          const outcome = (msg['outcome'] as string) ?? 'unknown';
          const summary = (msg['summary'] as string) ?? '';
          log.info('session_done outcome=%s summary=%s', outcome, summary.slice(0, 80));
          void sessionContext; // retain reference (used for future context-aware replies)
          finish();
          break;
        }

        default:
          log.warn('conference: unknown msg type=%s', msg['type']);
      }
    });

    ws.on('error', (err: Error) => {
      log.error('conference ws error: %s', err.message);
      finish(err);
    });

    ws.on('close', () => {
      log.info('conference ws closed session_id=%s', session_id);
      finish();
    });
  });
}
