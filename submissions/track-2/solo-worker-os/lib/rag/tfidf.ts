/**
 * Pure-TypeScript TF-IDF vector search engine.
 *
 * Zero external dependencies. Supports mixed Chinese/English queries:
 *  - English: lowercase -> split on non-alphanumerics -> drop stopwords.
 *  - Chinese: bi-gram of consecutive Han characters, dropping bi-grams that
 *    contain a function/question particle (是 / 什 / 么 / 吗 ...).
 *
 * Relevance is computed as cosine similarity between TF-IDF document vectors
 * and the query vector. Designed for small corpora (5-50 docs); no ANN.
 */

import { KNOWLEDGE_DOCS_SEED } from '../mock-supabase';

// ─── Public types ────────────────────────────────────────────────────────────

export interface SearchResult {
  docId: string;
  score: number;
  title: string;
  content: string;
  doc_type?: string;
  tags?: string[];
}

// ─── Tokenizer ───────────────────────────────────────────────────────────────

/** English stopwords. Includes the ones called out in the spec (the, is, a, an, what, are, my, ...). */
const ENGLISH_STOPWORDS = new Set<string>([
  'the', 'is', 'a', 'an', 'what', 'are', 'my', 'and', 'or', 'to', 'of', 'in',
  'on', 'for', 'with', 'i', 'you', 'your', 'yours', 'this', 'that', 'it', 'its',
  'as', 'at', 'by', 'be', 'do', 'how', 'which', 'who', 'when', 'where', 'why',
  'can', 'could', 'would', 'should', 'will', 'me', 'we', 'us', 'our', 'ours',
  'they', 'them', 'their', 'he', 'she', 'his', 'her', 'was', 'were', 'been',
  'being', 'have', 'has', 'had', 'does', 'did', 'about', 'into', 'from', 'up',
  'down', 'out', 'if', 'then', 'so', 'no', 'not', 'but', 'than', 'too', 'very',
  'just', 'please', 'tell', 'show', 'give', 'need', 'want', 'looking', 'find',
  'me', 'help',
]);

/**
 * Chinese function / question particles. Any bi-gram containing one of these
 * characters is dropped, which both trims noise and reproduces the spec example
 * ("我的标准付款条款是什么" -> [我的, 的标, 标准, 准付, 付款, 款条, 条款]).
 */
const CHINESE_STOP_CHARS = new Set<string>(
  '是什么吗呢啊吧了就也都还不没这那哪怎为何与或把被让给对向从到在上下里中们个之其而'.split('')
);

/** Han (CJK ideograph) test. Covers CJK Unified Ideographs + Extension A. */
function isHan(ch: string): boolean {
  const code = ch.charCodeAt(0);
  return (code >= 0x4e00 && code <= 0x9fff) || (code >= 0x3400 && code <= 0x4dbf);
}

/** ASCII alphanumeric (after lowercasing the input). */
function isAsciiAlnum(ch: string): boolean {
  return /[a-z0-9]/.test(ch);
}

/**
 * Tokenize mixed Chinese/English text.
 *
 * English example: "What are my standard payment terms?" -> [standard, payment, terms]
 * Chinese example: "我的标准付款条款是什么" -> [我的, 的标, 标准, 准付, 付款, 款条, 条款]
 */
export function tokenize(text: string): string[] {
  const tokens: string[] = [];
  const lower = text.toLowerCase();
  const len = lower.length;
  let i = 0;

  while (i < len) {
    const ch = lower[i];

    if (isHan(ch)) {
      // Collect the full run of Han characters, then bi-gram it.
      let j = i;
      while (j < len && isHan(lower[j])) j++;
      const run = lower.slice(i, j);

      if (run.length >= 2) {
        for (let k = 0; k < run.length - 1; k++) {
          const a = run[k];
          const b = run[k + 1];
          if (CHINESE_STOP_CHARS.has(a) || CHINESE_STOP_CHARS.has(b)) continue;
          tokens.push(a + b);
        }
      } else if (!CHINESE_STOP_CHARS.has(run)) {
        // Lone Han character (rare) — keep it if it isn't a particle.
        tokens.push(run);
      }
      i = j;
    } else if (isAsciiAlnum(ch)) {
      // Collect the full alphanumeric run as one English token.
      let j = i;
      while (j < len && isAsciiAlnum(lower[j])) j++;
      const word = lower.slice(i, j);
      if (word && !ENGLISH_STOPWORDS.has(word)) {
        tokens.push(word);
      }
      i = j;
    } else {
      // Punctuation / whitespace / other — separator, skip.
      i++;
    }
  }

  return tokens;
}

// ─── Index internals ─────────────────────────────────────────────────────────

interface InputDoc {
  id: string;
  title: string;
  content: string;
  doc_type?: string;
  tags?: string[];
}

interface IndexedDoc extends InputDoc {
  /** term -> raw count in this document */
  termFreq: Map<string, number>;
  /** total token count (for TF normalization) */
  tokenCount: number;
  /** term -> TF-IDF weight (populated by build()) */
  vector: Map<string, number>;
  /** L2 norm of the vector (populated by build()) */
  norm: number;
}

// ─── TfidfIndex ──────────────────────────────────────────────────────────────

export class TfidfIndex {
  private docs: IndexedDoc[] = [];
  /** term -> number of documents containing it (document frequency) */
  private df = new Map<string, number>();
  /** term -> inverse document frequency (populated by build()) */
  private idf = new Map<string, number>();
  private built = false;

