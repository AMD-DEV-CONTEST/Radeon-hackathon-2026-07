/**
 * Conversation memory store — unified interface for persisting and loading
 * multi-turn conversation history.
 *
 * Two backends:
 *   1. Supabase (cloud/SaaS mode) — uses the `messages` table with
 *      `conversation_id` column for grouping.
 *   2. Local JSON file (offline/local mode) — for AMD local deployment
 *      and any environment without Supabase access.
 *
 * The local backend writes JSONL to `data/conversations/<conversationId>.jsonl`.
 * This avoids native module dependencies (better-sqlite3 needs compilation)
 * while still providing persistent multi-turn memory — a core requirement
 * for the AMD DevMaster "local multi-turn memory" capability.
 */

import type { SupabaseClient } from '@supabase/supabase-js';
import { existsSync, mkdirSync, readFileSync, appendFileSync, readdirSync } from 'fs';
import { join, dirname } from 'path';

// ─── Types ─────────────────────────────────────────────────────────────────────

export interface MemoryMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  conversationId: string;
  createdAt: string;
}

export interface ConversationSummary {
  id: string;
  lastMessageAt: string;
  messageCount: number;
  preview?: string;
}

/**
 * Per-request context passed from the API route.
 * SupabaseMemoryStore uses this to respect RLS and scope queries to the
 * authenticated user. LocalMemoryStore ignores it (single-user local mode).
 */
export interface StoreContext {
  userId?: string;
  supabase?: SupabaseClient;
}

export interface MemoryStore {
  save(message: MemoryMessage, ctx?: StoreContext): Promise<void>;
  loadHistory(
    conversationId: string,
    ctx?: StoreContext,
    limit?: number,
  ): Promise<MemoryMessage[]>;
  listConversations(ctx?: StoreContext): Promise<ConversationSummary[]>;
}

// ─── Supabase backend ──────────────────────────────────────────────────────────

class SupabaseMemoryStore implements MemoryStore {
  async save(message: MemoryMessage, ctx?: StoreContext): Promise<void> {
    const supabase = ctx?.supabase;
    if (!supabase) {
      throw new Error('SupabaseMemoryStore.save requires a supabase client in ctx');
    }

    const { error } = await supabase.from('messages').insert({
      role: message.role,
      content: message.content,
      conversation_id: message.conversationId,
      project_id: null,
      ...(ctx?.userId && { user_id: ctx.userId }),
    });

    if (error) throw error;
  }

  async loadHistory(
    conversationId: string,
    ctx?: StoreContext,
    limit = 50,
  ): Promise<MemoryMessage[]> {
    const supabase = ctx?.supabase;
    if (!supabase) return [];

    const { data, error } = await supabase
      .from('messages')
      .select('id, role, content, created_at, conversation_id')
      .eq('conversation_id', conversationId)
      .order('created_at', { ascending: true })
      .limit(limit);

    if (error || !data) return [];

    return (data as Array<{
      id: string;
      role: string;
      content: string;
      created_at: string;
      conversation_id: string;
    }>).map((m) => ({
      id: m.id,
      role: m.role as 'user' | 'assistant',
      content: m.content,
      conversationId: m.conversation_id,
      createdAt: m.created_at,
    }));
  }

  async listConversations(ctx?: StoreContext): Promise<ConversationSummary[]> {
    const supabase = ctx?.supabase;
    if (!supabase) return [];

    // Fetch recent messages (enough to group by conversation_id)
    const { data, error } = await supabase
      .from('messages')
      .select('conversation_id, created_at, content, role')
      .not('conversation_id', 'is', null)
      .order('created_at', { ascending: false })
      .limit(500);

    if (error || !data) return [];

    // Group by conversation_id, track count + last message + preview
    const groups = new Map<
      string,
      { count: number; lastAt: string; preview: string }
    >();

    for (const row of data as Array<{
      conversation_id: string;
      created_at: string;
      content: string;
      role: string;
    }>) {
      const cid = row.conversation_id;
      if (!cid) continue;
      const existing = groups.get(cid);
      if (existing) {
        existing.count += 1;
        // Track the most recent message timestamp
        if (row.created_at > existing.lastAt) {
          existing.lastAt = row.created_at;
        }
      } else {
        // First user message as preview
        const preview =
          row.role === 'user'
            ? row.content.slice(0, 80)
            : undefined;
        groups.set(cid, {
          count: 1,
          lastAt: row.created_at,
          preview: preview ?? row.content.slice(0, 80),
        });
      }
    }

    return [...groups.entries()]
      .map(([id, v]) => ({
        id,
        lastMessageAt: v.lastAt,
        messageCount: v.count,
        preview: v.preview,
      }))
      .sort((a, b) => b.lastMessageAt.localeCompare(a.lastMessageAt));
  }
}

