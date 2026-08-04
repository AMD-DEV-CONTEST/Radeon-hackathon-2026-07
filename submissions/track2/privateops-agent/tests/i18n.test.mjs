import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import test from "node:test";

const modulePath = new URL("../web/i18n.js", import.meta.url);
assert.ok(existsSync(modulePath), "web/i18n.js must provide the bilingual runtime");
await import(modulePath);

const i18n = globalThis.PrivateOpsI18n;

test("defaults invalid or unavailable stored language to English", () => {
  assert.equal(i18n.readLanguage({ getItem: () => null }), "en");
  assert.equal(i18n.readLanguage({ getItem: () => "fr" }), "en");
  assert.equal(i18n.readLanguage({ getItem: () => { throw new Error("blocked"); } }), "en");
});

test("persists only a normalized supported language", () => {
  const writes = [];
  const storage = { setItem: (key, value) => writes.push([key, value]) };

  assert.equal(i18n.writeLanguage(storage, "zh-CN"), "zh-CN");
  assert.equal(i18n.writeLanguage(storage, "invalid"), "en");
  assert.deepEqual(writes, [
    ["privateops.language", "zh-CN"],
    ["privateops.language", "en"],
  ]);
});

test("normalizes the interface language for Agent response requests", () => {
  assert.equal(i18n.responseLanguage("en"), "en");
  assert.equal(i18n.responseLanguage("zh-CN"), "zh-CN");
  assert.equal(i18n.responseLanguage("fr"), "en");
});

test("returns a demo prompt in the selected interface language", () => {
  assert.equal(
    i18n.demoPrompt("en"),
    "Audit this project for hackathon submission readiness and run the safe checks.",
  );
  assert.equal(
    i18n.demoPrompt("zh-CN"),
    "审计本项目的黑客松提交准备情况，并运行安全检查。",
  );
});

test("translates with interpolation and falls back without blank copy", () => {
  assert.equal(i18n.translate("zh-CN", "language.switch"), "EN");
  assert.equal(i18n.translate("en", "comparison.latency", { value: 2.5 }), "2.5× lower latency");
  assert.equal(i18n.translate("zh-CN", "missing.key"), "missing.key");
});

test("both catalogs cover the first-render language controls and service status", () => {
  for (const language of ["en", "zh-CN"]) {
    for (const key of ["document.title", "language.switch", "language.aria", "health.online", "health.offline", "mode.amd-cloud-api"]) {
      assert.equal(typeof i18n.catalogs[language][key], "string", `${language} is missing ${key}`);
      assert.ok(i18n.catalogs[language][key].length > 0, `${language} has blank ${key}`);
    }
  }
});

test("both catalogs cover dynamic Agent, permission, audit, and benchmark copy", () => {
  const required = [
    "request.loading", "request.completed", "request.profileSaved", "request.benchmarkRecorded",
    "permission.safe", "permission.confirm", "permission.blocked", "permission.reason.safe",
    "permission.reason.confirm", "permission.reason.blocked", "evidence.noMatch", "plan.empty",
    "plan.retrieve", "plan.inspect", "plan.synthesize", "plan.pending", "plan.status.completed",
    "tools.empty", "audit.empty", "benchmark.empty", "comparison.label", "comparison.latency",
    "comparison.throughput", "runtime.framework", "runtime.inference", "runtime.location",
    "runtime.provider", "runtime.documents", "runtime.boundary", "tool.name.workspace_inventory",
    "tool.name.submission_readiness", "units.milliseconds", "units.tokensPerSecond",
    "plan.status.attention", "plan.status.failed", "plan.status.unsupported",
    "tool.name.startup_inventory", "tool.name.process_inventory", "tool.name.service_inventory",
    "tool.name.scheduled_task_inventory", "tool.name.system_overview",
    "tool.name.network_listener_inventory", "tool.name.security_status",
    "theme.switchLight", "theme.switchDark", "theme.ariaLight", "theme.ariaDark",
    "api.open", "api.aria", "api.title", "api.mode", "api.remote", "api.local",
    "api.endpoint", "api.model", "api.key", "api.keyRequired", "api.keyOptional",
    "api.showKey", "api.hideKey", "api.remember", "api.rememberHint", "api.test",
    "api.apply", "api.testing", "api.testSuccess", "api.applying", "api.applySuccess",
    "api.validationRemote", "api.validationLocal", "api.failure", "evidence.toolsTitle", "evidence.toolsDetail",
    "answer.apiRequired",
    "evidence.general", "evidence.itemCount", "evidence.truncated", "audit.delete",
    "audit.deleteAria", "audit.deleteConfirm", "audit.deleteSuccess", "audit.deleteFailure",
    "performance.proof.verified", "performance.proof.unavailable", "performance.proof.captured",
    "performance.proof.instance", "performance.proof.gpu", "performance.proof.architecture",
    "performance.proof.rocm", "performance.proof.model", "performance.proof.location",
    "performance.proof.modelLatency", "performance.proof.throughput", "performance.proof.tokens",
    "performance.proof.agentLatency", "performance.proof.vram", "performance.proof.pytorch",
    "performance.proof.hip", "performance.proof.vllm", "performance.proof.provider",
    "performance.proof.endpoint", "performance.proof.sources", "performance.proof.sourceJson",
    "performance.proof.boundary", "performance.retest.title", "performance.retest.help",
  ];
  for (const language of ["en", "zh-CN"]) {
    for (const key of required) {
      assert.equal(typeof i18n.catalogs[language][key], "string", `${language} is missing ${key}`);
    }
  }
});

test("provider mode copy distinguishes remote credentials from keyless local ROCm", () => {
  assert.equal(i18n.translate("en", "api.local"), "Local ROCm");
  assert.equal(i18n.translate("zh-CN", "api.local"), "本地 ROCm");
  assert.match(i18n.translate("en", "api.keyOptional"), /optional/i);
  assert.match(i18n.translate("zh-CN", "api.keyOptional"), /可选/);
});

test("system inspection tools have truthful bilingual names", () => {
  assert.equal(i18n.translate("en", "tool.name.startup_inventory"), "Startup applications");
  assert.equal(i18n.translate("zh-CN", "tool.name.startup_inventory"), "开机自启项");
});

test("unsupported system checks have bilingual status", () => {
  assert.equal(i18n.translate("en", "plan.status.unsupported"), "unsupported");
  assert.equal(i18n.translate("zh-CN", "plan.status.unsupported"), "不支持");
});

test("known server copy is localized while unknown evidence stays verbatim", () => {
  assert.equal(
    i18n.translateKnown("zh-CN", "Read-only or planning request; no external side effects detected."),
    "只读或规划类请求；未检测到外部副作用。",
  );
  assert.equal(i18n.translateKnown("zh-CN", "Retrieved 3 evidence items."), "已检索 3 条证据。")
  assert.equal(i18n.translateKnown("zh-CN", "AMD Cloud shared API"), "AMD 云共享 API");
  assert.equal(
    i18n.translateKnown("zh-CN", "Audit this project for hackathon submission readiness and run the safe checks."),
    "审计本项目的黑客松提交准备情况，并运行安全检查。",
  );
  assert.equal(
    i18n.translateKnown("en", "审计本项目的黑客松提交准备情况，并运行安全检查。"),
    "Audit this project for hackathon submission readiness and run the safe checks.",
  );
  assert.equal(i18n.translateKnown("zh-CN", "private evidence excerpt"), "private evidence excerpt");
});
