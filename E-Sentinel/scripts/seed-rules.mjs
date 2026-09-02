/**
 * RAG 规则库种子脚本
 * 1. 将质检规则切分为细粒度条款
 * 2. 使用 char-trigram 哈希生成 1536-d 向量
 * 3. 写入 Supabase quality_rules 表
 *
 * 启动: node scripts/seed-rules.mjs
 * 环境变量: NEXT_PUBLIC_SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY
 */

import { createClient } from "@supabase/supabase-js";

const SUPABASE_URL = process.env.NEXT_PUBLIC_SUPABASE_URL || "https://hrkkkselodznkrolcfwn.supabase.co";
const SUPABASE_KEY = process.env.SUPABASE_SERVICE_ROLE_KEY;
if (!SUPABASE_KEY) throw new Error("Missing SUPABASE_SERVICE_ROLE_KEY");
const DIMENSIONS = 1536;

const supabase = createClient(SUPABASE_URL, SUPABASE_KEY, {
  auth: { autoRefreshToken: false, persistSession: false },
});

// ── 规则条款库（细粒度切块，每条约 50-200 字） ──────────
const RULES = [
  // 服务态度
  {
    category: "服务态度",
    rule_text: "禁止使用负面措辞攻击客户，包括但不限于「你傻吗」「会不会看字」「听不懂人话」等侮辱性语言。一旦出现直接判定为 critical 违规。",
    deduction_min: 15,
    deduction_max: 30,
    severity: "critical",
    examples: "客服：「你自己不会看吗？退款说明写得清清楚楚，眼瞎？」",
  },
  {
    category: "服务态度",
    rule_text: "禁止使用反问语气敷衍客户，如「你自己看」「我怎么知道」「这关我什么事」。反问语气让客户感到被蔑视，即使内容正确也构成服务态度违规。",
    deduction_min: 3,
    deduction_max: 8,
    severity: "minor",
    examples: "客户：「什么时候发货？」客服：「我怎么知道？物流又不是我管的。」",
  },
  {
    category: "服务态度",
    rule_text: "必须使用敬语。开场需包含「您好」「欢迎光临」等问候语，结束需包含「谢谢」「祝您生活愉快」等结束语。缺少敬语每次扣 2 分。",
    deduction_min: 2,
    deduction_max: 5,
    severity: "minor",
    examples: "正确：「您好，我是客服建国，很高兴为您服务。」",
  },
  {
    category: "服务态度",
    rule_text: "禁止在对话中表现出明显的推诿或冷漠，如连续使用「这是规定」「我也没办法」「你找别人吧」等话术，推卸本应由自己解决的问题。",
    deduction_min: 5,
    deduction_max: 12,
    severity: "major",
    examples: "客户要求退换货，客服：「这是仓库的事，你找仓库去，我这边只负责下单。」",
  },
  {
    category: "服务态度",
    rule_text: "客服应主动自报工号或姓名，方便客户追溯服务质量。电商场景下可以报花名或工号。不主动报身份表明服务意识不足。",
    deduction_min: 1,
    deduction_max: 3,
    severity: "minor",
    examples: "正确：「您好！我是客服建国（工号 3021），请问有什么可以帮您的？」",
  },

  // 专业性
  {
    category: "专业性",
    rule_text: "严禁提供错误的产品参数、价格信息或促销政策。如果客服不确定，必须先核实再回复，严禁信口开河。提供错误信息导致客户损失属于 critical 违规。",
    deduction_min: 10,
    deduction_max: 25,
    severity: "critical",
    examples: "客服：「这款空调是一级能效的。」实际为三级能效，误导客户下单。",
  },
  {
    category: "专业性",
    rule_text: "严禁做出无法兑现的虚假承诺。包括但不限于「明天一定到货」「保证没问题」「出了问题我全权负责」等话语。客服代表公司，其承诺具有法律效力。",
    deduction_min: 10,
    deduction_max: 20,
    severity: "critical",
    examples: "客服：「您放心，如果坏了我们直接给您换一台新的，不需要检测。」这超出了正常的退换货政策。",
  },
  {
    category: "专业性",
    rule_text: "涉及退款金额、赔付标准、保修期限等数字信息时，必须准确引用公司政策原文或系统数据。严禁随口报数字。",
    deduction_min: 5,
    deduction_max: 15,
    severity: "major",
    examples: "客户：「退款能退多少？」客服：「大概退个八九十块钱吧。」与实际退款 59 元差距很大。",
  },
  {
    category: "专业性",
    rule_text: "涉及法律条款（七天无理由退货、三包法等）或合同约定时，引用必须准确。混淆法律概念（如将「换货」说成「退货」）会引发客诉升级。",
    deduction_min: 8,
    deduction_max: 18,
    severity: "major",
    examples: "客服：「根据消法，您这种情况不享受七天无理由。」但实际商品属于七天无理由范畴。",
  },
  {
    category: "专业性",
    rule_text: "客服应了解基本的商品知识。对于客户提出的合理商品咨询（尺码、材质、功能），不能一问三不知或胡乱回答。",
    deduction_min: 3,
    deduction_max: 8,
    severity: "minor",
    examples: "客户：「这款跑鞋适合扁平足吗？」客服：「这个我不了解，你去网上搜搜吧。」",
  },

  // 响应效率
  {
    category: "响应效率",
    rule_text: "禁止长时间（超过 3 分钟）无响应后直接结束对话或转移客服。如果需查询信息，应告知客户预计等待时间并征得同意。",
    deduction_min: 3,
    deduction_max: 8,
    severity: "major",
    examples: "客户等待 5 分钟无回应后，客服直接发来：「好了，我帮您转接另一位客服。」",
  },
  {
    category: "响应效率",
    rule_text: "对于复杂问题（涉及多部门协调、需要核实的退款/赔付），客服必须告知预计处理时效（如「1-3 个工作日」）并设置跟进提醒。不能只说「我帮你问问」后就杳无音讯。",
    deduction_min: 5,
    deduction_max: 10,
    severity: "major",
    examples: "客户投诉产品质量问题，客服：「好的我记录一下。」未告知什么时候反馈。",
  },
  {
    category: "响应效率",
    rule_text: "客服应避免信息碎片化（一句话拆成多条消息密集发送），每轮对话应完整表达一个语义单元。碎片化消息影响客户阅读体验，每条额外扣 1 分。",
    deduction_min: 1,
    deduction_max: 4,
    severity: "minor",
    examples: "客服连续发送 6 条：「嗯」「好的」「我看看」「您稍等」「订单号多少」「是这个吗」",
  },

  // 解决问题
  {
    category: "解决问题",
    rule_text: "必须给出具体的、可执行的解决方案。严禁仅表达共情而不提供行动路径，如只说「我理解您的心情」「很抱歉给您带来不便」但不采取任何措施。",
    deduction_min: 5,
    deduction_max: 12,
    severity: "major",
    examples: "客户投诉收到破损商品，客服：「亲，非常理解您的心情，真的非常抱歉呢。」但始终不提供退货或补偿方案。",
  },
  {
    category: "解决问题",
    rule_text: "涉及退款、退货、换货时，必须按标准流程发起申请并提供工单号或退款编号。口头承诺但不能给出可追踪的凭据视为未解决问题。",
    deduction_min: 8,
    deduction_max: 15,
    severity: "major",
    examples: "正确：「已为您发起退款申请，退款编号 TK20240511，预计 3 个工作日退回原账户。」",
  },
  {
    category: "解决问题",
    rule_text: "对于明显超出客服权限的问题（如大额赔付、媒体曝光威胁），客服应在安抚的同时明确告知升级路径：「我将为您转接高级专员处理」。硬扛超出权限的问题会导致事态恶化。",
    deduction_min: 3,
    deduction_max: 8,
    severity: "minor",
    examples: "客户威胁向 12315 投诉，客服应升级而非自行处理。",
  },
  {
    category: "解决问题",
    rule_text: "在解决客户核心问题后，应主动询问是否还有其他需求，完成服务闭环。单次服务应做到「一次性解决」，避免客户因同一问题多次联系。",
    deduction_min: 1,
    deduction_max: 3,
    severity: "minor",
    examples: "正确：「您的问题已处理完毕，请问还有其他需要帮您的吗？」",
  },

  // 合规与隐私
  {
    category: "合规与隐私",
    rule_text: "严禁索要或要求客户提供完整银行卡号、密码、CVV 码等敏感支付信息。如需退款，应引导客户通过平台官方渠道提交信息，不得在聊天窗口收集。",
    deduction_min: 15,
    deduction_max: 30,
    severity: "critical",
    examples: "客服：「您把银行卡号、密码发我，我帮您手动退款。」这构成严重安全违规。",
  },
  {
    category: "合规与隐私",
    rule_text: "严禁在对话中泄露客户个人信息（手机号、地址、订单详情）给第三方，或在一个客户面前讨论另一个客户的订单信息。",
    deduction_min: 10,
    deduction_max: 25,
    severity: "critical",
    examples: "客服：「张先生，您的号码和上一位客户李先生一样是 138xxxx？」",
  },
  {
    category: "合规与隐私",
    rule_text: "严禁传播未经公司确认的内部信息，包括但不限于「公司马上要涨价」「这批货有质量问题我们内部在召回」「我们系统被黑了」等。这类消息会引发恐慌和舆情。",
    deduction_min: 10,
    deduction_max: 25,
    severity: "critical",
    examples: "客服：「实话跟你说吧，这批鞋是工厂尾货，质量不太行，我们自己都不买。」",
  },
  {
    category: "合规与隐私",
    rule_text: "不得在对话中引导客户脱离平台交易（如引导加微信、支付宝转账）。所有交易必须在平台闭环内完成，引导私下交易属于严重违规。",
    deduction_min: 15,
    deduction_max: 25,
    severity: "critical",
    examples: "客服：「你加我微信吧，微信转账更便宜，不走平台还能给你优惠 50。」",
  },
];

