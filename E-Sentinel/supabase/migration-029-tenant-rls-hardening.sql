-- ============================================================================
-- Migration 029: Tenant RLS hardening for legacy QA tables
--
-- This is forward-only. Published migrations are intentionally left unchanged.
-- Service-role clients still bypass RLS by design; API routes must continue to
-- resolve a tenant and apply the same scope explicitly.
-- ============================================================================

CREATE OR REPLACE FUNCTION public.jwt_tenant_id()
RETURNS TEXT
LANGUAGE sql
STABLE
AS $$
  SELECT COALESCE(
    auth.jwt() ->> 'tenant_id',
    auth.jwt() -> 'app_metadata' ->> 'tenant_id'
  )
$$;

DO $$
DECLARE
  table_name TEXT;
  tenant_tables TEXT[] := ARRAY[
    'profiles',
    'quality_reports',
    'bad_cases',
    'bot_configs',
    'knowledge_entries',
    'bot_chat_sessions',
    'optimization_tasks',
    'robot_reports',
    'knowledge_update_logs',
    'user_roles',
    'audit_logs',
    'correction_samples',
    'compliance_rules',
    'compliance_audit_logs',
    'system_configs',
    'intent_accuracy_logs',
    'platform_credentials',
    'shadow_replies',
    'actual_replies',
    'work_orders',
    'work_order_actions',
    'pending_orders',
    'payment_reminders',
    'unresolved_questions',
    'unresolved_question_logs',
    'llm_call_logs'
  ];
BEGIN
  FOREACH table_name IN ARRAY tenant_tables LOOP
    IF to_regclass(format('public.%I', table_name)) IS NULL THEN
      CONTINUE;
    END IF;

    EXECUTE format(
      'ALTER TABLE public.%I ADD COLUMN IF NOT EXISTS tenant_id TEXT',
      table_name
    );
    EXECUTE format(
      'UPDATE public.%I SET tenant_id = ''default'' WHERE tenant_id IS NULL',
      table_name
    );
    EXECUTE format(
      'ALTER TABLE public.%I ALTER COLUMN tenant_id SET DEFAULT ''default''',
      table_name
    );
    EXECUTE format(
      'ALTER TABLE public.%I ALTER COLUMN tenant_id SET NOT NULL',
      table_name
    );
    EXECUTE format(
      'CREATE INDEX IF NOT EXISTS %I ON public.%I (tenant_id)',
      'idx_' || table_name || '_tenant',
      table_name
    );

    -- Keep existing role/permission policies. A restrictive policy is ANDed
    -- with every permissive policy, so legacy USING(true) cannot cross tenants
    -- and existing admin/team restrictions are not widened.
    EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', table_name || '_tenant_select', table_name);
    EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', table_name || '_tenant_insert', table_name);
    EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', table_name || '_tenant_update', table_name);
    EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', table_name || '_tenant_delete', table_name);
    EXECUTE format(
      'CREATE POLICY %I ON public.%I AS RESTRICTIVE FOR SELECT USING (auth.uid() IS NOT NULL AND tenant_id = public.jwt_tenant_id())',
      table_name || '_tenant_select',
      table_name
    );
    EXECUTE format(
      'CREATE POLICY %I ON public.%I AS RESTRICTIVE FOR INSERT WITH CHECK (auth.uid() IS NOT NULL AND tenant_id = public.jwt_tenant_id())',
      table_name || '_tenant_insert',
      table_name
    );
    EXECUTE format(
      'CREATE POLICY %I ON public.%I AS RESTRICTIVE FOR UPDATE USING (auth.uid() IS NOT NULL AND tenant_id = public.jwt_tenant_id()) WITH CHECK (auth.uid() IS NOT NULL AND tenant_id = public.jwt_tenant_id())',
      table_name || '_tenant_update',
      table_name
    );
    EXECUTE format(
      'CREATE POLICY %I ON public.%I AS RESTRICTIVE FOR DELETE USING (auth.uid() IS NOT NULL AND tenant_id = public.jwt_tenant_id())',
      table_name || '_tenant_delete',
      table_name
    );

    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', table_name);
    EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY', table_name);
  END LOOP;
END
$$;

CREATE INDEX IF NOT EXISTS idx_knowledge_entries_tenant_status
  ON public.knowledge_entries (tenant_id, status);

-- Diagnosis tables already carry tenant_id but migration-027 only enabled RLS.
DO $$
DECLARE
  table_name TEXT;
  tenant_tables TEXT[] := ARRAY[
    'diagnosis_sessions',
    'diagnosis_findings',
    'diagnosis_reviews',
    'diagnosis_work_items',
    'feedback_records',
    'release_manifests',
    'release_evidences',
    'dora_metrics',
    'rollback_drills'
  ];
