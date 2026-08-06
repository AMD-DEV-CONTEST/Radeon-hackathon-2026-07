import type { Db } from "../db/open-db.js";
import { chunkText } from "./chunk.js";
import {
  bufferToFloat32,
  cosineSimilarity,
  float32ToBuffer,
  type EmbeddingClient
} from "./embeddings.js";
import {
  corpusFingerprint,
  loadRagCorpus,
  type CorpusDocument
} from "./corpus.js";

export const RAG_RETRIEVAL_VERSION = "rag-embedding-local-1.0.0";

export type RagHit = {
  chunkId: string;
  documentId: string;
  sourcePath: string;
  title: string;
  licenseId: string;
  content: string;
  score: number;
  chunkIndex: number;
};

export type RagRetrieveResult = {
  queryId: string;
  retrievalVersion: string;
  embeddingModel: string;
  embeddingKind: "vllm" | "hash";
  hits: RagHit[];
  note: string;
};

type StoredChunk = {
  id: string;
  document_id: string;
  chunk_index: number;
  content: string;
  embedding: Buffer;
  embedding_dims: number;
  source_path: string;
  title: string;
  license_id: string;
};

/**
 * Build or refresh the vector index when corpus or embedding model changes.
 */
export async function ensureRagIndex(
  db: Db,
  embedding: EmbeddingClient
): Promise<{ rebuilt: boolean; chunkCount: number }> {
  const docs = await loadRagCorpus();
  if (docs.length === 0) {
    return { rebuilt: false, chunkCount: 0 };
  }
  const hash = corpusFingerprint(docs);
  const meta = db
    .prepare(
      `SELECT corpus_hash, embedding_model, chunk_count FROM rag_index_meta WHERE id = 1`
    )
    .get() as
    | { corpus_hash: string; embedding_model: string; chunk_count: number }
    | undefined;

  if (
    meta &&
    meta.corpus_hash === hash &&
    meta.embedding_model === embedding.modelId &&
    meta.chunk_count > 0
  ) {
    return { rebuilt: false, chunkCount: meta.chunk_count };
  }

  const now = new Date().toISOString();
  const prepared: Array<{
    doc: CorpusDocument;
    chunks: ReturnType<typeof chunkText>;
  }> = docs.map((doc) => ({
    doc,
    chunks: chunkText(doc.body)
  }));

  const allTexts: string[] = [];
  for (const item of prepared) {
    for (const chunk of item.chunks) {
      // Title prefix improves retrieval for short policy cards.
      allTexts.push(`${item.doc.title}\n${chunk.content}`);
    }
  }

  // Batch embed (vLLM may prefer moderate batch sizes).
  const BATCH = 16;
  const vectors: number[][] = [];
  for (let i = 0; i < allTexts.length; i += BATCH) {
    const batch = allTexts.slice(i, i + BATCH);
    const embedded = await embedding.embed(batch);
    vectors.push(...embedded);
  }
  if (vectors.length !== allTexts.length) {
    throw new Error("RAG embed batch size mismatch");
  }
  if (embedding.dimensions === 0 && vectors[0]) {
    embedding.dimensions = vectors[0].length;
  }

  db.exec("BEGIN IMMEDIATE");
  try {
    db.exec(`DELETE FROM rag_chunks`);
    db.exec(`DELETE FROM rag_documents`);
    db.exec(`DELETE FROM rag_index_meta`);

    let vectorCursor = 0;
    let chunkCount = 0;
    for (const item of prepared) {
      db.prepare(
        `INSERT INTO rag_documents
         (id, source_path, title, license_id, content_hash, created_at)
         VALUES (?, ?, ?, ?, ?, ?)`
      ).run(
        item.doc.id,
        item.doc.sourcePath,
        item.doc.title,
        item.doc.licenseId,
        item.doc.contentHash,
        now
      );
      for (const chunk of item.chunks) {
        const vec = vectors[vectorCursor++]!;
        const chunkId = `${item.doc.id}#${chunk.index}`;
        db.prepare(
          `INSERT INTO rag_chunks
           (id, document_id, chunk_index, content, token_estimate, embedding, embedding_dims, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)`
        ).run(
          chunkId,
          item.doc.id,
          chunk.index,
          chunk.content,
          chunk.tokenEstimate,
          float32ToBuffer(vec),
          vec.length,
          now
        );
        chunkCount += 1;
      }
    }

    db.prepare(
      `INSERT INTO rag_index_meta
       (id, corpus_hash, embedding_model, embedding_dims, retrieval_version, chunk_count, built_at)
       VALUES (1, ?, ?, ?, ?, ?, ?)`
    ).run(
      hash,
      embedding.modelId,
      embedding.dimensions || (vectors[0]?.length ?? 0),
      RAG_RETRIEVAL_VERSION,
      chunkCount,
      now
    );
    db.exec("COMMIT");
    return { rebuilt: true, chunkCount };
  } catch (error) {
    db.exec("ROLLBACK");
    throw error;
  }
}

export async function retrieveFromRagIndex(
  db: Db,
  embedding: EmbeddingClient,
  input: { query: string; topK?: number }
): Promise<RagRetrieveResult> {
  const topK = Math.min(5, Math.max(1, input.topK ?? 3));
  const query = input.query.trim();
  const queryId = `rq-${Date.now().toString(36)}`;

  await ensureRagIndex(db, embedding);

  if (!query) {
    return {
      queryId,
      retrievalVersion: RAG_RETRIEVAL_VERSION,
      embeddingModel: embedding.modelId,
      embeddingKind: embedding.kind,
      hits: [],
      note: "empty_query"
    };
  }

  const [queryVec] = await embedding.embed([query]);
  if (!queryVec) {
    return {
      queryId,
      retrievalVersion: RAG_RETRIEVAL_VERSION,
      embeddingModel: embedding.modelId,
      embeddingKind: embedding.kind,
      hits: [],
      note: "embed_failed"
    };
  }

  const rows = db
    .prepare(
      `SELECT c.id, c.document_id, c.chunk_index, c.content, c.embedding, c.embedding_dims,
              d.source_path, d.title, d.license_id
       FROM rag_chunks c
       JOIN rag_documents d ON d.id = c.document_id`
    )
    .all() as StoredChunk[];

  const scored = rows
    .map((row) => {
      const vec = bufferToFloat32(row.embedding);
      return {
        chunkId: row.id,
        documentId: row.document_id,
        sourcePath: row.source_path,
        title: row.title,
        licenseId: row.license_id,
        content: row.content,
        chunkIndex: row.chunk_index,
        score: cosineSimilarity(queryVec, vec)
      };
    })
    .sort((a, b) => b.score - a.score || a.chunkId.localeCompare(b.chunkId));

  // Soft threshold: keep near-top relative scores so hash embed still works.
  const best = scored[0]?.score ?? 0;
  const minScore = Math.max(0.05, best * 0.35);
  const hits = scored
    .filter((h) => h.score >= minScore)
    .slice(0, topK);

  return {
    queryId,
    retrievalVersion: RAG_RETRIEVAL_VERSION,
    embeddingModel: embedding.modelId,
    embeddingKind: embedding.kind,
    hits,
    note:
      hits.length === 0
        ? "no_relevant_chunks"
        : embedding.kind === "hash"
          ? "hash_embedding_offline_not_model_evidence"
          : "vllm_embedding_retrieval"
  };
}
