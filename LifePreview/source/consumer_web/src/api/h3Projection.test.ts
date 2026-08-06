import { describe, expect, it } from "vitest";

import publicIpPolicy from "../../../shared_contracts/fixtures/h3_public_ip_policy.v1.json";
import { H3ProjectionError, parseH3ProductProjection } from "./h3Projection";

const EPISODE_REVISION_ID = "22222222-2222-4222-8222-222222222222";
const PROJECT_ID = "11111111-1111-4111-8111-111111111111";
const SEQUENCE_ID = "33333333-3333-4333-8333-333333333333";
const REFERENCE_SET_ID = "44444444-4444-4444-8444-444444444444";
const REFERENCE_SET_REVISION_ID = "55555555-5555-4555-8555-555555555555";

interface PublicIpPolicyCase {
  name: string;
  url: string;
  allowlist_host: string;
  canonical_url?: string;
}

const PUBLIC_IP_POLICY = publicIpPolicy as {
  allowed_https_urls: PublicIpPolicyCase[];
  rejected_https_urls: PublicIpPolicyCase[];
  rejected_allowlist_hosts: string[];
};

function goldenProjection(): Record<string, unknown> {
  return {
    schemaVersion: "shidu.h3-product-projection.v1",
    episodeRevisionId: EPISODE_REVISION_ID,
    projectId: PROJECT_ID,
    status: "succeeded",
    durationSeconds: 209 / 24,
    referenceCards: [
      {
        referenceSetId: REFERENCE_SET_ID,
        referenceSetRevisionId: REFERENCE_SET_REVISION_ID,
        characterId: "character.protagonist",
        ageStage: "adult",
        viewName: "front",
        attemptOrdinal: 0,
        imageUrl: "/artifacts/references/protagonist/front",
        qcPassed: true,
        modelFamily: "flux2-dev",
        modelId: "flux2-dev-fp8mixed.v1",
        revision: "flux2-dev-fp8mixed.v1",
      },
      {
        referenceSetId: REFERENCE_SET_ID,
        referenceSetRevisionId: REFERENCE_SET_REVISION_ID,
        characterId: "character.protagonist",
        ageStage: "adult",
        viewName: "three_quarter_left",
        attemptOrdinal: 1,
        imageUrl: "/artifacts/references/protagonist/three-quarter",
        qcPassed: true,
        modelFamily: "flux2-dev",
        modelId: "flux2-dev-fp8mixed.v1",
        revision: "flux2-dev-fp8mixed.v1",
      },
      {
        referenceSetId: REFERENCE_SET_ID,
        referenceSetRevisionId: REFERENCE_SET_REVISION_ID,
        characterId: "character.protagonist",
        ageStage: "adult",
        viewName: "profile_left",
        attemptOrdinal: 0,
        imageUrl: "/artifacts/references/protagonist/profile",
        qcPassed: true,
        modelFamily: "flux2-dev",
        modelId: "flux2-dev-fp8mixed.v1",
        revision: "flux2-dev-fp8mixed.v1",
      },
    ],
    sequences: [
      {
        sequenceId: SEQUENCE_ID,
        ordinal: 1,
        durationSeconds: 209 / 24,
        status: "delivered",
        attempts: [
          {
            attemptOrdinal: 0,
            qcVector: {
              mediaIntegrity: 0.99,
              identityAndSemantics: 0.99,
              technicalQuality: 0.99,
              aestheticQuality: 0.99,
            },
            exceptionCodes: ["H3_FLICKER"],
          },
          {
            attemptOrdinal: 1,
            qcVector: {
              mediaIntegrity: 0.8,
              identityAndSemantics: 0.8,
              technicalQuality: 0.8,
              aestheticQuality: 0.8,
            },
            exceptionCodes: [],
          },
        ],
        selectedAttemptOrdinal: 1,
        selectedCleanly: true,
        selectedWithQcException: false,
        exceptionCodes: [],
        selectionReason: "修复版无质量异常，按固定 clean-first 规则交付。",
      },
    ],
    playbackUrl: "/artifacts/deliveries/episode/play",
    downloadUrl: "/artifacts/deliveries/episode/download",
    disclosure: {
      code: "AI_COMPLETED_NON_ORIGINAL",
      contentMode: "ai_completed",
      label: "AI 补全剧情（非原文）",
      notice: "未找到可核验原文；内容由 AI 补全，可能存在偏差。",
    },
  };
}

