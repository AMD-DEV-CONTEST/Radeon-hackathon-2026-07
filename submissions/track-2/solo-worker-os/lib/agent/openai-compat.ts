/**
 * Shared OpenAI-compatible agent provider factory.
 *
 * Qwen (DashScope), MTClaw, and OpenAI all speak the OpenAI chat.completions
 * API format. This module encapsulates the common streaming + tool-call loop
 * logic, parameterised by a provider config.
 *
 * Each concrete provider (qwen.ts, mtclaw.ts, openai.ts) creates an instance
 * via `createOpenAICompatibleProvider()`.
 */

import type { AgentProvider, RunStreamParams } from './types';

// ─── Types ───────────────────────────────────────────────────────────────────

interface ProviderConfig {
  /** Provider name for AgentProvider interface */
  name: string;
  /** Resolve the API base URL (e.g. https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions) */
  getApiUrl: () => string;
  /** Resolve the API key */
  getApiKey: () => string;
  /** Resolve the model name */
  getModel: () => string;
  /** Max tokens per response */
  getMaxTokens?: () => number;
  /** Max tool-call iterations per turn */
  getMaxIterations?: () => number;
  /** Optional: extra fields to merge into the request body (e.g. router_hints) */
  extraBody?: () => Record<string, unknown>;
}

interface OpenAIMessage {
  role: 'user' | 'assistant' | 'system' | 'tool';
  content: string | ContentPart[];
  tool_calls?: ToolCallPart[];
  tool_call_id?: string;
}

interface ContentPart {
  type: 'text';
  text: string;
}

interface ToolCallPart {
  type: 'function';
  id: string;
  function: {
    name: string;
    arguments: string;
  };
}

// ─── Message conversion ──────────────────────────────────────────────────────

/**
 * Normalize a provider-neutral message into OpenAI format.
 *
 * The agent layer sends messages with:
 *   - role: 'user' | 'assistant'
 *   - content: string  (for user turns)
 *   - content: Anthropic-style content[] (for assistant turns with tool calls)
 *
 * This function converts both to the OpenAI chat.completions format.
 */
function toOpenAIMessage(msg: { role: string; content: unknown }): OpenAIMessage {
  if (msg.role === 'user') {
    return { role: 'user', content: String(msg.content ?? '') };
  }

  if (msg.role === 'assistant') {
    const raw = msg.content;

    if (typeof raw === 'string') {
      return { role: 'assistant', content: raw };
    }

    if (Array.isArray(raw)) {
      const textParts: string[] = [];
      const toolCalls: ToolCallPart[] = [];

      for (const block of raw as Array<Record<string, unknown>>) {
        if (block.type === 'text' && typeof block.text === 'string') {
          textParts.push(block.text);
        } else if (block.type === 'tool_use') {
          toolCalls.push({
            type: 'function',
            id: String(block.id ?? ''),
            function: {
              name: String(block.name ?? ''),
              arguments: JSON.stringify((block.input as Record<string, unknown>) ?? {}),
            },
          });
        }
      }

      const content = textParts.length > 0 ? textParts.join('') : '';

      if (toolCalls.length > 0) {
        return { role: 'assistant', content, tool_calls: toolCalls };
      }
      return { role: 'assistant', content };
    }

    return { role: 'assistant', content: String(raw) };
  }

  // tool role — convert from Anthropic tool_result blocks or plain string
  if (msg.role === 'tool') {
    const raw = msg.content;
    let text = '';
    let toolCallId = (msg as { tool_call_id?: string }).tool_call_id ?? '';

    if (typeof raw === 'string') {
      text = raw;
    } else if (Array.isArray(raw)) {
      text = (raw as Array<Record<string, unknown>>)
        .map((block) => {
          if (block.tool_use_id) toolCallId = String(block.tool_use_id);
          if (typeof block.content === 'string') return block.content;
          if (block.content && typeof block.content === 'object') {
            const cb = block.content as Record<string, unknown>;
            if (cb.type === 'text') return String(cb.text ?? '');
          }
          return JSON.stringify(block);
        })
        .join('\n');
    }

    const result: OpenAIMessage = {
      role: 'tool',
      content: text,
    };
    if (toolCallId) {
      result.tool_call_id = toolCallId;
    }
    return result;
  }

  return { role: 'user' as const, content: String(msg.content ?? '') };
}

