/**
 * Incremental migration 003: household memory + daily meal ledger.
 * Safe to run on existing production SQLite (CREATE IF NOT EXISTS only).
 */
export const MIGRATION_003_NAME = "household_memory_and_meal_ledger";
export const MIGRATION_003_ID = 3;

export const MIGRATION_003_SQL = `
CREATE TABLE IF NOT EXISTS member_health_facts (
  id TEXT PRIMARY KEY,
  member_id TEXT NOT NULL REFERENCES household_members(id),
  household_id TEXT NOT NULL REFERENCES households(id),
  kind TEXT NOT NULL,
  summary TEXT NOT NULL,
  source TEXT NOT NULL,
  effective_from TEXT NOT NULL,
  effective_to TEXT,
  version INTEGER NOT NULL DEFAULT 1,
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS member_preferences (
  id TEXT PRIMARY KEY,
  member_id TEXT NOT NULL REFERENCES household_members(id),
  household_id TEXT NOT NULL REFERENCES households(id),
  kind TEXT NOT NULL,
  target_type TEXT NOT NULL DEFAULT 'note',
  target_id TEXT,
  note TEXT NOT NULL,
  polarity TEXT NOT NULL DEFAULT 'prefer',
  source TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1,
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS member_daily_targets (
  id TEXT PRIMARY KEY,
  member_id TEXT NOT NULL REFERENCES household_members(id),
  household_id TEXT NOT NULL REFERENCES households(id),
  service_date TEXT,
  energy_kcal REAL NOT NULL,
  carbohydrate_g REAL NOT NULL,
  protein_g REAL NOT NULL,
  fat_g REAL NOT NULL,
  sodium_mg REAL NOT NULL,
  source TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1,
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS meal_records (
  id TEXT PRIMARY KEY,
  household_id TEXT NOT NULL REFERENCES households(id),
  service_date TEXT NOT NULL,
  meal_type TEXT NOT NULL,
  status TEXT NOT NULL,
  plan_id TEXT,
  plan_version INTEGER,
  source TEXT NOT NULL,
  diner_ids_json TEXT NOT NULL,
  completed_at TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS meal_record_items (
  id TEXT PRIMARY KEY,
  meal_record_id TEXT NOT NULL REFERENCES meal_records(id),
  member_id TEXT NOT NULL REFERENCES household_members(id),
  template_id TEXT,
  food_id TEXT NOT NULL,
  quantity_g REAL NOT NULL,
  energy_kcal REAL NOT NULL,
  carbohydrate_g REAL NOT NULL,
  protein_g REAL NOT NULL,
  fat_g REAL NOT NULL,
  sodium_mg REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS inventory_ledger (
  id TEXT PRIMARY KEY,
  household_id TEXT NOT NULL REFERENCES households(id),
  inventory_item_id TEXT NOT NULL REFERENCES inventory_items(id),
  food_id TEXT,
  reason TEXT NOT NULL,
  before_estimate_g REAL,
  delta_g REAL NOT NULL,
  after_estimate_g REAL,
  related_meal_record_id TEXT,
  related_pending_action_id TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS unit_conversion_rules (
  id TEXT PRIMARY KEY,
  food_id TEXT NOT NULL REFERENCES foods(id),
  raw_unit TEXT NOT NULL,
  grams_per_unit REAL NOT NULL,
  confidence TEXT NOT NULL,
  source_id TEXT NOT NULL,
  license_id TEXT NOT NULL,
  rule_version TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS meal_candidate_sets (
  id TEXT PRIMARY KEY,
  household_id TEXT NOT NULL REFERENCES households(id),
  service_date TEXT NOT NULL,
  meal_type TEXT NOT NULL,
  diner_ids_json TEXT NOT NULL,
  version_stamp_json TEXT NOT NULL,
  candidates_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS household_intake_versions (
  household_id TEXT PRIMARY KEY REFERENCES households(id),
  intake_version INTEGER NOT NULL DEFAULT 1,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_meal_records_household_date
  ON meal_records(household_id, service_date, status);

CREATE INDEX IF NOT EXISTS idx_meal_record_items_record
  ON meal_record_items(meal_record_id);

CREATE INDEX IF NOT EXISTS idx_inventory_ledger_household
  ON inventory_ledger(household_id, created_at);
`;