// ─── Local JSON-file backend ──────────────────────────────────────────────────

const LOCAL_DATA_DIR = join(process.cwd(), 'data', 'conversations');

class LocalMemoryStore implements MemoryStore {
  constructor() {
    if (!existsSync(LOCAL_DATA_DIR)) {
      mkdirSync(LOCAL_DATA_DIR, { recursive: true });
    }
  }

  private filePath(conversationId: string): string {
    // Sanitize: only allow alphanumeric and hyphens
    const safe = conversationId.replace(/[^a-zA-Z0-9-]/g, '');
    return join(LOCAL_DATA_DIR, `${safe}.jsonl`);
  }

  async save(message: MemoryMessage, _ctx?: StoreContext): Promise<void> {
    const line = JSON.stringify(message) + '\n';
    const path = this.filePath(message.conversationId);
    try {
      appendFileSync(path, line, 'utf8');
    } catch {
      // Ensure directory exists (might have been cleaned)
      mkdirSync(dirname(path), { recursive: true });
      appendFileSync(path, line, 'utf8');
    }
  }

  async loadHistory(
    conversationId: string,
    _ctx?: StoreContext,
    limit = 50,
  ): Promise<MemoryMessage[]> {
    const path = this.filePath(conversationId);
    if (!existsSync(path)) return [];
    const content = readFileSync(path, 'utf8');
    const lines = content.trim().split('\n').filter(Boolean);
    const messages: MemoryMessage[] = [];
    for (const line of lines) {
      try {
        messages.push(JSON.parse(line) as MemoryMessage);
      } catch {
        // Skip malformed lines
      }
    }
    return messages.slice(-limit);
  }

  async listConversations(_ctx?: StoreContext): Promise<ConversationSummary[]> {
    if (!existsSync(LOCAL_DATA_DIR)) return [];
    const files = readdirSync(LOCAL_DATA_DIR).filter((f) => f.endsWith('.jsonl'));
    const conversations: ConversationSummary[] = [];
    for (const file of files) {
      const id = file.replace('.jsonl', '');
      const content = readFileSync(join(LOCAL_DATA_DIR, file), 'utf8');
      const lines = content.trim().split('\n').filter(Boolean);
      if (lines.length === 0) continue;
      let lastAt = '';
      let preview = '';
      try {
        const last = JSON.parse(lines[lines.length - 1]) as MemoryMessage;
        lastAt = last.createdAt;
        // First user message as preview
        for (const line of lines) {
          const msg = JSON.parse(line) as MemoryMessage;
          if (msg.role === 'user') {
            preview = msg.content.slice(0, 80);
            break;
          }
        }
      } catch {
        lastAt = new Date().toISOString();
      }
      conversations.push({
        id,
        lastMessageAt: lastAt,
        messageCount: lines.length,
        preview,
      });
    }
    return conversations.sort((a, b) =>
      b.lastMessageAt.localeCompare(a.lastMessageAt),
    );
  }
}

// ─── Factory ───────────────────────────────────────────────────────────────────

let _store: MemoryStore | null = null;

/**
 * Get the active memory store.
 *
 * Uses Supabase when configured, falls back to local JSON files.
 * The local backend is used when:
 *   - NEXT_PUBLIC_DEMO_MODE is true AND no Supabase is configured
 *   - SOLO_LOCAL_MODE is true (explicit local mode for AMD deployment)
 */
export function getMemoryStore(): MemoryStore {
  if (_store) return _store;

  const isLocal =
    process.env.SOLO_LOCAL_MODE === 'true' ||
    (process.env.NEXT_PUBLIC_DEMO_MODE === 'true' &&
     !process.env.NEXT_PUBLIC_SUPABASE_URL);

  if (isLocal) {
    _store = new LocalMemoryStore();
  } else {
    _store = new SupabaseMemoryStore();
  }
  return _store;
}

/**
 * Generate a conversation ID.
 * Uses date + random suffix for uniqueness and sortability.
 */
export function generateConversationId(): string {
  const date = new Date().toISOString().slice(0, 10);
  const rand = Math.random().toString(36).slice(2, 8);
  return `${date}-${rand}`;
}
