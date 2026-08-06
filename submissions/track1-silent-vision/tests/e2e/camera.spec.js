const { test, expect } = require("@playwright/test");

const phraseCatalog = [
  {
    phraseId: "zh_light_on_hello",
    text: "你好，请帮我打开灯",
    language: "zh",
    intent: "LIGHT_ON",
    enabled: true,
  },
  {
    phraseId: "en_light_on_hello",
    text: "Hello, please turn on the light.",
    language: "en",
    intent: "LIGHT_ON",
    enabled: true,
  },
];

const staleHttpCatalog = [
  {
    phraseId: "zh_stale_http",
    text: "迟到的目录",
    language: "zh",
    intent: "CHAT_OTHER",
    enabled: true,
  },
];

async function installRecordingFakes(page, {
  readyDelayMs = null,
  serverErrorStage = null,
  websocketCatalog = phraseCatalog,
} = {}) {
  await page.addInitScript(({ catalog, readyDelayMs: delayMs, serverErrorStage: errorStage }) => {
    window.sentWebSocketMessages = [];
    window.recordingTestCounters = {
      sessionRequests: 0,
      websocketConnections: 0,
      cameraRequests: 0,
    };
    window.operationErrorCounters = {
      binaryUploads: 0,
      cameraStops: 0,
      clipReceivedEvents: 0,
      socketCloses: 0,
    };
    const nativeFetch = window.fetch.bind(window);
    window.fetch = async (input, init) => {
      const rawUrl = typeof input === "string" ? input : input.url;
      const url = new URL(rawUrl, window.location.origin);
      if (url.pathname !== "/api/sessions") return nativeFetch(input, init);
      window.recordingTestCounters.sessionRequests += 1;
      return new Response(
        JSON.stringify({ sessionId: "browser-test-session" }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    };

    class FakeWebSocket {
      static OPEN = 1;

      constructor() {
        window.recordingTestCounters.websocketConnections += 1;
        this.readyState = FakeWebSocket.OPEN;
        Promise.resolve().then(() => {
          this.onopen?.();
          const sendReady = () => this.onmessage?.({
            data: JSON.stringify({
              type: "session.ready",
              parameters: {
                captureFps: 25,
                captureCountdownSeconds: 0,
                commandClipMaxSeconds: 0.001,
                phraseCatalog: catalog,
              },
            }),
          });
          if (delayMs === null) sendReady();
          else window.setTimeout(sendReady, delayMs);
        });
      }

      send(message) {
        window.sentWebSocketMessages.push(message);
        if (message instanceof Blob) {
          window.operationErrorCounters.binaryUploads += 1;
          if (errorStage === "after-received") {
            Promise.resolve().then(() => {
              window.operationErrorCounters.clipReceivedEvents += 1;
              this.onmessage?.({
                data: JSON.stringify({ type: "clip.received", bytes: message.size }),
              });
              this.onmessage?.({
                data: JSON.stringify({
                  type: "error",
                  code: "INTERNAL_ERROR",
                  message: "command clip processing failed",
                  recoverable: true,
                }),
              });
            });
          }
          return;
        }
        if (errorStage === "before-upload" && JSON.parse(message).type === "clip.start") {
          Promise.resolve().then(() => this.onmessage?.({
            data: JSON.stringify({
              type: "error",
              code: "INVALID_REQUEST",
              message: "clip request rejected",
              recoverable: true,
            }),
          }));
        }
      }

      close() {
        window.operationErrorCounters.socketCloses += 1;
        this.readyState = 3;
      }
    }

    window.WebSocket = FakeWebSocket;
    Object.defineProperty(navigator.mediaDevices, "getUserMedia", {
      configurable: true,
      value: async () => {
        window.recordingTestCounters.cameraRequests += 1;
        const stream = new MediaStream();
        Object.defineProperty(stream, "getTracks", {
          configurable: true,
          value: () => [{
            stop: () => {
              window.operationErrorCounters.cameraStops += 1;
            },
          }],
        });
        return stream;
      },
    });
    HTMLMediaElement.prototype.play = async () => {};
    window.MediaRecorder = class {
      static isTypeSupported() {
        return true;
      }

      constructor() {
        this.state = "inactive";
      }

      start() {
        this.state = "recording";
      }

      stop() {
        this.state = "inactive";
        this.onstop?.();
      }
    };
  }, { catalog: websocketCatalog, readyDelayMs, serverErrorStage });
}

async function routePhraseCatalog(page, { catalog = phraseCatalog, status = 200 } = {}) {
  await page.route("**/api/phrases", (route) => route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(status === 200 ? { phrases: catalog } : { error: "failed" }),
  }));
}

async function deferPhraseCatalog(page, { catalog = staleHttpCatalog, status = 200 } = {}) {
  let releaseRequest;
  const gate = new Promise((resolve) => {
    releaseRequest = resolve;
  });
  await page.route("**/api/phrases", async (route) => {
    await gate;
    await route.fulfill({
      status,
      contentType: "application/json",
      body: JSON.stringify(status === 200 ? { phrases: catalog } : { error: "failed" }),
    });
  });
  return releaseRequest;
}

