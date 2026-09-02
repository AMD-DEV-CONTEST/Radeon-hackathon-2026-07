// ============================================================================
// Lazy SupabaseAdmin getter for adapter layer.
// Avoids top-level imports that would defeat cold-start optimization.
// ============================================================================

import type { SupabaseClient } from "@supabase/supabase-js";

let _db: SupabaseClient | null = null;

export async function getDb(): Promise<SupabaseClient | null> {
  if (_db) return _db;
  try {
    const { supabaseAdmin } = await import("../supabase");
    _db = supabaseAdmin;
    return _db;
  } catch {
    console.warn("[Adapter] Supabase client unavailable");
    return null;
  }
}
