// ============================================================================
// Admin API auth — viewer/operator via separate env keys (adapted from rag-ai-agent)
// Server-only. Use timingSafeEqual for constant-time comparison.
// ============================================================================

import { timingSafeEqual } from "node:crypto";
import { supabaseAdmin } from "@/lib/supabase";
import { createCorrelationId } from "@/lib/correlation";

// Constant-time comparison to avoid timing side-channel attacks.
function safeKeyEqual(a: string, b: string): boolean {
  if (!a || !b) return false;
  const ab = Buffer.from(a);
  const bb = Buffer.from(b);
  if (ab.length !== bb.length) return false;
  return timingSafeEqual(ab, bb);
}

const OPERATOR_API_KEY = process.env.ADMIN_API_KEY || process.env.API_SECRET || "";
const ADMIN_VIEWER_KEY = process.env.ADMIN_VIEWER_KEY || "";

export type AdminRole = "viewer" | "operator";

export interface AdminAuthResult {
  role: AdminRole | null;
  error: Response | null;
}

/** Route-level authorization helper used by the shared API policy. */
export async function authorizeRequest(
  request: Request,
  options: { mutation?: boolean } = {},
): Promise<AdminAuthResult> {
  const key = request.headers.get("x-api-key");
  if (key) {
    const auth = await authenticateAdmin(request);
    if (!auth.error && options.mutation && auth.role !== "operator") {
      return {
        role: null,
        error: new Response(
          JSON.stringify({ error: "权限不足：需要 operator 角色。" }),
          { status: 403, headers: { "Content-Type": "application/json" } },
        ),
      };
    }
    return auth;
  }

  // Bearer validation is implemented in api-auth. Dynamic import avoids a
  // module cycle because api-auth also exposes the admin key helper.
  const { requireAuth } = await import("@/lib/api-auth");
  const auth = await requireAuth(request);
  if (auth.error) return { role: null, error: auth.error };
  return { role: "operator", error: null };
}

/**
 * Authenticate an admin request.
 *
 * - If no ADMIN_API_KEY or API_SECRET configured → 503
 * - If x-api-key matches ADMIN_VIEWER_KEY → viewer (read-only)
 * - If x-api-key matches ADMIN_API_KEY or API_SECRET → operator (read + write)
 * - Otherwise → 401
 */
export async function authenticateAdmin(request: Request): Promise<AdminAuthResult> {
  if (!OPERATOR_API_KEY) {
    return {
      role: null,
      error: new Response(
        JSON.stringify({ error: "Admin API not configured." }),
        { status: 503, headers: { "Content-Type": "application/json" } },
      ),
    };
  }

  const key = request.headers.get("x-api-key") || "";
  if (!key) {
    // Log failure
    try {
      if (supabaseAdmin) {
        await supabaseAdmin.from("audit_logs").insert({
          action: "auth_failure",
          resource_type: "admin",
          detail: { reason: "missing_x_api_key" },
          correlation_id: createCorrelationId(),
        });
      }
    } catch {}
    return {
      role: null,
      error: new Response(
        JSON.stringify({ error: "未授权：缺少 x-api-key。" }),
        { status: 401, headers: { "Content-Type": "application/json" } },
      ),
    };
  }

  if (safeKeyEqual(key, OPERATOR_API_KEY)) {
    return { role: "operator", error: null };
  }

  if (ADMIN_VIEWER_KEY && safeKeyEqual(key, ADMIN_VIEWER_KEY)) {
    return { role: "viewer", error: null };
  }

  try {
    if (supabaseAdmin) {
      await supabaseAdmin.from("audit_logs").insert({
        action: "auth_failure",
        resource_type: "admin",
        detail: { reason: "invalid_x_api_key" },
        correlation_id: createCorrelationId(),
      });
    }
  } catch {}

  return {
    role: null,
    error: new Response(
      JSON.stringify({ error: "未授权：x-api-key 无效。" }),
      { status: 401, headers: { "Content-Type": "application/json" } },
    ),
  };
}

export async function requireOperator(request: Request): Promise<AdminAuthResult> {
  const auth = await authenticateAdmin(request);
  if (auth.error) return auth;
  if (auth.role !== "operator") {
    return {
      role: null,
      error: new Response(
        JSON.stringify({ error: "权限不足：需要 operator 角色。" }),
        { status: 403, headers: { "Content-Type": "application/json" } },
      ),
    };
  }
  return auth;
}