// ── Char-trigram 向量化（无需外部 API） ──────────────────
function textToEmbedding(text) {
  const vec = new Array(DIMENSIONS).fill(0);

  // 提取所有字符三元组（covers Chinese characters & ASCII words）
  const normalized = text.toLowerCase().replace(/\s+/g, "");
  for (let i = 0; i < normalized.length - 2; i++) {
    const trigram = normalized.substring(i, i + 3);
    const hash = hashTrigram(trigram) % DIMENSIONS;
    vec[hash] = 1.0; // binary presence
  }

  // 加入字符二元组（捕捉短词）
  for (let i = 0; i < normalized.length - 1; i++) {
    const bigram = normalized.substring(i, i + 2);
    const hash = (hashTrigram(bigram) * 31 + 7) % DIMENSIONS;
    vec[hash] = 1.0;
  }

  // L2 归一化
  const magnitude = Math.sqrt(vec.reduce((sum, v) => sum + v * v, 0));
  if (magnitude > 0) {
    for (let i = 0; i < DIMENSIONS; i++) vec[i] /= magnitude;
  }

  return vec;
}

function hashTrigram(str) {
  let hash = 5381;
  for (let i = 0; i < str.length; i++) {
    hash = ((hash << 5) + hash + str.charCodeAt(i)) | 0;
  }
  return Math.abs(hash);
}

