const fs = require("fs");
const path = require("path");

const distHtml = path.join(__dirname, "../dist/index.html");
const outHeader = path.join(__dirname, "../dist/gen_index_html.h");

if (!fs.existsSync(distHtml)) {
    console.error("index.html not found. Please run pnpm build first.");
    process.exit(1);
}

const html = fs.readFileSync(distHtml);
const bytes = Array.from(html).map((b) => `0x${b.toString(16).padStart(2, "0")},`);
const lines = [];
for (let i = 0; i < bytes.length; i += 12) {
    lines.push("  " + bytes.slice(i, i + 12).join(" "));
}

const headerContent =
    `static const unsigned char index_html_bytes[] = {\n${lines.join("\n")}\n};\n` +
    "static const size_t index_html_size = sizeof(index_html_bytes);\n";

fs.writeFileSync(outHeader, headerContent);
console.log(`Generated ${outHeader}`);
