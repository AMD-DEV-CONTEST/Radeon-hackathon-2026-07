import { createClient } from "@supabase/supabase-js";
import { NextRequest, NextResponse } from "next/server";

const PUBLIC_PATHS = new Set(["/api/qa/share-card"]);

async function recordFailure(request: NextRequest, reason: string): Promise<void> {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL || "";
  const key = process.env.SUPABASE_SERVICE_ROLE_KEY || "";
  if (!url || !key) {
    console.error(`[AuthProxy] ${reason}: audit unavailable`);
    return;
  }

  try {
    const db = createClient(url, key, { auth: { autoRefreshToken: false, persistSession: false } });
    const { error } = await db.from("audit_logs").insert({
      action: "auth_failure",
      resource_type: "api",
      resource_id: request.nextUrl.pathname,
      detail: {
        reason,
        status_code: 401,
        method: request.method,
        path: request.nextUrl.pathname,
        ip: request.headers.get("x-forwarded-for") || request.headers.get("x-real-ip") || "unknown",
      },
      correlation_id: `proxy_${crypto.randomUUID()}`,
    });
    if (error) console.error(`[AuthProxy] audit write failed: ${error.message}`);
  } catch (error) {
    console.error(`[AuthProxy] audit write failed: ${error instanceof Error ? error.message : "unknown error"}`);
  }
}

export async function middleware(request: NextRequest) {
  if (PUBLIC_PATHS.has(request.nextUrl.pathname) || request.method === "OPTIONS") {
    return NextResponse.next();
  }

  const apiKey = request.headers.get("x-api-key");
  const isMutation = ["POST", "PUT", "PATCH", "DELETE"].includes(request.method);
  const validApiKeys = [
    process.env.API_SECRET,
    process.env.ADMIN_API_KEY,
    process.env.ADMIN_VIEWER_KEY,
  ].filter((value): value is string => Boolean(value));

  if (apiKey && validApiKeys.includes(apiKey) && !(isMutation && apiKey === process.env.ADMIN_VIEWER_KEY)) {
    return NextResponse.next();
  }

  if (apiKey && apiKey === process.env.ADMIN_VIEWER_KEY && isMutation) {
    await recordFailure(request, "viewer_mutation_forbidden");
    return NextResponse.json({ error: "Operator authorization required" }, { status: 403 });
  }

  const authorization = request.headers.get("authorization");
  if (authorization?.startsWith("Bearer ")) {
    const token = authorization.slice("Bearer ".length).trim();
    const url = process.env.NEXT_PUBLIC_SUPABASE_URL || "";
    const key = process.env.SUPABASE_SERVICE_ROLE_KEY || "";
    if (token && url && key) {
      try {
        const authClient = createClient(url, key, { auth: { autoRefreshToken: false, persistSession: false } });
        const { data: { user } } = await authClient.auth.getUser(token);
        if (user) return NextResponse.next();
      } catch {
        // Fall through to the uniform unauthorized response.
      }
    }
    await recordFailure(request, "invalid_token");
  } else {
    await recordFailure(request, "missing_authorization");
  }

  return NextResponse.json({ error: "Missing or invalid authorization" }, { status: 401 });
}

export const config = {
  matcher: ["/api/qa/:path*"],
};
