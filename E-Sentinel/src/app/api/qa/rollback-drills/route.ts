import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";
import { authorizeGovernanceRequest } from "@/lib/governance/authorization";

/**
 * Sprint 8: Rollback Drills API
 * 管理回滚演练记录
 * - 每个 Release 至少完成一次演练
 * - 支持定期演练、发布后演练、随机演练
 */

// GET: 获取演练记录列表
export async function GET(request: Request) {
  const authorization = await authorizeGovernanceRequest(request);
  if (authorization.error) return authorization.error;
  const tenantId = authorization.context?.tenantId;
  if (!tenantId) return NextResponse.json({ error: "Tenant scope required" }, { status: 403 });

  const { searchParams } = new URL(request.url);
  const limit = Math.min(parseInt(searchParams.get("limit") || "20"), 100);
  const success = searchParams.get("success");
  const drillType = searchParams.get("drill_type");

  if (!supabaseAdmin) {
    return NextResponse.json(
      { error: "Database not configured" },
      { status: 500 }
    );
  }

  try {
    let query = supabaseAdmin
      .from("rollback_drills")
      .select("*")
      .order("started_at", { ascending: false })
      .limit(limit)
      .eq("tenant_id", tenantId);

    if (success !== null && success !== undefined) {
      query = query.eq("success", success === "true");
    }

    if (drillType) {
      query = query.eq("drill_type", drillType);
    }

    const { data, error } = await query;

    if (error) {
      // 表不存在时返回空数据
      if (error.message.includes("does not exist") || error.code === "42P01") {
        return NextResponse.json({
          drills: [],
          total: 0,
          message: "rollback_drills 表尚未创建",
        });
      }
      return NextResponse.json({ error: error.message }, { status: 500 });
    }

    // 计算统计信息
    const stats = {
      total: data?.length ?? 0,
      successful: data?.filter((d) => d.success === true).length ?? 0,
      failed: data?.filter((d) => d.success === false).length ?? 0,
      pending: data?.filter((d) => d.success === null).length ?? 0,
      avg_duration_seconds:
        data && data.length > 0
          ? Math.round(
              data
                .filter((d) => d.duration_seconds)
                .reduce((sum, d) => sum + (d.duration_seconds || 0), 0) /
                data.filter((d) => d.duration_seconds).length
            )
          : null,
    };

    return NextResponse.json({
      drills: data ?? [],
      stats,
    });
  } catch (error) {
    console.error("[rollback-drills] Error:", error);
    return NextResponse.json(
      { error: "Failed to fetch rollback drills" },
      { status: 500 }
    );
  }
}

// POST: 创建演练记录
export async function POST(request: Request) {
  const authorization = await authorizeGovernanceRequest(request, { mutation: true });
  if (authorization.error) return authorization.error;
  const tenantId = authorization.context?.tenantId;
  if (!tenantId) return NextResponse.json({ error: "Tenant scope required" }, { status: 403 });

  if (!supabaseAdmin) {
    return NextResponse.json(
      { error: "Database not configured" },
      { status: 500 }
    );
  }

  try {
    const body = await request.json();

    // 验证必填字段
    const drillName = body.drill_name || body.drillName;
    const drillType = body.drill_type || body.drillType;
    const triggeredBy = body.triggered_by || body.triggeredBy;

    if (!drillName || !drillType || !triggeredBy) {
      return NextResponse.json(
        { error: "drill_name, drill_type, and triggered_by are required" },
        { status: 400 }
      );
    }

    const drill = {
      tenant_id: tenantId,
      drill_name: drillName,
      drill_type: drillType, // 'scheduled', 'random', 'release_based'
      triggered_by: triggeredBy,
      started_at: body.started_at || body.startedAt || new Date().toISOString(),
      release_evidence_id: body.release_evidence_id || body.releaseEvidenceId || null,
    };

    const { data, error } = await supabaseAdmin
      .from("rollback_drills")
      .insert(drill)
      .select()
      .single();

    if (error) {
      return NextResponse.json({ error: error.message }, { status: 500 });
    }

    return NextResponse.json({ drill: data }, { status: 201 });
  } catch (error) {
    console.error("[rollback-drills] Error:", error);
    return NextResponse.json(
      { error: "Failed to create rollback drill" },
      { status: 500 }
    );
  }
}

