export interface Logger {
  info(msg: string, ...args: unknown[]): void;
  warn(msg: string, ...args: unknown[]): void;
  error(msg: string, ...args: unknown[]): void;
}

export function makeLogger(prefix: string): Logger {
  const ts = () => new Date().toISOString();
  return {
    info:  (msg, ...a) => console.log (`${ts()} [${prefix}] INFO  ${msg}`, ...a),
    warn:  (msg, ...a) => console.warn(`${ts()} [${prefix}] WARN  ${msg}`, ...a),
    error: (msg, ...a) => console.error(`${ts()} [${prefix}] ERROR ${msg}`, ...a),
  };
}
