/**
 * Environment variable validation — fails fast on misconfiguration.
 *
 * Importing this module validates all required env vars at startup.
 * In demo mode, Supabase and LLM keys are optional.
 */

import { z } from 'zod';

const envSchema = z.object({
  // ── Demo mode ────────────────────────────────────────────────────────────
  NEXT_PUBLIC_DEMO_MODE: z
    .string()
    .optional()
    .transform((v) => v === 'true'),

  // ── App ──────────────────────────────────────────────────────────────────
  NEXT_PUBLIC_APP_URL: z
    .string()
    .url()
    .optional()
    .default('http://localhost:3000'),

  // ── Supabase (required in production, optional in demo mode) ──────────────
  NEXT_PUBLIC_SUPABASE_URL: z.string().optional(),
  NEXT_PUBLIC_SUPABASE_ANON_KEY: z.string().optional(),
  SUPABASE_SERVICE_ROLE_KEY: z.string().optional(),

  // ── LLM Provider ─────────────────────────────────────────────────────────
  AGENT_PROVIDER: z
    .enum(['qwen', 'claude', 'openai', 'mtclaw', 'local'])
    .optional()
    .default('qwen'),

  // ── Qwen / DashScope ─────────────────────────────────────────────────────
  DASHSCOPE_API_KEY: z.string().optional(),
  QWEN_MODEL: z.string().optional().default('qwen-plus'),

  // ── Anthropic Claude ─────────────────────────────────────────────────────
  ANTHROPIC_API_KEY: z.string().optional(),

  // ── OpenAI ───────────────────────────────────────────────────────────────
  OPENAI_API_KEY: z.string().optional(),

  // ── Local self-hosted LLM (AMD Radeon GPU + ROCm + vLLM/SGLang) ──────────
  // Private deployment: business data never leaves the premises.
  LOCAL_LLM_BASE_URL: z.string().optional(),
  LOCAL_LLM_API_KEY: z.string().optional(),
  LOCAL_LLM_MODEL: z.string().optional(),

  // ── Email (optional) ─────────────────────────────────────────────────────
  RESEND_API_KEY: z.string().optional(),
  NOTIFICATION_EMAIL: z.string().email().optional(),

  // ── Competition mode (optional) ──────────────────────────────────────────
  COMPETITION_MODE: z.enum(['qwen', 'casper']).optional(),

  // ── Casper Network (optional) ────────────────────────────────────────────
  NEXT_PUBLIC_CASPER_RPC_URL: z.string().url().optional(),

  // ── Stripe (optional, for monetization) ──────────────────────────────────
  STRIPE_SECRET_KEY: z.string().optional(),
  STRIPE_PRO_PRICE_ID: z.string().optional(),
  STRIPE_TEAM_PRICE_ID: z.string().optional(),
  STRIPE_WEBHOOK_SECRET: z.string().optional(),
});

export type Env = z.infer<typeof envSchema>;

function validateEnv(): Env {
  const parsed = envSchema.safeParse(process.env);

  if (!parsed.success) {
    const errors = parsed.error.issues
      .map((i) => `  ${i.path.join('.')}: ${i.message}`)
      .join('\n');
    console.error('[env] Invalid environment variables:\n' + errors);
    // Don't crash in demo mode — let the app start with mock data
    if (process.env.NEXT_PUBLIC_DEMO_MODE !== 'true') {
      throw new Error(`Environment validation failed:\n${errors}`);
    }
    // In demo mode, return a permissive fallback
    return process.env as unknown as Env;
  }

  const env = parsed.data;

  // Cross-field validation: non-demo mode requires Supabase keys
  if (!env.NEXT_PUBLIC_DEMO_MODE) {
    const missing: string[] = [];
    if (!env.NEXT_PUBLIC_SUPABASE_URL) missing.push('NEXT_PUBLIC_SUPABASE_URL');
    if (!env.NEXT_PUBLIC_SUPABASE_ANON_KEY) missing.push('NEXT_PUBLIC_SUPABASE_ANON_KEY');
    if (!env.SUPABASE_SERVICE_ROLE_KEY) missing.push('SUPABASE_SERVICE_ROLE_KEY');

    if (missing.length > 0) {
      console.warn(
        `[env] Missing Supabase keys: ${missing.join(', ')}. ` +
          'Set NEXT_PUBLIC_DEMO_MODE=true for demo mode, or provide all Supabase keys for production.'
      );
    }
  }

  return env;
}

export const env = validateEnv();
