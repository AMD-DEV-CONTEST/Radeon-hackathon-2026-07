/**
 * 完整 E2E 测试: 质检 + 驳回
 * 启动: node scripts/test-full-flow.mjs
 */

const SUPABASE_URL = process.env.NEXT_PUBLIC_SUPABASE_URL;
const SUPABASE_KEY = process.env.SUPABASE_SERVICE_ROLE_KEY || "";

const BASE = "http://localhost:3001/api/qa";

const CONVERSATION = `客服：您好，请问有什么可以帮您？
客户：我前天买的那个洗面奶，收到的包装是破的，里面的东西漏了一半，你们怎么发的货？
客服：你自己签收的时候不看一眼的吗？
客户：快递放丰巢柜的，我怎么看？现在我要求退款。
客服：退款需要你先垫付运费寄回来，我们收到货检查没问题才能退。
客户：你们发的问题货为什么要我垫运费？我不接受。
客服：这是公司规定，我也没办法。
客户：那把你的工号给我，我要投诉。
客服：行行行，给你登记了，等通知吧。`;

async function getTeamLeadId() {
  const res = await fetch(
    `${SUPABASE_URL}/rest/v1/profiles?role=eq.team_lead&select=id,name&limit=1`,
    { headers: { apikey: SUPABASE_KEY, Authorization: `Bearer ${SUPABASE_KEY}` } }
  );
  const data = await res.json();
  return Array.isArray(data) && data.length > 0 ? data[0] : null;
}

async function main() {
  console.log("=== QA System Full-Flow E2E Test ===\n");

  const lead = await getTeamLeadId();
  if (!lead) { console.log("FAIL: No team_lead found in profiles. Run schema.sql first."); return; }
  console.log(`Team lead: ${lead.name} (${lead.id})\n`);

  // ── Step 1: Evaluate ──────────────────────────────────
  console.log("1. POST /api/qa/evaluate");
  const start1 = Date.now();
  const evalRes = await fetch(`${BASE}/evaluate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ticket_id: "fullflow_001", conversation: CONVERSATION }),
  });
  const evalData = await evalRes.json();
  console.log(`   ${evalRes.status} (${Date.now() - start1}ms)`);
  console.log(`   Report: ${evalData.report_id}`);
  console.log(`   Score: ${evalData.total_score} | Risk: ${evalData.risk_level}`);
  console.log(`   Alert: ${evalData.needs_alert} (${evalData.alert_method})`);
  console.log(`   Trace: ${evalData.correlation_id}\n`);

  if (evalData.error) {
    console.log(`   FAIL: ${evalData.error}`);
    return;
  }

  const reportId = evalData.report_id;

  // ── Step 2: Overturn (human-in-the-loop) ──────────────
  console.log("2. POST /api/qa/overturn (simulate team_lead rejection)");
  const start2 = Date.now();
  const overturnRes = await fetch(`${BASE}/overturn`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      report_id: reportId,
      corrected_by: lead.id,
      reason: "客服并没有明显违规，退款需垫付运费是公司真实规定，AI 误判",
      corrected_judgment: {
        total_score: 85,
        risk_level: "medium",
        violations: [
          {
            category: "服务态度",
            rule: "禁止使用负面措辞、反问语气",
            deduction: 10,
            severity: "major",
            source_quote: "你自己签收的时候不看一眼的吗？",
          },
          {
            category: "服务态度",
            rule: "禁止敷衍话术",
            deduction: 5,
            severity: "minor",
            source_quote: "行行行，给你登记了，等通知吧。",
          },
        ],
      },
    }),
  });
  const overturnData = await overturnRes.json();
  console.log(`   ${overturnRes.status} (${Date.now() - start2}ms)`);
  console.log(`   Status: ${overturnData.status}`);
  console.log(`   Bad case saved: ${overturnData.bad_case_saved}\n`);

  // ── Step 3: Verify overturned report ──────────────────
  console.log("3. Verify (check Supabase directly via REST)");
  const verifyRes = await fetch(
    `${process.env.NEXT_PUBLIC_SUPABASE_URL}/rest/v1/quality_reports?id=eq.${reportId}&select=status,total_score,risk_level,violations`,
    {
      headers: {
        apikey: process.env.SUPABASE_SERVICE_ROLE_KEY || "",
        Authorization: `Bearer ${process.env.SUPABASE_SERVICE_ROLE_KEY || ""}`,
      },
    }
  );
  const verifyData = await verifyRes.json();
  if (Array.isArray(verifyData) && verifyData.length > 0) {
    const r = verifyData[0];
    console.log(`   Status: ${r.status}`);
    console.log(`   Score: ${r.total_score} (overturned from ${evalData.total_score})`);
    console.log(`   Risk: ${r.risk_level} (was ${evalData.risk_level})`);
  }

  // ── Step 4: Try re-overturning (should fail with 409) ──
  console.log("\n4. Re-overturn (expect 409 conflict)");
  const reOverturnRes = await fetch(`${BASE}/overturn`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      report_id: reportId,
      corrected_by: lead.id,
      reason: "再次驳回",
    }),
  });
  console.log(`   ${reOverturnRes.status} (expected 409)`);

  console.log("\n=== Full Flow Complete ===");
}

main().catch(console.error);
