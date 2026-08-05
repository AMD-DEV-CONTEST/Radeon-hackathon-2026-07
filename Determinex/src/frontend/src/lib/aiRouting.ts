export type ApiKeyStatus = Record<string, boolean | undefined>;

export type AiRouteOption = {
  id: string;
  label: string;
  provider: string;
  providerLabel: string;
  kind: "auto" | "local" | "free_cloud" | "cloud";
  note: string;
};

export const LOCAL_ROUTE_OPTIONS: AiRouteOption[] = [
  {
    id: "auto",
    label: "Auto router",
    provider: "local",
    providerLabel: "Determinex",
    kind: "auto",
    note: "Use the saved role slots",
  },
  {
    id: "local/fast",
    label: "Local fast",
    provider: "local",
    providerLabel: "Ollama",
    kind: "local",
    note: "qwen2.5-coder fast route",
  },
  {
    id: "determinex/planner",
    label: "Planner",
    provider: "local",
    providerLabel: "Ollama",
    kind: "local",
    note: "local planning alias",
  },
  {
    id: "determinex/engineer",
    label: "Engineer",
    provider: "local",
    providerLabel: "Ollama",
    kind: "local",
    note: "local build alias",
  },
  {
    id: "determinex/observer",
    label: "Observer",
    provider: "local",
    providerLabel: "Ollama",
    kind: "local",
    note: "local monitor alias",
  },
];

export const FREE_CLOUD_ROUTE_OPTIONS: AiRouteOption[] = [
  {
    id: "free/qwen3-coder",
    label: "Qwen3 Coder 480B",
    provider: "openrouter",
    providerLabel: "OpenRouter",
    kind: "free_cloud",
    note: "free tier, coding",
  },
  {
    id: "free/nemotron-ultra",
    label: "NVIDIA Nemotron Ultra 550B",
    provider: "openrouter",
    providerLabel: "OpenRouter",
    kind: "free_cloud",
    note: "free tier, reasoning",
  },
  {
    id: "free/gpt-oss-120b",
    label: "OpenAI OSS 120B",
    provider: "openrouter",
    providerLabel: "OpenRouter",
    kind: "free_cloud",
    note: "free tier, 131K ctx",
  },
  {
    id: "free/llama-3.3-70b",
    label: "Llama 3.3 70B",
    provider: "openrouter",
    providerLabel: "OpenRouter",
    kind: "free_cloud",
    note: "free tier, reviewer",
  },
  {
    id: "free/gemma-4-31b",
    label: "Google Gemma 4 31B",
    provider: "openrouter",
    providerLabel: "OpenRouter",
    kind: "free_cloud",
    note: "free tier, 262K ctx",
  },
  {
    id: "free/nemotron-super",
    label: "NVIDIA Nemotron Super 120B",
    provider: "openrouter",
    providerLabel: "OpenRouter",
    kind: "free_cloud",
    note: "free tier, 1M ctx",
  },
  {
    id: "free/cohere-code",
    label: "Cohere North Mini Code",
    provider: "openrouter",
    providerLabel: "OpenRouter",
    kind: "free_cloud",
    note: "free tier, code",
  },
];

export const CLOUD_ROUTE_OPTIONS: AiRouteOption[] = [
  {
    id: "cloud/claude-best",
    label: "Claude Opus 4.8",
    provider: "anthropic",
    providerLabel: "Anthropic",
    kind: "cloud",
    note: "quality route",
  },
  {
    id: "cloud/claude-mid",
    label: "Claude Sonnet 5",
    provider: "anthropic",
    providerLabel: "Anthropic",
    kind: "cloud",
    note: "balanced route",
  },
  {
    id: "cloud/claude-fast",
    label: "Claude Haiku 4.5",
    provider: "anthropic",
    providerLabel: "Anthropic",
    kind: "cloud",
    note: "fast route",
  },
  {
    id: "cloud/deepseek-chat",
    label: "DeepSeek V3",
    provider: "deepseek",
    providerLabel: "DeepSeek",
    kind: "cloud",
    note: "chat route",
  },
  {
    id: "cloud/deepseek-coder",
    label: "DeepSeek Coder",
    provider: "deepseek",
    providerLabel: "DeepSeek",
    kind: "cloud",
    note: "code route",
  },
  {
    id: "cloud/mistral-large",
    label: "Mistral Large",
    provider: "mistral",
    providerLabel: "Mistral",
    kind: "cloud",
    note: "general route",
  },
  {
    id: "cloud/groq-llama",
    label: "Groq LLaMA",
    provider: "groq",
    providerLabel: "Groq",
    kind: "cloud",
    note: "low-latency route",
  },
  {
    id: "cloud/gpt4o",
    label: "OpenAI / GPT-4o",
    provider: "openai",
    providerLabel: "OpenAI",
    kind: "cloud",
    note: "multimodal route",
  },
  {
    id: "cloud/gemini-flash",
    label: "Gemini Flash",
    provider: "gemini",
    providerLabel: "Google",
    kind: "cloud",
    note: "fast multimodal route",
  },
  {
    id: "cloud/kimi-k2",
    label: "Kimi K2",
    provider: "kimi",
    providerLabel: "Moonshot AI",
    kind: "cloud",
    note: "long-context route",
  },
];

export const AI_ROUTE_OPTIONS: AiRouteOption[] = [
  ...LOCAL_ROUTE_OPTIONS,
  ...FREE_CLOUD_ROUTE_OPTIONS,
  ...CLOUD_ROUTE_OPTIONS,
];

export function routeOptionById(id: string): AiRouteOption | undefined {
  return AI_ROUTE_OPTIONS.find((option) => option.id === id);
}

export function routeLabel(id: string): string {
  return routeOptionById(id)?.label ?? id;
}

export function routeRequiresKey(id: string): boolean {
  const option = routeOptionById(id);
  return option?.kind === "cloud" || option?.kind === "free_cloud";
}

export function routeKeyReady(id: string, keyStatus: ApiKeyStatus = {}): boolean {
  const option = routeOptionById(id);
  if (!option || option.kind === "auto" || option.kind === "local") return true;
  return keyStatus[option.provider] === true;
}

export function routeReadinessLabel(id: string, keyStatus: ApiKeyStatus = {}): string {
  if (!routeRequiresKey(id)) return "Local";
  return routeKeyReady(id, keyStatus) ? "Connected" : "Needs key";
}
