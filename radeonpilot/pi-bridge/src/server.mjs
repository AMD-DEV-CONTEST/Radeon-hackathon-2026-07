import http from "node:http";
import { randomUUID } from "node:crypto";
import { performance } from "node:perf_hooks";
import { fileURLToPath } from "node:url";
import { loadConfig, PI_SDK_PACKAGE, PI_SDK_VERSION, readModelConfigStatus } from "./config.mjs";
import { writeAudit } from "./audit.mjs";
import { HttpError, validateOrchestrateRequest } from "./validation.mjs";
import { Orchestrator } from "./orchestrator.mjs";
import { probeRuntime } from "./runtime.mjs";

function sendJson(res, status, body, headers = {}) {
  const payload = JSON.stringify(body);
  res.writeHead(status, {
    "content-type": "application/json; charset=utf-8",
    "content-length": Buffer.byteLength(payload),
    "cache-control": "no-store",
    ...headers
  });
  res.end(payload);
}

function corsHeaders(config, req) {
  const origin = req.headers.origin;
  if (!origin) return {};
  if (!config.corsOrigins.includes(origin)) return null;
  return {
    "access-control-allow-origin": origin,
    "access-control-allow-methods": "GET,POST,OPTIONS",
    "access-control-allow-headers": "content-type",
    "vary": "origin"
  };
}

async function readJsonBody(req, limit) {
  const chunks = [];
  let total = 0;
  for await (const chunk of req) {
    total += chunk.length;
    if (total > limit) throw new HttpError(413, "request_too_large", `Request body exceeds ${limit} bytes`);
    chunks.push(chunk);
  }
  if (total === 0) throw new HttpError(400, "invalid_json", "Request body is required");
  try {
    return JSON.parse(Buffer.concat(chunks).toString("utf8"));
  } catch {
    throw new HttpError(400, "invalid_json", "Request body must be valid JSON");
  }
}

function errorBody(error, requestId) {
  const status = error instanceof HttpError ? error.status : 500;
  return {
    status,
    body: {
      error: {
        code: error instanceof HttpError ? error.code : "internal_error",
        message: error instanceof Error ? error.message : String(error),
        request_id: requestId,
        details: error instanceof HttpError ? error.details : undefined
      }
    }
  };
}

export function createHttpServer(config, orchestrateFn) {
  const runtimePromise = probeRuntime(config);
  return http.createServer(async (req, res) => {
    const requestId = randomUUID();
    const started = performance.now();
    const cors = corsHeaders(config, req);
    if (cors === null) {
      sendJson(res, 403, { error: { code: "cors_forbidden", message: "Origin is not allowed", request_id: requestId } });
      return;
    }
    if (req.method === "OPTIONS") {
      sendJson(res, 204, {}, cors);
      return;
    }
    try {
      if (req.method === "GET" && req.url === "/health") {
        const modelConfig = await readModelConfigStatus(config);
        const runtime = await runtimePromise;
        sendJson(res, 200, {
          ok: true,
          pi: { package: PI_SDK_PACKAGE, version: PI_SDK_VERSION },
          model: {
            provider: config.providerId,
            id: config.modelId,
            baseUrl: modelConfig.baseUrl,
            providerConfigured: modelConfig.providerConfigured,
            modelConfigured: modelConfig.modelConfigured,
            baseUrlConfigured: modelConfig.baseUrlConfigured,
            apiKeyConfigured: modelConfig.apiKeyConfigured,
            apiKeySource: modelConfig.apiKeySource
          },
          server: {
            host: config.host,
            port: config.port,
            maxRequestBytes: config.maxRequestBytes,
            corsWhitelistConfigured: config.corsOrigins.length > 0
          },
          runtime
        }, cors);
        return;
      }
      if (req.method === "POST" && req.url === "/v1/orchestrate") {
        if (!/^application\/json\b/i.test(req.headers["content-type"] || "")) {
          throw new HttpError(415, "unsupported_media_type", "Content-Type must be application/json");
        }
        const rawBody = await readJsonBody(req, config.maxRequestBytes);
        const body = validateOrchestrateRequest(rawBody);
        let result;
        try {
          result = await orchestrateFn(body);
        } catch (error) {
          throw new HttpError(502, "orchestration_failed", error instanceof Error ? error.message : String(error));
        }
        await writeAudit(config, {
          type: "orchestrate",
          requestId,
          sessionId: result.session_id,
          ok: true,
          status: 200,
          durationMs: Math.round(performance.now() - started),
          remote: req.socket.remoteAddress,
          body
        });
        sendJson(res, 200, result, cors);
        return;
      }
      throw new HttpError(404, "not_found", "Route not found");
    } catch (error) {
      const { status, body } = errorBody(error, requestId);
      await writeAudit(config, {
        type: "error",
        requestId,
        sessionId: undefined,
        ok: false,
        status,
        durationMs: Math.round(performance.now() - started),
        remote: req.socket.remoteAddress,
        error: body.error
      });
      sendJson(res, status, body, cors ?? {});
    }
  });
}

export async function start() {
  const config = loadConfig();
  const orchestrator = new Orchestrator(config);
  const server = createHttpServer(config, (body) => orchestrator.orchestrate(body));
  server.listen(config.port, config.host, () => {
    const address = server.address();
    console.log(JSON.stringify({ event: "pi_bridge_listening", address }));
  });
  return server;
}

if (fileURLToPath(import.meta.url) === process.argv[1]) {
  start().catch((error) => {
    console.error(JSON.stringify({ event: "pi_bridge_start_failed", error: error instanceof Error ? error.message : String(error) }));
    process.exitCode = 1;
  });
}
