import {
  runDiagnosis,
  detectReasonSignals,
  computeConfidence,
  buildFinding,
  detectTrafficQualityIssue,
  ENGINE_VERSION,
  type ConversationEvidence,
  type FunnelContext,
  type DiagnosisInput,
} from "../diagnosis/engine";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function makeConversation(overrides: Partial<ConversationEvidence> = {}): ConversationEvidence {
  return {
    conversation_id: "conv-001",
    campaign_id: "camp-001",
    product_id: "prod-001",
    messages: [],
    had_cart: false,
    had_order: false,
    had_payment: false,
    transferred_to_human: false,
    duration_seconds: 120,
    customer_sentiment: "neutral",
    ...overrides,
  };
}

const priceConversation = makeConversation({
  messages: [
    { role: "customer", content: "这个太贵了，有没有便宜点的？", timestamp: "2026-07-20T10:00:00Z" },
    { role: "agent", content: "我们目前有满减活动", timestamp: "2026-07-20T10:00:30Z" },
    { role: "customer", content: "还是超出预算了", timestamp: "2026-07-20T10:01:00Z" },
  ],
  customer_sentiment: "negative",
});

const fulfillmentConversation = makeConversation({
  conversation_id: "conv-002",
  messages: [
    { role: "customer", content: "这个什么时候发货？多久到？", timestamp: "2026-07-20T11:00:00Z" },
    { role: "agent", content: "一般3-5天", timestamp: "2026-07-20T11:00:20Z" },
    { role: "customer", content: "太慢了，我急需", timestamp: "2026-07-20T11:00:40Z" },
  ],
  transferred_to_human: true,
});

const noSignalConversation = makeConversation({
  conversation_id: "conv-003",
  messages: [
    { role: "customer", content: "你好", timestamp: "2026-07-20T12:00:00Z" },
    { role: "agent", content: "您好，有什么可以帮您？", timestamp: "2026-07-20T12:00:10Z" },
  ],
  duration_seconds: 30,
});

const cartNoOrderConversation = makeConversation({
  conversation_id: "conv-004",
  messages: [
    { role: "customer", content: "太贵了，先加购看看有没有优惠", timestamp: "2026-07-20T13:00:00Z" },
  ],
  had_cart: true,
  had_order: false,
});

// ---------------------------------------------------------------------------
// detectReasonSignals
// ---------------------------------------------------------------------------

describe("detectReasonSignals", () => {
  it("detects price objection keywords", () => {
    const signals = detectReasonSignals(priceConversation);
    expect(signals.length).toBeGreaterThanOrEqual(1);
    const priceSignal = signals.find((s) => s.category === "price_objection");
    expect(priceSignal).toBeDefined();
    expect(priceSignal!.matched_keywords).toContain("太贵");
    expect(priceSignal!.matched_keywords).toContain("预算");
  });

  it("detects inventory/fulfillment keywords", () => {
    const signals = detectReasonSignals(fulfillmentConversation);
    const fulfillmentSignal = signals.find((s) => s.category === "inventory_fulfillment");
    expect(fulfillmentSignal).toBeDefined();
    expect(fulfillmentSignal!.matched_keywords).toContain("发货");
    expect(fulfillmentSignal!.matched_keywords).toContain("多久到");
  });

  it("returns empty for conversations without category signals", () => {
    const signals = detectReasonSignals(noSignalConversation);
    expect(signals).toHaveLength(0);
  });

  it("ignores agent messages for signal detection", () => {
    const conv = makeConversation({
      messages: [
        { role: "agent", content: "这个太贵了我理解", timestamp: "2026-07-20T10:00:00Z" },
        { role: "customer", content: "好的谢谢", timestamp: "2026-07-20T10:01:00Z" },
      ],
    });
    const signals = detectReasonSignals(conv);
    expect(signals.find((s) => s.category === "price_objection")).toBeUndefined();
  });
});

// ---------------------------------------------------------------------------
// computeConfidence
// ---------------------------------------------------------------------------

describe("computeConfidence", () => {
  it("caps confidence at 0.75 without order evidence", () => {
    const signals = detectReasonSignals(priceConversation);
    const { score } = computeConfidence(signals, priceConversation, "price_objection");
    expect(score).toBeLessThanOrEqual(0.75);
  });

  it("gives higher confidence with multiple keywords + negative sentiment", () => {
    const signals = detectReasonSignals(priceConversation);
    const { level, score } = computeConfidence(signals, priceConversation, "price_objection");
    expect(score).toBeGreaterThanOrEqual(0.4);
    expect(["medium", "high"]).toContain(level);
  });

  it("gives low/insufficient confidence for weak signals", () => {
    const conv = makeConversation({
      messages: [{ role: "customer", content: "有点贵", timestamp: "2026-07-20T10:00:00Z" }],
      customer_sentiment: "neutral",
    });
    const signals = detectReasonSignals(conv);
    const { level } = computeConfidence(signals, conv, "price_objection");
    expect(["low", "insufficient", "medium"]).toContain(level);
  });

  it("boosts confidence when cart exists but no order", () => {
    const signals = detectReasonSignals(cartNoOrderConversation);
    const { score } = computeConfidence(signals, cartNoOrderConversation, "price_objection");
    // Should get a boost from had_cart && !had_order
    expect(score).toBeGreaterThan(0.3);
  });
});

// ---------------------------------------------------------------------------
// buildFinding
// ---------------------------------------------------------------------------

