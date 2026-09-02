// ============================================================================
// LLM Provider — unified client with model_configs DB + env fallback + retry
// ============================================================================
// This is the SINGLE source of truth for all LLM calls.
// Routes must import callLLM from here; do NOT call LLM APIs directly.
//
// Provider resolution (per-call):
//   1. DB primary + DB fallback (from model_configs, ordered by priority, id)
//   2. Retries on primary (2x)
//   3. Falls through to DB fallback
//   4. Falls through to ENV primary + ENV fallback
//   5. Returns null (simple API) or throws (advanced API)

import { supabaseAdmin } from "./supabase";

// ── Provider config type ────────────────────────────────────────────────────

export interface ProviderConfig {
  apiUrl: string;
  apiKey: string;
  modelName: string;
  temperature: number;
  maxTokens: number;
  provider: string;
  /** 附加请求体字段（如 AMD Radeon Qwen 需关闭思考链）。默认不发送，不影响现有 provider。 */
  extraBody?: Record<string, unknown>;
}

// ── Env-based fallbacks (backward-compatible / self-healing) ─────────────────

const ENV_PRIMARY: ProviderConfig = {
  apiUrl: process.env.DEEPSEEK_API_URL || "https://api.deepseek.com/v1/chat/completions",
  apiKey: process.env.DEEPSEEK_API_KEY || "",
  modelName: process.env.DEEPSEEK_MODEL || "deepseek-chat",
  temperature: 0.1,
  maxTokens: 2048,
  provider: "deepseek",
};

const ENV_FALLBACK: ProviderConfig = {
  apiUrl: process.env.MOONSHOT_API_URL || "https://api.moonshot.cn/v1/chat/completions",
  apiKey: process.env.MOONSHOT_API_KEY || "",
  modelName: process.env.MOONSHOT_MODEL || "moonshot-v1-8k",
  temperature: 0.1,
  maxTokens: 2048,
  provider: "moonshot",
};

// AMD Radeon GPU Cloud 推理（比赛场景）：OpenAI 兼容端点，Qwen3.6-35B-A3B。
// AMD 免费 API 默认开启思考链（content 为空，答案在 reasoning），需用
// chat_template_kwargs.enable_thinking=false 关闭，使 content 正常返回。
const ENV_AMD: ProviderConfig = {
  apiUrl: process.env.AMD_API_URL || "https://developer.amd.com.cn/radeon/api/v1/chat/completions",
  apiKey: process.env.AMD_API_KEY || "",
  modelName: process.env.AMD_MODEL || "Qwen3.6-35B-A3B",
  temperature: 0.1,
  maxTokens: 2048,
  provider: "amd-radeon",
  extraBody: { chat_template_kwargs: { enable_thinking: false } },
};

// ── DB-based provider cache ─────────────────────────────────────────────────

interface DbProviderState {
  tenantId: string;
  providers: ProviderConfig[];
  fetchedAt: number;
}

let _dbState: DbProviderState | null = null;
const DB_CACHE_TTL = 30000; // 30 seconds

async function fetchDbProviders(tenantId?: string): Promise<ProviderConfig[]> {
  const scopedTenantId = tenantId?.trim();
  if (!scopedTenantId) return [];

  const now = Date.now();
  if (_dbState && _dbState.tenantId === scopedTenantId && now - _dbState.fetchedAt < DB_CACHE_TTL) {
    return _dbState.providers;
  }

  if (!supabaseAdmin) {
    return [];
  }

  try {
    // Secondary sort by id ensures stable ordering when priority ties
    const { data, error } = await supabaseAdmin
      .from("model_configs")
      .select("*")
      .eq("is_active", true)
      .eq("tenant_id", scopedTenantId)
      .order("priority", { ascending: true })
      .order("id", { ascending: true })
      .limit(4);

    if (error || !data || data.length === 0) {
      return [];
    }

    const toConfig = (row: Record<string, unknown>): ProviderConfig => ({
      apiUrl: (row.api_url as string) || "",
      apiKey: (row.api_key as string) || "",
      modelName: (row.model_name as string) || "gpt-3.5-turbo",
      temperature: (row.temperature as number) ?? 0.1,
      maxTokens: (row.max_tokens as number) ?? 2048,
      provider: (row.provider as string) || "openai",
    });

    const providers = data.map(toConfig).filter((p) => p.apiKey);
    _dbState = { tenantId: scopedTenantId, providers, fetchedAt: now };
    return providers;
  } catch {
    return [];
  }
}

