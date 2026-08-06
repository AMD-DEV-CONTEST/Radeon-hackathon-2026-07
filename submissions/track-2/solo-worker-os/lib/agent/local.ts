/**
 * Local self-hosted LLM provider (AMD Radeon GPU + ROCm + vLLM/SGLang).
 *
 * Built for the "Private AI Agent" track of AMD AI DevMaster 2026.
 *
 * The thesis: Solo Worker OS manages a freelancer's entire business —
 * client intake, contracts, invoices, payments. That is sensitive commercial
 * data that should not be sent to a commercial third-party LLM API. With this
 * provider the agent's inference runs on a participant-controlled AMD Radeon
 * GPU endpoint through the open ROCm stack.
 *
 * Reuses the shared OpenAI-compatible loop from openai-compat.ts, because
 * both vLLM and SGLang expose an OpenAI-compatible /v1/chat/completions
 * endpoint. Only the config (URL, key, model) is provider-specific.
 *
 * Env vars:
 *   LOCAL_LLM_BASE_URL  → e.g. http://localhost:8000/v1/chat/completions
 *   LOCAL_LLM_API_KEY   → optional (vLLM/SGLang default token is "EMPTY")
 *   LOCAL_LLM_MODEL     → e.g. Qwen/Qwen3-4B
 *
 * Recommended serving stack on AMD Radeon GPU:
 *   vllm serve Qwen/Qwen3-4B --port 8000 --trust-remote-code
 */

import { createOpenAICompatibleProvider } from './openai-compat';

// vLLM's default serving port is 8000; SGLang's is 30000.
// Default to vLLM (8000) since it is the more common ROCm entrypoint.
const DEFAULT_BASE_URL = 'http://localhost:8000/v1/chat/completions';

// vLLM/SGLang accept any non-empty bearer token by default; "EMPTY" is the
// convention vLLM itself uses when --api-key is not set.
const DEFAULT_API_KEY = 'EMPTY';

const DEFAULT_MODEL = 'Qwen/Qwen3-4B';

export const localProvider = createOpenAICompatibleProvider({
  name: 'local',
  getApiUrl: () => process.env.LOCAL_LLM_BASE_URL ?? DEFAULT_BASE_URL,
  getApiKey: () => process.env.LOCAL_LLM_API_KEY ?? DEFAULT_API_KEY,
  getModel: () => process.env.LOCAL_LLM_MODEL ?? DEFAULT_MODEL,
  getMaxTokens: () => 768,
  extraBody: () => ({
    chat_template_kwargs: { enable_thinking: false },
  }),
});
