import assert from "node:assert/strict";
import test from "node:test";
import { outputLanguageInstruction, parseLocale } from "../../src/shared/locale.ts";

test("locale parsing keeps Chinese as the default and accepts English aliases", () => {
	assert.equal(parseLocale(), "zh-CN");
	assert.equal(parseLocale("zh"), "zh-CN");
	assert.equal(parseLocale("zh-CN"), "zh-CN");
	assert.equal(parseLocale("en"), "en");
	assert.equal(parseLocale("en-US"), "en");
});

test("unsupported locales fail with a bilingual actionable error", () => {
	assert.throws(() => parseLocale("fr"), /Unsupported language.*zh-CN, en/);
});

test("English language instructions preserve machine-readable output", () => {
	const instruction = outputLanguageInstruction("en");
	assert.match(instruction, /must be in English/);
	assert.match(instruction, /machine-readable result markers exactly/);
});
