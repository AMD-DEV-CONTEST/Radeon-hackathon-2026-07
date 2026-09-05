-- Database schema for AI search tool
CREATE TABLE documents (
    id SERIAL PRIMARY KEY,
    path VARCHAR(512) NOT NULL,
    content TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_documents_content ON documents USING gin(to_tsvector(content));
