import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { IntelligenceRecord } from "../types";
import { IntelligenceDrawer } from "./IntelligenceDrawer";

const record: IntelligenceRecord = {
  schema_version: "signalforge/intelligence-lineage/v1",
  run_id: "run-accepted",
  request_id: "request-accepted",
  trace_id: "80c42f9bdbda413b9f86413db94ed20a",
  status: "completed",
  capture: {
    enabled: false,
    available: false,
    status: "disabled",
    stored_bytes: 0,
    maximum_bytes: 0
  },
  started_at: "2026-07-25T00:00:00Z",
  completed_at: "2026-07-25T00:00:01Z",
  timeline: [
    {
      sequence: 1,
      step_id: "interpret-request",
      event_type: "interpretation",
      status: "completed",
      at: "2026-07-25T00:00:00Z"
    },
    {
      sequence: 2,
      step_id: "context-wave-1",
      event_type: "wave",
      status: "started",
      wave: 1,
      specialist_count: 4,
      concurrency_limit: 4,
      at: "2026-07-25T00:00:00.100Z"
    },
    {
      sequence: 3,
      step_id: "context-wave-1",
      event_type: "wave",
      status: "completed",
      wave: 1,
      specialist_count: 4,
      concurrency_limit: 4,
      succeeded_count: 4,
      observed_concurrency: 4,
      at: "2026-07-25T00:00:00.800Z"
    },
    {
      sequence: 4,
      step_id: "final-synthesis",
      event_type: "run",
      status: "completed",
      at: "2026-07-25T00:00:01Z"
    }
  ],
  model_calls: [],
  retrievals: [{
    retrieval_id: "retrieval-accepted",
    step_id: "context-accepted",
    role_id: "financial-quality/v1",
    method: "authorized_context_packet",
    context_packet_id: "packet-accepted",
    evidence_ids: [],
    estimated_tokens: 0,
    status: "selected",
    completed_at: "2026-07-25T00:00:01Z"
  }],
  engine_calls: [],
  reviews: [],
  release: {
    answer_id: "answer-accepted",
    primary_intent: "company_comparison",
    section_types: ["comparison"],
    claim_refs: ["claim-answer-used"],
    evidence_refs: ["evidence-answer-used"],
    receipt_refs: ["receipt-answer-used"],
    status: "released"
  }
};

describe("IntelligenceDrawer identity boundary", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("renders lineage only when Workspace and Mission Control identities match", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => record
    } as Response)));
    render(
      <IntelligenceDrawer
        runID={record.run_id}
        traceID={record.trace_id}
        open
        protectedCapture={false}
        onClose={vi.fn()}
      />
    );
    expect(await screen.findByText(/80c42f9bdbda/)).toBeInTheDocument();
    expect(screen.getByText("run-accepted")).toBeInTheDocument();
    expect(screen.getByText(/1 answer-used claims/i)).toBeInTheDocument();
  });

  it("shows a judge-facing trace with the same identity and bounded specialist wave", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => record
    } as Response)));
    render(
      <IntelligenceDrawer
        runID={record.run_id}
        traceID={record.trace_id}
        open
        protectedCapture={false}
        onClose={vi.fn()}
      />
    );
    fireEvent.click(await screen.findByRole("tab", { name: "trace" }));
    const trace = await screen.findByRole("region", { name: "Judge-facing correlated execution trace" });
    expect(trace).toHaveTextContent("Conversation-to-trace timeline");
    expect(trace).toHaveTextContent("Context Wave 1");
    expect(trace).toHaveTextContent("4 specialists");
    expect(trace).toHaveTextContent("limit 4");
    expect(trace).toHaveTextContent("concurrency 4");
    expect(trace).toHaveTextContent(/80c42f9bdbda/);
  });

  it("fails closed when Mission Control returns a different trace", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => ({ ...record, trace_id: "ffffffffffffffffffffffffffffffff" })
    } as Response)));
    render(
      <IntelligenceDrawer
        runID={record.run_id}
        traceID={record.trace_id}
        open
        protectedCapture={false}
        onClose={vi.fn()}
      />
    );
    expect(await screen.findByText("Lineage unavailable")).toBeInTheDocument();
    expect(screen.queryByText("ffffffffffff")).not.toBeInTheDocument();
  });

  it("treats nullable historical audit collections as empty instead of crashing", async () => {
    const nullableRecord: IntelligenceRecord = {
      ...record,
      retrievals: [{
        retrieval_id: "retrieval-empty",
        step_id: "context-financial-quality",
        role_id: "financial-quality/v1",
        method: "authorized_context_packet",
        context_packet_id: "packet-empty",
        evidence_ids: null as unknown as string[],
        estimated_tokens: 0,
        status: "selected",
        completed_at: "2026-07-25T00:00:01Z"
      }]
    };
    vi.stubGlobal("fetch", vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => nullableRecord
    } as Response)));
    render(
      <IntelligenceDrawer
        runID={nullableRecord.run_id}
        traceID={nullableRecord.trace_id}
        open
        protectedCapture={false}
        onClose={vi.fn()}
      />
    );
    expect(await screen.findByText("run-accepted")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "evidence" }));
    expect(await screen.findByText("Financial Quality V1")).toBeInTheDocument();
    expect(screen.queryByText("Lineage unavailable")).not.toBeInTheDocument();
  });
});
