import { readFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { isLoopbackHost, isLoopbackUrl } from "./runtime.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "..");

export const PI_SDK_PACKAGE = "@earendil-works/pi-coding-agent";
export const PI_SDK_VERSION = "0.83.0";

function integerEnv(env, name, fallback, { min, max } = {}) {
  const raw = env[name];
  if (raw === undefined || raw === "") return fallback;
  const parsed = Number.parseInt(raw, 10);
  if (!Number.isSafeInteger(parsed)) return fallback;
  if (min !== undefined && parsed < min) return fallback;
  if (max !== undefined && parsed > max) return fallback;
  return parsed;
}

function csvEnv(env, name) {
  return (env[name] ?? "").split(",").map((value) => value.trim()).filter(Boolean);
}

export function loadConfig(env = process.env) {
  const modelId = env.PI_MODEL_ID || "qwen3-8b";
  const providerId = env.PI_MODEL_PROVIDER || env.PI_PROVIDER_ID || "radeon-local";
  const vllmBaseUrl = env.VLLM_BASE_URL || "http://127.0.0.1:8000/v1";
  if (!isLoopbackUrl(vllmBaseUrl)) {
    throw new Error(`Model endpoint must be loopback; refusing ${vllmBaseUrl}`);
  }
  const host = env.PI_BRIDGE_HOST || "127.0.0.1";
  if (!isLoopbackHost(host)) {
    throw new Error(`Pi bridge must bind to loopback; refusing host ${host}`);
  }
  return {
    host,
    port: integerEnv(env, env.PI_BRIDGE_PORT ? "PI_BRIDGE_PORT" : "PORT", 8787, { min: 1, max: 65535 }),
    corsOrigins: csvEnv(env, env.PI_ALLOWED_ORIGINS ? "PI_ALLOWED_ORIGINS" : "CORS_ORIGINS"),
    maxRequestBytes: integerEnv(env, "MAX_REQUEST_BYTES", 524_288, { min: 1024 }),
    sessionTtlMs: integerEnv(env, "SESSION_TTL_MS", 3_600_000, { min: 60_000 }),
    maxSessions: integerEnv(env, "MAX_SESSIONS", 64, { min: 1, max: 512 }),
    auditLogPath: resolve(root, env.AUDIT_LOG_PATH || "./logs/audit.jsonl"),
    modelsPath: resolve(root, env.PI_MODELS_PATH || "./models.json"),
    agentDir: resolve(root, ".pi-agent-runtime"),
    providerId,
    modelId,
    vllmBaseUrl,
    apiKey: env.PI_API_KEY || env.VLLM_API_KEY || "local-radeon",
    apiKeySource: env.PI_API_KEY || env.VLLM_API_KEY ? "environment" : "placeholder",
    rocmSmiBin: env.ROCM_SMI_BIN || "rocm-smi",
    amdSmiBin: env.AMD_SMI_BIN || "amd-smi",
    vllmPid: integerEnv(env, "VLLM_PID", null, { min: 1 }),
    rocmVersion: env.ROCM_VERSION || "",
    rocmProbeTimeoutMs: integerEnv(env, "ROCM_PROBE_TIMEOUT_MS", 5000, { min: 500, max: 30_000 })
  };
}

export async function readModelConfigStatus(config) {
  try {
    const content = await readFile(config.modelsPath, "utf8");
    const parsed = JSON.parse(content);
    const provider = parsed.providers?.[config.providerId];
    const model = provider?.models?.find((item) => item?.id === config.modelId);
    const configuredBaseUrl = provider?.baseUrl && !provider.baseUrl.includes("$") ? provider.baseUrl : config.vllmBaseUrl;
    return {
      modelsPath: config.modelsPath,
      providerConfigured: Boolean(provider),
      modelConfigured: Boolean(model),
      baseUrlConfigured: Boolean(provider?.baseUrl),
      baseUrl: configuredBaseUrl,
      apiKeyConfigured: Boolean(config.apiKey || provider?.apiKey),
      apiKeySource: config.apiKeySource
    };
  } catch (error) {
    return {
      modelsPath: config.modelsPath,
      providerConfigured: false,
      modelConfigured: false,
      baseUrlConfigured: false,
      baseUrl: config.vllmBaseUrl,
      apiKeyConfigured: Boolean(config.apiKey),
      apiKeySource: config.apiKeySource,
      error: error instanceof Error ? error.message : String(error)
    };
  }
}
