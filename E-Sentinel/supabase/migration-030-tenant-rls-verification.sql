-- Forward-only follow-up: enable RLS on the release/DORA tables and remove
-- the legacy unscoped quality-rule RPC overload.

DO $$
DECLARE
  table_name TEXT;
BEGIN
  FOREACH table_name IN ARRAY ARRAY[
    'diagnosis_sessions', 'diagnosis_findings', 'diagnosis_reviews',
    'diagnosis_work_items', 'feedback_records', 'release_manifests',
    'release_evidences', 'dora_metrics', 'rollback_drills'
  ] LOOP
    IF to_regclass(format('public.%I', table_name)) IS NULL THEN
      CONTINUE;
    END IF;
    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', table_name);
    EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY', table_name);
  END LOOP;
END
$$;

DROP FUNCTION IF EXISTS public.match_quality_rules(vector, integer);
