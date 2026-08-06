-- Minimal tenant isolation for the existing SaaS core tables.
CREATE TABLE IF NOT EXISTS tenants (
  id TEXT PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  plan TEXT NOT NULL DEFAULT 'standard',
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'suspended', 'archived')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO tenants (id, code, name)
VALUES ('default', 'default', 'Default tenant')
ON CONFLICT (id) DO NOTHING;

ALTER TABLE profiles
  ADD COLUMN IF NOT EXISTS tenant_id TEXT;
ALTER TABLE profiles
  ALTER COLUMN tenant_id SET DEFAULT 'default';
UPDATE profiles SET tenant_id = 'default' WHERE tenant_id IS NULL;

DO $$
DECLARE
  table_name TEXT;
BEGIN
  FOREACH table_name IN ARRAY ARRAY['knowledge_entries', 'bot_configs', 'bot_chat_sessions', 'quality_reports', 'optimization_tasks']
  LOOP
    EXECUTE format('ALTER TABLE %I ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT ''default''', table_name);
    EXECUTE format('UPDATE %I SET tenant_id = ''default'' WHERE tenant_id IS NULL', table_name);
    EXECUTE format('CREATE INDEX IF NOT EXISTS %I ON %I(tenant_id, created_at DESC)', 'idx_' || table_name || '_tenant_created', table_name);
  END LOOP;
END $$;

ALTER TABLE tenants ENABLE ROW LEVEL SECURITY;
DO $$
BEGIN
  CREATE POLICY "Tenants require matching JWT tenant" ON tenants
    FOR SELECT USING (auth.uid() IS NOT NULL AND id = COALESCE(auth.jwt() ->> 'tenant_id', auth.jwt() -> 'app_metadata' ->> 'tenant_id'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
