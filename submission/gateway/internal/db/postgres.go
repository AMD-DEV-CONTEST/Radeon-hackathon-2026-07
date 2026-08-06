package db

import (
	"context"
	"fmt"
	"os"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

// Pool is the shared PostgreSQL connection pool.
var Pool *pgxpool.Pool

// DSNFromEnv returns the PostgreSQL connection string.
// Reads DATABASE_URL first; falls back to individual env vars.
func DSNFromEnv() string {
	if dsn := os.Getenv("DATABASE_URL"); dsn != "" {
		return dsn
	}
	return fmt.Sprintf(
		"postgres://%s:%s@%s:%s/%s?sslmode=%s",
		envDefault("DB_USER", "postgres"),
		os.Getenv("DB_PASSWORD"),
		envDefault("DB_HOST", "127.0.0.1"),
		envDefault("DB_PORT", "5432"),
		envDefault("DB_NAME", "unionagents"),
		envDefault("DB_SSLMODE", "disable"),
	)
}

// Connect creates and validates a connection pool.
func Connect(ctx context.Context) (*pgxpool.Pool, error) {
	dsn := DSNFromEnv()
	poolCfg, err := pgxpool.ParseConfig(dsn)
	if err != nil {
		return nil, fmt.Errorf("parse config: %w", err)
	}

	poolCfg.MaxConns = 20
	poolCfg.MinConns = 2
	poolCfg.MaxConnLifetime = 30 * time.Minute
	poolCfg.MaxConnIdleTime = 5 * time.Minute

	pool, err := pgxpool.NewWithConfig(ctx, poolCfg)
	if err != nil {
		return nil, fmt.Errorf("create pool: %w", err)
	}

	if err := pool.Ping(ctx); err != nil {
		pool.Close()
		return nil, fmt.Errorf("ping: %w", err)
	}

	Pool = pool
	return pool, nil
}

// Close shuts down the connection pool.
func Close() {
	if Pool != nil {
		Pool.Close()
	}
}

// RunMigrations executes the base schema creation.
// In production, this is idempotent (CREATE IF NOT EXISTS).
func RunMigrations(ctx context.Context) error {
	for _, stmt := range migrationStatements {
		if _, err := Pool.Exec(ctx, stmt); err != nil {
			return fmt.Errorf("migration: %w", err)
		}
	}
	return nil
}

func envDefault(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

// migrationStatements are the minimal required tables for orchestrator + gateway.
var migrationStatements = []string{
	// Extensions
	`CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public`,
	`CREATE EXTENSION IF NOT EXISTS "uuid-ossp"`,

	// updated_at trigger function
	`CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql`,

	// Agents
	`CREATE TABLE IF NOT EXISTS agents (
    id uuid DEFAULT gen_random_uuid() NOT NULL PRIMARY KEY,
    name text NOT NULL,
    agent_type text NOT NULL,
    host_id text NOT NULL,
    status text DEFAULT 'online' NOT NULL,
    os text,
    shell text,
    python_version text,
    workspace_root text,
    available_commands jsonb DEFAULT '[]' NOT NULL,
    capabilities jsonb DEFAULT '{}' NOT NULL,
    network_capabilities jsonb DEFAULT '[]' NOT NULL,
    model_policy text,
    max_concurrency integer DEFAULT 1 NOT NULL,
    last_heartbeat_at timestamptz,
    last_poll_at timestamptz,
    preferred_agent_id text,
    created_at timestamptz DEFAULT now() NOT NULL,
    updated_at timestamptz DEFAULT now() NOT NULL
)`,

	// Migration: add failure tracking columns + update status constraint (v1.1 — circuit breaker)
	`DO $$ BEGIN
		ALTER TABLE agents ADD COLUMN IF NOT EXISTS consecutive_failures integer DEFAULT 0;
	EXCEPTION WHEN duplicate_column THEN NULL;
	END $$`,
	`DO $$ BEGIN
		ALTER TABLE agents ADD COLUMN IF NOT EXISTS total_failures integer DEFAULT 0;
	EXCEPTION WHEN duplicate_column THEN NULL;
	END $$`,
	`ALTER TABLE agents DROP CONSTRAINT IF EXISTS agents_status_check`,
	`ALTER TABLE agents ADD CONSTRAINT agents_status_check CHECK (status = ANY (ARRAY[
		'online','healthy','degraded','offline','unhealthy','dead','draining','disabled'
	]))`,
	`ALTER TABLE agents DROP CONSTRAINT IF EXISTS agents_agent_type_check`,
	`ALTER TABLE agents ADD CONSTRAINT agents_agent_type_check CHECK (agent_type ~ '^[a-z0-9_-]{1,64}$')`,

	// Migration: binding_status column (Phase 2.6 — phase-change hook).
	// Carries the agent's current role binding state (ready/degraded/failed).
	// Note: AgentRegister already writes this column; this ALTER makes the
	// schema match the handler so those writes stop erroring.
	`DO $$ BEGIN
		ALTER TABLE agents ADD COLUMN IF NOT EXISTS binding_status text DEFAULT 'ready';
	EXCEPTION WHEN duplicate_column THEN NULL;
	END $$`,

	// Phase change (Phase 2.6 — keeper↔worker role transitions).
	// Agents carry pending_role + pending_until directly; the scanner
	// sets them when trigger conditions fire and applies the change
	// after the grace period if conditions still hold.
	`DO $$ BEGIN
		ALTER TABLE agents ADD COLUMN IF NOT EXISTS pending_role text;
	EXCEPTION WHEN duplicate_column THEN NULL;
	END $$`,
	`DO $$ BEGIN
		ALTER TABLE agents ADD COLUMN IF NOT EXISTS pending_until timestamptz;
	EXCEPTION WHEN duplicate_column THEN NULL;
	END $$`,

	// Dead letter queue (v1.2 — P1-5)
	`CREATE TABLE IF NOT EXISTS dead_letter (
		id uuid DEFAULT gen_random_uuid() NOT NULL PRIMARY KEY,
		original_task_id uuid NOT NULL,
		title text NOT NULL,
		description text DEFAULT '' NOT NULL,
		task_type text NOT NULL,
		priority integer NOT NULL,
		max_attempts integer NOT NULL,
		payload jsonb DEFAULT '{}' NOT NULL,
		required_capabilities jsonb DEFAULT '{}' NOT NULL,
		acceptance_check jsonb DEFAULT '{}' NOT NULL,
		created_by text NOT NULL,
		target_agent_id uuid,
		last_status text NOT NULL,
		last_lease_owner uuid,
		failure_reason text,
		failure_summary text,
		attempt_count integer DEFAULT 0 NOT NULL,
		events_summary jsonb DEFAULT '[]' NOT NULL,
		original_created_at timestamptz,
		original_updated_at timestamptz,
		archived_at timestamptz DEFAULT now() NOT NULL,
		created_at timestamptz DEFAULT now() NOT NULL
	)`,
	`CREATE INDEX IF NOT EXISTS idx_dead_letter_original_task ON dead_letter (original_task_id)`,
	`CREATE INDEX IF NOT EXISTS idx_dead_letter_archived_at ON dead_letter (archived_at)`,

	// Tasks
	`CREATE TABLE IF NOT EXISTS tasks (
    id uuid DEFAULT gen_random_uuid() NOT NULL PRIMARY KEY,
    parent_task_id uuid,
    title text NOT NULL,
    description text DEFAULT '' NOT NULL,
    task_type text NOT NULL,
    status text DEFAULT 'queued' NOT NULL,
    priority integer DEFAULT 100 NOT NULL,
    dependencies jsonb DEFAULT '[]' NOT NULL,
    required_capabilities jsonb DEFAULT '{}' NOT NULL,
    acceptance_check jsonb DEFAULT '{}' NOT NULL,
    payload jsonb DEFAULT '{}' NOT NULL,
    max_attempts integer DEFAULT 3 NOT NULL,
    lease_owner uuid,
    lease_expires_at timestamptz,
    blocked_until timestamptz,
    created_by text DEFAULT 'system' NOT NULL,
    target_agent_id uuid,
    created_at timestamptz DEFAULT now() NOT NULL,
    updated_at timestamptz DEFAULT now() NOT NULL,
    finished_at timestamptz
)`,

	// Migration: handoff columns (Phase 2.5 — timeout task handoff to
	// another agent/base). handoff_count caps recursive handoff at 1.
	`DO $$ BEGIN
		ALTER TABLE tasks ADD COLUMN IF NOT EXISTS handoff_count integer DEFAULT 0;
	EXCEPTION WHEN duplicate_column THEN NULL;
	END $$`,
	`DO $$ BEGIN
		ALTER TABLE tasks ADD COLUMN IF NOT EXISTS handoff_from_agent text;
	EXCEPTION WHEN duplicate_column THEN NULL;
	END $$`,
	`DO $$ BEGIN
		ALTER TABLE tasks ADD COLUMN IF NOT EXISTS partial_result jsonb;
	EXCEPTION WHEN duplicate_column THEN NULL;
	END $$`,

	// Task Attempts
	`CREATE TABLE IF NOT EXISTS task_attempts (
    id uuid DEFAULT gen_random_uuid() NOT NULL PRIMARY KEY,
    task_id uuid NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    attempt_no integer NOT NULL,
    agent_id uuid REFERENCES agents(id) ON DELETE SET NULL,
    lease_expires_at timestamptz,
    heartbeat_at timestamptz,
    started_at timestamptz,
    finished_at timestamptz,
    status text NOT NULL,
    exit_code integer,
    error_type text,
    error_message text,
    blocked_until timestamptz,
    summary text,
    metadata jsonb DEFAULT '{}' NOT NULL,
    created_at timestamptz DEFAULT now() NOT NULL,
    updated_at timestamptz DEFAULT now() NOT NULL
)`,

	// Events
	`CREATE TABLE IF NOT EXISTS events (
    id uuid DEFAULT gen_random_uuid() NOT NULL PRIMARY KEY,
    task_id uuid REFERENCES tasks(id) ON DELETE CASCADE,
    attempt_id uuid REFERENCES task_attempts(id) ON DELETE SET NULL,
    agent_id uuid REFERENCES agents(id) ON DELETE SET NULL,
    event_type text NOT NULL,
    message text DEFAULT '' NOT NULL,
    level text DEFAULT 'info' NOT NULL,
    payload jsonb DEFAULT '{}' NOT NULL,
    created_at timestamptz DEFAULT now() NOT NULL
)`,

	// Active Tokens (for gateway auth)
	`CREATE TABLE IF NOT EXISTS active_tokens (
    token text NOT NULL PRIMARY KEY,
    expires_at timestamptz NOT NULL,
    created_at timestamptz DEFAULT now() NOT NULL,
    updated_at timestamptz DEFAULT now() NOT NULL
)`,

	// cleanup_expired_tokens function
	`CREATE OR REPLACE FUNCTION cleanup_expired_tokens()
RETURNS void AS $$
BEGIN
    DELETE FROM active_tokens WHERE expires_at < now();
END;
$$ LANGUAGE plpgsql`,

	// Gateway agent identity persistence (survives restarts)
	`CREATE TABLE IF NOT EXISTS gateway_agent_identities (
		agent_id  TEXT PRIMARY KEY,
		app_id    TEXT NOT NULL,
		agent_name TEXT NOT NULL,
		secret    TEXT NOT NULL,
		registered_at TIMESTAMPTZ DEFAULT now() NOT NULL,
		expires_at    TIMESTAMPTZ NOT NULL,
		updated_at    TIMESTAMPTZ DEFAULT now() NOT NULL
	)`,

	// Indexes
	`CREATE INDEX IF NOT EXISTS idx_tasks_status_priority ON tasks (status, priority, created_at)`,
	`CREATE INDEX IF NOT EXISTS idx_tasks_lease_expires ON tasks (lease_expires_at) WHERE status IN ('leased', 'running')`,
	`CREATE INDEX IF NOT EXISTS idx_tasks_target_agent ON tasks (target_agent_id) WHERE target_agent_id IS NOT NULL`,
	`CREATE INDEX IF NOT EXISTS idx_task_attempts_task ON task_attempts (task_id, attempt_no DESC)`,
	`CREATE INDEX IF NOT EXISTS idx_events_task_created ON events (task_id, created_at)`,
	`CREATE INDEX IF NOT EXISTS idx_events_created_desc ON events (created_at DESC)`,
	`CREATE INDEX IF NOT EXISTS idx_active_tokens_expires_at ON active_tokens (expires_at)`,

	// Life Memory nodes (Phase 3.1 — persistent agent memory).
	// tags is text[] with a GIN index for AND-tag queries; created_at has
	// a btree index for the timeline range scan.
	`CREATE TABLE IF NOT EXISTS life_memory_nodes (
		id uuid DEFAULT gen_random_uuid() NOT NULL PRIMARY KEY,
		title text NOT NULL,
		content text NOT NULL,
		tags text[] DEFAULT '{}' NOT NULL,
		created_at timestamptz DEFAULT now() NOT NULL,
		updated_at timestamptz DEFAULT now() NOT NULL
	)`,
	`CREATE INDEX IF NOT EXISTS idx_life_memory_tags ON life_memory_nodes USING GIN (tags)`,
	`CREATE INDEX IF NOT EXISTS idx_life_memory_created ON life_memory_nodes (created_at)`,
}
