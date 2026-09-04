export interface ChatMessage {
  role: "system" | "user" | "assistant" | "tool";
  content?: string | null;
  tool_calls?: ToolCall[];
  tool_call_id?: string;
  name?: string;
}

export interface ToolCall {
  id: string;
  type: "function";
  function: { name: string; arguments: string };
}

export interface ToolSpec {
  type: "function";
  function: {
    name: string;
    description: string;
    parameters: Record<string, unknown>;
  };
}

export interface ChatCompletionResponse {
  id?: string;
  choices: Array<{
    index: number;
    message: ChatMessage;
    finish_reason?: string | null;
  }>;
  usage?: {
    prompt_tokens?: number;
    completion_tokens?: number;
    total_tokens?: number;
  };
}

export interface LlmClientOptions {
  baseUrl: string;
  apiKey?: string;
  model: string;
  timeoutMs?: number;
}

/** Strip ASCII controls except tab/LF/CR so vLLM/json parsers don't 400. */
function stripBadControls(s: string): string {
  let out = "";
  for (let i = 0; i < s.length; i++) {
    const c = s.charCodeAt(i);
    if (c === 9 || c === 10 || c === 13 || (c >= 32 && c !== 127)) out += s[i];
  }
  return out;
}

function sanitizeMessages(messages: ChatMessage[]): ChatMessage[] {
  return messages.map((m) => {
    const next: ChatMessage = { ...m };
    if (typeof next.content === "string") next.content = stripBadControls(next.content);
    if (next.tool_calls?.length) {
      next.tool_calls = next.tool_calls.map((tc) => ({
        ...tc,
        function: {
          ...tc.function,
          name: stripBadControls(tc.function.name),
          // Keep arguments as a JSON object string when possible; always strip bad controls.
          arguments: normalizeToolArguments(tc.function.arguments),
        },
      }));
    }
    if (typeof next.name === "string") next.name = stripBadControls(next.name);
    if (typeof next.tool_call_id === "string") next.tool_call_id = stripBadControls(next.tool_call_id);
    return next;
  });
}

function normalizeToolArguments(raw: string | undefined): string {
  const s = stripBadControls(raw ?? "{}");
  try {
    return JSON.stringify(JSON.parse(s));
  } catch {
    // Model sometimes emits raw newlines inside "JSON"; coerce to a single-line object string.
    try {
      const compact = s.replace(/\r?\n/g, "\\n");
      return JSON.stringify(JSON.parse(compact));
    } catch {
      return JSON.stringify({ raw: s.slice(0, 4000) });
    }
  }
}

export class LlmClient {
  private readonly baseUrl: string;
  private readonly apiKey: string;
  private readonly model: string;
  private readonly timeoutMs: number;

  constructor(opts: LlmClientOptions) {
    this.baseUrl = opts.baseUrl.replace(/\/$/, "");
    this.apiKey = opts.apiKey ?? "local";
    this.model = opts.model;
    this.timeoutMs = opts.timeoutMs ?? 180_000;
  }

  get modelName(): string {
    return this.model;
  }

  async listModels(): Promise<unknown> {
    const res = await this.fetch("/models", { method: "GET" });
    return res.json();
  }

  async chat(opts: {
    messages: ChatMessage[];
    tools?: ToolSpec[];
    toolChoice?: "auto" | "none" | { type: "function"; function: { name: string } };
    maxTokens?: number;
    temperature?: number;
  }): Promise<ChatCompletionResponse> {
    const body: Record<string, unknown> = {
      model: this.model,
      messages: sanitizeMessages(opts.messages),
      max_tokens: opts.maxTokens ?? 800,
      temperature: opts.temperature ?? 0,
    };
    if (opts.tools?.length) {
      body.tools = opts.tools;
      body.tool_choice = opts.toolChoice ?? "auto";
    }
    // Ensure the wire payload is strict JSON (no raw control chars outside strings).
    const payload = JSON.stringify(body);
    const res = await this.fetch("/chat/completions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: payload,
    });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(`LLM HTTP ${res.status}: ${text.slice(0, 800)}`);
    }
    return (await res.json()) as ChatCompletionResponse;
  }

  private async fetch(pathname: string, init: RequestInit): Promise<Response> {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), this.timeoutMs);
    try {
      const headers = new Headers(init.headers);
      headers.set("Authorization", `Bearer ${this.apiKey}`);
      return await fetch(`${this.baseUrl}${pathname}`, {
        ...init,
        headers,
        signal: ctrl.signal,
      });
    } finally {
      clearTimeout(timer);
    }
  }
}
