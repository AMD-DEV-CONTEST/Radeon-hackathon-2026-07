import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { dirname, extname, join } from "node:path";
import { fileURLToPath } from "node:url";

import enUS from "../src/i18n/messages/en-US.js";

const testDir = dirname(fileURLToPath(import.meta.url));
const sourceRoot = join(testDir, "..", "src");
const catalogPath = join(sourceRoot, "i18n", "messages", "en-US.js");
const languageDialogPath = join(sourceRoot, "components", "LanguageSelectionDialog.vue");
const HAN = /\p{Script=Han}/u;

function sourceFiles(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) return sourceFiles(path);
    return [path];
  }).filter((path) => [".js", ".vue"].includes(extname(path)));
}

test("the English catalog does not declare duplicate keys", () => {
  const source = readFileSync(catalogPath, "utf8");
  const keys = [...source.matchAll(/^\s{2}("(?:[^"\\]|\\.)+"):/gm)]
    .map((match) => JSON.parse(match[1]));
  const duplicates = keys.filter((key, index) => keys.indexOf(key) !== index);
  assert.deepEqual([...new Set(duplicates)], []);
});

test("literal translation calls resolve to an English catalog entry", () => {
  const missing = [];
  for (const path of sourceFiles(sourceRoot)) {
    const source = readFileSync(path, "utf8");
    const calls = source.matchAll(/\b(?:t|translate)\(\s*(["'])((?:\\.|(?!\1).)*)\1/g);
    for (const match of calls) {
      const key = match[2].replaceAll(`\\${match[1]}`, match[1]);
      if (!(key in enUS)) missing.push(`${path}: ${key}`);
    }
  }
  assert.deepEqual(missing, []);
});

test("Chinese string literals used as UI keys exist in the English catalog", () => {
  const missing = [];
  for (const path of sourceFiles(sourceRoot)) {
    if (path === catalogPath || path === languageDialogPath) continue;
    const fileSource = readFileSync(path, "utf8");
    const source = extname(path) === ".vue"
      ? [...fileSource.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)].map((match) => match[1]).join("\n")
      : fileSource;
    for (const match of source.matchAll(/(["'`])((?:\\.|(?!\1).)*)\1/g)) {
      const value = match[2].replaceAll(`\\${match[1]}`, match[1]);
      if (HAN.test(value) && !value.includes("${") && !(value in enUS)) {
        missing.push(`${path}: ${value}`);
      }
    }
  }
  assert.deepEqual([...new Set(missing)], []);
});

test("Vue templates contain no untranslated static Chinese UI text", () => {
  const findings = [];
  for (const path of sourceFiles(sourceRoot).filter((item) => extname(item) === ".vue")) {
    if (path === languageDialogPath) continue;
    const source = readFileSync(path, "utf8");
    const template = source.match(/<template>([\s\S]*?)<\/template>/)?.[1] || "";
    for (const match of template.matchAll(/>([^<]+)</g)) {
      const text = match[1].replace(/\{\{[\s\S]*?\}\}/g, "").trim();
      if (HAN.test(text)) findings.push(`${path}: text=${text}`);
    }
    for (const match of template.matchAll(/(?<![:@])\b(?:placeholder|title|aria-label)="([^"]*)"/g)) {
      if (HAN.test(match[1])) findings.push(`${path}: attribute=${match[1]}`);
    }
  }
  assert.deepEqual(findings, []);
});