async function recordingCounters(page) {
  return page.evaluate(() => window.recordingTestCounters);
}

async function operationErrorCounters(page) {
  return page.evaluate(() => window.operationErrorCounters);
}

async function phraseOptionValues(page) {
  return page.locator("#calibration-phrase-id option").evaluateAll((options) => (
    options.map((option) => option.value)
  ));
}

async function sentMessage(page, type) {
  return page.evaluate((messageType) => window.sentWebSocketMessages
    .map((message) => {
      try {
        return JSON.parse(message);
      } catch {
        return null;
      }
    })
    .filter((message) => message?.type === messageType)
    .at(-1), type);
}

test("home page exposes camera controls and status", async ({ page }) => {
  await page.goto("http://127.0.0.1:8000/");
  await expect(page.locator("#startButton")).toBeVisible();
  await expect(page.locator("#cameraStatus")).toContainText("idle");
  await expect(page.locator("#bufferStatus")).toContainText("waiting");
});

test("waits for the catalog before fresh-page calibration", async ({ page }) => {
  await routePhraseCatalog(page);
  await installRecordingFakes(page, { readyDelayMs: 50 });
  await page.goto("http://127.0.0.1:8000/");

  await page.locator("#save-sample").click();
  await expect.poll(() => sentMessage(page, "calibration.start")).toEqual({
    type: "calibration.start",
    profileId: "global",
    language: "zh",
    phraseId: "zh_light_on_hello",
    phrase: "",
    scope: "global",
  });
});

test("records the selected language and catalog phrase", async ({ page }) => {
  await routePhraseCatalog(page);
  await installRecordingFakes(page);
  await page.goto("http://127.0.0.1:8000/");

  await expect(page.locator("#recognition-language option")).toHaveCount(2);
  expect(await page.locator("#recognition-language option").evaluateAll((options) => (
    options.map((option) => option.value)
  ))).toEqual(["zh", "en"]);
  await expect(page.locator("#calibration-language")).toBeVisible();
  await expect(page.locator("#calibration-phrase-id")).toBeVisible();
  await expect(page.locator("#calibration-unknown-phrase")).toBeVisible();
  await expect(page.locator("#calibration-intent")).toHaveCount(0);

  await page.locator("#recognition-language").selectOption("en");
  await page.locator("#startButton").click();
  await page.waitForFunction(() => window.sentWebSocketMessages.some((message) => {
    try {
      return JSON.parse(message).type === "clip.start";
    } catch {
      return false;
    }
  }));
  await expect.poll(() => sentMessage(page, "clip.start")).toEqual({
    type: "clip.start",
    profileId: "global",
    language: "en",
  });

  await page.locator("#calibration-language").selectOption("en");
  await expect.poll(() => phraseOptionValues(page)).toEqual([
    "en_light_on_hello",
    "UNKNOWN",
  ]);
  await expect(page.locator("#calibration-unknown-phrase")).toBeDisabled();
  await expect(page.locator("#calibration-unknown-phrase")).not.toHaveAttribute("required", "");

  await page.locator("#calibration-phrase-id").selectOption("UNKNOWN");
  await expect(page.locator("#calibration-unknown-phrase")).toBeEnabled();
  await expect(page.locator("#calibration-unknown-phrase")).toHaveAttribute("required", "");
  await page.locator("#calibration-unknown-phrase").fill("What time is it?");

  await page.locator("#stopButton").click();
  await expect(page.locator("#save-sample")).toBeEnabled();
  await page.locator("#save-sample").click();
  await expect.poll(() => sentMessage(page, "calibration.start")).toEqual({
    type: "calibration.start",
    profileId: "global",
    language: "en",
    phraseId: "UNKNOWN",
    phrase: "What time is it?",
    scope: "global",
  });

  await page.locator("#calibration-language").selectOption("zh");
  await expect.poll(() => phraseOptionValues(page)).toEqual([
    "zh_light_on_hello",
    "UNKNOWN",
  ]);
  await page.locator("#calibration-phrase-id").selectOption("zh_light_on_hello");
  await expect(page.locator("#calibration-unknown-phrase")).toBeDisabled();

  await page.locator("#stopButton").click();
  await expect(page.locator("#save-sample")).toBeEnabled();
  await page.locator("#save-sample").click();
  await expect.poll(() => sentMessage(page, "calibration.start")).toEqual({
    type: "calibration.start",
    profileId: "global",
    language: "zh",
    phraseId: "zh_light_on_hello",
    phrase: "",
    scope: "global",
  });
});

test("preloads phrases without starting a session, socket, or camera", async ({ page }) => {
  await routePhraseCatalog(page);
  await installRecordingFakes(page);
  await page.goto("http://127.0.0.1:8000/");

  await expect(page.locator("#recognition-language option")).toHaveText(["Chinese", "English"]);
  await expect(page.locator("#calibration-language option")).toHaveText(["Chinese", "English"]);
  await expect.poll(() => phraseOptionValues(page)).toEqual([
    "zh_light_on_hello",
    "UNKNOWN",
  ]);
  await expect(page.locator("#save-sample")).toBeEnabled();
  await expect.poll(() => recordingCounters(page)).toEqual({
    sessionRequests: 0,
    websocketConnections: 0,
    cameraRequests: 0,
  });
});

