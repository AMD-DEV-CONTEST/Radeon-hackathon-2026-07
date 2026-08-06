import { AgentConfig } from './config';
import { OrchestratorApi } from './api';
import { agentSession } from './session';
import { codexAgentSession } from './codex-session';
import { makeLogger } from './logger';

class Semaphore {
  private queue: Array<() => void> = [];
  private count: number;

  constructor(max: number) { this.count = max; }

  async acquire(): Promise<void> {
    if (this.count > 0) { this.count--; return; }
    await new Promise<void>(resolve => this.queue.push(resolve));
  }

  release(): void {
    const next = this.queue.shift();
    if (next) { next(); }
    else { this.count++; }
  }
}

export async function runPollLoop(
  agentId: string,
  cfg: AgentConfig,
  api: OrchestratorApi,
): Promise<void> {
  const log = makeLogger('poll');
  const sem = new Semaphore(cfg.maxConcurrency);

  log.info('poll loop started agent_id=%s max_concurrency=%d poll_interval=%ds',
    agentId, cfg.maxConcurrency, cfg.pollInterval);

  let stopping = false;
  const stop = () => { stopping = true; };
  process.once('SIGINT', stop);
  process.once('SIGTERM', stop);

  const agentHeartbeat = setInterval(() => {
    void api.agentHeartbeat(agentId).catch(err => {
      log.warn('agent heartbeat failed agent_id=%s: %s', agentId, (err as Error).message);
    });
  }, cfg.heartbeatInterval * 1000);
  void api.agentHeartbeat(agentId).catch(err => {
    log.warn('initial agent heartbeat failed agent_id=%s: %s', agentId, (err as Error).message);
  });

  while (!stopping) {
    let task = null;
    try {
      task = await api.poll(agentId);
    } catch (err) {
      log.error('poll error: %s', (err as Error).message);
      await sleep(cfg.pollInterval * 1000);
      continue;
    }

    if (!task) {
      log.info('waiting for tasks...');
      await sleep(cfg.pollInterval * 1000);
      continue;
    }

    log.info('leased task task_id=%s title=%s', task.id, task.title);

    await sem.acquire();

    void (async () => {
      try {
        if (cfg.agentType === 'codex') {
          await codexAgentSession(task!, agentId, cfg, api);
        } else {
          await agentSession(task!, agentId, cfg, api);
        }
      } catch (err) {
        log.error('session uncaught task_id=%s: %s', task!.id, (err as Error).message);
      } finally {
        sem.release();
      }
    })();
  }

  clearInterval(agentHeartbeat);
  log.info('draining active sessions...');
  for (let i = 0; i < cfg.maxConcurrency; i++) await sem.acquire();
  log.info('poll loop stopped');
}

function sleep(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms));
}