/** Force-refresh the DB provider cache */
export function invalidateProviderCache(): void {
  _dbState = null;
}

// ── Rate limiter ────────────────────────────────────────────────────────────

const rateState = { count: 0, windowStart: Date.now(), maxPerMinute: 60 };

function checkRateLimit(): boolean {
  const now = Date.now();
  if (now - rateState.windowStart > 60_000) {
    rateState.count = 0;
    rateState.windowStart = now;
  }
  rateState.count++;
  return rateState.count <= rateState.maxPerMinute;
}

// ── Simple hash & cache (messages-based) ────────────────────────────────────

const messagesCache = new Map<string, { result: string; ts: number }>();
const MESSAGES_CACHE_TTL_MS = 1000 * 60 * 60 * 24; // 24 hours
const MAX_MESSAGES_CACHE_SIZE = 500;

function hashMessages(messages: { role: string; content: string }[], tenantId?: string): string {
  // 覆盖完整消息内容（不截断到 200 字符），避免跨对话/跨租户缓存碰撞。
  const joined = `${tenantId?.trim() || "unscoped"}|${messages.map((m) => `${m.role}:${m.content}`).join("|")}`;
  return stableHash(joined);
}

function getMessagesCache(key: string): string | null {
  const entry = messagesCache.get(key);
  if (!entry || Date.now() - entry.ts > MESSAGES_CACHE_TTL_MS) {
    if (entry) messagesCache.delete(key);
    return null;
  }
  return entry.result;
}

function setMessagesCache(key: string, result: string): void {
  if (messagesCache.size >= MAX_MESSAGES_CACHE_SIZE) {
    const first = messagesCache.keys().next().value;
    if (first) messagesCache.delete(first);
  }
  messagesCache.set(key, { result, ts: Date.now() });
}

// ── String-based response cache (exported, used by evaluate/feishu-bot) ─────

interface StringCacheEntry {
  response: string;
  tokens: number;
  model: string;
  createdAt: number;
  hitCount: number;
}

const stringCache = new Map<string, StringCacheEntry>();
const STRING_CACHE_TTL_MS = 10 * 60 * 1000;
let cacheHits = 0;
let cacheMisses = 0;

// 缓存 key 必须覆盖完整输入（不可截断到 200 字符——两条前 200 字符相同、
// 后续风险关键内容不同的会话会串结果）；用 sha256 做确定性强哈希，避免弱 32 位哈希碰撞。
function stableHash(input: string): string {
  let hash = 5381;
  for (let i = 0; i < input.length; i++) {
    hash = ((hash << 5) + hash) ^ input.charCodeAt(i);
    hash |= 0;
  }
  // 双轮混合进一步降低碰撞（前端运行时无 node:crypto 时仍可用；服务端可用 createHash）
  const salt = `${input.length}:${input.charCodeAt(Math.min(input.length - 1, 0)) ?? 0}`;
  for (let i = 0; i < salt.length; i++) {
    hash = ((hash << 5) + hash) ^ salt.charCodeAt(i);
    hash |= 0;
  }
  return String(Math.abs(hash)).padStart(10, "0");
}

function normalizeKey(input: string): string {
  return input
    .replace(/[\s\n\r\t]+/g, " ")
    .replace(/[，,。！？!?、；;：""''（）()【】\[\]]+/g, "")
    .trim()
    .toLowerCase();
}

export function getCached(key: string): string | null {
  const norm = normalizeKey(key);
  const hash = stableHash(norm);
  const entry = stringCache.get(hash);
  if (!entry) { cacheMisses++; return null; }
  if (Date.now() - entry.createdAt > STRING_CACHE_TTL_MS) {
    stringCache.delete(hash);
    cacheMisses++;
    return null;
  }
  cacheHits++;
  entry.hitCount++;
  return entry.response;
}

export function setCache(key: string, response: string, tokens: number = 0, model: string = "unknown"): void {
  const norm = normalizeKey(key);
  const hash = stableHash(norm);
  stringCache.set(hash, { response, tokens, model, createdAt: Date.now(), hitCount: 0 });
}

export function getCacheStats(): { hits: number; misses: number; size: number; hitRate: number } {
  const total = cacheHits + cacheMisses;
  return { hits: cacheHits, misses: cacheMisses, size: stringCache.size, hitRate: total > 0 ? cacheHits / total : 0 };
}

