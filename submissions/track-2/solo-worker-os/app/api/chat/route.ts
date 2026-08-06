import { NextRequest, NextResponse } from 'next/server';
import { getAuthenticatedClientWithUser, AuthError } from '@/lib/supabase-server';
import { getAgent } from '@/lib/agent';
import type { ToolExecutor } from '@/lib/agent/types';
import { buildSystemPrompt } from '@/lib/agent/prompt';
import { routeMessage, getRoutedTools } from '@/lib/agent/router';
import {
  startTrace,
  addRouteEvent,
  addToolCallEvent,
  addToolResultEvent,
  addLlmCallEvent,
  addErrorEvent,
  endTrace,
} from '@/lib/agent/trace';
import {
  executeToolForMode,
  getToolSpecsForMode,
  type CompetitionMode,
} from '@/lib/tools';
import { todayISO } from '@/lib/utils';
import { checkBurst, consumeChatQuota } from '@/lib/rate-limit';
import { getMemoryStore, generateConversationId, type StoreContext } from '@/lib/memory/store';
import type { Project } from '@/lib/types';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/** Max characters accepted in a single user message. */
const MAX_MESSAGE_CHARS = 8_000;
/** Max turns of history accepted, to bound prompt size and cost. */
const MAX_HISTORY_MESSAGES = 40;

interface ChatRequestBody {
  messages: { role: 'user' | 'assistant'; content: string }[];
  persist?: boolean;
  conversation_id?: string;
  load_history?: boolean;
}

function resolveCompetitionMode(body: ChatRequestBody): CompetitionMode {
  const raw = (body as unknown as { competition_mode?: string }).competition_mode
    ?? process.env.COMPETITION_MODE
    ?? 'default';
  const normalized = raw.toLowerCase();
  if (normalized === 'qwen' || normalized === 'casper') return normalized;
  return 'default';
}

function jsonError(message: string, status: number, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify({ error: message }), {
    status,
    headers: { 'Content-Type': 'application/json', ...headers },
  });
}

