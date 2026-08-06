import { createServerClient as createSSRClient } from '@supabase/ssr';
import type { SupabaseClient } from '@supabase/supabase-js';
import { cookies } from 'next/headers';
import { createMockClient } from './mock-supabase';

const supabaseUrl  = process.env.NEXT_PUBLIC_SUPABASE_URL!;
const supabaseAnon = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!;

/**
 * User-scoped Supabase client for Server Components and Route Handlers.
 * Reads the auth session from cookies — respects RLS automatically.
 * Use this for all user-initiated data operations.
 *
 * When NEXT_PUBLIC_DEMO_MODE=true, returns an in-memory mock client pre-seeded with demo data.
 */
export function createSupabaseServerClient(): SupabaseClient {
  if (process.env.NEXT_PUBLIC_DEMO_MODE === 'true') {
    return createMockClient() as unknown as SupabaseClient;
  }
  const cookieStore = cookies();
  return createSSRClient(supabaseUrl, supabaseAnon, {
    cookies: {
      getAll() {
        return cookieStore.getAll();
      },
      setAll(cookiesToSet) {
        try {
          for (const { name, value, options } of cookiesToSet) {
            cookieStore.set(name, value, options);
          }
        } catch {
          // setAll from a Server Component — cookies are read-only,
          // this is fine; the middleware refreshes them.
        }
      },
    },
  });
}

/**
 * Returns an authenticated Supabase client for API route handlers.
 *
 * In demo mode: returns the mock client (no auth needed).
 * In production: returns the user-scoped client if authenticated.
 * If unauthenticated, throws an AuthError that the caller should catch
 * and convert to a 401 response.
 *
 * This replaces the insecure `user ? userClient : createServiceClient()`
 * pattern that allowed unauthenticated API calls to bypass RLS via the
 * service-role client.
 */
export class AuthError extends Error {
  constructor() {
    super('Unauthorized');
    this.name = 'AuthError';
  }
}

export async function getAuthenticatedClient(): Promise<SupabaseClient> {
  // Demo mode: no auth, use mock client directly
  if (process.env.NEXT_PUBLIC_DEMO_MODE === 'true') {
    return createMockClient() as unknown as SupabaseClient;
  }

  const userClient = createSupabaseServerClient();
  const { data: { user } } = await userClient.auth.getUser().catch(() => ({
    data: { user: null },
  }));

  if (!user) throw new AuthError();
  return userClient;
}

/**
 * Returns an authenticated Supabase client AND the user object in a single
 * auth call. Use this instead of getAuthenticatedClient() + supabase.auth.getUser()
 * to avoid the redundant double-auth that adds ~100-200ms latency per request.
 *
 * Returns { client, user } — in demo mode, user is null (mock client has no real user).
 */
export async function getAuthenticatedClientWithUser(): Promise<{
  client: SupabaseClient;
  user: { id: string } | null;
}> {
  if (process.env.NEXT_PUBLIC_DEMO_MODE === 'true') {
    return { client: createMockClient() as unknown as SupabaseClient, user: null };
  }

  const userClient = createSupabaseServerClient();
  const { data: { user } } = await userClient.auth.getUser().catch(() => ({
    data: { user: null },
  }));

  if (!user) throw new AuthError();
  return { client: userClient, user: { id: user.id } };
}

// ─── Re-export service client for the few places that still need it ──────────
export { createServiceClient } from './supabase-service';

/** @deprecated Use createSupabaseServerClient() instead. Kept for backwards compat during migration. */
export { createServiceClient as createServerClient } from './supabase-service';
