import { expect, test } from "@playwright/test";

const showcasePayload = {
  people: [
    {
      id: "steve-jobs",
      name: "Steve Jobs",
      entries: [
        { id: "jobs-garage", title: "The Garage Before the World", mediaUrl: "/api/showcase-media/jobs-garage", label: "Previously generated on AMD" },
        { id: "jobs-one-more-thing", title: "One More Thing", mediaUrl: "/api/showcase-media/jobs-one-more-thing", label: "Previously generated on AMD" },
      ],
    },
    {
      id: "su-dongpo",
      name: "Su Dongpo",
      entries: [{ id: "su-dongpo-huangzhou", title: "Moon over Huangzhou", mediaUrl: "/api/showcase-media/su-dongpo-huangzhou", label: "Previously generated on AMD" }],
    },
    {
      id: "frida-kahlo",
      name: "Frida Kahlo",
      entries: [{ id: "frida-painting-through-pain", title: "Painting Through Pain", mediaUrl: "/api/showcase-media/frida-painting-through-pain", label: "Previously generated on AMD" }],
    },
  ],
};

test("keeps the LifePreview vertical slice user-triggered and subtitle-free", async ({ page }) => {
  const seenApiRequests: string[] = [];
  let finalJobPosts = 0;
  let jobReads = 0;
  const book = {
    id: "steve-jobs-biography",
    title: "Steve Jobs",
    author: "Walter Isaacson",
    language: "en",
    edition: "First edition",
    translator: "",
    researchStatus: "ready",
    evidenceCoverage: { independentSources: 3 },
    momentCount: 1,
    shelfHook: "The choices behind a defining creative life.",
    directions: [{
      id: "direction-1",
      directionKey: "resonance-1",
      score: 0.9,
      payload: { title: "One Step Further", spoiler_level: "low" },
      momentNumber: 1,
      summary: "Stand inside the pause before a defining decision.",
      keywords: ["choice", "courage", "change"],
      resonanceOptions: [
        { id: "choice-1", text: "I felt the weight of the choice" },
        { id: "choice-2", text: "I wondered what made the person begin" },
        { id: "choice-3", text: "It recalled a turning point of my own" },
      ],
    }],
  };
  const candidate = {
    candidateId: "candidate-1",
    title: book.title,
    author: book.author,
    language: book.language,
    edition: book.edition,
    translator: book.translator,
  };

  await page.route("http://127.0.0.1:4174/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const requestKey = `${request.method()} ${url.pathname}`;
    seenApiRequests.push(requestKey);
    const json = (body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

    if (url.pathname === "/api/shelf") return json({ books: [book] });
    if (url.pathname === "/api/showcase") return json(showcasePayload);
    if (url.pathname === "/api/resolve-input") return json({
      resolutionId: "resolution-1",
      resolution: "candidates",
      candidates: [candidate],
    });
    if (url.pathname === "/api/resolve-input/resolution-1/select") return json({ book, researchJobId: "research-1" });
    if (url.pathname === "/api/books") return json({ books: [book] });
    if (url.pathname === "/api/director-preview") return json({
      bookId: book.id,
      directionRevisionId: "direction-1",
      scriptRevisionId: "script-1",
      provisionalTitle: "The Choice Before the Machine",
      experiencePromise: "Enter one verified Steve Jobs moment without mistaking it for a full life overview.",
      openingLine: "The machine still had to feel inevitable.",
      openingLineKind: "rewritten",
      openingLineLabel: "Rewritten opening",
      contentMode: "source_grounded",
      contentLabel: "Source-grounded adaptation",
      contentNotice: "Adapted from verified source material.",
      emotionCurve: ["pressure", "choice", "afterglow"],
      shots: [{ ordinal: 1, narrativeTask: "Opening", action: "Begin", stateTransition: "Hesitation to decision", durationSeconds: 9 }],
      durationEstimateSeconds: 54,
      fitFor: [],
      notFitFor: [],
      sourceSummaries: [],
      spoilerLevel: "low",
      riskFlags: [],
      characterReference: {
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
      },
    });
    if (url.pathname === "/api/video-jobs" && request.method() === "POST") {
      finalJobPosts += 1;
      expect(request.postDataJSON()).toEqual({ bookId: book.id, directionRevisionId: "direction-1", trialScriptRevisionId: "script-1" });
      expect(request.headers()["idempotency-key"]).toBeTruthy();
      return json({ jobId: "job-1", bookId: book.id, status: "queued" }, 202);
    }
    if (url.pathname === "/api/video-jobs/job-1") {
      jobReads += 1;
      return json(jobReads <= 1
        ? {
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
          }
        : {
            jobId: "job-1",
            bookId: book.id,
            status: "succeeded",
            artifacts: {
              video: "/artifacts/video-token",
              subtitle: "/artifacts/subtitle-token",
              cover: "/artifacts/cover-token",
              shareCard: "/artifacts/share-token",
            },
          });
    }
    if (url.pathname === "/api/feedback") return json({ feedbackId: "feedback-1", accepted: true });
    return route.abort();
  });
  await page.route("**/artifacts/**", (route) => route.fulfill({ status: 200, contentType: "application/octet-stream", body: "" }));

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Unearth a story, experience a life." })).toBeVisible();
  await expect(page.getByRole("button", { name: /light|dark/i })).toHaveCount(0);
  await page.getByRole("textbox", { name: "Book title" }).fill("Steve Jobs");
  await page.getByRole("button", { name: "Find a life" }).click();
  await page.getByRole("button", { name: /^Choose Steve Jobs/ }).click();
  await page.getByRole("button", { name: /Open moment 1/ }).click();
  await page.getByRole("button", { name: "View director's preview" }).click();

  await expect(page.getByText("Vertical Slice / Preview")).toBeVisible();
  await expect(page.getByText("About 3 seconds")).toBeVisible();
  await expect(page.getByText("73 frames at 24 fps (3.04 seconds). Native audio. No subtitles.")).toBeVisible();
  const characterReference = page.getByRole("img", { name: "Prepared preuploaded Steve Jobs reference asset" });
  await expect(characterReference).toHaveCount(1);
  await expect(characterReference).toHaveAttribute("src", "/api/prepared-reference-assets/70000000-0000-4000-8000-000000000020/image");
  await expect(page.getByText("Prepared reference asset")).toBeVisible();
  await expect(page.getByText("Preuploaded imported asset · not this run's FLUX output")).toBeVisible();
  await expect(page.getByText("AI-generated character interpretation")).toHaveCount(0);
  await expect(page.getByText(/three[- ]view|historical photo|real (?:appearance|likeness)/i)).toHaveCount(0);
  await expect(page.getByText(/90 seconds|90-second/i)).toHaveCount(0);
  expect(finalJobPosts).toBe(0);
  expect(seenApiRequests).not.toContain("POST /api/video-jobs");

  await page.getByRole("button", { name: "Start generation" }).click();
  await expect.poll(() => finalJobPosts).toBe(1);
  await expect(page.getByText("Rendering on AMD GPU")).toBeVisible();
  await expect(page.getByText("100%")).toHaveCount(0);
  const video = page.getByLabel("LifePreview vertical slice");
  await expect(video).toBeVisible({ timeout: 10_000 });
  await expect(video.locator("track")).toHaveCount(0);
  expect(finalJobPosts).toBe(1);

  await page.getByRole("textbox", { name: "Or write your own response" }).fill("This moment made me want to read more.");
  await page.getByRole("button", { name: "Send response" }).click();
  await expect(page.getByText("Your response is part of the archive")).toBeVisible();

  expect(new Set(seenApiRequests)).toEqual(new Set([
    "GET /api/shelf",
    "GET /api/showcase",
    "GET /api/prepared-reference-assets/70000000-0000-4000-8000-000000000020/image",
    "POST /api/resolve-input",
    "POST /api/resolve-input/resolution-1/select",
    "GET /api/books",
    "POST /api/director-preview",
    "POST /api/video-jobs",
    "GET /api/video-jobs/job-1",
    "POST /api/feedback",
  ]));
});

