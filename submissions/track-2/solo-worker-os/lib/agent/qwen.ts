/**
 * Qwen Cloud (DashScope) agent provider.
 *
 * Uses DashScope's OpenAI-compatible mode:
 *   POST https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions
 *
 * This file reuses the shared OpenAI-compatible logic from openai-compat.ts.
 * Only the config (API URL, key, model) is provider-specific.
 *
 * Env vars (with backward-compatible fallbacks):
 *   LLM_BASE_URL  → QWEN base URL (default: DashScope)
 *   LLM_API_KEY   → DASHSCOPE_API_KEY
 *   LLM_MODEL     → QWEN_MODEL (default: qwen-plus)
 */

import { createOpenAICompatibleProvider } from './openai-compat';

const DEFAULT_API_URL = 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions';

export const qwenProvider = createOpenAICompatibleProvider({
  name: 'qwen',
  getApiUrl: () =>
    process.env.LLM_BASE_URL ?? DEFAULT_API_URL,
  getApiKey: () => {
    const key = process.env.LLM_API_KEY ?? process.env.DASHSCOPE_API_KEY;
    if (!key) {
      throw new Error(
        'Missing API key. Set LLM_API_KEY or DASHSCOPE_API_KEY in .env.local'
      );
    }
    return key;
  },
  getModel: () =>
    process.env.LLM_MODEL ?? process.env.QWEN_MODEL ?? 'qwen-plus',
});
