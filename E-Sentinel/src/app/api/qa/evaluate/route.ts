// ReAct agent 多轮调用需要更长超时；Vercel Hobby 支持 60s
export const maxDuration = 60;

import { authorizeRequest, guardPublic } from "@/lib/api-auth";
import { supabaseAdmin } from "@/lib/supabase";
import { createCorrelationId } from "@/lib/correlation";
import { dispatchAlert, sendFeishuGroupCard, isFeishuEnabled } from "@/lib/feishu";
import { textToEmbedding } from "@/lib/embedding";
import { recordLLMCall } from "@/lib/llm-metrics";
import { callLLM, getCached, setCache } from "@/lib/llm-provider";
import { runJudge, runInvestigation } from "@/lib/agent/evaluate-judge";
import type { AgentEvidence } from "@/lib/agent/types";
import { deriveRequiredTools, classifyFindingType, deriveRetrievalQuery, type FindingType } from "@/lib/agent/investigation-policy";
import { getFewShotExamples } from "@/lib/few-shot";
import { scanHardRedlines, classifySoftSignals, floorFromHighestRisk, type RiskLevel } from "@/lib/compliance-engine";
import {
  QUALITY_STANDARDS,
  resolveFinalRisk,
  validateAgentEscalation,
  computeRequiresHumanReview,
  applyCustomerIssueMediumFloor,
} from "@/lib/qa/evaluate-core";
import { apiOk, apiErr } from "@/lib/api-response";
import { composeFinalAnswer } from "@/lib/answer-composer";
import { loadGovernanceContext } from "@/lib/governance/roles";
import { persistQualityEvaluation, type QualityViolation, type QualityEvaluationInput } from "@/lib/governance/quality-loop";

// ── 质检标准（RAG fallback，规则库为空时使用）已由 evaluate-core 提供（QUALITY_STANDARDS）

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

// ── RAG 检索 ───────────────────────────────────────────
async function retrieveRules(conversation: string): Promise<string> {
  if (!supabaseAdmin) return QUALITY_STANDARDS;

  try {
    const embedding = textToEmbedding(conversation);
    const { data: matches, error } = await supabaseAdmin.rpc("match_quality_rules", {
      query_embedding: JSON.stringify(embedding),
      match_count: 5,
    });

    if (error || !matches || matches.length === 0) return QUALITY_STANDARDS;

    const lines = (matches as Array<Record<string, unknown>>).map(
      (m, i: number) =>
        `${i + 1}. 【${String(m.category || "")}·${String(m.severity || "")}】(扣${String(m.deduction_min || 0)}-${String(m.deduction_max || 0)}分) ${String(m.rule_text || "")}${m.examples ? ` 举例：${String(m.examples)}` : ""}`
    );

    return `【动态检索到的相关质检规则（共${matches.length}条）】\n${lines.join("\n")}\n\n【兜底通用规则】\n${QUALITY_STANDARDS}`;
  } catch {
    return QUALITY_STANDARDS;
  }
}

