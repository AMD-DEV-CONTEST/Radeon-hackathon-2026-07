import type { BotChatSession } from "./types/bot";

export interface ChatMessage {
  role: "bot" | "customer" | "system";
  content: string;
  timestamp?: string;
}

export interface ParsedChat {
  messages: ChatMessage[];
  customer_questions: string[];
  bot_responses: string[];
  transfer_triggered: boolean;
}

/**
 * Parse a serialized chat conversation into structured messages.
 * Supports multiple import formats:
 *   - "客服：xxx\n用户：yyy"  (Chinese labels)
 *   - "Agent: xxx\nCustomer: yyy" (English labels)
 *   - JSON array of {role, content}
 */
export function parseConversation(conversation: string): ParsedChat {
  const result: ParsedChat = {
    messages: [],
    customer_questions: [],
    bot_responses: [],
    transfer_triggered: false,
  };

  const raw = conversation.trim();
  if (!raw) return result;

  // Try JSON array format
  if (raw.startsWith("[") && raw.endsWith("]")) {
    try {
      const arr = JSON.parse(raw) as ChatMessage[];
      for (const m of arr) {
        result.messages.push(m);
        if (m.role === "customer") result.customer_questions.push(m.content);
        if (m.role === "bot") result.bot_responses.push(m.content);
      }
      return result;
    } catch {
      // fall through to line parsing
    }
  }

  // Line-based parsing
  const lines = raw.split("\n");
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) continue;

    // Chinese label patterns
    const customerMatch = trimmed.match(/^(?:用户|顾客|买家|客户)[：:]\s*(.+)/);
    const botMatch = trimmed.match(/^(?:客服|机器人|客服机器人|智能客服|店小二)[：:]\s*(.+)/);
    // English label patterns
    const enCustomerMatch = trimmed.match(/^(?:Customer|User|Buyer)[：:]\s*(.+)/i);
    const enBotMatch = trimmed.match(/^(?:Agent|Bot|CS|Service)[：:]\s*(.+)/i);

    if (customerMatch || enCustomerMatch) {
      const content = (customerMatch || enCustomerMatch)![1];
      result.messages.push({ role: "customer", content });
      result.customer_questions.push(content);
    } else if (botMatch || enBotMatch) {
      const content = (botMatch || enBotMatch)![1];
      result.messages.push({ role: "bot", content });
      result.bot_responses.push(content);
      if (/转接|转人工|人工客服|transfer/i.test(content)) {
        result.transfer_triggered = true;
      }
    }
  }

  return result;
}

/**
 * Convert parsed messages to a simple serialized format for storage/display.
 */
export function serializeMessages(messages: ChatMessage[]): string {
  return messages
    .map((m) => {
      const label = m.role === "customer" ? "用户" : m.role === "bot" ? "客服" : "系统";
      return `${label}：${m.content}`;
    })
    .join("\n");
}

/**
 * Extract user questions from a batch of sessions.
 */
export function extractUserQuestions(sessions: BotChatSession[]): { session_id: string; user_questions: string[] }[] {
  return sessions.map((s) => {
    const parsed = parseConversation(s.conversation);
    return {
      session_id: s.id,
      user_questions: parsed.customer_questions.filter((q) => q.length > 2),
    };
  });
}
