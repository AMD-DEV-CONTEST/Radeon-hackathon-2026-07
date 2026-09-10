import { mkdir, readFile, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { createAgentSession, DefaultResourceLoader, ModelRuntime, SessionManager, SettingsManager } from "@earendil-works/pi-coding-agent";

export const ROLE_NAMES = ["envdoctor", "deployplanner", "benchmarkrunner", "optimanalyst", "opscommander"];

export class SessionPool {
  constructor(config) {
    this.config = config;
    this.records = new Map();
    this.runtimePromise = undefined;
  }

  cleanup(now = Date.now()) {
    for (const [id, record] of this.records) {
      if (now - record.lastUsed > this.config.sessionTtlMs) this.delete(id);
    }
    while (this.records.size > this.config.maxSessions) {
      const oldest = [...this.records.entries()].sort((a, b) => a[1].lastUsed - b[1].lastUsed)[0];
      if (!oldest) break;
      this.delete(oldest[0]);
    }
  }

  delete(id) {
    const record = this.records.get(id);
    if (!record) return;
    for (const session of Object.values(record.sessions)) session?.dispose?.();
    this.records.delete(id);
  }

  async getRuntime() {
    if (!this.runtimePromise) {
      this.runtimePromise = (async () => {
        await mkdir(this.config.agentDir, { recursive: true });
        process.env.VLLM_BASE_URL ||= this.config.vllmBaseUrl;
        process.env.PI_API_KEY ||= this.config.apiKey;
        // The SDK does not expand $ENV placeholders in models.json, so write a
        // resolved copy with the literal loopback baseUrl before loading it.
        const modelsPath = await this.writeResolvedModels();
        const runtime = await ModelRuntime.create({
          authPath: resolve(this.config.agentDir, "auth.json"),
          modelsPath,
          modelsStorePath: resolve(this.config.agentDir, "models-store.json"),
          allowModelNetwork: false
        });
        if (this.config.apiKey) await runtime.setRuntimeApiKey(this.config.providerId, this.config.apiKey, { allowNetwork: false });
        return runtime;
      })();
    }
    return this.runtimePromise;
  }

  async writeResolvedModels() {
    const resolvedPath = resolve(this.config.agentDir, "models-resolved.json");
    const raw = JSON.parse(await readFile(this.config.modelsPath, "utf8"));
    const provider = raw.providers?.[this.config.providerId];
    if (provider) {
      provider.baseUrl = this.config.vllmBaseUrl;
      if (typeof provider.apiKey === "string" && provider.apiKey.startsWith("$")) {
        provider.apiKey = this.config.apiKey;
      }
    }
    await writeFile(resolvedPath, JSON.stringify(raw, null, 2), "utf8");
    return resolvedPath;
  }

  async createPiSession(name, systemPrompt) {
    const runtime = await this.getRuntime();
    const model = runtime.getModel(this.config.providerId, this.config.modelId);
    if (!model) {
      throw new Error(`Configured model not found: ${this.config.providerId}/${this.config.modelId}`);
    }
    const settingsManager = SettingsManager.create(process.cwd(), this.config.agentDir);
    const resourceLoader = new DefaultResourceLoader({
      cwd: process.cwd(),
      agentDir: this.config.agentDir,
      settingsManager,
      noExtensions: true,
      noSkills: true,
      noPromptTemplates: true,
      noThemes: true,
      noContextFiles: true,
      systemPrompt
    });
    await resourceLoader.reload();
    const { session } = await createAgentSession({
      cwd: process.cwd(),
      agentDir: this.config.agentDir,
      modelRuntime: runtime,
      model,
      thinkingLevel: "off",
      noTools: "all",
      resourceLoader,
      settingsManager,
      sessionManager: SessionManager.inMemory(process.cwd(), { id: `${name}-${Date.now()}` })
    });
    session.setSessionName(name);
    return session;
  }

  async get(sessionId, systemPrompts) {
    this.cleanup();
    let record = this.records.get(sessionId);
    if (!record) {
      const sessions = {};
      for (const roleName of ROLE_NAMES) {
        sessions[roleName] = await this.createPiSession(roleName, systemPrompts[roleName]);
      }
      record = { sessions, createdAt: Date.now(), lastUsed: Date.now() };
      this.records.set(sessionId, record);
      this.cleanup();
    }
    record.lastUsed = Date.now();
    return record.sessions;
  }
}
