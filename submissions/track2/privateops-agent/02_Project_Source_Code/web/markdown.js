(function (root) {
  function escapeHtml(value) {
    return String(value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function safeLink(label, url) {
    try {
      const parsed = new URL(url);
      if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return label;
      return `<a href="${escapeHtml(parsed.href)}" target="_blank" rel="noopener noreferrer">${label}</a>`;
    } catch (_error) {
      return label;
    }
  }

  function inline(value) {
    const code = [];
    let output = escapeHtml(value).replace(/`([^`]+)`/g, (_match, content) => {
      const token = `\u0000CODE${code.length}\u0000`;
      code.push(`<code>${content}</code>`);
      return token;
    });
    output = output.replace(/\[([^\]]+)\]\(([^\s)]+)(?:\s+&quot;[^&]*&quot;)?\)/g, (_match, label, url) => safeLink(label, url));
    output = output.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    output = output.replace(/__([^_]+)__/g, "<strong>$1</strong>");
    output = output.replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>");
    output = output.replace(/(^|[^_])_([^_\n]+)_/g, "$1<em>$2</em>");
    return output.replace(/\u0000CODE(\d+)\u0000/g, (_match, index) => code[Number(index)]);
  }

  function tableCells(line) {
    const trimmed = line.trim().replace(/^\|/, "").replace(/\|$/, "");
    return trimmed.split("|").map((cell) => cell.trim());
  }

  function isTableDivider(line) {
    const cells = tableCells(line);
    return cells.length > 0 && cells.every((cell) => /^:?-{3,}:?$/.test(cell));
  }

  function startsBlock(lines, index) {
    const line = lines[index] || "";
    return /^```/.test(line)
      || /^(#{1,6})\s+/.test(line)
      || /^>\s?/.test(line)
      || /^\s*[-*+]\s+/.test(line)
      || /^\s*\d+[.)]\s+/.test(line)
      || (line.includes("|") && isTableDivider(lines[index + 1] || ""));
  }

  function render(markdown) {
    if (typeof markdown !== "string" || !markdown.trim()) return "";
    const lines = markdown.replace(/\r\n?/g, "\n").split("\n");
    const output = [];
    let index = 0;
    while (index < lines.length) {
      const line = lines[index];
      if (!line.trim()) {
        index += 1;
        continue;
      }

      const fence = /^```([A-Za-z0-9_-]*)\s*$/.exec(line);
      if (fence) {
        const content = [];
        index += 1;
        while (index < lines.length && !/^```\s*$/.test(lines[index])) {
          content.push(lines[index]);
          index += 1;
        }
        if (index < lines.length) index += 1;
        const className = fence[1] ? ` class="language-${fence[1]}"` : "";
        output.push(`<pre><code${className}>${escapeHtml(content.join("\n"))}\n</code></pre>`);
        continue;
      }

      const heading = /^(#{1,6})\s+(.+)$/.exec(line);
      if (heading) {
        const level = heading[1].length;
        output.push(`<h${level}>${inline(heading[2])}</h${level}>`);
        index += 1;
        continue;
      }

      if (line.includes("|") && isTableDivider(lines[index + 1] || "")) {
        const headers = tableCells(line);
        index += 2;
        const rows = [];
        while (index < lines.length && lines[index].trim() && lines[index].includes("|")) {
          rows.push(tableCells(lines[index]));
          index += 1;
        }
        const head = `<thead><tr>${headers.map((cell) => `<th>${inline(cell)}</th>`).join("")}</tr></thead>`;
        const body = `<tbody>${rows.map((row) => `<tr>${headers.map((_header, cellIndex) => `<td>${inline(row[cellIndex] || "")}</td>`).join("")}</tr>`).join("")}</tbody>`;
        output.push(`<div class="markdown-table-wrap"><table>${head}${body}</table></div>`);
        continue;
      }

      const unordered = /^\s*[-*+]\s+(.+)$/.exec(line);
      const ordered = /^\s*\d+[.)]\s+(.+)$/.exec(line);
      if (unordered || ordered) {
        const tag = unordered ? "ul" : "ol";
        const items = [];
        while (index < lines.length) {
          const match = tag === "ul"
            ? /^\s*[-*+]\s+(.+)$/.exec(lines[index])
            : /^\s*\d+[.)]\s+(.+)$/.exec(lines[index]);
          if (!match) break;
          items.push(`<li>${inline(match[1])}</li>`);
          index += 1;
        }
        output.push(`<${tag}>${items.join("")}</${tag}>`);
        continue;
      }

      if (/^>\s?/.test(line)) {
        const quote = [];
        while (index < lines.length && /^>\s?/.test(lines[index])) {
          quote.push(lines[index].replace(/^>\s?/, ""));
          index += 1;
        }
        output.push(`<blockquote><p>${inline(quote.join(" "))}</p></blockquote>`);
        continue;
      }

      const paragraph = [];
      while (index < lines.length && lines[index].trim() && !startsBlock(lines, index)) {
        paragraph.push(lines[index]);
        index += 1;
      }
      if (paragraph.length) {
        output.push(`<p>${paragraph.map(inline).join("<br>")}</p>`);
      } else {
        output.push(`<p>${inline(lines[index])}</p>`);
        index += 1;
      }
    }
    return output.join("");
  }

  root.PrivateOpsMarkdown = {render};
})(globalThis);