test("recovers from a server error before clip upload", async ({ page }) => {
  await routePhraseCatalog(page);
  await installRecordingFakes(page, { serverErrorStage: "before-upload" });
  await page.goto("http://127.0.0.1:8000/");

  await page.locator("#startButton").click();

  await expect(page.locator("#visionStatus")).toHaveText(
    "INVALID_REQUEST: clip request rejected",
  );
  await expect(page.locator("#cameraStatus")).toHaveText("stopped");
  await expect(page.locator("#socketStatus")).toHaveText("closed");
  await expect(page.locator("#startButton")).toBeEnabled();
  await expect(page.locator("#stopButton")).toBeDisabled();
  await expect.poll(() => operationErrorCounters(page)).toEqual({
    binaryUploads: 0,
    cameraStops: 1,
    clipReceivedEvents: 0,
    socketCloses: 1,
  });
  await page.waitForTimeout(50);
  await expect(page.locator("#visionStatus")).toHaveText(
    "INVALID_REQUEST: clip request rejected",
  );
});

test("recovers from a server error after clip.received", async ({ page }) => {
  await routePhraseCatalog(page);
  await installRecordingFakes(page, { serverErrorStage: "after-received" });
  await page.goto("http://127.0.0.1:8000/");

  await page.locator("#startButton").click();

  await expect(page.locator("#visionStatus")).toHaveText(
    "INTERNAL_ERROR: command clip processing failed",
  );
  await expect(page.locator("#cameraStatus")).toHaveText("stopped");
  await expect(page.locator("#socketStatus")).toHaveText("closed");
  await expect(page.locator("#startButton")).toBeEnabled();
  await expect(page.locator("#stopButton")).toBeDisabled();
  await expect.poll(() => operationErrorCounters(page)).toEqual({
    binaryUploads: 1,
    cameraStops: 1,
    clipReceivedEvents: 1,
    socketCloses: 1,
  });
  await page.waitForTimeout(50);
  await expect(page.locator("#visionStatus")).toHaveText(
    "INTERNAL_ERROR: command clip processing failed",
  );
});

test("keeps calibration disabled when phrase loading fails", async ({ page }) => {
  await routePhraseCatalog(page, { status: 503 });
  await installRecordingFakes(page);
  await page.goto("http://127.0.0.1:8000/");

  await expect(page.locator("#calibration-phrase-id")).toHaveText("Unable to load phrases");
  await expect(page.locator("#calibration-phrase-id")).toBeDisabled();
  await expect(page.locator("#save-sample")).toBeDisabled();
  await expect(page.locator("#startButton")).toBeEnabled();

  await page.locator("#stopButton").evaluate((button) => {
    button.disabled = false;
    button.click();
  });
  await expect(page.locator("#save-sample")).toBeDisabled();

  await page.locator("#startButton").click();
  await expect.poll(() => phraseOptionValues(page)).toEqual([
    "zh_light_on_hello",
    "UNKNOWN",
  ]);
  await page.locator("#stopButton").click();
  await expect(page.locator("#save-sample")).toBeEnabled();
});

test("allows UNKNOWN when the selected language has no registered phrase", async ({ page }) => {
  const englishOnlyCatalog = phraseCatalog.filter((phrase) => phrase.language === "en");
  await routePhraseCatalog(page, { catalog: englishOnlyCatalog });
  await installRecordingFakes(page, { websocketCatalog: englishOnlyCatalog });
  await page.goto("http://127.0.0.1:8000/");

  await expect.poll(() => phraseOptionValues(page)).toEqual(["UNKNOWN"]);
  await expect(page.locator("#calibration-unknown-phrase")).toBeEnabled();
  await expect(page.locator("#save-sample")).toBeEnabled();
});

for (const lateStatus of [200, 503]) {
  test(`ignores a late HTTP ${lateStatus} after session.ready`, async ({ page }) => {
    const releaseHttp = await deferPhraseCatalog(page, {
      catalog: staleHttpCatalog,
      status: lateStatus,
    });
    await installRecordingFakes(page, { websocketCatalog: phraseCatalog });
    await page.goto("http://127.0.0.1:8000/");

    await expect(page.locator("#calibration-phrase-id")).toHaveText("Loading phrases...");
    await expect(page.locator("#save-sample")).toBeDisabled();

    await page.locator("#startButton").click();
    await expect.poll(() => phraseOptionValues(page)).toEqual([
      "zh_light_on_hello",
      "UNKNOWN",
    ]);

    const responseFinished = page.waitForResponse((response) => (
      response.url().endsWith("/api/phrases") && response.status() === lateStatus
    ));
    releaseHttp();
    await responseFinished;

    await expect.poll(() => phraseOptionValues(page)).toEqual([
      "zh_light_on_hello",
      "UNKNOWN",
    ]);
    await expect(page.locator("#calibration-phrase-id option").first()).not.toHaveValue("zh_stale_http");
  });
}
