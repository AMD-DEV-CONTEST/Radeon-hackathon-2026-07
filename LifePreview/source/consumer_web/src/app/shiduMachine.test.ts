import { describe, expect, it } from "vitest";

import { initialState, transition } from "./shiduMachine";

describe("Shidu state machine", () => {
  it("requires discovery and persisted candidate selection before catalog loading", () => {
    const discovering = transition(initialState, {
      type: "DISCOVERY_STARTED",
      title: "测试之书",
    });
    expect(discovering).toEqual({ name: "discovering", title: "测试之书" });

    const candidates = transition(discovering, {
      type: "DISCOVERY_COMPLETED",
      resolutionId: "resolution-1",
      candidates: [{
        candidateId: "candidate-1",
        title: "测试之书",
        author: "作者",
        language: "zh-cn",
        edition: "",
        translator: "",
      }],
    });
    expect(candidates.name).toBe("candidates");
    const selecting = transition(candidates, {
      type: "SELECTION_STARTED",
      candidateId: "candidate-1",
    });
    expect(selecting.name).toBe("selecting");
    const catalog = transition(selecting, {
      type: "SELECTION_COMPLETED",
      book: { id: "book-1", title: "测试之书", author: "作者" },
      researchJobId: "research-1",
    });
    expect(catalog).toEqual({
      name: "catalog_loading",
      book: { id: "book-1", title: "测试之书", author: "作者" },
      researchJobId: "research-1",
    });
  });

  it("advances production only from backend job projections", () => {
    const queued = transition(initialState, {
      type: "JOB_ACCEPTED",
      bookId: "book-1",
      directionId: "direction-1",
      job: { jobId: "job-1", bookId: "book-1", status: "queued" },
    });
    expect(queued.name).toBe("job");
    if (queued.name !== "job") throw new Error("expected job state");
    expect(queued.job.status).toBe("queued");

    const scripting = transition(queued, {
      type: "JOB_PROJECTED",
      job: { ...queued.job, status: "scripting" },
    });
    expect(scripting.name).toBe("job");
    if (scripting.name !== "job") throw new Error("expected job state");
    expect(scripting.job.status).toBe("scripting");
  });

  it("opens one moment and can return from the dedicated next-story page", () => {
    const direction = { id: "direction-1", directionKey: "resonance", score: 0.9, payload: { title: "再走一步" } };
    const book = {
      id: "book-1",
      title: "测试之书",
      researchStatus: "ready" as const,
      evidenceCoverage: {},
      directions: [direction],
    };
    const moments = transition(initialState, { type: "CATALOG_PROJECTED", book });
    const moment = transition(moments, { type: "DIRECTION_SELECTED", directionId: direction.id });
    expect(moment).toEqual({ name: "moment", book, direction });

    const job = transition(initialState, {
      type: "JOB_ACCEPTED",
      bookId: book.id,
      directionId: direction.id,
      job: { jobId: "job-1", bookId: book.id, status: "succeeded" },
      book,
      direction,
    });
    const next = transition(job, { type: "NEXT_OPENED" });
    expect(next.name).toBe("next");
    expect(transition(next, { type: "PLAYER_RETURNED" }).name).toBe("job");
  });

  it("stops automatic polling only at machine terminal projections", () => {
    for (const status of ["succeeded", "failed"] as const) {
      const state = transition(initialState, {
        type: "JOB_ACCEPTED",
        bookId: "book-1",
        directionId: "direction-1",
        job: { jobId: "job-1", bookId: "book-1", status },
      });
      expect(state.name).toBe("job");
      if (state.name !== "job") throw new Error("expected job state");
      expect(state.polling).toBe(false);
    }
  });
});