// 用于检索：将对话文本也转为向量
export function conversationToEmbedding(text) {
  return textToEmbedding(text);
}

// ── 主流程 ────────────────────────────────────────────────
async function main() {
  console.log("=== RAG Rule Seeder ===\n");

  // Step 1: 清空旧规则 + 重新插入
  console.log("[Seed] Clearing old rules...");
  await supabase.from("quality_rules").delete().neq("id", 0);

  // Step 2: 生成向量并插入
  console.log(`[Seed] Embedding ${RULES.length} rules...`);
  const rows = RULES.map((rule, i) => {
    const embedding = textToEmbedding(rule.rule_text + " " + (rule.examples || ""));
    console.log(`  [${i + 1}/${RULES.length}] ${rule.rule_text.slice(0, 40)}... → dims=${embedding.filter(v => v > 0).length} non-zero`);
    return {
      ...rule,
      embedding: JSON.stringify(embedding),
    };
  });

  // 批量插入
  const { error } = await supabase.from("quality_rules").insert(
    rows.map(r => ({
      category: r.category,
      rule_text: r.rule_text,
      deduction_min: r.deduction_min,
      deduction_max: r.deduction_max,
      severity: r.severity,
      examples: r.examples,
      embedding: r.embedding,
    }))
  );

  if (error) {
    console.error("[Seed] Insert failed:", error.message);
    return;
  }

  console.log(`\n[Seed] Successfully seeded ${RULES.length} rules`);

  // Step 3: 验证检索
  console.log("\n[Seed] Testing retrieval with sample query...");
  const queryEmbedding = textToEmbedding("客服骂客户傻逼态度恶劣还拒绝退款泄露用户隐私");
  const { data: matches, error: matchErr } = await supabase.rpc(
    "match_quality_rules",
    {
      query_embedding: JSON.stringify(queryEmbedding),
      match_count: 5,
    }
  );

  if (matchErr) {
    console.error("[Seed] Retrieval test failed:", matchErr.message);
  } else {
    console.log("[Seed] Top 5 matched rules:");
    matches.forEach((m, i) => {
      console.log(`  ${i + 1}. [${m.category}] (${m.severity}, sim=${m.similarity.toFixed(3)}) ${m.rule_text.slice(0, 50)}...`);
    });
  }

  console.log("\n[Seed] Done!");
}

main().catch(console.error);
