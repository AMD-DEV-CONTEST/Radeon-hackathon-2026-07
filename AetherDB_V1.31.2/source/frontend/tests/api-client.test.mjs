import test from "node:test";
import assert from "node:assert/strict";

import {
  ApiError,
  StreamSequenceBuffer,
  buildQuery,
  configureApiClient,
  request,
} from "../src/api/client.js";
import { createImportTask, confirmImportTask, analyzeImportTask } from "../src/api/import.js";
import {
  createEntityStateSegment,
  createTemporalAnchor,
  createTemporalRelation,
  createTimeline,
  getChapterTemporalContext,
  getEntityStateHistory,
  getResolvedEntityState,
  getTemporalEventMetadata,
  listTemporalAnchors,
  listTemporalRelations,
  listTimelines,
  setChapterTemporalContext,
  setTemporalEventMetadata,
} from "../src/api/temporal.js";
import {
  approveContextCandidates,
  buildEvidencePack,
  createContextMap,
  getContextCandidates,
  listContextTasks,
} from "../src/api/context.js";
import { confirmChangeSet, getChangeSet } from "../src/api/changesets.js";
import { getAuthStatus } from "../src/api/auth.js";
import {
  cancelVectorTask,
  createVectorTask,
  getHardwareAccelerationStatus,
  getVectorIndexStatus,
  getVectorTask,
  listVectorTasks,
  rebuildVectorIndex,
  retryFailedVectorItems,
} from "../src/api/vectorIndex.js";
import {
  createModelBinding,
  createModelProfile,
  createModelProvider,
  confirmModelRecovery,
  confirmModelDataManifest,
  createModelDataManifest,
  executeModelStream,
  getAnalysisPreferences,
  getModelManagementOverview,
  getModelDataManifest,
  testModelProvider,
  updateAnalysisPreferences,
} from "../src/api/models.js";
import {
  cancelOllamaInstallOperation,
  cancelOllamaExecution,
  cancelOllamaOperation,
  confirmOllamaInstallDownload,
  createOllamaInstallOperation,
  getOllamaInstallPlan,
  getOllamaStatus,
  listOllamaExecutions,
  listOllamaObservations,
  launchOllamaInstaller,
  pullOllamaModel,
  startOllama,
  stopOllama,
  syncOllamaModels,
} from "../src/api/ollama.js";
import { activateBook, activateDatabase, createBook, createDatabase, initializeDatabase, updateBook } from "../src/api/settings.js";
import {
  analyzeChapter,
  approveChapterTranslation,
  autosaveChapter,
  buildChapterChangeSet,
  createChapter,
  createChapterLocalization,
  createChapterTranslation,
  getChapter,
  listChapterLocalizations,
  listChapterTranslations,
  listChapters,
  listChapterVersions,
  listTranslationModels,
  rejectChapterTranslation,
  reviewChapterLocalization,
  saveChapter,
  updateChapterTranslation,
} from "../src/api/chapters.js";
import {
  createEntity,
  getEntities,
  getEntityTranslations,
  reviewEntityTranslation,
  saveEntityTranslation,
} from "../src/api/entities.js";
import {
  approveMediaAsset,
  createMediaBinding,
  deleteMediaBinding,
  listEffectiveChapterMedia,
  listMediaAssets,
  loadMediaContent,
  reviewMediaAnnotation,
  uploadMediaAsset,
} from "../src/api/mediaAssets.js";
import {
  activateMediaVisualSpace,
  cancelMediaVisualMigration,
  createMediaVisualSpace,
  garbageCollectMediaVisualSpace,
  getMediaVisionStatus,
  getMediaVisualMigration,
  indexMediaVisionAsset,
  indexMediaVisionBatch,
  listMediaVisualMigrations,
  listMediaVisualSpaces,
  removeMediaVisionAsset,
  retryMediaVisualMigration,
  rollbackMediaVisualSpace,
  searchMediaVisionImage,
  searchMediaVisionText,
  validateMediaVisualSpace,
} from "../src/api/mediaVision.js";
import {
  cancelMediaGenerationTask,
  createMediaGenerationTask,
  getMediaGenerationStatus,
  getMediaGenerationTask,
  listMediaGenerationEvents,
  listMediaGenerationTasks,
  retryMediaGenerationTask,
} from "../src/api/mediaGeneration.js";
import {
  cancelAudioTask,
  createAudioTask,
  createPronunciationEntry,
  createVoiceProfile,
  deletePronunciationEntry,
  getAudioAsset,
  getAudioContractStatus,
  getAudioTask,
  getAudioWaveform,
  listAudioTaskEvents,
  listAudioTasks,
  listPronunciationEntries,
  listVoiceProfiles,
  registerAudioOutput,
  registerAudioResult,
  retryAudioTask,
  reviewAudioResult,
  updatePronunciationEntry,
  updateVoiceProfile,
} from "../src/api/audioContract.js";
import {
  acceptModelPackageLicense,
  cancelModelPackageOperation,
  checkModelPackageDistribution,
  installModelPackage,
  listModelPackageOperations,
  listModelPackages,
  retryModelPackageOperation,
  uninstallModelPackage,
  verifyModelPackage,
} from "../src/api/modelPackages.js";
import {
  cancelModelRuntimeJob,
  evaluateModelAdmission,
  getModelRuntimeJob,
  getModelRuntimePolicy,
  getModelRuntimeResources,
  getModelWorker,
  listModelCoexistenceEvidence,
  listModelRuntimeEvidence,
  listModelRuntimeJobs,
  listModelRuntimeLeases,
  listModelRuntimeDrift,
  listModelWorkers,
  loadModelWorker,
  probeModelWorker,
  reconcileModelRuntimeDrift,
  startModelWorker,
  stopModelWorker,
  unloadModelWorker,
  updateModelRuntimePolicy,
} from "../src/api/modelRuntime.js";


test("buildQuery omits empty values and preserves arrays", () => {
  assert.equal(buildQuery({ q: "星 港", empty: "", tags: ["a", "b"] }), "?q=%E6%98%9F+%E6%B8%AF&tags=a&tags=b");
});


