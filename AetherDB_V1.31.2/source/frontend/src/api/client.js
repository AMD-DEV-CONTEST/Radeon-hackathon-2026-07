const DEFAULT_CONFIG = {
  baseUrl: "/api",
  apiKey: "",
  timeoutMs: 15_000,
  streamTimeoutMs: 300_000,
};

let config = { ...DEFAULT_CONFIG };
const desktopRuntime = Boolean(globalThis.window?.__TAURI_INTERNALS__);
let desktopRuntimeConfigured = !desktopRuntime;

const ERROR_CODE_ALIASES = Object.freeze({
  AUTH_FAILED: "API_UNAUTHORIZED",
  CREDENTIAL_UNAVAILABLE: "API_UNAUTHORIZED",
  INVALID_ENDPOINT: "API_ENDPOINT_INVALID",
  TARGET_BLOCKED: "API_ENDPOINT_INVALID",
  DNS_FAILED: "API_ENDPOINT_INVALID",
  CONNECTION_FAILED: "API_ENDPOINT_INVALID",
  REDIRECT_BLOCKED: "API_ENDPOINT_INVALID",
  NO_MODELS: "MODEL_NOT_FOUND",
  TIMEOUT: "MODEL_REQUEST_TIMEOUT",
});

const ERROR_MESSAGES = Object.freeze({
  "zh-CN": {
    BACKEND_UNAVAILABLE: "AetherDB 本地后台服务未启动或已经退出，请重新启动后台服务后重试。",
    BACKEND_START_FAILED: "AetherDB 本地后台服务启动失败，请查看启动日志后重试。",
    BACKEND_PORT_IN_USE: "本地端口已被占用，AetherDB 无法在该端口启动后台服务。",
    BACKEND_BUILD_MISMATCH: "桌面客户端与本地后端不是同一次构建，请重新安装完整发行包。",
    BACKEND_TIMEOUT: "AetherDB 本地后台服务没有及时响应，请重试。",
    API_UNAUTHORIZED: "访问凭据无效或权限不足。",
    API_ENDPOINT_INVALID: "模型服务地址无效、无法访问或服务类型不匹配。",
    MODEL_NOT_FOUND: "模型服务中没有找到可用的模型。",
    MODEL_REQUEST_TIMEOUT: "云端模型连接测试超时，请检查网络、地址和代理设置。",
    DATABASE_WRITE_FAILED: "数据库写入失败，请检查磁盘空间、文件权限或数据库占用状态。",
    REQUEST_CANCELLED: "请求已取消。",
    UNKNOWN_REQUEST_ERROR: "请求失败，无法确定具体原因，请查看日志。",
  },
  "en-US": {
    BACKEND_UNAVAILABLE: "The local AetherDB backend is not running. Restart it and try again.",
    BACKEND_START_FAILED: "The local AetherDB backend failed to start. Review the startup log and retry.",
    BACKEND_PORT_IN_USE: "The selected local port is occupied, so the AetherDB backend could not start.",
    BACKEND_BUILD_MISMATCH: "The desktop client and local backend came from different builds. Reinstall the complete release package.",
    BACKEND_TIMEOUT: "The local AetherDB backend did not respond in time.",
    API_UNAUTHORIZED: "The API credential is invalid or does not have sufficient permission.",
    API_ENDPOINT_INVALID: "The model endpoint is invalid, unreachable, or uses an unsupported API format.",
    MODEL_NOT_FOUND: "No usable model was found at the configured provider.",
    MODEL_REQUEST_TIMEOUT: "The cloud model connection test timed out. Check the network, URL, and proxy.",
    DATABASE_WRITE_FAILED: "The database write failed. Check disk space, permissions, and database locks.",
    REQUEST_CANCELLED: "The request was cancelled.",
    UNKNOWN_REQUEST_ERROR: "The request failed for an unknown reason. Review the logs for details.",
  },
});

export class ApiError extends Error {
  constructor(message, { status = 0, code = "API_ERROR", detail = null } = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.detail = detail;
  }
}

function currentLocale() {
  return globalThis.document?.documentElement?.lang === "en-US" ? "en-US" : "zh-CN";
}

export function normalizeApiErrorCode(code, status = 0) {
  if (status === 401 || status === 403) return "API_UNAUTHORIZED";
  return ERROR_CODE_ALIASES[code] || code || "UNKNOWN_REQUEST_ERROR";
}

export function apiErrorMessage(code) {
  const normalized = normalizeApiErrorCode(code);
  const catalog = ERROR_MESSAGES[currentLocale()];
  return catalog[normalized] || catalog.UNKNOWN_REQUEST_ERROR;
}