  /**
   * When `seed` is true (default), auto-loads the 5 knowledge_docs seed data
   * from mock-supabase.ts, per the spec. Pass `false` (or use `TfidfIndex.empty()`)
   * to start with a clean slate — used by the mock client to rank arbitrary rows.
   */
  constructor(seed = true) {
    if (seed) {
      for (const doc of KNOWLEDGE_DOCS_SEED) {
        this.addDocument({
          id: doc.id,
          title: doc.title,
          content: doc.content,
          doc_type: doc.doc_type,
          tags: doc.tags,
        });
      }
    }
  }

  /** Create an empty index (no seed data). */
  static empty(): TfidfIndex {
    return new TfidfIndex(false);
  }

  /** Add a document to the index. Call `build()` once all docs are added. */
  addDocument(doc: InputDoc): void {
    // Title is duplicated to give it extra weight (matches are usually
    // title-driven), then content, tags and doc_type are folded in.
    const text = [
      doc.title,
      doc.title,
      doc.content,
      (doc.tags ?? []).join(' '),
      doc.doc_type ?? '',
    ].join(' ');

    const tokens = tokenize(text);
    const termFreq = new Map<string, number>();
    for (const t of tokens) {
      termFreq.set(t, (termFreq.get(t) ?? 0) + 1);
    }

    this.docs.push({
      ...doc,
      termFreq,
      tokenCount: tokens.length,
      vector: new Map(),
      norm: 0,
    });

    // Update document frequency for each distinct term.
    for (const term of termFreq.keys()) {
      this.df.set(term, (this.df.get(term) ?? 0) + 1);
    }
    this.built = false;
  }

  /** Build the TF-IDF vectors after all documents are added. */
  build(): void {
    const N = this.docs.length;
    this.idf.clear();

    // IDF = log(N / (1 + df)). A +1 is folded into the log — i.e.
    // log(1 + N / (1 + df)) — so that terms appearing in (almost) every
    // document keep a small positive weight instead of collapsing to 0 (or
    // going negative when df = N). Without this smoothing, common-but-meaningful
    // terms such as "payment" (present in 4 of 5 seed docs) would become
    // unsearchable, which breaks mixed-language queries that rely on the shared
    // English token. The variant is still monotonically decreasing in df, so
    // rare terms remain more discriminative than common ones.
    for (const [term, df] of this.df) {
      this.idf.set(term, Math.log(1 + N / (1 + df)));
    }

    // Build each document's TF-IDF vector and its L2 norm.
    for (const doc of this.docs) {
      const vector = new Map<string, number>();
      let sumSq = 0;
      const denom = Math.max(doc.tokenCount, 1);

      for (const [term, count] of doc.termFreq) {
        const tf = count / denom;
        const idf = this.idf.get(term) ?? Math.log(1 + N);
        const weight = tf * idf;
        vector.set(term, weight);
        sumSq += weight * weight;
      }

      doc.vector = vector;
      doc.norm = Math.sqrt(sumSq);
    }

    this.built = true;
  }

  /** Search for documents matching the query, return top-k results by cosine similarity. */
  search(query: string, topK = 4): SearchResult[] {
    if (!this.built) this.build();

    const qTokens = tokenize(query);
    if (qTokens.length === 0) return [];

    // Build the query TF vector (only over terms that exist in the corpus;
    // OOV terms cannot contribute to any document's dot product).
    const qFreq = new Map<string, number>();
    for (const t of qTokens) {
      qFreq.set(t, (qFreq.get(t) ?? 0) + 1);
    }
    const qTotal = qTokens.length;

    const qVec = new Map<string, number>();
    let qNorm = 0;
    for (const [term, count] of qFreq) {
      const idf = this.idf.get(term);
      if (idf === undefined) continue; // term not in any indexed document
      const tf = count / qTotal;
      const weight = tf * idf;
      qVec.set(term, weight);
      qNorm += weight * weight;
    }
    qNorm = Math.sqrt(qNorm);
    if (qNorm === 0) return [];

    // Cosine similarity against every document.
    const scored: Array<{ doc: IndexedDoc; score: number }> = [];
    for (const doc of this.docs) {
      if (doc.norm === 0) continue;
      let dot = 0;
      for (const [term, qw] of qVec) {
        const dw = doc.vector.get(term);
        if (dw !== undefined) dot += qw * dw;
      }
      if (dot === 0) continue;
      const score = dot / (qNorm * doc.norm);
      if (score > 0) scored.push({ doc, score });
    }

    scored.sort((a, b) => b.score - a.score);

    return scored.slice(0, topK).map(({ doc, score }) => ({
      docId: doc.id,
      score,
      title: doc.title,
      content: doc.content,
      doc_type: doc.doc_type,
      tags: doc.tags,
    }));
  }

  /** Get the number of indexed documents. */
  size(): number {
    return this.docs.length;
  }
}

// ─── Shared singleton (pre-seeded knowledge index) ───────────────────────────

let _sharedIndex: TfidfIndex | null = null;

/**
 * Lazily-built, cached TfidfIndex pre-seeded with the mock knowledge_docs.
 * Used by `searchKnowledge()` in demo mode.
 */
export function getKnowledgeIndex(): TfidfIndex {
  if (!_sharedIndex) {
    _sharedIndex = new TfidfIndex();
    _sharedIndex.build();
  }
  return _sharedIndex;
}

/** Convenience wrapper: search the shared pre-seeded knowledge index. */
export function searchKnowledgeIndex(query: string, topK = 4): SearchResult[] {
  return getKnowledgeIndex().search(query, topK);
}
