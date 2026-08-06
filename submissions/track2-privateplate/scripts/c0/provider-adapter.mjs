const REMOTE_APPROVAL_RESOURCE_TYPES = new Map([
  ["shared_api_rehearsal", new Set(["shared_free_model_api"])],
  [
    "c0b_radeon_validation",
    new Set(["gpu_notebook", "dedicated_model_api"])
  ]
]);
const SENSITIVE_KEY_PATTERN =
  /authorization|api[-_]?key|confirmation[-_]?token|idempotency[-_]?key|password|secret/i;

const STRING_ARRAY_SCHEMA = {
  type: "array",
  items: { type: "string", minLength: 1 }
};

const DINER_IDS_SCHEMA = {
  ...STRING_ARRAY_SCHEMA,
  minItems: 1,
  maxItems: 3
};

export const privatePlateTools = [
  {
    type: "function",
    function: {
      name: "get_meal_context",
      description:
        "Read the current household, selected diners, dietary constraints, meal policies and pantry snapshot.",
      strict: true,
      parameters: {
        type: "object",
        additionalProperties: false,
        properties: {
          dinerIds: DINER_IDS_SCHEMA
        },
        required: ["dinerIds"]
      }
    }
  },
  {
    type: "function",
    function: {
      name: "compose_family_meal",
      description:
        "Create an initial shared lunch or dinner plan from deterministic household and pantry data.",
      strict: true,
      parameters: {
        type: "object",
        additionalProperties: false,
        properties: {
          dinerIds: DINER_IDS_SCHEMA,
          mealType: { type: "string", enum: ["lunch", "dinner"] },
          rejectedFoodIds: STRING_ARRAY_SCHEMA,
          rejectedTemplateIds: STRING_ARRAY_SCHEMA,
          requestedPriorityFoodIds: STRING_ARRAY_SCHEMA,
          preferLowEffort: { type: "boolean" }
        },
        required: [
          "dinerIds",
          "mealType",
          "rejectedFoodIds",
          "rejectedTemplateIds",
          "requestedPriorityFoodIds",
          "preferLowEffort"
        ]
      }
    }
  },
  {
    type: "function",
    function: {
      name: "revise_family_meal",
      description:
        "Apply only this-turn plan changes: reject dish templates, reject foods, and/or prefer lower effort.",
      strict: true,
      parameters: {
        type: "object",
        additionalProperties: false,
        properties: {
          rejectTemplateIds: STRING_ARRAY_SCHEMA,
          rejectFoodIds: STRING_ARRAY_SCHEMA,
          preferLowEffort: { type: "boolean" }
        },
        required: ["rejectTemplateIds", "rejectFoodIds", "preferLowEffort"]
      }
    }
  },
  {
    type: "function",
    function: {
      name: "retrieve_approved_guidance",
      description:
        "Retrieve approved local knowledge cards with a natural semantic query. Use memberIds, not health tags. planTags and topK are optional hints.",
      strict: true,
      parameters: {
        type: "object",
        additionalProperties: false,
        properties: {
          query: { type: "string", minLength: 1 },
          memberIds: STRING_ARRAY_SCHEMA,
          planTags: STRING_ARRAY_SCHEMA,
          topK: { type: "integer", minimum: 1, maximum: 3 }
        },
        required: ["query", "memberIds"]
      }
    }
  },
  {
    type: "function",
    function: {
      name: "preview_caregiver_task",
      description:
        "Preview a minimum-disclosure caregiver task for the active plan. This never commits or sends it.",
      strict: true,
      parameters: {
        type: "object",
        additionalProperties: false,
        properties: {
          recipientLabel: { type: "string", minLength: 1 },
          serveAt: { type: "string", minLength: 1 }
        },
        required: ["recipientLabel", "serveAt"]
      }
    }
  }
];

export const privatePlateToolNames = privatePlateTools.map(
  (tool) => tool.function.name
);

