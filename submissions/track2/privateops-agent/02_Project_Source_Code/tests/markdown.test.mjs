import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import test from "node:test";

const modulePath = new URL("../web/markdown.js", import.meta.url);
assert.ok(existsSync(modulePath), "web/markdown.js must provide safe Markdown rendering");
await import(modulePath);

const markdown = globalThis.PrivateOpsMarkdown;

test("renders headings paragraphs and inline emphasis", () => {
  const html = markdown.render("# Result\n\nThis is **important** and *local* with `code`.");
  assert.match(html, /<h1>Result<\/h1>/);
  assert.match(html, /<p>This is <strong>important<\/strong> and <em>local<\/em> with <code>code<\/code>\.<\/p>/);
});

test("renders ordered and unordered lists", () => {
  const html = markdown.render("- First\n- Second\n\n1. Inspect\n2. Report");
  assert.match(html, /<ul><li>First<\/li><li>Second<\/li><\/ul>/);
  assert.match(html, /<ol><li>Inspect<\/li><li>Report<\/li><\/ol>/);
});

test("renders blockquotes fenced code and language class", () => {
  const html = markdown.render("> Observed locally\n\n```powershell\nGet-Process <unsafe>\n```");
  assert.match(html, /<blockquote><p>Observed locally<\/p><\/blockquote>/);
  assert.match(html, /<pre><code class="language-powershell">Get-Process &lt;unsafe&gt;\n<\/code><\/pre>/);
});

test("renders a Markdown table with escaped cells", () => {
  const html = markdown.render("| Name | Status |\n| --- | :---: |\n| Agent | **Ready** |");
  assert.match(html, /<table>/);
  assert.match(html, /<thead><tr><th>Name<\/th><th>Status<\/th><\/tr><\/thead>/);
  assert.match(html, /<tbody><tr><td>Agent<\/td><td><strong>Ready<\/strong><\/td><\/tr><\/tbody>/);
});

test("allows only HTTP and HTTPS links", () => {
  const html = markdown.render("[Safe](https://example.com) [Bad](javascript:alert(1)) [Mail](mailto:a@example.com)");
  assert.match(html, /href="https:\/\/example\.com\//);
  assert.match(html, /rel="noopener noreferrer"/);
  assert.doesNotMatch(html, /javascript:/i);
  assert.doesNotMatch(html, /mailto:/i);
  assert.match(html, /Bad/);
  assert.match(html, /Mail/);
});

test("escapes raw HTML and event handlers instead of executing them", () => {
  const html = markdown.render('<script>alert(1)</script>\n\n<img src=x onerror="alert(2)">');
  assert.doesNotMatch(html, /<script/i);
  assert.doesNotMatch(html, /<img/i);
  assert.doesNotMatch(html, /<[^>]+\sonerror=/i);
  assert.match(html, /&lt;script&gt;/);
  assert.match(html, /&lt;img src=x onerror=&quot;alert\(2\)&quot;&gt;/);
});

test("empty or non-string input produces no markup", () => {
  assert.equal(markdown.render(""), "");
  assert.equal(markdown.render(null), "");
});