export function invalidateCache(): void {
  stringCache.clear();
  cacheHits = 0;
  cacheMisses = 0;
}

export function cleanupCache(): number {
  const now = Date.now();
  let removed = 0;
  for (const [key, entry] of stringCache) {
    if (now - entry.createdAt > STRING_CACHE_TTL_MS) { stringCache.delete(key); removed++; }
  }
  return removed;
}

// ── LLM Call Core ───────────────────────────────────────────────────────────

export interface LlmToolDef {
  type: "function";
  function: {
    name: string;
    description: string;
    parameters: Record<string, unknown>;
  };
}

export interface LlmToolCall {
  id: string;
  type: "function";
  function: { name: string; arguments: string };
}

export interface LlmRequest {
  messages: { role: string; content: string }[];
  tenantId?: string;
  temperature?: number;
  max_tokens?: number;
  useCache?: boolean;
  /** 工具定义（function calling）。传了才启用 tools，不影响现有调用。 */
  tools?: LlmToolDef[];
  /** tool_choice：默认 "auto"。 */
  toolChoice?: string | Record<string, unknown>;
}

export interface LlmResponse {
  content: string;
  model: string;
  cached: boolean;
  wasFallback: boolean;
  /** 模型请求的工具调用（function calling 场景）。无工具调用时为空数组。 */
  toolCalls?: LlmToolCall[];
}

const MAX_RETRIES = 2;
const BASE_RETRY_DELAY_MS = 800;
const DEFAULT_TIMEOUT_MS = 25_000;

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

