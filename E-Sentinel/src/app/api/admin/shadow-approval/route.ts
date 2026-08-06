// ============================================================================
// GET/POST /api/admin/shadow-approval — human review for AI replies
// Before real replies are sent, a human must approve them (Phase 3a gate).
// ============================================================================

import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";
import { authorizeRequest } from "@/lib/admin-auth";

/** GET — list pending approvals */
export async function GET(request: Request) {
  const auth = await authorizeRequest(request);
  if (auth.error) return auth.error;

  if (!supabaseAdmin) {
    return NextResponse.json({ error: "Database not available" }, { status: 503 });
  }

  const url = new URL(request.url);
  const page = parseInt(url.searchParams.get("page") || "1", 10);
  const limit = Math.min(parseInt(url.searchParams.get("limit") || "20", 10), 100);
  const offset = (page - 1) * limit;

  try {
    const { data, error, count } = await supabaseAdmin
      .from("actual_replies")
      .select("*", { count: "exact" })
      .eq("sent_success", false)
      .order("created_at", { ascending: false })
      .range(offset, offset + limit - 1);

    if (error) {
      // Table doesn't exist yet (migration not run on prod) → return empty
      if (error.code === "42P01") {
        return NextResponse.json({ data: [], page, limit, total: 0 });
      }
      return NextResponse.json({ error: error.message }, { status: 500 });
    }

    return NextResponse.json({
      data,
      page,
      limit,
      total: count ?? 0,
    });
  } catch {
    return NextResponse.json({ data: [], page, limit, total: 0 });
  }
}

/** POST — approve or reject a reply */
export async function POST(request: Request) {
  const auth = await authorizeRequest(request, { mutation: true });
  if (auth.error) return auth.error;

  if (!supabaseAdmin) {
    return NextResponse.json({ error: "Database not available" }, { status: 503 });
  }

  let body: Record<string, unknown>;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON" }, { status: 400 });
  }

  const action = body.action as string;
  const replyId = body.reply_id as string;
  const reviewedBy = (body.reviewed_by as string) || "admin";

  if (!replyId || !["approve", "reject"].includes(action)) {
    return NextResponse.json({ error: "Required: reply_id, action (approve|reject)" }, { status: 400 });
  }

  if (action === "reject") {
    const { error } = await supabaseAdmin
      .from("actual_replies")
      .update({
        metadata: {
          reviewed_by: reviewedBy,
          reviewed_at: new Date().toISOString(),
          rejected: true,
          reject_reason: (body.reason as string) || "未指定原因",
        },
      })
      .eq("id", replyId);

    if (error) {
      return NextResponse.json({ error: error.message }, { status: 500 });
    }

    return NextResponse.json({ status: "rejected", reply_id: replyId });
  }

  // Approve: send via platform adapter
  const { data: replyRow } = await supabaseAdmin
    .from("actual_replies")
    .select("*")
    .eq("id", replyId)
    .single();

  if (!replyRow) {
    return NextResponse.json({ error: "Reply not found" }, { status: 404 });
  }

  // Try to send via adapter
  let sentSuccess = false;
  let platformMsgId: string | undefined;

  try {
    const { getAdapter } = await import("@/lib/adapters/registry");
    const adapter = getAdapter("tmall");
    if (adapter && !adapter.health.isCircuitOpen) {
      const result = await adapter.sendReply({
        in_reply_to: {
          platform_message_id: replyRow.message_id as string,
          platform_code: "tmall",
          session_id: replyRow.session_id as string,
          customer_id: replyRow.customer_id as string,
          content: replyRow.original_text as string,
          message_type: "text",
          timestamp: replyRow.created_at as string,
          reply_context: {},
        },
        content: replyRow.sanitized_reply as string,
        reply_type: "text",
      });
      sentSuccess = result.success;
      platformMsgId = result.messageId;
    }
  } catch (err) {
    console.error("[Approval] Send error:", String(err).slice(0, 100));
  }

  // Update the record
  const { error } = await supabaseAdmin
    .from("actual_replies")
    .update({
      sent_success: sentSuccess,
      sent_at: sentSuccess ? new Date().toISOString() : null,
      platform_msg_id: platformMsgId || null,
      metadata: {
        reviewed_by: reviewedBy,
        reviewed_at: new Date().toISOString(),
        approved: true,
        sent_success: sentSuccess,
      },
    })
    .eq("id", replyId);

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  return NextResponse.json({
    status: sentSuccess ? "sent" : "approved_pending_send",
    reply_id: replyId,
    platform_msg_id: platformMsgId,
  });
}