// ─── Streaming ────────────────────────────────────────────────────────────────

interface StreamChoice {
  delta: {
    content?: string;
    tool_calls?: Array<{
      index: number;
      id?: string;
      type?: string;
      function?: { name?: string; arguments?: string };
    }>;
  };
  finish_reason?: string;
}

interface StreamEvent {
  choices: StreamChoice[];
}

/**
 * Stream a single chat.completions call.
 * Accumulates text deltas and buffers tool_calls across chunks.
 */
async function streamMessage(
  apiUrl: string,
  apiKey: string,
  model: string,
  maxTokens: number,
  system: string,
  messages: OpenAIMessage[],
  tools: { name: string; description: string; input_schema: Record<string, unknown> }[],
  onText: (delta: string) => void,
  extraBody?: Record<string, unknown>,
): Promise<{
  text: string;
  toolUses: { id: string; name: string; input: Record<string, unknown> }[];
  finishReason: string | null;
}> {
  const openaiTools = tools.map((t) => ({
    type: 'function' as const,
    function: {
      name: t.name,
      description: t.description,
      parameters: t.input_schema,
    },
  }));

  const serializedMessages = messages.map((m) => {
    const msgWithCalls = m as OpenAIMessage & { tool_calls?: ToolCallPart[] };
    const hasToolCalls = Array.isArray(msgWithCalls.tool_calls) && msgWithCalls.tool_calls.length > 0;

    let contentStr: string;
    if (typeof m.content === 'string') {
      contentStr = m.content;
    } else if (Array.isArray(m.content)) {
      contentStr = (m.content as unknown as Array<Record<string, unknown>>)
        .filter((b) => b.type === 'text' && typeof b.text === 'string')
        .map((b) => b.text as string)
        .join('');
    } else {
      contentStr = '';
    }

    const base: Record<string, unknown> = {
      role: m.role,
      content: hasToolCalls ? (contentStr || null) : contentStr,
    };
    if (hasToolCalls) {
      base.tool_calls = msgWithCalls.tool_calls;
    }
    if (m.role === 'tool' && m.tool_call_id) {
      base.tool_call_id = m.tool_call_id;
    }
    return base;
  });

  // DashScope / OpenAI compatible mode: system prompt must be injected as
  // messages[0].role="system" — NOT as a top-level "system" field (that's
  // Anthropic format and gets silently ignored by DashScope).
  const messagesWithSystem: Record<string, unknown>[] = [];
  if (system) {
    messagesWithSystem.push({ role: 'system', content: system });
  }
  messagesWithSystem.push(...serializedMessages);

  const body: Record<string, unknown> = {
    model,
    max_tokens: maxTokens,
    stream: true,
    messages: messagesWithSystem,
    tools: openaiTools.length > 0 ? openaiTools : undefined,
    ...extraBody,
  };

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 30_000);

  let res: Response;
  try {
    res = await fetch(apiUrl, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${apiKey}`,
      },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
  } finally {
    clearTimeout(timeoutId);
  }

  if (!res.ok) {
    const errText = await res.text().catch(() => 'Unknown error');
    throw new Error(`LLM API error ${res.status}: ${errText}`);
  }

  const reader = res.body?.getReader();
  if (!reader) throw new Error('No response body from LLM API');

  const decoder = new TextDecoder();
  let buffer = '';
  let fullText = '';
  const toolCallsMap = new Map<number, { id: string; name: string; args: string }>();
  let finishReason: string | null = null;

  // Read-timeout: abort if NO data arrives for 60s.
  // Uses a resettable setTimeout (NOT setInterval) so continuous streaming
  // never trips the timeout — only genuine silence does.
  let readTimeout: ReturnType<typeof setTimeout> | null = null;
  const resetReadTimeout = () => {
    if (readTimeout) clearTimeout(readTimeout);
    readTimeout = setTimeout(() => controller.abort(), 60_000);
  };
  resetReadTimeout();

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      // Got data — reset the silence timer.
      resetReadTimeout();

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() ?? '';

    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed || !trimmed.startsWith('data: ')) continue;
      const payload = trimmed.slice(6);
      if (payload === '[DONE]') break;

      try {
        const event = JSON.parse(payload) as StreamEvent;
        const choice = event.choices?.[0];
        if (!choice) continue;

        const delta = choice.delta;

        if (delta.content) {
          fullText += delta.content;
          onText(delta.content);
        }

        if (delta.tool_calls) {
          for (const tc of delta.tool_calls) {
            const idx = tc.index;
            if (!toolCallsMap.has(idx)) {
              toolCallsMap.set(idx, {
                id: tc.id ?? '',
                name: tc.function?.name ?? '',
                args: tc.function?.arguments ?? '',
              });
            } else {
              const existing = toolCallsMap.get(idx)!;
              if (tc.id) existing.id = tc.id;
              if (tc.function?.name) existing.name = tc.function.name;
              if (tc.function?.arguments) existing.args += tc.function.arguments;
            }
          }
        }

        if (choice.finish_reason) finishReason = choice.finish_reason;
      } catch {
        // Skip unparseable lines
      }
    }
  }
  } finally {
    if (readTimeout) clearTimeout(readTimeout);
  }

  const toolUses = [...toolCallsMap.values()]
    .filter((tc) => tc.name)   // 只要求 name 存在；id 缺失时生成 fallback id
    .map((tc, i) => ({
      id: tc.id || `call_${Date.now()}_${i}`,
      name: tc.name,
      input: (() => {
        try { return JSON.parse(tc.args || '{}'); }
        catch { return {}; }
      })(),
    }));

  return { text: fullText, toolUses, finishReason };
}

// ─── Factory ──────────────────────────────────────────────────────────────────

/**
 * Create an OpenAI-compatible AgentProvider from a config.
 *
 * All three providers (qwen, mtclaw, openai) use this factory to avoid
 * duplicating the streaming + tool-call loop logic.
 */
export function createOpenAICompatibleProvider(config: ProviderConfig): AgentProvider {
  const MAX_TOKENS = 4096;
  const MAX_ITERATIONS = 6;

  return {
    name: config.name,

    async runStream({ system, messages, tools, executeTool, callbacks }: RunStreamParams): Promise<string> {
      const apiUrl = config.getApiUrl();
      const apiKey = config.getApiKey();
      const model = config.getModel();
      const maxTokens = config.getMaxTokens?.() ?? MAX_TOKENS;
      const maxIterations = config.getMaxIterations?.() ?? MAX_ITERATIONS;
      const extraBody = config.extraBody?.();

      const openaiMessages: OpenAIMessage[] = messages.map(toOpenAIMessage);

      let allText = '';
      const onText = (delta: string) => {
        allText += delta;
        callbacks.onText(delta);
      };

      for (let i = 0; i < maxIterations; i++) {
        const res = await streamMessage(
          apiUrl, apiKey, model, maxTokens,
          system, openaiMessages, tools, onText,
          extraBody,
        );

        // Build assistant turn in Anthropic content-block format
        const assistantBlocks: Array<Record<string, unknown>> = [];

        if (res.text) {
          assistantBlocks.push({ type: 'text', text: res.text });
        }

        for (const tu of res.toolUses) {
          assistantBlocks.push({
            type: 'tool_use',
            id: tu.id,
            name: tu.name,
            input: tu.input,
          });
        }

        openaiMessages.push({ role: 'assistant', content: assistantBlocks } as any);

        // If no tool calls, we're done.
        // 注意：不检查 finishReason === 'tool_calls'，因为 Qwen 等模型
        // 可能返回 'function_call' 或 'stop'，只要解析出 toolUses 就继续执行。
        if (res.toolUses.length === 0) {
          return allText;
        }

        // Execute tools and append results
        for (const tu of res.toolUses) {
          try {
            const out = await executeTool(tu.name, tu.input);
            callbacks.onTool?.(tu.name, out.clientSummary);
            // Stream displayText (contracts, invoices, reports) to the user
            if (out.displayText) {
              callbacks.onText(out.displayText + '\n\n');
              allText += out.displayText + '\n\n';
            }
            openaiMessages.push({
              role: 'tool',
              content: out.toolResult,
              tool_call_id: tu.id,
            } as OpenAIMessage);
          } catch (err) {
            const message = err instanceof Error ? err.message : String(err);
            callbacks.onTool?.(tu.name, `Error: ${message}`);
            openaiMessages.push({
              role: 'tool',
              content: `Error: ${message}`,
              tool_call_id: tu.id,
            } as OpenAIMessage);
          }
        }
      }

      return allText;
    },
  };
}
