import * as fs from 'fs';
import * as path from 'path';
import { execSync } from 'child_process';
import { AgentConfig } from './config';
import { OrchestratorApi, Task } from './api';
import { DeepSeekClient, Message, parseFinish, parseBlock } from './deepseek';
import { ToolExecutor } from './toolexec';
import { SecurityError } from './security';
import { runAcceptanceCheck, AcceptanceCheck } from './acceptance';
import { ToolName } from './tools';
import { makeLogger } from './logger';

function loadSkill(skillPath: string): string {
  if (!skillPath) return '';
  try {
    const raw = fs.readFileSync(skillPath, 'utf-8');
    // Strip YAML frontmatter (--- ... ---) from SKILL.md
    const stripped = raw.replace(/^---[\s\S]*?---\n/, '');
    return `\n\n## LOADED SKILL\n\n${stripped.trim()}`;
  } catch {
    return '';
  }
}

const STAGE_PROMPTS: Record<string, string> = {
  '论证': '你是论证者。对提案给出署名意见，包括：同意/反对、理由、风险。格式：签署方 + 结论 + 论据。完成后输出 <<<FINISH>>>。',
  '决策': '你是决策者。综合各方意见，做出最终裁决。署名并给出理由。完成后输出 <<<FINISH>>>。',
  '实施': '你是实施者。按行动计划执行任务，完成后输出 <<<FINISH>>>。',
};

function buildSystemPrompt(task: Task, workspacePath: string, cfg: AgentConfig, stage?: string): string {
  const instruction =
    (task.payload['instruction'] as string | undefined) ??
    task.title ??
    '(no instruction)';

  const skillBlock = loadSkill(cfg.skill);
  const stageBlock = stage && STAGE_PROMPTS[stage]
    ? `\n\n—— STAGE ROLE ——\n\nStage: ${stage}\n${STAGE_PROMPTS[stage]}`
    : '';

  return `You are a Reasonix coding agent executing a UnionAgents task.

Task ID: ${task.id}
Task Type: ${task.task_type}
Workspace: ${workspacePath}

User's instruction:
${instruction}

—— OUTPUT CONVENTIONS ——

When you have completed the task, output EXACTLY:

<<<FINISH>>>
summary: <one paragraph describing what was done>
artifacts: <comma-separated relative paths to output files>

When you are blocked (auth failure, rate limit, missing dependency, permission denied), output EXACTLY:

<<<BLOCK>>>
type: blocked_auth | blocked_rate_limit | blocked_env | blocked_permission
message: <human-readable explanation>
blocked_until: <ISO8601 timestamp, ONLY for blocked_rate_limit>

—— RULES ——

- All file operations MUST stay within the workspace directory.
- Destructive operations (rm -rf, git push --force, DROP TABLE) are forbidden.
- Do NOT ask the user questions — this is a headless execution.
- Use ${cfg.model || 'deepseek-chat'}. Quality over speed.
- Start by exploring the workspace with list_dir and read_file before making changes.${stageBlock}${skillBlock}`;
}

function initWorkspace(task: Task, workspacePath: string, artifactsPath: string): void {
  fs.mkdirSync(workspacePath, { recursive: true });
  fs.mkdirSync(artifactsPath, { recursive: true });

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
      execSync(`git clone "${url}" "${workspacePath}"`, { timeout: 120_000, stdio: 'pipe' });
    }
  } else if (mode === 'git-worktree') {
    // git-worktree: workspace dir is pre-populated by the caller;
    // just verify it exists and is a git repository.
    const gitDir = path.join(workspacePath, '.git');
    if (!fs.existsSync(gitDir)) {
      throw new Error(`git-worktree mode: workspace ${workspacePath} is not a git repository`);
    }
  }
}