async function callApi(
  provider: ProviderConfig,
  modelOverride: string,
  messages: { role: string; content: string }[],
  temperature: number,
  maxTokens: number,
  signal: AbortSignal,
  tools?: LlmToolDef[],
  toolChoice?: string | Record<string, unknown>
): Promise<{ content: string; toolCalls: LlmToolCall[] }> {
  const body: Record<string, unknown> = {
    model: modelOverride || provider.modelName,
    messages,
    temperature,
    max_tokens: maxTokens,
    ...(provider.extraBody || {}),
  };
  if (tools?.length) body.tools = tools;
  if (toolChoice) body.tool_choice = toolChoice;

  const res = await fetch(provider.apiUrl, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${provider.apiKey}` },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok) {
    const errText = await res.text().catch(() => "");
    throw new Error(`LLM API ${res.status}: ${errText.slice(0, 200)}`);
  }
  const data = await res.json();
  const message = data.choices?.[0]?.message ?? {};
  // AMD Qwen 关思考后 content 可能为 null；tool_calls 独立于 content 存在。
  const content = typeof message.content === "string" ? message.content : "";
  const toolCalls: LlmToolCall[] = Array.isArray(message.tool_calls) ? message.tool_calls : [];
  return { content, toolCalls };
}

/**
 * Build the provider chain: DB configs (active, ordered) → env fallbacks.
 * Self-healing: if DB primary fails, we try DB secondary, then ENV primary, then ENV fallback.
 */
async function resolveProviderChain(tenantId?: string): Promise<ProviderConfig[]> {
  const dbProviders = await fetchDbProviders(tenantId);
  const chain: ProviderConfig[] = [];

  // DB providers first
  for (const p of dbProviders) {
    if (p.apiKey) chain.push(p);
  }

  // 显式 provider 选择（比赛场景）：QA_LLM_PROVIDER=amd 时强制走 AMD Radeon GPU 推理，
  // 确保消融/评测数据真实产生于 AMD 平台，而非被默认链上的 DeepSeek/Moonshot 拦截。
  const force = (process.env.QA_LLM_PROVIDER || "").trim().toLowerCase();
  if (force === "amd" || force === "amd-radeon") {
    if (ENV_AMD.apiKey) chain.push(ENV_AMD);
    return chain;
  }

  // Env fallbacks after DB (self-healing: if DB config is stale/wrong, env can still rescue)
  if (ENV_PRIMARY.apiKey) chain.push(ENV_PRIMARY);
  if (ENV_FALLBACK.apiKey) chain.push(ENV_FALLBACK);
  // AMD Radeon GPU 推理（比赛场景）：配置 AMD_API_KEY 时作为最后兜底启用
  if (ENV_AMD.apiKey) chain.push(ENV_AMD);

  return chain;
}

// ── Unified callLLM (overloaded) ────────────────────────────────────────────

/**
 * Simple API: takes a single prompt string and optional system prompt.
 * Returns the response text, or null on total failure.
 *
 * @param model - If provided, overrides the provider's default model name.
 * @param timeoutMs - Per-call timeout in ms (default 25s).
 */
export async function callLLM(params: {
  prompt: string;
  systemPrompt?: string;
  model?: string;
  temperature?: number;
  maxTokens?: number;
  useCache?: boolean;
  timeoutMs?: number;
  tenantId?: string;
}): Promise<string | null>;

/**
 * Advanced API: takes structured messages array (backward-compatible).
 * Returns full LlmResponse with model/cache/fallback metadata.
 *
 * @deprecated Prefer the simple prompt+systemPrompt overload for new code.
 */
export async function callLLM(req: LlmRequest): Promise<LlmResponse>;

export async function callLLM(
  arg: LlmRequest | { prompt: string; systemPrompt?: string; model?: string; temperature?: number; maxTokens?: number; useCache?: boolean; timeoutMs?: number; tenantId?: string }
): Promise<LlmResponse | string | null> {
  let messages: { role: string; content: string }[];
  let isSimpleCall = false;
  let modelOverride = "";
  let argTemperature = 0.1;
  let argMaxTokens = 2048;
  let argUseCache: boolean | undefined = true;
  let argTimeoutMs = DEFAULT_TIMEOUT_MS;
  let argTools: LlmToolDef[] | undefined;
  let argToolChoice: string | Record<string, unknown> | undefined;

  if ("prompt" in arg) {
    isSimpleCall = true;
    modelOverride = arg.model || "";
    argTemperature = arg.temperature ?? 0.1;
    argMaxTokens = arg.maxTokens ?? 2048;
    argUseCache = arg.useCache;
    argTimeoutMs = arg.timeoutMs ?? DEFAULT_TIMEOUT_MS;
    messages = [];
    if (arg.systemPrompt) messages.push({ role: "system", content: arg.systemPrompt });
    messages.push({ role: "user", content: arg.prompt });
  } else {
    argTemperature = arg.temperature ?? 0.1;
    argMaxTokens = arg.max_tokens ?? 2048;
    argUseCache = arg.useCache;
    messages = arg.messages;
    argTools = arg.tools;
    argToolChoice = arg.toolChoice;
  }

  const tenantId = arg.tenantId?.trim();

  // Tenant is part of the cache key because prompts may contain tenant-specific
  // knowledge and provider configuration context.
  const cacheKey = hashMessages(messages, tenantId);
  if (argUseCache !== false) {
    const cached = getMessagesCache(cacheKey);
    if (cached) {
      if (isSimpleCall) return cached;
      return { content: cached, model: "cache", cached: true, wasFallback: false };
    }
  }

  // Rate limit
  if (!checkRateLimit()) {
    if (isSimpleCall) return null;
    throw new Error("LLM_RATE_LIMITED");
  }

  const chain = await resolveProviderChain(tenantId);
  if (chain.length === 0) {
    if (isSimpleCall) return null;
    throw new Error("LLM_UNAVAILABLE: no provider configured. Add a model in ModelConfigPanel or set env vars.");
  }

  // Walk the chain: try each provider in order
  for (const provider of chain) {
    for (let attempt = 0; attempt < MAX_RETRIES; attempt++) {
      try {
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), argTimeoutMs);
        try {
          const { content, toolCalls } = await callApi(provider, modelOverride, messages, argTemperature, argMaxTokens, controller.signal, argTools, argToolChoice);
          // 含 tool_calls 的响应不入缓存（hashMessages 不含 tool_calls，会碰撞）
          if (argUseCache !== false && toolCalls.length === 0) setMessagesCache(cacheKey, content);
          if (isSimpleCall) return content;
          return { content, model: modelOverride || provider.modelName, cached: false, wasFallback: false, toolCalls: toolCalls.length ? toolCalls : undefined };
        } finally {
          clearTimeout(timeout);
        }
      } catch (err) {
        if (attempt === MAX_RETRIES - 1) break; // exhausted retries for this provider, try next
        if (err instanceof Error && err.name === "AbortError") break; // don't retry timeouts on same provider
        await sleep(BASE_RETRY_DELAY_MS * Math.pow(2, attempt));
      }
    }
  }

  // All providers exhausted
  if (isSimpleCall) return null;
  throw new Error("LLM_UNAVAILABLE: all providers exhausted");
}

export function clearLlmCache(): void {
  messagesCache.clear();
}
