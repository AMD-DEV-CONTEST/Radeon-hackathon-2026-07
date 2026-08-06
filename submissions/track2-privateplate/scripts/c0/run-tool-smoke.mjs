import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { setTimeout as delay } from "node:timers/promises";
import { fileURLToPath } from "node:url";
import {
  LocalMockProvider,
  OpenAiCompatibleHttpProvider,
  classifyProviderError,
  collectToolCall,
  createFixtureExpectedToolCall,
  createOpenAiCompatibleRequest,
  jsonValuesEqual,
  privatePlateToolNames,
  redactSensitive,
  validateFixtureBoundToolCall,
  validatePrivatePlateToolCall
} from "./provider-adapter.mjs";
import { evaluateToolGate } from "./tool-gate.mjs";

const projectRoot = fileURLToPath(new URL("../../", import.meta.url));
const fixturePath = new URL(
  "../../fixtures/c0/v2/tool-calling-scenarios.json",
  import.meta.url
);

const fixture = JSON.parse(await readFile(fixturePath, "utf8"));
const scenarios = fixture.scenarios;
const provider = new LocalMockProvider(fixture);
const records = [];

for (const scenario of scenarios) {
  const expectedCall = createFixtureExpectedToolCall(scenario);
  assert.equal(validatePrivatePlateToolCall(expectedCall), true);
  assert.equal(
    validateFixtureBoundToolCall(expectedCall, fixture.fixture_id_map),
    true
  );

  const request = createOpenAiCompatibleRequest(scenario, {
    fixtureIdMap: fixture.fixture_id_map
  });
  const userPayload = JSON.parse(request.messages[1].content);
  assert.equal(userPayload.scenarioId, scenario.id);
  assert.deepEqual(userPayload.fixtureIdMap, fixture.fixture_id_map);
  assert.equal("expected_tool" in userPayload, false);
  assert.equal("expected_arguments" in userPayload, false);

  const call = await collectToolCall(provider.streamChatCompletion(request));
  const schemaValid = validatePrivatePlateToolCall(call);
  const toolMatch = call.name === scenario.expected_tool;
  const argumentsMatch =
    toolMatch && jsonValuesEqual(call.arguments, expectedCall.arguments);
  const secretSentinel = `stage-a-secret-${scenario.id}`;
  const redacted = redactSensitive({
    authorization: `Bearer ${secretSentinel}`,
    confirmationToken: secretSentinel,
    idempotencyKey: secretSentinel,
    call
  });
  const redactionPassed = !JSON.stringify(redacted).includes(secretSentinel);

  records.push({
    schema_version: "2.0",
    stage: "C0-A",
    case_id: scenario.id,
    provider_mode: "local_mock",
    remote_api: false,
    model: null,
    expected_tool: scenario.expected_tool,
    expected_arguments: expectedCall.arguments,
    actual_tool: call.name,
    raw_model_arguments: call.arguments,
    normalized_model_arguments: call.arguments,
    actual_arguments: call.arguments,
    stream_reassembled: true,
    schema_valid: schemaValid,
    tool_match: toolMatch,
    arguments_match: argumentsMatch,
    raw_arguments_match: argumentsMatch,
    redaction_passed: redactionPassed,
    outcome:
      schemaValid && toolMatch && argumentsMatch && redactionPassed
        ? "CONTRACT_PASS"
        : "CONTRACT_FAIL",
    evidence_eligible: false,
    measurement_scope: "adapter_contract_only"
  });
}

assert.equal(records.length, scenarios.length);
assert.equal(
  records.filter((record) => record.outcome === "CONTRACT_PASS").length,
  scenarios.length
);
for (const toolName of privatePlateToolNames) {
  assert.ok(
    records.some((record) => record.expected_tool === toolName),
    `Missing C0-A coverage for ${toolName}`
  );
}
assert.equal(evaluateToolGate(records).overall_gate, "PASS");
assert.equal(
  evaluateToolGate(
    records.map((record, index) =>
      index < records.length - 2
        ? record
        : {
            ...record,
            actual_tool: "get_meal_context",
            expected_tool: "compose_family_meal"
          }
    )
  ).minimum_routing_gate,
  "FAIL"
);
assert.equal(
  evaluateToolGate(
    records.map((record, index) =>
      index < records.length - 3
        ? record
        : {
            ...record,
            raw_model_arguments: { ...record.raw_model_arguments, __wrong: true },
            normalized_model_arguments: {
              ...record.normalized_model_arguments,
              __wrong: true
            },
            actual_arguments: { ...record.actual_arguments, __wrong: true }
          }
    )
  ).full_arguments_gate,
  "FAIL"
);
const errorCases = [
  [{ code: "REMOTE_PROVIDER_NOT_AUTHORIZED" }, "REMOTE_PROVIDER_NOT_AUTHORIZED"],
  [{ code: "REMOTE_APPROVAL_INVALID" }, "REMOTE_APPROVAL_INVALID"],
  [{ code: "INSECURE_REMOTE_PROVIDER" }, "INSECURE_REMOTE_PROVIDER"],
  [
    { code: "REMOTE_PROVIDER_API_KEY_REQUIRED" },
    "REMOTE_PROVIDER_API_KEY_REQUIRED"
  ],
  [{ name: "AbortError" }, "PROVIDER_TIMEOUT"],
  [{ name: "TimeoutError" }, "PROVIDER_TIMEOUT"],
  [new SyntaxError("bad stream"), "MALFORMED_PROVIDER_RESPONSE"],
  [{ status: 401 }, "PROVIDER_AUTH_FAILED"],
  [{ status: 429 }, "PROVIDER_RATE_LIMITED"]
];

