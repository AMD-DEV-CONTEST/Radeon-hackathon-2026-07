import { spawn } from 'child_process';
import { OrchestratorApi, Task } from './api';

// ─── Agent control signal parsers ────────────────────────────────────────────

interface FinishSignal {
  summary: string;
  artifacts: string[];
}

interface BlockSignal {
  type: 'blocked_auth' | 'blocked_rate_limit' | 'blocked_env' | 'blocked_permission';
  message: string;
  blocked_until?: string;
}

const FINISH_RE = /<<<FINISH>>>\s*\nsummary:\s*([\s\S]+?)(?:\nartifacts:\s*([\s\S]+?))?(?:\n<<<|$)/;
const BLOCK_RE  = /<<<BLOCK>>>\s*\ntype:\s*(\S+)\s*\nmessage:\s*([\s\S]+?)(?:\nblocked_until:\s*(\S+))?(?:\n<<<|$)/;

function parseFinish(text: string): FinishSignal | null {
  const m = FINISH_RE.exec(text);
  if (!m) return null;
  const artifacts = (m[2] ?? '').split(',').map(s => s.trim()).filter(Boolean);
  return { summary: (m[1] ?? '').trim(), artifacts };
}

function parseBlock(text: string): BlockSignal | null {
  const m = BLOCK_RE.exec(text);
  if (!m) return null;
  return {
    type: (m[1] ?? 'blocked_env').trim() as BlockSignal['type'],
    message: (m[2] ?? '').trim(),
    blocked_until: m[3]?.trim(),
  };
}

// ─── Acceptance check helpers ────────────────────────────────────────────────

/**
 * Determine the acceptance result based on the task's acceptance_check config.
 *
 * claude_code agents are trust-based: by default we submit 'pass'.
 * If the task explicitly requires manual review (acceptance_check.type === 'manual'),
 * we submit 'needs_review' so the orchestrator surfaces it for human inspection.
 *
 * The orchestrator also validates artifacts server-side (required_artifact_paths,
 * sha256 policy) and can override acceptance_result from pass to needs_review
 * if artifacts are missing — so we don't need to duplicate that logic here.
 */
function determineAcceptanceResult(task: Task): string {
  const check = task.acceptance_check as Record<string, unknown> | null | undefined;
  if (!check || !check['type']) {
    return 'pass';
  }
  const checkType = String(check['type']).toLowerCase().trim();
  if (checkType === 'manual') {
    return 'needs_review';
  }
  // For command/file_exists checks, claude_code trusts the agent's attestation.
  // The orchestrator can re-validate server-side if needed.
  return 'pass';
}

export async function runSession(
  task: Task,
  agentId: string,
  api: OrchestratorApi,
  heartbeatSec: number,
  timeoutSec: number,
): Promise<void> {
  const tag = `[cc-agent:${task.id.slice(0, 8)}]`;
  console.log(`${tag} start title="${task.title}" type=${task.task_type} attempt=${task.attempt_no}`);

  let hbActive = true;
  const hbTimer = setInterval(async () => {
    if (!hbActive) return;
    try { await api.heartbeat(task.id, agentId); }
    catch { /* ignore */ }
  }, heartbeatSec * 1000);

  const stopHeartbeat = () => { hbActive = false; clearInterval(hbTimer); };

  try {
    const prompt = buildPrompt(task);
    const { summary, artifacts } = await executeWithClaude(prompt, timeoutSec, tag);

    // Determine acceptance result based on task config
    const acceptanceResult = determineAcceptanceResult(task);
    console.log(`${tag} acceptance_result=${acceptanceResult}`);

    await api.complete(task.id, agentId, summary, artifacts, acceptanceResult);
    console.log(`${tag} done summary="${summary.slice(0, 80)}"`);
  } catch (err) {
    const msg = (err as Error).message;
    console.error(`${tag} failed: ${msg}`);

    // Check if the error is a block signal
    const block = parseBlock(msg);
    if (block) {
      await api.fail(task.id, agentId, block.type, block.message).catch(() => undefined);
    } else {
      await api.fail(task.id, agentId, 'retryable', msg).catch(() => undefined);
    }
  } finally {
    stopHeartbeat();
  }
}

