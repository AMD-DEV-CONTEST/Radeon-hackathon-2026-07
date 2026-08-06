import { describe, expect, it } from "vitest";

import { mockActivationResponse } from "../mock/mockActivationResponse";
import { decodeActivationResponse } from "./activationApiDecoders";

describe("activation API decoder", () => {
  it("decodes the frozen F03-C projection", () => {
    const decoded = decodeActivationResponse(mockActivationResponse);

    expect(decoded.projection_version).toBe("f03c-demo-v1");
    expect(decoded.event.status).toBe("PENDING_HUMAN_REVIEW");
    expect(decoded.work_records).toHaveLength(2);
    expect(decoded.work_records[0]?.task_id).toBeNull();
  });

  it("rejects unknown versions and non-null activation tasks", () => {
    expect(() =>
      decodeActivationResponse({
        ...mockActivationResponse,
        projection_version: "future-version",
      }),
    ).toThrow("Unsupported activation projection version");

    expect(() =>
      decodeActivationResponse({
        ...mockActivationResponse,
        work_records: [
          {
            ...mockActivationResponse.work_records[0],
            task_id: "task_must_not_exist",
          },
        ],
      }),
    ).toThrow("task_id must be null");
  });
});
