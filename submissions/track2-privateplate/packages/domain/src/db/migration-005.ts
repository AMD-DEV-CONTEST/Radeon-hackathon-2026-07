export const MIGRATION_005_ID = 5;
export const MIGRATION_005_NAME = "member_nutrition_profiles";

export const MIGRATION_005_SQL = `
CREATE TABLE IF NOT EXISTS member_nutrition_profiles (
  member_id TEXT PRIMARY KEY REFERENCES household_members(id),
  gender TEXT NOT NULL,
  age INTEGER,
  birth_year INTEGER,
  height_cm REAL NOT NULL,
  weight_kg REAL NOT NULL,
  activity_level TEXT NOT NULL,
  weight_goal TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT 'demo_fixture',
  profile_version TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  CHECK (age IS NOT NULL OR birth_year IS NOT NULL)
);
`;
