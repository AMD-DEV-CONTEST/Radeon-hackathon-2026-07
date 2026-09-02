import { FormEvent, useCallback, useEffect, useReducer, useRef, useState } from "react";

import {
  ShiduApiError,
  STEVE_JOBS_IMPORTED_REFERENCE_SHA256,
  createShiduClient,
  isActiveResearchStatus,
  type BookIdentity,
  type BookSummary,
  type DiscoveryCandidate,
  type DirectionSummary,
  type FeedbackInput,
  type ResonanceOption,
  type SelectCandidateResult,
  type ShiduClient,
  type VideoJob,
} from "../api/shiduClient";
import { initialState, isPollingStatus, transition, type FailureStage } from "./shiduMachine";

const JOB_LABELS: Record<VideoJob["status"], string> = {
  queued: "Waiting to begin",
  researching: "Verifying sources",
  scripting: "Shaping the story",
  rendering: "Creating the film",
  voicing: "Adding native audio",
  composing: "Finishing the cut",
  succeeded: "Preview ready",
  failed: "Generation stopped",
};

const ACTIVE_STEPS: Array<{ status: VideoJob["status"]; label: string }> = [
  { status: "researching", label: "Verify sources" },
  { status: "scripting", label: "Shape the story" },
  { status: "rendering", label: "Create the film" },
  { status: "voicing", label: "Add native audio" },
  { status: "composing", label: "Finish the cut" },
];

const SHOWCASE_LABEL = "Previously generated on AMD";

export interface ShowcaseEntryViewModel {
  id: string;
  title: string;
  mediaUrl: string;
  label: typeof SHOWCASE_LABEL;
}

export interface ShowcasePersonViewModel {
  id: string;
  name: string;
  entries: ShowcaseEntryViewModel[];
}

interface ShowcaseSelection {
  person: ShowcasePersonViewModel;
  entry: ShowcaseEntryViewModel;
}

function directionTitle(direction: DirectionSummary): string {
  const title = direction.payload.title;
  if (typeof title === "string" && title.trim()) {
    const normalized = title.trim();
    return normalized.length > 48 ? `${normalized.slice(0, 48)}…` : normalized;
  }
  return `Moment ${direction.momentNumber ?? direction.directionKey.slice(0, 8)}`;
}

function directionDetail(direction: DirectionSummary): string {
  const firstPerson = direction.payload.first_person_entry;
  if (firstPerson && typeof firstPerson === "object" && "text" in firstPerson) {
    const text = (firstPerson as { text?: unknown }).text;
    if (typeof text === "string") return text;
  }
  const spoiler = direction.payload.spoiler_level;
  return typeof spoiler === "string" ? `Spoiler level: ${spoiler}` : `Resonance score ${direction.score.toFixed(2)}`;
}

function momentSummary(direction: DirectionSummary): string {
  return direction.summary?.trim() || directionDetail(direction);
}

function momentKeywords(direction: DirectionSummary): string[] {
  if (direction.keywords?.length) return direction.keywords.slice(0, 3);
  return [directionTitle(direction)];
}

function momentOptions(direction?: DirectionSummary): ResonanceOption[] {
  if (direction?.resonanceOptions?.length === 3) return direction.resonanceOptions;
  return [
    { id: "resonance-1", text: direction ? directionDetail(direction) : "I heard the choice this person had to make" },
    { id: "resonance-2", text: "I care most about what caused the turning point" },
    { id: "resonance-3", text: "I want to carry my own experience into the story" },
  ];
}

function candidateMetadata(candidate: DiscoveryCandidate): string[] {
  return [
    candidate.author ? `Author: ${candidate.author}` : "",
    candidate.language ? `Language: ${candidate.language}` : "",
    candidate.edition ? `Edition: ${candidate.edition}` : "",
    candidate.translator ? `Translator: ${candidate.translator}` : "",
  ].filter(Boolean);
}

function candidateSelectionLabel(candidate: DiscoveryCandidate): string {
  return [`Choose ${candidate.title}`, ...candidateMetadata(candidate)].join(", ");
}

