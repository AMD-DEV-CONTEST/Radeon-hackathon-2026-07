import { useState, useEffect, useRef, useMemo, type ReactNode } from "react";
import Box from "@mui/material/Box";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Chip from "@mui/material/Chip";
import Typography from "@mui/material/Typography";
import Tooltip from "@mui/material/Tooltip";
import { Info } from "../components/Info";

export interface ArticleDetailArticle {
  id: string;
  type: string;
  content: string;
  payload?: Record<string, unknown>;
  trust_score?: number | null;
  cites?: string[];
  agent_signature?: string | null;
  org_signature?: string | null;
  src_org?: string;
  provenance_children?: { id: string; content: string }[];
}

export interface ArticleDetailProps {
  articleId: string;
  article?: ArticleDetailArticle | null;
  fetchArticle: (id: string) => Promise<ArticleDetailArticle>;
  onNavigate?: (path: string) => void;
}

const ORG_LABELS: Record<string, string> = {
  "did:percq:org:soc-alpha": "SOC Alpha",
  "did:percq:org:soc-beta": "SOC Beta",
};

const IOC_RE = /\b(?:[0-9a-f]{32,64}|CVE-\d{4}-\d{4,}|T\d{4}(?:\.\d{3})?|\d{1,3}(?:\.\d{1,3}){3})\b/gi;

function CopyChip({ text, label }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <Tooltip title={copied ? "copied ✓" : "click to copy"} arrow>
      <Typography
        component="span"
        onClick={() => { navigator.clipboard.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 1500); }}
        sx={{
          fontFamily: '"IBM Plex Mono", monospace', fontSize: "0.6875rem", color: "#c2cbda",
          px: 0.75, py: 0.25, borderRadius: "var(--r-sm, 6px)",
          border: "1px solid rgba(150,170,200,.16)",
          bgcolor: "rgba(255,255,255,.02)",
          textDecoration: "underline dotted rgba(150,170,200,.3)",
          textUnderlineOffset: 3,
          cursor: "copy", display: "inline-block",
          transition: "all 0.14s cubic-bezier(.22,.61,.36,1)",
          "&:hover": { borderColor: "rgba(150,170,200,.3)", color: "#eef2f8" },
        }}
      >
        {label || text.length > 16 ? `${text.slice(0, 8)}…${text.slice(-4)}` : text}
      </Typography>
    </Tooltip>
  );
}