describe("buildFinding", () => {
  it("produces layered output: fact, inference, confidence, suggestion", () => {
    const signals = detectReasonSignals(priceConversation);
    const finding = buildFinding("price_objection", signals, priceConversation);

    expect(finding.reason_category).toBe("price_objection");
    expect(finding.fact_statement).toContain("太贵");
    expect(finding.fact_statement).toContain("未产生订单");
    expect(finding.inference_statement).toContain("价格异议");
    expect(finding.confidence).toBeDefined();
    expect(finding.confidence_score).toBeGreaterThan(0);
    expect(finding.suggestion).toBeTruthy();
    expect(finding.suggestion_actionable).toBe(true);
    expect(finding.evidence_refs.length).toBeGreaterThanOrEqual(1);
    expect(finding.evidence_refs[0].type).toBe("conversation");
  });

  it("includes counter-evidence when sentiment is positive", () => {
    const conv = makeConversation({
      messages: [{ role: "customer", content: "太贵了但你们态度很好", timestamp: "2026-07-20T10:00:00Z" }],
      customer_sentiment: "positive",
    });
    const signals = detectReasonSignals(conv);
    const finding = buildFinding("price_objection", signals, conv);
    expect(finding.counter_evidence).toContain("正面");
  });
});

// ---------------------------------------------------------------------------
// detectTrafficQualityIssue
// ---------------------------------------------------------------------------

describe("detectTrafficQualityIssue", () => {
  it("detects traffic quality issue when conversion is very low", () => {
    const funnel: FunnelContext = {
      traffic_count: 1000,
      conversation_count: 50, // 5% — very low
      cart_count: 10,
      order_count: 3,
      payment_count: 2,
    };
    const conversations = Array.from({ length: 10 }, (_, i) =>
      makeConversation({ conversation_id: `conv-t${i}`, duration_seconds: 20, had_cart: false }),
    );
    const finding = detectTrafficQualityIssue(funnel, conversations);
    expect(finding).not.toBeNull();
    expect(finding!.reason_category).toBe("traffic_quality");
    expect(finding!.confidence_score).toBeLessThanOrEqual(0.75);
  });

  it("returns null when conversion rate is acceptable", () => {
    const funnel: FunnelContext = {
      traffic_count: 100,
      conversation_count: 20, // 20% — fine
      cart_count: 8,
      order_count: 4,
      payment_count: 3,
    };
    const finding = detectTrafficQualityIssue(funnel, []);
    expect(finding).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// runDiagnosis (integration of all parts)
// ---------------------------------------------------------------------------

describe("runDiagnosis", () => {
  const input: DiagnosisInput = {
    tenant_id: "default",
    conversation_ids: ["conv-001", "conv-002", "conv-003"],
  };

  it("produces findings for conversations with signals", () => {
    const result = runDiagnosis(input, [priceConversation, fulfillmentConversation, noSignalConversation]);

    expect(result.engine_version).toBe(ENGINE_VERSION);
    expect(result.findings.length).toBeGreaterThanOrEqual(2);

    const categories = result.findings.map((f) => f.reason_category);
    expect(categories).toContain("price_objection");
    expect(categories).toContain("inventory_fulfillment");
  });

  it("marks unknown for conversations without signals that have no order", () => {
    const result = runDiagnosis(input, [noSignalConversation]);
    expect(result.findings).toHaveLength(1);
    expect(result.findings[0].reason_category).toBe("unknown");
    expect(result.findings[0].confidence).toBe("insufficient");
  });

  it("does NOT claim ROI without order evidence", () => {
    const result = runDiagnosis(input, [priceConversation, fulfillmentConversation]);
    expect(result.summary.roi_claimable).toBe(false);
    expect(result.summary.roi_disclaimer).toContain("不能宣称真实 ROI");
  });

  it("sets roi_disclaimer to null when order evidence exists", () => {
    const convWithOrder = makeConversation({
      conversation_id: "conv-order",
      messages: [{ role: "customer", content: "太贵了", timestamp: "2026-07-20T10:00:00Z" }],
      had_order: true,
      had_payment: true,
    });
    const result = runDiagnosis(
      { ...input, conversation_ids: ["conv-order"] },
      [convWithOrder],
    );
    expect(result.summary.has_order_evidence).toBe(true);
    expect(result.summary.roi_disclaimer).toBeNull();
  });

  it("includes traffic quality finding when funnel shows low conversion", () => {
    const funnel: FunnelContext = {
      traffic_count: 1000,
      conversation_count: 30,
      cart_count: 5,
      order_count: 1,
      payment_count: 1,
    };
    const shortConvs = Array.from({ length: 8 }, (_, i) =>
      makeConversation({ conversation_id: `conv-s${i}`, duration_seconds: 15, had_cart: false }),
    );
    const result = runDiagnosis(
      { ...input, conversation_ids: shortConvs.map((c) => c.conversation_id) },
      shortConvs,
      funnel,
    );
    const trafficFinding = result.findings.find((f) => f.reason_category === "traffic_quality");
    expect(trafficFinding).toBeDefined();
  });

  it("summary top_reasons are sorted by count", () => {
    const conv1 = makeConversation({
      conversation_id: "c1",
      messages: [{ role: "customer", content: "太贵了，预算不够", timestamp: "T" }],
    });
    const conv2 = makeConversation({
      conversation_id: "c2",
      messages: [{ role: "customer", content: "价格高，有没有折扣", timestamp: "T" }],
    });
    const conv3 = makeConversation({
      conversation_id: "c3",
      messages: [{ role: "customer", content: "什么时候发货", timestamp: "T" }],
    });
    const result = runDiagnosis(
      { ...input, conversation_ids: ["c1", "c2", "c3"] },
      [conv1, conv2, conv3],
    );
    expect(result.summary.top_reasons[0].category).toBe("price_objection");
    expect(result.summary.top_reasons[0].count).toBe(2);
  });
});
