import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ShiduApiError, type ShiduClient } from "../api/shiduClient";
import { ShiduApp } from "./ShiduApp";

const book = {
  id: "book-1",
  title: "测试之书",
  author: "作者",
  language: "zh-CN",
  edition: "首版",
  translator: "",
  researchStatus: "ready" as const,
  evidenceCoverage: { independentSources: 3 },
  directions: [
    {
      id: "direction-1",
      directionKey: "resonance",
      score: 0.91,
      payload: { title: "再走一步", promise: "看见选择的重量" },
      momentNumber: 1,
      summary: "在选择发生之前，先听见人物没有说出口的犹豫。",
      keywords: ["选择", "犹豫", "代价"],
      resonanceOptions: [
        { id: "choice-1", text: "我听见了那一步的重量" },
        { id: "choice-2", text: "我更在意他为什么出发" },
        { id: "choice-3", text: "我也有过相似的迟疑" },
      ],
    },
    {
      id: "direction-2",
      directionKey: "memory",
      score: 0.84,
      payload: { title: "回头看见来路" },
      momentNumber: 2,
      summary: "另一段经过核验的阅读时刻。",
      keywords: ["来路"],
      resonanceOptions: [
        { id: "memory-1", text: "我想起了自己的来路" },
        { id: "memory-2", text: "我听见了时间的变化" },
        { id: "memory-3", text: "我想继续听他的选择" },
      ],
    },
  ],
  momentCount: 2,
  shelfHook: "听见选择发生前的犹豫。",
};

const candidate = {
  candidateId: "candidate-1",
  title: book.title,
  author: book.author,
  language: book.language,
  edition: book.edition,
  translator: book.translator,
};

const preview = {
  bookId: book.id,
  directionRevisionId: "direction-1",
  scriptRevisionId: "script-1",
  provisionalTitle: "最后一程",
  experiencePromise: "看见选择的代价",
  openingLine: "我只剩最后一次机会。",
  openingLineKind: "rewritten",
  openingLineLabel: "AI 改写开场",
  contentMode: "source_grounded" as const,
  contentLabel: "原文与资料核验改写",
  contentNotice: "内容根据已核验原文与资料进行改写。",
  emotionCurve: ["压迫", "挣扎", "余韵"],
  shots: [{ ordinal: 1, narrativeTask: "开场", action: "启程", stateTransition: "迟疑到决断", durationSeconds: 9 }],
  durationEstimateSeconds: 54,
  fitFor: ["喜欢历史叙事"],
  notFitFor: ["只想看爽文"],
  sourceSummaries: [],
  spoilerLevel: "low",
  riskFlags: [],
};

const characterReference = {
  referenceProfile: "competition-imported-single-view-v1",
  sourceMode: "preuploaded_imported",
  requiredImages: 1,
  status: "prepared",
  label: "Prepared reference asset",
  disclosureLabel: "Preuploaded imported asset",
  requestId: "70000000-0000-4000-8000-000000000020",
  characterName: "Steve Jobs",
  importAuthoritySha256: "b".repeat(64),
  fluxProofPromptSha256: "c".repeat(64),
  fluxProofSeed: 20260806,
  fluxProofTemplateWorkflowSha256: "d".repeat(64),
  reference: {
    artifactRef: "prepared-reference:70000000-0000-4000-8000-000000000020",
    imageUrl: "/api/prepared-reference-assets/70000000-0000-4000-8000-000000000020/image",
    sha256: "fe82d64b5c47c2ef9159428f7dc1bedc18bf90dfe4ff86dff551672bbc673153",
    viewName: "front_three_quarter",
    mimeType: "image/png",
    width: 880,
    height: 1168,
    importedBeforeUserClick: true,
    generatedByCurrentFlux: false,
  },
} as const;