function IOCRenderer({ src }: { src: string }) {
  const parts: ReactNode[] = [];
  const segments = src.split(/(\*\*[^*]+\*\*|`[^`]+`)/g);
  segments.forEach((seg, i) => {
    if (seg.startsWith("**") && seg.endsWith("**")) {
      parts.push(<strong key={i} style={{ color: "#eef2f8", fontWeight: 600 }}>{seg.slice(2, -2)}</strong>);
    } else if (seg.startsWith("`") && seg.endsWith("`")) {
      const inner = seg.slice(1, -1);
      parts.push(<CopyChip key={i} text={inner} />);
    } else {
      const spans: ReactNode[] = [];
      let last = 0;
      IOC_RE.lastIndex = 0;
      let m: RegExpExecArray | null;
      while ((m = IOC_RE.exec(seg)) !== null) {
        if (m.index > last) spans.push(<span key={`${i}-${last}`}>{seg.slice(last, m.index)}</span>);
        spans.push(<CopyChip key={`${i}-${m.index}`} text={m[0]} />);
        last = m.index + m[0].length;
      }
      if (last < seg.length) spans.push(<span key={`${i}-${last}`}>{seg.slice(last)}</span>);
      parts.push(...spans);
    }
  });
  return <>{parts}</>;
}

function extractIndicators(text: string) {
  const hashes: string[] = [];
  const tcodes: string[] = [];
  IOC_RE.lastIndex = 0;
  let m: RegExpExecArray | null;
  while ((m = IOC_RE.exec(text)) !== null) {
    const v = m[0];
    if (/^[0-9a-f]{32,64}$/i.test(v)) hashes.push(v);
    else if (/^T\d/.test(v)) tcodes.push(v);
  }
  return { hashes: [...new Set(hashes)], tcodes: [...new Set(tcodes)] };
}

function useScrollProgress(ref: React.RefObject<HTMLDivElement | null>) {
  const [pct, setPct] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const handler = () => {
      const { scrollTop, scrollHeight, clientHeight } = el;
      setPct(scrollHeight > clientHeight ? (scrollTop / (scrollHeight - clientHeight)) * 100 : 100);
    };
    el.addEventListener("scroll", handler, { passive: true });
    handler();
    return () => el.removeEventListener("scroll", handler);
  }, [ref]);
  return pct;
}

function MetaField({ label, children, mono }: { label: string; children: React.ReactNode; mono?: boolean }) {
  return (
    <Box sx={{ display: "flex", flexDirection: "column", gap: "4px", minWidth: 96 }}>
      <Typography sx={{ fontFamily: '"IBM Plex Mono", monospace', fontWeight: 500, fontSize: "0.59375rem", letterSpacing: "0.16em", textTransform: "uppercase", color: "#8a94a8" }}>
        {label}
      </Typography>
      <Box sx={{ fontFamily: mono ? '"IBM Plex Mono", monospace' : '"IBM Plex Sans", sans-serif', fontSize: mono ? "0.75rem" : "0.8125rem", fontWeight: 500, color: "#eef2f8", display: "flex", alignItems: "center", gap: 0.5 }}>
        {children}
      </Box>
    </Box>
  );
}

export function ArticleDetail({ articleId, article: initialArticle, fetchArticle, onNavigate }: ArticleDetailProps) {
  const [article, setArticle] = useState<ArticleDetailArticle | null>(initialArticle || null);
  useEffect(() => {
    if (initialArticle) return;
    let alive = true;
    fetchArticle(articleId).then(a => { if (alive) setArticle(a); });
    return () => { alive = false; };
  }, [articleId, fetchArticle, initialArticle]);
  useEffect(() => {
    if (initialArticle) setArticle(initialArticle);
  }, [initialArticle]);

  const scrollRef = useRef<HTMLDivElement>(null);
  const readPct = useScrollProgress(scrollRef);
  const content = article?.content || "";
  const indicators = useMemo(() => extractIndicators(content), [content]);

  if (!article) return <Typography sx={{ color: "#8a94a8", p: 4 }}>Loading...</Typography>;
  if (!article.content || article.content === article.id) return <Typography sx={{ color: "#8a94a8", p: 4 }}>Loading article data...</Typography>;

  const orgLabel = ORG_LABELS[article.src_org || ""] || "";
  const isUnranked = article.trust_score === null || article.trust_score === undefined || article.trust_score === 0;
  const trustVal = article.trust_score ?? 0;
  const trustColor = trustVal > 0.7 ? "#3ddc97" : trustVal > 0.4 ? "#f5a524" : "#ff5d73";
  const sourceIds = (article.payload as Record<string, unknown>)?.source_article_ids as string[] | undefined;
  const rawPayload = JSON.stringify(article.payload, null, 2);

  const bodySections = article.content.split(/(?=\*\*)/g);
  const firstLine = bodySections[0]?.replace(/\*\*/g, "") || "";
  const restBody = bodySections.slice(1).join("");

  return (
    <Box sx={{ maxWidth: 1200, mx: "auto" }}>
      {/* Breadcrumb */}
      <Box sx={{ display: "flex", alignItems: "center", gap: 1, py: 1, fontFamily: '"IBM Plex Mono", monospace', fontSize: "0.6875rem", color: "#8a94a8" }}>
        <Box component="a" onClick={() => onNavigate?.("/feed")} sx={{ color: "#8a94a8", cursor: "pointer", "&:hover": { color: "#34d6c8" } }}>
          Article Feed
        </Box>
        <span>›</span>
        <span>{article.type}</span>
        <span>›</span>
        <span>{article.id.slice(0, 8)}…{article.id.slice(-4)}</span>
        <Box sx={{ flex: 1 }} />
        <Box component="a" onClick={() => onNavigate?.("/feed")} sx={{ color: "#8a94a8", cursor: "pointer", "&:hover": { color: "#34d6c8" } }}>
          ‹ back
        </Box>
      </Box>

      {/* Header band */}
      <Box sx={{ py: "18px 0 16px", borderBottom: "1px solid rgba(150,170,200,.08)", mb: 0 }}>
        <Box sx={{ display: "flex", alignItems: "baseline", gap: 1.5, mb: 1.5 }}>
          <Chip
            label={article.type}
            size="small"
            sx={{
              height: 22, fontSize: "0.6875rem", fontWeight: 600,
              color: article.type === "finding" ? "#ff5d73" : article.type === "insight" ? "#9b7bff" : "#8a94a8",
              bgcolor: article.type === "finding" ? "rgba(255,93,115,.12)" : article.type === "insight" ? "rgba(155,123,255,.12)" : "rgba(150,170,200,.08)",
              "& .MuiChip-label": { px: 1 },
            }}
          />
          <Info k={article.type as any} />
          <Typography sx={{ fontFamily: '"Space Grotesk", sans-serif', fontWeight: 600, fontSize: "1.5rem", letterSpacing: "-0.02em", color: "#eef2f8", lineHeight: 1.2 }}>
            {article.content.replace(/\*\*/g, "").split(/[.!\n]/)[0]}
          </Typography>
        </Box>

        <Box sx={{ display: "flex", flexWrap: "wrap", gap: "22px 30px" }}>
          <MetaField label="Type">
            <Typography sx={{ textTransform: "capitalize", fontSize: "0.8125rem", fontWeight: 500, color: "#eef2f8" }}>{article.type}</Typography>
          </MetaField>
          {orgLabel && (
            <MetaField label="Org">
              <Box sx={{ display: "flex", alignItems: "center", gap: 0.5 }}>
                <Box sx={{ width: 6, height: 6, borderRadius: "50%", bgcolor: article.src_org?.includes("beta") ? "#f5a524" : "#5b8cff" }} />
                <Typography sx={{ fontSize: "0.8125rem", color: "#eef2f8" }}>{orgLabel}</Typography>
              </Box>
            </MetaField>
          )}
          <MetaField label="Trust">
            <Box sx={{ display: "flex", alignItems: "center", gap: 0.5 }}>
              <Box sx={{ width: 48, height: 3, borderRadius: 1.5, bgcolor: "rgba(150,170,200,.16)", overflow: "hidden" }}>
                <Box sx={{
                  width: isUnranked ? "100%" : `${trustVal * 100}%`,
                  height: "100%",
                  bgcolor: isUnranked ? "transparent" : trustColor,
                  borderRadius: 1.5,
                  border: isUnranked ? "1px dashed rgba(150,170,200,.4)" : "none",
                  opacity: isUnranked ? 0.5 : 1,
                }} />
              </Box>
              <Typography sx={{ fontSize: "0.75rem", color: "#8a94a8", fontFamily: '"IBM Plex Mono", monospace' }}>
                {isUnranked ? "unranked" : (trustVal * 100).toFixed(0) + "%"}
              </Typography>
              <Info k="unranked" />
            </Box>
          </MetaField>
          <MetaField label="ID" mono>
            <Typography sx={{ fontSize: "0.75rem", color: "#c2cbda", fontFamily: '"IBM Plex Mono", monospace' }}>
              {article.id.slice(0, 8)}…{article.id.slice(-4)}
            </Typography>
          </MetaField>
          {article.agent_signature && (
            <MetaField label="Agent" mono>
              <Typography sx={{ fontSize: "0.75rem", color: "#c2cbda" }}>{article.agent_signature.slice(0, 12)}…</Typography>
            </MetaField>
          )}
        </Box>
      </Box>

      {/* Body + Rail */}
      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: { xs: "1fr", lg: "minmax(0, 1fr) 320px" },
          gap: { xs: 0, lg: "34px" },
          pt: "22px",
          alignItems: "start",
        }}
      >
        {/* Reading column */}
        <Box ref={scrollRef} sx={{ maxWidth: "70ch", position: "relative", overflow: "auto" }}>
          <Box sx={{ position: "sticky", top: 0, height: 2, bgcolor: "rgba(150,170,200,.08)", borderRadius: 1, mb: 2, overflow: "hidden" }}>
            <Box sx={{ width: `${readPct}%`, height: "100%", bgcolor: "#34d6c8", transition: "width 80ms linear" }} />
          </Box>
          <Box sx={{ borderLeft: "2px solid #34d6c8", p: "10px 14px", mb: 2, bgcolor: "rgba(52,214,200,.07)", borderRadius: "0 var(--r-sm, 6px) var(--r-sm, 6px) 0", fontSize: "0.84375rem", fontWeight: 500, lineHeight: 1.5, color: "#eef2f8" }}>
            <IOCRenderer src={firstLine} />
          </Box>
          <Box sx={{ "& p": { fontFamily: '"IBM Plex Sans", sans-serif', fontWeight: 400, fontSize: "0.9375rem", lineHeight: 1.68, color: "#c2cbda", mb: "14px" } }}>
            <IOCRenderer src={restBody || article.content} />
          </Box>
        </Box>

        {/* Right rail */}
        <Box sx={{ display: "flex", flexDirection: "column", gap: 1.5, position: { lg: "sticky" }, top: { lg: 18 } }}>
          {indicators.hashes.length > 0 && (
            <Box sx={{ p: "14px 15px", border: "1px solid rgba(150,170,200,.08)", borderRadius: "var(--r-md, 10px)", bgcolor: "var(--bg-panel, #161c26)" }}>
              <Box sx={{ display: "flex", alignItems: "center", gap: 1, mb: 1.5, fontFamily: '"IBM Plex Mono", monospace', fontSize: "0.625rem", letterSpacing: "0.16em", textTransform: "uppercase", color: "#8a94a8" }}>
                Extracted indicators <Info k="hash" />
              </Box>
              <Box sx={{ display: "flex", flexWrap: "wrap", gap: "6px" }}>
                {indicators.hashes.map(h => <CopyChip key={h} text={h} />)}
                {indicators.tcodes.map(t => <CopyChip key={t} text={t} />)}
              </Box>
            </Box>
          )}

          {article.cites && article.cites.length > 0 && (
            <Box sx={{ p: "14px 15px", border: "1px solid rgba(150,170,200,.08)", borderRadius: "var(--r-md, 10px)", bgcolor: "var(--bg-panel, #161c26)" }}>
              <Box sx={{ display: "flex", alignItems: "center", gap: 1, mb: 1.5, fontFamily: '"IBM Plex Mono", monospace', fontSize: "0.625rem", letterSpacing: "0.16em", textTransform: "uppercase", color: "#8a94a8" }}>
                Provenance ({article.cites.length} sources) <Info k="provenance" />
              </Box>
              <Box sx={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                {article.cites.map(cid => (
                  <Box key={cid} onClick={() => onNavigate?.(`/article/${cid}`)} sx={{ display: "flex", alignItems: "center", gap: 1, cursor: "pointer", borderRadius: "var(--r-sm, 6px)", px: 0.5, py: 0.25, mx: -0.5, transition: "all 0.14s ease", "&:hover": { bgcolor: "rgba(255,255,255,.03)", transform: "translateX(2px)" } }}>
                    <Typography sx={{ fontFamily: '"IBM Plex Mono", monospace', fontSize: "0.6875rem", color: "#c2cbda" }}>
                      src · {cid.slice(0, 8)}…{cid.slice(-4)}
                    </Typography>
                    <Typography sx={{ fontFamily: '"IBM Plex Mono", monospace', fontSize: "0.625rem", color: "#8a94a8", ml: "auto" }}>↗</Typography>
                  </Box>
                ))}
              </Box>
            </Box>
          )}

          <Box sx={{ p: "14px 15px", border: "1px solid rgba(150,170,200,.08)", borderRadius: "var(--r-md, 10px)", bgcolor: "var(--bg-panel, #161c26)" }}>
            <Box component="details">
              <Box component="summary" sx={{ fontFamily: '"IBM Plex Mono", monospace', fontSize: "0.625rem", letterSpacing: "0.16em", textTransform: "uppercase", color: "#8a94a8", cursor: "pointer", display: "flex", alignItems: "center", gap: 1, "&:hover": { color: "#c2cbda" } }}>
                Raw tool payload <Info k="payload" />
              </Box>
              <Box component="pre" sx={{ mt: 1.5, p: 1.5, borderRadius: "var(--r-sm, 6px)", bgcolor: "rgba(150,170,200,.04)", border: "1px solid rgba(150,170,200,.08)", overflow: "auto", fontSize: "0.6875rem", fontFamily: '"IBM Plex Mono", monospace', color: "#c2cbda", lineHeight: 1.5 }}>
                {rawPayload}
              </Box>
            </Box>
          </Box>
        </Box>
      </Box>
    </Box>
  );
}
