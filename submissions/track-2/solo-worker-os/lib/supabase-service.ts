import { createClient, SupabaseClient } from '@supabase/supabase-js';
import { createMockClient } from './mock-supabase';

let _client: SupabaseClient | null = null;

/**
 * Server-only service-role client. Bypasses RLS entirely.
 * Use ONLY for: cron jobs, admin tasks, seed scripts.
 * Never import this from a Client Component or expose to browser.
 *
 * When NEXT_PUBLIC_DEMO_MODE=true, returns an in-memory mock client pre-seeded with demo data.
 */
export function createServiceClient(): SupabaseClient {
  if (_client) return _client;
  if (process.env.NEXT_PUBLIC_DEMO_MODE === 'true') {
    _client = createMockClient() as unknown as SupabaseClient;
    return _client;
  }
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!url || !key) {
    throw new Error('Missing NEXT_PUBLIC_SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY');
  }
  _client = createClient(url, key, {
    auth: { persistSession: false, autoRefreshToken: false },
  });
  return _client;
}