const showcasePayload = {
  people: [
    {
      id: "steve-jobs",
      name: "Steve Jobs",
      entries: [
        {
          id: "jobs-garage",
          title: "The Garage Before the World",
          mediaUrl: "/api/showcase-media/jobs-garage",
          label: "Previously generated on AMD",
        },
        {
          id: "jobs-one-more-thing",
          title: "One More Thing",
          mediaUrl: "/api/showcase-media/jobs-one-more-thing",
          label: "Previously generated on AMD",
        },
      ],
    },
    {
      id: "su-dongpo",
      name: "Su Dongpo",
      entries: [{
        id: "su-dongpo-huangzhou",
        title: "Moon over Huangzhou",
        mediaUrl: "/api/showcase-media/su-dongpo-huangzhou",
        label: "Previously generated on AMD",
      }],
    },
    {
      id: "frida-kahlo",
      name: "Frida Kahlo",
      entries: [{
        id: "frida-painting-through-pain",
        title: "Painting Through Pain",
        mediaUrl: "/api/showcase-media/frida-painting-through-pain",
        label: "Previously generated on AMD",
      }],
    },
  ],
};

function stubShowcase(payload: unknown = showcasePayload) {
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function client(overrides: Partial<ShiduClient> = {}): ShiduClient {
  return {
    resolveInput: vi.fn().mockResolvedValue({
      resolutionId: "resolution-1",
      resolution: "candidates",
      candidates: [candidate],
    }),
    selectCandidate: vi.fn().mockResolvedValue({ book, researchJobId: "research-1" }),
    retryResearch: vi.fn().mockResolvedValue({ book, researchJobId: "research-retry-1" }),
    listShelf: vi.fn().mockResolvedValue({ books: [book] }),
    listBooks: vi.fn().mockResolvedValue({ books: [book] }),
    getBook: vi.fn().mockResolvedValue({ book }),
    directorPreview: vi.fn().mockResolvedValue(preview),
    createVideoJob: vi.fn().mockResolvedValue({ jobId: "job-1", bookId: book.id, status: "queued" }),
    getVideoJob: vi.fn().mockImplementation(() => new Promise(() => undefined)),
    sendFeedback: vi.fn().mockResolvedValue({ feedbackId: "feedback-1", accepted: true }),
    ...overrides,
  };
}

async function reachJob(api: ShiduClient) {
  const user = userEvent.setup();
  render(<ShiduApp client={api} pollIntervalMs={1000} />);
  await user.type(screen.getByRole("textbox", { name: "Book title" }), "测试之书");
  await user.click(screen.getByRole("button", { name: "Find a life" }));
  await user.click(await screen.findByRole("button", { name: /^Choose 测试之书/ }));
  await user.click(await screen.findByRole("button", { name: /Open moment 1/ }));
  await user.click(await screen.findByRole("button", { name: "View director's preview" }));
  await user.click(await screen.findByRole("button", { name: "Start generation" }));
}

async function reachPreview(api: ShiduClient) {
  const user = userEvent.setup();
  render(<ShiduApp client={api} />);
  await user.type(screen.getByRole("textbox", { name: "Book title" }), "测试之书");
  await user.click(screen.getByRole("button", { name: "Find a life" }));
  await user.click(await screen.findByRole("button", { name: /^Choose 测试之书/ }));
  await user.click(await screen.findByRole("button", { name: /Open moment 1/ }));
  await user.click(await screen.findByRole("button", { name: "View director's preview" }));
}

describe("ShiduApp", () => {
  it("keeps the default API client stable after the shelf response rerenders the app", async () => {
    let resolveShelf!: (response: Response) => void;
    const shelfResponse = new Promise<Response>((resolve) => {
      resolveShelf = resolve;
    });
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      if (String(input) === "/api/shelf") return shelfResponse;
      if (String(input) === "/api/showcase") {
        return Promise.resolve(new Response(JSON.stringify({ people: [] }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }));
      }
      return new Promise<Response>(() => undefined);
    });
    vi.stubGlobal("fetch", fetchMock);

    try {
      render(<ShiduApp />);
      await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/showcase", expect.anything()));
      expect(fetchMock.mock.calls.filter(([input]) => String(input) === "/api/shelf")).toHaveLength(1);

      await act(async () => {
        resolveShelf(new Response(JSON.stringify({ books: [] }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }));
      });

      expect(fetchMock.mock.calls.filter(([input]) => String(input) === "/api/shelf")).toHaveLength(1);
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("frames the product as an English LifePreview vertical slice", () => {
    render(<ShiduApp client={client()} />);

    expect(screen.getByRole("button", { name: "Return to LifePreview home" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Unearth a story, experience a life." })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /light|dark/i })).not.toBeInTheDocument();
  });

  it("loads three lives and four independent previously generated AMD films", async () => {
    const fetchMock = stubShowcase();
    const api = client();
    render(<ShiduApp client={api} />);

    expect(await screen.findByRole("heading", { name: "Steve Jobs" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Su Dongpo" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Frida Kahlo" })).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /^Play .+ — .+$/ })).toHaveLength(4);
    expect(screen.getAllByText("Previously generated on AMD")).toHaveLength(5);
    expect(screen.getByText("3 lives · 4 films")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("/api/showcase", expect.objectContaining({
      headers: { Accept: "application/json" },
    }));
    expect(api.createVideoJob).not.toHaveBeenCalled();

    vi.unstubAllGlobals();
  });

  it("opens a separate seekable Showcase player and returns without creating a live job", async () => {
    stubShowcase();
    const api = client();
    const user = userEvent.setup();
    render(<ShiduApp client={api} />);

    await user.click(await screen.findByRole("button", { name: "Play The Garage Before the World — Steve Jobs" }));

    const player = screen.getByLabelText("Previously generated on AMD: The Garage Before the World");
    expect(player).toHaveAttribute("controls");
    expect(player).toHaveAttribute("src", "/api/showcase-media/jobs-garage");
    expect(screen.getByRole("heading", { name: "The Garage Before the World" })).toBeInTheDocument();
    expect(screen.getByText("Steve Jobs")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Start generation" })).not.toBeInTheDocument();
    expect(api.createVideoJob).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Back to Choose a life" }));
    expect(screen.getByRole("heading", { name: "Choose a life" })).toBeInTheDocument();
    expect(api.createVideoJob).not.toHaveBeenCalled();

    vi.unstubAllGlobals();
  });

  it("shows a readable error when a previously generated film cannot play", async () => {
    stubShowcase();
    const user = userEvent.setup();
    render(<ShiduApp client={client()} />);

    await user.click(await screen.findByRole("button", { name: "Play Moon over Huangzhou — Su Dongpo" }));
    fireEvent.error(screen.getByLabelText("Previously generated on AMD: Moon over Huangzhou"));

    expect(screen.getByRole("alert")).toHaveTextContent("This previously generated video could not be played");
    vi.unstubAllGlobals();
  });

  it("submits exactly one final job only after the user starts the vertical slice", async () => {
    const api = client();
    const user = userEvent.setup();
    render(<ShiduApp client={api} />);
    await user.type(screen.getByRole("textbox", { name: "Book title" }), "测试之书");
    await user.click(screen.getByRole("button", { name: "Find a life" }));
    await user.click(await screen.findByRole("button", { name: /^Choose 测试之书/ }));
    await user.click(await screen.findByRole("button", { name: /Open moment 1/ }));
    await user.click(await screen.findByRole("button", { name: "View director's preview" }));

    expect(await screen.findByText("Vertical Slice / Preview")).toBeInTheDocument();
    expect(screen.getByText("About 3 seconds")).toBeInTheDocument();
    expect(screen.getByText("73 frames at 24 fps (3.04 seconds). Native audio. No subtitles.")).toBeInTheDocument();
    expect(api.createVideoJob).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Start generation" }));

    expect(api.createVideoJob).toHaveBeenCalledTimes(1);
  });

  it("shows one honestly labelled preuploaded Steve Jobs reference before submission", async () => {
    const api = client({
      directorPreview: vi.fn().mockResolvedValue({
        ...preview,
        characterReference,
      }),
    });

    await reachPreview(api);

    const images = await screen.findAllByRole("img", {
      name: "Prepared preuploaded Steve Jobs reference asset",
    });
    expect(images).toHaveLength(1);
    expect(images[0]).toHaveAttribute("src", "/api/prepared-reference-assets/70000000-0000-4000-8000-000000000020/image");
    expect(images[0]).toHaveAttribute("width", "880");
    expect(images[0]).toHaveAttribute("height", "1168");
    expect(screen.getByText("Prepared reference asset")).toBeInTheDocument();
    expect(screen.getByText("Preuploaded imported asset · not this run's FLUX output")).toBeInTheDocument();
    expect(screen.queryByText("AI-generated character interpretation")).not.toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/three[- ]view|historical photo|real (?:appearance|likeness)/i);
    expect(api.createVideoJob).not.toHaveBeenCalled();
  });

  it("fails closed for legacy multi-image character reference data", async () => {
    const api = client({
      directorPreview: vi.fn().mockResolvedValue({
        ...preview,
        characterReference: {
          ...characterReference,
          requiredImages: 3,
          references: [characterReference.reference, characterReference.reference, characterReference.reference],
        },
      }),
    });

    await reachPreview(api);

    expect(screen.queryByRole("img", { name: "Prepared preuploaded Steve Jobs reference asset" })).not.toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/three[- ]view|historical photo|real (?:appearance|likeness)/i);
    expect(api.createVideoJob).not.toHaveBeenCalled();
  });

  it("fails closed when the prepared asset is not the fixed Steve Jobs import", async () => {
    const api = client({
      directorPreview: vi.fn().mockResolvedValue({
        ...preview,
        characterReference: {
          ...characterReference,
          reference: { ...characterReference.reference, sha256: "0".repeat(64) },
        },
      }),
    });

    await reachPreview(api);

    expect(screen.queryByRole("img", { name: "Prepared preuploaded Steve Jobs reference asset" })).not.toBeInTheDocument();
    expect(api.createVideoJob).not.toHaveBeenCalled();
  });

  it("never advances making progress without a backend projection", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    await reachJob(client());
    expect(await screen.findByRole("heading", { name: "Waiting to begin" })).toBeInTheDocument();
    await act(async () => vi.advanceTimersByTimeAsync(60_000));
    expect(screen.getByRole("heading", { name: "Waiting to begin" })).toBeInTheDocument();
    expect(screen.queryByText("100%")).not.toBeInTheDocument();
    vi.useRealTimers();
  });

  it("shows the AI completion disclosure while the video task is running", async () => {
    const api = client({
      createVideoJob: vi.fn().mockResolvedValue({
        jobId: "job-1",
        bookId: book.id,
        status: "queued",
        contentMode: "ai_completed",
        contentLabel: "AI 补全剧情（非原文）",
        contentNotice: "未找到可核验原文；内容由 AI 补全，可能存在偏差。",
      }),
    });

    await reachJob(api);

    expect(await screen.findByRole("note", { name: "AI content disclosure" })).toHaveTextContent("AI-completed content, not original text");
  });

  it("selects a Reader-verified candidate before the first catalog request", async () => {
    const api = client();
    const user = userEvent.setup();
    render(<ShiduApp client={api} />);
    await user.type(screen.getByRole("textbox", { name: "Book title" }), "测试之书");
    await user.click(screen.getByRole("button", { name: "Find a life" }));

    expect(await screen.findByText("Reader verified")).toBeInTheDocument();
    expect(api.listBooks).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: /^Choose 测试之书/ }));
    await screen.findByRole("heading", { name: /has 2 defining moments/ });
    expect(api.selectCandidate).toHaveBeenCalledWith(
      "resolution-1",
      "candidate-1",
      expect.any(AbortSignal),
    );
    expect(vi.mocked(api.selectCandidate).mock.invocationCallOrder[0]).toBeLessThan(
      vi.mocked(api.listBooks).mock.invocationCallOrder[0],
    );
    expect(document.body.textContent).not.toContain("人工审核");
  });

  it("opens another verified book from the candidate shelf", async () => {
    const api = client();
    const user = userEvent.setup();
    render(<ShiduApp client={api} />);

    await user.click(await screen.findByRole("button", { name: "Open 测试之书, 2 moments" }));
    expect(screen.getByRole("heading", { name: "测试之书 has 2 defining moments" })).toBeInTheDocument();
    expect(api.resolveInput).not.toHaveBeenCalled();
  });

  it("shows summary, keywords and exactly three resonance choices for one moment", async () => {
    const api = client();
    const user = userEvent.setup();
    render(<ShiduApp client={api} />);
    await user.click(await screen.findByRole("button", { name: "Open 测试之书, 2 moments" }));
    await user.click(screen.getByRole("button", { name: /Open moment 1/ }));

    expect(screen.getByRole("heading", { name: "再走一步" })).toBeInTheDocument();
    expect(screen.getByText("在选择发生之前，先听见人物没有说出口的犹豫。")).toBeInTheDocument();
    expect(screen.getByLabelText("Keywords")).toHaveTextContent("选择");
    expect(screen.getByRole("heading", { name: "What might resonate with you" })).toBeInTheDocument();
    expect(screen.getAllByRole("listitem")).toHaveLength(3);
  });

  it("distinguishes candidates whose only identity difference is language", async () => {
    const api = client({
      resolveInput: vi.fn().mockResolvedValue({
        resolutionId: "resolution-languages",
        resolution: "candidates",
        candidates: [
          { ...candidate, candidateId: "candidate-zh", language: "zh-cn" },
          { ...candidate, candidateId: "candidate-en", language: "en" },
        ],
      }),
    });
    const user = userEvent.setup();
    render(<ShiduApp client={api} />);
    await user.type(screen.getByRole("textbox", { name: "Book title" }), "测试之书");
    await user.click(screen.getByRole("button", { name: "Find a life" }));

    expect(await screen.findByText("Language: zh-cn")).toBeInTheDocument();
    expect(screen.getByText("Language: en")).toBeInTheDocument();
    expect(screen.getByRole("button", {
      name: "Choose 测试之书, Author: 作者, Language: zh-cn, Edition: 首版",
    })).toBeInTheDocument();
    expect(screen.getByRole("button", {
      name: "Choose 测试之书, Author: 作者, Language: en, Edition: 首版",
    })).toBeInTheDocument();
  });

  it("shows unresolved discovery without starting selection or catalog polling", async () => {
    const api = client({
      resolveInput: vi.fn().mockResolvedValue({
        resolutionId: "resolution-empty",
        resolution: "unresolved",
        candidates: [],
      }),
    });
    const user = userEvent.setup();
    render(<ShiduApp client={api} />);
    await user.type(screen.getByRole("textbox", { name: "Book title" }), "不存在的书");
    await user.click(screen.getByRole("button", { name: "Find a life" }));

    expect(await screen.findByRole("heading", { name: "We could not verify that book yet" })).toBeInTheDocument();
    expect(api.selectCandidate).not.toHaveBeenCalled();
    expect(api.listBooks).not.toHaveBeenCalled();
  });

  it("shows only the stable public dependency error", async () => {
    const api = client({
      resolveInput: vi.fn().mockRejectedValue(new ShiduApiError(503, {
        error_code: "dependency_unavailable",
        message: "服务暂时不可用，请稍后重试",
        retryable: true,
      })),
    });
    const user = userEvent.setup();
    render(<ShiduApp client={api} />);
    await user.type(screen.getByRole("textbox", { name: "Book title" }), "测试之书");
    await user.click(screen.getByRole("button", { name: "Find a life" }));

    expect(await screen.findByRole("heading", { name: "服务暂时不可用，请稍后重试" })).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/https?:\/\/|10\.0\.0\.1|reader body/i);
  });

  it("starts a fresh research job when the previous evidence result is insufficient", async () => {
    const insufficient = { ...book, researchStatus: "insufficient" as const, directions: [] };
    const retryResearch = vi.fn().mockResolvedValue({
      book: insufficient,
      researchJobId: "research-retry-1",
    });
    const api = client({
      listBooks: vi.fn().mockResolvedValue({ books: [insufficient] }),
      retryResearch,
    });
    const user = userEvent.setup();
    render(<ShiduApp client={api} />);
    await user.type(screen.getByRole("textbox", { name: "Book title" }), "测试之书");
    await user.click(screen.getByRole("button", { name: "Find a life" }));
    await user.click(await screen.findByRole("button", { name: /^Choose 测试之书/ }));
    expect(await screen.findByRole("heading", { name: "This story is not ready to generate" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "View director's preview" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Research again with AI completion" }));
    expect(retryResearch).toHaveBeenCalledWith(book.id, expect.any(AbortSignal));
    expect(await screen.findByRole("heading", { name: "Verifying 测试之书" })).toBeInTheDocument();
  });

  it("labels AI-completed directions instead of presenting them as original text", async () => {
    const completed = {
      ...book,
      contentMode: "ai_completed" as const,
      evidenceCoverage: { content_mode: "ai_completed" },
    };
    const api = client({ listShelf: vi.fn().mockResolvedValue({ books: [completed] }) });
    const user = userEvent.setup();
    render(<ShiduApp client={api} />);
    await user.click(await screen.findByRole("button", { name: "Open 测试之书, 2 moments" }));
    expect(screen.getByText("AI-COMPLETED CONTENT, NOT ORIGINAL TEXT")).toBeInTheDocument();
  });

  it("keeps polling every durable research phase until the backend projection becomes ready", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const phases = ["resolving", "searching", "reading", "extracting", "synthesizing"] as const;
    const listBooks = vi.fn()
      .mockResolvedValueOnce({ books: [{ ...book, researchStatus: phases[0], directions: [] }] })
      .mockResolvedValueOnce({ books: [{ ...book, researchStatus: phases[1], directions: [] }] })
      .mockResolvedValueOnce({ books: [{ ...book, researchStatus: phases[2], directions: [] }] })
      .mockResolvedValueOnce({ books: [{ ...book, researchStatus: phases[3], directions: [] }] })
      .mockResolvedValueOnce({ books: [{ ...book, researchStatus: phases[4], directions: [] }] })
      .mockResolvedValueOnce({ books: [book] });
    const api = client({ listBooks });
    const user = userEvent.setup();
    render(<ShiduApp client={api} pollIntervalMs={1000} />);
    await user.type(screen.getByRole("textbox", { name: "Book title" }), "测试之书");
    await user.click(screen.getByRole("button", { name: "Find a life" }));
    await user.click(await screen.findByRole("button", { name: /^Choose 测试之书/ }));
    expect(await screen.findByRole("heading", { name: "Verifying 测试之书" })).toBeInTheDocument();

    await act(async () => vi.advanceTimersByTimeAsync(5100));
    expect(await screen.findByRole("heading", { name: /has 2 defining moments/ })).toBeInTheDocument();
    expect(listBooks).toHaveBeenCalledTimes(6);
    vi.useRealTimers();
  });

  it("treats retryable research failure as a retryable terminal projection", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const retryableFailure = { ...book, researchStatus: "retryable_failed" as const, directions: [] };
    const listBooks = vi.fn().mockResolvedValue({ books: [retryableFailure] });
    const api = client({ listBooks });
    const user = userEvent.setup();
    render(<ShiduApp client={api} pollIntervalMs={1000} />);
    await user.type(screen.getByRole("textbox", { name: "Book title" }), "测试之书");
    await user.click(screen.getByRole("button", { name: "Find a life" }));
    await user.click(await screen.findByRole("button", { name: /^Choose 测试之书/ }));

    expect(await screen.findByRole("heading", { name: "This story is not ready to generate" })).toBeInTheDocument();
    expect(screen.getByText(/retryable problem/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Research again with AI completion" })).toBeInTheDocument();
    await act(async () => vi.advanceTimersByTimeAsync(5000));
    expect(listBooks).toHaveBeenCalledTimes(1);
    vi.useRealTimers();
  });

  it("uses projected signed artifact URLs without rendering a subtitle track", async () => {
    const api = client({
      getVideoJob: vi.fn().mockResolvedValue({
        jobId: "job-1",
        bookId: book.id,
        status: "succeeded",
        artifacts: {
          video: "/artifacts/video-token",
          subtitle: "/artifacts/subtitle-token",
          cover: "/artifacts/cover-token",
          shareCard: "/artifacts/share-token",
        },
      }),
    });
    await reachJob(api);
    const video = await screen.findByLabelText("LifePreview vertical slice");
    expect(video).toHaveAttribute("src", "/artifacts/video-token");
    expect(video).toHaveAttribute("poster", "/artifacts/cover-token");
    expect(video.querySelector("track")).toBeNull();
    expect(screen.getByText("Vertical Slice / Preview")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "View share card" })).toHaveAttribute("href", "/artifacts/share-token");
  });

  it("does not claim AMD GPU rendering from status alone", async () => {
    const api = client({
      getVideoJob: vi.fn().mockResolvedValue({
        jobId: "job-1",
        bookId: book.id,
        status: "rendering",
      }),
    });

    await reachJob(api);

    expect(await screen.findByRole("heading", { name: "Creating the film" })).toBeInTheDocument();
    expect(screen.queryByText("Rendering on AMD GPU")).not.toBeInTheDocument();
    expect(api.createVideoJob).toHaveBeenCalledTimes(1);
  });

  it("shows AMD GPU rendering only for a validated H3 runtime proof", async () => {
    const api = client({
      getVideoJob: vi.fn().mockResolvedValue({
        jobId: "job-1",
        bookId: book.id,
        status: "rendering",
        gpuRuntimeProof: {
          phase: "h3",
          promptId: "h3-prompt-1",
          queueId: 17,
          submissionNonce: "1".repeat(32),
          workflowSha256: "2".repeat(64),
          gpuActivityObserved: true,
          processExited: false,
          referenceSha256: "fe82d64b5c47c2ef9159428f7dc1bedc18bf90dfe4ff86dff551672bbc673153",
          referenceSourceMode: "preuploaded_imported",
        },
      }),
    });

    await reachJob(api);

    expect(await screen.findByText("Rendering on AMD GPU")).toBeInTheDocument();
    expect(api.createVideoJob).toHaveBeenCalledTimes(1);
  });

  it("keeps the non-original AI disclosure on the finished film and share card", async () => {
    const api = client({
      getVideoJob: vi.fn().mockResolvedValue({
        jobId: "job-1",
        bookId: book.id,
        status: "succeeded",
        contentMode: "ai_completed",
        contentLabel: "AI 补全剧情（非原文）",
        contentNotice: "未找到可核验原文；内容由 AI 根据可用资料补全，可能存在偏差。",
        artifacts: {
          video: "/artifacts/video-token",
          subtitle: "/artifacts/subtitle-token",
          cover: "/artifacts/cover-token",
          shareCard: "/artifacts/share-token",
        },
      }),
    });

    await reachJob(api);

    expect(await screen.findByRole("note", { name: "AI content disclosure" })).toHaveTextContent("AI-completed content, not original text");
    expect(screen.getByRole("note", { name: "AI content disclosure" })).toHaveTextContent("可能存在偏差");
    expect(screen.getByRole("link", { name: "View share card (AI-completed content)" })).toHaveAttribute(
      "href",
      "/artifacts/share-token",
    );
    expect(screen.getByRole("img", { name: "LifePreview share card" })).toHaveAttribute("src", "/artifacts/share-token");
    expect(screen.getByText("AI-completed content, not original text", { selector: "figcaption" })).toBeInTheDocument();
  });

  it("aborts an in-flight job projection when the view unmounts", async () => {
    let observedSignal: AbortSignal | undefined;
    const api = client({
      getVideoJob: vi.fn().mockImplementation((_jobId, signal) => {
        observedSignal = signal;
        return new Promise(() => undefined);
      }),
    });
    const view = render(<ShiduApp client={api} />);
    const user = userEvent.setup();
    await user.type(screen.getByRole("textbox", { name: "Book title" }), "测试之书");
    await user.click(screen.getByRole("button", { name: "Find a life" }));
    await user.click(await screen.findByRole("button", { name: /^Choose 测试之书/ }));
    await user.click(await screen.findByRole("button", { name: /Open moment 1/ }));
    await user.click(await screen.findByRole("button", { name: "View director's preview" }));
    await user.click(await screen.findByRole("button", { name: "Start generation" }));
    await screen.findByRole("heading", { name: "Waiting to begin" });
    expect(observedSignal?.aborted).toBe(false);
    view.unmount();
    expect(observedSignal?.aborted).toBe(true);
  });

  it("offers three structured choices and opens a dedicated next-story page", async () => {
    const api = client({
      getVideoJob: vi.fn().mockResolvedValue({
        jobId: "job-1",
        bookId: book.id,
        status: "succeeded",
        artifacts: {
          video: "/artifacts/video-token",
          subtitle: "/artifacts/subtitle-token",
          cover: "/artifacts/cover-token",
          shareCard: "/artifacts/share-token",
        },
      }),
    });
    await reachJob(api);
    const user = userEvent.setup();
    const choices = await screen.findAllByRole("button", { name: /我听见了那一步的重量|我更在意他为什么出发|我也有过相似的迟疑/ });
    expect(choices).toHaveLength(3);
    await user.click(choices[0]);
    expect(screen.getByRole("textbox", { name: "Or write your own response" })).toHaveValue("我听见了那一步的重量");

    await user.click(screen.getByRole("button", { name: "Experience another life" }));
    expect(screen.getByRole("heading", { name: "Experience another life" })).toBeInTheDocument();
    expect(window.location.pathname).toBe("/next");
    expect(screen.getByRole("button", { name: /回头看见来路/ })).toBeInTheDocument();
  });
});