const SYSTEM_PROMPT = [
  "你是 PrivatePlate 的工具路由器，只选择一个工具，不要直接回答用户。",
  "输入 JSON 会提供 scenarioId、request、currentState 和 fixtureIdMap。",
  "scenarioId 只用于追踪，绝不能放进工具参数。",
  "只能使用 fixtureIdMap 中存在的成员、食物和模板 ID，不能自行编造 ID。",
  "读取家庭、成员、约束或库存使用 get_meal_context。",
  "首次规划午餐或晚餐使用 compose_family_meal。",
  "修改已有活动计划使用 revise_family_meal；只传本轮明确提出的 rejectTemplateIds/rejectFoodIds，未拒绝则传空数组。",
  "解释计划或引用本地审核知识时使用 retrieve_approved_guidance；query 可为自然语义；成员用 memberIds，不要传健康标签。",
  "生成给照护者的任务卡使用 preview_caregiver_task，这只是预览，不能发送。",
  "成员顺序、食物顺序和模板顺序均按 fixtureIdMap 中的顺序输出。",
  "只输出工具调用，参数必须严格满足工具 Schema。"
].join(" ");

export function createOpenAiCompatibleRequest(
  scenario,
  { model = "c0-local-mock", fixtureIdMap } = {}
) {
  if (!fixtureIdMap || typeof fixtureIdMap !== "object") {
    throw new TypeError("C0 request requires the frozen fixture ID map.");
  }

  return {
    model,
    messages: [
      { role: "system", content: SYSTEM_PROMPT },
      {
        role: "user",
        content: JSON.stringify({
          scenarioId: scenario.id,
          request: scenario.user_text,
          currentState: scenario.current_state,
          fixtureIdMap
        })
      }
    ],
    tools: privatePlateTools,
    tool_choice: "required",
    stream: true,
    temperature: 0,
    metadata: {
      stage: "C0-A",
      scenarioId: scenario.id
    }
  };
}

export class OpenAiCompatibleHttpProvider {
  constructor({
    baseUrl,
    apiKey,
    model,
    remoteApproval = null,
    timeoutMs = 30_000,
    fetchImpl = globalThis.fetch,
    now = Date.now
  }) {
    this.baseUrl = new URL(baseUrl.endsWith("/") ? baseUrl : `${baseUrl}/`);
    if (!["http:", "https:"].includes(this.baseUrl.protocol)) {
      throw new TypeError("Provider base URL must use HTTP or HTTPS.");
    }
    if (!Number.isFinite(timeoutMs) || timeoutMs <= 0) {
      throw new TypeError("Provider timeout must be a positive number.");
    }
    if (typeof model !== "string" || model.length === 0) {
      throw new TypeError("Provider model must be a non-empty string.");
    }

    this.apiKey = apiKey;
    this.model = model;
    this.remoteApproval = remoteApproval;
    this.timeoutMs = timeoutMs;
    this.fetchImpl = fetchImpl;
    this.now = now;
  }

  async *streamChatCompletion(request) {
    const isRemote = !isLoopbackHost(this.baseUrl.hostname);
    if (isRemote) {
      validateRemoteApproval({
        baseUrl: this.baseUrl,
        apiKey: this.apiKey,
        model: this.model,
        approval: this.remoteApproval,
        now: this.now()
      });
    }

    const { metadata: _metadata, ...requestBody } = request;
    const headers = {
      "Content-Type": "application/json"
    };
    if (this.apiKey) {
      headers.Authorization = `Bearer ${this.apiKey}`;
    }

    const response = await this.fetchImpl(
      new URL("chat/completions", this.baseUrl),
      {
        method: "POST",
        headers,
        body: JSON.stringify({
          ...requestBody,
          model: this.model
        }),
        signal: AbortSignal.timeout(this.timeoutMs)
      }
    );

    if (!response.ok) {
      const error = new Error(`Provider returned HTTP ${response.status}.`);
      error.status = response.status;
      throw error;
    }
    if (!response.body) {
      throw new SyntaxError("Provider response has no streaming body.");
    }

    const decoder = new TextDecoder();
    for await (const chunk of response.body) {
      yield typeof chunk === "string" ? chunk : decoder.decode(chunk, { stream: true });
    }

    const remainder = decoder.decode();
    if (remainder) {
      yield remainder;
    }
  }
}