export function configureApiClient(overrides = {}) {
  const next = { ...config, ...overrides };
  if (typeof next.apiKey !== "string" || next.apiKey.length > 8192) {
    throw new TypeError("API credential must be a bounded string");
  }
  if (next.baseUrl !== "/api") {
    let parsed;
    try {
      parsed = new URL(next.baseUrl);
    } catch {
      throw new TypeError("API base URL must be /api or an absolute loopback URL");
    }
    if (
      parsed.protocol !== "http:"
      || parsed.hostname !== "127.0.0.1"
      || !parsed.port
      || parsed.pathname.replace(/\/$/, "") !== "/api"
      || parsed.username
      || parsed.password
      || parsed.search
      || parsed.hash
    ) {
      throw new TypeError("Desktop API base URL must use a dynamic 127.0.0.1 port and /api path");
    }
    next.baseUrl = next.baseUrl.replace(/\/$/, "");
  }
  config = next;
  desktopRuntimeConfigured = true;
}

function notifyBackendUnavailable(detail = {}) {
  if (!desktopRuntime || typeof globalThis.window?.dispatchEvent !== "function") return;
  globalThis.window.dispatchEvent(new CustomEvent("aetherdb:backend-unavailable", {
    detail,
  }));
}

function getApiKey() {
  if (config.apiKey) return config.apiKey;
  if (typeof sessionStorage === "undefined") return "";
  return sessionStorage.getItem("aetherdb_api_key") || sessionStorage.getItem("apiKey") || "";
}

export function buildQuery(params = {}) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") return;
    const values = Array.isArray(value) ? value : [value];
    values.forEach((item) => query.append(key, String(item)));
  });
  const encoded = query.toString();
  return encoded ? `?${encoded}` : "";
}

function createAbortContext(externalSignal, timeoutMs) {
  const controller = new AbortController();
  let timedOut = false;
  const abortFromExternal = () => controller.abort(externalSignal.reason);
  if (externalSignal) {
    if (externalSignal.aborted) abortFromExternal();
    else externalSignal.addEventListener("abort", abortFromExternal, { once: true });
  }
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);
  return {
    signal: controller.signal,
    timedOut: () => timedOut,
    dispose() {
      clearTimeout(timer);
      externalSignal?.removeEventListener("abort", abortFromExternal);
    },
  };
}

async function parseBody(response) {
  if (response.status === 204) return null;
  const text = await response.text();
  if (!text) return null;
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("json")) {
    try {
      return JSON.parse(text);
    } catch {
      throw new ApiError("Invalid JSON response", { status: response.status, code: "INVALID_RESPONSE" });
    }
  }
  return text;
}

