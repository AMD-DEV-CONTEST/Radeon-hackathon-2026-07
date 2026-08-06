/**
 * OpenAI agent provider.
 *
 * Standard OpenAI chat.completions API:
 *   POST https://api.openai.com/v1/chat/completions
 *
 * Env vars:
 *   OPENAI_API_KEY   → OpenAI API key
 *   OPENAI_BASE_URL  → Custom base URL (for Azure OpenAI or proxies)
 *   OPENAI_MODEL     → Model name (default: gpt-4o)
 */

import { createOpenAICompatibleProvider } from './openai-compat';

const DEFAULT_API_URL = 'https://api.openai.com/v1/chat/completions';

export const openaiProvider = createOpenAICompatibleProvider({
  name: 'openai',
  getApiUrl: () =>
    process.env.OPENAI_BASE_URL ?? DEFAULT_API_URL,
  getApiKey: () => {
    const key = process.env.OPENAI_API_KEY ?? process.env.LLM_API_KEY;
    if (!key) {
      throw new Error('Missing OPENAI_API_KEY in .env.local');
    }
    return key;
  },
  getModel: () =>
    process.env.OPENAI_MODEL ?? 'gpt-4o',
});
