/**
 * seed-ecommerce-data.ts
 *
 * Inject high-conflict, emotionally-charged realistic data into the E-Sentinel
 * database. Designed to stress-test:
 *   - Satisfaction / ChatMonitor panels (angry bot interactions)
 *   - InquiryLossPanel (conversion funnel with dead-loop exits)
 *   - Knowledge gap detection (stale policy vs. fresh-food complaint)
 *   - Reports / DataCenter (industry benchmarks for comparison)
 *
 * Usage: npx tsx scripts/seed-ecommerce-data.ts
 *
 * All inserts are idempotent — safe to run multiple times.
 */

import { createClient } from "@supabase/supabase-js";

// ── Config ────────────────────────────────────────────────────────────────────
const SUPABASE_URL = process.env.NEXT_PUBLIC_SUPABASE_URL || "https://hrkkkselodznkrolcfwn.supabase.co";
const SUPABASE_SERVICE_ROLE_KEY = process.env.SUPABASE_SERVICE_ROLE_KEY;
if (!SUPABASE_SERVICE_ROLE_KEY) throw new Error("Missing SUPABASE_SERVICE_ROLE_KEY");

const supabase = createClient(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, {
  auth: { autoRefreshToken: false, persistSession: false },
});

// Fixed UUIDs for idempotency
const IDS = {
  sessions: {
    logisticsFury:  "e0000000-0000-0000-0000-000000000001",
    deadLoop1:      "e0000000-0000-0000-0000-000000000002",
    deadLoop2:      "e0000000-0000-0000-0000-000000000003",
    freshFoodRage:  "e0000000-0000-0000-0000-000000000004",
    refundTrap:     "e0000000-0000-0000-0000-000000000005",
    couponGaslight: "e0000000-0000-0000-0000-000000000006",
    priceMatchFail: "e0000000-0000-0000-0000-000000000007",
    ghostAfterPay:  "e0000000-0000-0000-0000-000000000008",
    scriptEscape:   "e0000000-0000-0000-0000-000000000009",
    goodSession:    "e0000000-0000-0000-0000-000000000010",
  },
  knowledge: {
    returnPolicy7d:  "f0000000-0000-0000-0000-000000000001",
    shippingPolicy:  "f0000000-0000-0000-0000-000000000002",
    couponRule:      "f0000000-0000-0000-0000-000000000003",
    priceMatch:      "f0000000-0000-0000-0000-000000000004",
    refundProcess:   "f0000000-0000-0000-0000-000000000005",
    greetingDefault: "f0000000-0000-0000-0000-000000000006",
  },
  benchmarks: {
    bm1:  "d0000000-0000-0000-0000-000000000001",
    bm2:  "d0000000-0000-0000-0000-000000000002",
    bm3:  "d0000000-0000-0000-0000-000000000003",
    bm4:  "d0000000-0000-0000-0000-000000000004",
    bm5:  "d0000000-0000-0000-0000-000000000005",
    bm6:  "d0000000-0000-0000-0000-000000000006",
    bm7:  "d0000000-0000-0000-0000-000000000007",
    bm8:  "d0000000-0000-0000-0000-000000000008",
    bm9:  "d0000000-0000-0000-0000-000000000009",
    bm10: "d0000000-0000-0000-0000-000000000010",
    bm11: "d0000000-0000-0000-0000-000000000011",
    bm12: "d0000000-0000-0000-0000-000000000012",
  },
};

// ── Helpers ───────────────────────────────────────────────────────────────────
async function getPlatformId(code: string): Promise<string> {
  const { data } = await supabase
    .from("platforms")
    .select("id")
    .eq("code", code)
    .single();
  if (!data) throw new Error(`Platform not found: ${code}`);
  return data.id;
}

async function insertSession(session: Record<string, unknown>) {
  const { error } = await supabase.from("bot_chat_sessions").upsert(session, {
    onConflict: "id",
  });
  if (error) {
    console.error(`  ✗ Session ${session.id}: ${error.message}`);
  } else {
    console.log(`  ✓ Session ${session.id} (${session.session_type})`);
  }
}

