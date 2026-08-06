import { createClient } from '@supabase/supabase-js';
import { createMockClient } from './mock-supabase';

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL as string;
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY as string;

if (!supabaseUrl || !supabaseAnonKey) {
  // Avoid crashing the build during static analysis; runtime calls will fail loudly.
  console.warn('[supabase] Missing NEXT_PUBLIC_SUPABASE_URL or NEXT_PUBLIC_SUPABASE_ANON_KEY');
}

export const supabase =
  process.env.NEXT_PUBLIC_DEMO_MODE === 'true'
    ? (createMockClient() as ReturnType<typeof createClient>)
    : createClient(supabaseUrl ?? '', supabaseAnonKey ?? '', {
        auth: { persistSession: false },
      });
