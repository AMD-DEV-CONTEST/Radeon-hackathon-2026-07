import { createHash } from "node:crypto";
import { readdir, readFile } from "node:fs/promises";
import path from "node:path";
import { fixturePath } from "../paths.js";

export type CorpusDocument = {
  id: string;
  sourcePath: string;
  title: string;
  licenseId: string;
  body: string;
  contentHash: string;
};

/**
 * Load local RAG corpus from fixtures/knowledge/corpus/*.md
 * Front-matter optional:
 *   ---
 *   title: ...
 *   licenseId: ...
 *   ---
 */
export async function loadRagCorpus(
  corpusDir: string = fixturePath("knowledge", "corpus")
): Promise<CorpusDocument[]> {
  let names: string[];
  try {
    names = await readdir(corpusDir);
  } catch {
    return [];
  }
  const mdFiles = names.filter((n) => n.endsWith(".md")).sort();
  const docs: CorpusDocument[] = [];
  for (const name of mdFiles) {
    const full = path.join(corpusDir, name);
    const raw = await readFile(full, "utf8");
    const parsed = parseFrontMatter(raw);
    const relative = path.posix.join("knowledge", "corpus", name);
    const contentHash = sha256(parsed.body);
    docs.push({
      id: `doc-${name.replace(/\.md$/i, "")}`,
      sourcePath: relative,
      title: parsed.title ?? name.replace(/\.md$/i, ""),
      licenseId: parsed.licenseId ?? "lic-privateplate-synthetic-1",
      body: parsed.body,
      contentHash
    });
  }
  return docs;
}

export function corpusFingerprint(docs: CorpusDocument[]): string {
  const payload = docs
    .map((d) => `${d.id}:${d.contentHash}`)
    .sort()
    .join("|");
  return sha256(payload);
}

function parseFrontMatter(raw: string): {
  title?: string;
  licenseId?: string;
  body: string;
} {
  if (!raw.startsWith("---\n")) {
    return { body: raw.trim() };
  }
  const end = raw.indexOf("\n---\n", 4);
  if (end < 0) {
    return { body: raw.trim() };
  }
  const header = raw.slice(4, end);
  const body = raw.slice(end + 5).trim();
  const result: { title?: string; licenseId?: string; body: string } = {
    body
  };
  for (const line of header.split("\n")) {
    const m = line.match(/^([A-Za-z0-9_]+):\s*(.*)$/);
    if (!m) continue;
    const key = m[1];
    const value = m[2]?.trim().replace(/^["']|["']$/g, "");
    if (!value) continue;
    if (key === "title") result.title = value;
    if (key === "licenseId") result.licenseId = value;
  }
  return result;
}

function sha256(text: string): string {
  return createHash("sha256").update(text, "utf8").digest("hex");
}