test("plays four previously generated AMD films in a flow isolated from live jobs", async ({ page }) => {
  let finalJobPosts = 0;

  await page.route("http://127.0.0.1:4174/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname === "/api/showcase") {
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(showcasePayload) });
    }
    if (url.pathname === "/api/shelf") {
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ books: [] }) });
    }
    if (url.pathname.startsWith("/api/showcase-media/")) {
      return route.fulfill({
        status: 206,
        contentType: "video/mp4",
        headers: {
          "Accept-Ranges": "bytes",
          "Content-Range": "bytes 0-0/1",
          "Content-Length": "1",
        },
        body: Buffer.from([0]),
      });
    }
    if (url.pathname === "/api/video-jobs" && request.method() === "POST") finalJobPosts += 1;
    return route.abort();
  });

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Steve Jobs" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Su Dongpo" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Frida Kahlo" })).toBeVisible();
  await expect(page.getByRole("button", { name: /^Play .+ — .+$/ })).toHaveCount(4);
  await expect(page.getByText("3 lives · 4 films")).toBeVisible();
  expect(finalJobPosts).toBe(0);

  await page.getByRole("button", { name: "Play The Garage Before the World — Steve Jobs" }).click();
  const player = page.getByLabel("Previously generated on AMD: The Garage Before the World");
  await expect(player).toBeVisible();
  await expect(player).toHaveAttribute("controls", "");
  await expect(player).toHaveAttribute("src", "/api/showcase-media/jobs-garage");
  await expect(page.getByRole("button", { name: "Start generation" })).toHaveCount(0);
  expect(finalJobPosts).toBe(0);

  await page.getByRole("button", { name: "Back to Choose a life" }).click();
  await expect(page.getByRole("heading", { name: "Choose a life" })).toBeVisible();
  expect(finalJobPosts).toBe(0);
});
