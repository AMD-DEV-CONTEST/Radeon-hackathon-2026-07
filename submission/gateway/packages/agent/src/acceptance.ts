import * as fs from 'fs';
import * as path from 'path';
import { ToolExecutor } from './toolexec';
import type { Logger } from './logger';

export type AcceptanceResult = 'pass' | 'fail' | 'needs_review';

export interface AcceptanceCheck {
  type: 'command' | 'file_exists' | 'manual';
  command?: string | string[];
  cwd?: string;
  expected_exit_code?: number;
  timeout_seconds?: number;
  paths?: string[];
  mode?: 'all' | 'any';
}

/**
 * Run the acceptance check using the ToolExecutor so all commands stay within
 * the workspace jail and inherit the same env isolation as agent tool calls.
 */
export async function runAcceptanceCheck(
  check: AcceptanceCheck | null | undefined,
  workspaceRoot: string,
  executor: ToolExecutor,
  log: Logger,
): Promise<AcceptanceResult> {
  if (!check || !check.type) {
    log.warn('acceptance_check missing or has no type — defaulting to needs_review');
    return 'needs_review';
  }

  switch (check.type) {
    case 'manual':
      log.info('acceptance type=manual → needs_review');
      return 'needs_review';

    case 'command': {
      const cmd = check.command;
      if (!cmd) {
        log.warn('acceptance type=command but no command specified');
        return 'fail';
      }
      const commandStr = Array.isArray(cmd) ? cmd.join(' ') : cmd;
      const expected = check.expected_exit_code ?? 0;
      const result = await executor.execute('run_command', {
        command: commandStr,
        cwd: check.cwd ?? '.',
        timeout: check.timeout_seconds ?? 120,
      });
      // error field is set only when command exits non-zero
      const exitedNonZero = !!result.error;
      const passed = expected === 0 ? !exitedNonZero : exitedNonZero;
      log.info('acceptance type=command cmd=%s expected_exit=%d result=%s', commandStr, expected, passed ? 'pass' : 'fail');
      return passed ? 'pass' : 'fail';
    }

    case 'file_exists': {
      const paths = check.paths ?? [];
      const mode = check.mode ?? 'all';
      const results = paths.map(p => {
        const abs = path.isAbsolute(p) ? p : path.join(workspaceRoot, p);
        return fs.existsSync(abs);
      });
      const passed = mode === 'any' ? results.some(Boolean) : results.every(Boolean);
      log.info('acceptance type=file_exists mode=%s result=%s', mode, passed ? 'pass' : 'fail');
      return passed ? 'pass' : 'fail';
    }

    default:
      log.warn('acceptance unknown type=%s', (check as AcceptanceCheck).type);
      return 'needs_review';
  }
}
