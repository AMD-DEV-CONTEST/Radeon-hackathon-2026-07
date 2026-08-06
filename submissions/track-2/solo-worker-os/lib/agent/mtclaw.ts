/**
 * MTClaw agent provider — Moore Threads' OpenAI-compatible Function Router.
 *
 * MTClaw is a proxy that sits between the client and the LLM, providing:
 *   - FunctionRouter: routing model decides whether to call MTClaw tools or forward to upstream
 *   - Custom tools: shell-script-backed tools registered in functions.jsonl
 *   - Completion check: decides whether to return tool result directly or hand to upstream LLM
 *   - OpenAI-compatible API: same request/response format as standard LLM providers
 *
 * Architecture:
 *   Client (our app) → MTClaw (routing model + tools + completion check) → Upstream LLM (Qwen)
 *
 * MTClaw uses its OWN routing model (configured in solo-config.json) to decide
 * tool calls — it does not accept external routing hints from the client.
 * Our app's keyword-based FunctionRouter is a COMPLEMENTARY layer:
 *   Layer 1 (our app): keyword routing → select Subagent → filter tools
 *   Layer 2 (MTClaw): routing model → match custom tool or forward to upstream
 *
 * Env vars:
 *   MTCLAW_BASE_URL  → MTClaw endpoint (e.g. http://127.0.0.1:18790/v1/chat/completions)
 *   MTCLAW_API_KEY   → API key (passed as Bearer token, MTClaw forwards to upstream)
 *   MTCLAW_MODEL     → Model name for upstream LLM (e.g. qwen3.7-plus)
 */

import { createOpenAICompatibleProvider } from './openai-compat';

export const mtclawProvider = createOpenAICompatibleProvider({
  name: 'mtclaw',
  getApiUrl: () => {
    const url = process.env.MTCLAW_BASE_URL;
    if (!url) {
      throw new Error(
        'Missing MTCLAW_BASE_URL. Set it to your MTClaw router endpoint in .env.local'
      );
    }
    return url;
  },
  getApiKey: () => {
    const key = process.env.MTCLAW_API_KEY ?? process.env.LLM_API_KEY ?? process.env.DASHSCOPE_API_KEY;
    if (!key) {
      throw new Error(
        'Missing API key. Set MTCLAW_API_KEY (or LLM_API_KEY) in .env.local'
      );
    }
    return key;
  },
  getModel: () =>
    process.env.MTCLAW_MODEL ?? process.env.LLM_MODEL ?? 'qwen3.7-plus',
});