BEGIN
  FOREACH table_name IN ARRAY tenant_tables LOOP
    IF to_regclass(format('public.%I', table_name)) IS NULL THEN
      CONTINUE;
    END IF;

    EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', table_name || '_tenant_select', table_name);
    EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', table_name || '_tenant_insert', table_name);
    EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', table_name || '_tenant_update', table_name);
    EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', table_name || '_tenant_delete', table_name);
    EXECUTE format(
      'CREATE POLICY %I ON public.%I AS RESTRICTIVE FOR SELECT USING (auth.uid() IS NOT NULL AND tenant_id = public.jwt_tenant_id())',
      table_name || '_tenant_select',
      table_name
    );
    EXECUTE format(
      'CREATE POLICY %I ON public.%I AS RESTRICTIVE FOR INSERT WITH CHECK (auth.uid() IS NOT NULL AND tenant_id = public.jwt_tenant_id())',
      table_name || '_tenant_insert',
      table_name
    );
    EXECUTE format(
      'CREATE POLICY %I ON public.%I AS RESTRICTIVE FOR UPDATE USING (auth.uid() IS NOT NULL AND tenant_id = public.jwt_tenant_id()) WITH CHECK (auth.uid() IS NOT NULL AND tenant_id = public.jwt_tenant_id())',
      table_name || '_tenant_update',
      table_name
    );
    EXECUTE format(
      'CREATE POLICY %I ON public.%I AS RESTRICTIVE FOR DELETE USING (auth.uid() IS NOT NULL AND tenant_id = public.jwt_tenant_id())',
      table_name || '_tenant_delete',
      table_name
    );
    EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY', table_name);
  END LOOP;
END
$$;

-- Legacy prompt/bot/model tables used UUID tenant columns and had no tenant
-- policy. Normalize them to the text tenant contract used by JWT claims and
-- the rest of the QA schema before enabling service-role-safe RLS.
DO $$
DECLARE
  legacy_table_name TEXT;
  column_type TEXT;
BEGIN
  FOREACH legacy_table_name IN ARRAY ARRAY['prompts', 'bots', 'model_configs', 'prompt_versions'] LOOP
    IF to_regclass(format('public.%I', legacy_table_name)) IS NULL THEN
      CONTINUE;
    END IF;

    IF NOT EXISTS (
      SELECT 1
      FROM information_schema.columns AS columns
      WHERE columns.table_schema = 'public'
        AND columns.table_name = legacy_table_name
        AND columns.column_name = 'tenant_id'
    ) THEN
      EXECUTE format('ALTER TABLE public.%I ADD COLUMN tenant_id TEXT', legacy_table_name);
    ELSE
      SELECT format_type(a.atttypid, a.atttypmod)
        INTO column_type
      FROM pg_attribute AS a
      JOIN pg_class AS c ON c.oid = a.attrelid
      JOIN pg_namespace AS n ON n.oid = c.relnamespace
      WHERE n.nspname = 'public'
        AND c.relname = legacy_table_name
        AND a.attname = 'tenant_id'
        AND a.attnum > 0
        AND NOT a.attisdropped;

      IF column_type <> 'text' THEN
        EXECUTE format(
          'ALTER TABLE public.%I ALTER COLUMN tenant_id TYPE TEXT USING tenant_id::text',
          legacy_table_name
        );
      END IF;
    END IF;

    EXECUTE format('UPDATE public.%I SET tenant_id = ''default'' WHERE tenant_id IS NULL', legacy_table_name);
    EXECUTE format('ALTER TABLE public.%I ALTER COLUMN tenant_id SET DEFAULT ''default''', legacy_table_name);
    EXECUTE format('ALTER TABLE public.%I ALTER COLUMN tenant_id SET NOT NULL', legacy_table_name);
    EXECUTE format(
      'CREATE INDEX IF NOT EXISTS %I ON public.%I (tenant_id)',
      'idx_' || legacy_table_name || '_tenant',
      legacy_table_name
    );
  END LOOP;

  IF to_regclass('public.prompt_versions') IS NOT NULL
     AND to_regclass('public.prompts') IS NOT NULL THEN
    UPDATE public.prompt_versions AS versions
    SET tenant_id = prompts.tenant_id
    FROM public.prompts AS prompts
    WHERE versions.prompt_id = prompts.id
      AND versions.tenant_id = 'default'
      AND prompts.tenant_id <> 'default';
  END IF;
END
$$;

