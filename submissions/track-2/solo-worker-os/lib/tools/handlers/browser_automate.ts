/**
 * Browser automation tool — lightweight web content extraction.
 *
 * Strategic purpose: the "time arbitrage" play. When new tools (WorkBuddy, etc.)
 * launch, the system can fetch their pricing/feature pages and extract
 * structured data for benchmark reports and content creation.
 *
 * Uses fetch + lightweight HTML parsing (no Puppeteer/Playwright dependency
 * at runtime). This works in serverless; if a full browser is available
 * locally (self-hosted AMD deployment), the tool degrades gracefully and
 * the fetch path still returns useful text.
 */

import { z } from 'zod';
import type { ToolConfig } from '../types';

// ─── Zod schema ────────────────────────────────────────────────────────────────
const BrowserAutomateSchema = z.object({
  url: z.string().url(),
  action: z.enum(['fetch', 'extract', 'research']).default('fetch'),
  selector: z
    .enum(['headings', 'links', 'tables', 'text', 'meta'])
    .optional()
    .describe('For extract action: which element type to pull'),
  max_chars: z.number().int().min(200).max(20000).default(4000),
});

// ─── HTML utilities ────────────────────────────────────────────────────────────

/** Tags whose entire content (including children) should be discarded. */
const DROP_TAGS = new Set([
  'script', 'style', 'noscript', 'svg', 'canvas', 'template',
  'iframe', 'embed', 'object', 'video', 'audio',
]);

/**
 * Strip HTML to readable text.
 * Removes scripts/styles, decodes entities, collapses whitespace.
 * Not a full parser — intentionally lightweight for serverless.
 */
function htmlToReadableText(html: string): string {
  let s = html;

  // Remove HTML comments
  s = s.replace(/<!--[\s\S]*?-->/g, '');

  // Remove drop tags entirely (script, style, etc.)
  for (const tag of DROP_TAGS) {
    const re = new RegExp(`<${tag}\\b[^>]*>[\\s\\S]*?</${tag}>`, 'gi');
    s = s.replace(re, '');
  }

  // Convert <br> and <p> to newlines before stripping tags
  s = s.replace(/<br\s*\/?>/gi, '\n');
  s = s.replace(/<\/(p|div|section|article|li|h[1-6])>/gi, '\n');

  // Decode common HTML entities
  s = s
    .replace(/&nbsp;/g, ' ')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&#x27;/g, "'")
    .replace(/&hellip;/g, '…')
    .replace(/&mdash;/g, '—')
    .replace(/&ndash;/g, '–');

  // Strip all remaining tags
  s = s.replace(/<[^>]+>/g, '');

  // Collapse whitespace
  s = s
    .replace(/[ \t]+/g, ' ')
    .replace(/\n{3,}/g, '\n\n')
    .trim();

  return s;
}

interface ExtractedLink {
  text: string;
  href: string;
}

interface ExtractedHeading {
  level: number;
  text: string;
}

/** Extract <a href> pairs from HTML. */
function extractLinks(html: string): ExtractedLink[] {
  const links: ExtractedLink[] = [];
  const re = /<a\s+[^>]*href=["']([^"']+)["'][^>]*>([\s\S]*?)<\/a>/gi;
  let m: RegExpExecArray | null;
  while ((m = re.exec(html)) !== null) {
    const href = m[1].trim();
    // Skip anchors, javascript, and mailto
    if (href.startsWith('#') || href.startsWith('javascript:') || href.startsWith('mailto:')) continue;
    const text = m[2].replace(/<[^>]+>/g, '').trim();
    if (text && text.length <= 120) links.push({ text, href });
  }
  return links.slice(0, 50); // cap
}

/** Extract <h1>-<h6> text from HTML. */
function extractHeadings(html: string): ExtractedHeading[] {
  const headings: ExtractedHeading[] = [];
  const re = /<h([1-6])\b[^>]*>([\s\S]*?)<\/h\1>/gi;
  let m: RegExpExecArray | null;
  while ((m = re.exec(html)) !== null) {
    const text = m[2].replace(/<[^>]+>/g, '').trim();
    if (text) headings.push({ level: parseInt(m[1], 10), text });
  }
  return headings;
}