// PATCH: 更新演练结果
export async function PATCH(request: Request) {
  const authorization = await authorizeGovernanceRequest(request, { mutation: true });
  if (authorization.error) return authorization.error;
  const tenantId = authorization.context?.tenantId;
  if (!tenantId) return NextResponse.json({ error: "Tenant scope required" }, { status: 403 });

  if (!supabaseAdmin) {
    return NextResponse.json(
      { error: "Database not configured" },
      { status: 500 }
    );
  }

  try {
    const body = await request.json();
    const id = body.id || body.drill_id || body.drillId;

    if (!id) {
      return NextResponse.json({ error: "id is required" }, { status: 400 });
    }

    const updates: Record<string, unknown> = {};

    // 处理演练完成
    if (body.completed !== undefined || body.success !== undefined) {
      updates.completed_at = new Date().toISOString();

      if (body.started_at) {
        const started = new Date(body.started_at);
        const completed = new Date();
        updates.duration_seconds = Math.round(
          (completed.getTime() - started.getTime()) / 1000
        );
      }

      updates.success = body.success;
      updates.failure_reason = body.failure_reason || body.failureReason || null;
      updates.missing_steps = body.missing_steps || body.missingSteps || [];
      updates.notes = body.notes || null;
    }

    if (Object.keys(updates).length === 0) {
      return NextResponse.json({ error: "No update fields provided" }, { status: 400 });
    }

    const { data, error } = await supabaseAdmin
      .from("rollback_drills")
      .update(updates)
      .eq("id", id)
      .eq("tenant_id", tenantId)
      .select()
      .single();

    if (error) {
      return NextResponse.json({ error: error.message }, { status: 500 });
    }

    return NextResponse.json({ drill: data });
  } catch (error) {
    console.error("[rollback-drills] Error:", error);
    return NextResponse.json(
      { error: "Failed to update rollback drill" },
      { status: 500 }
    );
  }
}

// DELETE: 删除演练记录 (仅限未完成的)
export async function DELETE(request: Request) {
  const authorization = await authorizeGovernanceRequest(request, { mutation: true });
  if (authorization.error) return authorization.error;
  const tenantId = authorization.context?.tenantId;
  if (!tenantId) return NextResponse.json({ error: "Tenant scope required" }, { status: 403 });

  if (!supabaseAdmin) {
    return NextResponse.json(
      { error: "Database not configured" },
      { status: 500 }
    );
  }

  try {
    const { searchParams } = new URL(request.url);
    const id = searchParams.get("id");

    if (!id) {
      return NextResponse.json({ error: "id parameter is required" }, { status: 400 });
    }

    // 只能删除未完成的演练
    const { data: existing } = await supabaseAdmin
      .from("rollback_drills")
      .select("id, success")
      .eq("id", id)
      .eq("tenant_id", tenantId)
      .single();

    if (!existing) {
      return NextResponse.json({ error: "Drill not found" }, { status: 404 });
    }

    if (existing.success !== null) {
      return NextResponse.json(
        { error: "Cannot delete completed drill records" },
        { status: 400 }
      );
    }

    const { error } = await supabaseAdmin
      .from("rollback_drills")
      .delete()
      .eq("id", id)
      .eq("tenant_id", tenantId);

    if (error) {
      return NextResponse.json({ error: error.message }, { status: 500 });
    }

    return NextResponse.json({ success: true });
  } catch (error) {
    console.error("[rollback-drills] Error:", error);
    return NextResponse.json(
      { error: "Failed to delete rollback drill" },
      { status: 500 }
    );
  }
}