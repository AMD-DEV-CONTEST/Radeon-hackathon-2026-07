// OpenAI-compatible AI service for the Radeon hackathon: use Radeon Cloud
// during development, then switch the same endpoints to local Ollama/vLLM.
import { createServer } from "node:http";
import { createReadStream } from "node:fs";
import { readFile, stat } from "node:fs/promises";
import { extname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const port = Number(process.env.PORT || 8790);
const baseUrl = (process.env.OLLAMA_BASE_URL || "http://127.0.0.1:11434/v1").replace(/\/$/, "");
const model = process.env.LOCAL_MODEL || "qwen3:8b";
const apiKey = process.env.LLM_API_KEY || "";
const upstreamTimeoutMs = Number(process.env.LLM_TIMEOUT_MS || 120_000);
const maxTokens = Number(process.env.LLM_MAX_TOKENS || 2048);
const maxAgentSteps = Number(process.env.LLM_MAX_AGENT_STEPS || 12);
const modelHost = new URL(baseUrl).hostname;
const isLocalModelRuntime = !apiKey && ["127.0.0.1", "localhost", "::1"].includes(modelHost);
const rootDir = fileURLToPath(new URL(".", import.meta.url));
// Personal material library (indexed by local-library/catalog.json). Defaults
// to the learner's iCloud folder; override with LIBRARY_ROOT.
const libraryRoot = resolve(process.env.LIBRARY_ROOT || join(process.env.HOME || "", "Library/Mobile Documents/com~apple~CloudDocs/雅思/雅思全套资料"));

const libraryTypes = {
  ".pdf": "application/pdf",
  ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
  ".txt": "text/plain; charset=utf-8",
  ".md": "text/plain; charset=utf-8",
  ".mp3": "audio/mpeg",
  ".m4a": "audio/mp4",
  ".wav": "audio/wav",
  ".mp4": "video/mp4",
  ".mov": "video/quicktime",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
};

async function serveLibrary(pathname, request, response) {
  let decoded;
  try {
    decoded = decodeURIComponent(pathname.slice("/library/".length));
  } catch {
    return send(request, response, 400, { error: "bad path" });
  }
  const targetPath = resolve(libraryRoot, decoded);
  if (!targetPath.startsWith(libraryRoot)) return send(request, response, 403, { error: "forbidden" });
  const type = libraryTypes[extname(targetPath).toLowerCase()];
  if (!type) return send(request, response, 404, { error: "not found" });
  let stats;
  try {
    stats = await stat(targetPath);
    if (stats.isDirectory()) return send(request, response, 404, { error: "not found" });
  } catch {
    return send(request, response, 404, { error: "not found" });
  }
  const headers = { "Content-Type": type, "Accept-Ranges": "bytes", "Access-Control-Allow-Origin": "*" };
  // Range support keeps audio/video playback and PDF viewers happy.
  const range = /^bytes=(\d+)-(\d*)$/.exec(request.headers.range || "");
  if (range) {
    const start = Number(range[1]);
    const end = range[2] ? Math.min(Number(range[2]), stats.size - 1) : stats.size - 1;
    if (start >= stats.size || start > end) {
      response.writeHead(416, { ...headers, "Content-Range": `bytes */${stats.size}` });
      return response.end();
    }
    response.writeHead(206, { ...headers, "Content-Range": `bytes ${start}-${end}/${stats.size}`, "Content-Length": end - start + 1 });
    return createReadStream(targetPath, { start, end }).pipe(response);
  }
  response.writeHead(200, { ...headers, "Content-Length": stats.size });
  return createReadStream(targetPath).pipe(response);
}

const staticTypes = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".webmanifest": "application/manifest+json",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".svg": "image/svg+xml",
  ".ico": "image/x-icon",
  ".mp3": "audio/mpeg",
  ".m4a": "audio/mp4",
  ".mp4": "video/mp4",
  ".ttf": "font/ttf",
  ".woff2": "font/woff2",
};

