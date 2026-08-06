import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { PrivatePlateDomain } from "./service/privateplate-domain.js";

describe("approved guidance retrieval", () => {
  let domain: PrivatePlateDomain;

  beforeEach(async () => {
    domain = await PrivatePlateDomain.create(":memory:");
    domain.db.exec(`DELETE FROM knowledge_cards`);
  });

  afterEach(() => {
    domain.close();
  });

  it("filters applicability, exclusions and risk before ranking", () => {
    insertCard(domain, {
      id: "safe-applicable",
      appliesTo: ["compose"],
      exclusions: [],
      riskLevel: "low",
      reviewStatus: "approved",
      sourceYear: 2024
    });
    insertCard(domain, {
      id: "wrong-scope",
      appliesTo: ["task_card"],
      exclusions: [],
      riskLevel: "low",
      reviewStatus: "approved",
      sourceYear: 2024
    });
    insertCard(domain, {
      id: "excluded-member",
      appliesTo: ["compose"],
      exclusions: ["egg_allergy"],
      riskLevel: "low",
      reviewStatus: "approved",
      sourceYear: 2024
    });
    insertCard(domain, {
      id: "excluded-compose-scope",
      appliesTo: ["compose"],
      exclusions: ["compose"],
      riskLevel: "low",
      reviewStatus: "approved",
      sourceYear: 2024
    });
    insertCard(domain, {
      id: "high-risk",
      appliesTo: ["compose"],
      exclusions: [],
      riskLevel: "high",
      reviewStatus: "approved",
      sourceYear: 2024
    });
    insertCard(domain, {
      id: "not-approved",
      appliesTo: ["compose"],
      exclusions: [],
      riskLevel: "low",
      reviewStatus: "draft",
      sourceYear: 2024
    });

    const packet = domain.retrieveApprovedGuidance({
      query: "专属检索词",
      memberTags: ["egg_allergy"],
      planTags: ["planning"],
      topK: 3
    });

    expect(packet.cards).toEqual([
      {
        sourceId: "safe-applicable",
        title: "safe-applicable",
        year: 2024,
        relevantContent: "专属检索词",
        matchedTags: []
      }
    ]);

    const handoffPacket = domain.retrieveApprovedGuidance({
      query: "专属检索词",
      memberTags: [],
      planTags: ["handoff"],
      topK: 3
    });
    expect(handoffPacket.cards.map((card) => card.sourceId)).toEqual([
      "wrong-scope"
    ]);
  });

  it("hits seeded cards from Chinese natural queries without requiring memberTags", async () => {
    // Re-seed default fixture cards (beforeEach wiped the table).
    domain.close();
    domain = await PrivatePlateDomain.create(":memory:");

    const cases = [
      {
        query: "解释这份初次规划为什么优先使用快坏的豆腐。",
        planTags: ["planning"],
        expect: "kc-priority-tofu"
      },
      {
        query: "说明妈妈在初次规划中的少盐约束。",
        planTags: ["planning"],
        expect: "kc-demo-guardrails"
      },
      {
        query: "爸爸控糖在规划里怎么处理的？",
        planTags: ["planning"],
        expect: "kc-demo-guardrails"
      },
      {
        query: "为什么拒绝项会在重规划中保留？",
        planTags: ["replan"],
        expect: "kc-reject-persists"
      },
      {
        query: "为什么任务交接卡要保护隐私？",
        planTags: ["privacy", "handoff"],
        expect: "kc-min-disclosure"
      },
      {
        query: "交接卡为什么不能写病历？",
        planTags: ["privacy", "handoff"],
        expect: "kc-min-disclosure"
      }
    ];

    for (const item of cases) {
      const packet = domain.retrieveApprovedGuidance({
        query: item.query,
        memberTags: [],
        planTags: item.planTags,
        topK: 3
      });
      const ids = packet.cards.map((card) => card.sourceId);
      expect(ids, item.query).toContain(item.expect);
    }

    const naturalAnswer = domain.retrieveApprovedGuidance({
      query: "为什么爸爸的任务卡写米饭小份？",
      memberTags: [],
      planTags: ["privacy"],
      topK: 1
    });
    expect(naturalAnswer.cards.map((card) => card.sourceId)).toEqual([
      "kc-father-rice-portion"
    ]);

    const confirmationAnswer = domain.retrieveApprovedGuidance({
      query: "为什么任务卡一定要等我确认后才能发送？",
      memberTags: [],
      planTags: ["handoff"],
      topK: 1
    });
    expect(confirmationAnswer.cards.map((card) => card.sourceId)).toEqual([
      "kc-confirm-before-send"
    ]);
  });

  it("hits kc-priority-tofu from natural language when planTags is empty", async () => {
    domain.close();
    domain = await PrivatePlateDomain.create(":memory:");

    const packet = domain.retrieveApprovedGuidance({
      query: "库存里快坏的东西为什么优先上桌？",
      memberTags: [],
      planTags: [],
      topK: 2
    });

    expect(packet.cards.map((card) => card.sourceId)).toContain(
      "kc-priority-tofu"
    );
  });
});

describe("minimum-disclosure semantic retrieval", () => {
  it.each([
    "交接时为什么不能写家人的完整病史？",
    "照护者不需要知道健康标签，这是什么原则？",
    "执行人员只该看到做饭所需的必要信息，为什么？"
  ])("recalls minimum disclosure for: %s", async (query) => {
    const domain = await PrivatePlateDomain.create(":memory:");
    try {
      const result = domain.retrieveApprovedGuidance({
        query,
        planTags: ["handoff", "privacy"],
        topK: 3
      });
      expect(result.cards.map((card) => card.sourceId)).toContain(
        "kc-min-disclosure"
      );
    } finally {
      domain.close();
    }
  });

  it("does not pull the low-sodium card for a generic privacy question", async () => {
    const domain = await PrivatePlateDomain.create(":memory:");
    try {
      const result = domain.retrieveApprovedGuidance({
        query: "任务交接怎样保护家人的隐私和个人信息？",
        planTags: ["privacy", "handoff"],
        topK: 3
      });
      const ids = result.cards.map((card) => card.sourceId);
      expect(ids).toContain("kc-min-disclosure");
      expect(ids).not.toContain("kc-low-sodium-prompt");
    } finally {
      domain.close();
    }
  });
});

function insertCard(
  domain: PrivatePlateDomain,
  input: {
    id: string;
    appliesTo: string[];
    exclusions: string[];
    riskLevel: "low" | "medium" | "high";
    reviewStatus: "draft" | "approved" | "rejected";
    sourceYear: number | null;
  }
): void {
  domain.db
    .prepare(
      `INSERT INTO knowledge_cards
       (id, title, content, tags_json, applicability_json, exclusions_json,
        risk_level, review_status, source_title, source_year, source_url,
        license_id, content_version)
       VALUES (?, ?, '专属检索词', '[]', ?, ?, ?, ?, '测试来源', ?, NULL,
               'lic-test', '1.0.0')`
    )
    .run(
      input.id,
      input.id,
      JSON.stringify(input.appliesTo),
      JSON.stringify(input.exclusions),
      input.riskLevel,
      input.reviewStatus,
      input.sourceYear
    );
}
