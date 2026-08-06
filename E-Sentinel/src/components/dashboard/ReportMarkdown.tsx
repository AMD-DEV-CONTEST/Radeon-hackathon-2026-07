import { useMemo } from "react";
import ReactMarkdown from "react-markdown";

// ── Metric extraction ──────────────────────────────────────────

interface MetricItem {
  label: string;
  value: string;
}

const OVERVIEW_HEADING = /^##\s*(月度概览|核心指标|数据概览|整体概览|概览|运营数据)/m;
const METRIC_LINE = /^-\s*(.+?)[：:]\s*(.+)$/;
const MAX_LABEL_LEN = 12; // Only card-ify short labels, not narrative sentences
const MIN_METRIC_COUNT = 2;

function extractMetrics(md: string): { metrics: MetricItem[]; cleanedMd: string } {
  const metrics: MetricItem[] = [];
  const headingMatch = md.match(OVERVIEW_HEADING);
  if (!headingMatch || headingMatch.index === undefined) return { metrics, cleanedMd: md };

  const sectionStart = headingMatch.index;
  const afterHeading = md.slice(sectionStart + headingMatch[0].length);
  const nextHeadingMatch = afterHeading.match(/^##\s/m);
  const sectionEnd = nextHeadingMatch
    ? sectionStart + headingMatch[0].length + (nextHeadingMatch.index ?? 0)
    : md.length;

  const sectionBody = md.slice(sectionStart + headingMatch[0].length, sectionEnd);
  const lines = sectionBody.split("\n");

  for (const line of lines) {
    const m = line.match(METRIC_LINE);
    if (m) {
      const label = m[1].replace(/\*+/g, "").trim(); // strip markdown bold markers
      if (label.length <= MAX_LABEL_LEN) {
        metrics.push({ label, value: m[2].trim() });
        continue;
      }
    }
    // Any non-metric line invalidates the section for card extraction
    if (line.trim() && !line.match(METRIC_LINE)) {
      return { metrics: [], cleanedMd: md };
    }
  }

  if (metrics.length < MIN_METRIC_COUNT) return { metrics: [], cleanedMd: md };

  const cleanedMd = md.slice(0, sectionStart) + md.slice(sectionEnd);
  return { metrics, cleanedMd };
}

// ── Metric cards grid ──────────────────────────────────────────

function MetricCardGrid({ metrics }: { metrics: MetricItem[] }) {
  if (metrics.length === 0) return null;
  return (
    <div className="grid grid-cols-2 gap-3 mb-6">
      {metrics.map((m) => (
        <div
          key={m.label}
          className="rounded-xl border border-border bg-white px-4 py-3.5 shadow-sm"
        >
          <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground/50 mb-1">
            {m.label}
          </p>
          <p className="text-2xl font-bold text-blue-600 tabular-nums">
            {m.value}
          </p>
        </div>
      ))}
    </div>
  );
}

// ── Main component ─────────────────────────────────────────────

export default function ReportMarkdown({ content }: { content: string }) {
  const cleanContent = content.replace(/\\n/g, "\n");
  const { metrics, cleanedMd } = useMemo(() => extractMetrics(cleanContent), [cleanContent]);

  return (
    <article className="max-w-none">
      <MetricCardGrid metrics={metrics} />

      <ReactMarkdown
        components={{
          h1: ({ children, ...props }) => (
            <h1
              className="text-xl font-bold text-foreground mt-8 mb-5 pb-2 border-b border-border"
              {...props}
            >
              {children}
            </h1>
          ),
          h2: ({ children, ...props }) => (
            <h2
              className="text-base font-semibold text-foreground mt-7 mb-3 pl-3 py-1 border-l-[3px] border-blue-500"
              {...props}
            >
              {children}
            </h2>
          ),
          h3: ({ children, ...props }) => (
            <h3
              className="text-sm font-semibold text-foreground/70 mt-5 mb-2"
              {...props}
            >
              {children}
            </h3>
          ),
          p: ({ children, ...props }) => (
            <p
              className="text-sm text-muted-foreground leading-relaxed mb-3"
              style={{ lineHeight: "1.7" }}
              {...props}
            >
              {children}
            </p>
          ),
          strong: ({ children, ...props }) => (
            <strong className="font-semibold text-foreground" {...props}>
              {children}
            </strong>
          ),
          ul: ({ children, ...props }) => (
            <ul className="space-y-1.5 my-3 pl-1" {...props}>
              {children}
            </ul>
          ),
          ol: ({ children, ...props }) => (
            <ol className="space-y-1.5 my-3 pl-1 list-decimal list-inside" {...props}>
              {children}
            </ol>
          ),
          li: ({ children, ...props }) => (
            <li
              className="text-sm text-muted-foreground leading-relaxed pl-4 relative before:content-['•'] before:absolute before:left-0 before:text-muted-foreground/20 before:font-bold"
              style={{ lineHeight: "1.7" }}
              {...props}
            >
              {children}
            </li>
          ),
          table: ({ children, ...props }) => (
            <div className="overflow-x-auto my-4 rounded-lg border border-border">
              <table className="w-full text-xs" {...props}>
                {children}
              </table>
            </div>
          ),
          thead: ({ children, ...props }) => (
            <thead className="bg-muted/50" {...props}>
              {children}
            </thead>
          ),
          th: ({ children, ...props }) => (
            <th
              className="text-left font-medium text-foreground/70 px-3 py-2 border-b border-border"
              {...props}
            >
              {children}
            </th>
          ),
          td: ({ children, ...props }) => (
            <td
              className="text-muted-foreground px-3 py-2 border-b border-muted"
              {...props}
            >
              {children}
            </td>
          ),
          tr: ({ children, ...props }) => (
            <tr className="hover:bg-muted/50/50 transition-colors" {...props}>
              {children}
            </tr>
          ),
        }}
      >
        {cleanedMd}
      </ReactMarkdown>
    </article>
  );
}