async function serveStatic(pathname, request, response) {
  let decoded;
  try {
    decoded = decodeURIComponent(pathname);
  } catch {
    return send(request, response, 400, { error: "bad path" });
  }
  const rel = decoded === "/" ? "index.html" : decoded === "/demo" ? "agent-demo.html" : decoded.replace(/^\/+/, "");
  const targetPath = resolve(rootDir, rel);
  if (!targetPath.startsWith(rootDir)) return send(request, response, 403, { error: "forbidden" });
  const type = staticTypes[extname(targetPath)] || null;
  if (!type) return send(request, response, 404, { error: "not found" });
  try {
    if ((await stat(targetPath)).isDirectory()) return send(request, response, 404, { error: "not found" });
    const body = await readFile(targetPath);
    response.writeHead(200, { "Content-Type": type, "Cache-Control": "no-store", "Access-Control-Allow-Origin": "*" });
    return response.end(body);
  } catch {
    return send(request, response, 404, { error: "not found" });
  }
}
// Reasoning models (Qwen3.x) burn the token budget on hidden thinking; the
// Radeon gateway kills requests that run past ~120s, so short answers need it off.
const disableThinking = process.env.LLM_DISABLE_THINKING === "1";

const tasks = {
  listening_review: "You are a private IELTS listening coach. Use only the supplied objective score, mistakes, evidence and learnerContext. Report only the supplied x/y result: never output a Band estimate, percentage, or any other score. For each mistake, describe only the literal mismatch between userAnswer, correctAnswer and evidence. Never propose hypothetical distractors or infer noise, attention, memory, pronunciation, what the learner heard, or questions and dates not included in the payload. If a cause is not evidenced, say it is unknown. Reply in concise Chinese Markdown with exactly: 本次结果, 错因诊断, 关键证据, 建议答案策略, 下一轮训练. Compare with prior moduleReviews only when evidence exists and give one concrete 5-minute drill.",
  reading_review: "You are a private IELTS reading coach. Use only the supplied answers, hint usage, passage summary, evidence and learnerContext. Report only the supplied correct/total, independentCorrect/total and hintCount: never output a Band estimate or invent missing questions or source text. If a cause is not evidenced, say it is unknown. Reply in concise Chinese Markdown with exactly: 本次结果, 错因诊断, 定位证据, 建议解题路径, 下一轮训练. Distinguish independent answers from answers completed with hints and give one concrete 5-minute drill.",
  writing_feedback: "You are a strict but encouraging IELTS writing teacher. Use learnerContext when available to connect this essay to the learner's recent weaknesses. Give concise feedback in Chinese with estimated TR, CC, LR and GRA bands, three highest-impact corrections, one improved example sentence, and one next practice task. Do not claim an official score.",
  speaking_coach: "You are an IELTS speaking examiner. Reply in English with one brief correction, one more natural phrase, and exactly one follow-up question. Keep the response under 90 words.",
  speaking_dialogue: "You are a warm IELTS speaking partner in a live voice conversation. Use learnerContext to avoid repeating mastered advice and to revisit a relevant recurring weakness. Reply in natural spoken English: react briefly to what the candidate said, model one improved phrase when useful, then ask exactly one follow-up question. Keep the reply under 45 words so it can be spoken aloud. No lists, no markdown, no labels.",
  speaking_debrief: "You are an expert IELTS speaking coach. Review only the supplied conversation, sessionMeta and learnerContext; never invent pronunciation, pause, or official band evidence that a transcript cannot show. Prioritize specificity, coherence and natural B1-B2 spoken English before advanced vocabulary. Never recommend memorized connectors, rare synonyms, or essay phrases such as 'primarily because', 'due to the fact that', and 'not only...but also'. Reply in concise Chinese Markdown with exactly five sections: 对话摘要 (two sentences), 能力评估 (Fluency & Coherence based only on idea development/cohesion, Lexical Resource, Grammar; label each 稳定/发展中/优先改进 with one piece of evidence; explicitly state Pronunciation 未评估 because only transcript is available), 本轮证据 (quote two short phrases), 更自然的示范答案 (English, 50-70 words, preserving the candidate's meaning), 下一轮训练 (one concrete 5-minute drill). Compare with prior learner memory when evidence exists; otherwise say this is the baseline.",
  news_feedback: "You are an IELTS reading teacher. Evaluate the learner summary for factual coverage, vocabulary, and grammar. Reply in concise Chinese and include one improved English summary.",
};

async function loadJson(path, fallback) {
  try {
    return JSON.parse(await readFile(new URL(path, import.meta.url), "utf8"));
  } catch {
    return fallback;
  }
}

const wordbook = await loadJson("./data/wordbook.json", { book: {}, dailyQueue: [], words: [] });
const synonyms = await loadJson("./data/synonyms.json", { groups: [] });
const wrongQuestions = await loadJson("./data/wrong-questions.json", { items: [], notes: [] });
const catalog = await loadJson("./local-library/catalog.json", { items: [] });

