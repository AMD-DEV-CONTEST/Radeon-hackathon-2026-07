import WebSocket from 'ws';
import { AgentConfig } from './config';
import { OrchestratorApi } from './api';
import { makeLogger } from './logger';
import { runConferenceRoom, SessionInvite } from './conference';
import { agentSession } from './session';
import { codexAgentSession } from './codex-session';
import { claudeCodeAgentSession } from './claude-code-session';
import { getAdapter } from './adapter-registry';

type BedroomStatus = 'online_idle' | 'summoned' | 'in_session_idle' | 'running' | 'draining';

async function fetchGatewayToken(cfg: AgentConfig, log: ReturnType<typeof makeLogger>): Promise<string> {
  const loginUrl = cfg.gatewayUrl.replace(/^ws/, 'http').replace(/\/$/, '') + '/auth/login';
  log.info('auto-login gateway url=%s user=%s', loginUrl, cfg.gatewayUsername);
  const body = JSON.stringify({ username: cfg.gatewayUsername, password: cfg.gatewayPassword });
  const resp = await fetch(loginUrl, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body,
  });
  if (!resp.ok) {
    throw new Error(`gateway login failed: HTTP ${resp.status}`);
  }
  const data = await resp.json() as Record<string, unknown>;
  const token = data['token'] as string | undefined;
  if (!token) throw new Error('gateway login: no token in response');
  log.info('gateway token acquired (len=%d)', token.length);
  return token;
}

export async function runBedroomLoop(
  agentId: string,
  capabilities: Record<string, unknown>,
  cfg: AgentConfig,
  api: OrchestratorApi,
): Promise<void> {
  const log = makeLogger('bedroom');
  let stopping = false;

  process.once('SIGINT', () => { stopping = true; });
  process.once('SIGTERM', () => { stopping = true; });

  // Auto-login: if credentials provided but no token yet, fetch one
  if (!cfg.gatewayToken && cfg.gatewayUsername && cfg.gatewayPassword) {
    cfg.gatewayToken = await fetchGatewayToken(cfg, log);
  }

  // Derive bedroom WS URL: replace http(s) with ws(s), connect to /ws/agents/{id}
  const base = cfg.gatewayUrl.replace(/^http/, 'ws');
  const tokenSuffix = cfg.gatewayToken ? `?token=${encodeURIComponent(cfg.gatewayToken)}` : '';
  const wsUrl = `${base}/ws/agents/${agentId}${tokenSuffix}`;

  log.info('standby mode agent_id=%s ws=%s', agentId, wsUrl);

  let attempt = 0;

  while (!stopping) {
    try {
      log.info('bedroom connecting attempt=%d', attempt + 1);
      await connectBedroom(wsUrl, agentId, capabilities, cfg, api, log, () => stopping);
      attempt = 0; // reset on clean close
    } catch (err) {
      if (stopping) break;
      const delaySec = Math.min(Math.pow(2, attempt), 32);
      log.warn('ws_disconnected reason=%s attempt=%d reconnecting_in=%ds',
        (err as Error).message, attempt + 1, delaySec);
      attempt++;
      await sleep(delaySec * 1000);
      log.info('ws_reconnecting attempt=%d', attempt);
    }
  }

  log.info('bedroom loop stopped');
}

