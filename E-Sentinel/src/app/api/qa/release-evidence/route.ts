import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";
import { createCorrelationId } from "@/lib/correlation";
import { authorizeGovernanceRequest } from "@/lib/governance/authorization";

/**
 * Sprint 8: Release Evidence API
 * 管理发布证据、审批记录、金丝雀阶段和回滚信息
 */

// GET: 获取发布证据列表
export async function GET(request: Request) {
  const authorization = await authorizeGovernanceRequest(request);
  if (authorization.error) return authorization.error;
  const tenantId = authorization.context?.tenantId;
  if (!tenantId) return NextResponse.json({ error: "Tenant scope required" }, { status: 403 });

  const { searchParams } = new URL(request.url);
  const limit = Math.min(parseInt(searchParams.get("limit") || "20"), 100);
  const status = searchParams.get("status");

  if (!supabaseAdmin) {
    return NextResponse.json(
      { error: "Database not configured" },
      { status: 500 }
    );
  }

  try {
    let query = supabaseAdmin
      .from("release_evidences")
      .select("*")
      .order("created_at", { ascending: false })
      .limit(limit)
      .eq("tenant_id", tenantId);

    if (status) {
      query = query.eq("status", status);
    }

    const { data, error } = await query;

    if (error) {
      // 如果表不存在，返回空数据而不是错误
      if (error.message.includes("does not exist") || error.code === "42P01") {
        return NextResponse.json({
          releases: [],
          total: 0,
          message: "release_evidences 表尚未创建，请先运行数据库迁移",
        });
      }
      return NextResponse.json({ error: error.message }, { status: 500 });
    }

    return NextResponse.json({
      releases: data ?? [],
      total: data?.length ?? 0,
    });
  } catch (error) {
    console.error("[release-evidence] Error:", error);
    return NextResponse.json(
      { error: "Failed to fetch release evidences" },
      { status: 500 }
    );
  }
}

// POST: 创建发布证据
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
    const commitSha = body.commit_sha || body.commitSha;
    if (!commitSha) {
      return NextResponse.json(
        { error: "commit_sha is required" },
        { status: 400 }
      );
    }

    const correlationId = createCorrelationId("release");

    const evidence = {
      tenant_id: tenantId,
      commit_sha: commitSha,
      build_id: body.build_id || body.buildId || null,
      schema_version: body.schema_version || body.schemaVersion || null,
      rule_version: body.rule_version || body.ruleVersion || null,
      prompt_version: body.prompt_version || body.promptVersion || null,
      model_version: body.model_version || body.modelVersion || null,
      issue_ids: body.issue_ids || body.issueIds || [],
      pr_ids: body.pr_ids || body.prIds || [],
      adr_refs: body.adr_refs || body.adrRefs || [],
      required_checks: body.required_checks || body.requiredChecks || {},
      checks_passed: body.checks_passed ?? body.checksPassed ?? false,
      checks_failed: body.checks_failed || body.checksFailed || [],
      status: body.status || "pending",
      feature_flags: body.feature_flags || body.featureFlags || [],
      target_cohort: body.target_cohort || body.targetCohort || null,
      target_percentage: body.target_percentage || body.targetPercentage || 0,
      correlation_id: correlationId,
    };

    const { data, error } = await supabaseAdmin
      .from("release_evidences")
      .insert(evidence)
      .select()
      .single();

    if (error) {
      return NextResponse.json({ error: error.message }, { status: 500 });
    }

    return NextResponse.json({ evidence: data }, { status: 201 });
  } catch (error) {
    console.error("[release-evidence] Error:", error);
    return NextResponse.json(
      { error: "Failed to create release evidence" },
      { status: 500 }
    );
  }
}

// PATCH: 更新发布状态（审批、金丝雀、回滚等）
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
    const id = body.id || body.release_id || body.releaseId;
    const actorId = authorization.auth.user?.id || null;

    if (!id) {
      return NextResponse.json({ error: "id is required" }, { status: 400 });
    }

    const updates: Record<string, unknown> = {
      updated_at: new Date().toISOString(),
    };

    // 处理审批
    if (body.approval) {
      updates.approver_id = body.approval.approver_id || actorId;
      updates.approver_name = body.approval.approver_name;
      updates.approval_reason = body.approval.reason;
      updates.approved_at = new Date().toISOString();
    }

    // 处理金丝雀阶段
    if (body.canary) {
      updates.canary_current_stage = body.canary.stage;
      updates.observation_metrics = body.canary.metrics || {};
      if (body.canary.stage === "started") {
        updates.observation_started_at = new Date().toISOString();
      } else if (body.canary.stage === "completed") {
        updates.observation_ended_at = new Date().toISOString();
      }
    }

    // 处理回滚
    if (body.rollback) {
      updates.rollback_triggered = true;
      updates.rollback_reason = body.rollback.reason;
      updates.rollback_method = body.rollback.method || "feature_flag";
      updates.rollback_executed_at = new Date().toISOString();
      updates.rollback_executed_by = actorId;
      updates.status = "rolled_back";
    }

    // 处理状态变更
    if (body.status) {
      updates.status = body.status;
    }

    // 处理最终结论
    if (body.conclusion) {
      updates.final_conclusion = body.conclusion;
    }

    const { data, error } = await supabaseAdmin
      .from("release_evidences")
      .update(updates)
      .eq("id", id)
      .eq("tenant_id", tenantId)
      .select()
      .single();

    if (error) {
      return NextResponse.json({ error: error.message }, { status: 500 });
    }

    return NextResponse.json({ evidence: data });
  } catch (error) {
    console.error("[release-evidence] Error:", error);
    return NextResponse.json(
      { error: "Failed to update release evidence" },
      { status: 500 }
    );
  }
}