function artifactUriFromPath(workspacePath: string, artifactPath: string): string {
  if (/^[a-z]+:\/\//i.test(artifactPath)) return artifactPath;
  const abs = path.isAbsolute(artifactPath)
    ? artifactPath
    : path.join(workspacePath, artifactPath);
  return `file://${abs.replace(/\\/g, '/')}`;
}

function guessArtifactType(artifactPath: string): 'patch' | 'log' | 'test_result' | 'screenshot' | 'report' | 'workspace_snapshot' | 'other' {
  const lower = artifactPath.toLowerCase();
  if (lower.endsWith('.patch') || lower.endsWith('.diff')) return 'patch';
  if (lower.endsWith('.log') || lower.endsWith('.txt')) return 'log';
  if (lower.endsWith('.png') || lower.endsWith('.jpg') || lower.endsWith('.jpeg') || lower.endsWith('.webp')) return 'screenshot';
  if (lower.endsWith('.json') || lower.endsWith('.xml') || lower.includes('test')) return 'test_result';
  if (lower.endsWith('.md') || lower.endsWith('.pdf') || lower.endsWith('.docx')) return 'report';
  if (lower.endsWith('.zip') || lower.endsWith('.tar') || lower.endsWith('.tar.gz')) return 'workspace_snapshot';
  return 'other';
}

async function registerArtifacts(
  api: OrchestratorApi,
  task: Task,
  artifacts: string[],
  workspacePath: string,
  log: ReturnType<typeof makeLogger>,
): Promise<string[]> {
  const uris = artifacts.map(artifact => artifactUriFromPath(workspacePath, artifact));
  for (let i = 0; i < artifacts.length; i++) {
    const artifact = artifacts[i];
    const uri = uris[i];
    try {
      await api.createArtifact(task.id, guessArtifactType(artifact), uri, {
        source: 'agent_finish_signal',
        original_path: artifact,
      });
      log.info('artifact registered uri=%s', uri);
    } catch (err) {
      log.warn('artifact registration failed uri=%s: %s', uri, (err as Error).message);
    }
  }
  return uris;
}

interface HeartbeatHandle { stop(): void }

function startHeartbeat(
  api: OrchestratorApi,
  taskId: string,
  agentId: string,
  intervalSec: number,
): HeartbeatHandle {
  const log = makeLogger('hb');
  let active = true;
  const timer = setInterval(async () => {
    if (!active) return;
    try { await api.heartbeat(taskId, agentId); }
    catch (err) { log.warn('heartbeat failed task=%s: %s', taskId, (err as Error).message); }
  }, intervalSec * 1000);
  return { stop() { active = false; clearInterval(timer); } };
}

export async function agentSession(
  task: Task,
  agentId: string,
  cfg: AgentConfig,
  api: OrchestratorApi,
  stage?: string,
): Promise<void> {
  const log = makeLogger(`session:${task.id.slice(0, 8)}`);
  const sessionRoot   = path.join(cfg.workspaceRoot, task.id);
  const workspacePath = path.join(sessionRoot, 'workspace');
  const artifactsPath = path.join(sessionRoot, 'artifacts');

  log.info('start task_id=%s title=%s', task.id, task.title);

  try { initWorkspace(task, workspacePath, artifactsPath); }
  catch (err) {
    log.error('workspace init failed: %s', (err as Error).message);
    await api.fail(task.id, agentId, 'blocked_env',
      `Workspace init failed: ${(err as Error).message}`);
    return;
  }

  const hb       = startHeartbeat(api, task.id, agentId, cfg.heartbeatInterval);
  const executor = new ToolExecutor(cfg.workspaceRoot, task.id, cfg.orchestratorUrl, log);
  const client   = new DeepSeekClient(cfg);

  const messages: Message[] = [
    { role: 'system', content: buildSystemPrompt(task, workspacePath, cfg, stage) },
    { role: 'user',   content: 'Begin executing the task.' },
  ];

  let consecutiveTextTurns = 0;
  let finalSummary   = '';
  let finalArtifacts: string[] = [];
  let done = false;

  try {
    for (let turn = 1; turn <= cfg.maxTurnsPerTask; turn++) {
      log.info('turn=%d/%d', turn, cfg.maxTurnsPerTask);

      const resp = await client.chat(messages);
      const msg  = resp.message;
      messages.push(msg);
      const content = msg.content ?? '';

      // ── Finish signal ────────────────────────────────────────────────────
      const finish = parseFinish(content);
      if (finish) {
        finalSummary   = finish.summary;
        finalArtifacts = finish.artifacts;
        done = true;
        log.info('FINISH turn=%d summary=%s', turn, finalSummary.slice(0, 80));
        break;
      }

      // ── Block signal ─────────────────────────────────────────────────────
      const block = parseBlock(content);
      if (block) {
        log.warn('BLOCK type=%s msg=%s', block.type, block.message);
        await api.fail(task.id, agentId, block.type, block.message, block.blocked_until);
        return;
      }

      // ── Tool calls ───────────────────────────────────────────────────────
      if (msg.tool_calls && msg.tool_calls.length > 0) {
        consecutiveTextTurns = 0;
        for (const tc of msg.tool_calls) {
          let resultContent: string;
          try {
            const args = JSON.parse(tc.function.arguments) as Record<string, unknown>;
            const res  = await executor.execute(tc.function.name as ToolName, args);
            resultContent = res.error ? `ERROR: ${res.error}\n${res.output}` : res.output;
          } catch (err) {
            if (err instanceof SecurityError) {
              await api.fail(task.id, agentId, 'blocked_permission',
                (err as SecurityError).message);
              return;
            }
            resultContent = `TOOL ERROR: ${(err as Error).message}`;
          }
          messages.push({ role: 'tool', tool_call_id: tc.id, content: resultContent });
        }
        continue;
      }

      // ── Plain text (no tool calls, no signal) ────────────────────────────
      consecutiveTextTurns++;
      log.warn('plain text turn=%d consecutive=%d', turn, consecutiveTextTurns);
      if (consecutiveTextTurns >= 3) {
        await api.fail(task.id, agentId, 'retryable',
          'Agent stalled: no tool calls for 3 consecutive turns');
        return;
      }
    }

    if (!done) {
      await api.fail(task.id, agentId, 'retryable',
        `Reached max_turns (${cfg.maxTurnsPerTask}) without completing task`);
      return;
    }

    // ── Acceptance check ─────────────────────────────────────────────────
    const acceptResult = await runAcceptanceCheck(
      task.acceptance_check as AcceptanceCheck | null,
      workspacePath, executor, log,
    );
    log.info('acceptance_result=%s', acceptResult);

    const artifactUris = await registerArtifacts(api, task, finalArtifacts, workspacePath, log);
    await api.complete(task.id, agentId, finalSummary, artifactUris, acceptResult);
    log.info('done task_id=%s', task.id);

  } catch (err) {
    log.error('crashed task_id=%s: %s', task.id, (err as Error).message);
    await api.fail(task.id, agentId, 'retryable',
      `Session crashed: ${(err as Error).message}`).catch(() => undefined);
  } finally {
    hb.stop();
  }
}
