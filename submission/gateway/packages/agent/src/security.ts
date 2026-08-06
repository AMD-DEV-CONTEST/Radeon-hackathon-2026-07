import * as path from 'path';

export class SecurityError extends Error {
  constructor(msg: string) {
    super(msg);
    this.name = 'SecurityError';
  }
}

// Commands that may cause irreversible damage and must be blocked
const HIGH_RISK_PATTERNS: RegExp[] = [
  /\brm\s+-[a-z]*f[a-z]*r[a-z]*\b/i,
  /\brm\s+-[a-z]*r[a-z]*f[a-z]*\b/i,
  /\bgit\s+push\b.*--force\b/i,
  /\bgit\s+push\b.*-f\b/i,
  /\bDROP\s+TABLE\b/i,
  /\bDROP\s+DATABASE\b/i,
  /\bDELETE\s+FROM\b/i,
  /\bTRUNCATE\s+TABLE\b/i,
  /\bchmod\s+777\b/i,
  /\bformat\s+[a-zA-Z]:\\/i,
  /\bdiskpart\b/i,
  /\bmkfs\b/i,
  /\bdd\s+if=/i,
];

/**
 * Verify that `requestedPath` resolves to within `workspaceJail`.
 * Throws SecurityError on path-traversal attempts.
 */
export function assertPathInJail(requestedPath: string, workspaceJail: string): string {
  const resolved = path.resolve(requestedPath);
  const jail = path.resolve(workspaceJail);
  const jailWithSep = jail.endsWith(path.sep) ? jail : jail + path.sep;
  if (resolved !== jail && !resolved.startsWith(jailWithSep)) {
    throw new SecurityError(
      `Path jail violation: "${requestedPath}" → "${resolved}" is outside workspace "${jail}"`,
    );
  }
  return resolved;
}

/**
 * Check command against high-risk pattern list.
 * Throws SecurityError if the command matches.
 */
export function assertCommandSafe(command: string): void {
  for (const pattern of HIGH_RISK_PATTERNS) {
    if (pattern.test(command)) {
      throw new SecurityError(`High-risk command blocked: "${command.slice(0, 120)}"`);
    }
  }
}

/**
 * Build a sanitised environment for a child process.
 * Only exposes safe variables; strips API keys, DB URLs, secrets.
 */
export function buildSafeEnv(overrides: Record<string, string>): Record<string, string> {
  const base: Record<string, string> = {
    PATH: process.env['PATH'] ?? '/usr/local/bin:/usr/bin:/bin',
  };
  // Preserve locale / terminal / OS variables that build tools need
  for (const key of ['HOME', 'USERPROFILE', 'TEMP', 'TMP', 'APPDATA',
                      'LANG', 'LC_ALL', 'TERM', 'COMSPEC', 'SystemRoot',
                      'SystemDrive', 'WINDIR']) {
    const val = process.env[key];
    if (val !== undefined) base[key] = val;
  }
  return { ...base, ...overrides };
}
