import { NextResponse } from "next/server";
import { requireApiKey } from "@/lib/api-auth";
import { supabaseAdmin } from "@/lib/supabase";

export async function GET(request: Request) {
  const auth = requireApiKey(request);
  if (auth.error) return auth.error;

  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ success: false, error: "Supabase not configured" }, { status: 500 });
    }

    // Clean up old audit logs (90+ days)
    const ninetyDaysAgo = new Date(Date.now() - 90 * 86400000).toISOString();
    const { count: auditDeleted } = await supabaseAdmin
      .from("audit_logs")
      .delete({ count: "exact" })
      .lt("created_at", ninetyDaysAgo);

    // Clean up old idempotency keys (not DB, just a note that we handle this in-memory)

    return NextResponse.json({
      success: true,
      cleaned: { audit_logs: auditDeleted || 0 },
    });
  } catch (error) {
    console.error("[Cron] Cleanup error:", error);
    return NextResponse.json({ success: false, error: String(error) }, { status: 500 });
  }
}