for (const [error, expectedCode] of errorCases) {
  assert.equal(classifyProviderError(error), expectedCode);
}

const timeoutSignal = AbortSignal.timeout(1);
await delay(5);
assert.equal(classifyProviderError(timeoutSignal.reason), "PROVIDER_TIMEOUT");

let rejectedRemoteFetchCalls = 0;
const rejectedFetch = async () => {
  rejectedRemoteFetchCalls += 1;
  throw new Error("A rejected remote provider reached the fetch boundary.");
};
const remoteRequest = createOpenAiCompatibleRequest(scenarios[0], {
  model: "stage-a-model",
  fixtureIdMap: fixture.fixture_id_map
});
const rejectedProviders = [
  {
    provider: new OpenAiCompatibleHttpProvider({
      baseUrl: "https://example.invalid/v1",
      apiKey: "stage-a-never-sent",
      model: "stage-a-model",
      fetchImpl: rejectedFetch
    }),
    code: "REMOTE_PROVIDER_NOT_AUTHORIZED"
  },
  {
    provider: new OpenAiCompatibleHttpProvider({
      baseUrl: "http://example.invalid/v1",
      apiKey: "stage-a-never-sent",
      model: "stage-a-model",
      fetchImpl: rejectedFetch
    }),
    code: "INSECURE_REMOTE_PROVIDER"
  },
  {
    provider: new OpenAiCompatibleHttpProvider({
      baseUrl: "https://example.invalid/v1",
      apiKey: null,
      model: "stage-a-model",
      remoteApproval: createSyntheticApproval(),
      fetchImpl: rejectedFetch
    }),
    code: "REMOTE_PROVIDER_API_KEY_REQUIRED"
  },
  {
    provider: new OpenAiCompatibleHttpProvider({
      baseUrl: "https://example.invalid/v1",
      apiKey: "stage-a-never-sent",
      model: "stage-a-model",
      remoteApproval: createSyntheticApproval({
        approvedAt: "2026-07-24T12:40:00.000Z",
        expiresAt: "2026-07-24T12:50:00.000Z"
      }),
      now: () => Date.parse("2026-07-24T13:00:00.000Z"),
      fetchImpl: rejectedFetch
    }),
    code: "REMOTE_APPROVAL_INVALID"
  },
  {
    provider: new OpenAiCompatibleHttpProvider({
      baseUrl: "https://example.invalid/v1",
      apiKey: "stage-a-never-sent",
      model: "stage-a-model",
      remoteApproval: createSyntheticApproval({
        approvedBaseUrl: "https://example.invalid/other/"
      }),
      now: () => Date.parse("2026-07-24T13:00:00.000Z"),
      fetchImpl: rejectedFetch
    }),
    code: "REMOTE_APPROVAL_INVALID"
  },
  {
    provider: new OpenAiCompatibleHttpProvider({
      baseUrl: "https://example.invalid/v1",
      apiKey: "stage-a-never-sent",
      model: "stage-a-model",
      remoteApproval: createSyntheticApproval({
        approvedModel: "different-model"
      }),
      now: () => Date.parse("2026-07-24T13:00:00.000Z"),
      fetchImpl: rejectedFetch
    }),
    code: "REMOTE_APPROVAL_INVALID"
  }
];

for (const { provider: rejectedProvider, code } of rejectedProviders) {
  await assert.rejects(
    () => rejectedProvider.streamChatCompletion(remoteRequest).next(),
    (error) => error.code === code
  );
}
assert.equal(rejectedRemoteFetchCalls, 0);

