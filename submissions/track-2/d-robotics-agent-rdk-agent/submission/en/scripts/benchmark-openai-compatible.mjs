#!/usr/bin/env node

import { homedir } from "node:os";
import { readFile, writeFile } from "node:fs/promises";
import { resolve } from "node:path";

function parseArgs(argv) {
	const options = {
		config: resolve(homedir(), ".pi/agent/models.json"),
		provider: "amd",
		runs: 3,
		prompt: "Reply with exactly: RDK_AGENT_BENCHMARK_OK",
		output: undefined,
	};
	for (let i = 0; i < argv.length; i++) {
		const value = argv[i];
		if (value === "--config") options.config = resolve(argv[++i]);
		else if (value === "--provider") options.provider = argv[++i];
		else if (value === "--runs") options.runs = Number.parseInt(argv[++i], 10);
		else if (value === "--prompt") options.prompt = argv[++i];
		else if (value === "--output") options.output = resolve(argv[++i]);
		else if (value === "--help") {
			console.log(`Usage: node benchmark-openai-compatible.mjs [options]

Options:
  --config <path>       Pi models.json path
  --provider <id>       Provider key (default: amd)
  --runs <count>        Number of measured requests (default: 3)
  --prompt <text>       Fixed benchmark prompt
  --output <path>       Also write the sanitized JSON report
`);
			process.exit(0);
		} else throw new Error(`Unknown argument: ${value}`);
	}
	if (!Number.isInteger(options.runs) || options.runs < 1 || options.runs > 20) {
		throw new Error("--runs must be an integer from 1 to 20");
	}
	return options;
}

function resolveSecret(value) {
	if (typeof value !== "string" || value.length === 0) return undefined;
	if (value.startsWith("$")) {
		const name = value.replace(/^\$\{?/, "").replace(/\}?$/, "");
		return process.env[name];
	}
	if (value.startsWith("!")) {
		throw new Error("Command-based API keys are intentionally unsupported by this evidence script");
	}
	return value;
}

function quantile(values, fraction) {
	const ordered = [...values].sort((a, b) => a - b);
	const index = Math.min(ordered.length - 1, Math.max(0, Math.ceil(fraction * ordered.length) - 1));
	return ordered[index];
}

async function runOnce({ baseUrl, apiKey, model, prompt }) {
	const started = performance.now();
	const response = await fetch(`${baseUrl.replace(/\/$/, "")}/chat/completions`, {
		method: "POST",
		headers: {
			"content-type": "application/json",
			...(apiKey ? { authorization: `Bearer ${apiKey}` } : {}),
		},
		body: JSON.stringify({
			model,
			messages: [{ role: "user", content: prompt }],
			temperature: 0,
			max_tokens: 64,
			stream: true,
			stream_options: { include_usage: true },
		}),
	});
	if (!response.ok || !response.body) {
		const body = await response.text();
		throw new Error(`Endpoint returned HTTP ${response.status}: ${body.slice(0, 300)}`);
	}

	let buffer = "";
	let firstTokenMs;
	let text = "";
	let usage;
	const decoder = new TextDecoder();
	for await (const chunk of response.body) {
		buffer += decoder.decode(chunk, { stream: true });
		const lines = buffer.split(/\r?\n/);
		buffer = lines.pop() ?? "";
		for (const line of lines) {
			if (!line.startsWith("data:")) continue;
			const payload = line.slice(5).trim();
			if (!payload || payload === "[DONE]") continue;
			const value = JSON.parse(payload);
			const content = value.choices?.[0]?.delta?.content;
			if (typeof content === "string" && content.length > 0) {
				firstTokenMs ??= performance.now() - started;
				text += content;
			}
			if (value.usage) usage = value.usage;
		}
	}
	const totalMs = performance.now() - started;
	const completionTokens = usage?.completion_tokens;
	const decodeSeconds = firstTokenMs === undefined ? undefined : (totalMs - firstTokenMs) / 1000;
	return {
		firstTokenMs: firstTokenMs === undefined ? null : Number(firstTokenMs.toFixed(1)),
		totalMs: Number(totalMs.toFixed(1)),
		completionTokens: Number.isFinite(completionTokens) ? completionTokens : null,
		decodeTokensPerSecond:
			Number.isFinite(completionTokens) && decodeSeconds > 0
				? Number((completionTokens / decodeSeconds).toFixed(2))
				: null,
		responseMatched: text.trim() === "RDK_AGENT_BENCHMARK_OK",
	};
}

const options = parseArgs(process.argv.slice(2));
const configuration = JSON.parse(await readFile(options.config, "utf8"));
const provider = configuration.providers?.[options.provider];
if (!provider) throw new Error(`Provider ${options.provider} is not present in ${options.config}`);
if (provider.api !== "openai-completions") {
	throw new Error(`Provider API must be openai-completions, got ${provider.api ?? "undefined"}`);
}
const model = provider.models?.[0]?.id;
if (!provider.baseUrl || !model) throw new Error("Provider requires baseUrl and at least one model id");
const apiKey = resolveSecret(provider.apiKey);

const runs = [];
for (let index = 0; index < options.runs; index++) {
	runs.push(await runOnce({ baseUrl: provider.baseUrl, apiKey, model, prompt: options.prompt }));
}
const firstTokenValues = runs.map((run) => run.firstTokenMs).filter(Number.isFinite);
const totalValues = runs.map((run) => run.totalMs);
const throughputValues = runs.map((run) => run.decodeTokensPerSecond).filter(Number.isFinite);
const endpointHost = new URL(provider.baseUrl).host;
const report = {
	schema: "rdk-agent-openai-endpoint-benchmark/v1",
	generatedAt: new Date().toISOString(),
	provider: options.provider,
	model,
	endpointHost,
	runs,
	summary: {
		runCount: runs.length,
		responseMatchCount: runs.filter((run) => run.responseMatched).length,
		p50FirstTokenMs: firstTokenValues.length ? quantile(firstTokenValues, 0.5) : null,
		p95FirstTokenMs: firstTokenValues.length ? quantile(firstTokenValues, 0.95) : null,
		p50TotalMs: quantile(totalValues, 0.5),
		p95TotalMs: quantile(totalValues, 0.95),
		p50DecodeTokensPerSecond: throughputValues.length ? quantile(throughputValues, 0.5) : null,
	},
	methodology: {
		transport: "OpenAI-compatible streaming chat completions",
		requestMaxTokens: 64,
		temperature: 0,
		throughputDefinition: "completion_tokens / elapsed seconds after first non-empty content delta",
		limitations: [
			"This client-side measurement includes network and tunnel overhead.",
			"The report identifies the configured endpoint and model but does not independently attest the server GPU or ROCm version.",
		],
	},
};
const rendered = `${JSON.stringify(report, null, 2)}\n`;
process.stdout.write(rendered);
if (options.output) await writeFile(options.output, rendered, "utf8");
