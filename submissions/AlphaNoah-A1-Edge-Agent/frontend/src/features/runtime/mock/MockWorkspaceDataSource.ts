import { adaptActionSummary } from "../adapter/actionSummaryAdapter";
import { adaptEventView } from "../adapter/eventViewAdapter";
import { adaptHealthView } from "../adapter/healthViewAdapter";
import { adaptPulseNotice } from "../adapter/pulseNoticeAdapter";
import {
  messageText,
  WorkspaceReadError,
  type WorkspaceDataSource,
  type WorkspaceRequest,
  type WorkspaceSnapshot,
} from "../models";
import {
  mockActionInputs,
  mockEventInputs,
  mockHealthInput,
  mockNoticeInputs,
} from "./mockAdapterInputs";

export class MockWorkspaceDataSource implements WorkspaceDataSource {
  readonly source = "mock" as const;
  readonly #snapshot: WorkspaceSnapshot;

  constructor(snapshot: WorkspaceSnapshot = buildMockWorkspaceSnapshot()) {
    this.#snapshot = snapshot;
  }

  getInitialSnapshot(): WorkspaceSnapshot {
    return this.#snapshot;
  }

  async getWorkspace(
    request: WorkspaceRequest = {},
  ): Promise<WorkspaceSnapshot> {
    if (request.signal?.aborted) {
      throw new WorkspaceReadError(
        "aborted",
        this.source,
        "Workspace read was aborted.",
      );
    }

    return selectCurrentFocus(
      this.#snapshot,
      request.selectedEventId,
    );
  }
}

export function buildMockWorkspaceSnapshot(): WorkspaceSnapshot {
  const events = mockEventInputs.map(adaptEventView);
  const actionSummaries = mockActionInputs.map(adaptActionSummary);
  const activeNotices = mockNoticeInputs
    .map(adaptPulseNotice)
    .sort(
      (left, right) =>
        right.priority - left.priority ||
        left.id.localeCompare(right.id),
    );

  return {
    source: "mock",
    site: {
      id: "mock_site_north_assembly_line_3",
      name: messageText("system.siteValue"),
      area: null,
      observationLabel: messageText("system.updated"),
    },
    health: adaptHealthView(mockHealthInput),
    contextSignals: [
      {
        id: "attention",
        label: messageText("workspace.attentionSummary"),
        tone: "attention",
      },
      {
        id: "analysis",
        label: messageText("workspace.analysisSummary"),
        tone: "info",
      },
      {
        id: "edge",
        label: messageText("workspace.edgeSummary"),
        tone: "success",
      },
    ],
    activeNotices,
    events,
    actionSummaries,
    currentFocus: actionSummaries[0] ?? null,
    commandSuggestions: [
      {
        id: "mock_command_summarize",
        label: messageText("command.quick1"),
      },
      {
        id: "mock_command_evidence",
        label: messageText("command.quick2"),
      },
      {
        id: "mock_command_risk",
        label: messageText("command.quick3"),
      },
    ],
    observedAt: null,
    quality: {
      availability: "available",
      unknownFields: [],
      contractWarnings: [],
    },
  };
}

function selectCurrentFocus(
  snapshot: WorkspaceSnapshot,
  selectedEventId?: string | null,
): WorkspaceSnapshot {
  if (selectedEventId === undefined) {
    return snapshot;
  }

  const selectedEvent = snapshot.events.find(
    (event) => event.id === selectedEventId,
  );
  const actionSummaryId = selectedEvent?.actionSummaryId ?? null;

  return {
    ...snapshot,
    currentFocus:
      actionSummaryId === null
        ? null
        : (snapshot.actionSummaries.find(
            (summary) =>
              summary.id === actionSummaryId &&
              summary.eventId === selectedEventId,
          ) ?? null),
  };
}

export const mockWorkspaceDataSource =
  new MockWorkspaceDataSource();