async function fetchResponse(path, options = {}, timeoutMs = config.timeoutMs) {
  if (desktopRuntime && !desktopRuntimeConfigured) {
    const error = new ApiError(apiErrorMessage("BACKEND_UNAVAILABLE"), {
      code: "BACKEND_UNAVAILABLE",
      detail: { cause: "DesktopRuntimeNotConfigured" },
    });
    notifyBackendUnavailable(error.detail);
    throw error;
  }
  const url = `${config.baseUrl}${path}`;
  const apiKey = getApiKey();
  const headers = new Headers(options.headers || {});
  if (apiKey) headers.set("X-API-Key", apiKey);
  const isFormData = typeof FormData !== "undefined" && options.body instanceof FormData;
  if (options.body != null && !isFormData && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const abort = createAbortContext(options.signal, timeoutMs);
  try {
    const response = await fetch(url, { ...options, headers, signal: abort.signal });
    return { response, abort };
  } catch (error) {
    if (abort.timedOut()) {
      abort.dispose();
      const code = options.timeoutCode || "BACKEND_TIMEOUT";
      throw new ApiError(apiErrorMessage(code), { code });
    }
    if (abort.signal.aborted) {
      abort.dispose();
      throw new ApiError(apiErrorMessage("REQUEST_CANCELLED"), { code: "REQUEST_CANCELLED" });
    }
    abort.dispose();
    notifyBackendUnavailable({ cause: error?.name || "FetchError" });
    throw new ApiError(apiErrorMessage("BACKEND_UNAVAILABLE"), {
      code: "BACKEND_UNAVAILABLE",
      detail: { cause: error?.name || "FetchError" },
    });
  }
}

export async function request(path, options = {}) {
  const { response, abort } = await fetchResponse(path, options, options.timeoutMs || config.timeoutMs);
  try {
    const body = await parseBody(response);
    if (!response.ok) {
      const detail = body?.detail ?? body;
      const code = normalizeApiErrorCode(detail?.code, response.status);
      const message = ERROR_MESSAGES[currentLocale()][code]
        ? apiErrorMessage(code)
        : typeof detail === "string" ? detail : detail?.message || `HTTP ${response.status}`;
      throw new ApiError(message, {
        status: response.status,
        code,
        detail,
      });
    }
    return body;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (abort.timedOut()) {
      const code = options.timeoutCode || "BACKEND_TIMEOUT";
      throw new ApiError(apiErrorMessage(code), { code });
    }
    if (abort.signal.aborted) {
      throw new ApiError(apiErrorMessage("REQUEST_CANCELLED"), { code: "REQUEST_CANCELLED" });
    }
    throw error;
  } finally {
    abort.dispose();
  }
}

export async function requestBlob(path, options = {}) {
  const { response, abort } = await fetchResponse(path, options, options.timeoutMs || config.timeoutMs);
  try {
    if (!response.ok) {
      const body = await parseBody(response);
      const detail = body?.detail ?? body;
      const code = normalizeApiErrorCode(detail?.code, response.status);
      const message = ERROR_MESSAGES[currentLocale()][code]
        ? apiErrorMessage(code)
        : typeof detail === "string" ? detail : detail?.message || `HTTP ${response.status}`;
      throw new ApiError(message, {
        status: response.status,
        code,
        detail,
      });
    }
    return await response.blob();
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (abort.timedOut()) {
      const code = options.timeoutCode || "BACKEND_TIMEOUT";
      throw new ApiError(apiErrorMessage(code), { code });
    }
    if (abort.signal.aborted) {
      throw new ApiError(apiErrorMessage("REQUEST_CANCELLED"), { code: "REQUEST_CANCELLED" });
    }
    throw error;
  } finally {
    abort.dispose();
  }
}

export class StreamSequenceBuffer {
  constructor(startSequence = 0) {
    this.nextSequence = startSequence;
    this.pending = new Map();
  }

  push(event) {
    if (!Number.isInteger(event?.sequence) || event.sequence < this.nextSequence) return [];
    if (event.protocol_version !== "1.0" || this.pending.has(event.sequence)) return [];
    this.pending.set(event.sequence, event);
    const ready = [];
    while (this.pending.has(this.nextSequence)) {
      ready.push(this.pending.get(this.nextSequence));
      this.pending.delete(this.nextSequence);
      this.nextSequence += 1;
    }
    return ready;
  }
}

export async function streamNdjson(path, body, { signal, timeoutMs, onEvent } = {}) {
  const { response, abort } = await fetchResponse(
    path,
    { method: "POST", body: JSON.stringify(body), signal },
    timeoutMs || config.streamTimeoutMs,
  );
  try {
    if (!response.ok) {
      const errorBody = await parseBody(response);
      const detail = errorBody?.detail ?? errorBody;
      const code = normalizeApiErrorCode(detail?.code, response.status);
      throw new ApiError(
        ERROR_MESSAGES[currentLocale()][code]
          ? apiErrorMessage(code)
          : typeof detail === "string" ? detail : detail?.message || `HTTP ${response.status}`,
        {
        status: response.status,
        code,
        detail,
        },
      );
    }
    if (!response.body) throw new ApiError("Streaming response body is unavailable", { code: "INVALID_RESPONSE" });

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    const sequence = new StreamSequenceBuffer();
    let buffered = "";
    const received = [];
    while (true) {
      const { value, done } = await reader.read();
      buffered += decoder.decode(value || new Uint8Array(), { stream: !done });
      if (buffered.length > 1_000_000) {
        await reader.cancel();
        throw new ApiError("Stream event exceeds limit", { code: "STREAM_EVENT_TOO_LARGE" });
      }
      const lines = buffered.split("\n");
      buffered = lines.pop() || "";
      for (const line of lines) {
        if (!line.trim()) continue;
        let event;
        try {
          event = JSON.parse(line);
        } catch {
          throw new ApiError("Invalid NDJSON event", { code: "INVALID_STREAM_EVENT" });
        }
        for (const ordered of sequence.push(event)) {
          received.push(ordered);
          onEvent?.(ordered);
        }
      }
      if (done) break;
    }
    if (buffered.trim()) {
      let event;
      try {
        event = JSON.parse(buffered);
      } catch {
        throw new ApiError("Invalid NDJSON event", { code: "INVALID_STREAM_EVENT" });
      }
      for (const ordered of sequence.push(event)) {
        received.push(ordered);
        onEvent?.(ordered);
      }
    }
    return received;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (abort.timedOut()) {
      const code = timeoutMs ? "MODEL_REQUEST_TIMEOUT" : "BACKEND_TIMEOUT";
      throw new ApiError(apiErrorMessage(code), { code });
    }
    if (abort.signal.aborted) {
      throw new ApiError(apiErrorMessage("REQUEST_CANCELLED"), { code: "REQUEST_CANCELLED" });
    }
    throw error;
  } finally {
    abort.dispose();
  }
}

export function get(path, params, options = {}) {
  return request(`${path}${buildQuery(params)}`, { ...options, method: "GET" });
}

export function post(path, body, options = {}) {
  return request(path, { ...options, method: "POST", body: JSON.stringify(body) });
}

export function put(path, body, options = {}) {
  return request(path, { ...options, method: "PUT", body: JSON.stringify(body) });
}

export function del(path, options = {}) {
  return request(path, { ...options, method: "DELETE" });
}

export function patch(path, body, options = {}) {
  return request(path, { ...options, method: "PATCH", body: JSON.stringify(body) });
}

export function upload(path, formData, options = {}) {
  return request(path, { ...options, method: "POST", body: formData });
}

export function getBlob(path, params, options = {}) {
  return requestBlob(`${path}${buildQuery(params)}`, { ...options, method: "GET" });
}
