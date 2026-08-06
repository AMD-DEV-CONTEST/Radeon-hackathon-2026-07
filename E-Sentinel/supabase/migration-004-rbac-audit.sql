-- ============================================================================
-- Migration 004: RBAC roles + audit logs + dynamic platforms seed update
-- ============================================================================

-- ── User Roles ───────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS user_roles (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  profile_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  role TEXT NOT NULL CHECK (role IN ('admin', 'operator', 'agent', 'viewer')),
  assigned_by UUID REFERENCES profiles(id),
  created_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE (profile_id)
);

COMMENT ON TABLE user_roles IS 'RBAC role assignments for each profile';

-- ── Audit Logs ───────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS audit_logs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  action TEXT NOT NULL,
  user_id UUID,
  user_name TEXT,
  resource_type TEXT,
  resource_id TEXT,
  detail JSONB,
  correlation_id TEXT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_audit_logs_action ON audit_logs(action);
CREATE INDEX IF NOT EXISTS idx_audit_logs_user_id ON audit_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_resource ON audit_logs(resource_type, resource_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_created_at ON audit_logs(created_at DESC);

COMMENT ON TABLE audit_logs IS 'Comprehensive audit log for auth, operations, AI calls, QA changes';

-- ── RLS for user_roles ───────────────────────────────────────────────────────
ALTER TABLE user_roles ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Admins can manage roles" ON user_roles;
CREATE POLICY "Admins can manage roles" ON user_roles
  FOR ALL
  USING (EXISTS (
    SELECT 1 FROM user_roles ur
    WHERE ur.profile_id = auth.uid() AND ur.role = 'admin'
  ));

DROP POLICY IF EXISTS "Users can read own role" ON user_roles;
CREATE POLICY "Users can read own role" ON user_roles
  FOR SELECT
  USING (profile_id = auth.uid());

-- ── RLS for audit_logs ───────────────────────────────────────────────────────
ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Admins can read all logs" ON audit_logs;
CREATE POLICY "Admins can read all logs" ON audit_logs
  FOR SELECT
  USING (EXISTS (
    SELECT 1 FROM user_roles ur
    WHERE ur.profile_id = auth.uid() AND ur.role = 'admin'
  ));

DROP POLICY IF EXISTS "Operators can read team logs" ON audit_logs;
CREATE POLICY "Operators can read team logs" ON audit_logs
  FOR SELECT
  USING (EXISTS (
    SELECT 1 FROM user_roles ur
    WHERE ur.profile_id = auth.uid() AND ur.role IN ('admin', 'operator')
  ));

-- ── Seed: assign admin role to first profile ─────────────────────────────────
INSERT INTO user_roles (profile_id, role)
SELECT id, 'admin'
FROM profiles
WHERE NOT EXISTS (SELECT 1 FROM user_roles)
LIMIT 1;