export class LocalMockProvider {
  constructor(fixture) {
    this.fixtureIdMap = fixture.fixture_id_map;
    this.scenarios = new Map(
      fixture.scenarios.map((scenario) => [scenario.id, scenario])
    );
  }

  async *streamChatCompletion(request) {
    validateRequest(request, this.fixtureIdMap);

    const scenario = this.scenarios.get(request.metadata.scenarioId);
    if (!scenario) {
      throw new Error(`Unknown C0 scenario: ${request.metadata.scenarioId}`);
    }

    const argumentText = JSON.stringify(
      createFixtureExpectedToolCall(scenario).arguments
    );
    const splitAt = Math.max(1, Math.floor(argumentText.length / 2));
    const events = [
      {
        id: `mock-${scenario.id}`,
        object: "chat.completion.chunk",
        choices: [
          {
            index: 0,
            delta: {
              tool_calls: [
                {
                  index: 0,
                  id: `call-${scenario.id}`,
                  type: "function",
                  function: {
                    name: scenario.expected_tool,
                    arguments: argumentText.slice(0, splitAt)
                  }
                }
              ]
            },
            finish_reason: null
          }
        ]
      },
      {
        id: `mock-${scenario.id}`,
        object: "chat.completion.chunk",
        choices: [
          {
            index: 0,
            delta: {
              tool_calls: [
                {
                  index: 0,
                  function: {
                    arguments: argumentText.slice(splitAt)
                  }
                }
              ]
            },
            finish_reason: null
          }
        ]
      },
      {
        id: `mock-${scenario.id}`,
        object: "chat.completion.chunk",
        choices: [
          {
            index: 0,
            delta: {},
            finish_reason: "tool_calls"
          }
        ]
      }
    ];

    const eventStream = [
      ...events.map((event) => `data: ${JSON.stringify(event)}\n\n`),
      "data: [DONE]\n\n"
    ].join("");

    const chunkSizes = [7, 19, 5, 31, 11, 23];
    let offset = 0;
    let chunkIndex = 0;

    while (offset < eventStream.length) {
      const size = chunkSizes[chunkIndex % chunkSizes.length];
      yield eventStream.slice(offset, offset + size);
      offset += size;
      chunkIndex += 1;
    }
  }
}

export function createFixtureExpectedToolCall(scenario) {
  const arguments_ =
    scenario.expected_tool === "retrieve_approved_guidance" &&
    !("query" in (scenario.expected_arguments ?? {}))
      ? {
          query: scenario.user_text,
          ...scenario.expected_arguments
        }
      : scenario.expected_arguments;
  return {
    name: scenario.expected_tool,
    arguments: arguments_
  };
}

export async function collectToolCall(stream) {
  let buffer = "";
  let done = false;
  let finishReason = null;
  const calls = new Map();

  for await (const chunk of stream) {
    buffer += chunk;

    let boundaryMatch = /\r?\n\r?\n/.exec(buffer);
    while (boundaryMatch) {
      const boundary = boundaryMatch.index;
      const eventBlock = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + boundaryMatch[0].length);

      for (const line of eventBlock.split(/\r?\n/)) {
        if (!line.startsWith("data:")) {
          continue;
        }

        const data = line.slice(5).trim();
        if (data === "[DONE]") {
          done = true;
          continue;
        }

        const event = JSON.parse(data);
        for (const choice of event.choices ?? []) {
          finishReason = choice.finish_reason ?? finishReason;

          for (const deltaCall of choice.delta?.tool_calls ?? []) {
            const current = calls.get(deltaCall.index) ?? {
              id: "",
              name: "",
              argumentsText: ""
            };

            current.id = deltaCall.id ?? current.id;
            current.name = deltaCall.function?.name ?? current.name;
            current.argumentsText += deltaCall.function?.arguments ?? "";
            calls.set(deltaCall.index, current);
          }
        }
      }

      boundaryMatch = /\r?\n\r?\n/.exec(buffer);
    }
  }

  if (buffer.length > 0) {
    throw new SyntaxError("Incomplete SSE event at end of stream.");
  }
  if (!done) {
    throw new SyntaxError("OpenAI-compatible stream ended without [DONE].");
  }
  if (finishReason !== "tool_calls") {
    throw new SyntaxError(`Unexpected finish reason: ${finishReason ?? "missing"}.`);
  }
  if (calls.size !== 1) {
    throw new SyntaxError(`Expected one tool call, received ${calls.size}.`);
  }

  const [call] = calls.values();
  return {
    id: call.id,
    name: call.name,
    arguments: JSON.parse(call.argumentsText)
  };
}

