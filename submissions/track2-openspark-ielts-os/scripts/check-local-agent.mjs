// Self-check for local-agent-server.mjs: stubs the Ollama upstream and
// verifies /api/health, /api/ai, and one full tool-calling round trip.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { createServer } from "node:http";
import { mkdtemp, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../", import.meta.url));
const libraryRoot = await mkdtemp(join(tmpdir(), "ielts-library-"));
await writeFile(join(libraryRoot, "sample.pdf"), "%PDF-1.4 fake-pdf-body-for-range-tests");

async function listen(server) {
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  return server.address().port;
}

async function freePort() {
  const server = createServer();
  const port = await listen(server);
  await new Promise((resolve) => server.close(resolve));
  return port;
}

function startApi(port, ollamaPort, { basePath = "/v1", apiKey = "", disableThinking = false, libraryRoot = "" } = {}) {
  const child = spawn(process.execPath, ["local-agent-server.mjs"], {
    cwd: root,
    env: {
      ...process.env,
      PORT: String(port),
      OLLAMA_BASE_URL: `http://127.0.0.1:${ollamaPort}${basePath}`,
      LOCAL_MODEL: "test-model",
      LLM_API_KEY: apiKey,
      LLM_DISABLE_THINKING: disableThinking ? "1" : "",
      LIBRARY_ROOT: libraryRoot,
    },
    stdio: ["ignore", "pipe", "pipe"],
  });
  return new Promise((resolve, reject) => {
    let output = "";
    const timeout = setTimeout(() => reject(new Error(`server did not start: ${output}`)), 8000);
    const read = (chunk) => {
      output += chunk;
      if (output.includes("IELTS OS local agent listening")) { clearTimeout(timeout); resolve(child); }
    };
    child.stdout.on("data", read);
    child.stderr.on("data", read);
    child.on("exit", (code) => { clearTimeout(timeout); reject(new Error(`server exited ${code}: ${output}`)); });
  });
}

let agentRounds = 0;
let cloudHealthProbes = 0;
const ollama = createServer(async (request, response) => {
  let text = "";
  for await (const chunk of request) text += chunk;
  if (request.url === "/v1/models") return response.end(JSON.stringify({ data: [{ id: "test-model" }] }));
  if (request.url === "/cloud/v1/models") {
    response.writeHead(404, { "Content-Type": "application/json" });
    return response.end(JSON.stringify({ error: "not found" }));
  }
  if (["/v1/chat/completions", "/cloud/v1/chat/completions"].includes(request.url)) {
    const body = JSON.parse(text);
    if (request.url.startsWith("/cloud/")) {
      assert.equal(request.headers.authorization, "Bearer test-key");
      assert.equal(body.max_tokens, 1);
      assert.deepEqual(body.chat_template_kwargs, { enable_thinking: false });
      cloudHealthProbes += 1;
      response.writeHead(200, { "Content-Type": "application/json" });
      return response.end(JSON.stringify({ choices: [{ message: { role: "assistant", content: "OK" } }] }));
    }
    response.writeHead(200, { "Content-Type": "application/json" });
    if (body.tools) agentRounds += 1;
    const userMessage = body.messages?.find((message) => message.role === "user")?.content || "";
    if (body.tools && userMessage.includes("memory-check")) {
      const toolMsg = body.messages.findLast((message) => message.role === "tool");
      if (!toolMsg) return response.end(JSON.stringify({ choices: [{ message: { role: "assistant", content: "", tool_calls: [{ id: "call_memory", type: "function", function: { name: "get_learning_memory", arguments: "{}" } }] } }] }));
      assert.match(toolMsg.content, /Speaking/);
      return response.end(JSON.stringify({ choices: [{ message: { role: "assistant", content: "你最近需要优先练习口语连贯性。" } }] }));
    }
    if (body.tools && agentRounds === 1) {
      // First agent round: demand a word lookup for "approach".
      return response.end(JSON.stringify({ choices: [{ message: { role: "assistant", content: "", tool_calls: [{ id: "call_1", type: "function", function: { name: "lookup_word", arguments: JSON.stringify({ word: "approach" }) } }] } }] }));
    }
    if (body.tools) {
      const toolMsg = body.messages.findLast((m) => m.role === "tool");
      assert.ok(toolMsg, "tool result must be fed back to the model");
      assert.match(toolMsg.content, /approach/);
      return response.end(JSON.stringify({ choices: [{ message: { role: "assistant", content: "approach 在你的词书里，意思是方法。" } }] }));
    }
    return response.end(JSON.stringify({ choices: [{ message: { role: "assistant", content: "mock feedback text" } }] }));
  }
  response.writeHead(404).end();
});

const ollamaPort = await listen(ollama);
const port = await freePort();
const api = await startApi(port, ollamaPort, { libraryRoot });
const cloudPort = await freePort();
const cloudApi = await startApi(cloudPort, ollamaPort, { basePath: "/cloud/v1", apiKey: "test-key", disableThinking: true });
const endpoint = `http://127.0.0.1:${port}`;
const cloudEndpoint = `http://127.0.0.1:${cloudPort}`;

try {
  const cloudHealthResponse = await fetch(`${cloudEndpoint}/api/health`);
  const cloudHealth = await cloudHealthResponse.json();
  assert.equal(cloudHealthResponse.status, 200);
  assert.deepEqual(
    { ok: cloudHealth.ok, provider: cloudHealth.provider, model: cloudHealth.model, modelReady: cloudHealth.modelReady },
    { ok: true, provider: `127.0.0.1:${ollamaPort}`, model: "test-model", modelReady: true },
  );
  assert.equal(cloudHealthProbes, 1, "cloud health must use a minimal chat probe");

  const health = await fetch(`${endpoint}/api/health`).then((r) => r.json());
  assert.deepEqual({ ok: health.ok, provider: health.provider, model: health.model, modelReady: health.modelReady }, { ok: true, provider: "Ollama (local)", model: "test-model", modelReady: true });

  const page = await fetch(`${endpoint}/`);
  assert.equal(page.status, 200);
  assert.match(await page.text(), /IELTS OS Mobile Demo/, "root must serve the main app");

  const demo = await fetch(`${endpoint}/demo`);
  assert.equal(demo.status, 200);
  assert.match(await demo.text(), /IELTS Private Agent/, "/demo must serve the agent demo page");

  const appJs = await fetch(`${endpoint}/app.js`);
  assert.equal(appJs.status, 200, "static assets must be served");

  const traversal = await fetch(`${endpoint}/..%2f..%2fetc%2fpasswd`);
  assert.notEqual(traversal.status, 200, "path traversal must be blocked");

  const file = await fetch(`${endpoint}/library/sample.pdf`);
  assert.equal(file.status, 200, "library files must stream");
  assert.equal(file.headers.get("content-type"), "application/pdf");
  assert.equal(await file.text(), "%PDF-1.4 fake-pdf-body-for-range-tests");

  const partial = await fetch(`${endpoint}/library/sample.pdf`, { headers: { Range: "bytes=5-9" } });
  assert.equal(partial.status, 206, "range requests must be honored");
  assert.equal(await partial.text(), "1.4 f");

  const escapeAttempt = await fetch(`${endpoint}/library/..%2f..%2fpackage.json`);
  assert.notEqual(escapeAttempt.status, 200, "library path traversal must be blocked");

  const feedback = await fetch(`${endpoint}/api/ai`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ task: "writing_feedback", payload: { essay: "test" } }),
  }).then((r) => r.json());
  assert.equal(feedback.text, "mock feedback text");

  for (const task of ["listening_review", "reading_review"]) {
    const review = await fetch(`${endpoint}/api/ai`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ task, payload: { result: { correct: 1, total: 2 } } }),
    }).then((r) => r.json());
    assert.equal(review.text, "mock feedback text");
  }

  const agent = await fetch(`${endpoint}/api/agent`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message: "approach 这个词我背过吗？" }),
  }).then((r) => r.json());
  assert.equal(agent.trace.length, 1);
  assert.equal(agent.trace[0].tool, "lookup_word");
  assert.equal(agent.trace[0].result.found, true, "approach must be found in the real wordbook");
  assert.match(agent.text, /approach/);

  const memoryAgent = await fetch(`${endpoint}/api/agent`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message: "memory-check", context: { progress: { weakModules: [{ module: "Speaking", count: 3 }] } } }),
  }).then((r) => r.json());
  assert.equal(memoryAgent.trace[0].tool, "get_learning_memory");
  assert.equal(memoryAgent.trace[0].result.progress.weakModules[0].module, "Speaking");

  const debrief = await fetch(`${endpoint}/api/ai`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ task: "speaking_debrief", payload: { conversation: [{ role: "user", text: "I like my city." }] } }),
  }).then((r) => r.json());
  assert.equal(debrief.text, "mock feedback text");
  const serverSource = await readFile(join(root, "local-agent-server.mjs"), "utf8");
  assert.match(serverSource, /Pronunciation 未评估/);
  assert.match(serverSource, /listening_review:/);
  assert.match(serverSource, /reading_review:/);

  console.log("local agent server checks passed (health, static app + demo page, /api/ai, tool-calling loop).");
} finally {
  api.kill("SIGTERM");
  cloudApi.kill("SIGTERM");
  await new Promise((resolve) => ollama.close(resolve));
}
