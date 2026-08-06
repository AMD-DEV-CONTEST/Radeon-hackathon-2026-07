import {
  OpenAiCompatibleToolProvider,
  ScriptedProductProvider,
  type AgentModelProvider
} from "@privateplate/agent-runtime";

export type RuntimeConfig = {
  appMode: "demo" | "production";
  databasePath: string;
  /** Product mode is always local_vllm; tests inject ScriptedProductProvider. */
  providerMode: "local_vllm";
  provider: AgentModelProvider;
  model: string;
  baseUrl: string | null;
  vllmApiKey?: string | null;
  requestTimeoutMs?: number;
  evidenceEligible: boolean;
  accessToken: string | null;
};

/**
 * Product dashboard requires a real local_vllm agent.
 * Offline unit tests should inject ScriptedProductProvider via createAppContext({ config }).
 */
export function loadRuntimeConfig(
  env: NodeJS.ProcessEnv = process.env
): RuntimeConfig {
  const appMode = env.PRIVATEPLATE_APP_MODE === "production" ? "production" : "demo";

  if (env.PRIVATEPLATE_AGENT_PROVIDER === "deterministic_dev") {
    throw new Error(
      "deterministic_dev / DeterministicDemoAgent has been removed. " +
        "Use PRIVATEPLATE_AGENT_PROVIDER=local_vllm for the real Agent, " +
        "or inject ScriptedProductProvider in tests."
    );
  }

  if (
    env.PRIVATEPLATE_AGENT_PROVIDER &&
    env.PRIVATEPLATE_AGENT_PROVIDER !== "local_vllm"
  ) {
    throw new Error(
      `Unknown PRIVATEPLATE_AGENT_PROVIDER=${env.PRIVATEPLATE_AGENT_PROVIDER}. Use local_vllm.`
    );
  }

  // Real dashboard keeps household memory across restarts. :memory: only when
  // PRIVATEPLATE_DATABASE_PATH=:memory: or PRIVATEPLATE_EPHEMERAL_DB=yes (tests).
  const databasePath =
    env.PRIVATEPLATE_DATABASE_PATH ??
    (env.PRIVATEPLATE_EPHEMERAL_DB === "yes"
      ? ":memory:"
      : "./data/privateplate-demo.sqlite");

  const baseUrl =
    env.PRIVATEPLATE_VLLM_BASE_URL ?? "http://127.0.0.1:8000/v1";
  const model = env.PRIVATEPLATE_MODEL_ACTIVE ?? env.PRIVATEPLATE_MODEL;
  if (!model) {
    throw new Error(
      "Real Agent dashboard requires PRIVATEPLATE_MODEL_ACTIVE or PRIVATEPLATE_MODEL " +
        "(OpenAI-compatible model id served by vLLM)."
    );
  }
  const accessToken = env.PRIVATEPLATE_ACCESS_TOKEN;
  if (appMode === "production" && (!accessToken || accessToken.length < 16)) {
    throw new Error(
      "Production mode requires PRIVATEPLATE_ACCESS_TOKEN with at least 16 characters."
    );
  }

  const requestTimeoutMs = Number(
    env.PRIVATEPLATE_REQUEST_TIMEOUT_MS ?? 120_000
  );
  const vllmApiKey = env.PRIVATEPLATE_VLLM_API_KEY;
  const providerOptions: ConstructorParameters<
    typeof OpenAiCompatibleToolProvider
  >[0] = {
    baseUrl,
    model,
    timeoutMs: requestTimeoutMs
  };
  if (env.PRIVATEPLATE_VLLM_API_KEY) {
    providerOptions.apiKey = env.PRIVATEPLATE_VLLM_API_KEY;
  }

  return {
    appMode,
    databasePath,
    providerMode: "local_vllm",
    provider: new OpenAiCompatibleToolProvider(providerOptions),
    model,
    baseUrl,
    vllmApiKey: vllmApiKey ?? null,
    requestTimeoutMs,
    evidenceEligible:
      appMode === "production" &&
      env.PRIVATEPLATE_RADEON_EVIDENCE_ELIGIBLE === "yes",
    accessToken: accessToken ?? null
  };
}

/** Shared fixture: real PrivatePlateAgent path with ScriptedProductProvider mock. */
export function mockAgentTestConfig(
  overrides: Partial<RuntimeConfig> = {}
): RuntimeConfig {
  const provider = overrides.provider ?? new ScriptedProductProvider();
  return {
    appMode: overrides.appMode ?? "demo",
    databasePath: overrides.databasePath ?? ":memory:",
    providerMode: "local_vllm",
    provider,
    model: overrides.model ?? provider.model,
    baseUrl: overrides.baseUrl ?? "http://127.0.0.1:8000/v1",
    vllmApiKey: overrides.vllmApiKey ?? null,
    requestTimeoutMs: overrides.requestTimeoutMs ?? 120_000,
    evidenceEligible: overrides.evidenceEligible ?? false,
    accessToken: overrides.accessToken ?? null
  };
}

/** Explicit ephemeral in-memory DB for unit tests. */
export function ephemeralDatabasePath(): string {
  return ":memory:";
}
