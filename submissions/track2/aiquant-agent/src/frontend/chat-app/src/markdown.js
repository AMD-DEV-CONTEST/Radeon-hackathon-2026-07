// 简单 Markdown 渲染（零依赖，量化场景够用）

export function renderMarkdown(text) {
  if (!text) return '';
  let html = escapeHtml(text);

  // 代码块 ```lang\ncode\n```
  html = html.replace(/```(\w*)\n([\s\S]*?)```/g, (_, lang, code) =>
    `<pre class="md-pre"><div class="md-code-lang">${lang || 'code'}</div><code>${code.trim()}</code></pre>`
  );

  // 行内代码
  html = html.replace(/`([^`\n]+)`/g, '<code class="md-code">$1</code>');

  // 标题
  html = html.replace(/^#### (.+)$/gm, '<h4 class="md-h4">$1</h4>');
  html = html.replace(/^### (.+)$/gm, '<h3 class="md-h3">$1</h3>');
  html = html.replace(/^## (.+)$/gm, '<h2 class="md-h2">$1</h2>');
  html = html.replace(/^# (.+)$/gm, '<h1 class="md-h1">$1</h1>');

  // 粗体 / 斜体
  html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/\*([^*]+)\*/g, '<em>$1</em>');

  // 链接
  html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g,
    '<a href="$2" target="_blank" rel="noopener" class="md-link">$1</a>');

  // 表格
  html = renderTables(html);

  // 分隔线
  html = html.replace(/^---$/gm, '<hr class="md-hr"/>');

  // 无序列表
  html = html.replace(/^[\-•] (.+)$/gm, '<li class="md-li">$1</li>');
  html = html.replace(/((?:<li class="md-li">.*?<\/li>\n?)+)/gs, '<ul class="md-ul">$1</ul>');

  // 有序列表
  html = html.replace(/^\d+[.、] (.+)$/gm, '<li class="md-oli">$1</li>');
  html = html.replace(/((?:<li class="md-oli">.*?<\/li>\n?)+)/gs, '<ol class="md-ol">$1</ol>');

  // 换行 → <br>（跳过 block 元素后的换行）
  html = html.replace(/\n/g, '<br>');
  html = html.replace(/(<\/(?:pre|ul|ol|h[1-4]|table|hr)[^>]*>)<br>/g, '$1');
  html = html.replace(/<br>(<(?:pre|ul|ol|h[1-4]|table|hr))/g, '$1');

  return html;
}

function escapeHtml(text) {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function renderTables(html) {
  const lines = html.split('\n');
  const out = [];
  let inTable = false;
  let rows = [];

  for (const line of lines) {
    const trimmed = line.trim();
    if (trimmed.startsWith('|') && trimmed.endsWith('|')) {
      if (/^\|[\s\-|]+\|$/.test(trimmed)) { inTable = true; continue; }
      if (!inTable) { inTable = true; rows = []; }
      rows.push(trimmed);
    } else {
      if (inTable) { out.push(buildTable(rows)); inTable = false; rows = []; }
      out.push(line);
    }
  }
  if (inTable) out.push(buildTable(rows));
  return out.join('\n');
}

function buildTable(rows) {
  if (!rows.length) return '';
  let html = '<div class="md-table-wrap"><table class="md-table">';
  rows.forEach((row, i) => {
    const cells = row.split('|').filter(c => c.trim() !== '');
    const tag = i === 0 ? 'th' : 'td';
    html += `<tr>${cells.map(c => `<${tag}>${c.trim()}</${tag}>`).join('')}</tr>`;
  });
  return html + '</table></div>';
}
