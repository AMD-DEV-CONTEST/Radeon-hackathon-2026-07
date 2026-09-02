import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { literalText, messageText, type PulseNotice } from "../models";
import { usePulse } from "../hooks/usePulse";
import { PulseProvider } from "./PulseProviderContext";
import {
  PulseReadError,
  type PulseDataSource,
} from "./pulseDataSource";

const notice: PulseNotice = {
  id: "runtime-pulse-event",
  eventId: "event_0123456789abcdef0123456789abcdef",
  kind: "attention",
  stateLabel: messageText("pulse.state.attention"),
  severity: "attention",
  priority: 200,
  title: literalText("Review required"),
  summary: literalText("Review required"),
  facts: null,
  analysis: null,
  nextAction: null,
  requiresHumanAction: true,
  createdAt: null,
  runtimeStatus: "UNKNOWN",
  rawRuntimeStatus: "UNKNOWN",
  sourceNotificationStatus: null,
  quality: {
    availability: "partial",
    unknownFields: [],
    contractWarnings: [],
  },
};

function PulseProbe() {
  const pulse = usePulse();
  return (
    <>
      <output data-testid="status">{pulse.status}</output>
      <output data-testid="notice">
        {pulse.currentNotice?.id ?? "none"}
      </output>
      <output data-testid="error">
        {pulse.error?.name ?? "none"}
      </output>
      <button type="button" onClick={pulse.refresh}>
        refresh
      </button>
    </>
  );
}

function sourceWithReads(
  ...reads: (
    | PulseNotice
    | null
    | PulseReadError
  )[]
): PulseDataSource {
  const getPulse = vi.fn<PulseDataSource["getPulse"]>();
  for (const read of reads) {
    if (read instanceof PulseReadError) {
      getPulse.mockRejectedValueOnce(read);
    } else {
      getPulse.mockResolvedValueOnce(read);
    }
  }
  return {
    source: "http",
    getInitialPulse: () => undefined,
    getPulse,
  };
}

describe("PulseProvider and usePulse", () => {
  it("works independently of WorkspaceProvider and exposes confirmed idle", async () => {
    render(
      <PulseProvider dataSource={sourceWithReads(null)}>
        <PulseProbe />
      </PulseProvider>,
    );

    await waitFor(() =>
      expect(screen.getByTestId("status")).toHaveTextContent(
        "ready",
      ),
    );
    expect(screen.getByTestId("notice")).toHaveTextContent("none");
    expect(screen.getByTestId("error")).toHaveTextContent("none");
  });

  it("refreshes the projection and preserves last-known notice on error", async () => {
    const user = userEvent.setup();
    const source = sourceWithReads(
      notice,
      new PulseReadError(
        "transport",
        "http",
        "Runtime Pulse is unavailable.",
      ),
    );
    render(
      <PulseProvider dataSource={source}>
        <PulseProbe />
      </PulseProvider>,
    );

    await waitFor(() =>
      expect(screen.getByTestId("notice")).toHaveTextContent(
        notice.id,
      ),
    );
    await user.click(
      screen.getByRole("button", { name: "refresh" }),
    );

    await waitFor(() =>
      expect(screen.getByTestId("status")).toHaveTextContent(
        "error",
      ),
    );
    expect(screen.getByTestId("notice")).toHaveTextContent(
      notice.id,
    );
    expect(screen.getByTestId("error")).toHaveTextContent(
      "PulseReadError",
    );
  });
});
