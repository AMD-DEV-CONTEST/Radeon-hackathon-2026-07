import type {
  BookIdentity,
  BookSummary,
  DiscoveryCandidate,
  DirectorPreview,
  DirectionSummary,
  VideoJob,
} from "../api/shiduClient";

export type FailureStage = "discovery" | "selection" | "catalog" | "preview" | "submit" | "poll" | "feedback";

export type ShiduState =
  | { name: "input" }
  | { name: "discovering"; title: string }
  | { name: "candidates"; resolutionId: string; candidates: DiscoveryCandidate[] }
  | { name: "unresolved"; resolutionId: string }
  | { name: "selecting"; resolutionId: string; candidate: DiscoveryCandidate }
  | { name: "catalog_loading"; book: BookIdentity; researchJobId: string }
  | { name: "researching"; book: BookSummary; researchJobId: string }
  | { name: "insufficient"; book: BookSummary }
  | { name: "directions"; book: BookSummary }
  | { name: "moment"; book: BookSummary; direction: DirectionSummary }
  | { name: "previewing"; book: BookSummary; direction: DirectionSummary }
  | { name: "preview"; book: BookSummary; direction: DirectionSummary; preview: DirectorPreview }
  | { name: "submitting"; book: BookSummary; direction: DirectionSummary; preview: DirectorPreview }
  | {
      name: "job";
      bookId: string;
      directionId: string;
      job: VideoJob;
      polling: boolean;
      book?: BookSummary;
      direction?: DirectionSummary;
      preview?: DirectorPreview;
    }
  | {
      name: "next";
      bookId: string;
      directionId: string;
      job: VideoJob;
      book?: BookSummary;
      direction?: DirectionSummary;
      preview?: DirectorPreview;
    }
  | {
      name: "feedback_submitting";
      bookId: string;
      directionId: string;
      job: VideoJob;
      book?: BookSummary;
    }
  | { name: "feedback_done"; feedbackId: string; job: VideoJob; book?: BookSummary }
  | { name: "error"; message: string; retryable: boolean; stage: FailureStage };

export type ShiduEvent =
  | { type: "RESET" }
  | { type: "DISCOVERY_STARTED"; title: string }
  | { type: "DISCOVERY_COMPLETED"; resolutionId: string; candidates: DiscoveryCandidate[] }
  | { type: "SELECTION_STARTED"; candidateId: string }
  | { type: "SELECTION_COMPLETED"; book: BookIdentity; researchJobId: string }
  | { type: "RESEARCH_RESTARTED"; book: BookSummary; researchJobId: string }
  | { type: "CATALOG_PROJECTED"; book: BookSummary }
  | { type: "DIRECTION_SELECTED"; directionId: string }
  | { type: "MOMENT_OPENED"; book: BookSummary; direction: DirectionSummary }
  | { type: "PREVIEW_STARTED"; direction: DirectionSummary }
  | { type: "PREVIEW_READY"; preview: DirectorPreview }
  | { type: "SUBMIT_STARTED" }
  | {
      type: "JOB_ACCEPTED";
      bookId: string;
      directionId: string;
      job: VideoJob;
      book?: BookSummary;
      direction?: DirectionSummary;
      preview?: DirectorPreview;
    }
  | { type: "JOB_PROJECTED"; job: VideoJob }
  | { type: "NEXT_OPENED" }
  | { type: "PLAYER_RETURNED" }
  | { type: "FEEDBACK_STARTED" }
  | { type: "FEEDBACK_ACCEPTED"; feedbackId: string }
  | { type: "FAILED"; message: string; retryable: boolean; stage: FailureStage };

export const initialState: ShiduState = { name: "input" };

export function isPollingStatus(status: VideoJob["status"]): boolean {
  return ["queued", "researching", "scripting", "rendering", "voicing", "composing"].includes(status);
}

