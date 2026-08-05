-- Order tracking table (maps to OrderTracking entity)
CREATE TABLE IF NOT EXISTS order_tracking (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    tracking_number VARCHAR(255) NOT NULL UNIQUE,
    status          VARCHAR(255) NOT NULL,
    origin          VARCHAR(255) NOT NULL,
    destination     VARCHAR(255) NOT NULL,
    sender          VARCHAR(255) NOT NULL,
    recipient       VARCHAR(255) NOT NULL,
    estimated_delivery TIMESTAMP,
    created_at      TIMESTAMP NOT NULL,
    updated_at      TIMESTAMP
);

-- Chat sessions table (used by SessionService)
CREATE TABLE IF NOT EXISTS chat_sessions (
    session_id   UUID PRIMARY KEY,
    created_at   TIMESTAMP NOT NULL,
    last_activity TIMESTAMP NOT NULL,
    metadata     TEXT
);

-- Vector store table for RAG embeddings (H2-compatible, stores embedding as TEXT)
CREATE TABLE IF NOT EXISTS vector_store (
    id        UUID PRIMARY KEY,
    content   TEXT NOT NULL,
    metadata  TEXT,
    embedding TEXT
);
