import path from "node:path";

export interface LdeaConfig {
  llmBaseUrl: string;
  llmApiKey: string;
  llmModel: string;
  root: string;
  cwd: string;
  maxToolRounds: number;
}

function env(name: string, fallback: string): string {
  const v = process.env[name];
  return v && v.trim() ? v.trim() : fallback;
}

export function loadConfig(overrides: Partial<LdeaConfig> = {}): LdeaConfig {
  return {
    llmBaseUrl: overrides.llmBaseUrl ?? env("LDEA_LLM_BASE_URL", "http://127.0.0.1:8000/v1"),
    llmApiKey: overrides.llmApiKey ?? env("LDEA_LLM_API_KEY", "local"),
    llmModel: overrides.llmModel ?? env("LDEA_LLM_MODEL", "qwen2.5-7b-instruct"),
    root: overrides.root ?? env("LDEA_ROOT", ".ldea"),
    cwd: path.resolve(overrides.cwd ?? env("LDEA_CWD", process.cwd())),
    maxToolRounds: overrides.maxToolRounds ?? Number(env("LDEA_MAX_TOOL_ROUNDS", "8")),
  };
}