function buildPrompt(task: Task): string {
  const instruction =
    (task.payload['instruction'] as string | undefined) ??
    (task.payload['description'] as string | undefined) ??
    task.title;

  const files = task.payload['files'] as Record<string, string> | undefined;

  // Build the standard output conventions prompt that aligns with orchestrator expectations
  const outputConventions = `
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

- All file operations MUST stay within the task workspace directory.
- Destructive operations (rm -rf, git push --force, DROP TABLE) are forbidden.
- Do NOT ask the user questions — this is a headless execution.
- Start by exploring the workspace with list_dir and read_file before making changes.`;

  const taskHeader = `Task ID: ${task.id}\nTask Type: ${task.task_type}\nAttempt: ${task.attempt_no}\n\nUser's instruction:\n${instruction}`;

  if (files && Object.keys(files).length > 0) {
    const fileCtx = Object.entries(files)
      .map(([name, content]) => `=== ${name} ===\n${content}`)
      .join('\n\n');
    return `${taskHeader}\n\n${fileCtx}\n\n---\n\n${outputConventions}`;
  }

  return `${taskHeader}\n\n${outputConventions}`;
}

interface ClaudeResult { summary: string; artifacts: string[] }

function executeWithClaude(prompt: string, timeoutSec: number, tag: string): Promise<ClaudeResult> {
  return new Promise((resolve, reject) => {
    const proc = spawn('claude', ['-p', prompt, '--output-format', 'stream-json', '--verbose'], {
      stdio: ['ignore', 'pipe', 'pipe'],
    });

    let stdout = '';
    let stderr = '';
    let timedOut = false;

    const timer = setTimeout(() => {
      timedOut = true;
      proc.kill();
    }, timeoutSec * 1000);

    proc.stdout.on('data', (chunk: Buffer) => { stdout += chunk.toString(); });
    proc.stderr.on('data', (chunk: Buffer) => { stderr += chunk.toString(); });

    proc.on('close', (code) => {
      clearTimeout(timer);
      if (timedOut) {
        reject(new Error(`claude CLI timed out after ${timeoutSec}s`));
        return;
      }

      // First, try to parse FINISH/BLOCK signals from the full output
      const fullOutput = stdout + '\n' + stderr;

      const finish = parseFinish(fullOutput);
      if (finish) {
        console.log(`${tag} parsed FINISH signal from claude output`);
        resolve({ summary: finish.summary, artifacts: finish.artifacts });
        return;
      }

      const block = parseBlock(fullOutput);
      if (block) {
        reject(new Error(`<<<BLOCK>>>\ntype: ${block.type}\nmessage: ${block.message}`));
        return;
      }

      if (code !== 0) {
        const detail = (stderr.trim() || stdout.trim() || `claude exited with code ${code}`).slice(0, 2000);
        reject(new Error(detail));
        return;
      }

      // Fallback: extract summary from stream JSON output
      const summary = extractSummary(stdout);
      console.log(`${tag} claude finished, extracted ${summary.length} chars`);
      resolve({ summary, artifacts: [] });
    });

    proc.on('error', (err) => {
      clearTimeout(timer);
      if ((err as NodeJS.ErrnoException).code === 'ENOENT') {
        reject(new Error('claude CLI not found in PATH — is Claude Code installed?'));
      } else {
        reject(err);
      }
    });
  });
}

function extractSummary(streamJsonOutput: string): string {
  const texts: string[] = [];

  for (const line of streamJsonOutput.split('\n')) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    try {
      const obj = JSON.parse(trimmed) as Record<string, unknown>;

      if (obj['type'] === 'result') {
        const r = obj['result'];
        if (typeof r === 'string' && r) return r;
      }

      if (obj['type'] === 'stream_event') {
        const ev = obj['event'] as Record<string, unknown> | undefined;
        if (ev?.['type'] === 'content_block_delta') {
          const delta = ev['delta'] as Record<string, unknown> | undefined;
          if (delta?.['type'] === 'text_delta' && typeof delta['text'] === 'string') {
            texts.push(delta['text'] as string);
          }
        }
      }
    } catch {
      // non-JSON line, skip
    }
  }

  return texts.join('').trim() || '(no output)';
}
