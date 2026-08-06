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
  const log = makeLogger('cc-hb');
  let active = true;
  const timer = setInterval(async () => {
    if (!active) return;
    try { await api.heartbeat(taskId, agentId); }
    catch (err) { log.warn('heartbeat failed task=%s: %s', taskId, (err as Error).message); }
  }, intervalSec * 1000);
  return { stop() { active = false; clearInterval(timer); } };
}

function buildPrompt(task: Task, workspaceRoot: string): string {
  const instruction =
    (task.payload['instruction'] as string | undefined) ??
    task.title ??
    '(no instruction)';

  return `You are a Claude Code agent executing a UnionAgents task.

Task ID: ${task.id}
Task Type: ${task.task_type}
Working directory: ${workspaceRoot}

Instructions:
${instruction}

Rules:
- Work directly in the repository at ${workspaceRoot}.
- Do not ask questions — this is headless execution.
- Commit and push when complete.
- End with a concise summary of what was done.`;
}

function runClaude(
  prompt: string,
  cwd: string,
  outputPath: string,
): Promise<{ code: number | null; stdout: string; stderr: string }> {
  // Run claude in non-interactive print mode
  const args = ['--print', '--output-format', 'text', prompt];

  return new Promise(resolve => {
    const child = spawn('claude', args, {
      cwd,
      shell: false,
      windowsHide: true,
      env: { ...process.env },
      timeout: 1800_000, // 30 min max
    });

    let stdout = '';
    let stderr = '';
    child.stdout?.on('data', chunk => { stdout += chunk.toString(); });
    child.stderr?.on('data', chunk => { stderr += chunk.toString(); });
    child.on('close', code => {
      fs.writeFileSync(outputPath, stdout, 'utf-8');
      resolve({ code, stdout, stderr });
    });
    child.on('error', err => resolve({ code: -1, stdout, stderr: err.message }));
  });
}

export async function claudeCodeAgentSession(
  task: Task,
  agentId: string,
  cfg: AgentConfig,
  api: OrchestratorApi,
): Promise<void> {
  const log = makeLogger(`cc:${task.id.slice(0, 8)}`);
  const artifactsDir = path.join(cfg.workspaceRoot, '.ua-artifacts', task.id);
  const outputPath   = path.join(artifactsDir, 'output.md');

  log.info('start task_id=%s title=%s', task.id, task.title);

  try {
    fs.mkdirSync(artifactsDir, { recursive: true });
  } catch (err) {
    await api.fail(task.id, agentId, 'blocked_env',
      `Artifacts dir init failed: ${(err as Error).message}`);
    return;
  }

  const hb = startHeartbeat(api, task.id, agentId, cfg.heartbeatInterval);
  try {
    const prompt = buildPrompt(task, cfg.workspaceRoot);
    log.info('spawning claude --print in cwd=%s', cfg.workspaceRoot);

    const result = await runClaude(prompt, cfg.workspaceRoot, outputPath);

    if (result.code !== 0) {
      const detail = (result.stderr || result.stdout || `claude exited ${result.code}`).slice(0, 4000);
      log.error('claude exited %d: %s', result.code, detail.slice(0, 200));
      await api.fail(task.id, agentId, 'retryable', detail);
      return;
    }

    const summary = result.stdout.trim().slice(0, 8000) || 'Claude Code task completed.';
    log.info('claude finished, summary len=%d', summary.length);

    const executor = new ToolExecutor(cfg.workspaceRoot, task.id, cfg.orchestratorUrl, log);
    const acceptanceResult = await runAcceptanceCheck(
      task.acceptance_check as AcceptanceCheck | null,
      cfg.workspaceRoot,
      executor,
      log,
    );

    await api.complete(task.id, agentId, summary, [outputPath], acceptanceResult);
    log.info('done task_id=%s', task.id);
  } catch (err) {
    log.error('crashed task_id=%s: %s', task.id, (err as Error).message);
    await api.fail(task.id, agentId, 'retryable',
      `CC session crashed: ${(err as Error).message}`).catch(() => undefined);
  } finally {
    hb.stop();
  }
}
