import { describe, expect, it } from "vitest";

import {
  projectDigitalEmployeeStage,
  projectDigitalEmployeeStatus,
} from "./displayProjection";

describe("digital employee display projection", () => {
  it.each([
    ["intern", "employees.stage.intern", "info"],
    ["trial", "employees.stage.trial", "attention"],
    ["production", "employees.stage.production", "info"],
    ["paused", "employees.stage.paused", "warning"],
    ["retired", "employees.stage.retired", "info"],
  ] as const)(
    "maps stage %s to its product label and tone",
    (raw, label, tone) => {
      expect(projectDigitalEmployeeStage(raw)).toEqual({
        value: raw,
        raw,
        label: { kind: "message", id: label },
        tone,
      });
    },
  );

  it("normalizes a known stage while preserving the unmodified raw value", () => {
    expect(projectDigitalEmployeeStage("  PRODUCTION ")).toEqual({
      value: "production",
      raw: "  PRODUCTION ",
      label: {
        kind: "message",
        id: "employees.stage.production",
      },
      tone: "info",
    });
  });

  it.each([["experimental"], [""], [null]] as const)(
    "fails closed for unknown stage %s and preserves its raw value",
    (raw) => {
      expect(projectDigitalEmployeeStage(raw)).toEqual({
        value: "unknown",
        raw,
        label: {
          kind: "message",
          id: "employees.stage.unknown",
        },
        tone: "warning",
      });
    },
  );

  it.each([
    ["online", "employees.status.online", "success"],
    ["offline", "employees.status.offline", "warning"],
    ["working", "employees.status.working", "attention"],
  ] as const)(
    "maps operational status %s to its product label and tone",
    (raw, label, tone) => {
      expect(projectDigitalEmployeeStatus(raw)).toEqual({
        value: raw,
        raw,
        label: { kind: "message", id: label },
        tone,
      });
    },
  );

  it("normalizes a known status while preserving the unmodified raw value", () => {
    expect(projectDigitalEmployeeStatus(" ONLINE ")).toEqual({
      value: "online",
      raw: " ONLINE ",
      label: {
        kind: "message",
        id: "employees.status.online",
      },
      tone: "success",
    });
  });

  it.each([["degraded"], [""], [null]] as const)(
    "fails closed for unknown status %s and preserves its raw value",
    (raw) => {
      expect(projectDigitalEmployeeStatus(raw)).toEqual({
        value: "unknown",
        raw,
        label: {
          kind: "message",
          id: "employees.status.unknown",
        },
        tone: "info",
      });
    },
  );
});
