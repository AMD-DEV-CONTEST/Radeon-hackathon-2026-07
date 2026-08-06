// ============================================================================
// API route authentication middleware
// - requireAuth: validates Supabase Bearer token (for user-facing routes)
// - requireApiKey: validates x-api-key header (for internal services, cron jobs)
// Enhanced with guard from rag reference for public endpoints (rate limit, validation, etc.)
// Admin uses dedicated admin-auth for roles.
// ============================================================================

import { createClient } from "@supabase/supabase-js";
import { timingSafeEqual } from "node:crypto";
import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";
import { createCorrelationId } from "@/lib/correlation";
import { guardPublicEndpoint } from "@/lib/api-guard";
import type { User } from "@supabase/supabase-js";

export interface AuthorizedRequest {
  user: User | null;
  authType: "bearer" | "api_key";
  role: "viewer" | "operator" | null;
}

function safeKeyEqual(actual: string, expected: string): boolean {
  if (!actual || !expected) return false;
  const actualBytes = Buffer.from(actual);
  const expectedBytes = Buffer.from(expected);
  return actualBytes.length === expectedBytes.length && timingSafeEqual(actualBytes, expectedBytes);
}

// ── Bearer token auth (user-facing routes) ──────────────────────────────

export async function requireAuth(request: Request) {
  const authHeader = request.headers.get("Authorization");

  if (!authHeader || !authHeader.startsWith("Bearer ")) {
    await logAuthFailure(request, "missing_authorization_header");
    return {
      error: NextResponse.json(
        { error: "Missing authorization" },
        { status: 401 },
      ),
    };
  }

  const token = authHeader.replace("Bearer ", "");

  // Create a fresh Supabase client to verify the user's JWT.
  // Using service_role key here is intentional — auth.getUser() verifies the
  // JWT against Supabase Auth regardless of the key's role.
  const authClient = createClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL || "",
    process.env.SUPABASE_SERVICE_ROLE_KEY || "",
  );

  const {
    data: { user },
    error,
  } = await authClient.auth.getUser(token);

  if (error || !user) {
    await logAuthFailure(request, "invalid_token", 401, error?.message);
    return {
      error: NextResponse.json(
        { error: "Invalid token" },
        { status: 401 },
      ),
    };
  }

  return { user };
}

// ── API key auth (cron jobs, internal services) ─────────────────────────

export function requireApiKey(request: Request) {
  const key = request.headers.get("x-api-key");
  const validKey = process.env.API_SECRET || "";

  if (!validKey) {
    console.warn("[api-auth] No API_SECRET configured — rejecting all API key auth requests");
    return {
      error: NextResponse.json(
        { error: "Server auth configuration missing" },
        { status: 500 },
      ),
    };
  }

  if (!key || key !== validKey) {
    return {
      error: NextResponse.json(
        { error: "Invalid API key" },
        { status: 401 },
      ),
    };
  }

  return { error: null };
}

/**
 * Shared API authorization for route handlers.
 * Bearer auth is used by the dashboard; x-api-key is reserved for internal
 * services and admin integrations. Viewer keys may only read data.
 */
export async function authorizeRequest(
  request: Request,
  options: { mutation?: boolean } = {},
): Promise<AuthorizedRequest & { error: NextResponse | null }> {
  const apiKey = request.headers.get("x-api-key");
  if (apiKey) {
    const expected = process.env.ADMIN_API_KEY || process.env.API_SECRET || "";
    const viewerKey = process.env.ADMIN_VIEWER_KEY || "";
    const role = safeKeyEqual(apiKey, expected)
      ? "operator"
      : safeKeyEqual(apiKey, viewerKey)
        ? "viewer"
        : null;

    if (!role) {
      await logAuthFailure(request, "invalid_x_api_key", 401);
      return {
        user: null,
        authType: "api_key",
        role: null,
        error: NextResponse.json({ error: "Invalid API key" }, { status: 401 }),
      };
    }

    if (options.mutation && role !== "operator") {
      await logAuthFailure(request, "viewer_mutation_forbidden", 403);
      return {
        user: null,
        authType: "api_key",
        role,
        error: NextResponse.json({ error: "Operator role required" }, { status: 403 }),
      };
    }

    return { user: null, authType: "api_key", role, error: null };
  }

  const auth = await requireAuth(request);
  if (auth.error) {
    return { user: null, authType: "bearer", role: null, error: auth.error };
  }

  return { user: auth.user, authType: "bearer", role: null, error: null };
}

// ── Public endpoint guard wrapper (new, from rag reference) ─────────────────────────
// Use for routes that accept user input (e.g. evaluate, export, share-card).
// Combines rate limit, spam, length validation, CORS.
export function guardPublic(request: Request, body: { message?: unknown; conversation?: unknown }) {
  return guardPublicEndpoint(request, body);
}

// ── Audit logging for failed auth attempts ──────────────────────────────

async function logAuthFailure(
  request: Request,
  reason: string,
  statusCode = 401,
  detail?: string,
) {
  try {
    if (!supabaseAdmin) {
      console.error(`[Audit] auth failure could not be persisted: ${reason}`);
      return;
    }

    const ip =
      request.headers.get("x-forwarded-for") ||
      request.headers.get("x-real-ip") ||
      "unknown";
    const userAgent = request.headers.get("user-agent") || "unknown";
    const path = new URL(request.url).pathname;

    const { error } = await supabaseAdmin.from("audit_logs").insert({
      action: "auth_failure",
      resource_type: "api",
      resource_id: path,
      detail: {
        reason,
        detail: detail || null,
        ip,
        user_agent: userAgent,
        method: request.method,
        path,
        status_code: statusCode,
      },
      correlation_id: createCorrelationId(),
    });

    if (error) {
      console.error(`[Audit] auth failure write failed: ${error.message}`);
    }
  } catch {
    console.error(`[Audit] auth failure write failed: ${reason}`);
  }
}