/** Extract <table> content as simplified rows. */
function extractTables(html: string): string[][][] {
  const tables: string[][][] = [];
  const tableRe = /<table\b[^>]*>([\s\S]*?)<\/table>/gi;
  let tm: RegExpExecArray | null;
  while ((tm = tableRe.exec(html)) !== null) {
    const rows: string[][] = [];
    const rowRe = /<tr\b[^>]*>([\s\S]*?)<\/tr>/gi;
    let rm: RegExpExecArray | null;
    while ((rm = rowRe.exec(tm[1])) !== null) {
      const cells: string[] = [];
      const cellRe = /<t[dh]\b[^>]*>([\s\S]*?)<\/t[dh]>/gi;
      let cm: RegExpExecArray | null;
      while ((cm = cellRe.exec(rm[1])) !== null) {
        cells.push(cm[1].replace(/<[^>]+>/g, '').trim());
      }
      if (cells.length > 0) rows.push(cells);
    }
    if (rows.length > 0) tables.push(rows);
  }
  return tables.slice(0, 5); // cap at 5 tables
}

/** Extract <title> and <meta> description/og tags. */
function extractMeta(html: string): { title: string; description: string; ogTitle: string; ogDescription: string } {
  let title = '';
  const titleMatch = html.match(/<title[^>]*>([\s\S]*?)<\/title>/i);
  if (titleMatch) title = titleMatch[1].trim();

  const getMeta = (name: string) => {
    const re = new RegExp(
      `<meta\\s+(?:name|property)=["']${name}["']\\s+content=["']([^"']*)["']`,
      'i',
    );
    const m = html.match(re);
    return m ? m[1].trim() : '';
  };

  return {
    title,
    description: getMeta('description'),
    ogTitle: getMeta('og:title'),
    ogDescription: getMeta('og:description'),
  };
}

// ─── Fetch helper ──────────────────────────────────────────────────────────────

interface FetchResult {
  ok: boolean;
  status: number;
  html: string;
  finalUrl: string;
  contentType: string;
}

async function fetchWithTimeout(url: string, timeoutMs = 10_000): Promise<FetchResult> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(url, {
      headers: {
        'User-Agent': 'Mozilla/5.0 (compatible; SoloWorkerBot/1.0)',
        Accept: 'text/html,application/xhtml+xml',
        'Accept-Language': 'en-US,en;q=0.9,zh-CN;q=0.8',
      },
      redirect: 'follow',
      signal: controller.signal,
      next: { revalidate: 300 }, // cache 5 min
    });
    const contentType = res.headers.get('content-type') ?? '';
    const html = contentType.includes('text/') || contentType.includes('xml')
      ? await res.text()
      : '';
    return {
      ok: res.ok,
      status: res.status,
      html,
      finalUrl: res.url || url,
      contentType,
    };
  } finally {
    clearTimeout(timeoutId);
  }
}

// ─── Tool configuration ───────────────────────────────────────────────────────

