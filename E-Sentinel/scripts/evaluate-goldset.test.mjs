/**
 * metrics 指标库测试：锁死公式，防"数字算错没法现场复算"。
 * 用法：node --test scripts/evaluate-goldset.test.mjs
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  isSevere,
  binarySeverityMetrics,
  macroF1ByRiskClass,
  macroF1ByViolationCategory,
  cohensKappa,
  riskAccuracy,
} from "./lib/metrics.mjs";

test("isSevere: high risk → severe", () => {
  assert.equal(isSevere({ riskLevel: "high", violations: [] }), true);
  assert.equal(isSevere({ riskLevel: "low", violations: [] }), false);
});

test("isSevere: severity 口径与 gold 一致，仅按 risk_level", () => {
  // gold 中 medium+major 违规标 severe:false；因此 major 违规本身不触发 severe。
  assert.equal(isSevere({ riskLevel: "low", violations: [{ severity: "major" }] }), false);
  assert.equal(isSevere({ riskLevel: "medium", violations: [{ severity: "major" }] }), false);
  assert.equal(isSevere({ riskLevel: "high", violations: [] }), true);
  assert.equal(isSevere({ riskLevel: "critical", violations: [{ severity: "minor" }] }), true);
});

test("binarySeverityMetrics: perfect prediction", () => {
  const m = binarySeverityMetrics([true, true, false, false], [true, true, false, false]);
  assert.equal(m.tp, 2);
  assert.equal(m.fn, 0);
  assert.equal(m.fp, 0);
  assert.equal(m.tn, 2);
  assert.equal(m.recall, 1);
  assert.equal(m.precision, 1);
  assert.equal(m.f1, 1);
  assert.equal(m.fpr, 0);
});

test("binarySeverityMetrics: one miss, one false alarm", () => {
  const m = binarySeverityMetrics([true, true, false], [true, false, true]);
  assert.equal(m.tp, 1);
  assert.equal(m.fn, 1);
  assert.equal(m.fp, 1);
  assert.equal(m.tn, 0);
  assert.equal(m.recall, 0.5);
  assert.equal(m.precision, 0.5);
  assert.equal(m.fpr, 1);
});

test("macroF1ByRiskClass: perfect → 1", () => {
  const m = macroF1ByRiskClass(["low", "medium", "high", "critical"], ["low", "medium", "high", "critical"]);
  assert.equal(m, 1);
});

test("macroF1ByRiskClass: all wrong → 0", () => {
  const m = macroF1ByRiskClass(["low", "low"], ["high", "high"]);
  assert.equal(m, 0);
});

test("cohensKappa: perfect agreement → 1", () => {
  const k = cohensKappa(["low", "high", "critical"], ["low", "high", "critical"]);
  assert.equal(k, 1);
});

test("riskAccuracy: 3/4 correct → 0.75", () => {
  const a = riskAccuracy(["low", "high", "medium", "low"], ["low", "high", "low", "low"]);
  assert.equal(a, 0.75);
});

test("macroF1ByViolationCategory: perfect", () => {
  const cats = ["服务态度", "专业性"];
  const gold = [new Set(["服务态度"]), new Set(["专业性"])];
  const pred = [new Set(["服务态度"]), new Set(["专业性"])];
  assert.equal(macroF1ByViolationCategory(gold, pred, cats), 1);
});
