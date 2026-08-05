import { readFile, writeFile } from "node:fs/promises";

const rowsPath = process.argv[2];
if (!rowsPath) throw new Error("Usage: node scripts/import-vocabulary.mjs <rows.json>");

const rows = JSON.parse(await readFile(rowsPath, "utf8"));
const wordbookUrl = new URL("../data/wordbook.json", import.meta.url);
const wordbook = JSON.parse(await readFile(wordbookUrl, "utf8"));
const existing = new Map(wordbook.words.map((item) => [item.word.trim().toLowerCase(), item]));

for (const [number, scene, word, meaning] of rows.slice(1)) {
  const normalized = String(word || "").trim().toLowerCase();
  if (!normalized || existing.has(normalized)) continue;
  existing.set(normalized, {
    word: String(word).trim(),
    phonetic: "",
    definition: String(meaning || "").trim(),
    status: "新词",
    memoryState: "new",
    bookIndex: 1000 + Number(number || existing.size),
    example: "",
    ieltsExample: "",
    source: "个人资料 · 听力核心场景词汇",
    topic: String(scene || "").trim(),
    links: []
  });
}

wordbook.words = [...existing.values()];
wordbook.book.total = wordbook.words.length;
wordbook.book.newToday = 8;
await writeFile(wordbookUrl, `${JSON.stringify(wordbook, null, 2)}\n`);
console.log(`Vocabulary library now contains ${wordbook.words.length} unique entries.`);