function send(request, response, status, body, type = "application/json; charset=utf-8") {
  response.writeHead(status, { "Content-Type": type, "Cache-Control": "no-store", "Access-Control-Allow-Origin": "*" });
  response.end(type.startsWith("application/json") ? JSON.stringify(body) : body);
}

async function chat(messages, extra = {}) {
  // The shared Radeon gateway flakes under load ("Model gateway is
  // unavailable"), so retry transient failures once before giving up.
  let lastError;
  for (let attempt = 0; attempt < 2; attempt += 1) {
    if (attempt) await new Promise((resolve) => setTimeout(resolve, 3000));
    try {
      const upstream = await fetch(`${baseUrl}/chat/completions`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(apiKey ? { Authorization: `Bearer ${apiKey}` } : {}) },
        body: JSON.stringify({
          model,
          messages,
          max_tokens: maxTokens,
          ...(disableThinking ? { chat_template_kwargs: { enable_thinking: false } } : {}),
          ...extra,
        }),
        signal: AbortSignal.timeout?.(upstreamTimeoutMs),
      });
      const data = await upstream.json().catch(() => ({}));
      if (upstream.ok) return data.choices?.[0]?.message || {};
      const message = data.error?.message || data.detail || `upstream ${upstream.status}`;
      if (upstream.status >= 400 && upstream.status < 500) throw new Error(message);
      lastError = new Error(message);
    } catch (error) {
      if (/upstream 4|Invalid|Unauthorized/i.test(error.message)) throw error;
      lastError = error;
    }
  }
  throw lastError;
}

const toolDefs = [
  { name: "lookup_word", description: "Look up an IELTS vocabulary word in the learner's local 8000-word book. Returns definition, phonetic, examples and the learner's memory state.", parameters: { type: "object", properties: { word: { type: "string" } }, required: ["word"] } },
  { name: "find_synonyms", description: "Find IELTS reading paraphrase/synonym groups containing a word, from the local 99-group synonym list.", parameters: { type: "object", properties: { word: { type: "string" } }, required: ["word"] } },
  { name: "search_library", description: "Search the learner's local IELTS material library (1200 files: PDFs, audio, video) by keyword in the file name or path.", parameters: { type: "object", properties: { query: { type: "string" } }, required: ["query"] } },
  { name: "get_study_status", description: "Get the learner's current study status: words learned, today's new/review queue, and recent mistake notes.", parameters: { type: "object", properties: {} } },
  { name: "get_learning_memory", description: "Read the learner's live long-term learning memory: target, recent weak modules, four-skill AI reviews, speaking sessions and recent mistakes.", parameters: { type: "object", properties: {} } },
];

const toolImpls = {
  lookup_word({ word }) {
    const entry = wordbook.words.find((item) => item.word.toLowerCase() === String(word).toLowerCase());
    if (!entry) return { found: false, word };
    const { word: w, phonetic, definition, status, memoryState, example, exampleZh } = entry;
    return { found: true, word: w, phonetic, definition, status, memoryState, example, exampleZh };
  },
  find_synonyms({ word }) {
    const needle = String(word).toLowerCase();
    const hits = synonyms.groups.filter((group) => group.terms.some((term) => term.toLowerCase() === needle)).slice(0, 2);
    return { found: hits.length > 0, groups: hits.map((group) => group.raw) };
  },
  // ponytail: naive substring search over 1200 catalog entries; swap in embedding
  // retrieval (bge-m3 via Ollama) only if demo questions get fuzzier than keywords.
  search_library({ query }) {
    const needle = String(query).toLowerCase();
    const hits = catalog.items.filter((item) => `${item.path}`.toLowerCase().includes(needle)).slice(0, 5);
    return { found: hits.length > 0, files: hits.map((item) => ({ path: item.path, kind: item.kind })) };
  },
  get_study_status() {
    return {
      book: wordbook.book,
      todayQueue: wordbook.dailyQueue,
      mistakeNotes: wrongQuestions.notes.map((note) => ({ title: note.title, type: note.type })),
    };
  },
};

