import { NextRequest, NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";
import { createCorrelationId } from "@/lib/correlation";
import { getConfigNumber } from "@/lib/system-config";
import { recordLLMCall } from "@/lib/llm-metrics";
import { callLLM, getCached, setCache } from "@/lib/llm-provider";

// GET /api/qa/payment-reminders — list pending orders with reminder stats
export async function GET(request: NextRequest) {
  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }

    const { searchParams } = new URL(request.url);
    const status = searchParams.get("status");
    const limit = parseInt(searchParams.get("limit") || "50");

    let query = supabaseAdmin
      .from("pending_orders")
      .select("*, reminders:payment_reminders(count)")
      .order("created_at", { ascending: false })
      .limit(Math.min(limit, 200));

    if (status) query = query.eq("order_status", status);

    const { data, error } = await query;
    if (error) {
      if (error.message?.includes("does not exist")) {
        return NextResponse.json({ orders: [], counts: {} });
      }
      throw error;
    }

    // Get summary counts
    const counts: Record<string, number> = {};
    try {
      for (const s of ["pending_payment", "reminded", "paid", "cancelled", "expired"]) {
        const { count } = await supabaseAdmin
          .from("pending_orders")
          .select("*", { count: "exact", head: true })
          .eq("order_status", s);
        counts[s] = count || 0;
      }
    } catch { /* counts query failed, non-critical */ }

    return NextResponse.json({ orders: data || [], counts });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    if (message.includes("does not exist")) {
      return NextResponse.json({ orders: [], counts: {} });
    }
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

// POST /api/qa/payment-reminders — import/sync pending orders
export async function POST(request: NextRequest) {
  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }

    const body = await request.json();
    const orders = Array.isArray(body.orders) ? body.orders : [body];
    const corrId = createCorrelationId("pmt");

    let imported = 0;
    let skipped = 0;

    for (const order of orders) {
      if (!order.external_order_id) { skipped++; continue; }

      const { error } = await supabaseAdmin.from("pending_orders").upsert({
        external_order_id: String(order.external_order_id),
        platform_id: order.platform_id || null,
        customer_id: order.customer_id || null,
        customer_name: order.customer_name || null,
        product_name: order.product_name || null,
        order_amount: order.order_amount ? Number(order.order_amount) : null,
        order_status: order.order_status || "pending_payment",
        created_at_order: order.created_at_order || new Date().toISOString(),
        expire_at: order.expire_at || null,
        metadata: order.metadata || {},
      }, { onConflict: "external_order_id,platform_id" });

      if (error) { skipped++; } else { imported++; }
    }

    return NextResponse.json({ imported, skipped, correlation_id: corrId }, { status: 201 });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

// PUT /api/qa/payment-reminders — send reminders for eligible orders
export async function PUT(request: NextRequest) {
  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }

    const body = await request.json();
    const orderIds: string[] | undefined = body.order_ids;
    const maxRounds = await getConfigNumber("payment_reminder_max_rounds", 3);

    // Find eligible orders: pending_payment or reminded but under max rounds
    let query = supabaseAdmin
      .from("pending_orders")
      .select("*, reminders:payment_reminders(id, round)");

    if (orderIds && orderIds.length > 0) {
      query = query.in("id", orderIds);
    } else {
      query = query.or("order_status.eq.pending_payment,order_status.eq.reminded");
    }

    const { data: eligibleOrders, error } = await query.limit(20);
    if (error) throw error;

    if (!eligibleOrders || eligibleOrders.length === 0) {
      return NextResponse.json({ sent: 0, message: "No eligible orders" });
    }

    // Filter orders that haven't exceeded max rounds
    const toRemind = (eligibleOrders as Array<Record<string, unknown>>).filter((o) => {
      const reminders = Array.isArray(o.reminders) ? o.reminders : [];
      return reminders.length < maxRounds;
    });

    let sent = 0;
    for (const order of toRemind) {
      const round = (Array.isArray(order.reminders) ? order.reminders.length : 0) + 1;

      // Generate personalized reminder script via LLM
      let script = "";
      try {
        const prompt = `你是一个电商客服AI，请生成一条催付提醒消息。
客户姓名: ${order.customer_name || "顾客"}
商品: ${order.product_name || "未知商品"}
金额: ¥${order.order_amount || "待确认"}
催付轮次: 第${round}轮
要求: 语气亲切友好，30字以内，提醒客户及时完成支付，避免订单过期。`;

        const cacheKey = `pmt:reminder:${order.id}:r${round}`;
        const cachedScript = getCached(cacheKey);

        if (cachedScript) {
          script = cachedScript;
          recordLLMCall({ endpoint: "/api/qa/payment-reminders", model: "auto", responseTimeMs: 0, tokensUsed: 0, success: true, cached: true });
        } else {
          const t0 = Date.now();
          const generated = await callLLM({
            prompt,
            temperature: 0.7,
            maxTokens: 120,
          });

          const elapsed = Date.now() - t0;

          if (generated) {
            script = generated.trim();
            recordLLMCall({ endpoint: "/api/qa/payment-reminders", model: "auto", responseTimeMs: elapsed, tokensUsed: Math.ceil(generated.length / 2), success: true, cached: false });
            setCache(cacheKey, script, Math.ceil(generated.length / 2), "auto");
          } else {
            recordLLMCall({ endpoint: "/api/qa/payment-reminders", model: "auto", responseTimeMs: elapsed, tokensUsed: 0, success: false });
          }
        }
      } catch {
        recordLLMCall({ endpoint: "/api/qa/payment-reminders", model: "auto", responseTimeMs: 0, tokensUsed: 0, success: false });
        script = `亲爱的${order.customer_name || "顾客"}，您的订单${order.external_order_id}待支付，请及时完成付款哦～`;
      }

      if (!script) {
        script = round === 1
          ? `亲爱的顾客，您的订单${order.external_order_id}已生成，请及时完成支付～`
          : `温馨提醒：您的订单${order.external_order_id}即将过期，请尽快支付以免失效～`;
      }

      // Insert reminder
      await supabaseAdmin.from("payment_reminders").insert({
        order_id: order.id,
        round,
        script,
        channel: "bot",
        status: "sent",
        sent_at: new Date().toISOString(),
      });

      // Update order status
      await supabaseAdmin.from("pending_orders")
        .update({ order_status: "reminded", updated_at: new Date().toISOString() })
        .eq("id", order.id);

      sent++;
    }

    return NextResponse.json({ sent, eligible: toRemind.length, correlation_id: createCorrelationId("pmt") });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