test("desktop client accepts only an explicit dynamic loopback API endpoint", async () => {
  globalThis.sessionStorage = { getItem: () => "test-key" };
  globalThis.fetch = async (url) => {
    assert.equal(url, "http://127.0.0.1:43127/api/status");
    return new Response(JSON.stringify({ ok: true }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };

  configureApiClient({ baseUrl: "http://127.0.0.1:43127/api" });
  await request("/status", { method: "GET" });
  assert.throws(
    () => configureApiClient({ baseUrl: "http://example.com:43127/api" }),
    /dynamic 127\.0\.0\.1/,
  );
  configureApiClient({ baseUrl: "/api", apiKey: "" });
});


test("desktop owner credential stays in client memory and overrides browser storage", async () => {
  globalThis.sessionStorage = { getItem: () => "browser-fallback-key" };
  globalThis.fetch = async (url, options) => {
    assert.equal(url, "http://127.0.0.1:43128/api/auth/status");
    assert.equal(options.headers.get("X-API-Key"), "ephemeral-owner-session");
    return new Response(JSON.stringify({ authenticated: true, effective_role: "owner" }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };

  configureApiClient({
    baseUrl: "http://127.0.0.1:43128/api",
    apiKey: "ephemeral-owner-session",
  });
  await request("/auth/status", { method: "GET" });
  configureApiClient({ baseUrl: "/api", apiKey: "" });
});


test("request exposes structured API errors without flattening detail", async () => {
  configureApiClient({ baseUrl: "/api", timeoutMs: 1000 });
  globalThis.sessionStorage = { getItem: () => "test-key" };
  globalThis.fetch = async (url, options) => {
    assert.equal(options.headers.get("X-API-Key"), "test-key");
    return new Response(JSON.stringify({ detail: { code: "AMBIGUOUS", message: "Choose a model" } }), {
      status: 409,
      headers: { "content-type": "application/json" },
    });
  };

  await assert.rejects(
    request("/route", { method: "GET" }),
    (error) => error instanceof ApiError && error.status === 409 && error.code === "AMBIGUOUS",
  );
});


test("connection refusal is classified as backend unavailable without a generic network error", async () => {
  configureApiClient({ baseUrl: "/api", timeoutMs: 1000 });
  globalThis.sessionStorage = { getItem: () => "test-key" };
  globalThis.fetch = async () => {
    throw new TypeError("fetch failed");
  };

  await assert.rejects(
    request("/stats", { method: "GET" }),
    (error) => (
      error instanceof ApiError
      && error.code === "BACKEND_UNAVAILABLE"
      && !error.message.includes("Network request failed")
    ),
  );
});


test("local API timeout is bounded and classified separately", async () => {
  configureApiClient({ baseUrl: "/api", timeoutMs: 5 });
  globalThis.fetch = (_url, options) => new Promise((_resolve, reject) => {
    options.signal.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
  });

  await assert.rejects(
    request("/stats", { method: "GET" }),
    (error) => error instanceof ApiError && error.code === "BACKEND_TIMEOUT",
  );
});


test("authentication failures use the stable API unauthorized code", async () => {
  configureApiClient({ baseUrl: "/api", timeoutMs: 1000 });
  globalThis.fetch = async () => new Response(JSON.stringify({ detail: "Not authorized" }), {
    status: 401,
    headers: { "content-type": "application/json" },
  });

  await assert.rejects(
    request("/stats", { method: "GET" }),
    (error) => error instanceof ApiError && error.code === "API_UNAUTHORIZED",
  );
});


test("model diagnostics reject failed 200 responses with a model-specific code", async () => {
  configureApiClient({ baseUrl: "/api", timeoutMs: 1000 });
  globalThis.fetch = async () => new Response(JSON.stringify({
    status: "failed",
    error: { code: "AUTH_FAILED", message: "Provider authentication failed" },
  }), {
    status: 200,
    headers: { "content-type": "application/json" },
  });

  await assert.rejects(
    testModelProvider("cloud-main"),
    (error) => error instanceof ApiError && error.code === "API_UNAUTHORIZED",
  );
});


test("stream sequence buffer reorders and deduplicates events", () => {
  const buffer = new StreamSequenceBuffer();
  const event = (sequence) => ({ protocol_version: "1.0", sequence, event: "final_delta" });

  assert.deepEqual(buffer.push(event(1)), []);
  assert.deepEqual(buffer.push(event(0)).map((item) => item.sequence), [0, 1]);
  assert.deepEqual(buffer.push(event(1)), []);
  assert.deepEqual(buffer.push({ ...event(2), protocol_version: "2.0" }), []);
  assert.deepEqual(buffer.push(event(2)).map((item) => item.sequence), [2]);
});


test("domain SDK routes durable import, temporal, and context workflows through AetherDB", async () => {
  configureApiClient({ baseUrl: "/api", timeoutMs: 1000 });
  globalThis.sessionStorage = { getItem: () => "test-key" };
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push({ url, method: options.method, body: options.body ? JSON.parse(options.body) : null });
    return new Response(JSON.stringify({ ok: true }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };

  await createImportTask({ database_id: "default", book_id: "default", text: "notes" });
  await confirmImportTask("import-1", { preview_hash: "a".repeat(64), entity_selections: [] });
  await analyzeImportTask("import-1", "local_rules");
  await createTemporalAnchor({ database_id: "default", book_id: "default", anchor_type: "unknown", label: "Now" });
  await getResolvedEntityState("CHAR_1", { database_id: "default", book_id: "default" });
  await createContextMap({
    task_type: "creative_assist",
    database_id: "default",
    book_id: "default",
    needs: [{ context_type: "mentioned_entities", query: "Lin", reason: "author review" }],
  });
  await getContextCandidates("context-1", "world one");
  await approveContextCandidates("context-1", "world one", [{ candidate_id: `ctx-${"b".repeat(32)}`, approved: true }]);
  await buildEvidencePack("context-1", "world one", {
    total_context_tokens: 4096,
    reserved_instruction: 256,
    reserved_current_text: 512,
    reserved_evidence: 1024,
    reserved_output: 1024,
  });
  await executeModelStream({
    task_type: "creative_assist",
    database_id: "default",
    book_id: "default",
    messages: [{ role: "user", content: "Continue" }],
  });

  assert.deepEqual(calls.map((item) => [item.method, item.url]), [
    ["POST", "/api/import/tasks"],
    ["POST", "/api/import/tasks/import-1/confirm"],
    ["POST", "/api/import/tasks/import-1/analyze"],
    ["POST", "/api/temporal/anchors"],
    ["GET", "/api/entities/CHAR_1/resolved-state?database_id=default&book_id=default"],
    ["POST", "/api/context/map"],
    ["GET", "/api/context/tasks/context-1/candidates?database_id=world+one"],
    ["POST", "/api/context/tasks/context-1/approval?database_id=world+one"],
    ["POST", "/api/context/tasks/context-1/evidence-pack?database_id=world+one"],
    ["POST", "/api/model-routing/execute-stream"],
  ]);
  assert.deepEqual(calls[2].body, { analysis_mode: "local_rules" });
});

test("temporal SDK covers timelines, partial order, entity state, and chapter context", async () => {
  configureApiClient({ baseUrl: "/api", timeoutMs: 1000 });
  globalThis.sessionStorage = { getItem: () => "author-key" };
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push([
      options.method,
      url,
      options.body ? JSON.parse(options.body) : null,
    ]);
    return new Response(JSON.stringify({ status: "ok" }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };

  const scope = { database_id: "world-db", book_id: "book-one" };
  await listTimelines(scope);
  await createTimeline({ ...scope, name: "Main branch", status: "active" });
  await listTemporalAnchors({ ...scope, timeline_id: "TL_MAIN" });
  await createTemporalAnchor({
    ...scope,
    timeline_id: "TL_MAIN",
    anchor_type: "order_only",
    label: "Opening",
  });
  await listTemporalRelations({ ...scope, timeline_id: "TL_MAIN" });
  await createTemporalRelation({
    ...scope,
    timeline_id: "TL_MAIN",
    source_anchor_id: "TA_A",
    relation_type: "before",
    target_anchor_id: "TA_B",
  });
  await createEntityStateSegment({
    ...scope,
    entity_id: "CHAR_1",
    timeline_id: "TL_MAIN",
    state_type: "location",
    state_payload: { place: "North gate" },
  });
  await getEntityStateHistory("CHAR_1", { ...scope, timeline_id: "TL_MAIN" });
  await getResolvedEntityState("CHAR_1", {
    ...scope,
    timeline_id: "TL_MAIN",
    anchor_id: "TA_A",
  });
  await getChapterTemporalContext("CHP_1", scope);
  await setChapterTemporalContext("CHP_1", {
    ...scope,
    timeline_id: "TL_MAIN",
    anchor_id: "TA_A",
    include_future_knowledge: false,
  });
  await getTemporalEventMetadata("7", scope);
  await setTemporalEventMetadata("7", {
    ...scope,
    timeline_id: "TL_MAIN",
    world_anchor_id: "TA_A",
  });

  assert.deepEqual(calls, [
    ["GET", "/api/temporal/timelines?database_id=world-db&book_id=book-one", null],
    ["POST", "/api/temporal/timelines", { ...scope, name: "Main branch", status: "active" }],
    ["GET", "/api/temporal/anchors?database_id=world-db&book_id=book-one&timeline_id=TL_MAIN", null],
    ["POST", "/api/temporal/anchors", {
      ...scope,
      timeline_id: "TL_MAIN",
      anchor_type: "order_only",
      label: "Opening",
    }],
    ["GET", "/api/temporal/relations?database_id=world-db&book_id=book-one&timeline_id=TL_MAIN", null],
    ["POST", "/api/temporal/relations", {
      ...scope,
      timeline_id: "TL_MAIN",
      source_anchor_id: "TA_A",
      relation_type: "before",
      target_anchor_id: "TA_B",
    }],
    ["POST", "/api/temporal/state-segments", {
      ...scope,
      entity_id: "CHAR_1",
      timeline_id: "TL_MAIN",
      state_type: "location",
      state_payload: { place: "North gate" },
    }],
    ["GET", "/api/entities/CHAR_1/state-history?database_id=world-db&book_id=book-one&timeline_id=TL_MAIN", null],
    ["GET", "/api/entities/CHAR_1/resolved-state?database_id=world-db&book_id=book-one&timeline_id=TL_MAIN&anchor_id=TA_A", null],
    ["GET", "/api/chapters/CHP_1/temporal-context?database_id=world-db&book_id=book-one", null],
    ["PUT", "/api/chapters/CHP_1/temporal-context", {
      ...scope,
      timeline_id: "TL_MAIN",
      anchor_id: "TA_A",
      include_future_knowledge: false,
    }],
    ["GET", "/api/temporal/events/7/metadata?database_id=world-db&book_id=book-one", null],
    ["PUT", "/api/temporal/events/7/metadata", {
      ...scope,
      timeline_id: "TL_MAIN",
      world_anchor_id: "TA_A",
    }],
  ]);
});


test("AI management and local runtime SDKs keep all calls behind AetherDB", async () => {
  configureApiClient({ baseUrl: "/api", timeoutMs: 1000 });
  globalThis.sessionStorage = { getItem: () => "admin-key" };
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push({ url, method: options.method, body: options.body ? JSON.parse(options.body) : null });
    return new Response(JSON.stringify({ status: "ok" }), { status: 200, headers: { "content-type": "application/json" } });
  };

  await getModelManagementOverview();
  await getAnalysisPreferences();
  await updateAnalysisPreferences("local_rules");
  await createModelProvider({ id: "deepseek", display_name: "DeepSeek" });
  await testModelProvider("deepseek");
  await createModelProfile({ id: "deepseek:chat", provider_id: "deepseek" });
  await createModelBinding({ id: "global:creative", target_id: "deepseek:chat" });
  await confirmModelRecovery("a".repeat(32), "deepseek:chat");
  await getOllamaStatus("ollama-local");
  await listOllamaObservations("ollama-local");
  await listOllamaExecutions(null, 50);
  await cancelOllamaExecution("execution-1");
  await startOllama("ollama-local");
  await stopOllama("ollama-local");
  await getOllamaInstallPlan("rocm");
  await createOllamaInstallOperation("rocm");
  await confirmOllamaInstallDownload("install-1");
  await cancelOllamaInstallOperation("install-1");
  await launchOllamaInstaller("install-1", "0.32.0");
  await syncOllamaModels("ollama-local");
  await pullOllamaModel("deepseek-r1:8b", "ollama-local");
  await cancelOllamaOperation("pull-1");
  const manifestPayload = {
    task_id: "task-1",
    task_type: "creative_assist",
    database_id: "default",
    book_id: "book-one",
    messages: [{ role: "user", content: "Continue." }],
  };
  await createModelDataManifest(manifestPayload);
  await getModelDataManifest("a".repeat(32));
  await confirmModelDataManifest("a".repeat(32));

  assert.deepEqual(calls.map((item) => [item.method, item.url]), [
    ["GET", "/api/ai-management/overview"],
    ["GET", "/api/ai/analysis-preferences"],
    ["PUT", "/api/ai/analysis-preferences"],
    ["POST", "/api/model-providers"],
    ["POST", "/api/model-providers/deepseek/test-connection"],
    ["POST", "/api/model-profiles"],
    ["POST", "/api/model-routing/bindings"],
    ["POST", `/api/model-routing/recovery/${"a".repeat(32)}/confirm`],
    ["GET", "/api/ollama/status?provider_id=ollama-local"],
    ["GET", "/api/ollama/observations?provider_id=ollama-local"],
    ["GET", "/api/ollama/executions?limit=50"],
    ["POST", "/api/ollama/executions/execution-1/cancel"],
    ["POST", "/api/ollama/start"],
    ["POST", "/api/ollama/stop"],
    ["GET", "/api/ollama/install/plan?accelerator=rocm"],
    ["POST", "/api/ollama/install/operations"],
    ["POST", "/api/ollama/install/operations/install-1/confirm-download"],
    ["POST", "/api/ollama/install/operations/install-1/cancel"],
    ["POST", "/api/ollama/install/operations/install-1/launch"],
    ["POST", "/api/ollama/models/sync"],
    ["POST", "/api/ollama/models/pull"],
    ["POST", "/api/ollama/operations/pull-1/cancel"],
    ["POST", "/api/model-routing/data-manifests"],
    ["GET", `/api/model-routing/data-manifests/${"a".repeat(32)}`],
    ["POST", `/api/model-routing/data-manifests/${"a".repeat(32)}/confirm`],
  ]);
  assert.deepEqual(calls[2].body, { default_mode: "local_rules" });
  assert.deepEqual(calls[7].body, { model_profile_id: "deepseek:chat" });
  assert.deepEqual(calls[15].body, { accelerator: "rocm" });
  assert.deepEqual(calls[18].body, { confirm_version: "0.32.0" });
  assert.deepEqual(calls[19].body, { provider_id: "ollama-local" });
  assert.deepEqual(calls[22].body, manifestPayload);
});


test("world creation SDK preserves query-based backend compatibility", async () => {
  configureApiClient({ baseUrl: "/api", timeoutMs: 1000 });
  globalThis.sessionStorage = { getItem: () => "admin-key" };
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push([options.method, url]);
    return new Response(JSON.stringify({ status: "ok" }), { status: 200, headers: { "content-type": "application/json" } });
  };

  await createDatabase({ name: "World One", author: "Author", description: "Notes" });
  await initializeDatabase("world_one");
  await activateDatabase("world_one");
  await createBook({ bookId: "book_one", title: "Book One", databaseId: "world_one" });
  await updateBook("book_one", { title: "Book One", description: "Story", author: "Author", databaseId: "world_one" });
  await activateBook("book_one");

  assert.deepEqual(calls, [
    ["POST", "/api/databases?name=World+One&author=Author&description=Notes"],
    ["POST", "/api/databases/world_one/init-db"],
    ["POST", "/api/databases/world_one/activate"],
    ["POST", "/api/books?book_id=book_one&title=Book+One&database_id=world_one"],
    ["PUT", "/api/books/book_one?title=Book+One&description=Story&author=Author&database_id=world_one"],
    ["POST", "/api/books/activate?book_id=book_one"],
  ]);
});


test("quick creation SDK sends typed entity content to the selected book", async () => {
  configureApiClient({ baseUrl: "/api", timeoutMs: 1000 });
  globalThis.sessionStorage = { getItem: () => "user-key" };
  let captured = null;
  globalThis.fetch = async (url, options) => {
    captured = { url, method: options.method, body: JSON.parse(options.body) };
    return new Response(JSON.stringify({ entity_id: "CHAR_0001" }), { status: 200, headers: { "content-type": "application/json" } });
  };

  await createEntity({
    entity_type: "character",
    title: "Lin",
    content: "# Lin\n\n## 首次出现年龄\n18",
    tags: ["主角"],
    importance: 8,
    book_id: "book_one",
  });

  assert.deepEqual(captured, {
    url: "/api/entity",
    method: "POST",
    body: {
      entity_type: "character",
      title: "Lin",
      content: "# Lin\n\n## 首次出现年龄\n18",
      tags: ["主角"],
      importance: 8,
      book_id: "book_one",
    },
  });
});


test("chapter workspace SDK uses JSON bodies and durable chapter routes", async () => {
  configureApiClient({ baseUrl: "/api", timeoutMs: 1000 });
  globalThis.sessionStorage = { getItem: () => "admin-key" };
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push([options.method, url, options.body ? JSON.parse(options.body) : null]);
    return new Response(JSON.stringify({ status: "ok" }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };

  await listChapters("book one");
  await createChapter("book one", { title: "第一章" });
  await getChapter("CHP_1");
  await listChapterLocalizations("CHP_1");
  await createChapterLocalization("CHP_1", { language_code: "en-US" });
  await saveChapter("CHP_1", { title: "第一章", content: "正文" });
  await autosaveChapter("CHP_1", { title: "第一章", content: "草稿" });
  await listChapterVersions("CHP_1");
  await analyzeChapter("CHP_1", "local_rules");
  await buildChapterChangeSet("CHP_1");

  assert.deepEqual(calls, [
    ["GET", "/api/books/book%20one/chapters", null],
    ["POST", "/api/books/book%20one/chapters", { title: "第一章" }],
    ["GET", "/api/chapters/CHP_1", null],
    ["GET", "/api/chapters/CHP_1/localizations", null],
    ["POST", "/api/chapters/CHP_1/localizations", { language_code: "en-US" }],
    ["PUT", "/api/chapters/CHP_1", { title: "第一章", content: "正文" }],
    ["POST", "/api/chapters/CHP_1/autosave", { title: "第一章", content: "草稿" }],
    ["POST", "/api/chapters/CHP_1/versions", {}],
    ["POST", "/api/chapters/CHP_1/analyze", { analysis_mode: "local_rules" }],
    ["POST", "/api/chapters/CHP_1/changeset", {}],
  ]);
});

test("translation SDK keeps model drafts and review gates behind AetherDB", async () => {
  configureApiClient({ baseUrl: "/api", timeoutMs: 1000 });
  globalThis.sessionStorage = { getItem: () => "admin-key" };
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push([options.method, url, options.body ? JSON.parse(options.body) : null]);
    return new Response(JSON.stringify({ status: "ok" }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };

  const chapterRequest = {
    target_language_code: "en-US",
    model_profile_id: "model-1",
    cloud_upload_confirmed: false,
    request_id: "translation-ui-1",
  };
  await listTranslationModels();
  await createChapterTranslation("CHP_1", chapterRequest);
  await listChapterTranslations("CHP_1");
  await updateChapterTranslation("TR_1", {
    title: "Chapter One",
    content: "Translated text.",
  });
  await approveChapterTranslation("TR_1", "a".repeat(64));
  await rejectChapterTranslation("TR_1");
  await reviewChapterLocalization("CHP_2", "approve", "b".repeat(64));
  await getEntityTranslations("ENTITY_1");
  await saveEntityTranslation("ENTITY_1", {
    book_id: "book-one",
    language: "en-US",
    title: "North Camp",
    content: "Summary",
    full_content: "Full translated content",
    ai_summary: "",
  });
  await reviewEntityTranslation(7, {
    action: "approve",
    expected_source_hash: "c".repeat(64),
  });

  assert.deepEqual(calls, [
    ["GET", "/api/translations/models", null],
    ["POST", "/api/chapters/CHP_1/translations", chapterRequest],
    ["GET", "/api/chapters/CHP_1/translations", null],
    ["PUT", "/api/translations/TR_1", {
      title: "Chapter One",
      content: "Translated text.",
    }],
    ["POST", "/api/translations/TR_1/approve", {
      expected_source_revision_hash: "a".repeat(64),
    }],
    ["POST", "/api/translations/TR_1/reject", {}],
    ["POST", "/api/chapters/CHP_2/translation-review", {
      action: "approve",
      expected_source_revision_hash: "b".repeat(64),
    }],
    ["GET", "/api/entity/ENTITY_1/translations", null],
    ["POST", "/api/entity/ENTITY_1/translate", {
      book_id: "book-one",
      language: "en-US",
      title: "North Camp",
      content: "Summary",
      full_content: "Full translated content",
      ai_summary: "",
    }],
    ["POST", "/api/entity-translations/7/review", {
      action: "approve",
      expected_source_hash: "c".repeat(64),
    }],
  ]);
});


test("entity collection SDK targets the authenticated collection route", async () => {
  configureApiClient({ baseUrl: "/api", timeoutMs: 1000 });
  globalThis.sessionStorage = { getItem: () => "user-key" };
  let captured = null;
  globalThis.fetch = async (url, options) => {
    captured = [options.method, url];
    return new Response(JSON.stringify({ entities: [] }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };

  await getEntities({ book_id: "book one", entity_type: "character", limit: 80 });
  assert.deepEqual(captured, ["GET", "/api/entity?book_id=book+one&entity_type=character&limit=80"]);
});


test("embedding task SDK stays behind AetherDB task endpoints", async () => {
  configureApiClient({ baseUrl: "/api", timeoutMs: 1000 });
  globalThis.sessionStorage = { getItem: () => "admin-key" };
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push([options.method, url, options.body ? JSON.parse(options.body) : null]);
    return new Response(JSON.stringify({ status: "queued" }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };

  await createVectorTask({ database_id: "default", entity_ids: ["ENTITY_1"] });
  await getHardwareAccelerationStatus();
  await getVectorIndexStatus("default");
  await rebuildVectorIndex("default", "book one");
  await listVectorTasks({ database_id: "default", status: "running" });
  await getVectorTask("task-1");
  await cancelVectorTask("task-1");
  await retryFailedVectorItems("task-1");

  assert.deepEqual(calls, [
    ["POST", "/api/vector-index/tasks", { database_id: "default", entity_ids: ["ENTITY_1"] }],
    ["GET", "/api/vector-index/runtime-status", null],
    ["GET", "/api/vector-index/status?database_id=default", null],
    ["POST", "/api/vector-index/rebuild?database_id=default&book_id=book%20one", {}],
    ["GET", "/api/vector-index/tasks?database_id=default&status=running", null],
    ["GET", "/api/vector-index/tasks/task-1", null],
    ["POST", "/api/vector-index/tasks/task-1/cancel", {}],
    ["POST", "/api/vector-index/tasks/task-1/retry-failed", {}],
  ]);
});


test("context and changeset recovery SDKs use durable IDs", async () => {
  configureApiClient({ baseUrl: "/api", timeoutMs: 1000 });
  globalThis.sessionStorage = { getItem: () => "user-key" };
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push([options.method, url]);
    return new Response(JSON.stringify({ status: "ok" }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };

  await listContextTasks({ database_id: "default", include_expired: true });
  await getChangeSet("CHS_1");
  await confirmChangeSet("CHS_1");

  assert.deepEqual(calls, [
    ["GET", "/api/context/tasks?database_id=default&include_expired=true"],
    ["GET", "/api/changesets/CHS_1"],
    ["POST", "/api/changesets/CHS_1/confirm"],
  ]);
});


test("auth status SDK probes only the AetherDB status endpoint", async () => {
  configureApiClient({ baseUrl: "/api", apiKey: "", timeoutMs: 1000 });
  globalThis.sessionStorage = { getItem: () => "probe-credential" };
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push([options.method, url]);
    return new Response(JSON.stringify({
      protocol_version: "1.0",
      status: "valid",
      valid: true,
      role: "user",
      deployment_mode: "local_desktop",
      deployment_enabled: true,
      authenticated: true,
      effective_role: "owner",
      capabilities: ["read_content", "manage_system"],
      credential_status: "valid",
    }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };

  await getAuthStatus();

  assert.deepEqual(calls, [["GET", "/api/auth/status"]]);
});


test("media SDK uploads, previews, approves, and binds only through AetherDB", async () => {
  configureApiClient({ baseUrl: "/api", timeoutMs: 1000 });
  globalThis.sessionStorage = { getItem: () => "user-key" };
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push([options.method, url, options.body]);
    if (url.endsWith("/content?database_id=default")) {
      return new Response(new Blob(["media"], { type: "image/png" }), {
        status: 200,
        headers: { "content-type": "image/png" },
      });
    }
    return new Response(JSON.stringify({ status: "ok", assets: [] }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };

  const file = new Blob(["png"], { type: "image/png" });
  Object.defineProperty(file, "name", { value: "cover.png" });
  await uploadMediaAsset({ databaseId: "default", bookId: "book-one", file });
  await listMediaAssets({ database_id: "default", book_id: "book-one" });
  await listEffectiveChapterMedia({
    database_id: "default",
    book_id: "book-one",
    chapter_id: "CHP_1",
    language_code: "en-US",
  });
  await loadMediaContent("asset-1", "default");
  await approveMediaAsset("asset-1", "default");
  await createMediaBinding("asset-1", "default", {
    book_id: "book-one",
    target_type: "chapter",
    target_id: "CHP_1",
    binding_type: "chapter_illustration",
  });
  await deleteMediaBinding("asset-1", "binding-1", "default");

  assert.equal(calls[0][0], "POST");
  assert.equal(calls[0][1], "/api/media-assets");
  assert.ok(calls[0][2] instanceof FormData);
  assert.equal(calls[0][2].get("database_id"), "default");
  assert.deepEqual(calls.slice(1).map(([method, url]) => [method, url]), [
    ["GET", "/api/media-assets?database_id=default&book_id=book-one"],
    ["GET", "/api/media-assets/effective?database_id=default&book_id=book-one&chapter_id=CHP_1&language_code=en-US"],
    ["GET", "/api/media-assets/asset-1/content?database_id=default"],
    ["POST", "/api/media-assets/asset-1/approve?database_id=default"],
    ["POST", "/api/media-assets/asset-1/bindings?database_id=default"],
    ["DELETE", "/api/media-assets/asset-1/bindings/binding-1?database_id=default"],
  ]);
});

test("media vision SDK keeps local indexing and retrieval behind AetherDB", async () => {
  configureApiClient({ baseUrl: "/api", timeoutMs: 1000 });
  globalThis.sessionStorage = { getItem: () => "user-key" };
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push([
      options.method,
      url,
      options.body ? JSON.parse(options.body) : null,
    ]);
    return new Response(JSON.stringify({ status: "ok", results: [] }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };

  await getMediaVisionStatus("default", "book-one");
  await listMediaVisualSpaces("default");
  await createMediaVisualSpace("default", "rocm_pytorch");
  await validateMediaVisualSpace("space-1", "default");
  await activateMediaVisualSpace("space-1", "default");
  await rollbackMediaVisualSpace("default");
  await garbageCollectMediaVisualSpace("space-old", "default");
  await listMediaVisualMigrations("default", null, 25);
  await getMediaVisualMigration("migration-1", "default");
  await cancelMediaVisualMigration("migration-1", "default");
  await retryMediaVisualMigration("migration-1", "default");
  await indexMediaVisionAsset("asset-1", "default", {
    requested_backend: "rocm_pytorch",
    include_caption: true,
  });
  await indexMediaVisionBatch("default", {
    asset_ids: ["asset-1", "asset-2"],
    requested_backend: "auto",
    include_caption: true,
    continue_on_error: true,
  });
  await searchMediaVisionText("default", {
    book_id: "book-one",
    query: "red tower",
  });
  await searchMediaVisionImage("default", {
    book_id: "book-one",
    query_asset_id: "asset-1",
  });
  await removeMediaVisionAsset("asset-1", "default");

  assert.deepEqual(calls, [
    ["GET", "/api/media-vision/status?database_id=default&book_id=book-one", null],
    ["GET", "/api/media-vision/spaces?database_id=default", null],
    ["POST", "/api/media-vision/spaces", {
      database_id: "default",
      requested_backend: "rocm_pytorch",
    }],
    ["POST", "/api/media-vision/spaces/space-1/validate", { database_id: "default" }],
    ["POST", "/api/media-vision/spaces/space-1/activate", { database_id: "default" }],
    ["POST", "/api/media-vision/spaces/rollback", { database_id: "default" }],
    ["POST", "/api/media-vision/spaces/space-old/garbage-collect", {
      database_id: "default",
      confirm_space_id: "space-old",
    }],
    ["GET", "/api/media-vision/migrations?database_id=default&limit=25", null],
    ["GET", "/api/media-vision/migrations/migration-1?database_id=default", null],
    ["POST", "/api/media-vision/migrations/migration-1/cancel", { database_id: "default" }],
    ["POST", "/api/media-vision/migrations/migration-1/retry", { database_id: "default" }],
    ["POST", "/api/media-vision/assets/asset-1/index?database_id=default", {
      requested_backend: "rocm_pytorch",
      include_caption: true,
    }],
    ["POST", "/api/media-vision/index-batch?database_id=default", {
      asset_ids: ["asset-1", "asset-2"],
      requested_backend: "auto",
      include_caption: true,
      continue_on_error: true,
    }],
    ["POST", "/api/media-vision/search/text?database_id=default", {
      book_id: "book-one",
      query: "red tower",
    }],
    ["POST", "/api/media-vision/search/image?database_id=default", {
      book_id: "book-one",
      query_asset_id: "asset-1",
    }],
    ["DELETE", "/api/media-vision/assets/asset-1/index?database_id=default", null],
  ]);
});


test("media generation SDK uses durable tasks and explicit review results", async () => {
  configureApiClient({ baseUrl: "/api", timeoutMs: 1000 });
  globalThis.sessionStorage = { getItem: () => "user-key" };
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push([
      options.method,
      url,
      options.body ? JSON.parse(options.body) : null,
    ]);
    return new Response(JSON.stringify({ status: "ok" }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };

  const payload = {
    database_id: "default",
    book_id: "book-one",
    operation: "image.generate",
    prompt: "a red tower",
    parameters: { width: 768, height: 512, steps: 20 },
  };
  await getMediaGenerationStatus();
  await createMediaGenerationTask(payload);
  await listMediaGenerationTasks({ database_id: "default", book_id: "book-one" });
  await getMediaGenerationTask("mgen-1", "default");
  await listMediaGenerationEvents("mgen-1", "default", 3);
  await cancelMediaGenerationTask("mgen-1", "default");
  await retryMediaGenerationTask("mgen-1", "default");

  assert.deepEqual(calls, [
    ["GET", "/api/media-generation/status", null],
    ["POST", "/api/media-generation/tasks", payload],
    ["GET", "/api/media-generation/tasks?database_id=default&book_id=book-one", null],
    ["GET", "/api/media-generation/tasks/mgen-1?database_id=default", null],
    ["GET", "/api/media-generation/tasks/mgen-1/events?database_id=default&after_sequence=3", null],
    ["POST", "/api/media-generation/tasks/mgen-1/cancel?database_id=default", {}],
    ["POST", "/api/media-generation/tasks/mgen-1/retry?database_id=default", {}],
  ]);
});


test("multimodal evidence SDK keeps annotation review and media budget server-side", async () => {
  configureApiClient({ baseUrl: "/api", timeoutMs: 1000 });
  globalThis.sessionStorage = { getItem: () => "user-key" };
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push([
      options.method,
      url,
      options.body ? JSON.parse(options.body) : null,
    ]);
    return new Response(JSON.stringify({ status: "ok" }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };

  const budget = {
    total_context_tokens: 4096,
    reserved_instruction: 500,
    reserved_current_text: 500,
    reserved_evidence: 1800,
    reserved_output: 1000,
  };
  const mediaBudget = {
    max_items: 3,
    allowed_modalities: ["image", "audio"],
  };
  await reviewMediaAnnotation("asset-1", "annotation-1", "default", true);
  await buildEvidencePack("context-1", "default", budget, mediaBudget);

  assert.deepEqual(calls, [
    ["POST", "/api/media-assets/asset-1/annotations/annotation-1/review?database_id=default", {
      approved: true,
    }],
    ["POST", "/api/context/tasks/context-1/evidence-pack?database_id=default", {
      budget,
      media_budget: mediaBudget,
    }],
  ]);
});


test("audio SDK freezes model-neutral tasks, review, waveform, and voice slots", async () => {
  configureApiClient({ baseUrl: "/api", timeoutMs: 1000 });
  globalThis.sessionStorage = { getItem: () => "user-key" };
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push([
      options.method,
      url,
      options.body ? JSON.parse(options.body) : null,
    ]);
    return new Response(JSON.stringify({ status: "ok" }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };

  const voice = {
    database_id: "default",
    book_id: "book-one",
    name: "Narrator",
    voice_kind: "provider_voice",
    model_profile_id: "ollama:voice",
    provider_voice_name: "speaker-1",
  };
  const task = {
    database_id: "default",
    book_id: "book-one",
    operation: "audio.tts.segment",
    source_text: "A short line.",
    voice_profile_id: "voice-1",
  };
  await getAudioContractStatus();
  await createVoiceProfile(voice);
  await listVoiceProfiles({ database_id: "default", book_id: "book-one" });
  await updateVoiceProfile("voice-1", "default", { enabled: false });
  const pronunciation = {
    database_id: "default",
    book_id: "book-one",
    locale: "zh-CN",
    term: "靖川",
    pronunciation: "jing chuan",
  };
  await createPronunciationEntry(pronunciation);
  await listPronunciationEntries({ database_id: "default", book_id: "book-one" });
  await updatePronunciationEntry("pron-1", "default", { enabled: false });
  await deletePronunciationEntry("pron-1", "default");
  await getAudioAsset("asset-1", "default");
  await getAudioWaveform("asset-1", "default", 256);
  await createAudioTask(task);
  await listAudioTasks({ database_id: "default", book_id: "book-one" });
  await getAudioTask("task-1", "default", { includeResultText: true });
  await listAudioTaskEvents("task-1", "default", 25);
  await retryAudioTask("task-1", "default");
  await registerAudioOutput("task-1", "default", {
    asset_id: "asset-2",
    output_kind: "final",
  });
  await registerAudioResult("task-1", "default", {
    result_type: "transcript",
    content_text: "review me",
  });
  await reviewAudioResult("result-1", "default", true);
  await cancelAudioTask("task-1", "default");

  assert.deepEqual(calls, [
    ["GET", "/api/audio/status", null],
    ["POST", "/api/audio/voice-profiles", voice],
    ["GET", "/api/audio/voice-profiles?database_id=default&book_id=book-one", null],
    ["PATCH", "/api/audio/voice-profiles/voice-1?database_id=default", { enabled: false }],
    ["POST", "/api/audio/pronunciations", pronunciation],
    ["GET", "/api/audio/pronunciations?database_id=default&book_id=book-one", null],
    ["PATCH", "/api/audio/pronunciations/pron-1?database_id=default", { enabled: false }],
    ["DELETE", "/api/audio/pronunciations/pron-1?database_id=default", null],
    ["GET", "/api/audio/assets/asset-1?database_id=default", null],
    ["GET", "/api/audio/assets/asset-1/waveform?database_id=default&points=256", null],
    ["POST", "/api/audio/tasks", task],
    ["GET", "/api/audio/tasks?database_id=default&book_id=book-one", null],
    ["GET", "/api/audio/tasks/task-1?database_id=default&include_result_text=true", null],
    ["GET", "/api/audio/tasks/task-1/events?database_id=default&limit=25", null],
    ["POST", "/api/audio/tasks/task-1/retry?database_id=default", {}],
    ["POST", "/api/audio/tasks/task-1/outputs?database_id=default", {
      asset_id: "asset-2",
      output_kind: "final",
    }],
    ["POST", "/api/audio/tasks/task-1/results?database_id=default", {
      result_type: "transcript",
      content_text: "review me",
    }],
    ["POST", "/api/audio/results/result-1/review?database_id=default", { approved: true }],
    ["POST", "/api/audio/tasks/task-1/cancel?database_id=default", {}],
  ]);
});


test("model package SDK keeps trusted install lifecycle behind AetherDB", async () => {
  configureApiClient({ baseUrl: "/api", timeoutMs: 1000 });
  globalThis.sessionStorage = { getItem: () => "admin-key" };
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push([
      options.method,
      url,
      options.body ? JSON.parse(options.body) : null,
    ]);
    return new Response(JSON.stringify({ status: "ok" }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };

  const packageId = "aetherdb.bge-m3";
  const version = "1.0.0";
  await listModelPackages();
  await acceptModelPackageLicense(packageId, {
    package_version: version,
    manifest_digest: "a".repeat(64),
    license_id: "MIT",
    accepted: true,
  });
  await installModelPackage(packageId, {
    package_version: version,
    source_kind: "catalog",
  });
  await verifyModelPackage(packageId, version);
  await listModelPackageOperations(10);
  await checkModelPackageDistribution([
    { package_id: packageId, package_version: version },
  ]);
  await cancelModelPackageOperation("operation-1");
  await retryModelPackageOperation("operation-1");
  await uninstallModelPackage("optional.vision", version);

  assert.deepEqual(calls, [
    ["GET", "/api/model-packages", null],
    ["POST", "/api/model-packages/aetherdb.bge-m3/license-acceptance", {
      package_version: version,
      manifest_digest: "a".repeat(64),
      license_id: "MIT",
      accepted: true,
    }],
    ["POST", "/api/model-packages/aetherdb.bge-m3/install", {
      package_version: version,
      source_kind: "catalog",
    }],
    ["POST", "/api/model-packages/aetherdb.bge-m3/verify", {
      package_version: version,
    }],
    ["GET", "/api/model-packages/operations?limit=10", null],
    ["POST", "/api/model-packages/distribution-check", {
      packages: [{ package_id: packageId, package_version: version }],
    }],
    ["POST", "/api/model-packages/operations/operation-1/cancel", {}],
    ["POST", "/api/model-packages/operations/operation-1/retry", {}],
    ["POST", "/api/model-packages/optional.vision/uninstall", {
      package_version: version,
      confirm_package_id: "optional.vision",
    }],
  ]);
});


test("model runtime SDK submits intent while hardware evidence stays server-owned", async () => {
  configureApiClient({ baseUrl: "/api", timeoutMs: 1000 });
  globalThis.sessionStorage = { getItem: () => "admin-key" };
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push([
      options.method,
      url,
      options.body ? JSON.parse(options.body) : null,
    ]);
    return new Response(JSON.stringify({ status: "ok" }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };

  await getModelRuntimeResources();
  await getModelRuntimePolicy();
  await updateModelRuntimePolicy({
    scheduling_policy: "AUTO",
    competition_mode: false,
    lease_ttl_seconds: 30,
    pressure_free_vram_percent: 10,
  });
  await evaluateModelAdmission({
    package_id: "aetherdb.bge-m3",
    task_id: "embedding-1",
    requested_backend: "auto",
  });
  await listModelRuntimeLeases(true);
  await listModelRuntimeDrift(true);
  await reconcileModelRuntimeDrift();
  await listModelRuntimeEvidence();
  await listModelCoexistenceEvidence();
  await listModelWorkers();
  await startModelWorker({
    package_id: "aetherdb.bge-m3",
    replica_id: "default",
  });
  await getModelWorker("worker-1");
  await loadModelWorker("worker-1", {
    task_id: "embedding-1",
    requested_backend: "cpu",
  });
  await probeModelWorker("worker-1", {
    requested_backend: "cpu",
    keep_loaded: false,
  });
  await unloadModelWorker("worker-1");
  await stopModelWorker("worker-1");
  await listModelRuntimeJobs("worker-1", 25);
  await getModelRuntimeJob("job-1");
  await cancelModelRuntimeJob("job-1");

  assert.deepEqual(calls, [
    ["GET", "/api/model-runtime/resources", null],
    ["GET", "/api/model-runtime/policy", null],
    ["PUT", "/api/model-runtime/policy", {
      scheduling_policy: "AUTO",
      competition_mode: false,
      lease_ttl_seconds: 30,
      pressure_free_vram_percent: 10,
    }],
    ["POST", "/api/model-runtime/admissions", {
      package_id: "aetherdb.bge-m3",
      task_id: "embedding-1",
      requested_backend: "auto",
    }],
    ["GET", "/api/model-runtime/leases?active_only=true", null],
    ["GET", "/api/model-runtime/drift?active_only=true", null],
    ["POST", "/api/model-runtime/drift/reconcile", {}],
    ["GET", "/api/model-runtime/runtime-evidence", null],
    ["GET", "/api/model-runtime/coexistence-evidence", null],
    ["GET", "/api/model-runtime/workers", null],
    ["POST", "/api/model-runtime/workers", {
      package_id: "aetherdb.bge-m3",
      replica_id: "default",
    }],
    ["GET", "/api/model-runtime/workers/worker-1", null],
    ["POST", "/api/model-runtime/workers/worker-1/load", {
      task_id: "embedding-1",
      requested_backend: "cpu",
    }],
    ["POST", "/api/model-runtime/workers/worker-1/probe", {
      requested_backend: "cpu",
      keep_loaded: false,
    }],
    ["POST", "/api/model-runtime/workers/worker-1/unload", {}],
    ["POST", "/api/model-runtime/workers/worker-1/stop", {}],
    ["GET", "/api/model-runtime/jobs?worker_id=worker-1&limit=25", null],
    ["GET", "/api/model-runtime/jobs/job-1", null],
    ["POST", "/api/model-runtime/jobs/job-1/cancel", {}],
  ]);
});
