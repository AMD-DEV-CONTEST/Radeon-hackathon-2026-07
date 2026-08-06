import {
  act,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { mockDigitalEmployeeCollection } from "../mock/mockDigitalEmployees";
import {
  DigitalEmployeeProvider,
} from "./DigitalEmployeeProvider";
import { useDigitalEmployee } from "./useDigitalEmployee";
import { useDigitalEmployees } from "./useDigitalEmployees";
import {
  DigitalEmployeeReadError,
  type DigitalEmployeeCollection,
  type DigitalEmployeeDataSource,
} from "../types";

function taggedCollection(
  tag: string,
  source: DigitalEmployeeCollection["source"] = "mock",
): DigitalEmployeeCollection {
  const first = mockDigitalEmployeeCollection.employees[0];
  if (!first) {
    throw new Error("Expected the deterministic employee fixture.");
  }

  return {
    ...mockDigitalEmployeeCollection,
    source,
    observedAt: tag,
    employees: [
      {
        ...first,
        id: `employee-${tag}`,
        name: { kind: "literal", value: `Employee ${tag}` },
      },
    ],
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

function dataSource({
  source = "mock",
  initial,
  read,
}: {
  source?: DigitalEmployeeDataSource["source"];
  initial: DigitalEmployeeCollection | null;
  read: DigitalEmployeeDataSource["getEmployees"];
}): DigitalEmployeeDataSource {
  return {
    source,
    getInitialCollection: () => initial,
    getEmployees: read,
  };
}

function EmployeeProbe({
  selectedId,
  onRender,
}: {
  selectedId?: string;
  onRender?: (value: string) => void;
}) {
  const collection = useDigitalEmployees();
  const selected = useDigitalEmployee(selectedId);
  const source = collection.collection?.source ?? "none";
  onRender?.(`${collection.source}:${source}`);

  return (
    <div>
      <output data-testid="resource-source">{collection.source}</output>
      <output data-testid="collection-source">{source}</output>
      <output data-testid="status">{collection.status}</output>
      <output data-testid="observed">
        {collection.collection?.observedAt ?? "none"}
      </output>
      <output data-testid="count">{collection.employees.length}</output>
      <output data-testid="first">
        {collection.employees[0]?.id ?? "none"}
      </output>
      <output data-testid="selected">
        {selected.employee?.id ?? "none"}
      </output>
      <output data-testid="error">
        {collection.error?.code ?? "none"}
      </output>
      <button type="button" onClick={collection.refresh}>
        refresh
      </button>
    </div>
  );
}

describe("DigitalEmployeeProvider and hooks", () => {
  it("publishes one collection to list and exact-ID hooks", async () => {
    const collection = mockDigitalEmployeeCollection;
    const source = dataSource({
      initial: collection,
      read: vi.fn().mockResolvedValue(collection),
    });

    render(
      <DigitalEmployeeProvider dataSource={source}>
        <EmployeeProbe selectedId="equipment-maintenance" />
      </DigitalEmployeeProvider>,
    );

    expect(screen.getByTestId("count")).toHaveTextContent("3");
    expect(screen.getByTestId("selected")).toHaveTextContent(
      "equipment-maintenance",
    );
    await waitFor(() =>
      expect(screen.getByTestId("status")).toHaveTextContent("ready"),
    );
    expect(screen.getByTestId("observed")).toHaveTextContent(
      collection.observedAt ?? "",
    );
  });

  it.each([
    "equipment",
    "equipment-maintenance-extra",
    "unknown-employee",
    "",
  ])(
    "returns null for non-exact employee ID %j without falling back",
    (selectedId) => {
      const source = dataSource({
        initial: mockDigitalEmployeeCollection,
        read: vi.fn().mockResolvedValue(mockDigitalEmployeeCollection),
      });

      render(
        <DigitalEmployeeProvider dataSource={source}>
          <EmployeeProbe selectedId={selectedId} />
        </DigitalEmployeeProvider>,
      );

      expect(screen.getByTestId("selected")).toHaveTextContent("none");
    },
  );

  it("turns a synchronous source mismatch into an explicit contract error", async () => {
    const source = dataSource({
      source: "http",
      initial: mockDigitalEmployeeCollection,
      read: vi.fn().mockResolvedValue(mockDigitalEmployeeCollection),
    });

    render(
      <DigitalEmployeeProvider dataSource={source}>
        <EmployeeProbe />
      </DigitalEmployeeProvider>,
    );

    await waitFor(() =>
      expect(screen.getByTestId("status")).toHaveTextContent("error"),
    );
    expect(screen.getByTestId("collection-source")).toHaveTextContent(
      "none",
    );
    expect(screen.getByTestId("error")).toHaveTextContent("contract");
  });

  it("turns an asynchronous source mismatch into an explicit contract error", async () => {
    const source = dataSource({
      source: "http",
      initial: null,
      read: vi.fn().mockResolvedValue(mockDigitalEmployeeCollection),
    });

    render(
      <DigitalEmployeeProvider dataSource={source}>
        <EmployeeProbe />
      </DigitalEmployeeProvider>,
    );

    await waitFor(() =>
      expect(screen.getByTestId("status")).toHaveTextContent("error"),
    );
    expect(screen.getByTestId("collection-source")).toHaveTextContent(
      "none",
    );
    expect(screen.getByTestId("error")).toHaveTextContent("contract");
  });

  it("does not expose the old collection while switching data sources", async () => {
    const renderTrace: string[] = [];
    const mockSource = dataSource({
      initial: taggedCollection("mock-old"),
      read: vi.fn().mockResolvedValue(taggedCollection("mock-old")),
    });
    const httpRead = deferred<DigitalEmployeeCollection>();
    const httpSource = dataSource({
      source: "http",
      initial: null,
      read: () => httpRead.promise,
    });

    const view = render(
      <DigitalEmployeeProvider dataSource={mockSource}>
        <EmployeeProbe
          onRender={(value) => renderTrace.push(value)}
        />
      </DigitalEmployeeProvider>,
    );
    await waitFor(() =>
      expect(screen.getByTestId("status")).toHaveTextContent("ready"),
    );

    view.rerender(
      <DigitalEmployeeProvider dataSource={httpSource}>
        <EmployeeProbe
          onRender={(value) => renderTrace.push(value)}
        />
      </DigitalEmployeeProvider>,
    );

    expect(renderTrace).not.toContain("http:mock");
    expect(screen.getByTestId("collection-source")).toHaveTextContent(
      "none",
    );

    await act(async () => {
      httpRead.resolve(taggedCollection("http-new", "http"));
      await httpRead.promise;
    });
    await waitFor(() =>
      expect(screen.getByTestId("first")).toHaveTextContent(
        "employee-http-new",
      ),
    );
  });

  it("aborts a stale request and ignores its late result", async () => {
    const reads: {
      signal: AbortSignal | undefined;
      result: ReturnType<typeof deferred<DigitalEmployeeCollection>>;
    }[] = [];
    const source = dataSource({
      initial: null,
      read: vi.fn((options) => {
        const result = deferred<DigitalEmployeeCollection>();
        reads.push({ signal: options?.signal, result });
        return result.promise;
      }),
    });

    render(
      <DigitalEmployeeProvider dataSource={source}>
        <EmployeeProbe />
      </DigitalEmployeeProvider>,
    );
    await waitFor(() => expect(reads).toHaveLength(1));

    await userEvent.click(
      screen.getByRole("button", { name: "refresh" }),
    );
    await waitFor(() => expect(reads).toHaveLength(2));
    const first = reads[0];
    const second = reads[1];
    if (!first || !second) {
      throw new Error("Expected two employee reads.");
    }
    expect(first.signal?.aborted).toBe(true);

    await act(async () => {
      second.result.resolve(taggedCollection("newest"));
      await second.result.promise;
    });
    await waitFor(() =>
      expect(screen.getByTestId("observed")).toHaveTextContent(
        "newest",
      ),
    );

    await act(async () => {
      first.result.resolve(taggedCollection("stale"));
      await first.result.promise;
    });
    expect(screen.getByTestId("observed")).toHaveTextContent("newest");
  });

  it("retains last-known data and exposes the refresh error", async () => {
    const lastKnown = taggedCollection("last-known");
    const source = dataSource({
      initial: lastKnown,
      read: vi.fn().mockRejectedValue(
        new DigitalEmployeeReadError(
          "transport",
          "mock",
          "Disconnected",
        ),
      ),
    });

    render(
      <DigitalEmployeeProvider dataSource={source}>
        <EmployeeProbe />
      </DigitalEmployeeProvider>,
    );

    await waitFor(() =>
      expect(screen.getByTestId("status")).toHaveTextContent("error"),
    );
    expect(screen.getByTestId("observed")).toHaveTextContent(
      "last-known",
    );
    expect(screen.getByTestId("first")).toHaveTextContent(
      "employee-last-known",
    );
    expect(screen.getByTestId("error")).toHaveTextContent("transport");
  });
});