async function connectBedroom(
  wsUrl: string,
  agentId: string,
  capabilities: Record<string, unknown>,
  cfg: AgentConfig,
  api: OrchestratorApi,
  log: ReturnType<typeof makeLogger>,
  isStopping: () => boolean,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(wsUrl);
    let status: BedroomStatus = 'online_idle';
    let pingTimer: ReturnType<typeof setInterval> | null = null;
    let heartbeatTimer: ReturnType<typeof setInterval> | null = null;

    const cleanup = (err?: Error) => {
      if (pingTimer) clearInterval(pingTimer);
      if (heartbeatTimer) clearInterval(heartbeatTimer);
      try { ws.terminate(); } catch { /* ignore */ }
      if (err) reject(err);
      else resolve();
    };

    ws.on('open', () => {
      log.info('ws_connected agent_id=%s', agentId);
      ws.send(JSON.stringify({
        type: 'identify',
        agent_id: agentId,
        agent_name: cfg.agentName,
        agent_type: cfg.agentType,
        capabilities,
        status: 'online_idle',
      }));
    });

    ws.on('message', (data: WebSocket.RawData) => {
      let msg: Record<string, unknown>;
      try { msg = JSON.parse(data.toString()) as Record<string, unknown>; }
      catch { return; }

      switch (msg['type'] as string) {
        case 'gateway_ready':
          log.info('gateway ready - standing by (heartbeat every %ss)', cfg.heartbeatInterval);
          void api.agentHeartbeat(agentId).catch(err => {
            log.warn('agent heartbeat failed: %s', (err as Error).message);
          });
          heartbeatTimer = setInterval(() => {
            void api.agentHeartbeat(agentId).catch(err => {
              log.warn('agent heartbeat failed: %s', (err as Error).message);
            });
          }, cfg.heartbeatInterval * 1000);
          pingTimer = setInterval(() => {
            if (ws.readyState === WebSocket.OPEN) {
              ws.send(JSON.stringify({ type: 'ping' }));
            }
          }, 30_000);
          break;

        case 'pong':
          break;

        case 'session_invite': {
          const invite = msg as unknown as SessionInvite;
          log.info('session_invite session_id=%s role=%s goal=%s',
            invite.session_id, invite.role, (invite.goal ?? '').slice(0, 60));

          if (status !== 'online_idle') {
            log.warn('busy (status=%s) — declining session_id=%s', status, invite.session_id);
            ws.send(JSON.stringify({
              type: 'session_decline',
              session_id: invite.session_id,
              agent_id: agentId,
              reason: 'busy',
            }));
            break;
          }

          // Capability check (Gateway already filters, this is a safety net)
          const required = (invite.required_capabilities ?? {}) as Record<string, unknown>;
          if (!matchCapabilities(capabilities, required)) {
            log.warn('capability_mismatch — declining session_id=%s', invite.session_id);
            ws.send(JSON.stringify({
              type: 'session_decline',
              session_id: invite.session_id,
              agent_id: agentId,
              reason: 'capability_mismatch',
            }));
            break;
          }

          // Accept
          status = 'summoned';
          ws.send(JSON.stringify({
            type: 'session_join',
            session_id: invite.session_id,
            agent_id: agentId,
            agent_name: cfg.agentName,
            role: invite.role,
          }));
          status = 'in_session_idle';

          // Resolve conference_url to absolute WS URL if Gateway sent a relative path
          const gatewayBase = cfg.gatewayUrl.replace(/^http/, 'ws').replace(/\/$/, '');
          const conferenceUrl = invite.conference_url.startsWith('/')
            ? `${gatewayBase}${invite.conference_url}`
            : invite.conference_url;
          const resolvedInvite = { ...invite, conference_url: conferenceUrl };

          // Run conference room async — block further invites until done
          void (async () => {
            try {
              await runConferenceRoom(resolvedInvite, agentId, cfg, api, log);
            } catch (err) {
              log.error('conference error: %s', (err as Error).message);
            } finally {
              status = 'online_idle';
              log.info('returned to bedroom online_idle');
              // Use session_leave (handled by Gateway) to reset agent status
              if (ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({
                  type: 'session_leave',
                  session_id: invite.session_id,
                  agent_id: agentId,
                }));
              }
            }
          })();
          break;
        }

        case 'task_assigned': {
          const taskTitle = msg['task'] && (msg['task'] as Record<string, unknown>)['title']
            ? String((msg['task'] as Record<string, unknown>)['title'])
            : (msg['title'] || msg['task_id'] || '(unknown)');
          log.info('task_assigned notification: %s (status=%s)', String(taskTitle), status);

          if (ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({
              type: 'task_received',
              agent_id: agentId,
              task_id: msg['task_id'] || ((msg['task'] as Record<string, unknown>)?.['id']),
              status: 'acknowledged',
            }));
          }

          if (status !== 'online_idle') {
            log.warn('busy (status=%s) — skipping task_assigned poll', status);
            break;
          }

          status = 'running';
          void (async () => {
            try {
              const task = await api.poll(agentId);
              if (!task) {
                log.info('task_assigned: poll empty (race lost or no matching task)');
                return;
              }
              log.info('leased task_id=%s title=%s', task.id, task.title);
              const adapter = getAdapter(cfg.agentType, task.task_type);
              await adapter(task, agentId, cfg, api);
            } catch (err) {
              log.error('task execution error: %s', (err as Error).message);
            } finally {
              status = 'online_idle';
              log.info('returned to online_idle after task');
            }
          })();
          break;
        }

        default:
          log.warn('bedroom: unknown msg type=%s', msg['type']);
      }
    });

    ws.on('error', (err: Error) => {
      log.error('ws error: %s', err.message);
      cleanup(err);
    });

    ws.on('close', () => {
      if (pingTimer) clearInterval(pingTimer);
      if (heartbeatTimer) clearInterval(heartbeatTimer);
      log.info('ws_disconnected agent_id=%s stopping=%s', agentId, isStopping());
      if (isStopping()) resolve();
      else reject(new Error('bedroom ws closed unexpectedly'));
    });
  });
}

function matchCapabilities(
  agentCaps: Record<string, unknown>,
  required: Record<string, unknown>,
): boolean {
  for (const [k, v] of Object.entries(required)) {
    if (agentCaps[k] !== v) return false;
  }
  return true;
}

function sleep(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms));
}