function cloneGolden(): any {
  return structuredClone(goldenProjection());
}

describe("Python H3 product projection DTO consumer", () => {
  it("accepts and reconstructs the shared clean-first golden DTO", () => {
    const projection = parseH3ProductProjection(goldenProjection());

    expect(projection).toEqual(goldenProjection());
    expect(projection.sequences[0]).toMatchObject({
      selectedAttemptOrdinal: 1,
      selectedCleanly: true,
      selectedWithQcException: false,
    });
  });

  it("accepts canonical UUIDv7 identifiers like the Python projector", () => {
    const value = cloneGolden();
    value.projectId = "018f1f2e-7b3c-7abc-8def-0123456789ab";

    expect(parseH3ProductProjection(value).projectId).toBe(value.projectId);
  });

  it("validates but does not independently recompute Python selection policy", () => {
    const value = cloneGolden();
    value.sequences[0].attempts[0].exceptionCodes = [];
    value.sequences[0].attempts[0].qcVector = {
      mediaIntegrity: 1,
      identityAndSemantics: 1,
      technicalQuality: 1,
      aestheticQuality: 1,
    };

    expect(parseH3ProductProjection(value).sequences[0].selectedAttemptOrdinal).toBe(1);
  });

  it.each([
    (value: any) => {
      value.workflowDigest = "must-not-leak";
    },
    (value: any) => {
      value.sequences[0].subtitleUrl = "/artifacts/subtitles/final.vtt";
    },
    (value: any) => {
      value.referenceCards[0].physicalPath = "C:\\weights\\front.png";
    },
    (value: any) => {
      value.sequences[0].attempts[0].qcVector.gpuScore = 1;
    },
  ])("rejects fields outside the Python DTO whitelist", (mutate) => {
    const value = cloneGolden();
    mutate(value);

    expect(() => parseH3ProductProjection(value)).toThrow(H3ProjectionError);
  });

  it("requires Python's canonical card, sequence, attempt, and exception ordering", () => {
    const cards = cloneGolden();
    cards.referenceCards.reverse();
    expect(() => parseH3ProductProjection(cards)).toThrow(H3ProjectionError);

    const attempts = cloneGolden();
    attempts.sequences[0].attempts.reverse();
    expect(() => parseH3ProductProjection(attempts)).toThrow(H3ProjectionError);

    const exceptions = cloneGolden();
    exceptions.sequences[0].attempts[0].exceptionCodes = ["Z_LAST", "A_FIRST"];
    expect(() => parseH3ProductProjection(exceptions)).toThrow(H3ProjectionError);
  });

  it.each([
    "/artifacts/%2e%2e/secret",
    "/artifacts/safe/%252e%252e/secret",
    "file:///workspace/final.mp4",
    "C:\\workspace\\final.mp4",
    "\\\\server\\share\\final.mp4",
    "https://user:password@cdn.example.com/reference/front",
    "https://127.0.0.1/reference/front",
    "https://192.168.1.9/reference/front",
    "https://cdn.example.com/reference/front?token=secret",
    "https://cdn.example.com/reference/front#secret",
  ])("rejects unsafe URLs even when the hostname appears in an allowlist", (unsafeUrl) => {
    const value = cloneGolden();
    value.referenceCards[0].imageUrl = unsafeUrl;

    expect(() => parseH3ProductProjection(value, {
      httpsHostAllowlist: ["cdn.example.com", "127.0.0.1", "192.168.1.9"],
    })).toThrow(H3ProjectionError);
  });

  it("accepts an explicitly allowlisted public HTTPS asset", () => {
    const value = cloneGolden();
    value.referenceCards[0].imageUrl =
      "https://cdn.example.com/references/protagonist/front";

    expect(parseH3ProductProjection(value, {
      httpsHostAllowlist: ["cdn.example.com"],
    }).referenceCards[0].imageUrl).toBe(
      "https://cdn.example.com/references/protagonist/front",
    );
  });

  it("preserves brackets for an explicitly allowlisted public IPv6 HTTPS asset", () => {
    const value = cloneGolden();
    const host = "2606:4700:4700::1111";
    const url = `https://[${host}]/references/protagonist/front`;
    value.referenceCards[0].imageUrl = url;

    expect(parseH3ProductProjection(value, {
      httpsHostAllowlist: [host],
    }).referenceCards[0].imageUrl).toBe(url);
  });

  it.each(PUBLIC_IP_POLICY.allowed_https_urls)(
    "normalizes shared public IP policy case: $name",
    (policyCase) => {
      const value = cloneGolden();
      value.referenceCards[0].imageUrl = policyCase.url;

      expect(parseH3ProductProjection(value, {
        httpsHostAllowlist: [policyCase.allowlist_host],
      }).referenceCards[0].imageUrl).toBe(policyCase.canonical_url);
    },
  );

  it.each(PUBLIC_IP_POLICY.rejected_https_urls)(
    "rejects shared non-public IP policy case: $name",
    (policyCase) => {
      const value = cloneGolden();
      value.referenceCards[0].imageUrl = policyCase.url;

      expect(() => parseH3ProductProjection(value, {
        httpsHostAllowlist: [policyCase.allowlist_host],
      })).toThrow(H3ProjectionError);
    },
  );

  it.each(PUBLIC_IP_POLICY.rejected_allowlist_hosts)(
    "rejects single-label HTTPS allowlist host: %s",
    (host) => {
      expect(() => parseH3ProductProjection(goldenProjection(), {
        httpsHostAllowlist: [host],
      })).toThrow(H3ProjectionError);
    },
  );

  it("accepts Python's source-grounded disclosure without an AI non-original claim", () => {
    const value = cloneGolden();
    value.disclosure = {
      code: "SOURCE_GROUNDED",
      contentMode: "source_grounded",
      label: "原文与资料核验改写",
      notice: "内容根据已核验原文与资料进行改写。",
    };

    expect(parseH3ProductProjection(value).disclosure).toEqual(value.disclosure);
  });

  it.each([
    ["剧情补全（非原文）", "内容由自动系统补全，可能存在偏差。"],
    ["AI 补全剧情", "内容由 AI 补全，可能存在偏差。"],
  ])("requires AI-completed disclosures to identify AI and non-original content", (
    label,
    notice,
  ) => {
    const value = cloneGolden();
    value.disclosure.label = label;
    value.disclosure.notice = notice;

    expect(() => parseH3ProductProjection(value)).toThrow(H3ProjectionError);
  });

  it.each([
    "来自 C:\\weights\\model.safetensors 的选版结果。",
    "详情见 file:///workspace/qc.json。",
    "详情见 /workspace/records/qc.json。",
    "详情见 %2Fworkspace%2Frecords%2Fqc.json。",
    "https://internal.local/disclosure",
  ])("rejects path- or URI-bearing public text", (unsafeText) => {
    const value = cloneGolden();
    value.sequences[0].selectionReason = unsafeText;

    expect(() => parseH3ProductProjection(value)).toThrow(H3ProjectionError);
  });

  it("checks selected flags against the selected candidate without ranking it", () => {
    const value = cloneGolden();
    value.sequences[0].selectedCleanly = false;
    value.sequences[0].selectedWithQcException = true;

    expect(() => parseH3ProductProjection(value)).toThrow(H3ProjectionError);
  });
});
