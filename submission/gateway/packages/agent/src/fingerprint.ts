import { execSync } from 'child_process';
import * as os from 'os';

export interface Fingerprint {
  os: string;
  shell: string;
  python_version: string;
  available_commands: string[];
  tools: string[];
  workspace_root: string;
}

function tryExec(cmd: string): string | null {
  try {
    return execSync(cmd, { timeout: 4000, stdio: 'pipe' }).toString().trim();
  } catch {
    return null;
  }
}

function commandExists(cmd: string): boolean {
  return tryExec(`${cmd} --version`) !== null;
}

export function collectFingerprint(workspaceRoot: string): Fingerprint {
  const platform = os.platform();
  const shell = platform === 'win32' ? 'powershell' : 'bash';

  const pythonVersion =
    tryExec('python --version') ??
    tryExec('python3 --version') ??
    'unknown';

  const candidates = ['git', 'node', 'npm', 'pnpm', 'python', 'python3',
                       'pip', 'pip3', 'curl', 'wget', 'tsc', 'deno'];
  const availableCommands = candidates.filter(commandExists);

  // Tools this agent exposes to the LLM via function calling
  const tools = [
    'read_file', 'write_file', 'edit_file', 'delete_file',
    'list_dir', 'run_command', 'search_files', 'create_dir',
  ];

  const osMap: Record<string, string> = {
    win32: 'windows',
    linux: 'linux',
    darwin: 'darwin',
  };

  return {
    os: osMap[platform] || 'unknown',
    shell,
    python_version: pythonVersion,
    available_commands: availableCommands,
    tools,
    workspace_root: workspaceRoot,
  };
}
