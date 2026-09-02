import {
  act,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { adaptActivationSnapshot } from "../adapter/activationAdapter";
import { mockActivationResponse } from "../mock/mockActivationResponse";
import type {
  ActivationCommand,
  ActivationDataSource,
} from "../models";
import { ActivationError } from "../models";
import { ActivationProvider } from "./ActivationProvider";
import { useActivation } from "./useActivation";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

function Probe() {
  const activation = useActivation();
  return (
    <div>
      <output data-testid="status">{activation.status}</output>
      <output data-testid="event">
        {activation.snapshot?.eventId ?? "none"}
      </output>
      <button
        type="button"
        disabled={activation.status === "activating"}
        onClick={() => void activation.activate()}
      >
        activate
      </button>
    </div>
  );
}

function MultiTriggerProbe() {
  const activation = useActivation();
  return (
    <div>
      <output data-testid="multi-status">{activation.status}</output>
      <output data-testid="multi-event">
        {activation.snapshot?.eventId ?? "none"}
      </output>
      <button
        type="button"
        onClick={() => void activation.activate()}
      >
        activate one
      </button>
      <button
        type="button"
        onClick={() => void activation.activate()}
      >
        activate two
      </button>
      <button type="button" onClick={() => void activation.retry()}>
        retry
      </button>
    </div>
  );
}

describe("ActivationProvider", () => {
  it("shares one snapshot and suppresses duplicate activation", async () => {
    const pending = deferred<
      ReturnType<typeof adaptActivationSnapshot>
    >();
    const activate = vi.fn(
      (_command: ActivationCommand) => pending.promise,
    );
    const source: ActivationDataSource = {
      source: "mock",
      activate,
      getEvent: vi.fn(),
    };

    render(
      <ActivationProvider
        dataSource={source}
        requestIdFactory={() => "activation-test-1"}
      >
        <Probe />
      </ActivationProvider>,
    );

    const button = screen.getByRole("button", { name: "activate" });
    await userEvent.click(button);
    expect(button).toBeDisabled();
    expect(screen.getByTestId("status")).toHaveTextContent(
      "activating",
    );

    await act(async () => {
      await screen.getByRole("button", { name: "activate" }).click();
      pending.resolve(
        adaptActivationSnapshot(mockActivationResponse, "mock"),
      );
      await pending.promise;
    });

    await waitFor(() =>
      expect(screen.getByTestId("status")).toHaveTextContent("ready"),
    );
    expect(activate).toHaveBeenCalledTimes(1);
    expect(activate.mock.calls[0]?.[0].requestId).toBe(
      "activation-test-1",
    );
    expect(screen.getByTestId("event")).not.toHaveTextContent("none");
  });

  it("coalesces simultaneous triggers into one write request", async () => {
    const pending = deferred<
      ReturnType<typeof adaptActivationSnapshot>
    >();
    const activate = vi.fn(
      (_command: ActivationCommand) => pending.promise,
    );
    const source: ActivationDataSource = {
      source: "mock",
      activate,
      getEvent: vi.fn(),
    };
    const user = userEvent.setup();

    render(
      <ActivationProvider
        dataSource={source}
        requestIdFactory={() => "activation-double-trigger"}
      >
        <MultiTriggerProbe />
      </ActivationProvider>,
    );

    await user.click(
      screen.getByRole("button", { name: "activate one" }),
    );
    await user.click(
      screen.getByRole("button", { name: "activate two" }),
    );
    expect(activate).toHaveBeenCalledTimes(1);

    pending.resolve(
      adaptActivationSnapshot(mockActivationResponse, "mock"),
    );
    await waitFor(() =>
      expect(screen.getByTestId("multi-status")).toHaveTextContent(
        "ready",
      ),
    );
  });

  it("recovers a partial failure by reading the persisted event", async () => {
    const snapshot = adaptActivationSnapshot(
      mockActivationResponse,
      "mock",
    );
    const activate = vi.fn().mockRejectedValue(
      new ActivationError({
        code: "rejected",
        source: "mock",
        message: "Provider unavailable.",
        status: 503,
        eventId: snapshot.eventId,
      }),
    );
    const getEvent = vi.fn().mockResolvedValue(snapshot);
    const source: ActivationDataSource = {
      source: "mock",
      activate,
      getEvent,
    };
    const user = userEvent.setup();

    render(
      <ActivationProvider
        dataSource={source}
        requestIdFactory={() => "activation-partial-failure"}
      >
        <MultiTriggerProbe />
      </ActivationProvider>,
    );

    await user.click(
      screen.getByRole("button", { name: "activate one" }),
    );
    await waitFor(() =>
      expect(screen.getByTestId("multi-status")).toHaveTextContent(
        "error",
      ),
    );
    await user.click(screen.getByRole("button", { name: "retry" }));

    await waitFor(() =>
      expect(screen.getByTestId("multi-status")).toHaveTextContent(
        "ready",
      ),
    );
    expect(activate).toHaveBeenCalledTimes(1);
    expect(getEvent).toHaveBeenCalledTimes(1);
    expect(getEvent).toHaveBeenCalledWith(
      snapshot.eventId,
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
  });
});
