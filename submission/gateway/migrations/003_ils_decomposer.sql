-- ILS v2.3: Vectorized Dynamic Task Decomposition Engine
-- Stores decomposition patterns with embeddings for semantic retrieval.

CREATE TABLE IF NOT EXISTS decomposition_patterns (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    intent_pattern text NOT NULL,
    project text NOT NULL DEFAULT 'default',
    dag jsonb NOT NULL DEFAULT '[]'::jsonb,
    embedding double precision[] NOT NULL DEFAULT '{}',
    hit_count integer NOT NULL DEFAULT 0 CHECK (hit_count >= 0),
    success_count integer NOT NULL DEFAULT 0 CHECK (success_count >= 0),
    failure_count integer NOT NULL DEFAULT 0 CHECK (failure_count >= 0),
    last_hit_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_decomp_patterns_project ON decomposition_patterns(project);
CREATE INDEX IF NOT EXISTS idx_decomp_patterns_hit_count ON decomposition_patterns(hit_count DESC);

-- Per-task embedding cache for fast re-lookup.
CREATE TABLE IF NOT EXISTS task_embeddings (
    task_id uuid PRIMARY KEY,
    goal text NOT NULL,
    embedding double precision[] NOT NULL DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_task_embeddings_created ON task_embeddings(created_at DESC);
