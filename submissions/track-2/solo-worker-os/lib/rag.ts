import { createServerClient } from './supabase-server';
import type { SupabaseClient } from '@supabase/supabase-js';
import { searchKnowledgeIndex, type SearchResult } from './rag/tfidf';

export type { SearchResult } from './rag/tfidf';

const DEMO_MODE = process.env.NEXT_PUBLIC_DEMO_MODE === 'true';

export interface KnowledgeDoc {
  id: string;
  title: string;
  content: string;
  doc_type: string;
  tags: string[];
  created_at: string;
}

/**
 * Full-text search over knowledge_docs.
 *
 * - DEMO_MODE: uses the pure-TypeScript TF-IDF vector index (lib/rag/tfidf.ts),
 *   supporting mixed Chinese/English queries with zero external dependencies.
 * - Otherwise: uses Supabase `textSearch` (websearch) as before.
 *
 * Uses user client if provided (respects RLS), otherwise service client.
 * Returns `SearchResult[]` (docId / score + title / content / doc_type / tags).
 */
export async function searchKnowledge(
  query: string,
  limit = 4,
  supabaseClient?: SupabaseClient
): Promise<SearchResult[]> {
  if (!query.trim()) return [];

  if (DEMO_MODE) {
    return searchKnowledgeIndex(query.trim(), limit);
  }

  const supabase = supabaseClient ?? createServerClient();
  const { data } = await supabase
    .from('knowledge_docs')
    .select('id, title, content, doc_type, tags, created_at')
    .textSearch('content', query.trim(), { type: 'websearch', config: 'simple' })
    .limit(limit);
  const docs = (data as KnowledgeDoc[]) ?? [];
  return docs.map((d) => ({
    docId: d.id,
    score: 1,
    title: d.title,
    content: d.content,
    doc_type: d.doc_type,
    tags: d.tags,
  }));
}

/** Save a new document to the knowledge base. */
export async function saveDocument(
  title: string,
  content: string,
  doc_type: string,
  tags: string[] = []
): Promise<KnowledgeDoc> {
  const supabase = createServerClient();
  const { data, error } = await supabase
    .from('knowledge_docs')
    .insert({ title, content, doc_type, tags })
    .select()
    .single();
  if (error) throw new Error(error.message);
  return data as KnowledgeDoc;
}

/** List all documents, newest first. */
export async function listDocuments(): Promise<KnowledgeDoc[]> {
  const supabase = createServerClient();
  const { data } = await supabase
    .from('knowledge_docs')
    .select('id, title, content, doc_type, tags, created_at')
    .order('created_at', { ascending: false });
  return (data as KnowledgeDoc[]) ?? [];
}

/** Delete a document by id. */
export async function deleteDocument(id: string): Promise<void> {
  const supabase = createServerClient();
  const { error } = await supabase.from('knowledge_docs').delete().eq('id', id);
  if (error) throw new Error(error.message);
}

/**
 * Build a RAG context block to inject into the system prompt.
 * Returns an empty string when no relevant docs are found.
 */
export function buildRagContext(docs: KnowledgeDoc[]): string {
  if (docs.length === 0) return '';
  const snippets = docs.map((d) =>
    `[${d.doc_type.toUpperCase()}] ${d.title}\n${d.content.slice(0, 600)}${d.content.length > 600 ? '…' : ''}`
  );
  return `\n\n--- Relevant knowledge base entries ---\n${snippets.join('\n\n---\n')}\n--- End of knowledge base entries ---\n`;
}
