import { AgentConfig } from './config';
import { TOOL_DEFINITIONS } from './tools';

export interface Message {
  role: 'system' | 'user' | 'assistant' | 'tool';
  content: string | null;
  tool_calls?: ToolCall[];
  tool_call_id?: string;
  name?: string;
}

export interface ToolCall {
  id: string;
  type: 'function';
  function: {
    name: string;
    arguments: string;
  };
}

export interface ChatResponse {
  message: Message;
  finish_reason: string | null;
}

export class DeepSeekClient {
  private readonly apiBase: string;

  constructor(private cfg: AgentConfig) {
    // Always use official DeepSeek API — no OpenRouter or proxies
    this.apiBase = cfg.apiBase.replace(/\/$/, '');
  }

  async chat(messages: Message[]): Promise<ChatResponse> {
    const body = {
      model: this.cfg.model,
      messages,
      tools: TOOL_DEFINITIONS,
      tool_choice: 'auto',
      temperature: 0.1,
      max_tokens: 8192,
    };

    const res = await fetch(`${this.apiBase}/chat/completions`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${this.cfg.apiKey}`,
      },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(180_000),
    });

    if (!res.ok) {
      const text = await res.text().catch(() => '');
      throw new Error(`DeepSeek API error ${res.status}: ${text}`);
    }

    const data = await res.json() as {
      choices: Array<{
        message: Message;
        finish_reason: string | null;
      }>;
    };

    const choice = data.choices[0];
    if (!choice) throw new Error('DeepSeek returned empty choices');

    return { message: choice.message, finish_reason: choice.finish_reason };
  }
}

// ─── Agent control signal parsers ────────────────────────────────────────────

export interface FinishSignal {
  summary: string;
  artifacts: string[];
}

export interface BlockSignal {
  type: 'blocked_auth' | 'blocked_rate_limit' | 'blocked_env' | 'blocked_permission';
  message: string;
  blocked_until?: string;
}

const FINISH_RE = /<<<FINISH>>>\s*\nsummary:\s*([\s\S]+?)(?:\nartifacts:\s*([\s\S]+?))?(?:\n<<<|$)/;
const BLOCK_RE  = /<<<BLOCK>>>\s*\ntype:\s*(\S+)\s*\nmessage:\s*([\s\S]+?)(?:\nblocked_until:\s*(\S+))?(?:\n<<<|$)/;

export function parseFinish(text: string): FinishSignal | null {
  const m = FINISH_RE.exec(text);
  if (!m) return null;
  const artifacts = (m[2] ?? '').split(',').map(s => s.trim()).filter(Boolean);
  return { summary: (m[1] ?? '').trim(), artifacts };
}

export function parseBlock(text: string): BlockSignal | null {
  const m = BLOCK_RE.exec(text);
  if (!m) return null;
  return {
    type: (m[1] ?? 'blocked_env').trim() as BlockSignal['type'],
    message: (m[2] ?? '').trim(),
    blocked_until: m[3]?.trim(),
  };
}
