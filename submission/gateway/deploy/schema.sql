--
-- PostgreSQL database dump
--

\restrict oQaJK3Ow0yANLmE1fOHn0sb99uT7oVH2eCgVhyOpq2vvcCpIHd6Bul4L4UmOZRh

-- Dumped from database version 15.18
-- Dumped by pg_dump version 16.14 (Ubuntu 16.14-0ubuntu0.24.04.1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: pgcrypto; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public;


--
-- Name: EXTENSION pgcrypto; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION pgcrypto IS 'cryptographic functions';


--
-- Name: vector; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;


--
-- Name: EXTENSION vector; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION vector IS 'vector data type and ivfflat and hnsw access methods';


--
-- Name: cleanup_expired_tokens(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.cleanup_expired_tokens() RETURNS void
    LANGUAGE plpgsql
    AS $$
BEGIN
    DELETE FROM active_tokens WHERE expires_at < now();
END;
$$;


--
-- Name: update_updated_at_column(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.update_updated_at_column() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: active_tokens; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.active_tokens (
    token text NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: agents; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agents (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    name text NOT NULL,
    agent_type text NOT NULL,
    host_id text NOT NULL,
    status text DEFAULT 'online'::text NOT NULL,
    os text,
    shell text,
    binding_status text,
    python_version text,
    workspace_root text,
    available_commands jsonb DEFAULT '[]'::jsonb NOT NULL,
    capabilities jsonb DEFAULT '{}'::jsonb NOT NULL,
    network_capabilities jsonb DEFAULT '[]'::jsonb NOT NULL,
    model_policy text,
    max_concurrency integer DEFAULT 1 NOT NULL,
    last_heartbeat_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    preferred_agent_id text,
    last_poll_at timestamp with time zone,
    CONSTRAINT agents_agent_type_check CHECK ((agent_type = ANY (ARRAY['claude_code'::text, 'codex'::text, 'reasonix'::text, 'opencode'::text, 'hermes'::text]))),
    CONSTRAINT agents_max_concurrency_check CHECK ((max_concurrency > 0)),
    CONSTRAINT agents_os_check CHECK ((os = ANY (ARRAY['windows'::text, 'linux'::text, 'darwin'::text, 'unknown'::text]))),
    CONSTRAINT agents_status_check CHECK ((status = ANY (ARRAY['online'::text, 'offline'::text, 'draining'::text, 'disabled'::text, 'degraded'::text])))
);

-- Migration for existing databases (run manually if needed):
-- ALTER TABLE public.agents ADD COLUMN IF NOT EXISTS binding_status text;
-- ALTER TABLE public.agents DROP CONSTRAINT IF EXISTS agents_agent_type_check;
-- ALTER TABLE public.agents ADD CONSTRAINT agents_agent_type_check CHECK ((agent_type = ANY (ARRAY['claude_code'::text, 'codex'::text, 'reasonix'::text, 'opencode'::text, 'hermes'::text])));


--
-- Name: artifacts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.artifacts (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    task_id uuid NOT NULL,
    attempt_id uuid,
    artifact_type text NOT NULL,
    uri text NOT NULL,
    sha256 text,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT artifacts_artifact_type_check CHECK ((artifact_type = ANY (ARRAY['patch'::text, 'log'::text, 'test_result'::text, 'screenshot'::text, 'report'::text, 'workspace_snapshot'::text, 'other'::text])))
);


--
-- Name: cases; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cases (
    case_id text NOT NULL,
    title text NOT NULL,
    description text DEFAULT ''::text NOT NULL,
    category text DEFAULT 'general'::text NOT NULL,
    tags text[] DEFAULT '{}'::text[] NOT NULL,
    content jsonb DEFAULT '{}'::jsonb NOT NULL,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    embedding public.vector(1024),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: decomposition_patterns; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.decomposition_patterns (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    intent_pattern text NOT NULL,
    project text DEFAULT 'default'::text NOT NULL,
    dag jsonb DEFAULT '[]'::jsonb NOT NULL,
    embedding double precision[] DEFAULT '{}'::double precision[] NOT NULL,
    hit_count integer DEFAULT 0 NOT NULL,
    success_count integer DEFAULT 0 NOT NULL,
    failure_count integer DEFAULT 0 NOT NULL,
    last_hit_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT decomposition_patterns_failure_count_check CHECK ((failure_count >= 0)),
    CONSTRAINT decomposition_patterns_hit_count_check CHECK ((hit_count >= 0)),
    CONSTRAINT decomposition_patterns_success_count_check CHECK ((success_count >= 0))
);


--
-- Name: events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.events (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    task_id uuid,
    attempt_id uuid,
    agent_id uuid,
    event_type text NOT NULL,
    message text DEFAULT ''::text NOT NULL,
    level text DEFAULT 'info'::text NOT NULL,
    payload jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT events_level_check CHECK ((level = ANY (ARRAY['debug'::text, 'info'::text, 'warn'::text, 'error'::text])))
);


--
-- Name: hub_context_snapshots; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.hub_context_snapshots (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    hub_session_id uuid NOT NULL,
    summary text DEFAULT ''::text NOT NULL,
    task_ids jsonb DEFAULT '[]'::jsonb NOT NULL,
    token_estimate integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT hub_context_snapshots_token_estimate_check CHECK ((token_estimate >= 0))
);


--
-- Name: hub_sessions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.hub_sessions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    title text NOT NULL,
    objective text DEFAULT ''::text NOT NULL,
    status text DEFAULT 'active'::text NOT NULL,
    model_policy text,
    owner text DEFAULT 'system'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    closed_at timestamp with time zone,
    CONSTRAINT hub_sessions_status_check CHECK ((status = ANY (ARRAY['active'::text, 'paused'::text, 'completed'::text, 'cancelled'::text])))
);


--
-- Name: ils_audit_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ils_audit_log (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    event_type text NOT NULL,
    task_id text,
    gate_id text,
    failure_code text,
    blocked boolean DEFAULT false NOT NULL,
    payload jsonb DEFAULT '{}'::jsonb NOT NULL,
    ils_version text DEFAULT '2.2'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: machine_sessions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.machine_sessions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    machine_id uuid NOT NULL,
    task_id uuid,
    agent_id uuid,
    session_id text NOT NULL,
    agent_type text NOT NULL,
    command jsonb DEFAULT '[]'::jsonb NOT NULL,
    cwd text,
    status text DEFAULT 'created'::text NOT NULL,
    pid integer,
    exit_code integer,
    log_uri text,
    started_at timestamp with time zone,
    ended_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT machine_sessions_status_check CHECK ((status = ANY (ARRAY['created'::text, 'running'::text, 'exited'::text, 'failed'::text, 'cancelled'::text])))
);


--
-- Name: machines; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.machines (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    name text NOT NULL,
    host text NOT NULL,
    launcher_port integer DEFAULT 9001 NOT NULL,
    status text DEFAULT 'offline'::text NOT NULL,
    os text,
    capabilities jsonb DEFAULT '{}'::jsonb NOT NULL,
    last_seen_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    ssh_host text,
    ssh_port integer DEFAULT 22 NOT NULL,
    ssh_user text DEFAULT 'root'::text NOT NULL,
    ssh_key_path text,
    wake_cmd text,
    always_on boolean DEFAULT false NOT NULL,
    wake_note text,
    CONSTRAINT machines_launcher_port_check CHECK ((launcher_port > 0)),
    CONSTRAINT machines_status_check CHECK ((status = ANY (ARRAY['online'::text, 'offline'::text, 'draining'::text])))
);


--
-- Name: ownership_registry; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ownership_registry (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    module_id text NOT NULL,
    owner_agent_id text NOT NULL,
    scope text DEFAULT ''::text NOT NULL,
    lease_duration_seconds integer,
    claimed_at timestamp with time zone DEFAULT now() NOT NULL,
    released_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: schema_migrations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.schema_migrations (
    filename text NOT NULL,
    applied_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: session_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.session_events (
    id integer NOT NULL,
    session_id character varying(64) NOT NULL,
    seq integer NOT NULL,
    msg_id character varying(64),
    agent_id character varying(128),
    type character varying(32),
    payload jsonb DEFAULT '{}'::jsonb,
    "timestamp" timestamp with time zone DEFAULT now()
);


--
-- Name: session_events_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.session_events_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: session_events_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.session_events_id_seq OWNED BY public.session_events.id;


--
-- Name: session_rounds; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.session_rounds (
    id integer NOT NULL,
    session_id character varying(64) NOT NULL,
    round_id integer NOT NULL,
    leader_instruction text DEFAULT ''::text,
    participant_assignments jsonb DEFAULT '{}'::jsonb,
    agent_outputs jsonb DEFAULT '{}'::jsonb,
    artifacts jsonb DEFAULT '[]'::jsonb,
    blockers jsonb DEFAULT '[]'::jsonb,
    leader_review text DEFAULT ''::text,
    deployment_opinion text DEFAULT ''::text,
    decision character varying(32) DEFAULT ''::character varying,
    next_action text DEFAULT ''::text,
    created_at timestamp with time zone DEFAULT now(),
    closed_at timestamp with time zone
);


--
-- Name: session_rounds_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.session_rounds_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: session_rounds_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.session_rounds_id_seq OWNED BY public.session_rounds.id;


--
-- Name: task_attempts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.task_attempts (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    task_id uuid NOT NULL,
    attempt_no integer NOT NULL,
    agent_id uuid,
    lease_expires_at timestamp with time zone,
    heartbeat_at timestamp with time zone,
    started_at timestamp with time zone,
    finished_at timestamp with time zone,
    status text NOT NULL,
    exit_code integer,
    error_type text,
    error_message text,
    blocked_until timestamp with time zone,
    summary text,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT task_attempts_attempt_no_check CHECK ((attempt_no > 0)),
    CONSTRAINT task_attempts_error_type_check CHECK (((error_type IS NULL) OR (error_type = ANY (ARRAY['blocked_permission'::text, 'blocked_auth'::text, 'blocked_rate_limit'::text, 'blocked_env'::text, 'timeout_silent'::text, 'retryable'::text, 'unrecoverable'::text, 'acceptance_failed'::text, 'needs_review'::text, 'needs_user_insight'::text])))),
    CONSTRAINT task_attempts_status_check CHECK ((status = ANY (ARRAY['leased'::text, 'running'::text, 'blocked_permission'::text, 'blocked_auth'::text, 'blocked_rate_limit'::text, 'blocked_env'::text, 'timeout_silent'::text, 'cancelled'::text, 'failed_retryable'::text, 'failed_final'::text, 'needs_review'::text, 'needs_user_insight'::text, 'done'::text])))
);


--
-- Name: task_embeddings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.task_embeddings (
    task_id uuid NOT NULL,
    goal text NOT NULL,
    embedding double precision[] DEFAULT '{}'::double precision[] NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: task_participants; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.task_participants (
    id bigint NOT NULL,
    task_id uuid NOT NULL,
    agent_id text NOT NULL,
    role text NOT NULL,
    derivation_source text DEFAULT 'explicit'::text NOT NULL,
    assigned_by text,
    assigned_at timestamp with time zone DEFAULT now() NOT NULL,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: TABLE task_participants; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.task_participants IS 'P61-L4: Tracks which agents are involved in a task and their roles.';


--
-- Name: COLUMN task_participants.derivation_source; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.task_participants.derivation_source IS 'How the role was determined: explicit, requester, target_agent, intent_type, policy';


--
-- Name: task_participants_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.task_participants_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: task_participants_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.task_participants_id_seq OWNED BY public.task_participants.id;


--
-- Name: tasks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tasks (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    parent_task_id uuid,
    title text NOT NULL,
    description text DEFAULT ''::text NOT NULL,
    task_type text NOT NULL,
    status text DEFAULT 'queued'::text NOT NULL,
    priority integer DEFAULT 100 NOT NULL,
    dependencies jsonb DEFAULT '[]'::jsonb NOT NULL,
    required_capabilities jsonb DEFAULT '{}'::jsonb NOT NULL,
    acceptance_check jsonb DEFAULT '{}'::jsonb NOT NULL,
    payload jsonb DEFAULT '{}'::jsonb NOT NULL,
    max_attempts integer DEFAULT 3 NOT NULL,
    lease_owner uuid,
    lease_expires_at timestamp with time zone,
    blocked_until timestamp with time zone,
    created_by text DEFAULT 'system'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    finished_at timestamp with time zone,
    target_agent_id uuid,
    CONSTRAINT tasks_check CHECK ((((status = ANY (ARRAY['leased'::text, 'running'::text])) AND (lease_owner IS NOT NULL) AND (lease_expires_at IS NOT NULL)) OR (status <> ALL (ARRAY['leased'::text, 'running'::text])))),
    CONSTRAINT tasks_check1 CHECK ((((status = 'blocked_rate_limit'::text) AND (blocked_until IS NOT NULL)) OR (status <> 'blocked_rate_limit'::text))),
    CONSTRAINT tasks_max_attempts_check CHECK ((max_attempts > 0)),
    CONSTRAINT tasks_status_check CHECK ((status = ANY (ARRAY['queued'::text, 'leased'::text, 'running'::text, 'done'::text, 'failed_final'::text, 'failed_retryable'::text, 'blocked_rate_limit'::text, 'blocked_auth'::text, 'blocked_env'::text, 'timeout_silent'::text, 'cancelled'::text, 'archived'::text])))
);


--
-- Name: thinking_cases; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.thinking_cases (
    id bigint NOT NULL,
    title character varying(255) NOT NULL,
    description text,
    category character varying(100),
    status character varying(50) DEFAULT 'draft'::character varying NOT NULL,
    priority integer DEFAULT 0 NOT NULL,
    content jsonb,
    metadata jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_by character varying(255),
    assigned_to character varying(255)
);


--
-- Name: thinking_cases_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.thinking_cases_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: thinking_cases_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.thinking_cases_id_seq OWNED BY public.thinking_cases.id;


--
-- Name: session_events id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.session_events ALTER COLUMN id SET DEFAULT nextval('public.session_events_id_seq'::regclass);


--
-- Name: session_rounds id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.session_rounds ALTER COLUMN id SET DEFAULT nextval('public.session_rounds_id_seq'::regclass);


--
-- Name: task_participants id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_participants ALTER COLUMN id SET DEFAULT nextval('public.task_participants_id_seq'::regclass);


--
-- Name: thinking_cases id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.thinking_cases ALTER COLUMN id SET DEFAULT nextval('public.thinking_cases_id_seq'::regclass);


--
-- Name: active_tokens active_tokens_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.active_tokens
    ADD CONSTRAINT active_tokens_pkey PRIMARY KEY (token);


--
-- Name: agents agents_host_id_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agents
    ADD CONSTRAINT agents_host_id_name_key UNIQUE (host_id, name);


--
-- Name: agents agents_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agents
    ADD CONSTRAINT agents_pkey PRIMARY KEY (id);


--
-- Name: artifacts artifacts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.artifacts
    ADD CONSTRAINT artifacts_pkey PRIMARY KEY (id);


--
-- Name: cases cases_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cases
    ADD CONSTRAINT cases_pkey PRIMARY KEY (case_id);


--
-- Name: decomposition_patterns decomposition_patterns_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.decomposition_patterns
    ADD CONSTRAINT decomposition_patterns_pkey PRIMARY KEY (id);


--
-- Name: events events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.events
    ADD CONSTRAINT events_pkey PRIMARY KEY (id);


--
-- Name: hub_context_snapshots hub_context_snapshots_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.hub_context_snapshots
    ADD CONSTRAINT hub_context_snapshots_pkey PRIMARY KEY (id);


--
-- Name: hub_sessions hub_sessions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.hub_sessions
    ADD CONSTRAINT hub_sessions_pkey PRIMARY KEY (id);


--
-- Name: ils_audit_log ils_audit_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ils_audit_log
    ADD CONSTRAINT ils_audit_log_pkey PRIMARY KEY (id);


--
-- Name: machine_sessions machine_sessions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.machine_sessions
    ADD CONSTRAINT machine_sessions_pkey PRIMARY KEY (id);


--
-- Name: machine_sessions machine_sessions_session_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.machine_sessions
    ADD CONSTRAINT machine_sessions_session_id_key UNIQUE (session_id);


--
-- Name: machines machines_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.machines
    ADD CONSTRAINT machines_name_key UNIQUE (name);


--
-- Name: machines machines_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.machines
    ADD CONSTRAINT machines_pkey PRIMARY KEY (id);


--
-- Name: ownership_registry ownership_registry_module_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ownership_registry
    ADD CONSTRAINT ownership_registry_module_id_key UNIQUE (module_id);


--
-- Name: ownership_registry ownership_registry_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ownership_registry
    ADD CONSTRAINT ownership_registry_pkey PRIMARY KEY (id);


--
-- Name: schema_migrations schema_migrations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.schema_migrations
    ADD CONSTRAINT schema_migrations_pkey PRIMARY KEY (filename);


--
-- Name: session_events session_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.session_events
    ADD CONSTRAINT session_events_pkey PRIMARY KEY (id);


--
-- Name: session_rounds session_rounds_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.session_rounds
    ADD CONSTRAINT session_rounds_pkey PRIMARY KEY (id);


--
-- Name: session_rounds session_rounds_session_id_round_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.session_rounds
    ADD CONSTRAINT session_rounds_session_id_round_id_key UNIQUE (session_id, round_id);


--
-- Name: task_attempts task_attempts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_attempts
    ADD CONSTRAINT task_attempts_pkey PRIMARY KEY (id);


--
-- Name: task_attempts task_attempts_task_id_attempt_no_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_attempts
    ADD CONSTRAINT task_attempts_task_id_attempt_no_key UNIQUE (task_id, attempt_no);


--
-- Name: task_embeddings task_embeddings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_embeddings
    ADD CONSTRAINT task_embeddings_pkey PRIMARY KEY (task_id);


--
-- Name: task_participants task_participants_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_participants
    ADD CONSTRAINT task_participants_pkey PRIMARY KEY (id);


--
-- Name: task_participants task_participants_unique; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_participants
    ADD CONSTRAINT task_participants_unique UNIQUE (task_id, agent_id, role);


--
-- Name: tasks tasks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tasks
    ADD CONSTRAINT tasks_pkey PRIMARY KEY (id);


--
-- Name: thinking_cases thinking_cases_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.thinking_cases
    ADD CONSTRAINT thinking_cases_pkey PRIMARY KEY (id);


--
-- Name: idx_active_tokens_expires_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_active_tokens_expires_at ON public.active_tokens USING btree (expires_at);


--
-- Name: idx_agents_last_heartbeat; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_agents_last_heartbeat ON public.agents USING btree (last_heartbeat_at);


--
-- Name: idx_agents_type_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_agents_type_status ON public.agents USING btree (agent_type, status);


--
-- Name: idx_artifacts_attempt; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_artifacts_attempt ON public.artifacts USING btree (attempt_id);


--
-- Name: idx_artifacts_task; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_artifacts_task ON public.artifacts USING btree (task_id, created_at);


--
-- Name: idx_audit_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_audit_created ON public.ils_audit_log USING btree (created_at DESC);


--
-- Name: idx_audit_event; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_audit_event ON public.ils_audit_log USING btree (event_type);


--
-- Name: idx_audit_task; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_audit_task ON public.ils_audit_log USING btree (task_id);


--
-- Name: idx_cases_category; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cases_category ON public.cases USING btree (category);


--
-- Name: idx_cases_embedding; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cases_embedding ON public.cases USING ivfflat (embedding public.vector_cosine_ops) WITH (lists='10');


--
-- Name: idx_cases_tags; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cases_tags ON public.cases USING gin (tags);


--
-- Name: idx_decomp_patterns_hit_count; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_decomp_patterns_hit_count ON public.decomposition_patterns USING btree (hit_count DESC);


--
-- Name: idx_decomp_patterns_project; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_decomp_patterns_project ON public.decomposition_patterns USING btree (project);


--
-- Name: idx_events_attempt_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_events_attempt_created ON public.events USING btree (attempt_id, created_at);


--
-- Name: idx_events_task_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_events_task_created ON public.events USING btree (task_id, created_at);


--
-- Name: idx_hub_context_snapshots_session_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_hub_context_snapshots_session_created ON public.hub_context_snapshots USING btree (hub_session_id, created_at DESC);


--
-- Name: idx_hub_sessions_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_hub_sessions_status ON public.hub_sessions USING btree (status);


--
-- Name: idx_machine_sessions_machine_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_machine_sessions_machine_status ON public.machine_sessions USING btree (machine_id, status);


--
-- Name: idx_machine_sessions_task; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_machine_sessions_task ON public.machine_sessions USING btree (task_id);


--
-- Name: idx_machines_always_on; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_machines_always_on ON public.machines USING btree (always_on) WHERE (always_on = true);


--
-- Name: idx_machines_last_seen; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_machines_last_seen ON public.machines USING btree (last_seen_at);


--
-- Name: idx_machines_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_machines_status ON public.machines USING btree (status);


--
-- Name: idx_ownership_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ownership_active ON public.ownership_registry USING btree (module_id) WHERE (released_at IS NULL);


--
-- Name: idx_ownership_agent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ownership_agent ON public.ownership_registry USING btree (owner_agent_id);


--
-- Name: idx_ownership_module; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ownership_module ON public.ownership_registry USING btree (module_id);


--
-- Name: idx_se_session_seq; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_se_session_seq ON public.session_events USING btree (session_id, seq);


--
-- Name: idx_se_sid_seq; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_se_sid_seq ON public.session_events USING btree (session_id, seq);


--
-- Name: idx_task_attempts_agent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_task_attempts_agent ON public.task_attempts USING btree (agent_id, status);


--
-- Name: idx_task_attempts_lease_expires; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_task_attempts_lease_expires ON public.task_attempts USING btree (lease_expires_at) WHERE (status = ANY (ARRAY['leased'::text, 'running'::text]));


--
-- Name: idx_task_attempts_task; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_task_attempts_task ON public.task_attempts USING btree (task_id, attempt_no DESC);


--
-- Name: idx_task_embeddings_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_task_embeddings_created ON public.task_embeddings USING btree (created_at DESC);


--
-- Name: idx_task_participants_agent_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_task_participants_agent_id ON public.task_participants USING btree (agent_id);


--
-- Name: idx_task_participants_role; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_task_participants_role ON public.task_participants USING btree (role);


--
-- Name: idx_task_participants_task_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_task_participants_task_id ON public.task_participants USING btree (task_id);


--
-- Name: idx_tasks_blocked_until; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tasks_blocked_until ON public.tasks USING btree (blocked_until) WHERE (status = 'blocked_rate_limit'::text);


--
-- Name: idx_tasks_lease_expires; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tasks_lease_expires ON public.tasks USING btree (lease_expires_at) WHERE (status = ANY (ARRAY['leased'::text, 'running'::text]));


--
-- Name: idx_tasks_parent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tasks_parent ON public.tasks USING btree (parent_task_id);


--
-- Name: idx_tasks_status_priority; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tasks_status_priority ON public.tasks USING btree (status, priority, created_at);


--
-- Name: idx_tasks_target_agent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tasks_target_agent ON public.tasks USING btree (target_agent_id) WHERE (target_agent_id IS NOT NULL);


--
-- Name: idx_thinking_cases_assigned_to; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_thinking_cases_assigned_to ON public.thinking_cases USING btree (assigned_to);


--
-- Name: idx_thinking_cases_category; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_thinking_cases_category ON public.thinking_cases USING btree (category);


--
-- Name: idx_thinking_cases_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_thinking_cases_created_at ON public.thinking_cases USING btree (created_at);


--
-- Name: idx_thinking_cases_created_by; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_thinking_cases_created_by ON public.thinking_cases USING btree (created_by);


--
-- Name: idx_thinking_cases_priority; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_thinking_cases_priority ON public.thinking_cases USING btree (priority);


--
-- Name: idx_thinking_cases_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_thinking_cases_status ON public.thinking_cases USING btree (status);


--
-- Name: thinking_cases trg_thinking_cases_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_thinking_cases_updated_at BEFORE UPDATE ON public.thinking_cases FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- Name: artifacts artifacts_attempt_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.artifacts
    ADD CONSTRAINT artifacts_attempt_id_fkey FOREIGN KEY (attempt_id) REFERENCES public.task_attempts(id) ON DELETE SET NULL;


--
-- Name: artifacts artifacts_task_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.artifacts
    ADD CONSTRAINT artifacts_task_id_fkey FOREIGN KEY (task_id) REFERENCES public.tasks(id) ON DELETE CASCADE;


--
-- Name: events events_agent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.events
    ADD CONSTRAINT events_agent_id_fkey FOREIGN KEY (agent_id) REFERENCES public.agents(id) ON DELETE SET NULL;


--
-- Name: events events_attempt_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.events
    ADD CONSTRAINT events_attempt_id_fkey FOREIGN KEY (attempt_id) REFERENCES public.task_attempts(id) ON DELETE SET NULL;


--
-- Name: events events_task_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.events
    ADD CONSTRAINT events_task_id_fkey FOREIGN KEY (task_id) REFERENCES public.tasks(id) ON DELETE CASCADE;


--
-- Name: hub_context_snapshots hub_context_snapshots_hub_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.hub_context_snapshots
    ADD CONSTRAINT hub_context_snapshots_hub_session_id_fkey FOREIGN KEY (hub_session_id) REFERENCES public.hub_sessions(id) ON DELETE CASCADE;


--
-- Name: machine_sessions machine_sessions_agent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.machine_sessions
    ADD CONSTRAINT machine_sessions_agent_id_fkey FOREIGN KEY (agent_id) REFERENCES public.agents(id) ON DELETE SET NULL;


--
-- Name: machine_sessions machine_sessions_machine_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.machine_sessions
    ADD CONSTRAINT machine_sessions_machine_id_fkey FOREIGN KEY (machine_id) REFERENCES public.machines(id) ON DELETE CASCADE;


--
-- Name: machine_sessions machine_sessions_task_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.machine_sessions
    ADD CONSTRAINT machine_sessions_task_id_fkey FOREIGN KEY (task_id) REFERENCES public.tasks(id) ON DELETE SET NULL;


--
-- Name: task_attempts task_attempts_agent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_attempts
    ADD CONSTRAINT task_attempts_agent_id_fkey FOREIGN KEY (agent_id) REFERENCES public.agents(id) ON DELETE SET NULL;


--
-- Name: task_attempts task_attempts_task_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_attempts
    ADD CONSTRAINT task_attempts_task_id_fkey FOREIGN KEY (task_id) REFERENCES public.tasks(id) ON DELETE CASCADE;


--
-- Name: task_participants task_participants_task_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_participants
    ADD CONSTRAINT task_participants_task_id_fkey FOREIGN KEY (task_id) REFERENCES public.tasks(id) ON DELETE CASCADE;


--
-- Name: tasks tasks_lease_owner_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tasks
    ADD CONSTRAINT tasks_lease_owner_fkey FOREIGN KEY (lease_owner) REFERENCES public.agents(id) ON DELETE SET NULL;


--
-- Name: tasks tasks_parent_task_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tasks
    ADD CONSTRAINT tasks_parent_task_id_fkey FOREIGN KEY (parent_task_id) REFERENCES public.tasks(id) ON DELETE SET NULL;


--
-- Name: tasks tasks_target_agent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tasks
    ADD CONSTRAINT tasks_target_agent_id_fkey FOREIGN KEY (target_agent_id) REFERENCES public.agents(id) ON DELETE SET NULL;


--
-- PostgreSQL database dump complete
--

\unrestrict oQaJK3Ow0yANLmE1fOHn0sb99uT7oVH2eCgVhyOpq2vvcCpIHd6Bul4L4UmOZRh

