#!/usr/bin/env node
/**
 * cc-agent — Claude Code headless agent mode
 * Polls UnionAgents Orchestrator and executes tasks via `claude -p` CLI (subscription OAuth).
 *
 * Usage:
 *   cc-agent run --orchestrator-url http://111.228.42.18:8000
 *   cc-agent run --orchestrator-url http://... --agent-name cc-reviewer
 */
import { Command } from 'commander';
import * as os from 'os';
import * as cp from 'child_process';
import { OrchestratorApi } from './api';
import { runSession } from './session';

const program = new Command();

program
  .name('cc-agent')
  .description('Claude Code headless agent — polls Orchestrator and executes tasks via claude CLI')
  .version('0.1.0');

program
  .command('run', { isDefault: true })
  .description('Register with orchestrator and start polling for tasks')
  .requiredOption('--orchestrator-url <url>', 'Orchestrator base URL',
    process.env['ORCHESTRATOR_URL'] ?? 'http://127.0.0.1:8000')
  .option('--agent-name <name>', 'Agent display name',
    process.env['AGENT_NAME'] ?? `cc-${os.hostname()}`)
  .option('--max-concurrency <n>', 'Max concurrent tasks',
    process.env['MAX_CONCURRENCY'] ?? '1')
  .option('--poll-interval <sec>', 'Seconds between polls',
    process.env['POLL_INTERVAL'] ?? '5')
  .option('--heartbeat-interval <sec>', 'Heartbeat interval in seconds',
    process.env['HEARTBEAT_INTERVAL'] ?? '30')
  .option('--timeout <sec>', 'Max seconds per task (claude -p timeout)',
    process.env['CLAUDE_TIMEOUT'] ?? '1800')
  .action(async (opts: Record<string, string>) => {
    // Verify claude CLI is available before registering
    try {
      const ver = cp.execSync('claude --version', { encoding: 'utf-8', timeout: 10_000 }).trim();
      console.log(`[cc-agent] Claude Code CLI: ${ver}`);
    } catch {
      console.error('[cc-agent] ERROR: claude CLI not found in PATH');
      console.error('[cc-agent] Install Claude Code: https://claude.ai/code');
      process.exit(1);
    }

    const orchestratorUrl = opts['orchestratorUrl'] as string;
    const agentName       = opts['agentName'] as string;
    const maxConcurrency  = parseInt(opts['maxConcurrency'] as string, 10);
    const pollInterval    = parseFloat(opts['pollInterval'] as string) * 1000;
    const heartbeatSec    = parseInt(opts['heartbeatInterval'] as string, 10);
    const timeoutSec      = parseInt(opts['timeout'] as string, 10);

    const api = new OrchestratorApi(orchestratorUrl);

    console.log(`[cc-agent] registering with orchestrator: ${orchestratorUrl}`);
    let agentId: string;
    try {
      agentId = await api.register(agentName);
    } catch (err) {
      console.error(`[cc-agent] registration failed: ${(err as Error).message}`);
      process.exit(1);
    }
    console.log(`[cc-agent] registered: agent_id=${agentId} (using claude CLI / subscription)`);

    let stopping = false;
    let active = 0;
    process.once('SIGINT',  () => { stopping = true; });
    process.once('SIGTERM', () => { stopping = true; });

    while (!stopping) {
      if (active >= maxConcurrency) {
        await sleep(pollInterval);
        continue;
      }

      let task = null;
      try {
        task = await api.poll(agentId);
      } catch (err) {
        console.error(`[cc-agent] poll error: ${(err as Error).message}`);
        await sleep(pollInterval);
        continue;
      }

      if (!task) {
        await sleep(pollInterval);
        continue;
      }

      console.log(`[cc-agent] leased task task_id=${task.id} title=${task.title}`);
      active++;
      void runSession(task, agentId, api, heartbeatSec, timeoutSec).finally(() => { active--; });
    }

    // drain active sessions before exit
    while (active > 0) await sleep(500);
    console.log('[cc-agent] stopped');
  });

program.parseAsync(process.argv).catch(err => {
  console.error(err);
  process.exit(1);
});

function sleep(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms));
}