export function validatePrivatePlateToolCall(call) {
  if (!call || !isRecord(call.arguments)) {
    return false;
  }

  switch (call.name) {
    case "get_meal_context":
      return (
        hasExactKeys(call.arguments, ["dinerIds"]) &&
        isStringArray(call.arguments.dinerIds, { min: 1, max: 3 })
      );
    case "compose_family_meal":
      return (
        hasExactKeys(call.arguments, [
          "dinerIds",
          "mealType",
          "rejectedFoodIds",
          "rejectedTemplateIds",
          "requestedPriorityFoodIds",
          "preferLowEffort"
        ]) &&
        isStringArray(call.arguments.dinerIds, { min: 1, max: 3 }) &&
        ["lunch", "dinner"].includes(call.arguments.mealType) &&
        isStringArray(call.arguments.rejectedFoodIds) &&
        isStringArray(call.arguments.rejectedTemplateIds) &&
        isStringArray(call.arguments.requestedPriorityFoodIds) &&
        typeof call.arguments.preferLowEffort === "boolean"
      );
    case "revise_family_meal":
      return (
        hasExactKeys(call.arguments, [
          "rejectTemplateIds",
          "rejectFoodIds",
          "preferLowEffort"
        ]) &&
        isStringArray(call.arguments.rejectTemplateIds) &&
        isStringArray(call.arguments.rejectFoodIds) &&
        typeof call.arguments.preferLowEffort === "boolean" &&
        (call.arguments.rejectTemplateIds.length > 0 ||
          call.arguments.rejectFoodIds.length > 0 ||
          call.arguments.preferLowEffort)
      );
    case "retrieve_approved_guidance":
      return (
        hasRequiredOnlyKeys(
          call.arguments,
          ["query", "memberIds"],
          ["query", "memberIds", "planTags", "topK"]
        ) &&
        typeof call.arguments.query === "string" &&
        call.arguments.query.length > 0 &&
        isStringArray(call.arguments.memberIds) &&
        (!("planTags" in call.arguments) ||
          isStringArray(call.arguments.planTags)) &&
        (!("topK" in call.arguments) ||
          (Number.isInteger(call.arguments.topK) &&
            call.arguments.topK >= 1 &&
            call.arguments.topK <= 3))
      );
    case "preview_caregiver_task":
      return (
        hasExactKeys(call.arguments, ["recipientLabel", "serveAt"]) &&
        typeof call.arguments.recipientLabel === "string" &&
        call.arguments.recipientLabel.length > 0 &&
        typeof call.arguments.serveAt === "string" &&
        call.arguments.serveAt.length > 0
      );
    default:
      return false;
  }
}

