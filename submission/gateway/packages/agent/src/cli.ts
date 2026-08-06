#!/usr/bin/env node
import { Command } from 'commander';
import * as os from 'os';
import { collectFingerprint } from './fingerprint';
import { OrchestratorApi } from './api';
import { runPollLoop } from './poll';
import { makeLogger } from './logger';
import type { AgentConfig } from './config';

const DEFAULT_API_BASE = 'https://api.deepseek.com';

const program = new Command();

program
  .name('ua-agent')
  .description('UnionAgents Reasonix headless agent executor')
  .version('0.1.0');

program
  .command('run', { isDefault: true })
  .description('Register with orchestrator and start polling for tasks')
  .option('--mode <mode>',                      'Execution mode', 'agent')
  .requiredOption('--orchestrator-url <url>',  'Orchestrator base URL',
    process.env['ORCHESTRATOR_URL'] ?? 'http://127.0.0.1:8000')
  .requiredOption('--agent-name <name>',        'Agent display name',
    process.env['AGENT_NAME'] ?? os.hostname())
  .option('--agent-type <type>',                'Agent type', 'reasonix')
  .option('--workspace-root <path>',            'Root directory for task workspaces',
    process.env['WORKSPACE_ROOT'] ?? process.cwd())
  .option('--max-concurrency <n>',              'Max concurrent tasks',
    process.env['MAX_CONCURRENCY'] ?? '3')
  .option('--poll-interval <sec>',              'Seconds between polls',
    process.env['POLL_INTERVAL'] ?? '5')
  .option('--max-turns-per-task <n>',           'Max agent turns per task',
    process.env['MAX_TURNS_PER_TASK'] ?? '30')
  .option('--heartbeat-interval <sec>',         'Heartbeat interval in seconds',
    process.env['HEARTBEAT_INTERVAL'] ?? '30')
  .option('--gateway-url <url>',                'Gateway WebSocket base URL for standby mode',
    process.env['GATEWAY_URL'] ?? '')
  .option('--gateway-token <token>',            'Bearer token for gateway auth (or set GATEWAY_TOKEN env)',
    process.env['GATEWAY_TOKEN'] ?? '')
  .option('--gateway-username <user>',          'Auto-login username for gateway (or set GATEWAY_USERNAME env)',
    process.env['GATEWAY_USERNAME'] ?? '')
  .option('--gateway-password <pass>',          'Auto-login password for gateway (or set GATEWAY_PASSWORD env)',
    process.env['GATEWAY_PASSWORD'] ?? '')
  .option('--skill <path>',                     'Path to SKILL.md file to load as hub/role override',
    process.env['UA_SKILL'] ?? '')
  .option('--model <model>',                    'DeepSeek model name',
    process.env['DEEPSEEK_MODEL'] ?? 'deepseek-chat')
  .option('--api-base <url>',                   'DeepSeek API base URL',
    process.env['DEEPSEEK_API_BASE'] ?? DEFAULT_API_BASE)
  .option('--codex-command <cmd>',              'Codex CLI command',
    process.env['CODEX_COMMAND'] ?? 'codex')
  .action(async (opts: Record<string, string>) => {
    const log = makeLogger('agent');
    const mode = opts['mode'] as string;
    const agentType = opts['agentType'] as string;
    const modelOptionProvided = process.argv.some(arg => arg === '--model' || arg.startsWith('--model='));
    const rawModel = opts['model'] as string;
    const model = agentType === 'codex' && !modelOptionProvided && !process.env['CODEX_MODEL']
      ? ''
      : rawModel;

    if (mode !== 'agent' && mode !== 'standby') {
      log.error('unsupported mode=%s; expected agent or standby', mode);
      process.exit(1);
    }

    const apiKey = process.env['DEEPSEEK_API_KEY'] ?? '';
    const providerUsesDeepSeek = agentType !== 'codex';
    const providerAuthRequired = mode !== 'standby' && providerUsesDeepSeek;
    const hasProviderKey = !providerUsesDeepSeek || !!apiKey;

    // Security: enforce official DeepSeek API only — no OpenRouter or proxies
    const apiBase = opts['apiBase'] as string;
    if (providerAuthRequired && apiKey && !apiBase.includes('api.deepseek.com')) {
      log.error('Only the official DeepSeek API (api.deepseek.com) is permitted. Got: %s', apiBase);
      process.exit(1);
    }

    const cfg: AgentConfig = {
      mode,
      orchestratorUrl:   opts['orchestratorUrl'] as string,
      agentName:         opts['agentName'] as string,
      agentType,
      workspaceRoot:     opts['workspaceRoot'] as string,
      maxConcurrency:    parseInt(opts['maxConcurrency'] as string, 10),
      pollInterval:      parseFloat(opts['pollInterval'] as string),
      maxTurnsPerTask:   parseInt(opts['maxTurnsPerTask'] as string, 10),
      heartbeatInterval: parseInt(opts['heartbeatInterval'] as string, 10),
      model,
      apiKey,
      apiBase,
      codexCommand:      opts['codexCommand'] as string,
      skill:             opts['skill'] as string,
      gatewayUrl:        (opts['gatewayUrl'] as string) ||
                         (opts['orchestratorUrl'] as string).replace(':8000', ':8001'),
      gatewayToken:      (opts['gatewayToken'] as string) || (process.env['GATEWAY_TOKEN'] ?? ''),
      gatewayUsername:   (opts['gatewayUsername'] as string) || (process.env['GATEWAY_USERNAME'] ?? ''),
      gatewayPassword:   (opts['gatewayPassword'] as string) || (process.env['GATEWAY_PASSWORD'] ?? ''),
    };

    // Step 1: collect fingerprint, even without a provider API key.
    log.info('collecting fingerprint...');
    const fp = collectFingerprint(cfg.workspaceRoot);
    log.info('os=%s shell=%s cmds=%s tools=%s',
      fp.os, fp.shell, fp.available_commands.join(','), fp.tools.join(','));

    const api = new OrchestratorApi(cfg);

    // Step 2: build capabilities with an explicit provider_auth flag.
    const capabilities: Record<string, unknown> = {
      agent: cfg.agentType,
      [cfg.agentType]: true,
      provider_auth: hasProviderKey,
      standby: mode === 'standby',
    };

    // Only declare coding:true when model execution is actually available.
    if (hasProviderKey) {
      if (cfg.agentType === 'reasonix') {
        capabilities['coding'] = true;
        capabilities['reasoning'] = true;
      }
      if (cfg.agentType === 'codex') {
        capabilities['coding'] = true;
        capabilities['codex'] = true;
      }
    }

    // Add tool capabilities from fingerprint
    for (const t of fp.tools) {
      capabilities[t] = true;
    }

    // Step 3: register identity before checking provider credentials.
    log.info('registering with orchestrator url=%s name=%s caps=%s',
      cfg.orchestratorUrl, cfg.agentName, JSON.stringify(capabilities));
    let agentId: string;
    try {
      agentId = await api.register(fp as unknown as Record<string, unknown>, capabilities);
    } catch (err) {
      log.error('registration failed: %s', (err as Error).message);
      process.exit(1);
    }
    log.info('registered: agent_id=%s', agentId);
    console.log(`[agent] registered: agent_id=${agentId}`);

    // Step 4: handle missing provider credentials after registration.
    if (providerAuthRequired && !apiKey) {
      log.warn('DEEPSEEK_API_KEY is not set - provider_auth=false, cannot execute coding tasks');
      console.log('[agent] blocked_auth: DEEPSEEK_API_KEY is not set. Agent registered without coding capability.');
      console.log('[agent] Exiting - set DEEPSEEK_API_KEY and restart to poll for coding tasks.');
      process.exit(0);
    }

    // Step 5: enter the execution loop.
    //
    // Standby is deliberately lightweight in the closed UAS loop:
    // the worker only registers, polls, leases, heartbeats, and submits.
    // Gateway/bedroom is no longer part of the task handoff path.
    if (mode === 'standby') {
      log.info('standby poll loop capabilities=%s', JSON.stringify(capabilities));
      await runPollLoop(agentId, cfg, api);
    } else {
      await runPollLoop(agentId, cfg, api);
    }
  });

program.parseAsync(process.argv).catch(err => {
  console.error(err);
  process.exit(1);
});
