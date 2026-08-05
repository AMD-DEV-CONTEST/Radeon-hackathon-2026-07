import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const wordbook = JSON.parse(await readFile(new URL("../data/wordbook.json", import.meta.url), "utf8"));
assert.equal(wordbook.book.total, 8000);
assert.equal(wordbook.words.length, 8000);
assert.equal(new Set(wordbook.words.map((item) => item.word.toLowerCase())).size, 8000);
assert.ok(wordbook.words.every((item) => item.definition));
assert.ok(wordbook.words.filter((item) => item.example).length >= 23);
assert.ok(wordbook.words.every((item) => !item.ieltsExample), "public wordbook must not ship unlicensed external examples");
assert.ok(wordbook.words.filter((item) => item.exampleZh).length >= 23);
assert.ok(wordbook.words.every((item) => !/^听力场景[:：]/.test(item.example || "") && !/^听力场景[:：]/.test(item.ieltsExample || "")));
assert.ok(wordbook.words.every((item) => !item.example || item.example !== item.ieltsExample));
console.log("Complete 8,000-word book checks passed.");
