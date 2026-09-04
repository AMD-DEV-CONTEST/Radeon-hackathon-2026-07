import type { OutcomeCandidate, SessionStore } from "airecap-plus";
import type { PrivacyRisk } from "./privacy.js";

export interface EvidenceReport {
  title: string;
  generated_at: string;
  session_id: string;
  model?: string;
  summary: {
    verified: number;
    evidenced: number;
    claimed: number;
    contradicted: number;
    abandoned: number;
  };
  outcomes: Array<{
    title: string;
    type: string;
    status: string;
    confidence: number;
    code_evidence: string[];
    test_evidence: string[];
    decision_notes: string[];
    summary_blob?: string;
  }>;
  privacy_risks: PrivacyRisk[];
  narrative?: string;
  notes: string[];
}

function linksByRelation(o: OutcomeCandidate, relation: string): string[] {
  return o.evidence_links
    .filter((l) => l.relation === relation || (relation === "supports" && l.relation === "defines"))
    .map((l) => `${l.relation}:${l.event_id} (${l.method})`);
}

function scopePaths(o: OutcomeCandidate): string[] {
  return o.scope?.paths ?? [];
}

function testAnchors(o: OutcomeCandidate): string[] {
  const fromAnchors = (o.verification_anchors ?? []).map((a) => `${a.kind}:${a.key}`);
  const fromScope = (o.scope?.commands ?? []).map((c) => `cmd:${c}`);
  return [...new Set([...fromAnchors, ...fromScope])];
}

export function buildStructuredReport(opts: {
  store: SessionStore;
  privacyRisks?: PrivacyRisk[];
  model?: string;
  narrative?: string;
  title?: string;
}): EvidenceReport {
  const { store } = opts;
  const active = store.outcomes.filter((o) => o.status !== "superseded");
  const summary = {
    verified: active.filter((o) => o.status === "verified").length,
    evidenced: active.filter((o) => o.status === "evidenced").length,
    claimed: active.filter((o) => o.status === "claimed").length,
    contradicted: active.filter((o) => o.status === "contradicted").length,
    abandoned: active.filter((o) => o.status === "abandoned").length,
  };

  const outcomes = active
    .slice()
    .sort((a, b) => statusRank(a.status) - statusRank(b.status) || b.confidence - a.confidence)
    .map((o) => ({
      title: o.title,
      type: o.type,
      status: o.status,
      confidence: o.confidence,
      code_evidence: scopePaths(o),
      test_evidence: testAnchors(o),
      decision_notes: linksByRelation(o, "defines").slice(0, 5),
      summary_blob: o.summary_blob,
    }));

  const notes: string[] = [];
  if (summary.verified === 0) {
    notes.push("当前没有 verified 成果：仅 claimed/evidenced 不能写成“已完成”。");
  }
  if (summary.claimed > 0) {
    notes.push(`存在 ${summary.claimed} 条仅声称、证据不足的 outcome。`);
  }
  if ((opts.privacyRisks?.length ?? 0) > 0) {
    notes.push("导出前需确认脱敏：检测到公开风险项。");
  }

  return {
    title: opts.title ?? `开发证据报告 · ${store.session_id}`,
    generated_at: new Date().toISOString(),
    session_id: store.session_id,
    model: opts.model,
    summary,
    outcomes,
    privacy_risks: opts.privacyRisks ?? [],
    narrative: opts.narrative,
    notes,
  };
}

function statusRank(s: string): number {
  switch (s) {
    case "verified":
      return 0;
    case "evidenced":
      return 1;
    case "claimed":
      return 2;
    case "contradicted":
      return 3;
    case "abandoned":
      return 4;
    default:
      return 9;
  }
}

/** One-line product stance shown at the top of every report. */
export const GATE_BANNER =
  "门禁：LDEA 拒绝未验证的完成叙事 — 仅 status=verified 可写「已完成/已修复」；LLM 不得自证 verified；空口 claim → abandoned。";

/** Deterministic markdown — no LLM required. */
export function renderReportMarkdown(report: EvidenceReport): string {
  const lines: string[] = [];
  lines.push(`# ${report.title}`);
  lines.push("");
  lines.push(`> ${GATE_BANNER}`);
  lines.push("");
  lines.push(`- 会话：\`${report.session_id}\``);
  lines.push(`- 生成时间：${report.generated_at}`);
  if (report.model) lines.push(`- 本地模型：\`${report.model}\``);
  lines.push(
    `- 状态计数：verified ${report.summary.verified} · evidenced ${report.summary.evidenced} · claimed ${report.summary.claimed} · contradicted ${report.summary.contradicted} · abandoned ${report.summary.abandoned}`,
  );
  lines.push("");

  const done = report.outcomes.filter((o) => o.status === "verified");
  const partial = report.outcomes.filter((o) => o.status === "evidenced");
  const weak = report.outcomes.filter((o) => !["verified", "evidenced"].includes(o.status));

  lines.push("## 成果");
  lines.push("（本栏只含 verified；claimed / evidenced / abandoned 见「未闭合」）");
  if (done.length === 0) {
    lines.push("（无 verified 成果）");
  } else {
    for (const o of done) {
      lines.push(`- **${o.title}** \`${o.type}\` · confidence ${o.confidence.toFixed(2)}`);
    }
  }
  lines.push("");

  lines.push("## 代码证据");
  const codeItems = [...done, ...partial].flatMap((o) =>
    o.code_evidence.map((p) => `- \`${p}\` ← ${o.title} [${o.status}]`),
  );
  lines.push(...(codeItems.length ? codeItems : ["- （无）"]));
  lines.push("");

  lines.push("## 验证证据");
  const testItems = [...done, ...partial].flatMap((o) =>
    o.test_evidence.map((t) => `- ${t} ← ${o.title} [${o.status}]`),
  );
  lines.push(...(testItems.length ? testItems : ["- （无）"]));
  lines.push("");

  lines.push("## 决策依据");
  const decisions = report.outcomes.flatMap((o) =>
    o.decision_notes.map((d) => `- ${d} ← ${o.title}`),
  );
  if (report.narrative) {
    lines.push(report.narrative.trim());
  } else if (decisions.length) {
    lines.push(...decisions);
  } else {
    lines.push("- （无独立决策记录；见各 outcome 证据链）");
  }
  lines.push("");

  lines.push("## 公开风险");
  if (!report.privacy_risks.length) {
    lines.push("- 未检测到常见密钥/邮箱模式");
  } else {
    for (const r of report.privacy_risks) {
      const sample = r.samples.slice(0, 2).join(", ");
      const paths = r.paths?.length ? ` @ ${r.paths.slice(0, 3).join(", ")}` : "";
      lines.push(`- **${r.kind}** × ${r.count}${paths}${sample ? ` · 例：${sample}` : ""}`);
    }
  }
  lines.push("");

  if (partial.length || weak.length) {
    lines.push("## 未闭合 / 不可公开为完成");
    for (const o of [...partial, ...weak]) {
      lines.push(
        `- **${o.title}** · \`${o.status}\`${o.summary_blob ? ` · ${o.summary_blob}` : ""}`,
      );
    }
    lines.push("");
  }

  if (report.notes.length) {
    lines.push("## 备注");
    for (const n of report.notes) lines.push(`- ${n}`);
    lines.push("");
  }

  lines.push("---");
  lines.push(
    "规则：仅 `verified` 可表述为已完成；`claimed` 无证据不能当作成果；LLM 不得直接把状态写成 verified。",
  );
  return lines.join("\n");
}
