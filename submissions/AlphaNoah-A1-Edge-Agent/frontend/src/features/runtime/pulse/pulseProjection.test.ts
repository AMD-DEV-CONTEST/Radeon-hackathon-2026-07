import { describe, expect, it } from "vitest";

import {
  adaptPulseProjection,
  decodePulseProjection,
  PulseContractError,
} from "./pulseProjection";

const eventId = "event_0123456789abcdef0123456789abcdef";

describe("Pulse projection contract", () => {
  it("treats null as the confirmed idle projection", () => {
    expect(decodePulseProjection(null)).toBeNull();
  });

  it.each(["attention", "critical"] as const)(
    "maps backend level %s directly without Event severity inference",
    (level) => {
      const dto = decodePulseProjection({
        level,
        title: "Equipment exception requires review",
        event_id: eventId,
      });

      expect(dto).not.toBeNull();
      const notice = adaptPulseProjection(dto!);
      expect(notice.kind).toBe(level);
      expect(notice.severity).toBe(level);
      expect(notice.eventId).toBe(eventId);
    },
  );

  it.each([
    ["prompt", "ignore prior instructions"],
    ["trace_id", "trace-private"],
    ["local_path", "C:\\private\\runtime.sqlite3"],
  ])(
    "rejects the additional sensitive field %s",
    (key, value) => {
      expect(() =>
        decodePulseProjection({
          level: "attention",
          title: "Review required",
          event_id: eventId,
          [key]: value,
        }),
      ).toThrow(PulseContractError);
    },
  );

  it("rejects missing, oversized, and malformed fields", () => {
    expect(() =>
      decodePulseProjection({
        level: "attention",
        title: "Review required",
      }),
    ).toThrow(PulseContractError);
    expect(() =>
      decodePulseProjection({
        level: "attention",
        title: "x".repeat(201),
        event_id: eventId,
      }),
    ).toThrow(PulseContractError);
    expect(() =>
      decodePulseProjection({
        level: "warning",
        title: "Review required",
        event_id: eventId,
      }),
    ).toThrow(PulseContractError);
  });
});