export async function POST(req: NextRequest) {
  const ip =
    req.headers.get('x-forwarded-for')?.split(',')[0].trim() ??
    req.headers.get('x-real-ip') ??
    'unknown';

  const burst = checkBurst(ip);
  if (!burst.ok) {
    return jsonError(burst.message ?? 'Too many requests.', 429, {
      'Retry-After': String(Math.ceil((burst.retryAfterMs ?? 60_000) / 1000)),
    });
  }

  let body: ChatRequestBody;
  try {
    body = (await req.json()) as ChatRequestBody;
  } catch {
    return jsonError('Invalid JSON body', 400);
  }

  const incoming = body.messages ?? [];
  const persist = body.persist !== false;
  const competitionMode = resolveCompetitionMode(body);
  // Conversation tracking: use provided ID or generate a new one.
  // The ID is returned via SSE so the client can use it for subsequent turns.
  const conversationId = body.conversation_id ?? generateConversationId();

  // Bound the request before it reaches the model: an unbounded history or a
  // multi-megabyte message is both a cost and a latency problem.
  if (incoming.length === 0) {
    return jsonError('No messages provided', 400);
  }
  if (incoming.length > MAX_HISTORY_MESSAGES) {
    return jsonError(
      `Conversation too long (max ${MAX_HISTORY_MESSAGES} messages). Start a new chat.`,
      413,
    );
  }
  const oversized = incoming.find((m) => (m.content?.length ?? 0) > MAX_MESSAGE_CHARS);
  if (oversized) {
    return jsonError(`Message too long (max ${MAX_MESSAGE_CHARS} characters).`, 413);
  }

  // Use authenticated client + user in a single auth call (avoids redundant getUser)
  let supabase;
  let user: { id: string } | null = null;
  try {
    const { client, user: u } = await getAuthenticatedClientWithUser();
    supabase = client;
    user = u;
  } catch (e) {
    if (e instanceof AuthError) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    throw e;
  }

  // Daily quota is checked after auth so it can be keyed to the user and plan.
  const quota = await consumeChatQuota(supabase, ip);
  if (!quota.ok) {
    return jsonError(
      quota.message ?? 'Daily limit reached.',
      quota.reason === 'store_unavailable' ? 503 : 429,
    );
  }

  // Build memory store context for this request (used for conversation persistence)
  const storeCtx: StoreContext = {
    ...(user && { userId: user.id }),
    supabase,
  };
  const memoryStore = getMemoryStore();

  const agent = await getAgent();

  // Load current user's projects for system prompt context
  const { data: projects } = await supabase
    .from('projects')
    .select('*')
    .order('created_at', { ascending: false });

  // ── FunctionRouter: route the user's message to the best Subagent ──
  // Two-layer routing: Layer 1 keyword matching (fast, ~0ms) → Layer 2 LLM
  // intent classification (fallback for ambiguous queries, ~2-3s).
  const lastUserMsg = [...incoming].reverse().find((m) => m.role === 'user');

  // Layer 2 LLM call function: uses the configured agent provider for a
  // lightweight text completion (no tools, no streaming) to classify intent.
  const routingLLMCall = async (prompt: string): Promise<string> => {
    try {
      const result = await agent.runStream({
        system: 'You are a FunctionRouter. Respond with ONLY the subagent id. No explanation.',
        messages: [{ role: 'user', content: prompt }],
        tools: [],
        executeTool: async () => ({ toolResult: '', clientSummary: '' }),
        callbacks: { onText: () => {} },
      });
      return result;
    } catch {
      return ''; // LLM call failed — router will fall back to 'general'
    }
  };

  const routeResult = await routeMessage(
    lastUserMsg?.content ?? '',
    routingLLMCall,
  );

  // Build system prompt with subagent-specific context
  const system = buildSystemPrompt(
    (projects as Project[]) ?? [],
    todayISO(),
    competitionMode,
    routeResult.subagent
  );

  // Filter tools based on routing: specific subagents get only their tools
  const allSpecs = getToolSpecsForMode(competitionMode);
  const allowedToolNames = getRoutedTools(routeResult.subagent, allSpecs.map((t) => t.name));
  const toolSpecs = allSpecs.filter((t) => allowedToolNames.includes(t.name));
  // Per-request map of in-flight tool calls, used to feed the trace collector
  // with accurate input + duration when the onTool callback fires.
  // (openai-compat.ts calls executeTool then onTool sequentially, so keying by
  // tool name is safe even for repeated same-name tool calls.)
  const toolCallMeta = new Map<string, { input: Record<string, unknown>; start: number }>();

  const executeToolFn: ToolExecutor = async (name: string, input: Record<string, unknown>): Promise<import('@/lib/agent/types').ToolExecutionResult> => {
    toolCallMeta.set(name, { input, start: Date.now() });
    const result = await executeToolForMode(competitionMode, name, input, supabase);
    return result;
  };

  // Persist the latest user message via memory store (with conversation_id)
  const lastUser = [...incoming].reverse().find((m) => m.role === 'user');
  if (persist && lastUser) {
    try {
      await memoryStore.save(
        {
          id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
          role: 'user',
          content: lastUser.content,
          conversationId,
          createdAt: new Date().toISOString(),
        },
        storeCtx,
      );
    } catch {
      // Non-blocking: persistence failure shouldn't break the chat
    }
  }

  const agentMessages = incoming.map((m) => ({ role: m.role, content: m.content }));

  // ── Load conversation history for multi-turn memory recovery ──
  // When load_history is true and a conversation_id is provided, prepend
  // stored history so the agent has full context across page refreshes.
  if (body.load_history && body.conversation_id) {
    try {
      const history = await memoryStore.loadHistory(body.conversation_id, storeCtx, 20);
      if (history.length > 0) {
        const historyMessages = history.map((m) => ({ role: m.role, content: m.content }));
        // Prepend history, then current messages (avoid duplicates)
        agentMessages.unshift(...historyMessages);
      }
    } catch {
      // Non-blocking: history load failure shouldn't break the chat
    }
  }

  const encoder = new TextEncoder();
  // Declare traceId outside so cancel() can access it
  let traceId: string | null = null;
  const stream = new ReadableStream<Uint8Array>({
    async start(controller) {
      const send = (obj: unknown) =>
        controller.enqueue(encoder.encode(`data: ${JSON.stringify(obj)}\n\n`));

      // ── Trace: start a trace for this turn (non-blocking; failure is swallowed) ──
      traceId = startTrace();
      const tid = traceId; // capture as const for closure type-narrowing
      addRouteEvent(tid, routeResult);

      let llmStart = 0;
      try {
        // Send conversation ID so the client can track this conversation
        send({ type: 'conversation', conversation_id: conversationId });
        // Send routing info to client for trace visualization
        send({ type: 'route', route: routeResult });

        llmStart = Date.now();

        // ── LLM call with retry: only retry if no text has been streamed yet ──
        // If the stream started and then broke, we can't retry (would duplicate).
        const MAX_LLM_RETRIES = 2;
        let textStarted = false;
        let finalText = '';

        for (let attempt = 0; attempt <= MAX_LLM_RETRIES; attempt++) {
          textStarted = false;
          try {
            finalText = await agent.runStream({
              system,
              messages: agentMessages,
              tools: toolSpecs,
              executeTool: executeToolFn,
              callbacks: {
                onText: (delta) => {
                  textStarted = true;
                  send({ type: 'text', delta });
                },
                onTool: (name, summary) => {
                  send({ type: 'tool', name, summary });
                  // Record tool_call + tool_result with captured input & duration.
                  // Wrapped so a trace failure can never break the chat stream.
                  try {
                    const meta = toolCallMeta.get(name);
                    const durationMs = meta ? Date.now() - meta.start : 0;
                    addToolCallEvent(tid, name, meta?.input ?? {});
                    addToolResultEvent(tid, name, summary, durationMs);
                    if (meta) toolCallMeta.delete(name);
                  } catch {
                    /* non-blocking */
                  }
                },
              },
            });
            break; // success — exit retry loop
          } catch (err) {
            if (textStarted || attempt === MAX_LLM_RETRIES) {
              throw err; // already streamed or max retries — can't safely retry
            }
            // Exponential backoff before retry: 500ms, 1000ms
            await new Promise((r) => setTimeout(r, 500 * Math.pow(2, attempt)));
            send({ type: 'retry', attempt: attempt + 1 });
          }
        }
        addLlmCallEvent(tid, Date.now() - llmStart, routeResult.subagent);

        if (persist && finalText.trim()) {
          try {
            await memoryStore.save(
              {
                id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
                role: 'assistant',
                content: finalText,
                conversationId,
                createdAt: new Date().toISOString(),
              },
              storeCtx,
            );
          } catch {
            // Non-blocking: persistence failure shouldn't break the chat
          }
        }
        send({ type: 'done' });
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Unknown error';
        try { addErrorEvent(traceId, message); } catch { /* non-blocking */ }
        send({ type: 'error', message });
      } finally {
        try { endTrace(tid); } catch { /* non-blocking */ }
        controller.close();
      }
    },
    // Clean up when client disconnects: abort any in-flight LLM/stream work
    cancel() {
      if (traceId) {
        try { endTrace(traceId); } catch { /* non-blocking */ }
      }
    },
  });

  return new Response(stream, {
    headers: {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache, no-transform',
      Connection: 'keep-alive',
    },
  });
}