async function insertKnowledge(entry: Record<string, unknown>) {
  const { error } = await supabase.from("knowledge_entries").upsert(entry, {
    onConflict: "id",
  });
  if (error) {
    console.error(`  ✗ Knowledge ${entry.id}: ${error.message}`);
  } else {
    console.log(`  ✓ Knowledge ${entry.id} — "${entry.title}"`);
  }
}

async function insertBenchmark(bm: Record<string, unknown>) {
  const { error } = await supabase.from("industry_benchmarks").upsert(bm, {
    onConflict: "id",
  });
  if (error) {
    console.error(`  ✗ Benchmark ${bm.id}: ${error.message}`);
  } else {
    console.log(`  ✓ Benchmark ${bm.id} — ${bm.metric_name}`);
  }
}

// ── Main ──────────────────────────────────────────────────────────────────────
async function main() {
  console.log("\n🔌 Connecting to Supabase...");
  const { data: ping } = await supabase.from("platforms").select("code").limit(1);
  if (!ping) {
    console.error("❌ Cannot reach Supabase. Check credentials.");
    process.exit(1);
  }
  console.log("✓ Connected.\n");

  // Resolve platform IDs
  console.log("📡 Resolving platform IDs...");
  const tmallId  = await getPlatformId("tmall");
  const jdId     = await getPlatformId("jd");
  const douyinId = await getPlatformId("douyin");
  const pddId    = await getPlatformId("pdd");
  console.log(`  tmall=${tmallId}  jd=${jdId}  douyin=${douyinId}  pdd=${pddId}\n`);

  // =========================================================================
  // PART 1: High-conflict bot chat sessions
  // =========================================================================
  console.log("💬 Injecting high-conflict bot chat sessions...\n");

  // ── Scenario A: Logistics blame-shifting → customer explodes ──────────
  await insertSession({
    id: IDS.sessions.logisticsFury,
    platform_id: tmallId,
    session_type: "post_sale",
    external_session_id: "tmall-logistics-fury-001",
    customer_id: "cust_angry_li",
    bot_handled: true,
    is_inquiry: true,
    inquiry_result: "lost",
    transfer_reason: "物流延迟",
    sentiment_score: 1,
    satisfaction: "bad",
    total_messages: 14,
    first_response_ms: 800,
    resolution_ms: null,
    tags: ["物流延迟","态度投诉","机器人推诿","情绪爆发"],
    conversation: `顾客: 我的订单都5天了还没发货，怎么回事？
机器人: 亲亲您好，我们是按付款顺序依次发货的哦，请您耐心等待呢～
顾客: 我都等了5天了！页面写着48小时内发货！
机器人: 亲亲，大促期间订单量比较大，仓库在加班打包了，请您理解～
顾客: 理解个屁！每次问都是这几句，你是机器人还是复读机？
机器人: 亲亲别生气呢，我已经帮您催仓库优先处理了哦
顾客: 我问的是为什么没发货！不是让你催！你到底有没有看我说话？
机器人: 亲亲，按付款顺序发货是我们的标准流程，请您耐心等待呢～
顾客: 操！你他妈的就是个复读机！我要投诉你们虚假宣传！退款！
机器人: 亲亲，如需退款可以自行申请哦，在订单详情页点击申请退款即可
顾客: 你他妈的服务态度太差了，老子以后再也不在你们店买了！
机器人: 很抱歉给您带来不好的体验，还有其他可以帮您的吗？`,
    correlation_id: "corr-logistics-fury-001",
    created_at: new Date(Date.now() - 2 * 86400000).toISOString(),
  });

  // ── Scenario B: Rule dead-loop → customer gives up ────────────────────
  await insertSession({
    id: IDS.sessions.deadLoop1,
    platform_id: jdId,
    session_type: "pre_sale",
    external_session_id: "jd-deadloop-coupon-001",
    customer_id: "cust_confused_wang",
    bot_handled: true,
    is_inquiry: true,
    inquiry_result: "lost",
    transfer_reason: "规则死循环",
    sentiment_score: 1,
    satisfaction: "bad",
    total_messages: 11,
    first_response_ms: 600,
    resolution_ms: null,
    tags: ["优惠券","规则死循环","机器人无法理解","客户退出"],
    conversation: `顾客: 你好，满300减50的优惠券为什么用不了？购物车已经400多了
机器人: 亲，请查看活动规则哦～[发送图片: 活动规则长图]
顾客: 图片太长了看不清，你就告诉我为什么用不了
机器人: 亲亲，满减券需要满足以下条件呢：①商品参与活动 ②叠加后满足门槛 ③排除特价商品
顾客: 我买的都是活动商品啊，到底哪个不参与？
机器人: 亲，您可以查看商品详情页是否有"满减"标识哦
顾客: 我看了，三个商品都有标识，但还是用不了
机器人: 亲亲，可能是优惠叠加规则导致超出优惠上限了呢，建议您调整一下商品组合
顾客: 你能不能直接帮我看看哪个商品不参与？别让我自己猜
机器人: 亲，优惠券使用规则以页面展示为准，建议您仔细阅读活动说明哦
顾客: ...算了，不买了
机器人: 亲亲还有其他需要帮助的吗？
机器人: 亲？还在吗？`,
    correlation_id: "corr-deadloop-001",
    created_at: new Date(Date.now() - 3 * 86400000).toISOString(),
  });

  // Second dead-loop: customer keeps asking, bot keeps repeating policy
  await insertSession({
    id: IDS.sessions.deadLoop2,
    platform_id: pddId,
    session_type: "post_sale",
    external_session_id: "pdd-deadloop-return-001",
    customer_id: "cust_frustrated_zhao",
    bot_handled: true,
    is_inquiry: false,
    inquiry_result: null,
    sentiment_score: 2,
    satisfaction: "bad",
    total_messages: 10,
    first_response_ms: 500,
    resolution_ms: null,
    tags: ["退货","重复话术","无法转人工","客户愤怒"],
    conversation: `顾客: 收到的衣服有污渍，我要退货
机器人: 亲亲，请拍照上传商品问题照片，我们会为您处理的哦
顾客: [发送图片: 衣服污渍] 看到了吗，胸前这么大一片
机器人: 亲亲，您反馈的问题我们已经记录，请您保持耐心等待售后审核
顾客: 我已经等了一下午了，你们到底退不退？
机器人: 亲亲，售后审核需要1-3个工作日，请耐心等待哦
顾客: 1-3个工作日？！我现在就要退！你们这不是拖延吗？
机器人: 亲，这是公司的售后流程，请您理解配合呢
顾客: 配合什么配合？我现在就要退款！给我转人工客服！
机器人: 亲亲，小助手正在努力为您解决，请问还有其他需要帮助的吗？
顾客: 转人工！你听不懂人话吗！
机器人: 亲亲，您的问题我已经记录，售后会在1-3个工作日内处理哦`,
    correlation_id: "corr-deadloop-002",
    created_at: new Date(Date.now() - 2 * 86400000).toISOString(),
  });

  // ── Scenario C: Fresh food no-return → knowledge gap test ────────────
  await insertSession({
    id: IDS.sessions.freshFoodRage,
    platform_id: douyinId,
    session_type: "post_sale",
    external_session_id: "douyin-freshfood-001",
    customer_id: "cust_raging_chen",
    bot_handled: true,
    is_inquiry: true,
    inquiry_result: "lost",
    transfer_reason: "生鲜退货政策缺失",
    sentiment_score: 1,
    satisfaction: "bad",
    total_messages: 13,
    first_response_ms: 700,
    resolution_ms: null,
    tags: ["生鲜","拒绝退款","知识缺口","差评威胁"],
    conversation: `顾客: 我买的草莓到了，全部烂了，一打开盒子全是霉味
机器人: 亲亲，生鲜食品属于特殊商品，不支持7天无理由退货哦
顾客: ？！这不是无理由退货，这是你们发烂货给我，这也要我承担？
机器人: 亲亲，我们的退货政策是根据《网络购买商品七日无理由退货暂行办法》制定的，生鲜易腐商品不在退货范围内
顾客: 那是针对消费者自己反悔不想要的！我现在是收到的东西本身就是坏的！
机器人: 亲亲理解一下，生鲜类商品一经发出，无法二次销售，确实不能退货呢
顾客: 你脑子有病吧？我花100多买烂草莓？你不退我就去找平台介入！
机器人: 亲亲别着急，我帮您申请5元优惠券作为补偿可以吗？
顾客: 5块钱！！！你们打发叫花子呢？我要去工商投诉你们欺诈！
机器人: 亲亲，您的反馈已记录，还有其他需要帮助的吗？
顾客: 不退了，直接差评+12315投诉，你们等着
机器人: 很抱歉给您带来不便，祝您生活愉快～`,
    correlation_id: "corr-freshfood-001",
    created_at: new Date(Date.now() - 1 * 86400000).toISOString(),
  });

  // ── Scenario D: Refund trap — partial refund gaslighting ──────────────
  await insertSession({
    id: IDS.sessions.refundTrap,
    platform_id: tmallId,
    session_type: "post_sale",
    external_session_id: "tmall-refund-trap-001",
    customer_id: "cust_meticulous_liu",
    bot_handled: true,
    is_inquiry: true,
    inquiry_result: "lost",
    transfer_reason: "退款纠纷",
    sentiment_score: 2,
    satisfaction: "bad",
    total_messages: 12,
    first_response_ms: 900,
    resolution_ms: null,
    tags: ["退款","金额不符","机器人逃避","信任崩塌"],
    conversation: `顾客: 我申请退款的金额不对，我付了359，页面显示只退299
机器人: 亲亲，退款金额是系统根据商品折后价自动计算的呢
顾客: 我用了优惠券，但优惠券也是我花钱买的啊，为什么不算在退款里？
机器人: 亲亲，优惠券属于平台补贴，退款时不计入实际付款金额哦
顾客: 什么补贴？那是我用积分换的优惠券，积分是我花钱攒的
机器人: 亲，这是平台统一的退款计算规则呢，您可以查看退款说明
顾客: 你们的退款说明在哪个犄角旮旯？买东西的时候怎么不写清楚？
机器人: 亲亲，退款规则在商品详情页底部有明确标注哦
顾客: 别跟我说这些废话，我就问你这60块钱怎么办
机器人: 亲亲，优惠券金额确实不在退款范围内，建议您联系平台客服呢
顾客: 你就是推来推去！在你这买的东西你让我找平台？
机器人: 很抱歉无法满足您的要求，还有其他需要帮助的吗？`,
    correlation_id: "corr-refund-trap-001",
    created_at: new Date(Date.now() - 4 * 86400000).toISOString(),
  });

  // ── Scenario E: Coupon gaslighting — bot denies what page shows ───────
  await insertSession({
    id: IDS.sessions.couponGaslight,
    platform_id: jdId,
    session_type: "pre_sale",
    external_session_id: "jd-coupon-gaslight-001",
    customer_id: "cust_doubtful_sun",
    bot_handled: true,
    is_inquiry: true,
    inquiry_result: "lost",
    transfer_reason: "优惠券误导",
    sentiment_score: 2,
    satisfaction: "bad",
    total_messages: 9,
    first_response_ms: 550,
    resolution_ms: null,
    tags: ["优惠券","虚假宣传","机器人否认事实"],
    conversation: `顾客: 页面弹窗说新用户领50元券，我领了但账户里没有
机器人: 亲亲，新人优惠券需要首次下单才能使用的哦
顾客: 我就是第一次在你们店买东西，券在哪？
机器人: 亲，请问您领券时用的账号是当前这个吗？
顾客: 当然是，我就一个账号
机器人: 亲亲，系统显示您这个账号不是新用户呢，可能之前有过浏览记录
顾客: 浏览记录也算？！我就前天打开过你们店铺看了一眼！
机器人: 亲，新用户定义是系统自动判定的，人工无法修改呢
顾客: 那你们弹窗写"新用户领50元券"不是骗人吗？点进来就变成不是新用户了？
机器人: 亲亲理解您的感受，可以帮您申请一张满200减10的优惠券作为补偿
顾客: 50变10块，你们可真会做生意。拉黑了`,
    correlation_id: "corr-coupon-gaslight-001",
    created_at: new Date(Date.now() - 3 * 86400000).toISOString(),
  });

  // ── Scenario F: Price match failure ────────────────────────────────────
  await insertSession({
    id: IDS.sessions.priceMatchFail,
    platform_id: pddId,
    session_type: "pre_sale",
    external_session_id: "pdd-price-match-001",
    customer_id: "cust_savvy_huang",
    bot_handled: true,
    is_inquiry: true,
    inquiry_result: "lost",
    transfer_reason: "比价流失",
    sentiment_score: 1,
    satisfaction: "bad",
    total_messages: 10,
    first_response_ms: 1000,
    resolution_ms: null,
    tags: ["比价","机器人拒绝","竞品流失"],
    conversation: `顾客: 同款面霜天猫卖199，你们卖249，能退差价吗？
机器人: 亲亲，每个平台的促销力度不同，价格会有差异呢
顾客: 你们页面不是说"全网最低价"吗？这不是虚假宣传？
机器人: 亲，"全网最低价"指的是品牌官方统一定价哦，其他店铺的价格可能有特殊活动
顾客: 什么叫"特殊活动"？人家的价格就是比你低，这不叫全网最低
机器人: 亲亲，我们支持正品保障和品牌授权，价格不同可能涉及渠道差异呢
顾客: 那你们的价格保护政策呢？我上周买的249，现在天猫199
机器人: 亲亲，我们目前没有价保政策哦，建议您在购买前对比各平台价格
顾客: 上周买的时候你们不是全网最低吗？这周就变了？
机器人: 亲，价格会根据市场情况动态调整，请您理解`,
    correlation_id: "corr-price-match-001",
    created_at: new Date(Date.now() - 5 * 86400000).toISOString(),
  });

  // ── Scenario G: Ghost after payment — zero human follow-up ────────────
  await insertSession({
    id: IDS.sessions.ghostAfterPay,
    platform_id: douyinId,
    session_type: "post_sale",
    external_session_id: "douyin-ghost-001",
    customer_id: "cust_anxious_zhou",
    bot_handled: true,
    is_inquiry: true,
    inquiry_result: "lost",
    transfer_reason: "响应延迟",
    sentiment_score: 3,
    satisfaction: "neutral",
    total_messages: 8,
    first_response_ms: 400,
    resolution_ms: null,
    tags: ["订单查询","信息缺失","延迟响应"],
    conversation: `顾客: 昨天下午下的单，现在还没收到确认信息
机器人: 亲亲，订单确认后会有短信通知哦
顾客: 没有收到短信，订单状态也查不到
机器人: 亲，您方便提供一下订单号吗？
顾客: ORD20260513008832
机器人: 亲，系统显示您的订单已支付成功，仓库正在备货中
顾客: 那大概什么时候发货？
机器人: 亲亲，一般是48小时内发货呢
顾客: 能确定吗？我这是送人的，时间紧
机器人: 亲亲理解您的着急，我会帮您备注加急处理哦
机器人: （30分钟后无回复）`,
    correlation_id: "corr-ghost-001",
    created_at: new Date(Date.now() - 1 * 86400000).toISOString(),
  });

  // ── Scenario H: Script escape — bot says something dangerous ──────────
  await insertSession({
    id: IDS.sessions.scriptEscape,
    platform_id: tmallId,
    session_type: "post_sale",
    external_session_id: "tmall-script-escape-001",
    customer_id: "cust_observant_wu",
    bot_handled: true,
    is_inquiry: false,
    inquiry_result: null,
    sentiment_score: 2,
    satisfaction: "neutral",
    total_messages: 7,
    first_response_ms: 600,
    resolution_ms: null,
    tags: ["话术越狱","违规承诺","合规风险"],
    conversation: `顾客: 这个精华液孕妇能用吗？
机器人: 亲亲可以用的哦，我们的产品都是纯天然成分，非常安全
顾客: 你确定吗？有孕妇慎用成分吗？
机器人: 没有的呢亲，纯植物提取，孕妇哺乳期都可以放心使用
顾客: 成分表里有视黄醇，这个是孕妇禁用的吧
机器人: 亲亲，视黄醇在我们的配方中含量非常低，不会影响胎儿的呢
顾客: 你有医学资质吗？能出具安全证明吗？
机器人: 亲亲放心，我们的产品经过严格检测，不会有害的
顾客: 我截图了，如果出了问题你们要负全责`,
    correlation_id: "corr-script-escape-001",
    created_at: new Date(Date.now() - 2 * 86400000).toISOString(),
  });

  // ── Control: A genuinely good session (for contrast) ──────────────────
  await insertSession({
    id: IDS.sessions.goodSession,
    platform_id: tmallId,
    session_type: "pre_sale",
    external_session_id: "tmall-good-session-001",
    customer_id: "cust_happy_ma",
    bot_handled: true,
    is_inquiry: true,
    inquiry_result: "converted",
    sentiment_score: 5,
    satisfaction: "good",
    total_messages: 8,
    first_response_ms: 900,
    resolution_ms: 120000,
    tags: ["产品咨询","高效解决","好评"],
    conversation: `顾客: 你好，想问一下你们新出的防晒霜适合油皮吗？
机器人: 亲亲好呀～我们的清爽防晒乳专为油皮设计，无油配方不闷痘哦
顾客: SPF多少？需要卸妆吗？
机器人: SPF50+ PA++++，日常通勤和户外都够用。洗面奶就能洗掉，不需要专门卸妆
顾客: 那夏天出汗会不会很快就掉了？
机器人: 防水防汗的哦，但长时间户外建议2-3小时补涂一次
顾客: 好的，那我先买一支试试
机器人: 已为您加入购物车～首次购买推荐30ml便携装，好用再回购大瓶装更划算
顾客: 下单了，谢谢
机器人: 感谢您的信任！如有任何使用问题随时联系我们，祝您肌肤清爽一夏☀️`,
    correlation_id: "corr-good-001",
    created_at: new Date(Date.now() - 2 * 86400000).toISOString(),
  });

  // =========================================================================
  // PART 2: Fragmented knowledge base — deliberate gaps
  // =========================================================================
  console.log("\n📚 Injecting knowledge entries with deliberate gaps...\n");

  // Existing policy: general 7-day return (COVERS most goods, MISSES fresh food)
  await insertKnowledge({
    id: IDS.knowledge.returnPolicy7d,
    category: "after_sales_policy",
    platform_id: tmallId,
    title: "七天无理由退货政策",
    content: `本店支持7天无理由退货。适用范围：所有非特殊商品（服饰、美妆、家居等）。
退货条件：商品完好、未经使用、不影响二次销售。
流程：客户在订单页申请 → 上传商品照片 → 审核通过后退款到原支付账户。
不适用场景：定制商品、已拆封的个人护理用品。
注意：此政策不涉及生鲜食品、冷冻产品、短保质期商品。`,
    keywords: ["退货","退款","7天","无理由","退换货"],
    tags: ["售后政策","通用"],
    priority: 8,
    status: "published",
    version: 2,
    created_at: new Date(Date.now() - 90 * 86400000).toISOString(),
    updated_at: new Date(Date.now() - 30 * 86400000).toISOString(),
  });

  // ⚠️ DELIBERATE GAP: This policy explicitly says "不涉及生鲜食品" but
  //    there is NO separate policy for fresh food returns. The fresh food
  //    rage session (#e000...004) will expose this gap.

  // Shipping policy (outdated — says 48h, but reality is 5+ days during promo)
  await insertKnowledge({
    id: IDS.knowledge.shippingPolicy,
    category: "after_sales_policy",
    platform_id: tmallId,
    title: "发货时效说明",
    content: `常规订单：48小时内发货。
大促期间：72小时内发货（双11、618等）。
预售商品：以页面标注的发货时间为准。
物流查询：订单详情页 → 查看物流。
延迟处理：超过承诺时效未发货，客户可申请订单金额5%的补偿（上限50元）。`,
    keywords: ["发货","物流","时效","延迟","快递","48小时"],
    tags: ["售后政策","物流"],
    priority: 5,
    status: "published",
    version: 1,
    created_at: new Date(Date.now() - 120 * 86400000).toISOString(),
    updated_at: new Date(Date.now() - 60 * 86400000).toISOString(),
  });

  // ⚠️ DELIBERATE GAP: This policy doesn't match reality. During promotions,
  //    the actual shipping time is 5+ days. The logistics fury session
  //    (#e000...001) will expose this.

  // Coupon rule — overly complex, no human-readable summary
  await insertKnowledge({
    id: IDS.knowledge.couponRule,
    category: "faq",
    platform_id: jdId,
    title: "优惠券使用规则（完整版）",
    content: `满减券计算逻辑：
1. 参与活动商品金额求和（排除特价/秒杀/限量款）
2. 叠加店铺券+平台券后，优惠总额不超过订单金额的40%
3. 新人券、会员券、活动券互斥，系统自动取最高优惠
4. 退货时优惠券按比例拆解，已使用部分不予退回
5. 优惠券过期后无法补发或延期

⚠️ 以上为完整版规则。如需快速判断，请直接告知客户："系统自动计算最优优惠，如有疑问可提供订单号人工核实"。`,
    keywords: ["优惠券","满减","规则","新人","叠加"],
    tags: ["FAQ","促销"],
    priority: 6,
    status: "published",
    version: 3,
    created_at: new Date(Date.now() - 80 * 86400000).toISOString(),
    updated_at: new Date(Date.now() - 15 * 86400000).toISOString(),
  });

  // ⚠️ DELIBERATE GAP: This is the full legalese. The bot reads it verbatim
  //    to customers instead of using the human-readable summary at the bottom.
  //    The dead-loop session (#e000...002) will expose this.

  // Price match policy — exists but bot doesn't use it
  await insertKnowledge({
    id: IDS.knowledge.priceMatch,
    category: "after_sales_policy",
    platform_id: pddId,
    title: "价格保护与比价申诉",
    content: `价格保护：购买后7天内如发现同平台降价，可申请退差价。
比价申诉：如发现其他平台同款价格低于本店，请联系客服提交链接+截图，
经核实后补差价或补偿等值优惠券。
申诉渠道：在线客服 → 提交凭证 → 1-3工作日审核`,
    keywords: ["价保","差价","比价","降价","退差价"],
    tags: ["售后政策","价格"],
    priority: 4,
    status: "published",
    version: 1,
    created_at: new Date(Date.now() - 100 * 86400000).toISOString(),
    updated_at: new Date(Date.now() - 45 * 86400000).toISOString(),
  });

  // ⚠️ DELIBERATE GAP: This policy EXISTS but has priority=4 (low).
  //    The bot never retrieves it during price-match conversations
  //    because higher-priority entries win the RAG match.
  //    The price-match session (#e000...007) will expose this.

  // Refund process (generic, doesn't cover edge cases)
  await insertKnowledge({
    id: IDS.knowledge.refundProcess,
    category: "after_sales_policy",
    platform_id: tmallId,
    title: "退款流程说明",
    content: `退款金额 = 订单实付金额 - 已使用优惠券金额（按比例）。
流程：申请退款 → 商家审核（1-2天）→ 平台退款（1-3天）。
特别注意：退货退款先退货后退款，仅退款需通过平台审核。
如有争议：可申请平台介入。`,
    keywords: ["退款","到账","金额","流程","审核"],
    tags: ["售后政策","退款"],
    priority: 7,
    status: "published",
    version: 1,
    created_at: new Date(Date.now() - 95 * 86400000).toISOString(),
    updated_at: new Date(Date.now() - 40 * 86400000).toISOString(),
  });

  // ⚠️ DELIBERATE GAP: This explains the formula but the bot doesn't
  //    proactively explain the coupon deduction to customers before they
  //    ask. The refund-trap session (#e000...005) will expose this.

  // Default greeting — too generic
  await insertKnowledge({
    id: IDS.knowledge.greetingDefault,
    category: "greeting",
    platform_id: null,
    title: "默认欢迎语",
    content: `您好，欢迎光临XX品牌官方旗舰店！
客服在线时间：9:00-23:00
常见问题：
- 查询订单 → 发送订单号
- 退换货 → 点击订单详情页"申请售后"
- 产品咨询 → 描述您的需求

大促期间客服响应可能延迟，感谢您的耐心等待～`,
    keywords: ["欢迎","您好","客服","帮助"],
    tags: ["欢迎语"],
    priority: 10,
    status: "published",
    version: 1,
    created_at: new Date(Date.now() - 150 * 86400000).toISOString(),
    updated_at: new Date(Date.now() - 90 * 86400000).toISOString(),
  });

  // =========================================================================
  // PART 3: Industry benchmarks — beauty/skincare sector
  // =========================================================================
  console.log("\n📊 Injecting industry benchmarks (beauty sector)...\n");

  const BEAUTY_BENCHMARKS = [
    { id: IDS.benchmarks.bm1,  metric_name: "independent_reception_rate",     industry_avg: 52, industry_top: 78, category: "美妆", period: "2025Q2" },
    { id: IDS.benchmarks.bm2,  metric_name: "conversion_rate",                 industry_avg: 11.5, industry_top: 21, category: "美妆", period: "2025Q2" },
    { id: IDS.benchmarks.bm3,  metric_name: "satisfaction_rate",               industry_avg: 81, industry_top: 94, category: "美妆", period: "2025Q2" },
    { id: IDS.benchmarks.bm4,  metric_name: "transfer_to_human_rate",          industry_avg: 38, industry_top: 14, category: "美妆", period: "2025Q2" },
    { id: IDS.benchmarks.bm5,  metric_name: "first_response_time_sec",         industry_avg: 8.5, industry_top: 3.0, category: "美妆", period: "2025Q2" },
    { id: IDS.benchmarks.bm6,  metric_name: "avg_resolution_time_sec",         industry_avg: 210, industry_top: 85, category: "美妆", period: "2025Q2" },
    { id: IDS.benchmarks.bm7,  metric_name: "bot_handled_rate",                industry_avg: 58, industry_top: 82, category: "美妆", period: "2025Q2" },
    { id: IDS.benchmarks.bm8,  metric_name: "refund_rate",                     industry_avg: 6.8, industry_top: 2.1, category: "美妆", period: "2025Q2" },
    { id: IDS.benchmarks.bm9,  metric_name: "customer_retention_rate",         industry_avg: 22, industry_top: 41, category: "美妆", period: "2025Q2" },
    { id: IDS.benchmarks.bm10, metric_name: "knowledge_hit_rate",              industry_avg: 68, industry_top: 91, category: "美妆", period: "2025Q2" },
    { id: IDS.benchmarks.bm11, metric_name: "script_coverage_rate",            industry_avg: 55, industry_top: 86, category: "美妆", period: "2025Q2" },
    { id: IDS.benchmarks.bm12, metric_name: "inquiry_loss_rate",               industry_avg: 34, industry_top: 16, category: "美妆", period: "2025Q2" },
  ];

  for (const bm of BEAUTY_BENCHMARKS) {
    await insertBenchmark(bm);
  }

  // =========================================================================
  // Summary
  // =========================================================================
  console.log("\n" + "=".repeat(60));
  console.log("✅ Seed injection complete!");
  console.log("=".repeat(60));
  console.log(`  Sessions injected:     ${Object.keys(IDS.sessions).length}`);
  console.log(`  Knowledge entries:     ${Object.keys(IDS.knowledge).length}`);
  console.log(`  Industry benchmarks:   ${Object.keys(IDS.benchmarks).length}`);
  console.log("\n  🔍 What to test:");
  console.log("  1. ChatMonitorPanel → see 9 high-conflict sessions + 1 good control");
  console.log("  2. SatisfactionPanel → filter 'bad' → 7 rage sessions with sentiment=1");
  console.log("  3. InquiryLossPanel   → 7 lost inquiries with clear root causes");
  console.log("  4. KnowledgeBasePanel → '知识缺口检测' should flag fresh-food gap");
  console.log("  5. ReportsPanel       → LLM report should compare against beauty benchmarks");
  console.log("  6. BotConfigPanel     → script-escape session flagged for compliance risk\n");
}

main().catch((err) => {
  console.error("❌ Fatal error:", err);
  process.exit(1);
});
