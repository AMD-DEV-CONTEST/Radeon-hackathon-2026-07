/**
 * Migration 004: local RAG corpus chunks + embedding vectors.
 */
export const MIGRATION_004_NAME = "local_rag_vector_index";
export const MIGRATION_004_ID = 4;

export const MIGRATION_004_SQL = `
CREATE TABLE IF NOT EXISTS rag_index_meta (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  corpus_hash TEXT NOT NULL,
  embedding_model TEXT NOT NULL,
  embedding_dims INTEGER NOT NULL,
  retrieval_version TEXT NOT NULL,
  chunk_count INTEGER NOT NULL,
  built_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rag_documents (
  id TEXT PRIMARY KEY,
  source_path TEXT NOT NULL,
  title TEXT NOT NULL,
  license_id TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rag_chunks (
  id TEXT PRIMARY KEY,
  document_id TEXT NOT NULL REFERENCES rag_documents(id),
  chunk_index INTEGER NOT NULL,
  content TEXT NOT NULL,
  token_estimate INTEGER NOT NULL,
  embedding BLOB NOT NULL,
  embedding_dims INTEGER NOT NULL,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_rag_chunks_document
  ON rag_chunks(document_id);
`;