const httpScenario = scenarios[0];
const httpRequest = createOpenAiCompatibleRequest(httpScenario, {
  model: "stage-a-http-contract",
  fixtureIdMap: fixture.fixture_id_map
});
const fakeProviderTextChunks = [];
for await (const chunk of provider.streamChatCompletion(
  createOpenAiCompatibleRequest(httpScenario, {
    fixtureIdMap: fixture.fixture_id_map
  })
)) {
  fakeProviderTextChunks.push(chunk);
}
const fakeProviderChunks = fakeProviderTextChunks.map((chunk) =>
  new TextEncoder().encode(chunk)
);

let approvedRemoteFetchCalls = 0;
const approvalNow = Date.parse("2026-07-24T13:00:00.000Z");
const approvedRemoteProvider = new OpenAiCompatibleHttpProvider({
  baseUrl: "https://example.invalid/v1",
  apiKey: "stage-a-approved-path-secret",
  model: "stage-a-http-contract",
  remoteApproval: createSyntheticApproval({
    approvedModel: "stage-a-http-contract"
  }),
  now: () => approvalNow,
  fetchImpl: async () => {
    approvedRemoteFetchCalls += 1;
    return createStreamingResponse(fakeProviderChunks);
  }
});

const approvedRemoteCall = await collectToolCall(
  approvedRemoteProvider.streamChatCompletion(httpRequest)
);
assert.deepEqual(approvedRemoteCall.arguments, httpScenario.expected_arguments);
assert.equal(approvedRemoteFetchCalls, 1);

let capturedHttpRequest = null;
const loopbackProvider = new OpenAiCompatibleHttpProvider({
  baseUrl: "http://127.0.0.1:8000/v1",
  apiKey: "stage-a-loopback-secret",
  model: "stage-a-http-contract",
  fetchImpl: async (url, init) => {
    capturedHttpRequest = { url: String(url), init };
    return createStreamingResponse(fakeProviderChunks);
  }
});

const httpCall = await collectToolCall(
  loopbackProvider.streamChatCompletion(httpRequest)
);
assert.deepEqual(httpCall.arguments, httpScenario.expected_arguments);
assert.equal(capturedHttpRequest.url, "http://127.0.0.1:8000/v1/chat/completions");
assert.equal(
  capturedHttpRequest.init.headers.Authorization,
  "Bearer stage-a-loopback-secret"
);
const capturedHttpBody = JSON.parse(capturedHttpRequest.init.body);
assert.equal(capturedHttpBody.model, "stage-a-http-contract");
assert.equal("metadata" in capturedHttpBody, false);
assert.equal(capturedHttpRequest.init.signal instanceof AbortSignal, true);

const crlfStreamText = fakeProviderTextChunks.join("").replaceAll("\n", "\r\n");
const crlfToolCall = await collectToolCall(splitText(crlfStreamText));
assert.deepEqual(crlfToolCall.arguments, httpScenario.expected_arguments);

console.log(
  JSON.stringify({
    project_root: projectRoot,
    status: "PASS",
    samples: records.length,
    tools: privatePlateToolNames,
    schema_pass_count: records.filter((record) => record.schema_valid).length,
    tool_match_count: records.filter((record) => record.tool_match).length,
    arguments_match_count: records.filter((record) => record.arguments_match).length,
    provider_mode: "local_mock",
    remote_api: false,
    evidence_eligible: false,
    measurement_scope: "five_tool_adapter_contract_only"
  })
);

async function* splitText(text) {
  const chunkSizes = [1, 13, 4, 29, 8, 17];
  let offset = 0;
  let chunkIndex = 0;

  while (offset < text.length) {
    const size = chunkSizes[chunkIndex % chunkSizes.length];
    yield text.slice(offset, offset + size);
    offset += size;
    chunkIndex += 1;
  }
}

function createStreamingResponse(chunks) {
  return {
    ok: true,
    status: 200,
    body: {
      async *[Symbol.asyncIterator]() {
        yield* chunks;
      }
    }
  };
}

function createSyntheticApproval(overrides = {}) {
  return {
    approvalId: "stage-a-synthetic-approval",
    approvedBy: "project_owner",
    approvedAt: "2026-07-24T12:55:00.000Z",
    expiresAt: "2026-07-24T13:05:00.000Z",
    approvedBaseUrl: "https://example.invalid/v1/",
    approvedModel: "stage-a-model",
    purpose: "shared_api_rehearsal",
    resourceType: "shared_free_model_api",
    maximumRuntimeMinutes: 10,
    approvedCreditRate: 0,
    creditRateUnit: "no_credits",
    billingEvidenceRef: "stage-a-synthetic-no-network",
    destroyAfterUse: false,
    ...overrides
  };
}
