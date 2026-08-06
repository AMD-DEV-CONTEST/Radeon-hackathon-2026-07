export const MIGRATION_SQL = `
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_migrations (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS households (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1,
  inventory_version INTEGER NOT NULL DEFAULT 1,
  meal_policy_version TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS household_members (
  id TEXT PRIMARY KEY,
  household_id TEXT NOT NULL REFERENCES households(id),
  display_name TEXT NOT NULL,
  relation_label TEXT,
  health_tags_json TEXT NOT NULL,
  notes TEXT,
  active INTEGER NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS member_constraints (
  id TEXT PRIMARY KEY,
  member_id TEXT NOT NULL REFERENCES household_members(id),
  kind TEXT NOT NULL,
  target_id TEXT NOT NULL,
  source TEXT NOT NULL,
  rule_version TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS member_meal_policies (
  member_id TEXT NOT NULL,
  meal_type TEXT NOT NULL,
  portion_units_json TEXT NOT NULL,
  guardrails_json TEXT NOT NULL,
  rule_version TEXT NOT NULL,
  source TEXT NOT NULL,
  PRIMARY KEY (member_id, meal_type, rule_version)
);

CREATE TABLE IF NOT EXISTS fixture_preferences (
  id TEXT PRIMARY KEY,
  household_id TEXT NOT NULL REFERENCES households(id),
  member_id TEXT,
  kind TEXT NOT NULL,
  value_json TEXT NOT NULL,
  rule_version TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS foods (
  id TEXT PRIMARY KEY,
  canonical_name TEXT NOT NULL,
  nutrition_json TEXT NOT NULL,
  allergen_tags_json TEXT NOT NULL,
  source_id TEXT NOT NULL,
  license_id TEXT NOT NULL,
  data_version TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS food_aliases (
  alias TEXT NOT NULL,
  food_id TEXT NOT NULL REFERENCES foods(id),
  UNIQUE(alias)
);

CREATE TABLE IF NOT EXISTS meal_templates (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  role TEXT NOT NULL,
  tags_json TEXT NOT NULL,
  instructions_summary TEXT NOT NULL,
  source_id TEXT NOT NULL,
  license_id TEXT NOT NULL,
  template_version TEXT NOT NULL,
  active INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS meal_template_ingredients (
  id TEXT PRIMARY KEY,
  template_id TEXT NOT NULL REFERENCES meal_templates(id),
  food_id TEXT NOT NULL REFERENCES foods(id),
  edible_quantity_g REAL NOT NULL,
  preparation_tag TEXT NOT NULL DEFAULT '',
  UNIQUE(template_id, food_id, preparation_tag)
);

CREATE TABLE IF NOT EXISTS meal_bundle_templates (
  id TEXT PRIMARY KEY,
  template_ids_json TEXT NOT NULL,
  bundle_version TEXT NOT NULL,
  source_id TEXT NOT NULL,
  license_id TEXT NOT NULL,
  active INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS inventory_items (
  id TEXT PRIMARY KEY,
  household_id TEXT NOT NULL REFERENCES households(id),
  food_id TEXT,
  raw_name TEXT NOT NULL,
  raw_quantity_expression TEXT NOT NULL,
  normalized_gram_range_json TEXT NOT NULL,
  state TEXT NOT NULL,
  priority_use INTEGER NOT NULL,
  notes TEXT,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS meal_planning_sessions (
  id TEXT PRIMARY KEY,
  household_id TEXT NOT NULL REFERENCES households(id),
  meal_type TEXT NOT NULL,
  diner_ids_json TEXT NOT NULL,
  active_constraints_json TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS meal_plans (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL REFERENCES meal_planning_sessions(id),
  version INTEGER NOT NULL,
  parent_plan_id TEXT,
  status TEXT NOT NULL,
  household_context_version INTEGER NOT NULL,
  inventory_version INTEGER NOT NULL,
  meal_policy_version TEXT NOT NULL,
  plan_json TEXT NOT NULL,
  UNIQUE(session_id, version)
);

CREATE TABLE IF NOT EXISTS agent_checkpoints (
  session_id TEXT NOT NULL,
  household_id TEXT NOT NULL REFERENCES households(id),
  state_json TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (household_id, session_id)
);

CREATE TABLE IF NOT EXISTS shopping_gap_items (
  plan_id TEXT NOT NULL REFERENCES meal_plans(id),
  food_id TEXT NOT NULL,
  required_json TEXT NOT NULL,
  available_json TEXT NOT NULL,
  purchase_json TEXT NOT NULL,
  status TEXT NOT NULL,
  used_by_template_ids_json TEXT NOT NULL,
  PRIMARY KEY (plan_id, food_id)
);

CREATE TABLE IF NOT EXISTS pending_actions (
  id TEXT PRIMARY KEY,
  household_id TEXT NOT NULL REFERENCES households(id),
  action_type TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  preview_json TEXT NOT NULL,
  payload_hash TEXT NOT NULL,
  confirmation_token_hash TEXT NOT NULL,
  status TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  committed_at TEXT,
  idempotency_key TEXT,
  commit_result_json TEXT,
  commit_result_hash TEXT,
  created_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS pending_actions_idempotency
  ON pending_actions(household_id, action_type, idempotency_key)
  WHERE idempotency_key IS NOT NULL;

CREATE TABLE IF NOT EXISTS caregiver_tasks (
  id TEXT PRIMARY KEY,
  household_id TEXT NOT NULL REFERENCES households(id),
  plan_id TEXT NOT NULL,
  plan_version INTEGER NOT NULL,
  recipient_label TEXT NOT NULL,
  task_card_json TEXT NOT NULL,
  channel TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS knowledge_cards (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  content TEXT NOT NULL,
  tags_json TEXT NOT NULL,
  applicability_json TEXT NOT NULL,
  exclusions_json TEXT NOT NULL,
  risk_level TEXT NOT NULL,
  review_status TEXT NOT NULL,
  source_title TEXT NOT NULL,
  source_year INTEGER,
  source_url TEXT,
  license_id TEXT NOT NULL,
  content_version TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_events (
  id TEXT PRIMARY KEY,
  session_id TEXT,
  household_id TEXT,
  tool_name TEXT,
  action_type TEXT NOT NULL,
  status TEXT NOT NULL,
  parameter_hash TEXT,
  result_summary TEXT,
  latency_ms INTEGER,
  created_at TEXT NOT NULL
);
`;