export const browserAutomateTool: ToolConfig = {
  name: 'browser_automate',
  description:
    'Fetch a web page and extract readable content, links, headings, or tables. ' +
    'Use for competitor research, pricing page extraction, or gathering market data for benchmark reports.',
  input_schema: {
    type: 'object',
    properties: {
      url: { type: 'string', description: 'Full URL to fetch (https://...).' },
      action: {
        type: 'string',
        enum: ['fetch', 'extract', 'research'],
        description:
          "fetch: get readable text. extract: pull specific elements. research: structured summary (title, headings, key text).",
      },
      selector: {
        type: 'string',
        enum: ['headings', 'links', 'tables', 'text', 'meta'],
        description: 'For extract action: which element type to pull.',
      },
      max_chars: {
        type: 'number',
        description: 'Max characters of text to return (200-20000).',
        default: 4000,
      },
    },
    required: ['url'],
  },
  subagent: 'general',
  tags: ['browser', 'research', 'scraping', 'web'],
  modes: ['default', 'qwen', 'casper'],
  async handler(input) {
    const parsed = BrowserAutomateSchema.safeParse(input);
    if (!parsed.success) throw new Error(`Invalid input: ${parsed.error.message}`);
    const { url, action, selector, max_chars } = parsed.data;

    const result = await fetchWithTimeout(url);

    if (!result.ok || !result.html) {
      return {
        toolResult: `Failed to fetch ${url}: HTTP ${result.status} (${result.contentType || 'no content'})`,
        clientSummary: `Fetch failed: ${result.status}`,
      };
    }

    if (action === 'fetch') {
      const text = htmlToReadableText(result.html).slice(0, max_chars);
      return {
        toolResult: `Content from ${result.finalUrl}:\n\n${text}`,
        clientSummary: `Fetched ${url} (${text.length} chars)`,
      };
    }

    if (action === 'extract') {
      switch (selector) {
        case 'headings': {
          const headings = extractHeadings(result.html);
          const lines = headings.map((h) => `${'  '.repeat(h.level - 1)}H${h.level}: ${h.text}`);
          return {
            toolResult: `Headings from ${result.finalUrl}:\n${lines.join('\n') || '(none found)'}`,
            clientSummary: `Extracted ${headings.length} headings`,
          };
        }
        case 'links': {
          const links = extractLinks(result.html);
          const lines = links.map((l) => `- [${l.text}](${l.href})`);
          return {
            toolResult: `Links from ${result.finalUrl}:\n${lines.join('\n') || '(none found)'}`,
            clientSummary: `Extracted ${links.length} links`,
          };
        }
        case 'tables': {
          const tables = extractTables(result.html);
          if (tables.length === 0) {
            return {
              toolResult: `No tables found at ${result.finalUrl}`,
              clientSummary: 'No tables found',
            };
          }
          const parts: string[] = [];
          tables.forEach((table, i) => {
            parts.push(`Table ${i + 1}:`);
            for (const row of table) parts.push(`  | ${row.join(' | ')} |`);
          });
          return {
            toolResult: `Tables from ${result.finalUrl}:\n${parts.join('\n')}`,
            clientSummary: `Extracted ${tables.length} tables`,
          };
        }
        case 'meta': {
          const meta = extractMeta(result.html);
          const lines = [
            `Title: ${meta.title || '(none)'}`,
            `Description: ${meta.description || '(none)'}`,
            `OG Title: ${meta.ogTitle || '(none)'}`,
            `OG Description: ${meta.ogDescription || '(none)'}`,
          ];
          return {
            toolResult: `Meta from ${result.finalUrl}:\n${lines.join('\n')}`,
            clientSummary: 'Extracted page metadata',
          };
        }
        case 'text':
        default: {
          const text = htmlToReadableText(result.html).slice(0, max_chars);
          return {
            toolResult: `Text from ${result.finalUrl}:\n\n${text}`,
            clientSummary: `Extracted ${text.length} chars of text`,
          };
        }
      }
    }

    // action === 'research' — structured summary
    const meta = extractMeta(result.html);
    const headings = extractHeadings(result.html).slice(0, 20);
    const text = htmlToReadableText(result.html).slice(0, max_chars);
    const headingLines = headings.map((h) => `${'  '.repeat(h.level - 1)}- ${h.text}`);

    const parts = [
      `URL: ${result.finalUrl}`,
      `Title: ${meta.title || meta.ogTitle || '(none)'}`,
      `Description: ${meta.description || meta.ogDescription || '(none)'}`,
      ``,
      `Structure:`,
      headingLines.join('\n') || '(no headings)',
      ``,
      `Content:`,
      text,
    ];

    return {
      toolResult: parts.join('\n'),
      clientSummary: `Researched ${url}`,
    };
  },
};

export default browserAutomateTool;
