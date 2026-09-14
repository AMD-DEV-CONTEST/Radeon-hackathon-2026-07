import { createHash } from "node:crypto";

export const NATIVE_PI_TOOL_NAMES = Object.freeze(["read", "grep", "find", "ls", "bash"]);

const NATIVE_PI_TOOL_NAME_SET = new Set(NATIVE_PI_TOOL_NAMES);
const SECRET_PATTERNS = [
  { name: "private_key", pattern: /-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----/i },
  { name: "openai_style_key", pattern: /\b(?:sk|rk|pk)-[A-Za-z0-9_-]{16,}\b/ },
  { name: "bearer_token", pattern: /\bBearer\s+[A-Za-z0-9._~+\/-]{12,}={0,2}\b/i },
  {
    name: "credential_assignment",
    pattern:
      /["']?(?:api[_-]?key|access[_-]?token|auth[_-]?token|password|passwd|secret)["']?\s*[:=]\s*["']?[^\s"',}\]]{4,}/i,
  },
];

export class NativePiExportError extends Error {
  constructor(code, message, details = undefined) {
    super(message);
    this.name = "NativePiExportError";
    this.code = code;
    if (details !== undefined) this.details = details;
  }
}

function fail(code, message, details = undefined) {
  throw new NativePiExportError(code, message, details);
}

function isPlainObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function canonicalize(value) {
  if (value === null || typeof value === "string" || typeof value === "boolean") return value;
  if (typeof value === "number") {
    if (!Number.isFinite(value)) fail("non_json_value", "A non-finite number cannot be exported");
    return value;
  }
  if (Array.isArray(value)) return value.map(canonicalize);
  if (!isPlainObject(value)) fail("non_json_value", "Only plain JSON objects can be exported");
  const result = {};
  for (const key of Object.keys(value).sort()) {
    if (value[key] === undefined) continue;
    result[key] = canonicalize(value[key]);
  }
  return result;
}

export function stableJson(value) {
  return JSON.stringify(canonicalize(value));
}

export function sha256Canonical(value) {
  return createHash("sha256").update(stableJson(value)).digest("hex");
}

function sha256Text(value) {
  return createHash("sha256").update(value, "utf8").digest("hex");
}

function cloneJson(value) {
  return JSON.parse(stableJson(value));
}

function assertNoSecrets(value, label) {
  const serialized = stableJson(value);
  for (const { name, pattern } of SECRET_PATTERNS) {
    if (pattern.test(serialized)) {
      fail("secret_detected", `Possible secret detected in ${label}`, { pattern: name });
    }
  }
}

function assertExactKeys(value, allowed, label) {
  const unexpected = Object.keys(value).filter((key) => !allowed.has(key));
  if (unexpected.length > 0) {
    fail("unsupported_provider_field", `${label} contains fields the target schema cannot preserve`, {
      fields: unexpected.sort(),
    });
  }
}

function assertNonEmptyString(value, label) {
  if (typeof value !== "string" || value.trim() === "") {
    fail("invalid_string", `${label} must be a non-empty string`);
  }
}

function rawSystemMessage(payload, roundIndex) {
  if (!isPlainObject(payload) || !Array.isArray(payload.messages)) {
    fail("unsupported_provider_payload", `Provider payload ${roundIndex} is not an OpenAI chat-completions payload`);
  }
  if (payload.messages.some((message) => message?.role === "developer")) {
    fail("developer_role", `Provider payload ${roundIndex} contains a developer message`);
  }
  const systems = payload.messages.filter((message) => message?.role === "system");
  if (systems.length !== 1 || payload.messages[0]?.role !== "system") {
    fail("system_prompt_shape", `Provider payload ${roundIndex} must start with exactly one system message`);
  }
  const system = systems[0];
  assertExactKeys(system, new Set(["role", "content"]), `Provider system message ${roundIndex}`);
  assertNonEmptyString(system.content, `Provider system message ${roundIndex} content`);
  return system;
}

function normalizeProviderTools(rawTools, roundIndex) {
  if (!Array.isArray(rawTools) || rawTools.length === 0) {
    fail("missing_tools", `Provider payload ${roundIndex} has no tools`);
  }
  const names = new Set();
  return rawTools.map((tool, toolIndex) => {
    if (!isPlainObject(tool)) fail("invalid_tool_schema", `Tool ${toolIndex} in round ${roundIndex} is not an object`);
    assertExactKeys(tool, new Set(["type", "function"]), `Tool ${toolIndex} in round ${roundIndex}`);
    if (tool.type !== "function" || !isPlainObject(tool.function)) {
      fail("custom_tool", `Tool ${toolIndex} in round ${roundIndex} is not a native function tool`);
    }
    const fn = tool.function;
    assertExactKeys(fn, new Set(["name", "description", "parameters", "strict"]), `Tool function ${toolIndex}`);
    assertNonEmptyString(fn.name, `Tool ${toolIndex} name`);
    assertNonEmptyString(fn.description, `Tool ${fn.name} description`);
    if (!NATIVE_PI_TOOL_NAME_SET.has(fn.name)) {
      fail("custom_tool", `Non-native Pi tool exposed to the model: ${fn.name}`);
    }
    if (names.has(fn.name)) fail("duplicate_tool", `Duplicate provider tool schema: ${fn.name}`);
    names.add(fn.name);
    if (!isPlainObject(fn.parameters)) fail("invalid_tool_schema", `Tool ${fn.name} parameters must be an object`);
    if (fn.strict !== undefined && fn.strict !== false) {
      fail("unsupported_tool_strictness", `Tool ${fn.name} uses strict=true, which rdk_sft_sample.v1 cannot preserve`);
    }
    return {
      type: "function",
      function: {
        name: fn.name,
        description: fn.description,
        parameters: cloneJson(fn.parameters),
      },
    };
  });
}

function validateProviderRounds(providerPayloads) {
  if (!Array.isArray(providerPayloads) || providerPayloads.length === 0) {
    fail("missing_provider_payload", "At least one before_provider_request payload is required");
  }
  assertNoSecrets(providerPayloads, "provider payloads");

  let firstSystem;
  let firstTools;
  let firstSystemHash;
  let firstToolsHash;
  let previousMessages;
  let previousPayloadHash;
  let logicalRoundCount = 0;
  let retryAttemptCount = 0;
  const payloadHashes = [];

  providerPayloads.forEach((payload, roundIndex) => {
    const system = rawSystemMessage(payload, roundIndex);
    const tools = normalizeProviderTools(payload.tools, roundIndex);
    const systemHash = sha256Canonical(system);
    const toolsHash = sha256Canonical(payload.tools);
    const payloadHash = sha256Canonical(payload);
    if (roundIndex === 0) {
      firstSystem = cloneJson(system);
      firstTools = tools;
      firstSystemHash = systemHash;
      firstToolsHash = toolsHash;
      logicalRoundCount = 1;
    } else {
      if (systemHash !== firstSystemHash) {
        fail("dynamic_system_prompt", `Provider system prompt changed at round ${roundIndex}`);
      }
      if (toolsHash !== firstToolsHash) {
        fail("dynamic_tool_schema", `Provider tool schema changed at round ${roundIndex}`);
      }
      if (payloadHash === previousPayloadHash) {
        // Pi turn-level retry reissues the exact same provider request after a
        // transient stream error. This is another HTTP attempt, not another
        // causal conversation round.
        retryAttemptCount += 1;
      } else {
        if (payload.messages.length <= previousMessages.length) {
          fail("non_monotonic_provider_history", `Provider history did not grow at round ${roundIndex}`);
        }
        const currentPrefix = payload.messages.slice(0, previousMessages.length);
        if (stableJson(currentPrefix) !== stableJson(previousMessages)) {
          fail("rewritten_provider_history", `Provider history prefix changed at round ${roundIndex}`);
        }
        logicalRoundCount += 1;
      }
    }
    previousMessages = cloneJson(payload.messages);
    previousPayloadHash = payloadHash;
    payloadHashes.push(payloadHash);
  });

  return {
    system: firstSystem,
    tools: firstTools,
    rawTools: cloneJson(providerPayloads[0].tools),
    systemHash: firstSystemHash,
    toolsHash: firstToolsHash,
    payloadHashes,
    logicalRoundCount,
    requestAttemptCount: providerPayloads.length,
    retryAttemptCount,
    lastMessages: cloneJson(providerPayloads.at(-1).messages),
  };
}

function parseToolArguments(value, callId) {
  let parsed = value;
  if (typeof value === "string") {
    try {
      parsed = JSON.parse(value);
    } catch {
      fail("invalid_tool_arguments", `Tool call ${callId} arguments are not valid JSON`);
    }
  }
  if (!isPlainObject(parsed)) fail("invalid_tool_arguments", `Tool call ${callId} arguments must be an object`);
  return cloneJson(parsed);
}

function providerAssistantContent(message, index) {
  if (message.content === null || message.content === undefined) return "";
  if (typeof message.content === "string") return message.content;
  fail("image_or_structured_content", `Provider assistant message ${index} has non-text content`);
}

function providerUserContent(message, index) {
  if (typeof message.content === "string") return message.content;
  if (!Array.isArray(message.content) || message.content.length !== 1) {
    fail("image_or_structured_content", `Provider user message ${index} is not one text block`);
  }
  const block = message.content[0];
  if (!isPlainObject(block) || block.type !== "text" || typeof block.text !== "string") {
    fail("image_or_structured_content", `Provider user message ${index} contains non-text content`);
  }
  assertExactKeys(block, new Set(["type", "text"]), `Provider user text block ${index}`);
  return block.text;
}

function buildProviderTranscript(providerInfo, task) {
  const messages = [];
  const callById = new Map();
  const pending = new Set();
  const rawCalls = [];
  const rawResults = new Map();
  let userCount = 0;

  for (let index = 0; index < providerInfo.lastMessages.length; index += 1) {
    const message = providerInfo.lastMessages[index];
    if (!isPlainObject(message)) fail("invalid_provider_message", `Provider message ${index} is not an object`);
    const role = message.role;
    if (role === "developer") fail("developer_role", `Provider message ${index} has developer role`);
    if (role === "system") {
      if (index !== 0) fail("system_prompt_shape", "System message must be first");
      messages.push({ role: "system", content: message.content });
      continue;
    }
    if (role === "user") {
      assertExactKeys(message, new Set(["role", "content", "name"]), `Provider user message ${index}`);
      const userText = providerUserContent(message, index);
      if (pending.size > 0) fail("unresolved_tool_calls", `User message ${index} appears before tool results complete`);
      userCount += 1;
      if (userCount !== 1 || index !== 1) {
        fail("extra_user_context", "Native collection accepts exactly one visible user instruction");
      }
      if (userText !== task.instruction) {
        fail("instruction_mismatch", "Task instruction differs from the actual provider user message");
      }
      messages.push({ role: "user", content: userText });
      continue;
    }
    if (role === "assistant") {
      assertExactKeys(
        message,
        new Set(["role", "content", "reasoning_content", "tool_calls"]),
        `Provider assistant message ${index}`,
      );
      if (
        message.reasoning_content !== undefined &&
        message.reasoning_content !== null &&
        message.reasoning_content !== ""
      ) {
        fail("thinking_content", `Provider assistant message ${index} contains non-empty reasoning content`);
      }
      if (pending.size > 0) {
        fail("unresolved_tool_calls", `Assistant message ${index} appears before tool results complete`);
      }
      if (!Array.isArray(message.tool_calls) || message.tool_calls.length === 0) {
        fail("non_tool_intermediate_assistant", `Provider assistant message ${index} has no tool calls`);
      }
      const toolCalls = message.tool_calls.map((call, callIndex) => {
        if (!isPlainObject(call)) fail("invalid_tool_call", `Tool call ${callIndex} at message ${index} is invalid`);
        assertExactKeys(call, new Set(["id", "type", "function"]), `Tool call ${callIndex} at message ${index}`);
        assertNonEmptyString(call.id, `Tool call ${callIndex} id`);
        if (callById.has(call.id)) fail("duplicate_tool_call_id", `Duplicate tool call id: ${call.id}`);
        if (call.type !== "function" || !isPlainObject(call.function)) {
          fail("custom_tool", `Tool call ${call.id} is not a function call`);
        }
        assertExactKeys(call.function, new Set(["name", "arguments"]), `Tool call ${call.id} function`);
        const name = call.function.name;
        if (!NATIVE_PI_TOOL_NAME_SET.has(name)) fail("custom_tool", `Non-native Pi tool called: ${name}`);
        if (!providerInfo.tools.some((tool) => tool.function.name === name)) {
          fail("undeclared_tool", `Tool call ${call.id} references undeclared tool ${name}`);
        }
        const args = parseToolArguments(call.function.arguments, call.id);
        const normalized = {
          id: call.id,
          type: "function",
          function: { name, arguments: args },
        };
        callById.set(call.id, { name, arguments: args });
        pending.add(call.id);
        rawCalls.push({ id: call.id, name, arguments: args });
        return normalized;
      });
      messages.push({ role: "assistant", content: providerAssistantContent(message, index), tool_calls: toolCalls });
      continue;
    }
    if (role === "tool") {
      assertExactKeys(message, new Set(["role", "content", "tool_call_id", "name"]), `Provider tool message ${index}`);
      assertNonEmptyString(message.tool_call_id, `Provider tool message ${index} call id`);
      if (typeof message.content !== "string") {
        fail("image_or_structured_content", `Provider tool result ${message.tool_call_id} has non-text content`);
      }
      const call = callById.get(message.tool_call_id);
      if (!call) fail("orphan_tool_result", `Orphan provider tool result: ${message.tool_call_id}`);
      if (!pending.has(message.tool_call_id)) {
        fail("duplicate_tool_result", `Duplicate or out-of-order tool result: ${message.tool_call_id}`);
      }
      if (message.name !== undefined && message.name !== call.name) {
        fail("tool_name_mismatch", `Provider tool result name differs for ${message.tool_call_id}`);
      }
      pending.delete(message.tool_call_id);
      rawResults.set(message.tool_call_id, message.content);
      messages.push({
        role: "tool",
        tool_call_id: message.tool_call_id,
        name: call.name,
        content: message.content,
      });
      continue;
    }
    fail("unsupported_provider_role", `Unsupported provider role at message ${index}: ${String(role)}`);
  }

  if (userCount !== 1) fail("missing_user", "Provider history must contain exactly one user instruction");
  if (rawCalls.length === 0) fail("missing_tool_call", "Native agentic trajectory contains no tool call");
  if (pending.size > 0) fail("unresolved_tool_calls", "Provider history ends with unresolved tool calls");
  if (messages.at(-1)?.role !== "tool") {
    fail("incomplete_provider_history", "The final provider request must include the last tool result");
  }
  return { messages, callById, rawCalls, rawResults };
}

function piToolResultText(message) {
  if (!Array.isArray(message.content)) fail("invalid_pi_tool_result", "Pi tool result content must be an array");
  if (message.content.some((block) => block?.type === "image")) {
    fail("image_content", `Pi tool result ${message.toolCallId} contains an image`);
  }
  if (message.content.some((block) => block?.type !== "text")) {
    fail("unsupported_pi_content", `Pi tool result ${message.toolCallId} contains non-text content`);
  }
  const text = message.content.map((block) => block.text).join("\n");
  return text.length > 0 ? text : "(no tool output)";
}

function validatePiMessages(piMessages, providerTranscript, providerRoundCount) {
  if (!Array.isArray(piMessages) || piMessages.length < 4) {
    fail("missing_pi_messages", "Final Pi messages are required for causal validation");
  }
  assertNoSecrets(piMessages, "Pi messages");
  const assistants = [];
  const piCalls = [];
  const piResults = new Map();
  const thinkingSummaries = [];
  let userCount = 0;

  for (let index = 0; index < piMessages.length; index += 1) {
    const message = piMessages[index];
    if (!isPlainObject(message)) fail("invalid_pi_message", `Pi message ${index} is not an object`);
    if (!new Set(["user", "assistant", "toolResult"]).has(message.role)) {
      fail("custom_pi_message", `Unsupported Pi message role: ${String(message.role)}`);
    }
    if (message.role === "user") {
      userCount += 1;
      const validTextArray =
        Array.isArray(message.content) &&
        message.content.length === 1 &&
        message.content[0]?.type === "text" &&
        typeof message.content[0]?.text === "string";
      if (userCount !== 1 || index !== 0 || (!validTextArray && typeof message.content !== "string")) {
        fail("extra_user_context", "Pi messages must contain exactly one initial text user instruction");
      }
      const userText = typeof message.content === "string" ? message.content : message.content[0].text;
      if (userText !== providerTranscript.messages[1]?.content) {
        fail("instruction_mismatch", "Pi user instruction differs from provider-visible instruction");
      }
      continue;
    }
    if (message.role === "assistant") {
      if (!Array.isArray(message.content)) fail("invalid_pi_assistant", `Pi assistant message ${index} has invalid content`);
      if (message.content.some((block) => block?.type === "image")) {
        fail("image_content", `Pi assistant message ${index} contains an image`);
      }
      if (message.content.some((block) => !new Set(["text", "thinking", "toolCall"]).has(block?.type))) {
        fail("unsupported_pi_content", `Pi assistant message ${index} has unsupported content`);
      }
      for (const block of message.content.filter((item) => item.type === "thinking")) {
        if (typeof block.thinking !== "string") {
          fail("invalid_thinking_content", `Pi assistant message ${index} has invalid thinking content`);
        }
        thinkingSummaries.push({
          message_index: index,
          chars: block.thinking.length,
          sha256: sha256Text(block.thinking),
        });
      }
      if (new Set(["error", "aborted", "length", "pending"]).has(message.stopReason)) {
        fail("unsuccessful_stop_reason", `Pi assistant message ${index} stopped with ${message.stopReason}`);
      }
      if (message.errorMessage) fail("assistant_error", `Pi assistant message ${index} has an error`);
      const calls = message.content.filter((block) => block.type === "toolCall");
      for (const call of calls) {
        if (!NATIVE_PI_TOOL_NAME_SET.has(call.name)) fail("custom_tool", `Non-native Pi tool called: ${call.name}`);
        piCalls.push({ id: call.id, name: call.name, arguments: cloneJson(call.arguments) });
      }
      assistants.push({ message, calls });
      continue;
    }
    if (message.isError) fail("tool_error", `Pi tool result ${message.toolCallId} is marked as an error`);
    if (Array.isArray(message.addedToolNames) && message.addedToolNames.length > 0) {
      fail("dynamic_tool_schema", `Pi tool result ${message.toolCallId} dynamically loaded tools`);
    }
    if (piResults.has(message.toolCallId)) fail("duplicate_tool_result", `Duplicate Pi tool result: ${message.toolCallId}`);
    piResults.set(message.toolCallId, { message, text: piToolResultText(message) });
  }

  if (userCount !== 1) fail("extra_user_context", "Pi messages must contain exactly one user instruction");
  if (assistants.length !== providerRoundCount) {
    fail("provider_round_mismatch", "Provider request count differs from Pi assistant turn count", {
      provider_rounds: providerRoundCount,
      assistant_turns: assistants.length,
    });
  }
  const final = assistants.at(-1);
  if (piMessages.at(-1) !== final.message) fail("non_final_assistant", "Last Pi message is not the final assistant message");
  if (final.message.stopReason !== "stop" || final.calls.length > 0) {
    fail("invalid_final_stop", "Final Pi assistant must stop normally without tool calls");
  }
  for (const intermediate of assistants.slice(0, -1)) {
    if (intermediate.message.stopReason !== "toolUse" || intermediate.calls.length === 0) {
      fail("invalid_intermediate_stop", "Every intermediate Pi assistant turn must stop for tool use");
    }
  }
  if (stableJson(piCalls) !== stableJson(providerTranscript.rawCalls)) {
    fail("provider_pi_call_mismatch", "Provider-visible tool calls differ from final Pi messages");
  }
  for (const call of providerTranscript.rawCalls) {
    const result = piResults.get(call.id);
    if (!result) fail("missing_pi_tool_result", `No Pi tool result found for ${call.id}`);
    if (result.message.toolName !== call.name) fail("tool_name_mismatch", `Pi tool result name differs for ${call.id}`);
    if (result.text !== providerTranscript.rawResults.get(call.id)) {
      fail("tool_result_visibility_mismatch", `Stored Pi tool result differs from text seen by the model for ${call.id}`);
    }
  }
  if (piResults.size !== providerTranscript.rawCalls.length) {
    fail("extra_pi_tool_result", "Pi messages contain tool results absent from provider history");
  }

  const textBlocks = final.message.content.filter((block) => block.type === "text");
  if (
    textBlocks.length === 0 ||
    final.message.content.some((block) => !new Set(["text", "thinking"]).has(block.type))
  ) {
    fail("invalid_final_content", "Final Pi assistant must contain text and optional non-replayed thinking only");
  }
  const finalText = textBlocks.map((block) => block.text).join("");
  if (finalText.trim() === "") fail("empty_final_answer", "Final Pi assistant answer is empty");
  return { finalText, thinkingSummaries };
}

function asEntries(value, label) {
  const entries = Array.isArray(value) ? value : value?.entries;
  if (!Array.isArray(entries)) fail("missing_audit", `${label} entries are required`);
  assertNoSecrets(entries, label);
  return entries;
}

function valueByAliases(value, aliases) {
  for (const alias of aliases) {
    if (Object.prototype.hasOwnProperty.call(value, alias)) return value[alias];
  }
  return undefined;
}

function validatePolicyAudit(policyAudit, calls) {
  const entries = asEntries(policyAudit, "policy audit");
  if (entries.length !== calls.length) fail("policy_audit_count", "Policy audit must contain one entry per tool call");
  const byId = new Map();
  for (const entry of entries) {
    if (!isPlainObject(entry)) fail("invalid_policy_audit", "Policy audit entry must be an object");
    const id = valueByAliases(entry, ["tool_call_id", "toolCallId"]);
    const name = valueByAliases(entry, ["tool_name", "toolName"]);
    if (typeof id !== "string" || byId.has(id)) fail("invalid_policy_audit", "Policy audit ids must be unique strings");
    if (entry.decision !== "allow" || entry.blocked === true || entry.isError === true || entry.is_error === true) {
      fail("blocked_or_failed_policy", `Policy did not cleanly allow tool call ${id}`);
    }
    if (entry.error !== undefined && entry.error !== null && entry.error !== "") {
      fail("blocked_or_failed_policy", `Policy audit contains an error for ${id}`);
    }
    byId.set(id, { entry, name });
  }
  for (const call of calls) {
    const observed = byId.get(call.id);
    if (!observed) fail("missing_policy_audit", `Missing policy audit for ${call.id}`);
    if (observed.name !== call.name) fail("policy_audit_mismatch", `Policy tool name differs for ${call.id}`);
    const requested = valueByAliases(observed.entry, [
      "requested_arguments",
      "requestedArguments",
      "requested_args",
      "requestedArgs",
    ]);
    if (!isPlainObject(requested) || stableJson(requested) !== stableJson(call.arguments)) {
      fail("policy_audit_mismatch", `Policy requested arguments differ for ${call.id}`);
    }
  }
  return entries;
}

function validateBoardEvidence(boardEvidence, calls) {
  const bashCalls = calls.filter((call) => call.name === "bash");
  const entries = asEntries(boardEvidence, "board evidence");
  if (entries.length !== bashCalls.length) {
    fail("board_evidence_count", "Board evidence must contain exactly one entry per native bash call");
  }
  const byId = new Map();
  for (const entry of entries) {
    if (!isPlainObject(entry)) fail("invalid_board_evidence", "Board evidence entry must be an object");
    const id = valueByAliases(entry, ["tool_call_id", "toolCallId"]);
    if (typeof id !== "string" || byId.has(id)) fail("invalid_board_evidence", "Board evidence ids must be unique strings");
    if (entry.schema_version !== "rdk_pi_native_board_dispatch.v1") {
      fail("invalid_board_evidence", `Board evidence schema differs for ${id}`);
    }
    if (entry.executed !== true) fail("unexecuted_board_call", `Board evidence does not prove execution for ${id}`);
    if (entry.status !== "observed") fail("failed_board_call", `Board execution was not observed for ${id}`);
    const transport = valueByAliases(entry, ["transport", "remote_transport"]);
    if (transport !== "ssh" || entry.evidence_source !== "native_board_cli") {
      fail("non_ssh_evidence", `Board evidence is not native_board_cli SSH evidence for ${id}`);
    }
    if (
      typeof entry.dispatch_id !== "string" ||
      !/^[a-f0-9]{32}$/.test(entry.dispatch_id) ||
      typeof entry.action !== "string" ||
      entry.action.trim() === "" ||
      typeof entry.evidence_path !== "string" ||
      entry.evidence_path.trim() === "" ||
      !/^[a-f0-9]{64}$/.test(entry.stdout_sha256 || "") ||
      !/^[a-f0-9]{64}$/.test(entry.stderr_sha256 || "")
    ) {
      fail("invalid_board_evidence", `Board wrapper evidence is incomplete for ${id}`);
    }
    if (
      !Number.isInteger(entry.exit_code) ||
      entry.isError === true ||
      entry.is_error === true ||
      entry.timed_out !== false
    ) {
      fail("failed_board_call", `Board execution failed for ${id}`);
    }
    byId.set(id, entry);
  }
  for (const call of bashCalls) {
    const entry = byId.get(call.id);
    if (!entry) fail("missing_board_evidence", `Missing board evidence for ${call.id}`);
    const requested = valueByAliases(entry, ["requested_command", "requestedCommand"]);
    if (requested !== call.arguments.command) {
      fail("board_evidence_mismatch", `Board evidence command differs for ${call.id}`);
    }
  }
  return entries;
}

function validatePiEvents(piEvents) {
  if (piEvents === undefined) return [];
  if (!Array.isArray(piEvents)) fail("invalid_pi_events", "piEvents must be an array when provided");
  assertNoSecrets(piEvents, "Pi events");
  for (const event of piEvents) {
    if (!isPlainObject(event)) fail("invalid_pi_events", "Pi event must be an object");
    if ((event.type === "tool_execution_end" || event.type === "tool_result") && event.isError === true) {
      fail("tool_error_event", `Pi event reports a tool error for ${event.toolCallId || "unknown"}`);
    }
    if (event.blocked === true || event.decision === "deny" || event.decision === "block") {
      fail("blocked_event", `Pi event reports a blocked operation: ${event.type || "unknown"}`);
    }
  }
  return piEvents;
}

function validateTask(task) {
  if (!isPlainObject(task)) fail("invalid_task", "task must be an object");
  if (task.profile !== "agentic") fail("invalid_profile", "Native Pi exporter only accepts agentic tasks");
  if (!/^agent_[0-9]{6}$/.test(task.task_id || "")) fail("invalid_task_id", "Native task_id must match agent_NNNNNN");
  if (!new Set(["train", "validation", "test"]).has(task.split)) fail("invalid_split", "Invalid task split");
  assertNonEmptyString(task.instruction, "task.instruction");
  const source = task.metadata?.source;
  assertNonEmptyString(source, "task.metadata.source");
}

/**
 * Losslessly exports the provider-visible native Pi transcript into rdk_sft_sample.v1.
 *
 * The provider payloads must be deep copies captured by before_provider_request.
 * The policy audit must contain one allow entry per call. Every native bash call
 * additionally requires independent SSH board evidence.
 */
export function exportNativePiSample({
  task,
  providerPayloads,
  piMessages,
  piEvents = undefined,
  policyAudit,
  boardEvidence,
  metadata = {},
}) {
  validateTask(task);
  if (!isPlainObject(metadata)) fail("invalid_metadata", "metadata must be an object");
  assertNoSecrets(task, "task");
  assertNoSecrets(metadata, "metadata");

  const providerInfo = validateProviderRounds(providerPayloads);
  const providerTranscript = buildProviderTranscript(providerInfo, task);
  const pi = validatePiMessages(piMessages, providerTranscript, providerInfo.logicalRoundCount);
  const policyEntries = validatePolicyAudit(policyAudit, providerTranscript.rawCalls);
  const evidenceEntries = validateBoardEvidence(boardEvidence, providerTranscript.rawCalls);
  const eventEntries = validatePiEvents(piEvents);

  const transcriptMessages = [...providerTranscript.messages, { role: "assistant", content: pi.finalText }];
  const activeToolNames = providerInfo.tools.map((tool) => tool.function.name);
  const provenance = {
    behavior_origin: "pi-coding-agent-native",
    trace_contract_version: "pi_native_export.v1",
    provider_api: "openai-completions",
    provider_round_count: providerInfo.logicalRoundCount,
    provider_request_attempt_count: providerInfo.requestAttemptCount,
    provider_retry_attempt_count: providerInfo.retryAttemptCount,
    provider_request_sha256: providerInfo.payloadHashes,
    provider_system_sha256: providerInfo.systemHash,
    provider_tools_sha256: providerInfo.toolsHash,
    canonical_system_sha256: sha256Text(providerInfo.system.content),
    canonical_tools_sha256: sha256Canonical(providerInfo.tools),
    pi_messages_sha256: sha256Canonical(piMessages),
    pi_events_sha256: sha256Canonical(eventEntries),
    policy_audit_sha256: sha256Canonical(policyEntries),
    board_evidence_sha256: sha256Canonical(evidenceEntries),
    omitted_thinking_sha256: sha256Canonical(pi.thinkingSummaries),
    omitted_thinking_block_count: pi.thinkingSummaries.length,
    active_tool_names: activeToolNames,
    tool_call_count: providerTranscript.rawCalls.length,
    bash_call_count: providerTranscript.rawCalls.filter((call) => call.name === "bash").length,
  };
  const sample = {
    schema_version: "rdk_sft_sample.v1",
    task_id: task.task_id,
    profile: "agentic",
    split: task.split,
    messages: transcriptMessages,
    tools: providerInfo.tools,
    outcome: { status: "success", final_answer: pi.finalText },
    metadata: {
      ...cloneJson(task.metadata),
      ...cloneJson(metadata),
      ...provenance,
    },
  };
  assertNoSecrets(sample, "exported sample");

  const audit = {
    schema_version: "pi_native_export_audit.v1",
    accepted: true,
    task_id: task.task_id,
    ...provenance,
    transcript_sha256: sha256Canonical(sample.messages),
    sample_sha256: sha256Canonical(sample),
  };
  return { sample, audit };
}
