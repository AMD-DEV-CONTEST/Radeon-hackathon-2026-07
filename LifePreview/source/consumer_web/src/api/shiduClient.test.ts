import { describe, expect, it, vi } from "vitest";

import { createShiduClient } from "./shiduClient";

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("Shidu same-origin client", () => {
  it("discovers by title, then selects only the persisted candidate before catalog polling", async () => {
    const fetcher = vi.fn()
      .mockResolvedValueOnce(json({
        resolutionId: "resolution-1",
        resolution: "candidates",
        candidates: [{ candidateId: "candidate-1", title: "测试之书", author: "作者" }],
      }))
      .mockResolvedValueOnce(json({
        book: { id: "book-1", title: "测试之书", author: "作者" },
        researchJobId: "research-1",
      }))
      .mockResolvedValueOnce(json({ books: [] }));
    const client = createShiduClient(fetcher);

    await client.resolveInput("测试之书");
    await client.selectCandidate("resolution-1", "candidate-1");
    await client.listBooks();

    expect(fetcher.mock.calls.map(([url]) => url)).toEqual([
      "/api/resolve-input",
      "/api/resolve-input/resolution-1/select",
      "/api/books",
    ]);
    expect(JSON.parse(String((fetcher.mock.calls[0][1] as RequestInit).body))).toEqual({ title: "测试之书" });
    expect(JSON.parse(String((fetcher.mock.calls[1][1] as RequestInit).body))).toEqual({ candidateId: "candidate-1" });
    expect(String((fetcher.mock.calls[1][1] as RequestInit).body)).not.toMatch(/title|author|url/i);
  });

  it("sends only consumer selections and a fresh idempotency key", async () => {
    const fetcher = vi.fn()
      .mockResolvedValueOnce(json({ jobId: "job-1", bookId: "book-1", status: "queued" }, 202))
      .mockResolvedValueOnce(json({ jobId: "job-2", bookId: "book-1", status: "queued" }, 202));
    const client = createShiduClient(fetcher);
    const selection = {
      bookId: "book-1",
      directionRevisionId: "direction-1",
      trialScriptRevisionId: "script-1",
    };
    await client.createVideoJob(selection);
    await client.createVideoJob(selection);

    const [url, init] = fetcher.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/video-jobs");
    expect(JSON.parse(String(init.body))).toEqual(selection);
    expect(JSON.stringify(init.body)).not.toContain("voicePreset");
    const firstKey = new Headers(init.headers).get("Idempotency-Key");
    const secondKey = new Headers((fetcher.mock.calls[1] as [string, RequestInit])[1].headers).get("Idempotency-Key");
    expect(firstKey).toBeTruthy();
    expect(secondKey).toBeTruthy();
    expect(secondKey).not.toBe(firstKey);
  });

  it("preserves the public retryability decision", async () => {
    const fetcher = vi.fn().mockResolvedValue(json({
      error_code: "dependency_unavailable",
      message: "服务暂时不可用，请稍后重试",
      retryable: true,
    }, 503));
    const client = createShiduClient(fetcher);
    await expect(client.listBooks()).rejects.toMatchObject({
      code: "dependency_unavailable",
      retryable: true,
      status: 503,
    });
  });

  it("starts a new research job for an insufficient book", async () => {
    const fetcher = vi.fn().mockResolvedValue(json({
      book: { id: "book-1", title: "测试之书", author: "作者" },
      researchJobId: "research-retry-1",
    }));
    const client = createShiduClient(fetcher);

    await client.retryResearch("book-1");

    expect(fetcher.mock.calls[0][0]).toBe("/api/books/book-1/research");
    expect((fetcher.mock.calls[0][1] as RequestInit).method).toBe("POST");
    expect(new Headers((fetcher.mock.calls[0][1] as RequestInit).headers).get("Idempotency-Key")).toBeTruthy();
  });

  it("fails closed when an H3 job contains an unvalidated product projection", async () => {
    const fetcher = vi.fn().mockResolvedValue(json({
      jobId: "job-1",
      bookId: "book-1",
      status: "succeeded",
      h3Product: {
        schemaVersion: "shidu.h3-product-projection.v1",
        playbackUrl: "file:///workspace/private.mp4",
      },
    }));
    const client = createShiduClient(fetcher);

    await expect(client.getVideoJob("job-1")).rejects.toMatchObject({
      name: "H3ProjectionError",
    });
  });

  it("also validates an idempotent create replay that is already H3-complete", async () => {
    const fetcher = vi.fn().mockResolvedValue(json({
      jobId: "job-1",
      bookId: "book-1",
      status: "succeeded",
      h3Product: { schemaVersion: "tampered" },
    }, 202));
    const client = createShiduClient(fetcher);

    await expect(client.createVideoJob({
      bookId: "book-1",
      directionRevisionId: "direction-1",
      trialScriptRevisionId: "script-1",
    })).rejects.toMatchObject({ name: "H3ProjectionError" });
  });

  it("preserves a validated H3 GPU runtime proof", async () => {
    const proof = {
      phase: "h3",
      promptId: "h3-prompt-1",
      queueId: 17,
      submissionNonce: "1".repeat(32),
      workflowSha256: "2".repeat(64),
      gpuActivityObserved: true,
      processExited: false,
      referenceSha256: "fe82d64b5c47c2ef9159428f7dc1bedc18bf90dfe4ff86dff551672bbc673153",
      referenceSourceMode: "preuploaded_imported",
    };
    const client = createShiduClient(vi.fn().mockResolvedValue(json({
      jobId: "job-1",
      bookId: "book-1",
      status: "rendering",
      gpuRuntimeProof: proof,
    })));

    await expect(client.getVideoJob("job-1")).resolves.toMatchObject({ gpuRuntimeProof: proof });
  });

  it("fails closed for a rendering claim with an invalid GPU proof", async () => {
    const client = createShiduClient(vi.fn().mockResolvedValue(json({
      jobId: "job-1",
      bookId: "book-1",
      status: "rendering",
      gpuRuntimeProof: {
        phase: "h3",
        promptId: "h3-prompt-1",
        queueId: 17,
        submissionNonce: "1".repeat(32),
        workflowSha256: "2".repeat(64),
        gpuActivityObserved: true,
        processExited: false,
        referenceSha256: "0".repeat(64),
        referenceSourceMode: "preuploaded_imported",
      },
    })));

    await expect(client.getVideoJob("job-1")).rejects.toThrow("Invalid GPU runtime proof");
  });

  it("reuses the idempotency key when a retryable discovery is retried", async () => {
    const fetcher = vi.fn()
      .mockResolvedValueOnce(json({
        error_code: "dependency_unavailable",
        message: "服务暂时不可用，请稍后重试",
        retryable: true,
      }, 503))
      .mockResolvedValueOnce(json({
        resolutionId: "resolution-1",
        resolution: "unresolved",
        candidates: [],
      }));
    const client = createShiduClient(fetcher);

    await expect(client.resolveInput("测试之书")).rejects.toMatchObject({ retryable: true });
    await client.resolveInput("测试之书");

    const first = new Headers((fetcher.mock.calls[0][1] as RequestInit).headers).get("Idempotency-Key");
    const second = new Headers((fetcher.mock.calls[1][1] as RequestInit).headers).get("Idempotency-Key");
    expect(first).toBeTruthy();
    expect(second).toBe(first);
  });

  it("reuses the video-job idempotency key when the first response is lost", async () => {
    const fetcher = vi.fn()
      .mockRejectedValueOnce(new TypeError("network response lost"))
      .mockResolvedValueOnce(json({
        jobId: "job-1",
        bookId: "book-1",
        status: "queued",
      }, 202));
    const client = createShiduClient(fetcher);
    const selection = {
      bookId: "book-1",
      directionRevisionId: "direction-1",
      trialScriptRevisionId: "script-1",
    };

    await expect(client.createVideoJob(selection)).rejects.toThrow("response lost");
    await expect(client.createVideoJob(selection)).resolves.toMatchObject({ jobId: "job-1" });

    const first = new Headers((fetcher.mock.calls[0][1] as RequestInit).headers).get("Idempotency-Key");
    const second = new Headers((fetcher.mock.calls[1][1] as RequestInit).headers).get("Idempotency-Key");
    expect(first).toBeTruthy();
    expect(second).toBe(first);
  });
});
