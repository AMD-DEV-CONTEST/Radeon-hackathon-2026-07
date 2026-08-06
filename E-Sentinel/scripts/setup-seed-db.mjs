#!/usr/bin/env node
/**
 * E-Sentinel — seeded administrator setup (one command)
 *
 * Creates or reconciles the seeded administrator account for the Operations Console.
 *
 * PREREQUISITES (once, before running this):
 *   1. A Supabase project (local `supabase start` or a cloud project).
 *   2. Database initialized: run `supabase/init-seed.sql` once in the
 *      Supabase SQL Editor (or: `psql "$DATABASE_URL" -f supabase/init-seed.sql`).
 *   3. `.env.local` has SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY.
 *
 * Usage:  node scripts/setup-seed-db.mjs    (or  npm run setup:seed-db)
 *
 * The seeded account id is pinned to the seed's administrator profile id
 * (seed-data.sql: 'a0000000-...-001', administrator role) so that after login
 * the dashboard resolves role = admin and shows all 27 panels.
 */
import { config } from "dotenv";
config({ path: ".env.local" });
import { createClient } from "@supabase/supabase-js";

const URL = process.env.SUPABASE_URL;
const SERVICE_KEY = process.env.SUPABASE_SERVICE_ROLE_KEY;

const SEED_ACCOUNT = {
  email: "admin@e-sentinel.local",
  password: "E-Sentinel-Admin-2026!",
  // Must match the admin profile id in supabase/seed-data.sql
  id: "a0000000-0000-0000-0000-000000000001",
};

if (!URL || !SERVICE_KEY) {
  console.error("✗ Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY in .env.local");
  console.error("  Copy .env.local.example to .env.local, then provide your Supabase URL and service_role key.");
  process.exit(1);
}

const admin = createClient(URL, SERVICE_KEY, {
  auth: { persistSession: false, autoRefreshToken: false },
});

async function main() {
  console.log(`[setup-seed-db] Creating or reconciling seeded administrator account: ${SEED_ACCOUNT.email}`);

  // 1) Try to create with the pinned admin-profile id (idempotent).
  const { error: createErr } = await admin.auth.admin.createUser({
    id: SEED_ACCOUNT.id,
    email: SEED_ACCOUNT.email,
    password: SEED_ACCOUNT.password,
    email_confirm: true,
  });

  if (!createErr) {
    console.log("✓ Created seeded administrator account (id matches the seeded administrator profile)");
  } else if (/already|exists/i.test(createErr.message)) {
    const { error: updErr } = await admin.auth.admin.updateUserById(SEED_ACCOUNT.id, {
      password: SEED_ACCOUNT.password,
      email_confirm: true,
    });
    if (updErr) {
      console.error("✗ Failed to update seeded administrator account:", updErr.message);
      process.exit(1);
    }
    console.log("✓ Seeded administrator account already existed; password reset completed");
  } else {
    console.error("✗ Failed to create seeded administrator account:", createErr.message);
    process.exit(1);
  }

  // 2) Sanity: confirm the admin profile exists in the DB.
  const { data: profiles, error: profErr } = await admin
    .from("profiles")
    .select("id, name, role")
    .eq("id", SEED_ACCOUNT.id);
  if (profErr) {
    console.warn("⚠ Could not verify the profiles table; the database may not be initialized:", profErr.message);
  } else if (!profiles || profiles.length === 0) {
    console.warn("⚠ Administrator profile not found. Run supabase/init-seed.sql before retrying.");
  } else {
    console.log(`✓ Administrator profile verified: ${profiles[0].name} / ${profiles[0].role}`);
  }

  console.log(`\nComplete. Sign in to /dashboard with: ${SEED_ACCOUNT.email} / ${SEED_ACCOUNT.password}`);
  console.log("Prerequisite: initialize the database by running supabase/init-seed.sql once in the Supabase SQL Editor.");
}

main().catch((e) => {
  console.error("✗ Setup script failed:", e.message);
  process.exit(1);
});
