import Anthropic from '@anthropic-ai/sdk';
import type { AgentProvider, RunStreamParams } from './types';

const MODEL = process.env.ANTHROPIC_MODEL ?? process.env.LLM_MODEL ?? 'claude-sonnet-4-6';
const MAX_TOKENS = 4096;
const MAX_ITERATIONS = 6;
const STREAM_TIMEOUT_MS = 120_000;

let _client: Anthropic | null = null;
function client(): Anthropic {
  if (!_client) {
    const apiKey = process.env.ANTHROPIC_API_KEY ?? process.env.LLM_API_KEY;
    if (!apiKey) throw new Error('Missing ANTHROPIC_API_KEY or LLM_API_KEY');
    _client = new Anthropic({ apiKey, timeout: STREAM_TIMEOUT_MS });
  }
  return _client;
}

interface StreamedTurn {
  text: string;
  toolUses: { id: string; name: string; input: Record<string, unknown> }[];
  stopReason: string | null;
  content: unknown[];
}

/** Stream a single Messages API call; forward text deltas and buffer tool_use. */
async function streamMessage(
  system: string,
  messages: Anthropic.MessageParam[],
  tools: Anthropic.Tool[],
  onText: (delta: string) => void
): Promise<StreamedTurn> {
  const stream = (await client().messages.create({
    model: MODEL,
    max_tokens: MAX_TOKENS,
    system,
    messages,
    tools,
    stream: true,
  })) as AsyncIterable<any>;

  let text = '';
  let blockText = '';
  let currentBlock: { type: string; id?: string; name?: string } | null = null;
  const inputBuffers: Record<string, string> = {};
  const toolUses: { id: string; name: string; input: Record<string, unknown> }[] = [];
  const content: unknown[] = [];
  let stopReason: string | null = null;

  for await (const event of stream) {
    switch (event.type) {
      case 'content_block_start': {
        const block = event.content_block as { type: string; id?: string; name?: string };
        currentBlock = { ...block };
        blockText = '';
        if (block.type === 'tool_use' && block.id) inputBuffers[block.id] = '';
        break;
      }
      case 'content_block_delta': {
        const delta = event.delta as
          | { type: 'text_delta'; text: string }
          | { type: 'input_json_delta'; partial_json: string };
        if (delta.type === 'text_delta') {
          text += delta.text;
          blockText += delta.text;
          onText(delta.text);
        } else if (delta.type === 'input_json_delta' && currentBlock?.id) {
          inputBuffers[currentBlock.id] += delta.partial_json;
        }
        break;
      }
      case 'content_block_stop': {
        if (currentBlock?.type === 'tool_use' && currentBlock.id && currentBlock.name) {
          let input: Record<string, unknown>;
          try { input = JSON.parse(inputBuffers[currentBlock.id] || '{}'); }
          catch { input = {}; }
          toolUses.push({ id: currentBlock.id, name: currentBlock.name, input });
          content.push({ type: 'tool_use', id: currentBlock.id, name: currentBlock.name, input });
        } else if (currentBlock?.type === 'text') {
          content.push({ type: 'text', text: blockText });
        }
        currentBlock = null;
        blockText = '';
        break;
      }
      case 'message_delta': {
        const delta = event.delta as { stop_reason?: string } | undefined;
        if (delta?.stop_reason) stopReason = delta.stop_reason;
        break;
      }
      default:
        break;
    }
  }

  return { text, toolUses, stopReason, content };
}

/** Claude implementation of the AgentProvider interface. */
export const claudeProvider: AgentProvider = {
  name: 'claude',
  async runStream({ system, messages, tools, executeTool, callbacks }: RunStreamParams) {
    const anthropicTools = tools.map((t) => ({
      name: t.name,
      description: t.description,
      input_schema: t.input_schema,
    })) as Anthropic.Tool[];

    let working: Anthropic.MessageParam[] = messages.map((m) => ({
      role: m.role,
      content: m.content,
    }));

    let allText = '';
    const onText = (delta: string) => {
      allText += delta;
      callbacks.onText(delta);
    };

    for (let i = 0; i < MAX_ITERATIONS; i++) {
      const res = await streamMessage(system, working, anthropicTools, onText);

      working.push({
        role: 'assistant',
        content:
          (res.content.length > 0
            ? res.content
            : [{ type: 'text', text: res.text }]) as Anthropic.ContentBlock[],
      });

      if (res.stopReason !== 'tool_use' || res.toolUses.length === 0) {
        return allText;
      }

      const toolResults: Anthropic.ToolResultBlockParam[] = [];
      for (const tu of res.toolUses) {
        try {
          const out = await executeTool(tu.name, tu.input);
          callbacks.onTool?.(tu.name, out.clientSummary);
          if (out.displayText) onText(out.displayText);
          toolResults.push({
            type: 'tool_result',
            tool_use_id: tu.id,
            content: out.toolResult,
          });
        } catch (err) {
          const message = err instanceof Error ? err.message : String(err);
          callbacks.onTool?.(tu.name, `Error: ${message}`);
          toolResults.push({
            type: 'tool_result',
            tool_use_id: tu.id,
            content: `Error: ${message}`,
            is_error: true,
          });
        }
      }
      working.push({ role: 'user', content: toolResults });
    }

    return allText;
  },
};