export function transition(state: ShiduState, event: ShiduEvent): ShiduState {
  switch (event.type) {
    case "RESET":
      return initialState;
    case "DISCOVERY_STARTED":
      return { name: "discovering", title: event.title };
    case "DISCOVERY_COMPLETED":
      return event.candidates.length === 0
        ? { name: "unresolved", resolutionId: event.resolutionId }
        : { name: "candidates", resolutionId: event.resolutionId, candidates: event.candidates };
    case "SELECTION_STARTED": {
      if (state.name !== "candidates") return state;
      const candidate = state.candidates.find((item) => item.candidateId === event.candidateId);
      return candidate
        ? { name: "selecting", resolutionId: state.resolutionId, candidate }
        : state;
    }
    case "SELECTION_COMPLETED":
      return state.name === "selecting"
        ? { name: "catalog_loading", book: event.book, researchJobId: event.researchJobId }
        : state;
    case "RESEARCH_RESTARTED":
      return {
        name: "researching",
        book: {
          ...event.book,
          researchStatus: "queued",
          directions: [],
        },
        researchJobId: event.researchJobId,
      };
    case "CATALOG_PROJECTED":
      if (event.book.researchStatus === "insufficient" || event.book.researchStatus === "failed") {
        return { name: "insufficient", book: event.book };
      }
      if (event.book.researchStatus !== "ready") {
        const researchJobId = state.name === "catalog_loading" || state.name === "researching"
          ? state.researchJobId
          : "";
        return { name: "researching", book: event.book, researchJobId };
      }
      if (event.book.directions.length === 0) return { name: "insufficient", book: event.book };
      return { name: "directions", book: event.book };
    case "DIRECTION_SELECTED":
      if (state.name !== "directions") return state;
      {
        const direction = state.book.directions.find((item) => item.id === event.directionId);
        return direction ? { name: "moment", book: state.book, direction } : state;
      }
    case "MOMENT_OPENED":
      return { name: "moment", book: event.book, direction: event.direction };
    case "PREVIEW_STARTED":
      return state.name === "moment"
        ? { name: "previewing", book: state.book, direction: event.direction }
        : state;
    case "PREVIEW_READY":
      return state.name === "previewing"
        ? { name: "preview", book: state.book, direction: state.direction, preview: event.preview }
        : state;
    case "SUBMIT_STARTED":
      return state.name === "preview"
        ? { name: "submitting", book: state.book, direction: state.direction, preview: state.preview }
        : state;
    case "JOB_ACCEPTED":
      return {
        name: "job",
        bookId: event.bookId,
        directionId: event.directionId,
        job: event.job,
        polling: isPollingStatus(event.job.status),
        book: event.book,
        direction: event.direction,
        preview: event.preview,
      };
    case "JOB_PROJECTED":
      return state.name === "job"
        ? { ...state, job: event.job, polling: isPollingStatus(event.job.status) }
        : state;
    case "NEXT_OPENED":
      return state.name === "job" && state.job.status === "succeeded"
        ? {
            name: "next",
            bookId: state.bookId,
            directionId: state.directionId,
            job: state.job,
            book: state.book,
            direction: state.direction,
            preview: state.preview,
          }
        : state;
    case "PLAYER_RETURNED":
      return state.name === "next"
        ? {
            name: "job",
            bookId: state.bookId,
            directionId: state.directionId,
            job: state.job,
            polling: false,
            book: state.book,
            direction: state.direction,
            preview: state.preview,
          }
        : state;
    case "FEEDBACK_STARTED":
      return state.name === "job" && state.job.status === "succeeded"
        ? {
            name: "feedback_submitting",
            bookId: state.bookId,
            directionId: state.directionId,
            job: state.job,
            book: state.book,
          }
        : state;
    case "FEEDBACK_ACCEPTED":
      return state.name === "feedback_submitting"
        ? { name: "feedback_done", feedbackId: event.feedbackId, job: state.job, book: state.book }
        : state;
    case "FAILED":
      return { name: "error", message: event.message, retryable: event.retryable, stage: event.stage };
  }
}
