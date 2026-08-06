import { spawn } from 'child_process';
import * as fs from 'fs';
import * as path from 'path';
import { AgentConfig } from './config';
import { OrchestratorApi, Task } from './api';
import { runAcceptanceCheck, AcceptanceCheck } from './acceptance';
import { ToolExecutor } from './toolexec';
import { makeLogger } from './logger';

interface HeartbeatHandle { stop(): void }

function startHeartbeat(
  api: OrchestratorApi,
  taskId: string,
  agentId: string,
  intervalSec: number,
): HeartbeatHandle {
  const log = makeLogger('codex-hb');
  let active = true;
  const timer = setInterval(async () => {
    if (!active) return;
    try { await api.heartbeat(taskId, agentId); }
    catch (err) { log.warn('heartbeat failed task=%s: %s', taskId, (err as Error).message); }
  }, intervalSec * 1000);
  return { stop() { active = false; clearInterval(timer); } };
}

function initWorkspace(task: Task, workspacePath: string): void {
  fs.mkdirSync(workspacePath, { recursive: true });

  const context = (task.payload['context'] as Record<string, unknown> | undefined) ?? {};
  const mode = (context['mode'] as string | undefined) ?? 'inline';

  if (mode === 'inline') {
    const files = (context['files'] as Record<string, string> | undefined) ?? {};
    for (const [rel, content] of Object.entries(files)) {
      const abs = path.join(workspacePath, rel);
      fs.mkdirSync(path.dirname(abs), { recursive: true });
      fs.writeFileSync(abs, content, 'utf-8');
    }
  } else if (mode === 'git-clone') {
    const url = context['url'] as string | undefined;
    if (url) {
      // eslint-disable-next-line @typescript-eslint/no-var-requires
      const { execFileSync } = require('child_process') as typeof import('child_process');
      execFileSync('git', ['clone', url, workspacePath], { timeout: 120_000, stdio: 'pipe' });
    }
  }
}

function taskInstruction(task: Task, workspacePath: string): string {
  const instruction =
    (task.payload['instruction'] as string | undefined) ??
    task.title ??
    '(no instruction)';

  return `You are Codex running as a UnionAgents headless worker.

Task ID: ${task.id}
Task Type: ${task.task_type}
Workspace: ${workspacePath}

Instruction:
${instruction}

Rules:
- Work only inside the supplied workspace unless the task explicitly names another path.
- Do not ask the user questions; make a reasonable implementation choice.
- Run focused verification when possible.
- End with a concise summary and list changed artifacts.`;
}

function runCodex(
  command: string,
  prompt: string,
  cwd: string,
  outputPath: string,
  model?: string,
): Promise<{ code: number | null; stdout: string; stderr: string }> {
  const args = [
    'exec',
    '--cd', cwd,
    '--sandbox', 'workspace-write',
    '--ask-for-approval', 'never',
    '--output-last-message', outputPath,
  ];
  if (model) args.push('--model', model);
  args.push(prompt);

  return new Promise(resolve => {
    const child = spawn(command, args, {
      cwd,
      shell: process.platform === 'win32',
      windowsHide: true,
      env: process.env,
    });

    let stdout = '';
    let stderr = '';
    child.stdout?.on('data', chunk => { stdout += chunk.toString(); });
    child.stderr?.on('data', chunk => { stderr += chunk.toString(); });
    child.on('close', code => resolve({ code, stdout, stderr }));
    child.on('error', err => resolve({ code: -1, stdout, stderr: err.message }));
  });
}

export async function codexAgentSession(
  task: Task,
  agentId: string,
  cfg: AgentConfig,
  api: OrchestratorApi,
): Promise<void> {
  const log = makeLogger(`codex:${task.id.slice(0, 8)}`);
  const sessionRoot = path.join(cfg.workspaceRoot, task.id);
  const workspacePath = path.join(sessionRoot, 'workspace');
  const artifactsPath = path.join(sessionRoot, 'artifacts');
  const outputPath = path.join(artifactsPath, 'codex-final.md');

  log.info('start task_id=%s title=%s', task.id, task.title);

  try {
    initWorkspace(task, workspacePath);
    fs.mkdirSync(artifactsPath, { recursive: true });
  } catch (err) {
    await api.fail(task.id, agentId, 'blocked_env',
      `Workspace init failed: ${(err as Error).message}`);
    return;
  }

  const hb = startHeartbeat(api, task.id, agentId, cfg.heartbeatInterval);
  try {
    const result = await runCodex(
      cfg.codexCommand,
      taskInstruction(task, workspacePath),
      workspacePath,
      outputPath,
      cfg.model,
    );

    if (result.code !== 0) {
      const detail = (result.stderr || result.stdout || `codex exited ${result.code}`).slice(0, 4000);
      await api.fail(task.id, agentId, 'retryable', detail);
      return;
    }

    const summary = fs.existsSync(outputPath)
      ? fs.readFileSync(outputPath, 'utf-8').trim()
      : (result.stdout.trim() || 'Codex task completed.');

    const executor = new ToolExecutor(cfg.workspaceRoot, task.id, cfg.orchestratorUrl, log);
    const acceptanceResult = await runAcceptanceCheck(
      task.acceptance_check as AcceptanceCheck | null,
      workspacePath,
      executor,
      log,
    );

    await api.complete(task.id, agentId, summary.slice(0, 8000), [outputPath], acceptanceResult);
    log.info('done task_id=%s', task.id);
  } catch (err) {
    await api.fail(task.id, agentId, 'retryable',
      `Codex session crashed: ${(err as Error).message}`).catch(() => undefined);
  } finally {
    hb.stop();
  }
}