const agentSystem = `You are the learner's private IELTS study agent across Listening, Reading, Writing and Speaking. All tools read local data only; never invent learner records. Use tools whenever the answer depends on the learner's words, synonyms, materials, study status or long-term memory. Use get_learning_memory for personalized plans, progress questions and advice that should carry across sessions. For cross-skill plans, prioritize recent moduleReviews and mistakes, explain why each task was chosen, and avoid assigning work to every skill when the evidence supports a narrower plan. Call find_synonyms only when the user explicitly asks about synonyms or paraphrases. When building a study plan, call get_study_status and get_learning_memory, then look up at most 4 words you will actually cite. When several lookups are independent, call them together in one turn. Answer concisely in Chinese, cite the evidence you found, and end with one concrete next action.`;

async function runAgent(message, context = {}) {
  const trace = [];
  const messages = [{ role: "system", content: agentSystem }, { role: "user", content: message }];
  const tools = toolDefs.map(({ name, description, parameters }) => ({ type: "function", function: { name, description, parameters } }));
  for (let step = 0; step < maxAgentSteps; step += 1) {
    const reply = await chat(messages, { tools });
    const calls = reply.tool_calls || [];
    if (!calls.length) return { text: (reply.content || "").trim(), trace };
    messages.push({ role: "assistant", content: reply.content || "", tool_calls: calls });
    for (const call of calls) {
      const name = call.function?.name;
      let args = {};
      try { args = JSON.parse(call.function?.arguments || "{}"); } catch { /* keep {} */ }
      const impl = toolImpls[name];
      const result = name === "get_learning_memory" ? context : impl ? impl(args) : { error: `unknown tool ${name}` };
      trace.push({ tool: name, args, result });
      messages.push({ role: "tool", tool_call_id: call.id, content: JSON.stringify(result) });
    }
  }
  return { text: "", trace, error: "agent exceeded step limit" };
}

async function readJsonBody(request) {
  let text = "";
  for await (const chunk of request) {
    text += chunk;
    if (text.length > 64_000) throw new Error("request too large");
  }
  return JSON.parse(text || "{}");
}

createServer(async (request, response) => {
  const url = new URL(request.url, "http://localhost");
  if (request.method === "OPTIONS") return send(request, response, 204, {});
  if (request.method === "GET" && url.pathname.startsWith("/library/")) return serveLibrary(url.pathname, request, response);
  if (request.method === "GET" && url.pathname === "/api/health") {
    try {
      if (isLocalModelRuntime) {
        const upstream = await fetch(`${baseUrl}/models`, { signal: AbortSignal.timeout?.(10_000) });
        const data = await upstream.json().catch(() => ({}));
        const models = (data.data || []).map((item) => item.id);
        if (!upstream.ok || !models.length) return send(request, response, 502, { ok: false, error: "model runtime is unavailable" });
        return send(request, response, 200, { ok: true, provider: "Ollama (local)", model, modelReady: models.includes(model), models });
      }
      await chat([{ role: "user", content: "Reply only with OK" }], { max_tokens: 1 });
      return send(request, response, 200, { ok: true, provider: new URL(baseUrl).host, model, modelReady: true });
    } catch {
      return send(request, response, 502, { ok: false, error: "model runtime is unavailable" });
    }
  }
  if (request.method === "GET") return serveStatic(url.pathname, request, response);
  if (request.method !== "POST" || !["/api/ai", "/api/agent"].includes(url.pathname)) return send(request, response, 404, { error: "not found" });
  let body;
  try {
    body = await readJsonBody(request);
  } catch (error) {
    return send(request, response, error.message === "request too large" ? 413 : 400, { error: error.message });
  }
  try {
    if (url.pathname === "/api/ai") {
      const { task, payload } = body;
      if (!tasks[task] || !payload || typeof payload !== "object") return send(request, response, 400, { error: "invalid task" });
      const reply = await chat([{ role: "system", content: tasks[task] }, { role: "user", content: JSON.stringify(payload) }]);
      const text = (reply.content || "").trim();
      if (!text) return send(request, response, 502, { error: "model returned an empty response" });
      return send(request, response, 200, { text });
    }
    const { message, context = {} } = body;
    if (typeof message !== "string" || !message.trim()) return send(request, response, 400, { error: "message required" });
    if (!context || typeof context !== "object" || Array.isArray(context)) return send(request, response, 400, { error: "invalid context" });
    const result = await runAgent(message.trim(), context);
    if (result.error) return send(request, response, 502, { error: result.error, trace: result.trace });
    return send(request, response, 200, result);
  } catch (error) {
    return send(request, response, 502, { error: "model request failed", detail: error.message });
  }
}).listen(port, () => console.log(`IELTS OS local agent listening on http://127.0.0.1:${port} (model: ${model})`));
