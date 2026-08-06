import { describe, expect, it } from "vitest";
import { afterEach, beforeEach } from "vitest";
import { PrivatePlateDomain } from "../service/privateplate-domain.js";
import {
  normalizeAgentPreferenceKind,
  persistAgentMemoryKind
} from "./memory-kind.js";

describe("memory kind vocabulary", () => {
  it("normalizes legacy taste rows to preference", () => {
    expect(normalizeAgentPreferenceKind("taste")).toBe("preference");
    expect(normalizeAgentPreferenceKind("preference")).toBe("preference");
  });

  it("persists preference kind from agent preview", () => {
    expect(persistAgentMemoryKind("preference")).toBe("preference");
    expect(persistAgentMemoryKind("taste")).toBe("preference");
    expect(persistAgentMemoryKind("health_fact")).toBe("health_fact");
  });
});

describe("member memory write kind persistence", () => {
  let domain: PrivatePlateDomain;

  beforeEach(async () => {
    domain = await PrivatePlateDomain.create(":memory:");
  });

  afterEach(() => {
    domain.close();
  });

  it("stores preference rows with kind preference, not taste", () => {
    const preview = domain.previewMemberMemoryChange({
      memberId: "mem-admin",
      kind: "preference",
      summary: "喜欢清淡口味"
    });
    const confirmed = domain.confirmPendingWrite({
      pendingActionId: preview.confirmation.pendingActionId,
      confirmationToken: preview.confirmation.confirmationToken,
      idempotencyKey: "mem-kind-test",
      expectedPayloadHash: preview.confirmation.payloadHash
    });
    expect(confirmed.ok).toBe(true);

    const row = domain.db
      .prepare(
        `SELECT kind, note FROM member_preferences
         WHERE member_id = ? AND note = ? AND active = 1`
      )
      .get("mem-admin", "喜欢清淡口味") as { kind: string; note: string } | undefined;
    expect(row?.kind).toBe("preference");

    const day = domain.getDayContext();
    const pref = day.members
      .flatMap((member) => member.preferences)
      .find((item) => item.note === "喜欢清淡口味");
    expect(pref?.kind).toBe("preference");
  });
});