export function validateFixtureBoundToolCall(call, fixtureIdMap) {
  if (!validatePrivatePlateToolCall(call) || !isRecord(fixtureIdMap)) {
    return false;
  }

  const memberIds = new Set(Object.keys(fixtureIdMap.members ?? {}));
  const foodIds = new Set(Object.keys(fixtureIdMap.foods ?? {}));
  const templateIds = new Set(Object.keys(fixtureIdMap.meal_templates ?? {}));
  const planTags = new Set(Object.keys(fixtureIdMap.guidance_plan_tags ?? {}));
  const recipientLabels = new Set(
    Object.keys(fixtureIdMap.caregiver_recipients ?? {})
  );
  switch (call.name) {
    case "get_meal_context":
      return allValuesKnown(call.arguments.dinerIds, memberIds);
    case "compose_family_meal":
      return (
        allValuesKnown(call.arguments.dinerIds, memberIds) &&
        allValuesKnown(call.arguments.rejectedFoodIds, foodIds) &&
        allValuesKnown(call.arguments.rejectedTemplateIds, templateIds) &&
        allValuesKnown(call.arguments.requestedPriorityFoodIds, foodIds)
      );
    case "revise_family_meal":
      return (
        allValuesKnown(call.arguments.rejectTemplateIds, templateIds) &&
        allValuesKnown(call.arguments.rejectFoodIds, foodIds)
      );
    case "retrieve_approved_guidance":
      return (
        allValuesKnown(call.arguments.memberIds, memberIds) &&
        allValuesKnown(call.arguments.planTags ?? [], planTags)
      );
    case "preview_caregiver_task":
      return recipientLabels.has(call.arguments.recipientLabel);
    default:
      return false;
  }
}

export function jsonValuesEqual(left, right) {
  return (
    JSON.stringify(canonicalizeJson(left)) ===
    JSON.stringify(canonicalizeJson(right))
  );
}

export function redactSensitive(value) {
  if (Array.isArray(value)) {
    return value.map(redactSensitive);
  }
  if (!value || typeof value !== "object") {
    return value;
  }

  return Object.fromEntries(
    Object.entries(value).map(([key, item]) => [
      key,
      SENSITIVE_KEY_PATTERN.test(key) ? "[REDACTED]" : redactSensitive(item)
    ])
  );
}

export function classifyProviderError(error) {
  if (
    error?.code === "REMOTE_PROVIDER_NOT_AUTHORIZED" ||
    error?.code === "REMOTE_APPROVAL_INVALID" ||
    error?.code === "INSECURE_REMOTE_PROVIDER" ||
    error?.code === "REMOTE_PROVIDER_API_KEY_REQUIRED"
  ) {
    return error.code;
  }
  if (error?.name === "AbortError" || error?.name === "TimeoutError") {
    return "PROVIDER_TIMEOUT";
  }
  if (error instanceof SyntaxError) {
    return "MALFORMED_PROVIDER_RESPONSE";
  }
  if (error?.status === 401 || error?.status === 403) {
    return "PROVIDER_AUTH_FAILED";
  }
  if (error?.status === 429) {
    return "PROVIDER_RATE_LIMITED";
  }
  return "PROVIDER_UNAVAILABLE";
}

function validateRequest(request, fixtureIdMap) {
  let userPayload = null;
  try {
    userPayload = JSON.parse(request?.messages?.[1]?.content);
  } catch {
    userPayload = null;
  }

  if (
    typeof request?.model !== "string" ||
    request.model.length === 0 ||
    request?.stream !== true ||
    request?.tool_choice !== "required" ||
    request?.tools?.length !== privatePlateTools.length ||
    !jsonValuesEqual(
      request.tools.map((tool) => tool.function?.name),
      privatePlateToolNames
    ) ||
    request?.messages?.length !== 2 ||
    request.messages[0].role !== "system" ||
    request.messages[1].role !== "user" ||
    typeof request?.metadata?.scenarioId !== "string" ||
    userPayload?.scenarioId !== request.metadata.scenarioId ||
    typeof userPayload?.request !== "string" ||
    !jsonValuesEqual(userPayload?.fixtureIdMap, fixtureIdMap)
  ) {
    throw new TypeError("Invalid C0 OpenAI-compatible request contract.");
  }
}

