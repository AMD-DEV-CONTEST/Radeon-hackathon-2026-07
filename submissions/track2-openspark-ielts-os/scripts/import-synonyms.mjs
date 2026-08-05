import { readFile, writeFile } from "node:fs/promises";

const sourcePath = process.argv[2];
if (!sourcePath) throw new Error("Usage: node scripts/import-synonyms.mjs <extracted-docx.json>");

const { paragraphs } = JSON.parse(await readFile(sourcePath, "utf8"));
const groups = [];
for (const paragraph of paragraphs.slice(1)) {
  const match = paragraph.match(/^(\d+)\.\s*(.*)$/);
  if (match) groups.push({ id: Number(match[1]), raw: match[2] });
  else if (groups.length) groups.at(-1).raw += ` ${paragraph}`;
}

const noise = new Set(["and", "or", "in", "of", "to", "for", "from", "by", "on", "with", "sth", "sb", "the", "a", "an", "n", "v"]);
for (const group of groups) {
  group.terms = [...new Set(group.raw
    .replace(/\([^)]*\)|\[[^\]]*\]/g, " ")
    .replace(/[^\x00-\x7F]+/g, "/")
    .replace(/(?:=>|->|><|=|;|,|:)/g, "/")
    .split("/")
    .flatMap((part) => part.toLowerCase().match(/[a-z]+(?:[- ][a-z]+){0,5}/g) || [])
    .map((term) => term.trim().replace(/^(be|is|are)\s+/, ""))
    .filter((term) => term.length > 1 && !noise.has(term)))];
}

const cleanGroups = groups.filter((group) => group.terms.length >= 2);
await writeFile(new URL("../data/synonyms.json", import.meta.url), `${JSON.stringify({
  title: "99 组雅思考试阅读同义词替换",
  source: "个人资料 · 桃子99组雅思阅读同义词替换",
  groups: cleanGroups
}, null, 2)}\n`);

const wordbookUrl = new URL("../data/wordbook.json", import.meta.url);
const wordbook = JSON.parse(await readFile(wordbookUrl, "utf8"));
const byName = new Map(wordbook.words.map((item) => [item.word.toLowerCase(), item]));
for (const group of cleanGroups) {
  for (const term of group.terms) {
    const item = byName.get(term);
    if (item) item.links = [...new Set([...(item.links || []), ...group.terms.filter((value) => value !== term)])].slice(0, 12);
  }
}
await writeFile(wordbookUrl, `${JSON.stringify(wordbook, null, 2)}\n`);
console.log(`Imported ${cleanGroups.length} synonym groups; enriched ${wordbook.words.filter((item) => item.links?.length).length} vocabulary entries.`);

