#!/usr/bin/env node
/**
 * CLI wrapper for prompt hygiene scan (also covered by vitest).
 * Usage: node scripts/prompt-hygiene.mjs
 */
import { pathToFileURL } from "node:url";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const modUrl = pathToFileURL(
  join(root, "packages/agent-runtime/dist/model/prompt-hygiene.js")
).href;

const { scanPromptHygiene, formatPromptHygieneReport } = await import(modUrl);
const findings = scanPromptHygiene();
const report = formatPromptHygieneReport(findings);
console.log(report);
if (findings.length > 0) process.exit(1);
