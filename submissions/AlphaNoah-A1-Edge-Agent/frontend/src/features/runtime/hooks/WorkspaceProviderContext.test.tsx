import {
  act,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { adaptActionSummary } from "../adapter/actionSummaryAdapter";
import { adaptEventView } from "../adapter/eventViewAdapter";
import { adaptHealthView } from "../adapter/healthViewAdapter";
import { adaptPulseNotice } from "../adapter/pulseNoticeAdapter";
import {
  literalText,
  WorkspaceReadError,
  type WorkspaceDataSource,
  type WorkspaceRequest,
  type WorkspaceSnapshot,
} from "../models";
import { buildMockWorkspaceSnapshot } from "../mock/MockWorkspaceDataSource";
import { useActionSummary } from "./useActionSummary";
import { useEvents } from "./useEvents";
import { useHealth } from "./useHealth";
import { usePulse } from "./usePulse";
import { useWorkspace } from "./useWorkspace";
import { WorkspaceProvider } from "./WorkspaceProviderContext";

function taggedSnapshot(
  tag: string,
  source: WorkspaceSnapshot["source"] = "mock",
): WorkspaceSnapshot {
  const event = adaptEventView({
    eventId: `event_${tag}`,
    status: "ANALYZED",
    severity: "MEDIUM",
    title: literalText(`Event ${tag}`),
    detail: null,
    sourceLabel: null,
    occurredAt: null,
    occurredLabel: null,
    location: null,
    assetId: null,
    actionSummaryId: `action_${tag}`,
  });
  const action = adaptActionSummary({
    id: `action_${tag}`,
    eventId: event.id,
    heading: literalText(`Action ${tag}`),
    facts: [],
    aiUnderstanding: null,
    rawSeverity: "MEDIUM",
    riskExplanation: null,
    suggestedAction: null,
    humanDecision: null,
    decision: null,
    task: null,
    evidenceStatus: null,
    timeline: [],
  });
  const notice = adaptPulseNotice({
    id: `notice_${tag}`,
    eventId: event.id,
    status: "ANALYZED",
    severity: "MEDIUM",
    title: literalText(`Notice ${tag}`),
    summary: literalText(`Summary ${tag}`),
    facts: null,
    analysis: null,
    nextAction: null,
    requiresHumanAction: false,
    createdAt: null,
    sourceNotificationStatus: null,
  });

  return {
    ...buildMockWorkspaceSnapshot(),
    source,
    site: {
      id: `site_${tag}`,
      name: literalText(`Site ${tag}`),
      area: null,
      observationLabel: null,
    },
    health: adaptHealthView({
      state: "healthy",
      label: literalText(`Health ${tag}`),
      components: [],
      observedAt: null,
    }),
    events: [event],
    activeNotices: [notice],
    actionSummaries: [action],
    currentFocus: action,
    observedAt: tag,
  };
}

function literalValue(
  value: { kind: "literal"; value: string } | { kind: "message" },
): string {
  return value.kind === "literal" ? value.value : value.kind;
}

function RuntimeProbe({
  expectedSource,
  onRender,
}: {
  expectedSource?: WorkspaceSnapshot["source"];
  onRender?: (value: string) => void;
}) {
  const workspace = useWorkspace();
  const { events } = useEvents();
  const health = useHealth();
  const pulse = usePulse();
  const action = useActionSummary(events[0]?.id ?? null);
  const source = workspace.data?.source ?? "none";

  onRender?.(`${expectedSource ?? "none"}:${source}`);

  return (
    <div>
      <output data-testid="status">{workspace.status}</output>
      <output data-testid="source">{source}</output>
      <output data-testid="observed">
        {workspace.data?.observedAt ?? "none"}
      </output>
      <output data-testid="event">{events[0]?.id ?? "none"}</output>
      <output data-testid="health">
        {health ? literalValue(health.label) : "none"}
      </output>
      <output data-testid="pulse">
        {pulse.currentNotice?.id ?? "none"}
      </output>
      <output data-testid="action">{action?.id ?? "none"}</output>
      <output data-testid="error">
        {workspace.error?.code ?? "none"}
      </output>
      <button type="button" onClick={workspace.refresh}>
        refresh
      </button>
    </div>
  );
}

function sourceWithReads({
  source = "mock",
  initial,
  getWorkspace,
}: {
  source?: WorkspaceDataSource["source"];
  initial: WorkspaceSnapshot | null;
  getWorkspace: (
    request?: WorkspaceRequest,
  ) => Promise<WorkspaceSnapshot>;
}): WorkspaceDataSource {
  return {
    source,
    getInitialSnapshot: () => initial,
    getWorkspace,
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

describe("WorkspaceProvider and runtime hooks", () => {
  it("exposes the synchronous Mock snapshot, refreshes it, and derives every hook from the same snapshot", async () => {
    const snapshots = [
      taggedSnapshot("refresh_1"),
      taggedSnapshot("refresh_2"),
    ];
    const getWorkspace = vi
      .fn<WorkspaceDataSource["getWorkspace"]>()
      .mockResolvedValueOnce(snapshots[0] as WorkspaceSnapshot)
      .mockResolvedValueOnce(snapshots[1] as WorkspaceSnapshot);
    const source = sourceWithReads({
      initial: taggedSnapshot("initial"),
      getWorkspace,
    });

    render(
      <WorkspaceProvider dataSource={source}>
        <RuntimeProbe />
      </WorkspaceProvider>,
    );

    expect(screen.getByTestId("source")).toHaveTextContent("mock");
    await waitFor(() =>
      expect(screen.getByTestId("observed")).toHaveTextContent(
        "refresh_1",
      ),
    );
    expect(screen.getByTestId("event")).toHaveTextContent(
      "event_refresh_1",
    );
    expect(screen.getByTestId("health")).toHaveTextContent(
      "Health refresh_1",
    );
    expect(screen.getByTestId("pulse")).toHaveTextContent(
      "notice_refresh_1",
    );
    expect(screen.getByTestId("action")).toHaveTextContent(
      "action_refresh_1",
    );

    await userEvent.click(
      screen.getByRole("button", { name: "refresh" }),
    );
    await waitFor(() =>
      expect(screen.getByTestId("observed")).toHaveTextContent(
        "refresh_2",
      ),
    );
    expect(screen.getByTestId("event")).toHaveTextContent(
      "event_refresh_2",
    );
    expect(screen.getByTestId("health")).toHaveTextContent(
      "Health refresh_2",
    );
    expect(screen.getByTestId("pulse")).toHaveTextContent(
      "notice_refresh_2",
    );
    expect(screen.getByTestId("action")).toHaveTextContent(
      "action_refresh_2",
    );
    expect(screen.getByTestId("status")).toHaveTextContent("ready");
  });

  it("preserves last-known data when refresh fails", async () => {
    const source = sourceWithReads({
      initial: taggedSnapshot("last_known"),
      getWorkspace: vi.fn().mockRejectedValue(
        new WorkspaceReadError(
          "transport",
          "mock",
          "Disconnected",
        ),
      ),
    });

    render(
      <WorkspaceProvider dataSource={source}>
        <RuntimeProbe />
      </WorkspaceProvider>,
    );

    await waitFor(() =>
      expect(screen.getByTestId("status")).toHaveTextContent("error"),
    );
    expect(screen.getByTestId("observed")).toHaveTextContent(
      "last_known",
    );
    expect(screen.getByTestId("error")).toHaveTextContent(
      "transport",
    );
  });

  it("aborts the stale request and ignores its late result", async () => {
    const reads: {
      signal: AbortSignal | undefined;
      result: ReturnType<typeof deferred<WorkspaceSnapshot>>;
    }[] = [];
    const source = sourceWithReads({
      initial: null,
      getWorkspace: vi.fn((request?: WorkspaceRequest) => {
        const result = deferred<WorkspaceSnapshot>();
        reads.push({ signal: request?.signal, result });
        return result.promise;
      }),
    });

    render(
      <WorkspaceProvider dataSource={source}>
        <RuntimeProbe />
      </WorkspaceProvider>,
    );
    await waitFor(() => expect(reads).toHaveLength(1));

    await userEvent.click(
      screen.getByRole("button", { name: "refresh" }),
    );
    await waitFor(() => expect(reads).toHaveLength(2));
    const first = reads[0];
    const second = reads[1];
    if (!first || !second) {
      throw new Error("Expected two provider reads.");
    }
    expect(first.signal?.aborted).toBe(true);

    await act(async () => {
      second.result.resolve(taggedSnapshot("newest"));
      await second.result.promise;
    });
    await waitFor(() =>
      expect(screen.getByTestId("observed")).toHaveTextContent(
        "newest",
      ),
    );

    await act(async () => {
      first.result.resolve(taggedSnapshot("stale"));
      await first.result.promise;
    });
    expect(screen.getByTestId("observed")).toHaveTextContent(
      "newest",
    );
  });

  it("does not expose data from the previous source during a provider switch", async () => {
    const renderTrace: string[] = [];
    const mockSource = sourceWithReads({
      initial: taggedSnapshot("mock_old", "mock"),
      getWorkspace: vi
        .fn()
        .mockResolvedValue(taggedSnapshot("mock_old", "mock")),
    });
    const pendingHttpRead = deferred<WorkspaceSnapshot>();
    const httpSource = sourceWithReads({
      source: "http",
      initial: null,
      getWorkspace: () => pendingHttpRead.promise,
    });

    const view = render(
      <WorkspaceProvider dataSource={mockSource}>
        <RuntimeProbe
          expectedSource="mock"
          onRender={(value) => renderTrace.push(value)}
        />
      </WorkspaceProvider>,
    );
    await waitFor(() =>
      expect(screen.getByTestId("status")).toHaveTextContent("ready"),
    );

    view.rerender(
      <WorkspaceProvider dataSource={httpSource}>
        <RuntimeProbe
          expectedSource="http"
          onRender={(value) => renderTrace.push(value)}
        />
      </WorkspaceProvider>,
    );

    expect(renderTrace).not.toContain("http:mock");
    expect(screen.getByTestId("source")).toHaveTextContent("none");
  });
});

function ActionProbe({
  eventId,
  actionSummaryId,
}: {
  eventId: string;
  actionSummaryId: string;
}) {
  const exactSelector = useActionSummary as unknown as (
    selectedEventId: string | null,
    selectedActionSummaryId: string | null,
  ) => ReturnType<typeof useActionSummary>;
  const action = exactSelector(eventId, actionSummaryId);

  return <output data-testid="selected-action">{action?.id ?? "none"}</output>;
}

function relationshipSnapshot(): WorkspaceSnapshot {
  const base = taggedSnapshot("relationship");
  const makeAction = (id: string, eventId: string) =>
    adaptActionSummary({
      id,
      eventId,
      heading: literalText(id),
      facts: [],
      aiUnderstanding: null,
      rawSeverity: "LOW",
      riskExplanation: null,
      suggestedAction: null,
      humanDecision: null,
      decision: null,
      task: null,
      evidenceStatus: null,
      timeline: [],
    });

  return {
    ...base,
    actionSummaries: [
      makeAction("action_a_first", "event_a"),
      makeAction("action_a_exact", "event_a"),
      makeAction("action_b", "event_b"),
    ],
    currentFocus: makeAction("action_b", "event_b"),
  };
}

describe("ActionSummary exact selection", () => {
  it("uses both eventId and actionSummaryId when an event has multiple summaries", () => {
    const snapshot = relationshipSnapshot();
    const source = sourceWithReads({
      initial: snapshot,
      getWorkspace: vi.fn().mockResolvedValue(snapshot),
    });

    render(
      <WorkspaceProvider dataSource={source}>
        <ActionProbe
          eventId="event_a"
          actionSummaryId="action_a_exact"
        />
      </WorkspaceProvider>,
    );

    expect(screen.getByTestId("selected-action")).toHaveTextContent(
      "action_a_exact",
    );
  });

  it("returns null for a stale or cross-event actionSummaryId instead of falling back", () => {
    const snapshot = relationshipSnapshot();
    const source = sourceWithReads({
      initial: snapshot,
      getWorkspace: vi.fn().mockResolvedValue(snapshot),
    });

    render(
      <WorkspaceProvider dataSource={source}>
        <ActionProbe
          eventId="event_a"
          actionSummaryId="action_b"
        />
      </WorkspaceProvider>,
    );

    expect(screen.getByTestId("selected-action")).toHaveTextContent(
      "none",
    );
  });
});
