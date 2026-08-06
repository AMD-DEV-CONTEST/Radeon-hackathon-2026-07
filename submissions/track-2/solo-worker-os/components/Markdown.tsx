import React from 'react';

/* ─── Inline renderer: bold, italic, inline code, links ───────── */

function renderInline(text: string, key: string): React.ReactNode[] {
  const nodes: React.ReactNode[] = [];
  const re = /(\*\*(.+?)\*\*|\*(.+?)\*|`([^`]+)`|\[([^\]]+)\]\(([^)]+)\))/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) nodes.push(text.slice(last, m.index));
    if (m[2])           nodes.push(<strong key={`${key}-b${i++}`} className="font-semibold text-gray-900 dark:text-white">{m[2]}</strong>);
    else if (m[3])      nodes.push(<em     key={`${key}-i${i++}`} className="italic text-gray-800 dark:text-white/80">{m[3]}</em>);
    else if (m[4])      nodes.push(
      <code key={`${key}-c${i++}`} className="rounded-md bg-gray-100 dark:bg-white/[0.07] px-1.5 py-0.5 font-mono text-[0.85em] text-amber-700 dark:text-amber-200/90">
        {m[4]}
      </code>
    );
    else if (m[5] && m[6]) {
      // Only allow safe URL protocols to prevent XSS (javascript:, data:, vbscript:)
      const href = m[6];
      const isSafe = /^(https?:|mailto:|\/|#)/i.test(href);
      nodes.push(
        <a key={`${key}-a${i++}`} href={isSafe ? href : '#'} target="_blank" rel="noopener noreferrer"
           className="text-amber-300 underline underline-offset-2 hover:text-amber-200 transition-colors">
          {m[5]}
        </a>
      );
    }
    last = m.index + m[0].length;
  }
  if (last < text.length) nodes.push(text.slice(last));
  return nodes;
}

/* ─── Table row parser ────────────────────────────────────────── */
function parseTableRow(line: string): string[] {
  return line.replace(/^\|/, '').replace(/\|\s*$/, '').split('|').map(c => c.trim());
}

/* ─── Main parser ─────────────────────────────────────────────── */

export default function Markdown({ content }: { content: string }) {
  const lines = content.replace(/\r\n/g, '\n').split('\n');
  const blocks: React.ReactNode[] = [];
  let list: { ordered: boolean; items: string[] } | null = null;
  let para: string[] = [];
  let inCode = false;
  let codeLang = '';
  let codeLines: string[] = [];
  let k = 0;

  const flushPara = () => {
    if (!para.length) return;
    blocks.push(
      <p key={`p-${k++}`} className="text-[14px] leading-relaxed text-gray-700 dark:text-white/70">
        {renderInline(para.join(' '), `p-${k}`)}
      </p>
    );
    para = [];
  };

  const flushList = () => {
    if (!list) return;
    const items = list.items.map((it, idx) => (
      <li key={`li-${k}-${idx}`} className="text-[14px] text-gray-700 dark:text-white/70">
        {renderInline(it, `li-${k}-${idx}`)}
      </li>
    ));
    blocks.push(
      list.ordered
        ? <ol key={`ol-${k++}`} className="ml-5 list-decimal space-y-1.5">{items}</ol>
        : <ul key={`ul-${k++}`} className="ml-5 list-disc space-y-1.5">{items}</ul>
    );
    list = null;
  };

  const flushCode = () => {
    blocks.push(
      <div key={`code-${k++}`} className="group relative overflow-hidden rounded-xl border border-gray-200 dark:border-white/[0.06] bg-gray-50 dark:bg-[#0b0b0d]">
        {codeLang && (
          <div className="flex items-center justify-between border-b border-gray-200 dark:border-white/[0.05] px-4 py-2">
            <span className="font-mono text-[11px] text-gray-400 dark:text-white/25">{codeLang}</span>
          </div>
        )}
        <pre className="overflow-x-auto p-4 font-mono text-[12.5px] leading-relaxed text-gray-700 dark:text-white/75">
          <code>{codeLines.join('\n')}</code>
        </pre>
      </div>
    );
    codeLines = [];
    codeLang = '';
  };

  for (let i = 0; i < lines.length; i++) {
    const raw = lines[i];
    const line = raw.trimEnd();

    // ── Code block ───────────────────────────────────────────────
    if (inCode) {
      if (line.startsWith('```')) {
        flushCode();
        inCode = false;
      } else {
        codeLines.push(raw);
      }
      continue;
    }
    if (line.startsWith('```')) {
      flushPara(); flushList();
      inCode = true;
      codeLang = line.slice(3).trim();
      continue;
    }

    // ── Blank line ───────────────────────────────────────────────
    if (/^\s*$/.test(line)) { flushPara(); flushList(); continue; }

    // ── Horizontal rule ─────────────────────────────────────────
    if (/^---+\s*$/.test(line)) {
      flushPara(); flushList();
      blocks.push(<hr key={`hr-${k++}`} className="my-3 border-gray-200 dark:border-white/[0.07]" />);
      continue;
    }

    // ── Headings ─────────────────────────────────────────────────
    const hm = /^(#{1,6})\s+(.*)$/.exec(line);
    if (hm) {
      flushPara(); flushList();
      const level = hm[1].length;
      const cls =
        level === 1 ? 'text-[18px] font-extrabold text-gray-900 dark:text-white' :
        level === 2 ? 'text-[15px] font-bold text-gray-900 dark:text-white' :
                     'text-[14px] font-semibold text-gray-900 dark:text-white/90';
      blocks.push(
        <p key={`h-${k++}`} className={`mt-1 ${cls}`}>
          {renderInline(hm[2], `h-${k}`)}
        </p>
      );
      continue;
    }

    // ── Blockquote ───────────────────────────────────────────────
    const bq = /^>\s+(.*)$/.exec(line);
    if (bq) {
      flushPara(); flushList();
      blocks.push(
        <blockquote key={`bq-${k++}`} className="border-l-2 border-amber-400/30 pl-4 text-[14px] italic text-gray-500 dark:text-white/50">
          {renderInline(bq[1], `bq-${k}`)}
        </blockquote>
      );
      continue;
    }

    // ── Unordered list ───────────────────────────────────────────
    const ul = /^[-*]\s+(.*)$/.exec(line);
    if (ul) {
      flushPara();
      if (!list || list.ordered) { flushList(); list = { ordered: false, items: [] }; }
      list.items.push(ul[1]);
      continue;
    }

    // ── Ordered list ─────────────────────────────────────────────
    const ol = /^\d+\.\s+(.*)$/.exec(line);
    if (ol) {
      flushPara();
      if (!list || !list.ordered) { flushList(); list = { ordered: true, items: [] }; }
      list.items.push(ol[1]);
      continue;
    }

    // ── Table (GFM style) ────────────────────────────────────────
    if (line.startsWith('|')) {
      const nextLine = (lines[i + 1] ?? '').trimEnd();
      if (/^\|[\s:|-]+$/.test(nextLine) && nextLine.includes('-')) {
        flushPara(); flushList();
        const header = parseTableRow(line);
        const rows: string[][] = [];
        i++; // skip separator line
        while (i + 1 < lines.length && lines[i + 1].trimEnd().startsWith('|')) {
          i++;
          rows.push(parseTableRow(lines[i].trimEnd()));
        }
        blocks.push(
          <div key={`tbl-${k++}`} className="overflow-x-auto rounded-xl border border-gray-200 dark:border-white/[0.06]">
            <table className="w-full border-collapse text-[13px]">
              <thead>
                <tr className="border-b border-gray-200 dark:border-white/10 bg-gray-50 dark:bg-white/[0.02]">
                  {header.map((h, idx) => (
                    <th key={idx} className="px-3 py-2 text-left font-semibold text-gray-800 dark:text-white/80">
                      {renderInline(h, `th-${k}-${idx}`)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((row, ri) => (
                  <tr key={ri} className="border-b border-gray-100 dark:border-white/[0.04] last:border-0">
                    {row.map((cell, ci) => (
                      <td key={ci} className="px-3 py-2 text-gray-600 dark:text-white/60">
                        {renderInline(cell, `td-${k}-${ri}-${ci}`)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );
        continue;
      }
    }

    // ── Normal paragraph ─────────────────────────────────────────
    flushList();
    para.push(line);
  }

  flushPara();
  flushList();
  if (inCode) flushCode(); // unclosed block

  return <div className="space-y-3">{blocks}</div>;
}
