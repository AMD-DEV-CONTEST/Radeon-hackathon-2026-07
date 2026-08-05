import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { LearningStudioPanel } from "../LearningStudioPanel";

const invokeMock = vi.fn();

vi.mock("@/lib/ide-product-shell-api", async (importOriginal) => {
  const actual = await importOriginal<any>();
  return {
    ...actual,
    invokeUnifiedProductCommand: (...args: unknown[]) => invokeMock(...args),
  };
});

describe("LearningStudioPanel corpus consult section", () => {
  beforeEach(() => {
    invokeMock.mockReset();
    invokeMock.mockImplementation(async (command: string) => {
      if (command === "get_learning_studio_workflow_state") {
        return {
          command,
          status: "TAURI_COMMAND_OK",
          payload: { modes: [] },
          source_mutation_authorized: false,
          training_eligible: false,
          notes: [],
        };
      }
      return {
        command,
        status: "TAURI_COMMAND_OK",
        payload: {},
        source_mutation_authorized: false,
        training_eligible: false,
        notes: [],
      };
    });
  });

  it("defaults to Ask mode and calls query_corpus with corpus_mode='ask'", async () => {
    invokeMock.mockImplementation(async (command: string) => {
      if (command === "query_corpus") {
        return {
          command,
          status: "TAURI_COMMAND_OK",
          payload: {
            mode: "ask",
            hits: [{ source: "entry", key: "k1", title: "K1", snippet: "s1", score: 2 }],
            warnings: [],
          },
          source_mutation_authorized: false,
          training_eligible: false,
          notes: [],
        };
      }
      return {
        command,
        status: "TAURI_COMMAND_OK",
        payload: {},
        source_mutation_authorized: false,
        training_eligible: false,
        notes: [],
      };
    });

    render(<LearningStudioPanel />);
    fireEvent.change(screen.getByTestId("learning-studio-ask-corpus-input"), {
      target: { value: "what is missing" },
    });
    fireEvent.click(screen.getByTestId("learning-studio-ask-corpus-button"));

    await waitFor(() => {
      expect(invokeMock).toHaveBeenCalledWith("query_corpus", {
        query: "what is missing",
        mode: "ask",
      });
    });
    await waitFor(() => {
      expect(screen.getByTestId("learning-studio-ask-corpus-hit-k1")).toBeInTheDocument();
    });
  });

  it("switches to 'What's missing?' mode and calls query_corpus with corpus_mode='maturity'", async () => {
    invokeMock.mockImplementation(async (command: string) => {
      if (command === "query_corpus") {
        return {
          command,
          status: "TAURI_COMMAND_OK",
          payload: {
            mode: "maturity",
            stats: {
              total_top_level_entries: 112,
              learned_class_verified_count: 0,
              quarantined_count: 3,
            },
            flywheel_is_empty: true,
            open_items: [
              {
                key: "hackathon_lever_map",
                marker: "NOT YET BUILT",
                topic: "HACKATHON_CAMPAIGN",
                snippet: "some gap description",
              },
            ],
            weak_open_items: [],
          },
          source_mutation_authorized: false,
          training_eligible: false,
          notes: [],
        };
      }
      return {
        command,
        status: "TAURI_COMMAND_OK",
        payload: {},
        source_mutation_authorized: false,
        training_eligible: false,
        notes: [],
      };
    });

    render(<LearningStudioPanel />);
    fireEvent.click(screen.getByTestId("learning-studio-corpus-mode-maturity"));
    // Ask-mode input should no longer be present.
    expect(screen.queryByTestId("learning-studio-ask-corpus-input")).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId("learning-studio-corpus-maturity-button"));

    await waitFor(() => {
      expect(invokeMock).toHaveBeenCalledWith("query_corpus", {
        query: "",
        mode: "maturity",
      });
    });
    await waitFor(() => {
      expect(
        screen.getByTestId("learning-studio-corpus-maturity-item-hackathon_lever_map")
      ).toBeInTheDocument();
    });
    expect(screen.getByTestId("learning-studio-corpus-maturity-stats")).toHaveTextContent(
      "112 corpus entries"
    );
    expect(screen.getByTestId("learning-studio-corpus-maturity-stats")).toHaveTextContent(
      "flywheel is EMPTY"
    );
  });

  it("shows an honest 'no open items' message rather than implying everything is done", async () => {
    invokeMock.mockImplementation(async (command: string) => {
      if (command === "query_corpus") {
        return {
          command,
          status: "TAURI_COMMAND_OK",
          payload: {
            mode: "maturity",
            stats: {
              total_top_level_entries: 5,
              learned_class_verified_count: 0,
              quarantined_count: 0,
            },
            flywheel_is_empty: true,
            open_items: [],
            weak_open_items: [],
          },
          source_mutation_authorized: false,
          training_eligible: false,
          notes: [],
        };
      }
      return {
        command,
        status: "TAURI_COMMAND_OK",
        payload: {},
        source_mutation_authorized: false,
        training_eligible: false,
        notes: [],
      };
    });

    render(<LearningStudioPanel />);
    fireEvent.click(screen.getByTestId("learning-studio-corpus-mode-maturity"));
    fireEvent.click(screen.getByTestId("learning-studio-corpus-maturity-button"));

    await waitFor(() => {
      expect(screen.getByTestId("learning-studio-corpus-maturity-no-open-items")).toHaveTextContent(
        /does NOT mean everything/i
      );
    });
  });
});