function isRecord(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function hasExactKeys(value, expectedKeys) {
  if (!isRecord(value)) {
    return false;
  }
  return jsonValuesEqual(Object.keys(value).sort(), [...expectedKeys].sort());
}

function hasRequiredOnlyKeys(value, requiredKeys, allowedKeys) {
  if (!isRecord(value)) {
    return false;
  }
  const actual = Object.keys(value);
  return (
    requiredKeys.every((key) => actual.includes(key)) &&
    actual.every((key) => allowedKeys.includes(key))
  );
}

function isStringArray(value, { min = 0, max = Number.POSITIVE_INFINITY } = {}) {
  return (
    Array.isArray(value) &&
    value.length >= min &&
    value.length <= max &&
    value.every((item) => typeof item === "string" && item.length > 0)
  );
}

function allValuesKnown(values, allowedValues) {
  return values.every((value) => allowedValues.has(value));
}

function canonicalizeJson(value) {
  if (Array.isArray(value)) {
    return value.map(canonicalizeJson);
  }
  if (!isRecord(value)) {
    return value;
  }
  return Object.fromEntries(
    Object.keys(value)
      .sort()
      .map((key) => [key, canonicalizeJson(value[key])])
  );
}

function isLoopbackHost(hostname) {
  return hostname === "localhost" || hostname === "127.0.0.1" || hostname === "[::1]";
}

function validateRemoteApproval({ baseUrl, apiKey, model, approval, now }) {
  if (baseUrl.protocol !== "https:") {
    throw providerConfigurationError(
      "INSECURE_REMOTE_PROVIDER",
      "Remote providers must use HTTPS."
    );
  }
  if (typeof apiKey !== "string" || apiKey.trim().length === 0) {
    throw providerConfigurationError(
      "REMOTE_PROVIDER_API_KEY_REQUIRED",
      "Remote providers require an API key."
    );
  }
  if (!approval) {
    throw providerConfigurationError(
      "REMOTE_PROVIDER_NOT_AUTHORIZED",
      "Remote provider access requires explicit user approval."
    );
  }

  const approvedAt = Date.parse(approval.approvedAt);
  const expiresAt = Date.parse(approval.expiresAt);
  const allowedResourceTypes = REMOTE_APPROVAL_RESOURCE_TYPES.get(
    approval.purpose
  );
  const approvalWindowMs = expiresAt - approvedAt;
  const maximumRuntimeMs = approval.maximumRuntimeMinutes * 60_000;
  const sharedApiScopeValid =
    approval.purpose !== "shared_api_rehearsal" ||
    (approval.resourceType === "shared_free_model_api" &&
      approval.approvedCreditRate === 0 &&
      approval.creditRateUnit === "no_credits" &&
      approval.destroyAfterUse === false);
  const c0bScopeValid =
    approval.purpose !== "c0b_radeon_validation" ||
    (approval.resourceType !== "shared_free_model_api" &&
      approval.creditRateUnit === "credits_per_hour" &&
      approval.destroyAfterUse === true);
  const approvalValid =
    typeof approval.approvalId === "string" &&
    approval.approvalId.length > 0 &&
    approval.approvedBy === "project_owner" &&
    approval.approvedBaseUrl === baseUrl.href &&
    approval.approvedModel === model &&
    allowedResourceTypes?.has(approval.resourceType) === true &&
    Number.isFinite(approval.maximumRuntimeMinutes) &&
    approval.maximumRuntimeMinutes > 0 &&
    Number.isFinite(approval.approvedCreditRate) &&
    approval.approvedCreditRate >= 0 &&
    typeof approval.billingEvidenceRef === "string" &&
    approval.billingEvidenceRef.length > 0 &&
    Number.isFinite(approvedAt) &&
    Number.isFinite(expiresAt) &&
    approvalWindowMs > 0 &&
    approvalWindowMs <= maximumRuntimeMs &&
    approvedAt <= now &&
    now < expiresAt &&
    sharedApiScopeValid &&
    c0bScopeValid;

  if (!approvalValid) {
    throw providerConfigurationError(
      "REMOTE_APPROVAL_INVALID",
      "Remote provider approval is expired or outside its endpoint, model, resource, runtime, or credit scope."
    );
  }
}

function providerConfigurationError(code, message) {
  const error = new Error(message);
  error.code = code;
  return error;
}
