import { mkdir, readdir, stat, writeFile } from "node:fs/promises";
import { extname, join, relative } from "node:path";

const source = process.env.IELTS_LIBRARY_PATH
  || "/Users/francischi/Library/Mobile Documents/com~apple~CloudDocs/雅思/雅思全套资料";
const output = process.env.IELTS_LIBRARY_OUTPUT
  ? new URL(`file://${process.env.IELTS_LIBRARY_OUTPUT}`)
  : new URL("../local-library/catalog.json", import.meta.url);
const kinds = new Map([
  [".pdf", "document"], [".doc", "document"], [".docx", "document"],
  [".mp3", "audio"], [".m4a", "audio"], [".wav", "audio"],
  [".mp4", "video"], [".mov", "video"],
  [".json", "data"], [".xlsx", "data"], [".xls", "data"]
]);

const items = [];

async function scan(directory) {
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    if (entry.name.startsWith(".")) continue;
    const path = join(directory, entry.name);
    if (entry.isDirectory()) await scan(path);
    else if (entry.isFile()) {
      const info = await stat(path);
      const extension = extname(entry.name).toLowerCase();
      items.push({
        path: relative(source, path),
        name: entry.name,
        kind: kinds.get(extension) || "other",
        bytes: info.size,
        modifiedAt: info.mtime.toISOString()
      });
    }
  }
}

await scan(source);
items.sort((a, b) => a.path.localeCompare(b.path, "zh-CN"));
const counts = Object.groupBy(items, ({ kind }) => kind);
const catalog = {
  version: 1,
  generatedAt: new Date().toISOString(),
  source: "iCloud Drive/雅思/雅思全套资料",
  totalFiles: items.length,
  totalBytes: items.reduce((sum, item) => sum + item.bytes, 0),
  counts: Object.fromEntries(Object.entries(counts).map(([kind, values]) => [kind, values.length])),
  items
};

await mkdir(new URL("../local-library/", import.meta.url), { recursive: true });
await writeFile(output, `${JSON.stringify(catalog, null, 2)}\n`);
console.log(`Indexed ${catalog.totalFiles} files (${catalog.totalBytes} bytes) -> ${output.pathname}`);