export interface CharacterReferenceViewModel {
  referenceProfile: "competition-imported-single-view-v1";
  sourceMode: "preuploaded_imported";
  requiredImages: 1;
  status: "prepared";
  label: "Prepared reference asset";
  disclosureLabel: "Preuploaded imported asset";
  requestId: string;
  characterName: string;
  importAuthoritySha256: string;
  fluxProofPromptSha256: string;
  fluxProofSeed: number;
  fluxProofTemplateWorkflowSha256: string;
  reference: {
    artifactRef: string;
    imageUrl: string;
    sha256: string;
    viewName: "front_three_quarter";
    mimeType: "image/png" | "image/jpeg" | "image/webp";
    width: number;
    height: number;
    importedBeforeUserClick: true;
    generatedByCurrentFlux: false;
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function characterReferenceFromPreview(preview: unknown): CharacterReferenceViewModel | null {
  if (!isRecord(preview) || !isRecord(preview.characterReference)) return null;
  const model = preview.characterReference;
  if (
    model.referenceProfile !== "competition-imported-single-view-v1"
    || model.sourceMode !== "preuploaded_imported"
    || model.requiredImages !== 1
    || model.status !== "prepared"
    || model.label !== "Prepared reference asset"
    || model.disclosureLabel !== "Preuploaded imported asset"
    || typeof model.requestId !== "string"
    || !/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(model.requestId)
    || !["Steve Jobs", "史蒂夫·乔布斯"].includes(String(model.characterName))
    || typeof model.importAuthoritySha256 !== "string"
    || !/^[0-9a-f]{64}$/.test(model.importAuthoritySha256)
    || typeof model.fluxProofPromptSha256 !== "string"
    || !/^[0-9a-f]{64}$/.test(model.fluxProofPromptSha256)
    || !Number.isSafeInteger(model.fluxProofSeed)
    || typeof model.fluxProofTemplateWorkflowSha256 !== "string"
    || !/^[0-9a-f]{64}$/.test(model.fluxProofTemplateWorkflowSha256)
    || !isRecord(model.reference)
  ) return null;

  const reference = model.reference;
  if (
    reference.artifactRef !== `prepared-reference:${model.requestId}`
    || typeof reference.imageUrl !== "string"
    || reference.imageUrl !== `/api/prepared-reference-assets/${model.requestId}/image`
    || reference.sha256 !== STEVE_JOBS_IMPORTED_REFERENCE_SHA256
    || reference.viewName !== "front_three_quarter"
    || !["image/png", "image/jpeg", "image/webp"].includes(String(reference.mimeType))
    || !Number.isSafeInteger(reference.width)
    || Number(reference.width) <= 0
    || !Number.isSafeInteger(reference.height)
    || Number(reference.height) <= 0
    || reference.importedBeforeUserClick !== true
    || reference.generatedByCurrentFlux !== false
  ) return null;

  return model as unknown as CharacterReferenceViewModel;
}

function CharacterReference({ preview }: { preview: unknown }) {
  const model = characterReferenceFromPreview(preview);
  if (!model) return null;
  const { reference } = model;
  return (
    <figure
      className="shidu-character-reference"
      data-reference-profile={model.referenceProfile}
      data-source-mode={model.sourceMode}
      data-view-name={reference.viewName}
    >
      <div className="shidu-character-reference-frame">
        <img
          src={reference.imageUrl}
          alt="Prepared preuploaded Steve Jobs reference asset"
          width={reference.width}
          height={reference.height}
          decoding="async"
        />
      </div>
      <figcaption>
        <span>Prepared reference asset</span>
        <small>Preuploaded imported asset · not this run&apos;s FLUX output</small>
      </figcaption>
    </figure>
  );
}

function showcasePayload(value: unknown): ShowcasePersonViewModel[] {
  if (!isRecord(value) || !Array.isArray(value.people)) throw new Error("Invalid Showcase response");
  const personIds = new Set<string>();
  const entryIds = new Set<string>();
  const mediaUrls = new Set<string>();
  const safeId = /^[A-Za-z0-9_-]+$/;

  return value.people.map((person): ShowcasePersonViewModel => {
    if (
      !isRecord(person)
      || typeof person.id !== "string"
      || !safeId.test(person.id)
      || personIds.has(person.id)
      || typeof person.name !== "string"
      || !person.name.trim()
      || !Array.isArray(person.entries)
    ) throw new Error("Invalid Showcase person");
    personIds.add(person.id);

    const entries = person.entries.map((entry): ShowcaseEntryViewModel => {
      if (
        !isRecord(entry)
        || typeof entry.id !== "string"
        || !safeId.test(entry.id)
        || entryIds.has(entry.id)
        || typeof entry.title !== "string"
        || !entry.title.trim()
        || typeof entry.mediaUrl !== "string"
        || !/^\/api\/showcase-media\/[A-Za-z0-9_-]+$/.test(entry.mediaUrl)
        || mediaUrls.has(entry.mediaUrl)
        || entry.label !== SHOWCASE_LABEL
      ) throw new Error("Invalid Showcase entry");
      entryIds.add(entry.id);
      mediaUrls.add(entry.mediaUrl);
      return {
        id: entry.id,
        title: entry.title.trim(),
        mediaUrl: entry.mediaUrl,
        label: SHOWCASE_LABEL,
      };
    });

    return { id: person.id, name: person.name.trim(), entries };
  });
}

async function loadShowcase(signal: AbortSignal): Promise<ShowcasePersonViewModel[]> {
  const response = await fetch("/api/showcase", {
    signal,
    headers: { Accept: "application/json" },
  });
  if (!response.ok) throw new Error("Showcase is unavailable");
  return showcasePayload(await response.json());
}

function errorDetails(error: unknown): { message: string; retryable: boolean } {
  if (error instanceof ShiduApiError) return { message: error.message, retryable: error.retryable };
  return { message: "Something interrupted the connection. Please try again.", retryable: true };
}

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

function isAiCompleted(
  job: VideoJob,
  preview?: { contentMode: "source_grounded" | "ai_completed" },
  book?: BookSummary,
): boolean {
  return (job.contentMode ?? preview?.contentMode ?? book?.contentMode) === "ai_completed";
}

function AiCompletionDisclosure({
  job,
  preview,
  book,
}: {
  job: VideoJob;
  preview?: { contentMode: "source_grounded" | "ai_completed"; contentNotice: string };
  book?: BookSummary;
}) {
  if (!isAiCompleted(job, preview, book)) return null;
  return (
    <aside className="shidu-opening shidu-ai-disclosure" role="note" aria-label="AI content disclosure">
      <span>AI-completed content, not original text</span>
      <p>{job.contentNotice ?? preview?.contentNotice ?? "No verifiable original text was found. AI completed this story from available bibliographic sources and may be inaccurate."}</p>
    </aside>
  );
}

interface Props {
  client?: ShiduClient;
  pollIntervalMs?: number;
}

export function ShiduApp({ client: providedClient, pollIntervalMs = 3000 }: Props) {
  const defaultClientRef = useRef<ShiduClient | null>(null);
  const client = providedClient ?? (defaultClientRef.current ??= createShiduClient());
  const [state, dispatch] = useReducer(transition, initialState);
  const [shelfBooks, setShelfBooks] = useState<BookSummary[]>([]);
  const [shelfStatus, setShelfStatus] = useState<"loading" | "ready" | "failed">("loading");
  const [showcasePeople, setShowcasePeople] = useState<ShowcasePersonViewModel[]>([]);
  const [showcaseStatus, setShowcaseStatus] = useState<"loading" | "ready" | "failed">("loading");
  const [showcaseSelection, setShowcaseSelection] = useState<ShowcaseSelection | null>(null);
  const [showcasePlaybackFailed, setShowcasePlaybackFailed] = useState(false);
  const [input, setInput] = useState("");
  const [customQuestion, setCustomQuestion] = useState("");
  const [resonanceText, setResonanceText] = useState("");
  const [resonanceOptionId, setResonanceOptionId] = useState("");
  const [comment, setComment] = useState("");
  const [wantsToRead, setWantsToRead] = useState(false);
  const [spoilerJudgment, setSpoilerJudgment] = useState<FeedbackInput["spoilerJudgment"]>("acceptable");
  const commandController = useRef<AbortController | null>(null);
  const retry = useRef<(() => void) | null>(null);
  const stateRef = useRef(state);
  const videoRef = useRef<HTMLVideoElement | null>(null);

  useEffect(() => {
    stateRef.current = state;
  }, [state]);

  const fail = useCallback((error: unknown, stage: FailureStage) => {
    if (isAbort(error)) return;
    const details = errorDetails(error);
    dispatch({ type: "FAILED", stage, ...details });
  }, []);

  const beginCommand = useCallback(() => {
    commandController.current?.abort();
    const controller = new AbortController();
    commandController.current = controller;
    return controller;
  }, []);

  useEffect(() => () => commandController.current?.abort(), []);

  useEffect(() => {
    const controller = new AbortController();
    void client.listShelf(controller.signal).then((result) => {
      setShelfBooks(result.books);
      setShelfStatus("ready");
    }).catch((error) => {
      if (!isAbort(error)) setShelfStatus("failed");
    });
    return () => controller.abort();
  }, [client]);

  useEffect(() => {
    const controller = new AbortController();
    void loadShowcase(controller.signal).then((people) => {
      setShowcasePeople(people);
      setShowcaseStatus("ready");
    }).catch((error) => {
      if (!isAbort(error)) setShowcaseStatus("failed");
    });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const onShowcasePopState = () => {
      if (!window.location.pathname.startsWith("/showcase/")) {
        setShowcaseSelection(null);
        setShowcasePlaybackFailed(false);
      }
    };
    window.addEventListener("popstate", onShowcasePopState);
    return () => window.removeEventListener("popstate", onShowcasePopState);
  }, []);

  useEffect(() => {
    const onPopState = () => {
      const current = stateRef.current;
      if (window.location.pathname === "/next" && current.name === "job" && current.job.status === "succeeded") {
        dispatch({ type: "NEXT_OPENED" });
      } else if (current.name === "next" && window.location.pathname !== "/next") {
        dispatch({ type: "PLAYER_RETURNED" });
      }
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  const resolveInput = useCallback(async () => {
    const value = input.trim();
    if (!value) return;
    retry.current = () => void resolveInput();
    const controller = beginCommand();
    dispatch({ type: "DISCOVERY_STARTED", title: value });
    try {
      const result = await client.resolveInput(value, controller.signal);
      dispatch({
        type: "DISCOVERY_COMPLETED",
        resolutionId: result.resolutionId,
        candidates: result.candidates,
      });
    } catch (error) {
      fail(error, "discovery");
    }
  }, [beginCommand, client, fail, input]);

  const loadCatalog = useCallback(async (identity: BookIdentity) => {
    retry.current = () => void loadCatalog(identity);
    const controller = beginCommand();
    try {
      const result = await client.listBooks(controller.signal);
      const book = result.books.find((candidate) => candidate.id === identity.id);
      if (!book) throw new ShiduApiError(404, { error_code: "not_found", message: "This book is not available yet", retryable: true });
      dispatch({ type: "CATALOG_PROJECTED", book });
    } catch (error) {
      fail(error, "catalog");
    }
  }, [beginCommand, client, fail]);

  const selectCandidate = useCallback(async (
    resolutionId: string,
    candidate: DiscoveryCandidate,
  ) => {
    retry.current = () => void selectCandidate(resolutionId, candidate);
    const controller = beginCommand();
    dispatch({ type: "SELECTION_STARTED", candidateId: candidate.candidateId });
    let selected: SelectCandidateResult;
    try {
      selected = await client.selectCandidate(
        resolutionId,
        candidate.candidateId,
        controller.signal,
      );
      dispatch({
        type: "SELECTION_COMPLETED",
        book: selected.book,
        researchJobId: selected.researchJobId,
      });
    } catch (error) {
      fail(error, "selection");
      return;
    }
    retry.current = () => void loadCatalog(selected.book);
    try {
      const result = await client.listBooks(controller.signal);
      const book = result.books.find((item) => item.id === selected.book.id);
      if (!book) throw new ShiduApiError(404, {
        error_code: "not_found",
        message: "This book is not available yet",
        retryable: true,
      });
      dispatch({ type: "CATALOG_PROJECTED", book });
    } catch (error) {
      fail(error, "catalog");
    }
  }, [beginCommand, client, fail, loadCatalog]);

  const restartResearch = useCallback(async (book: BookSummary) => {
    retry.current = () => void restartResearch(book);
    const controller = beginCommand();
    try {
      const result = await client.retryResearch(book.id, controller.signal);
      dispatch({
        type: "RESEARCH_RESTARTED",
        book,
        researchJobId: result.researchJobId,
      });
    } catch (error) {
      fail(error, "catalog");
    }
  }, [beginCommand, client, fail]);

  const researchBook = state.name === "researching" ? state.book : null;
  useEffect(() => {
    if (!researchBook || !isActiveResearchStatus(researchBook.researchStatus)) return;
    let active = true;
    let timer: number | undefined;
    const controller = new AbortController();
    const poll = async () => {
      try {
        const result = await client.listBooks(controller.signal);
        const book = result.books.find((candidate) => candidate.id === researchBook.id);
        if (!book) throw new Error("book projection disappeared");
        if (!active) return;
        dispatch({ type: "CATALOG_PROJECTED", book });
        if (isActiveResearchStatus(book.researchStatus)) {
          timer = window.setTimeout(() => void poll(), pollIntervalMs);
        }
      } catch (error) {
        if (active) fail(error, "catalog");
      }
    };
    timer = window.setTimeout(() => void poll(), pollIntervalMs);
    return () => {
      active = false;
      if (timer !== undefined) window.clearTimeout(timer);
      controller.abort();
    };
  }, [client, fail, pollIntervalMs, researchBook?.id, researchBook?.researchStatus, researchBook?.title]);

  const requestPreview = useCallback(async (book: BookSummary, direction: DirectionSummary) => {
    retry.current = () => void requestPreview(book, direction);
    const controller = beginCommand();
    dispatch({ type: "PREVIEW_STARTED", direction });
    try {
      const preview = await client.directorPreview(
        {
          bookId: book.id,
          directionRevisionId: direction.id,
          ...(customQuestion.trim() ? { customQuestion: customQuestion.trim() } : {}),
        },
        controller.signal,
      );
      dispatch({ type: "PREVIEW_READY", preview });
    } catch (error) {
      fail(error, "preview");
    }
  }, [beginCommand, client, customQuestion, fail]);

  const createJob = useCallback(async () => {
    if (state.name !== "preview") return;
    const context = state;
    retry.current = () => void createJob();
    const controller = beginCommand();
    dispatch({ type: "SUBMIT_STARTED" });
    try {
      const job = await client.createVideoJob(
        {
          bookId: context.book.id,
          directionRevisionId: context.direction.id,
          trialScriptRevisionId: context.preview.scriptRevisionId,
        },
        controller.signal,
      );
      dispatch({
        type: "JOB_ACCEPTED",
        bookId: context.book.id,
        directionId: context.direction.id,
        job,
        book: context.book,
        direction: context.direction,
        preview: context.preview,
      });
    } catch (error) {
      fail(error, "submit");
    }
  }, [beginCommand, client, fail, state]);

  const pollingJob = state.name === "job" ? state : null;
  useEffect(() => {
    if (!pollingJob?.polling) return;
    const context = pollingJob;
    retry.current = () => dispatch({
      type: "JOB_ACCEPTED",
      bookId: context.bookId,
      directionId: context.directionId,
      job: context.job,
      book: context.book,
      direction: context.direction,
      preview: context.preview,
    });
    let active = true;
    let timer: number | undefined;
    const controller = new AbortController();
    const poll = async () => {
      try {
        const projection = await client.getVideoJob(pollingJob.job.jobId, controller.signal);
        if (!active) return;
        dispatch({ type: "JOB_PROJECTED", job: projection });
        if (isPollingStatus(projection.status)) {
          timer = window.setTimeout(() => void poll(), pollIntervalMs);
        }
      } catch (error) {
        if (active) fail(error, "poll");
      }
    };
    void poll();
    return () => {
      active = false;
      if (timer !== undefined) window.clearTimeout(timer);
      controller.abort();
    };
  }, [client, fail, pollIntervalMs, pollingJob?.job.jobId, pollingJob?.polling]);

  const sendFeedback = useCallback(async () => {
    if (state.name !== "job" || state.job.status !== "succeeded" || !resonanceText.trim()) return;
    const context = state;
    retry.current = () => void sendFeedback();
    const controller = beginCommand();
    dispatch({ type: "FEEDBACK_STARTED" });
    try {
      const result = await client.sendFeedback(
        {
          bookId: context.bookId,
          directionRevisionId: context.directionId,
          resonanceText: resonanceText.trim(),
          jobId: context.job.jobId,
          momentRevisionId: context.directionId,
          ...(resonanceOptionId ? { resonanceOptionId } : {}),
          wantsToRead,
          spoilerJudgment,
          ...(comment.trim() ? { comment: comment.trim() } : {}),
        },
        controller.signal,
      );
      dispatch({ type: "FEEDBACK_ACCEPTED", feedbackId: result.feedbackId });
    } catch (error) {
      fail(error, "feedback");
    }
  }, [beginCommand, client, comment, fail, resonanceOptionId, resonanceText, spoilerJudgment, state, wantsToRead]);

  const submitFeedback = (event: FormEvent) => {
    event.preventDefault();
    void sendFeedback();
  };

  const reset = () => {
    commandController.current?.abort();
    retry.current = null;
    setInput("");
    setCustomQuestion("");
    setResonanceText("");
    setResonanceOptionId("");
    setComment("");
    setWantsToRead(false);
    setShowcaseSelection(null);
    setShowcasePlaybackFailed(false);
    window.history.replaceState({}, "", "/");
    dispatch({ type: "RESET" });
  };

  const openShowcase = (person: ShowcasePersonViewModel, entry: ShowcaseEntryViewModel) => {
    setShowcasePlaybackFailed(false);
    setShowcaseSelection({ person, entry });
    window.history.pushState(
      { shiduPage: "showcase", showcaseEntryId: entry.id },
      "",
      `/showcase/${encodeURIComponent(entry.id)}`,
    );
  };

  const closeShowcase = () => {
    setShowcaseSelection(null);
    setShowcasePlaybackFailed(false);
    window.history.replaceState({}, "", "/");
  };

  const chooseResonance = (option: ResonanceOption) => {
    setResonanceOptionId(option.id);
    setResonanceText(option.text);
  };

  const openNextStories = () => {
    if (state.name !== "job" || state.job.status !== "succeeded") return;
    if (videoRef.current) {
      window.sessionStorage.setItem(`shidu:playhead:${state.job.jobId}`, String(videoRef.current.currentTime));
    }
    window.history.pushState(
      { shiduPage: "next" },
      "",
      `/next?fromBookId=${encodeURIComponent(state.bookId)}&fromMomentId=${encodeURIComponent(state.directionId)}`,
    );
    dispatch({ type: "NEXT_OPENED" });
  };

  const restorePlayhead = (video: HTMLVideoElement, jobId: string) => {
    const saved = Number(window.sessionStorage.getItem(`shidu:playhead:${jobId}`));
    if (Number.isFinite(saved) && saved > 0) video.currentTime = saved;
  };

  return (
    <div className="shidu-stage">
    <div className="shidu-device">
      <div className="shidu-device-speaker" aria-hidden="true" />
    <div className="shidu-root" data-screen={showcaseSelection ? "showcase" : state.name}>
      <a className="shidu-skip" href="#shidu-main">Skip to main content</a>
      <header className="shidu-topbar">
        <button className="shidu-brand" type="button" onClick={reset} aria-label="Return to LifePreview home">
          <span className="shidu-seal" aria-hidden="true">LP</span>
          <span><b>LifePreview</b><small>UNEARTH A STORY / EXPERIENCE A LIFE</small></span>
        </button>
        <span className="shidu-status" aria-live="polite">{showcaseSelection ? SHOWCASE_LABEL : state.name === "job" ? JOB_LABELS[state.job.status] : "Stories in motion"}</span>
      </header>

      <main id="shidu-main" className="shidu-main">
        {showcaseSelection ? (
          <section className="shidu-page shidu-showcase-player">
            <button className="shidu-back" type="button" onClick={closeShowcase}>Back to Choose a life</button>
            <p className="shidu-eyebrow">{SHOWCASE_LABEL}</p>
            <h1>{showcaseSelection.entry.title}</h1>
            <p className="shidu-showcase-person-name">{showcaseSelection.person.name}</p>
            <div className="shidu-cinema shidu-showcase-cinema">
              <video
                aria-label={`${SHOWCASE_LABEL}: ${showcaseSelection.entry.title}`}
                src={showcaseSelection.entry.mediaUrl}
                controls
                preload="metadata"
                onError={() => setShowcasePlaybackFailed(true)}
              />
            </div>
            <p className="shidu-showcase-provenance">{SHOWCASE_LABEL}</p>
            {showcasePlaybackFailed && (
              <p className="shidu-showcase-error" role="alert">This previously generated video could not be played. Return and choose another film.</p>
            )}
          </section>
        ) : (
          <>
        {state.name === "input" && (
          <section className="shidu-page shidu-hero">
            <p className="shidu-eyebrow">A CINEMATIC LIFE ARCHIVE</p>
            <h1>Unearth a story, <em>experience a life.</em></h1>
            <p className="shidu-lead">Search for a life, verify the sources, then step inside one defining moment.</p>
            <form className="shidu-search" onSubmit={(event) => { event.preventDefault(); void resolveInput(); }}>
              <label htmlFor="book-input">Book title</label>
              <div>
                <input id="book-input" value={input} onChange={(event) => setInput(event.target.value)} autoComplete="off" />
                <button className="shidu-primary" type="submit" disabled={!input.trim()}>Find a life</button>
              </div>
            </form>
            <section className="shidu-shelf" aria-labelledby="shelf-title">
              <div className="shidu-shelf-heading">
                <h2 id="shelf-title">Choose a life</h2>
                <span>{showcaseStatus === "loading" ? "Loading" : showcaseStatus === "failed" ? "Unavailable" : `${showcasePeople.length} lives · ${showcasePeople.reduce((total, person) => total + person.entries.length, 0)} films`}</span>
              </div>
              {showcaseStatus === "failed" && <p className="shidu-shelf-empty">Previously generated films are unavailable right now.</p>}
              {showcaseStatus === "ready" && (
                <div className="shidu-showcase-archive">
                  <div className="shidu-showcase-intro">
                    <span>{SHOWCASE_LABEL}</span>
                    <small>Independent films from earlier AMD runs</small>
                  </div>
                  <div className="shidu-showcase-grid">
                    {showcasePeople.map((person) => (
                      <article className="shidu-showcase-person" key={person.id}>
                        <h3>{person.name}</h3>
                        <div>
                          {person.entries.map((entry) => (
                            <button
                              className="shidu-showcase-entry"
                              type="button"
                              key={entry.id}
                              aria-label={`Play ${entry.title} — ${person.name}`}
                              onClick={() => openShowcase(person, entry)}
                            >
                              <span>{entry.label}</span>
                              <b>{entry.title}</b>
                              <small>Play film</small>
                            </button>
                          ))}
                        </div>
                      </article>
                    ))}
                  </div>
                </div>
              )}
              {shelfStatus === "ready" && shelfBooks.length === 0 && <p className="shidu-shelf-empty">Verified stories will appear here. You can also begin with a title.</p>}
              {shelfBooks.length > 0 && (
                <div className="shidu-shelf-track">
                  {shelfBooks.map((book, index) => (
                    <button
                      className="shidu-shelf-book"
                      type="button"
                      key={book.id}
                      aria-label={`Open ${book.title}, ${book.momentCount ?? book.directions.length} moments`}
                      onClick={() => dispatch({ type: "CATALOG_PROJECTED", book })}
                    >
                      <span>{String(index + 1).padStart(2, "0")}</span>
                      <b>{book.title}</b>
                      <small>{book.author || "Author pending verification"}</small>
                      <p>{book.shelfHook || "Enter a verified moment from this life"}</p>
                    </button>
                  ))}
                </div>
              )}
            </section>
          </section>
        )}

        {state.name === "discovering" && <Waiting eyebrow="SEARCH AND VERIFY" title="Finding the life you meant" detail={state.title} />}

        {state.name === "candidates" && (
          <section className="shidu-page shidu-candidates">
            <p className="shidu-eyebrow">CONFIRM THE BOOK</p>
            <h1>Choose the Reader-verified edition</h1>
            <p className="shidu-lead">Reader verified</p>
            <div className="shidu-book-grid">
              {state.candidates.map((book) => (
                <article className="shidu-book-card" key={book.candidateId}>
                  <span className="shidu-book-mark" aria-hidden="true">LP</span>
                  <div>
                    <h2>{book.title}</h2>
                    <p>{book.author || "Author pending verification"}</p>
                    <small>
                      {[
                        book.language ? `Language: ${book.language}` : "",
                        book.edition ? `Edition: ${book.edition}` : "",
                        book.translator ? `Translator: ${book.translator}` : "",
                      ].filter(Boolean).map((detail, index) => (
                        <span key={detail}>{index > 0 ? ", " : ""}{detail}</span>
                      ))}
                    </small>
                  </div>
                  <button
                    aria-label={candidateSelectionLabel(book)}
                    className="shidu-primary"
                    type="button"
                    onClick={() => void selectCandidate(state.resolutionId, book)}
                  >Choose this edition</button>
                </article>
              ))}
            </div>
            <button className="shidu-text-button" type="button" onClick={reset}>None of these. Search again.</button>
          </section>
        )}

        {state.name === "unresolved" && (
          <MessagePage eyebrow="NOT YET VERIFIED" title="We could not verify that book yet" detail="Check the title and try again. Search summaries never replace Reader-verified bibliographic data.">
            <button className="shidu-primary" type="button" onClick={reset}>Search again</button>
          </MessagePage>
        )}

        {state.name === "selecting" && <Waiting eyebrow="CONFIRMING THE BOOK" title={`Selecting ${state.candidate.title}`} detail="Only the persisted, verified candidate will be used." />}

        {state.name === "catalog_loading" && <Waiting eyebrow="READING THE RESEARCH" title={`Opening ${state.book.title}`} detail="Only material confirmed by the source and service is shown." />}

        {state.name === "researching" && state.book.researchStatus !== "retryable_failed" && (
          <section className="shidu-page shidu-waiting" aria-live="polite">
            <p className="shidu-eyebrow">SOURCE RESEARCH</p>
            <div className="shidu-pulse" aria-hidden="true" />
            <h1>Verifying {state.book.title}</h1>
            <p className="shidu-lead">This page follows the server research state. It does not invent a wait time.</p>
            <button className="shidu-ghost" type="button" onClick={() => void loadCatalog(state.book)}>Check research status</button>
          </section>
        )}

        {state.name === "researching" && state.book.researchStatus === "retryable_failed" && (
          <MessagePage eyebrow="MORE RESEARCH NEEDED" title="This story is not ready to generate" detail="Source verification encountered a retryable problem. There is not enough trusted material yet.">
            <button className="shidu-primary" type="button" onClick={() => void restartResearch(state.book)}>Research again with AI completion</button>
            <button className="shidu-ghost" type="button" onClick={reset}>Choose another book</button>
          </MessagePage>
        )}

        {state.name === "insufficient" && (
          <MessagePage eyebrow="MORE RESEARCH NEEDED" title="This story is not ready to generate" detail="A new search will look for source material. If none can be verified, any AI-completed content will be clearly labeled.">
            <button className="shidu-primary" type="button" onClick={() => void restartResearch(state.book)}>Research again with AI completion</button>
            <button className="shidu-ghost" type="button" onClick={reset}>Choose another book</button>
          </MessagePage>
        )}

        {state.name === "directions" && (
          <section className="shidu-page shidu-moments">
            <button className="shidu-back" type="button" onClick={reset}>Back to the archive</button>
            <p className="shidu-eyebrow">BOOK MOMENTS</p>
            {state.book.contentMode === "ai_completed" && (
              <p className="shidu-eyebrow">AI-COMPLETED CONTENT, NOT ORIGINAL TEXT</p>
            )}
            <h1>{state.book.title} has {state.book.directions.length} defining moments</h1>
            <p className="shidu-lead">{state.book.contentMode === "ai_completed" ? "AI completed these moments from bibliographic and available source material. Details may be inaccurate." : "Each moment comes from verified material. Enter any one without following a sequence."}</p>
            <div className="shidu-moment-timeline">
              {state.book.directions.map((direction, index) => (
                <button
                  className="shidu-direction"
                  type="button"
                  key={direction.id}
                  onClick={() => dispatch({ type: "DIRECTION_SELECTED", directionId: direction.id })}
                  aria-label={`Open moment ${index + 1}: ${directionTitle(direction)}`}
                >
                  <span>{String(index + 1).padStart(2, "0")}</span>
                  <div><h2>{directionTitle(direction)}</h2><p>{momentSummary(direction)}</p></div>
                  <b aria-hidden="true">Open</b>
                </button>
              ))}
            </div>
          </section>
        )}

        {state.name === "moment" && (
          <section className="shidu-page shidu-moment-detail">
            <button className="shidu-back" type="button" onClick={() => dispatch({ type: "CATALOG_PROJECTED", book: state.book })}>Back to all moments</button>
            <p className="shidu-moment-index">Moment {String(state.direction.momentNumber ?? state.book.directions.indexOf(state.direction) + 1).padStart(2, "0")}</p>
            <h1>{directionTitle(state.direction)}</h1>
            <p className="shidu-moment-summary">{momentSummary(state.direction)}</p>
            <div className="shidu-keywords" aria-label="Keywords">
              {momentKeywords(state.direction).map((keyword) => <span key={keyword}>{keyword}</span>)}
            </div>
            <section className="shidu-resonance-preview" aria-labelledby="moment-resonance-title">
              <h2 id="moment-resonance-title">What might resonate with you</h2>
              <ol>{momentOptions(state.direction).map((option) => <li key={option.id}>{option.text}</li>)}</ol>
            </section>
            <label className="shidu-question" htmlFor="custom-question">Bring a question into the film (optional)</label>
            <input id="custom-question" className="shidu-line-input" maxLength={500} value={customQuestion} onChange={(event) => setCustomQuestion(event.target.value)} />
            <div className="shidu-sticky-action">
              <button className="shidu-primary" type="button" onClick={() => void requestPreview(state.book, state.direction)}>View director's preview</button>
            </div>
          </section>
        )}

        {state.name === "previewing" && <Waiting eyebrow="DIRECTOR'S PREVIEW" title="Composing this moment" detail="The opening and shot plan come from the live preview service." />}

        {state.name === "preview" && (
          <section className="shidu-page">
            <p className="shidu-eyebrow">DIRECTOR'S PREVIEW</p>
            <h1>{state.preview.provisionalTitle}</h1>
            <aside className="shidu-slice-summary" aria-label="Vertical slice delivery">
              <span>Vertical Slice / Preview</span>
              <strong>About 3 seconds</strong>
              <p>73 frames at 24 fps (3.04 seconds). Native audio. No subtitles.</p>
            </aside>
            <CharacterReference preview={state.preview} />
            <article className="shidu-script-card">
              <div className="shidu-opening"><span>{state.preview.contentLabel}</span><p>{state.preview.contentNotice}</p></div>
              <div className="shidu-opening"><span>{state.preview.openingLineLabel}</span><blockquote>{state.preview.openingLine}</blockquote></div>
              <p>{state.preview.experiencePromise}</p>
              <dl className="shidu-preview-meta">
                <div><dt>Shots</dt><dd>{state.preview.shots.length}</dd></div>
                <div><dt>Delivery</dt><dd>3.04 seconds</dd></div>
                <div><dt>Spoiler level</dt><dd>{state.preview.spoilerLevel}</dd></div>
              </dl>
              <ol className="shidu-shot-list">
                {state.preview.shots.map((shot) => <li key={shot.ordinal}><span>{String(shot.ordinal).padStart(2, "0")}</span><b>{shot.narrativeTask}</b><small>{shot.stateTransition}</small></li>)}
              </ol>
              <div className="shidu-curve" aria-label="Emotional arc">{state.preview.emotionCurve.map((item) => <span key={item}>{item}</span>)}</div>
            </article>
            <p className="shidu-submit-note">Preparation is complete. Generation begins only when you select Start generation.</p>
            <div className="shidu-actions">
              <button className="shidu-primary" type="button" onClick={() => void createJob()}>Start generation</button>
              <button className="shidu-ghost" type="button" onClick={() => dispatch({ type: "CATALOG_PROJECTED", book: state.book })}>Choose another moment</button>
            </div>
          </section>
        )}

        {state.name === "submitting" && <Waiting eyebrow="STARTING THE PREVIEW" title="Submitting your vertical slice" detail="From here, the page follows only the production state projected by the service." />}

        {state.name === "job" && isPollingStatus(state.job.status) && (
          <section className="shidu-page shidu-making">
            <p className="shidu-eyebrow">MAKING THE FILM</p>
            <h1>{JOB_LABELS[state.job.status]}</h1>
            <AiCompletionDisclosure job={state.job} preview={state.preview} book={state.book} />
            {state.job.status === "rendering"
              && state.job.gpuRuntimeProof?.gpuActivityObserved === true
              && state.job.gpuRuntimeProof.processExited === false && (
              <p className="shidu-runtime-proof" role="status"><span>AMD</span><strong>{state.job.gpuRuntimeProof.phase === "h3" ? "Rendering on AMD GPU" : "Running FLUX proof on AMD GPU"}</strong></p>
            )}
            <div className="shidu-orbit" aria-hidden="true"><span>{state.job.status === "queued" ? "Q" : "LP"}</span></div>
            <p className="shidu-lead">No invented percentage. Production advances only when the service state changes.</p>
            <ol className="shidu-progress-list">
              {ACTIVE_STEPS.map((step) => {
                const currentIndex = ACTIVE_STEPS.findIndex((item) => item.status === state.job.status);
                const stepIndex = ACTIVE_STEPS.indexOf(step);
                const mode = state.job.status === "queued" ? "pending" : stepIndex < currentIndex ? "done" : stepIndex === currentIndex ? "active" : "pending";
                return <li key={step.status} data-mode={mode}><span>{mode === "done" ? "✓" : String(stepIndex + 1).padStart(2, "0")}</span>{step.label}</li>;
              })}
            </ol>
          </section>
        )}

        {state.name === "job" && state.job.status === "failed" && (
          <MessagePage eyebrow="GENERATION STOPPED" title="The preview was not completed" detail={state.job.error?.message || "The service stopped this job before a playable film was delivered."}>
            <button className="shidu-primary" type="button" onClick={reset}>Start again</button>
          </MessagePage>
        )}

        {state.name === "job" && state.job.status === "succeeded" && state.job.artifacts && (
          <section className="shidu-page shidu-watch">
            <p className="shidu-eyebrow">Vertical Slice / Preview</p>
            <h1>{state.preview?.provisionalTitle || state.book?.title || "Your LifePreview film"}</h1>
            <AiCompletionDisclosure job={state.job} preview={state.preview} book={state.book} />
            <div className="shidu-cinema">
              <video
                ref={videoRef}
                aria-label="LifePreview vertical slice"
                src={state.job.artifacts.video}
                poster={state.job.artifacts.cover}
                controls
                preload="metadata"
                onLoadedMetadata={(event) => restorePlayhead(event.currentTarget, state.job.jobId)}
                onTimeUpdate={(event) => window.sessionStorage.setItem(`shidu:playhead:${state.job.jobId}`, String(event.currentTarget.currentTime))}
              />
            </div>
            <div className="shidu-delivery-note">
              <span>Delivery checks passed</span>
              <a href={state.job.artifacts.shareCard} target="_blank" rel="noreferrer">
                {isAiCompleted(state.job, state.preview, state.book) ? "View share card (AI-completed content)" : "View share card"}
              </a>
            </div>
            {isAiCompleted(state.job, state.preview, state.book) && (
              <figure className="shidu-share-card-disclosure">
                <img src={state.job.artifacts.shareCard} alt="LifePreview share card" />
                <figcaption>AI-completed content, not original text</figcaption>
              </figure>
            )}
            <form className="shidu-feedback" onSubmit={submitFeedback}>
              <fieldset className="shidu-resonance-choices">
                <legend>What stayed with you?</legend>
                {momentOptions(state.direction).map((option) => (
                  <button
                    className="shidu-resonance-choice"
                    data-selected={resonanceOptionId === option.id}
                    type="button"
                    key={option.id}
                    aria-pressed={resonanceOptionId === option.id}
                    onClick={() => chooseResonance(option)}
                  >{option.text}</button>
                ))}
              </fieldset>
              <label htmlFor="resonance">Or write your own response</label>
              <textarea id="resonance" required maxLength={1000} value={resonanceText} onChange={(event) => { setResonanceOptionId(""); setResonanceText(event.target.value); }} />
              <label htmlFor="spoiler">Spoiler balance</label>
              <select id="spoiler" value={spoilerJudgment} onChange={(event) => setSpoilerJudgment(event.target.value as FeedbackInput["spoilerJudgment"])}>
                <option value="acceptable">Balanced</option><option value="too_much">Too revealing</option><option value="none">No spoilers</option>
              </select>
              <label className="shidu-check"><input type="checkbox" checked={wantsToRead} onChange={(event) => setWantsToRead(event.target.checked)} /> I want to read this book</label>
              <label htmlFor="comment">Additional note (optional)</label>
              <textarea id="comment" maxLength={2000} value={comment} onChange={(event) => setComment(event.target.value)} />
              <button className="shidu-primary" type="submit" disabled={!resonanceText.trim()}>Send response</button>
            </form>
            <button className="shidu-next-story" type="button" onClick={openNextStories}>Experience another life</button>
          </section>
        )}

        {state.name === "next" && (
          <section className="shidu-page shidu-next-page">
            <button className="shidu-back" type="button" onClick={() => { window.history.back(); dispatch({ type: "PLAYER_RETURNED" }); }}>Back to your preview</button>
            <p className="shidu-eyebrow">KEEP LISTENING</p>
            <h1>Experience another life</h1>
            <AiCompletionDisclosure job={state.job} preview={state.preview} book={state.book} />
            {state.book && state.book.directions.filter((direction) => direction.id !== state.directionId).length > 0 && (
              <section className="shidu-next-section" aria-labelledby="same-book-title">
                <h2 id="same-book-title">Another moment from the same life</h2>
                <div className="shidu-next-list">
                  {state.book.directions.filter((direction) => direction.id !== state.directionId).map((direction) => (
                    <button type="button" key={direction.id} onClick={() => { window.history.replaceState({}, "", "/"); dispatch({ type: "MOMENT_OPENED", book: state.book!, direction }); }}>
                      <b>{directionTitle(direction)}</b><span>{momentSummary(direction)}</span>
                    </button>
                  ))}
                </div>
              </section>
            )}
            <section className="shidu-next-section" aria-labelledby="other-books-title">
              <h2 id="other-books-title">Choose another book</h2>
              <div className="shidu-next-list">
                {shelfBooks.filter((book) => book.id !== state.bookId).map((book) => (
                  <button type="button" key={book.id} onClick={() => { window.history.replaceState({}, "", "/"); dispatch({ type: "CATALOG_PROJECTED", book }); }}>
                    <b>{book.title}</b><span>{book.author || "Author pending verification"}, {book.momentCount ?? book.directions.length} moments</span>
                  </button>
                ))}
              </div>
            </section>
            <button className="shidu-primary shidu-search-another" type="button" onClick={reset}>Search another book</button>
          </section>
        )}

        {state.name === "feedback_submitting" && <Waiting eyebrow="SAVING YOUR RESPONSE" title="Sending what stayed with you" detail="Please wait. This response will not be submitted twice." />}

        {state.name === "feedback_done" && (
          <MessagePage eyebrow="FEEDBACK RECEIVED" title="Your response is part of the archive" detail={`Feedback ID ${state.feedbackId}`}>
            <button className="shidu-primary" type="button" onClick={reset}>Explore another life</button>
          </MessagePage>
        )}

        {state.name === "error" && (
          <MessagePage eyebrow="PAUSED HERE" title={state.message} detail={state.retryable ? "This can be retried safely with the same request identifier." : "This action cannot be retried safely. Please start again."}>
            {state.retryable && retry.current && <button className="shidu-primary" type="button" onClick={() => retry.current?.()}>Try again</button>}
            <button className="shidu-ghost" type="button" onClick={reset}>Return home</button>
          </MessagePage>
        )}
          </>
        )}
      </main>
      <footer className="shidu-footer"><span>LifePreview</span><small>Verified sources / labeled AI completion / delivery checked</small></footer>
    </div>
    </div>
    </div>
  );
}

function Waiting({ eyebrow, title, detail }: { eyebrow: string; title: string; detail: string }) {
  return <section className="shidu-page shidu-waiting" aria-live="polite"><p className="shidu-eyebrow">{eyebrow}</p><div className="shidu-pulse" aria-hidden="true" /><h1>{title}</h1><p className="shidu-lead">{detail}</p></section>;
}

function MessagePage({ eyebrow, title, detail, children }: { eyebrow: string; title: string; detail: string; children: React.ReactNode }) {
  return <section className="shidu-page shidu-message"><p className="shidu-eyebrow">{eyebrow}</p><h1>{title}</h1><p className="shidu-lead">{detail}</p><div className="shidu-actions">{children}</div></section>;
}