function parseJsonContent(content: string): Record<string, unknown> | null {
  const raw = content
    .replace(/```json\s*/gi, "")
    .replace(/```\s*/gi, "")
    .trim();

  const objStart = raw.indexOf("{");
  const objEnd = raw.lastIndexOf("}");
  if (objStart !== -1 && objEnd !== -1 && objEnd > objStart) {
    const objStr = raw.substring(objStart, objEnd + 1);
    try {
      return JSON.parse(objStr);
    } catch {}
    const cleaned = objStr.replace(/[\x00-\x1f]/g, " ");
    try {
      return JSON.parse(cleaned);
    } catch {}
    try {
      let repaired = cleaned;
      const openBraces = (repaired.match(/\{/g) || []).length;
      const closeBraces = (repaired.match(/\}/g) || []).length;
      const openBrackets = (repaired.match(/\[/g) || []).length;
      const closeBrackets = (repaired.match(/\]/g) || []).length;
      if ((repaired.match(/"/g) || []).length % 2 !== 0) repaired += '"';
      for (let i = closeBraces; i < openBraces; i++) repaired += "}";
      for (let i = closeBrackets; i < openBrackets; i++) repaired += "]";
      return JSON.parse(repaired);
    } catch {}
  }

  console.error("[QA] Cannot parse JSON from:", raw.slice(0, 300));
  return null;
}

export async function POST(request: Request) {
  const auth = await authorizeRequest(request, { mutation: true });
  if (auth.error) return auth.error;
  const context = auth.user ? await loadGovernanceContext(auth.user.id) : null;

  const correlationId = createCorrelationId();

  try {
    if (!supabaseAdmin) {
      return apiErr("Supabase not configured", "CONFIG_ERROR", 500);
    }

    const body = await request.json().catch(() => null);
    const conversation = typeof body?.conversation === "string" ? body.conversation.trim() : "";
    const ticketId = typeof body?.ticket_id === "string" ? body.ticket_id : `ticket_${correlationId}`;
    const agentId = typeof body?.agent_id === "string" ? body.agent_id : null;
    // Dify 部署场景默认跳过飞书告警（用户补充：DIFY 上只需要稳定使用，不需要飞书告警）
    // 也可显式传 skip_feishu: true，或设置 DISABLE_FEISHU_ALERTS=true / DIFY_MODE=true
    const isDifyMode = !isFeishuEnabled();
    const skipFeishu = body?.skip_feishu === true || isDifyMode;
    const backdateCreatedAt = typeof body?.created_at === "string" ? body.created_at : null;
    const reviewMode = body?.review_mode === "shadow" ? "shadow" : "active";

    // ── 消融变体（ADR-0003 5 层架构） ─────────────────────────
    // eval_mode 决定哪些层参与：llm_only（纯 LLM）/ dual（+硬红线+软信号）/
    // dual_rag（+RAG 规则）/ dual_rag_memory（+few-shot 记忆）/ agent（+Agent 调查员）/
    // baseline_only（只出语义基线，供配对消融共享快照）。
    // 生产默认 dual_rag_memory（RAG+few-shot+硬红线+软信号，无 Agent）；QA_AGENT_ENABLED=1 或 use_agent=true 时叠加调查。
    const EVAL_MODES = ["llm_only", "dual", "dual_rag", "dual_rag_memory", "agent", "baseline_only"] as const;
    type EvalMode = (typeof EVAL_MODES)[number];
    const evalMode = (EVAL_MODES as readonly string[]).includes(String(body?.eval_mode))
      ? (body?.eval_mode as EvalMode)
      : "dual_rag_memory";
    const isBaselineOnly = evalMode === "baseline_only";
    const wantAgent = (evalMode === "agent" || body?.use_agent === true || process.env.QA_AGENT_ENABLED === "1") && !isBaselineOnly;
    const useRag = isBaselineOnly || evalMode === "dual_rag" || evalMode === "dual_rag_memory" || evalMode === "agent";
    const useFewShot = isBaselineOnly || evalMode === "dual_rag_memory" || evalMode === "agent";
    const useHardFloor = !isBaselineOnly && evalMode !== "llm_only";
    const useSoftSignals = !isBaselineOnly && evalMode !== "llm_only";
    // 稳定性评测：no_cache=true 时绕过 LLM 消息缓存与响应缓存，强制真实独立推理
    const noCache = body?.no_cache === true;
    // 配对消融（--paired）：baseline_override 提供共享语义基线快照，跳过 runJudge 复用同一结果。
    let baselineOverride: Record<string, unknown> | null = null;
    const rawOverride = body?.baseline_override;
    if (typeof rawOverride === "string") {
      try { baselineOverride = JSON.parse(rawOverride); } catch { baselineOverride = null; }
    } else if (rawOverride && typeof rawOverride === "object") {
      baselineOverride = rawOverride as Record<string, unknown>;
    }
    const useBaselineOverride = Boolean(
      baselineOverride && typeof baselineOverride.risk_level === "string"
    );

    const guardErr = guardPublic(request, { conversation });
    if (guardErr) return guardErr;

    if (!conversation || conversation.length < 20) {
      return apiErr("conversation is required (min 20 chars)", "BAD_REQUEST", 400);
    }

    console.log(`[QA] ${correlationId} Starting evaluation (mode=${reviewMode}), conversation length: ${conversation.length}`);

    // 解析 agent 身份
    let agentProfile: { id?: string; name?: string; role?: string; team_id?: string } | null = null;
    let reviewerId: string | null = null;
    let teamId: string | null = null;

    if (agentId) {
      const { data: profile } = await supabaseAdmin
        .from("profiles")
        .select("id, name, role, team_id")
        .eq("id", agentId)
        .maybeSingle();
      agentProfile = profile;

      if (profile?.team_id) {
        teamId = profile.team_id;
        const { data: lead } = await supabaseAdmin
          .from("profiles")
          .select("id")
          .eq("team_id", teamId)
          .eq("role", "team_lead")
          .maybeSingle();
        reviewerId = lead?.id || null;
      }
    }

    // ── RAG 规则检索（dual_rag+ / agent） ─────────────────
    const retrievedRules = useRag ? await retrieveRules(conversation) : QUALITY_STANDARDS;
    console.log(`[QA] ${correlationId} eval_mode=${evalMode} agent=${wantAgent} rules=${useRag ? "rag" : "static"}`);

    // ── LLM 质检裁判（第 2 层：语义基线，唯一风险裁判） ────
    const systemPrompt = `你是电商客服质检系统的 AI 裁判官。请对以下客服对话进行严格质量评估，输出纯 JSON 对象，不要包裹 markdown 代码块。

${retrievedRules}

【输出 JSON 格式要求】
{
  "intent": "客户真实意图（简短概括，10字以内）",
  "sentiment_score": 1-5（1=平静 2=略不满 3=不满 4=愤怒 5=极其愤怒）,
  "total_score": 0-100（各项扣分后的总分）,
  "risk_level": "low|medium|high|critical"（critical=分数低于60或情绪为5级）,
  "violations": [
    {
      "category": "服务态度|专业性|响应效率|解决问题|合规与隐私",
      "rule": "违反的具体标准条款",
      "deduction": 扣分值（整数）,
      "severity": "minor|major|critical",
      "source_quote": "从对话原文中精准摘录的违规证据",
      "finding_type": "false_commitment|product_accuracy|refund_policy|policy_mismatch|privacy_request|threat_or_abuse|service_attitude|other"
    }
  ],
  "summary": "质检总结（50字以内，指出核心问题和改进方向）"
}

【finding_type 判定指引】
- false_commitment：虚假承诺/夸大保证（如"肯定到账""个人赔偿""保证有效"）
- product_accuracy：产品/价格/参数/兼容性信息不实
- refund_policy：退款/退货/运费/赔付政策相关违规
- policy_mismatch：服务流程/政策执行不一致
- privacy_request：索要验证码/银行卡/密码等隐私
- threat_or_abuse：威胁、辱骂、贬低客户
- service_attitude：推诿、敷衍、消极应对等服务态度
- other：其他
该字段决定是否必须检索企业政策/产品知识库（false_commitment/product_accuracy/refund_policy/policy_mismatch 需要），请如实标注。

【评审要求】
1. 每个违规点必须引用对话原文作为 source_quote，严禁自行概括。
2. 无违规则 violations 为空数组 []，total_score 为 100。
3. 扣分力度与违规严重程度成正比：minor 扣 2-5 分，major 扣 5-15 分，critical 扣 15-30 分。
4. risk_level 综合判定（客服回复质量 + 客户问题严重程度双维度）：
   - critical = 总分 < 60, 或 sentiment = 5, 或涉及人身安全/法律风险, 或客服存在威胁、索要隐私（验证码/银行卡）、绝对化虚假承诺
   - high = 总分 60-74, 或客服明确推诿、敷衍、贬低客户、拒绝服务、消极不解决
   - medium = 总分 75-89, 或客户问题属于中高风险类型（退款/发货延迟/质量瑕疵/投诉/12315/假货/二手）但客服基本妥善处理
   - low = 总分 90-100, 且客服专业妥善处理、客户无强烈不满
   规则：客户问题类型影响定级，但升级到 high/critical 必须有客服端的明确违规证据（推诿/敷衍/贬低/威胁/虚假承诺/索要隐私）。不得仅因客户提到"12315/退款/假货/投诉"等关键词就升为 high/critical——客户提关键词但客服处理得当时，应判 medium/low。
5. 严格输出纯 JSON 对象，首字符必须是 {，尾字符必须是 }。
6. 注意：与对话无关的规则不要引用，只引用确实触犯的规则。`;

    // 缓存 key 并入 eval_mode/agent/noCache，避免消融变体互相命中（原缺陷：key 只含 conversation）。
    // 传入完整对话，由 getCached/setCache 内部做全量 sha 哈希——不得截断（截断 200 字符会
    // 让仅后半段不同的会话串结果，见 W1 审计）。tenantId 为 undefined 时 getCached 以对话全量区分。
    const cacheKey = `qa:evaluate:${evalMode}:${wantAgent}:${noCache ? "nc" : "c"}:${conversation}`;
    const t0 = Date.now();

    let evaluation: Record<string, unknown> | null = null;

    if (useBaselineOverride) {
      // 配对消融：复用共享语义基线快照（不重新调用 runJudge，隔离工具效果）
      evaluation = baselineOverride;
      console.log(`[QA] ${correlationId} Using baseline_override (shared snapshot)`);
    } else {
      // Check LLM response cache first
      const cached = noCache ? null : getCached(cacheKey);
      if (cached) {
        evaluation = parseJsonContent(cached);
        console.log(`[QA] ${correlationId} Using cached baseline evaluation`);
      }

      if (!evaluation) {
        // few-shot 学习闭环（dual_rag_memory+ / agent）：注入历史人工纠错案例
        const fewShot = useFewShot ? await getFewShotExamples(conversation, { count: 3 }) : null;
        const fewShotPrompt = fewShot?.promptInsert
          ? `\n\n【历史纠错参考（人工复核过的相似案例，作为先例参考，避免重复误判）】\n${fewShot.promptInsert}`
          : "";

        const elapsed = Date.now() - t0;

        // 语义基线：始终单次判定（adjudicator），不做 agent 循环，保证稳定性
        const judgeResult = await runJudge({
          conversation,
          systemPrompt: systemPrompt + fewShotPrompt,
          tenantId: undefined,
          useAgent: false,
          useCache: !noCache,
        });

        const content = judgeResult.content;
        if (!content) {
          recordLLMCall({ endpoint: "/api/qa/evaluate", model: "auto", responseTimeMs: elapsed, tokensUsed: 0, success: false });
          return apiErr("LLM 调用失败，请稍后重试", "UPSTREAM_ERROR", 502);
        }

        // 日志脱敏：只记录长度与风险字段，不打印含 source_quote 的原文（客户对话内容不得进服务器日志）。
        console.log(`[QA] ${correlationId} LLM raw length=${content.length}`);

        recordLLMCall({ endpoint: "/api/qa/evaluate", model: "auto", responseTimeMs: elapsed, tokensUsed: Math.ceil(content.length / 3), success: true, cached: false });
        if (!noCache) setCache(cacheKey, content, Math.ceil(content.length / 3), "auto");

        evaluation = parseJsonContent(content);
        if (!evaluation) {
          return apiErr("LLM 返回格式异常，请缩短对话文本后重试", "UPSTREAM_ERROR", 502);
        }
      } else {
        recordLLMCall({ endpoint: "/api/qa/evaluate", model: "auto", responseTimeMs: 0, tokensUsed: 0, success: true, cached: true });
      }
    }

    // 三条路径（baseline_override / cache / judge）都保证 evaluation 非空
    if (!evaluation) {
      return apiErr("评估失败，请稍后重试", "INTERNAL_ERROR", 500);
    }

    // ── 落库字段提取 ────────────────────────────────────
    const violations: QualityViolation[] = Array.isArray(evaluation.violations)
      ? evaluation.violations.filter(isRecord).map((violation) => violation as QualityViolation)
      : [];
    const totalScore =
      typeof evaluation.total_score === "number"
        ? Math.max(0, Math.min(100, evaluation.total_score))
        : 100;
    const sentimentScore =
      typeof evaluation.sentiment_score === "number"
        ? Math.max(1, Math.min(5, evaluation.sentiment_score))
        : 1;
    const configuredRisk = evaluation.risk_level;
    const semanticBaseline: RiskLevel = ["low", "medium", "high", "critical"].includes(String(configuredRisk))
      ? configuredRisk as RiskLevel
      : totalScore < 60 || sentimentScore === 5
        ? "critical"
        : totalScore < 75
          ? "high"
          : totalScore < 90
            ? "medium"
            : "low";

    // ── baseline_only：只返回语义基线（配对消融快照），不做后续层 ──
    if (isBaselineOnly) {
      return apiOk({
        baseline_only: true,
        baseline_risk_level: semanticBaseline,
        risk_level: semanticBaseline,
        total_score: totalScore,
        sentiment_score: sentimentScore,
        intent: typeof evaluation.intent === "string" ? evaluation.intent : "",
        summary: typeof evaluation.summary === "string" ? evaluation.summary : "",
        violations: mapViolationsForResponse(violations),
      });
    }

    // ── 第 1 层：硬红线下限（确定性，不可降级） ──────────
    const hardScan = useHardFloor ? scanHardRedlines(conversation) : null;
    const hardFloor: RiskLevel = hardScan ? floorFromHighestRisk(hardScan.highest_risk) : "low";
    if (hardScan && hardScan.highest_risk > 0) {
      console.log(`[QA] ${correlationId} Hard redline floor=${hardFloor} (${hardScan.matches.map((m) => m.rule.id).join(",")})`);
    }

    // ── 第 3 层：软关键词信号（不升风险，只提示复核） ─────
    const soft = useSoftSignals ? classifySoftSignals(conversation) : { flags: [], requiresHumanReview: false };

    // ── 第 4 层：Agent 调查员（无 finalRisk 写权限） ──────
    let investigation: Awaited<ReturnType<typeof runInvestigation>> | null = null;
    let validatedEscalation: RiskLevel | undefined;
    if (wantAgent) {
      const baselineSummary = buildBaselineSummary(semanticBaseline, violations);
      const hardRedlineHit = Boolean(hardScan && hardScan.highest_risk > 0);
      // 服务端调查策略：按 finding 类型/软信号/硬红线推导必调工具
      const requiredTools = deriveRequiredTools({
        baselineViolations: violations,
        softSignals: soft.flags,
        hardRedlineHit,
      });
      const findingTypes: FindingType[] = violations
        .map((v) => {
          const explicit = (v as { finding_type?: string }).finding_type;
          return (explicit as FindingType | undefined) || classifyFindingType(v.category, v.rule);
        })
        .filter((x): x is FindingType => Boolean(x));
      const requiredQuery = requiredTools.length > 0
        ? deriveRetrievalQuery(findingTypes, conversation)
        : undefined;
      const requiredIntent = findingTypes.includes("product_accuracy") ? "product_qa" : "policy_qa";
      investigation = await runInvestigation({
        conversation,
        baselineSummary,
        tenantId: undefined,
        requiredTool: requiredTools[0],
        requiredQuery,
        requiredIntent,
      });
      validatedEscalation = validateAgentEscalation(investigation.parsed, conversation);
      console.log(
        `[QA] ${correlationId} investigation requiredTools=${requiredTools.join(",") || "none"} mode=${investigation.mode} turns=${investigation.turns} tools=${investigation.toolsUsed.join(",") || "none"} escalation=${validatedEscalation || "none"} parsed=${investigation.parsed ? "ok" : "null"}`
      );
    }

    // ── 第 5 层：确定性解析器（Agent 不得降级基线） ───────
    let riskLevel: QualityEvaluationInput["riskLevel"] = resolveFinalRisk({
      hardFloor,
      semanticBaseline,
      agentEscalation: validatedEscalation,
    });
    // 关键词陷阱一致性：客户诉求属中高风险类型且客服处理得当（low）时，不低于 medium；
    // 只升到 medium（非 severe），不产生严重误报（Sprint 3）。
    riskLevel = applyCustomerIssueMediumFloor(riskLevel, soft.flags.map((f) => f.code));

    // fail-closed：非 agent 路径无 knowledgeStatus 概念，视为 ok；
    // 但 agent 调查存在却 parse 失败（parsed=null，可能是 agent-fallback）时按 insufficient 触发人工复核。
    const knowledgeStatus: AgentEvidence["knowledgeStatus"] = investigation
      ? (investigation.parsed?.knowledgeStatus ?? "insufficient")
      : "ok";
    const requiresHumanReview = computeRequiresHumanReview({
      hardRedlineHit: Boolean(hardScan && hardScan.highest_risk > 0),
      riskLevel,
      softRequiresReview: soft.requiresHumanReview,
      agentRequiresReview: investigation?.parsed?.requiresHumanReview === true,
      agentEvidenceConflict: investigation?.parsed?.evidenceConflict === true,
      knowledgeStatus,
    });

    const alertViolations = violations.map((violation) => ({
      category: violation.category || "unknown",
      rule: violation.rule || "unknown",
      deduction: typeof violation.deduction === "number" ? violation.deduction : 0,
      source_quote: violation.source_quote || "",
    }));

    const { data: report, error: insertErr } = await supabaseAdmin
      .from("quality_reports")
      .insert({
        tenant_id: context?.tenantId || "default",
        ticket_id: ticketId,
        agent_id: agentProfile?.id || null,
        reviewer_id: reviewerId,
        conversation,
        intent: typeof evaluation.intent === "string" ? evaluation.intent : "",
        sentiment_score: sentimentScore,
        total_score: totalScore,
        violations,
        risk_level: riskLevel,
        status: "pending_review",
        correlation_id: correlationId,
        review_mode: reviewMode,
        ...(backdateCreatedAt ? { created_at: backdateCreatedAt } : {}),
      })
      .select("id")
      .single();

    if (insertErr) {
      console.error(`[QA] ${correlationId} Insert failed:`, insertErr.message);
      return apiErr("数据库写入失败", "INTERNAL_ERROR", 500);
    }

    console.log(
      `[QA] ${correlationId} Report ${report.id}: score=${totalScore} risk=${riskLevel} violations=${violations.length} mode=${reviewMode}`
    );

    const qualityLoop = await persistQualityEvaluation({
      reportId: report.id,
      tenantId: context?.tenantId || "default",
      teamId,
      ticketId,
      correlationId,
      conversationLength: conversation.length,
      intent: typeof evaluation.intent === "string" ? evaluation.intent : "",
      sentimentScore,
      totalScore,
      riskLevel,
      violations,
      summary: typeof evaluation.summary === "string" ? evaluation.summary : "",
      reviewMode,
      reviewerId,
      rulesExcerpt: retrievedRules,
    });

    // ── Auto-collect negative samples with quality filtering ────
    if ((riskLevel === "critical" || totalScore < 40) && supabaseAdmin) {
      try {
        // Only collect if violations are AI-relevant (service/professionalism/compliance), not external (logistics)
        const aiRelevantCategories = ["服务态度", "专业性", "响应效率", "合规与隐私"];
        const hasAiRelevantViolation = violations.some(
          (v: { category?: string }) => aiRelevantCategories.includes(v.category || "")
        );
        if (!hasAiRelevantViolation && violations.length > 0) {
          console.log(`[Self-Learn] Skipped low-score report ${ticketId}: violations not AI-relevant (${violations.map((v: { category?: string }) => v.category).join(", ")})`);
        } else {
          const contentHash = simpleHash(conversation);
          const { data: existingSample } = await supabaseAdmin
            .from("correction_samples")
            .select("id")
            .eq("conversation_hash", contentHash)
            .maybeSingle();

          if (!existingSample) {
            const grade = hasAiRelevantViolation ? "S" : "A"; // S=high value, A=moderate
            await supabaseAdmin.from("correction_samples").insert({
              session_id: ticketId,
              conversation: conversation.substring(0, 2000),
              conversation_hash: contentHash,
              ai_prediction: {
                type: "negative_sample",
                quality_score: totalScore,
                risk_level: riskLevel,
                grade: grade,
                violations: violations
                  .map((v: { rule?: string; category?: string }) => v.rule || v.category || "")
                  .join("; "),
                meta: { ticket_id: ticketId, auto_collected: true },
              },
              human_correction: { corrected_text: "" },
              correction_type: "other",
            });
            console.log(`[Self-Learn] Auto-collected ${grade}-grade negative sample from ${ticketId}`);
          }
        }
      } catch (err) {
        // Graceful degradation — table may not exist yet
        console.warn(
          `[Self-Learn] Failed to auto-collect (table may not exist):`,
          err instanceof Error ? err.message : err
        );
      }
    }

    // ── 飞书预警（Dify 模式 / skip_feishu / 影子模式 均静默）────────────────
    let alertResult = { method: "none", target: null as string | null };
    const needsAlert = (riskLevel === "critical" || riskLevel === "high") && reviewMode !== "shadow";

    if (needsAlert && !skipFeishu) {
      let reviewerOpenId: string | null = null;
      let reviewerWebhook: string | null = null;

      if (reviewerId) {
        const { data: reviewerProfile } = await supabaseAdmin
          .from("profiles")
          .select("feishu_open_id")
          .eq("id", reviewerId)
          .maybeSingle();
        reviewerOpenId = reviewerProfile?.feishu_open_id || null;
        reviewerWebhook = null;
      }

      alertResult = await dispatchAlert(
        {
          reportId: report.id,
          ticketId,
          agentName: agentProfile?.name || "未知客服",
          totalScore,
          riskLevel,
          sentimentScore,
          violations: alertViolations,
          correlationId,
        },
        reviewerOpenId,
        reviewerWebhook
      );

      if (alertResult.method !== "none") {
        console.log(
          `[QA] ${correlationId} Alert dispatched via ${alertResult.method} → ${alertResult.target}`
        );
      }

      // Push high-risk card to group chat with action button
      const violationSummary = violations.slice(0, 3).map((v) => `- [${v.rule || v.category || "unknown"}] ${v.source_quote || ""}`).join("\n");
      sendFeishuGroupCard({
        header: { title: { tag: "plain_text", content: riskLevel === "critical" ? "🔴 致命风险告警" : "🟠 高风险告警" }, template: riskLevel === "critical" ? "red" : "orange" },
        elements: [
          { tag: "div", text: { tag: "lark_md", content: `**会话ID：** ${ticketId}\n**客服：** ${agentProfile?.name || "未知"}\n**风险等级：** ${riskLevel}\n**违规项：**\n${violationSummary || "无"}` } },
          { tag: "hr" },
          { tag: "action", actions: [{
            tag: "button", text: { tag: "plain_text", content: "📋 一键转工单" }, type: "primary",
            value: JSON.stringify({ action: "create_work_order", session_id: ticketId, risk: riskLevel }),
          }]},
        ],
      }).catch(() => {});
    }

    // ── 自动工单生成（critical 且有违规项） ──────────────
    if (riskLevel === "critical" && violations.length > 0 && reviewMode !== "shadow") {
      const violationSummary = violations
        .slice(0, 3)
        .map((v) => `[${v.category || "unknown"}] ${v.rule || "unknown"}`)
        .join("；");
      const workOrderTitle = `[自动] 质检红灯工单 — ${agentProfile?.name || "未知客服"} — ${violationSummary.slice(0, 80)}`;
      const workOrderDesc = [
        `质检报告 #${report.id}`,
        `客服：${agentProfile?.name || "未知客服"}`,
        `评分：${totalScore}/100`,
        `风险：${riskLevel}`,
        `违规数：${violations.length}`,
        ``,
        `违规详情：`,
        ...violations.map((v, i: number) =>
          `${i + 1}. [${v.category || "unknown"}] ${v.rule || "unknown"} (扣${v.deduction || 0}分) — "${(v.source_quote || "").slice(0, 100)}"`
        ),
      ].join("\n");

      try {
        const woRes = await supabaseAdmin
          .from("work_orders")
          .insert({
            title: workOrderTitle,
            description: workOrderDesc,
            source: "qa_evaluate",
            source_id: report.id,
            priority: "critical",
            category: "system_issue",
            status: "open",
            metadata: {
              report_id: report.id,
              ticket_id: ticketId,
              agent_id: agentProfile?.id || null,
              total_score: totalScore,
            },
          })
          .select("id")
          .single();

        if (woRes.data) {
          await supabaseAdmin.from("work_order_actions").insert({
            work_order_id: woRes.data.id,
            action: "created",
            metadata: { auto_generated: true, source: "qa_evaluate", report_id: report.id },
          });
          console.log(`[QA] ${correlationId} Auto-created work order ${woRes.data.id}`);
        }
      } catch (woErr) {
        console.error(`[QA] ${correlationId} Failed to auto-create work order:`, woErr);
      }
    }

    const finalNote = needsAlert || riskLevel === "critical"
      ? composeFinalAnswer(`报告已生成，风险 ${riskLevel}，建议人工复核。`, { lowConfidence: true }, "zh", correlationId)
      : `报告已生成。[${correlationId}]`;

    return apiOk({
      report_id: report.id,
      evaluation_id: qualityLoop.evaluationId,
      finding_ids: qualityLoop.findingIds,
      work_item_ids: qualityLoop.workItemIds,
      ticket_id: ticketId,
      total_score: totalScore,
      risk_level: riskLevel,
      sentiment_score: sentimentScore,
      // 逐案明细：评测/审计需要按违规项做错误分析（sprint 2/3 基线对比）
      violations: mapViolationsForResponse(violations),
      violations_count: violations.length,
      latency_ms: Date.now() - t0,
      correlation_id: correlationId,
      review_mode: reviewMode,
      needs_alert: needsAlert,
      alert_method: isDifyMode ? "disabled" : alertResult.method,
      final_note: finalNote,
      // 5 层架构：语义基线恒为 adjudicator；agent 调查员只增强证据（use_agent 时才存在）
      agent_mode: wantAgent ? (investigation?.mode ?? "agent-fallback") : "single-shot",
      agent_turn_count: wantAgent ? (investigation?.turns ?? 0) : 0,
      agent_tools: wantAgent ? (investigation?.toolsUsed ?? []) : [],
      soft_signal_flags: soft.flags,
      requires_human_review: requiresHumanReview,
      knowledge_status: knowledgeStatus,
      hard_redline_matches: hardScan && hardScan.highest_risk > 0
        ? hardScan.matches.map((m) => ({ id: m.rule.id, rule: m.rule.rule_text, matched: m.matched_text }))
        : [],
      agent_evidence: investigation?.parsed
        ? {
            evidence_count: investigation.parsed.evidence?.length ?? 0,
            policy_findings_count: investigation.parsed.policyFindings?.length ?? 0,
            proposed_escalation: investigation.parsed.proposedEscalation ?? null,
            escalation_evidence: investigation.parsed.escalationEvidence ?? [],
            evidence_conflict: investigation.parsed.evidenceConflict === true,
            requires_human_review: investigation.parsed.requiresHumanReview === true,
          }
        : null,
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    console.error(`[QA] ${correlationId} Error:`, message);
    return apiErr(message, "INTERNAL_ERROR", 500);
  }
}

function simpleHash(str: string): string {
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    hash = ((hash << 5) - hash + str.charCodeAt(i)) | 0;
  }
  return Math.abs(hash).toString(16);
}

/** 把违规项映射为响应/配对快照可回喂的 JSON（含 finding_type，供调查策略与评测使用）。 */
function mapViolationsForResponse(violations: QualityViolation[]): Array<{
  category: string;
  rule: string;
  severity: string;
  deduction: number;
  source_quote: string;
  finding_type: string;
}> {
  return violations.map((v) => ({
    category: v.category || "unknown",
    rule: v.rule || "unknown",
    severity: v.severity || "unknown",
    deduction: typeof v.deduction === "number" ? v.deduction : 0,
    source_quote: v.source_quote || "",
    finding_type: String((v as Record<string, unknown>).finding_type || ""),
  }));
}

/** 构造注入调查员的不可修改基线摘要（第 4 层初始状态）。 */
function buildBaselineSummary(riskLevel: RiskLevel, violations: QualityViolation[]): string {
  const lines = violations
    .slice(0, 5)
    .map(
      (v, i) =>
        `  ${i + 1}. [${v.category || "unknown"}] ${v.rule || "unknown"} (severity=${v.severity || "unknown"}) — "${String(v.source_quote || "").slice(0, 80)}"`
    );
  return `risk_level=${riskLevel}\nviolations(${violations.length}):\n${lines.join("\n") || "  （无）"}`;
}