DO $$
BEGIN
  IF to_regclass('public.prompts') IS NOT NULL THEN
    ALTER TABLE public.prompts ENABLE ROW LEVEL SECURITY;
    ALTER TABLE public.prompts FORCE ROW LEVEL SECURITY;
    DROP POLICY IF EXISTS prompts_tenant_access ON public.prompts;
    CREATE POLICY prompts_tenant_access ON public.prompts
      AS PERMISSIVE FOR ALL TO authenticated
      USING (auth.uid() IS NOT NULL AND tenant_id = public.jwt_tenant_id())
      WITH CHECK (auth.uid() IS NOT NULL AND tenant_id = public.jwt_tenant_id());
  END IF;

  IF to_regclass('public.bots') IS NOT NULL THEN
    ALTER TABLE public.bots ENABLE ROW LEVEL SECURITY;
    ALTER TABLE public.bots FORCE ROW LEVEL SECURITY;
    DROP POLICY IF EXISTS bots_tenant_access ON public.bots;
    CREATE POLICY bots_tenant_access ON public.bots
      AS PERMISSIVE FOR ALL TO authenticated
      USING (auth.uid() IS NOT NULL AND tenant_id = public.jwt_tenant_id())
      WITH CHECK (auth.uid() IS NOT NULL AND tenant_id = public.jwt_tenant_id());
  END IF;

  IF to_regclass('public.model_configs') IS NOT NULL THEN
    ALTER TABLE public.model_configs ENABLE ROW LEVEL SECURITY;
    ALTER TABLE public.model_configs FORCE ROW LEVEL SECURITY;
    DROP POLICY IF EXISTS model_configs_tenant_access ON public.model_configs;
    CREATE POLICY model_configs_tenant_access ON public.model_configs
      AS PERMISSIVE FOR ALL TO authenticated
      USING (auth.uid() IS NOT NULL AND tenant_id = public.jwt_tenant_id())
      WITH CHECK (auth.uid() IS NOT NULL AND tenant_id = public.jwt_tenant_id());
  END IF;

  IF to_regclass('public.prompt_versions') IS NOT NULL THEN
    ALTER TABLE public.prompt_versions ENABLE ROW LEVEL SECURITY;
    ALTER TABLE public.prompt_versions FORCE ROW LEVEL SECURITY;
    DROP POLICY IF EXISTS prompt_versions_tenant_access ON public.prompt_versions;
    CREATE POLICY prompt_versions_tenant_access ON public.prompt_versions
      AS PERMISSIVE FOR ALL TO authenticated
      USING (
        auth.uid() IS NOT NULL
        AND tenant_id = public.jwt_tenant_id()
        AND EXISTS (
          SELECT 1
          FROM public.prompts
          WHERE prompts.id = prompt_versions.prompt_id
            AND prompts.tenant_id = prompt_versions.tenant_id
        )
      )
      WITH CHECK (
        auth.uid() IS NOT NULL
        AND tenant_id = public.jwt_tenant_id()
        AND EXISTS (
          SELECT 1
          FROM public.prompts
          WHERE prompts.id = prompt_versions.prompt_id
            AND prompts.tenant_id = prompt_versions.tenant_id
        )
      );
  END IF;
END
$$;

-- Replace the old unscoped hybrid-search functions. The old signatures are
-- dropped so callers cannot accidentally keep invoking an all-tenant variant.
DROP FUNCTION IF EXISTS public.hybrid_search_vector(vector, integer);
DROP FUNCTION IF EXISTS public.hybrid_search_keyword(text, integer);

CREATE OR REPLACE FUNCTION public.hybrid_search_vector(
  query_embedding vector(1536),
  match_count integer DEFAULT 20,
  tenant_id text DEFAULT NULL
)
RETURNS TABLE(
  id uuid,
  title text,
  content text,
  category text,
  keywords text[],
  similarity float
)
LANGUAGE sql
STABLE
AS $$
  SELECT
    ke.id,
    ke.title,
    ke.content,
    ke.category,
    ke.keywords,
    (1 - (ke.embedding <=> $1))::float AS similarity
  FROM public.knowledge_entries AS ke
  WHERE ke.status = 'published'
    AND ke.embedding IS NOT NULL
    AND $3 IS NOT NULL
    AND ke.tenant_id = $3
  ORDER BY ke.embedding <=> $1
  LIMIT $2
$$;

CREATE OR REPLACE FUNCTION public.hybrid_search_keyword(
  query_text text,
  match_count integer DEFAULT 20,
  tenant_id text DEFAULT NULL
)
RETURNS TABLE(
  id uuid,
  title text,
  content text,
  category text,
  keywords text[],
  similarity float
)
LANGUAGE sql
STABLE
AS $$
  SELECT
    ke.id,
    ke.title,
    ke.content,
    ke.category,
    ke.keywords,
    ts_rank_cd(ke.search_vector, plainto_tsquery('simple', $1))::float AS similarity
  FROM public.knowledge_entries AS ke
  WHERE ke.status = 'published'
    AND ke.search_vector @@ plainto_tsquery('simple', $1)
    AND $3 IS NOT NULL
    AND ke.tenant_id = $3
  ORDER BY similarity DESC
  LIMIT $2
$$;
