import * as fs from 'fs';
import * as path from 'path';
import { execSync } from 'child_process';
import { assertPathInJail, assertCommandSafe, buildSafeEnv, SecurityError } from './security';
import { ToolName } from './tools';
import type { Logger } from './logger';

export type ToolArgs = Record<string, unknown>;
export type ToolResult = { output: string; error?: string };

export class ToolExecutor {
  constructor(
    private readonly workspaceRoot: string,
    private readonly taskId: string,
    private readonly orchestratorUrl: string,
    private readonly log: Logger,
  ) {}

  async execute(name: ToolName, args: ToolArgs): Promise<ToolResult> {
    try {
      switch (name) {
        case 'read_file':    return this.readFile(args['path'] as string);
        case 'write_file':   return this.writeFile(args['path'] as string, args['content'] as string);
        case 'edit_file':    return this.editFile(args['path'] as string, args['old_str'] as string, args['new_str'] as string);
        case 'delete_file':  return this.deleteFile(args['path'] as string);
        case 'list_dir':     return this.listDir((args['path'] as string | undefined) ?? '.');
        case 'run_command':  return this.runCommand(args['command'] as string, args['cwd'] as string | undefined, args['timeout'] as number | undefined);
        case 'search_files': return this.searchFiles(args['pattern'] as string, (args['path'] as string | undefined) ?? '.');
        case 'create_dir':   return this.createDir(args['path'] as string);
        default: return { output: '', error: `Unknown tool: ${name as string}` };
      }
    } catch (err) {
      if (err instanceof SecurityError) {
        this.log.warn('security block tool=%s: %s', name, (err as Error).message);
        throw err;
      }
      const msg = err instanceof Error ? err.message : String(err);
      this.log.error('tool error tool=%s: %s', name, msg);
      return { output: '', error: msg };
    }
  }

  private resolve(rel: string): string {
    const abs = path.isAbsolute(rel) ? rel : path.join(this.workspaceRoot, rel);
    return assertPathInJail(abs, this.workspaceRoot);
  }

  private readFile(relPath: string): ToolResult {
    const abs = this.resolve(relPath);
    if (!fs.existsSync(abs)) return { output: '', error: `File not found: ${relPath}` };
    const content = fs.readFileSync(abs, 'utf-8');
    return { output: content };
  }

  private writeFile(relPath: string, content: string): ToolResult {
    const abs = this.resolve(relPath);
    fs.mkdirSync(path.dirname(abs), { recursive: true });
    fs.writeFileSync(abs, content, 'utf-8');
    return { output: `Written: ${relPath}` };
  }

  private editFile(relPath: string, oldStr: string, newStr: string): ToolResult {
    const abs = this.resolve(relPath);
    if (!fs.existsSync(abs)) return { output: '', error: `File not found: ${relPath}` };
    const original = fs.readFileSync(abs, 'utf-8');
    const count = original.split(oldStr).length - 1;
    if (count === 0) return { output: '', error: `old_str not found in ${relPath}` };
    if (count > 1)   return { output: '', error: `old_str is ambiguous (${count} occurrences) in ${relPath}` };
    fs.writeFileSync(abs, original.replace(oldStr, newStr), 'utf-8');
    return { output: `Edited: ${relPath}` };
  }

  private deleteFile(relPath: string): ToolResult {
    const abs = this.resolve(relPath);
    if (!fs.existsSync(abs)) return { output: '', error: `File not found: ${relPath}` };
    fs.unlinkSync(abs);
    return { output: `Deleted: ${relPath}` };
  }

  private listDir(relPath: string): ToolResult {
    const abs = this.resolve(relPath);
    if (!fs.existsSync(abs)) return { output: '', error: `Directory not found: ${relPath}` };
    const entries = fs.readdirSync(abs, { withFileTypes: true });
    const lines = entries.map(e => `${e.isDirectory() ? '[dir] ' : '      '}${e.name}`);
    return { output: lines.join('\n') || '(empty directory)' };
  }

  private runCommand(command: string, relCwd?: string, timeoutSec?: number): ToolResult {
    assertCommandSafe(command);

    const cwd = relCwd ? this.resolve(relCwd) : this.workspaceRoot;
    const timeoutMs = Math.min((timeoutSec ?? 120) * 1000, 600_000);
    const env = buildSafeEnv({
      REASONIX_TASK_ID: this.taskId,
      REASONIX_WORKSPACE: this.workspaceRoot,
      REASONIX_ORCHESTRATOR_URL: this.orchestratorUrl,
    });

    try {
      const output = execSync(command, {
        cwd,
        env,
        timeout: timeoutMs,
        encoding: 'utf-8',
        stdio: ['pipe', 'pipe', 'pipe'],
        shell: process.platform === 'win32' ? (process.env.ComSpec || 'cmd.exe') : '/bin/bash',
      });
      return { output: typeof output === 'string' ? output : '' };
    } catch (err: unknown) {
      const e = err as { stdout?: string; stderr?: string; message?: string };
      const combined = [e.stdout, e.stderr, e.message].filter(Boolean).join('\n');
      return { output: combined, error: 'Command exited with non-zero status' };
    }
  }

  private async searchFiles(pattern: string, relRoot: string): Promise<ToolResult> {
    const absRoot = this.resolve(relRoot);
    const matches: string[] = [];
    // Use manual recursive walk instead of fs/promises.glob for Node 18 compat
    const walk = (dir: string) => {
      if (matches.length >= 200) return;
      let entries: fs.Dirent[];
      try { entries = fs.readdirSync(dir, { withFileTypes: true }); }
      catch { return; }
      for (const entry of entries) {
        if (matches.length >= 200) break;
        const full = path.join(dir, entry.name);
        if (entry.isDirectory()) { walk(full); }
        else {
          const rel = path.relative(absRoot, full);
          if (minimatch(rel, pattern)) matches.push(rel);
        }
      }
    };
    walk(absRoot);
    if (matches.length >= 200) matches.push('... (truncated at 200)');
    return { output: matches.join('\n') || '(no matches)' };
  }

  private createDir(relPath: string): ToolResult {
    const abs = this.resolve(relPath);
    fs.mkdirSync(abs, { recursive: true });
    return { output: `Created: ${relPath}` };
  }
}

// Minimal glob matching for search_files (avoids external deps)
function minimatch(str: string, pattern: string): boolean {
  const regex = new RegExp(
    '^' +
    pattern
      .replace(/\./g, '\\.')
      .replace(/\*\*\//g, '(?:.+/)?')
      .replace(/\*\*/g, '.*')
      .replace(/\*/g, '[^/]*')
      .replace(/\?/g, '[^/]') +
    '$',
  );
  return regex.test(str.replace(/\\/g, '/'));
}
