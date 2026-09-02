import { getPublicErrorMessage, toUtcRangeEnd } from "@/lib/api-error";

describe("getPublicErrorMessage", () => {
  it("preserves PostgREST object error messages instead of falling back to internal_error", () => {
    expect(getPublicErrorMessage({
      code: "23503",
      message: "insert or update on table violates foreign key constraint",
      details: "Key is not present in table.",
      hint: "Check prompt_id.",
    })).toBe("insert or update on table violates foreign key constraint Key is not present in table. Check prompt_id.");
  });

  it("falls back to a stable code when no message exists", () => {
    expect(getPublicErrorMessage({ code: "PGRST205" })).toBe("PGRST205");
  });

  it("keeps a full ISO timestamp intact while expanding a date-only filter", () => {
    expect(toUtcRangeEnd("2026-08-06T03:04:05.000Z")).toBe("2026-08-06T03:04:05.000Z");
    expect(toUtcRangeEnd("2026-08-06")).toBe("2026-08-06T23:59:59.999Z");
  });
});
