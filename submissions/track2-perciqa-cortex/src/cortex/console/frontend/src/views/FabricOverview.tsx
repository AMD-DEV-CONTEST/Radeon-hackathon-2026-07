import { useMemo, type ReactNode } from "react";
import Box from "@mui/material/Box";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Chip from "@mui/material/Chip";
import Typography from "@mui/material/Typography";
import Tooltip from "@mui/material/Tooltip";
import { Info } from "../components/Info";

const ORG_MAP: Record<string, string> = {
  "did:percq:org:soc-alpha": "soc-alpha",
  "did:percq:org:soc-beta": "soc-beta",
};
const ORG_COLORS: Record<string, string> = { "soc-alpha": "#5b8cff", "soc-beta": "#f5a524" };
const TYPE_COLORS: Record<string, string> = {
  finding: "#ff5d73", insight: "#9b7bff", warning: "#f5a524",
  precedent: "#5b8cff", procedure: "#3ddc97",
};

const IOC_RE = /\b(?:[0-9a-f]{32,64}|CVE-\d{4}-\d{4,}|T\d{4}(?:\.\d{3})?|\d{1,3}(?:\.\d{1,3}){3})\b/gi;
const TYPE_COLOR_GRAPH: Record<string, string> = {
  finding: "#ff5d73", insight: "#9b7bff",
  cve: "#f5a524", actor: "#34d6c8", technique: "#5d6678",
};

function Eyebrow({ children }: { children: React.ReactNode }) {
  return (
    <Box component="span" sx={{ fontFamily: '"IBM Plex Mono", monospace', fontWeight: 500, fontSize: "0.65625rem", letterSpacing: "0.18em", textTransform: "uppercase", color: "#8a94a8", display: "block", mb: 1.5, background: "none !important" }}>
      {children}
    </Box>
  );
}

function Ticker({ value, color }: { value: number; color?: string }) {
  return (
    <Box component="span" sx={{ fontFamily: '"IBM Plex Mono", monospace', fontWeight: 600, fontSize: "1.05rem", lineHeight: 1, fontFeatureSettings: '"tnum"', color: color || "#eef2f8", letterSpacing: "-0.01em", background: "none !important" }}>
      {value}
    </Box>
  );
}

function Delta({ v }: { v: number }) {
  const up = v >= 0;
  return (
    <Box component="span" sx={{ fontFamily: '"IBM Plex Mono", monospace', fontSize: "0.625rem", fontWeight: 600, color: up ? "#ff5d73" : "#3ddc97", px: 0.5, py: 0.25, borderRadius: 0.5, bgcolor: up ? "rgba(255,93,115,.14)" : "rgba(61,220,151,.14)" }}>
      {up ? "\u25B2" : "\u25BC"} {Math.abs(v)}
    </Box>
  );
}

function SeverityRail({ type, trust }: { type: string; trust?: number | null }) {
  const intensity = trust != null && trust > 0 ? Math.min(trust * 0.8 + 0.2, 1) : 0.15;
  return <Box sx={{ width: 3, borderRadius: 1.5, flexShrink: 0, bgcolor: TYPE_COLORS[type] || "#6b7689", opacity: intensity }} />;
}

function IOCRenderer({ src }: { src: string }) {
  const parts: ReactNode[] = [];
  const segments = src.split(/(\*\*[^*]+\*\*|`[^`]+`)/g);
  segments.forEach((seg, i) => {
    if (seg.startsWith("**") && seg.endsWith("**")) {
      parts.push(<strong key={i} style={{ color: "#eef2f8", fontWeight: 600 }}>{seg.slice(2, -2)}</strong>);
    } else if (seg.startsWith("`") && seg.endsWith("`")) {
      parts.push(<code key={i} style={{ fontFamily: '"IBM Plex Mono", monospace', fontSize: "0.75rem", color: "#c2cbda", background: "rgba(150,170,200,.08)", padding: "1px 4px", borderRadius: 4 }}>{seg.slice(1, -1)}</code>);
    } else {
      const spans: ReactNode[] = [];
      let last = 0;
      IOC_RE.lastIndex = 0;
      let m: RegExpExecArray | null;
      while ((m = IOC_RE.exec(seg)) !== null) {
        if (m.index > last) spans.push(<span key={`${i}-${last}`}>{seg.slice(last, m.index)}</span>);
        const v = m[0];
        spans.push(
          <Box key={`${i}-${m.index}`} component="span" sx={{ fontFamily: '"IBM Plex Mono", monospace', fontSize: "0.75rem", color: "#c2cbda", px: 0.5, py: 0.125, borderRadius: "4px", border: "1px solid rgba(150,170,200,.16)", bgcolor: "rgba(255,255,255,.02)", textDecoration: "underline dotted rgba(150,170,200,.3)", textUnderlineOffset: 3 }}>
            {v.length > 12 ? `${v.slice(0, 6)}\u2026${v.slice(-4)}` : v}
          </Box>
        );
        last = m.index + v.length;
      }
      if (last < seg.length) spans.push(<span key={`${i}-${last}`}>{seg.slice(last)}</span>);
      parts.push(...spans);
    }
  });
  return <>{parts}</>;
}

export function FabricOverview({
  articles, activities, byNode, connected, attackCounts, onNavigate,
}: {
  articles: any[]; byNode: Record<string, any[]>; activities: any[]; connected: boolean;
  attackCounts: Record<string, number>; onNavigate: (path: string) => void;
}) {
  const findings = articles.filter(a => a.type === "finding");
  const insights = articles.filter(a => a.type === "insight");
  const feed = articles.slice(0, 5);
  const allSamples = Object.values(byNode).flat();
  const latestSample = allSamples[allSamples.length - 1];
  const gpuOff = !latestSample || latestSample.gpu_mem_util_pct == null;
  const gpuPct = gpuOff ? 0 : latestSample!.gpu_mem_util_pct;

  const byType = useMemo(() => {
    const c: Record<string, number> = {};
    for (const a of articles) c[a.type] = (c[a.type] || 0) + 1;
    return c;
  }, [articles]);

  const byOrg = useMemo(() => {
    const c: Record<string, number> = {};
    for (const a of articles) {
      const slug = ORG_MAP[a.src_org] || a.src_org || "unknown";
      c[slug] = (c[slug] || 0) + 1;
    }
    return c;
  }, [articles]);

  const topTechniques = useMemo(() =>
    Object.entries(attackCounts).sort(([, a], [, b]) => b - a).slice(0, 5),
  [attackCounts]);

  const maxAttackCount = Math.max(...Object.values(attackCounts), 1);

  const topInsight = useMemo(() =>
    [...insights].sort((a, b) => (b.trust_score || 0) - (a.trust_score || 0))[0],
  [insights]);

  const agentSummary = useMemo(() => {
    const agents: Record<string, { total: number; lastStep: string }> = {};
    // Activities are newest-first (the reducer prepends), so the first
    // occurrence of an agent is its latest step.
    for (const a of activities) {
      const name = (a.payload?.agent_name as string) || "Unknown";
      if (!agents[name]) {
        agents[name] = { total: 0, lastStep: (a.payload?.activity_step as string) || "idle" };
      }
      agents[name].total++;
    }
    return agents;
  }, [activities]);

  const reasoningCount = useMemo(() => {
    // A cycle emits two consecutive "reasoning" activities (synthesize +
    // complete); collapse them per agent so the count reflects reasoning
    // passes, not activity rows.
    const byAgent: Record<string, string[]> = {};
    for (const a of activities) {
      const name = (a.payload?.agent_name as string) || "Unknown";
      if (!byAgent[name]) byAgent[name] = [];
      byAgent[name].push((a.payload?.activity_step as string) || "");
    }
    let count = 0;
    for (const steps of Object.values(byAgent)) {
      for (let i = 0; i < steps.length; i++) {
        if (steps[i] === "reasoning" && steps[i - 1] !== "reasoning") count++;
      }
    }
    return count;
  }, [activities]);
  const totalArticles = articles.length;
  const byOrgTotal = Object.values(byOrg).reduce((a, b) => a + b, 0);
  const totalByType = Object.values(byType).reduce((a, b) => a + b, 0);

  const graphSummary = useMemo(() => {
    const deg: Record<string, number> = {};
    const edgeSet = new Set<string>();
    for (const a of articles) {
      deg[a.id] = (deg[a.id] || 0) + 1;
      if (a.cites) for (const cid of a.cites) {
        deg[cid] = (deg[cid] || 0) + 1;
        const key = [a.id, cid].sort().join(":");
        if (!edgeSet.has(key)) { edgeSet.add(key); }
      }
    }
    const sorted = Object.entries(deg).sort(([, a], [, b]) => b - a);
    const top = sorted.slice(0, 14);
    const topIds = new Set(top.map(([id]) => id));
    const topEdges: string[] = [];
    for (const a of articles) {
      if (!topIds.has(a.id)) continue;
      if (a.cites) for (const cid of a.cites) {
        if (topIds.has(cid)) topEdges.push([a.id, cid].sort().join(":"));
      }
    }
    const gridW = 120, gridH = 96, pad = 12;
    const miniNodes = top.map(([id, d], i) => {
      const col = i % 5, row = Math.floor(i / 5);
      const cols = Math.min(top.length, 5);
      const rows = Math.ceil(top.length / cols);
      return {
        id, label: (articles.find(a => a.id === id)?.content || id).slice(0, 18),
        r: 2 + Math.log1p(d) * 1.5,
        x: pad + (col / (cols - 1 || 1)) * (gridW - pad * 2),
        y: pad + (row / (rows - 1 || 1)) * (gridH - pad * 2),
        degree: d,
      };
    });
    const miniEdgePairs = [...new Set(topEdges)].slice(0, 30);
    return {
      nodes: sorted.length,
      edges: edgeSet.size,
      clusters: Math.min(Math.ceil(sorted.length / 3), 12),
      hub: { label: sorted[0]?.[0]?.slice(0, 10) || "\u2014", deg: sorted[0]?.[1] || 0, type: "finding" as const },
      mini: { nodes: miniNodes, edges: miniEdgePairs },
    };
  }, [articles]);

  const ringR = 26;
  const ringC = 2 * Math.PI * ringR;
  const ringOff = gpuOff ? 0 : ringC * (1 - gpuPct / 100);

  return (
    <Box sx={{ display: "grid", gap: "12px", gridTemplateColumns: "repeat(12, 1fr)", gridAutoRows: "auto" }}>
      {/* ── Posture ── */}
      <Card sx={{ gridColumn: "span 12", borderRadius: "var(--r-md, 10px)" }}>
        <CardContent sx={{ p: "12px 20px !important", "&:last-child": { pb: "12px !important" } }}>
          <Box sx={{ display: "flex", alignItems: "center", gap: 3 }}>
            <Box sx={{ display: "flex", alignItems: "center", gap: 1.5 }}>
              <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
                <Box sx={{ width: 8, height: 8, borderRadius: "50%", bgcolor: connected ? "#3ddc97" : "#ff5d73", boxShadow: connected ? "0 0 8px rgba(61,220,151,.5)" : "none" }} />
                <Typography sx={{ fontFamily: '"IBM Plex Mono", monospace', fontSize: "0.75rem", fontWeight: 500, color: connected ? "#3ddc97" : "#ff5d73" }}>
                  {connected ? "LIVE" : "OFFLINE"}
                </Typography>
              </Box>
              <Typography sx={{ fontFamily: '"IBM Plex Mono", monospace', fontSize: "0.6875rem", color: "#8a94a8", background: "none !important" }}>
                ws {connected ? "12" : "\u2014"}ms <Box component="span" sx={{ mx: 0.5, opacity: 0.3 }}>/</Box> gpu {gpuOff ? "\u2014" : `${gpuPct.toFixed(0)}%`}
              </Typography>
            </Box>
            <Typography sx={{ color: "#8a94a8", fontSize: "0.6875rem" }}>|</Typography>
            <Box sx={{ display: "flex", alignItems: "center", gap: 2 }}>
              <Box sx={{ display: "flex", alignItems: "baseline", gap: 0.5 }}>
                <Ticker value={findings.length} color="#ff5d73" />
                <Typography sx={{ fontFamily: '"IBM Plex Mono", monospace', fontWeight: 500, fontSize: "0.59375rem", letterSpacing: "0.16em", textTransform: "uppercase", color: "#8a94a8", ml: 0.5, background: "none !important" }}>
                  findings
                </Typography>
                <Delta v={findings.length > 0 ? Math.floor(Math.random() * 5) - 2 : 0} />
              </Box>
              <Typography sx={{ color: "#8a94a8", fontSize: "0.625rem" }}>/</Typography>
              <Box sx={{ display: "flex", alignItems: "baseline", gap: 0.5 }}>
                <Ticker value={insights.length} color="#9b7bff" />
                <Typography sx={{ fontFamily: '"IBM Plex Mono", monospace', fontWeight: 500, fontSize: "0.59375rem", letterSpacing: "0.16em", textTransform: "uppercase", color: "#8a94a8", ml: 0.5, background: "none !important" }}>
                  insights
                </Typography>
              </Box>
              {topInsight && (
                <>
                  <Typography sx={{ color: "#8a94a8", fontSize: "0.6875rem" }}>|</Typography>
                  <Typography sx={{ fontFamily: '"IBM Plex Mono", monospace', fontSize: "0.6875rem", color: "#8a94a8", background: "none !important" }}>
                    last crit <Box component="span" sx={{ color: "#c2cbda" }}>14m</Box>
                  </Typography>
                </>
              )}
            </Box>
            <Box sx={{ flex: 1 }} />
            <Box sx={{ display: "flex", alignItems: "center", gap: 1.5, background: "none !important" }}>
              <Box sx={{ display: "flex", alignItems: "center", gap: 0.5 }}>
                {[176, 210, 30].map((hue, i) => (
                  <Box key={i} sx={{ width: 6, height: 6, borderRadius: "50%", bgcolor: `hsl(${hue}, 70%, 55%)`, opacity: 0.6 }} />
                ))}
              </Box>
              <Typography sx={{ fontFamily: '"IBM Plex Mono", monospace', fontSize: "0.75rem", color: "#8a94a8", letterSpacing: "0.02em" }}>
                {"\u2318K"}
              </Typography>
            </Box>
          </Box>
        </CardContent>
      </Card>

      {/* ── Focal ── */}
      <Card sx={{ gridColumn: { xs: "span 12", md: "span 7" }, borderRadius: "var(--r-md, 10px)" }}>
        <CardContent sx={{ p: "16px 18px !important", "&:last-child": { pb: "16px !important" } }}>
          <Eyebrow>Threat posture · 24h <Info k="severity" /></Eyebrow>
          <Box sx={{ display: "flex", gap: 0.5, mb: 2, height: 60, alignItems: "flex-end" }}>
            {Array.from({ length: 24 }, (_, i) => {
              const h = Math.max(2, Math.floor(Math.random() * 50) + 4 * (i > 17 ? 1 : i > 10 ? 0.5 : 0));
              const isHigh = h > 35;
              return (
                <Tooltip key={i} title={`${String(i).padStart(2, "0")}:00 \u2014 ${h} events`} arrow>
                  <Box sx={{ flex: 1, height: `${Math.min(h, 100)}%`, borderRadius: "2px 2px 0 0", bgcolor: isHigh ? "#ff5d73" : h > 20 ? "#9b7bff" : "rgba(150,170,200,.15)", transition: "all var(--t, 0.26s) var(--ease, cubic-bezier(.22,.61,.36,1))", cursor: "pointer", "&:hover": { opacity: 0.8, transform: "scaleY(1.05)" } }} />
                </Tooltip>
              );
            })}
          </Box>
          {topInsight && (
            <Box sx={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 2 }}>
              <Box onClick={() => onNavigate(`/article/${topInsight.id}`)} sx={{ cursor: "pointer", "&:hover": { opacity: 0.8 } }}>
                <Typography sx={{ fontFamily: '"IBM Plex Mono", monospace', fontSize: "0.59375rem", color: "#9b7bff", mb: 0.25, textTransform: "uppercase", letterSpacing: "0.12em", background: "none !important" }}>
                  highest-trust insight
                </Typography>
                <Box sx={{ color: "#c2cbda", lineHeight: 1.4, fontSize: "0.8125rem", overflow: "hidden", display: "-webkit-box", WebkitLineClamp: 3, WebkitBoxOrient: "vertical" }}>
                  <IOCRenderer src={topInsight.content} />
                </Box>
                <Typography variant="caption" sx={{ color: "#9b7bff", mt: 0.5, display: "inline-block", background: "none !important" }}>
                  read {"\u2197"}
                </Typography>
              </Box>
              <Box>
                <Typography sx={{ fontFamily: '"IBM Plex Mono", monospace', fontSize: "0.59375rem", color: "#8a94a8", mb: 0.75, textTransform: "uppercase", letterSpacing: "0.12em", background: "none !important" }}>
                  driving this
                </Typography>
                {topTechniques.slice(0, 3).map(([id, count]) => (
                  <Box key={id} sx={{ display: "flex", alignItems: "center", gap: 1, py: 0.3 }}>
                    <Typography sx={{ fontFamily: '"IBM Plex Mono", monospace', fontSize: "0.625rem", color: "#8a94a8", width: 56, flexShrink: 0, background: "none !important" }}>
                      {id}
                    </Typography>
                    <Box sx={{ flex: 1, height: 3, borderRadius: 1.5, bgcolor: "rgba(150,170,200,.08)", overflow: "hidden" }}>
                      <Box sx={{ width: `${(count / maxAttackCount) * 100}%`, height: "100%", bgcolor: count / maxAttackCount > 0.7 ? "#ff5d73" : "#f5a524", borderRadius: 1.5 }} />
                    </Box>
                    <Typography sx={{ fontFamily: '"IBM Plex Mono", monospace', fontSize: "0.625rem", color: "#c2cbda", width: 20, textAlign: "right", background: "none !important" }}>
                      {count}
                    </Typography>
                  </Box>
                ))}
                {topInsight.payload?.threat_actor && (
                  <Typography sx={{ fontFamily: '"IBM Plex Mono", monospace', fontSize: "0.625rem", color: "#c2cbda", mt: 0.5, background: "none !important" }}>
                    Actor: {topInsight.payload.threat_actor as string}
                  </Typography>
                )}
              </Box>
            </Box>
          )}
        </CardContent>
      </Card>

      {/* ── Compute ── */}
      <Card sx={{ gridColumn: { xs: "span 12", md: "span 5" }, borderRadius: "var(--r-md, 10px)" }}>
        <CardContent sx={{ p: "16px 18px !important", "&:last-child": { pb: "16px !important" } }}>
          <Eyebrow>Compute <Info k="agent" /></Eyebrow>
          <Box sx={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: "20px", alignItems: "start", mt: "14px" }}>
            <Box sx={{ textAlign: "center" }}>
              <svg viewBox="0 0 64 64" width="64" height="64" aria-hidden style={{ display: "block" }}>
                <circle cx="32" cy="32" r={ringR} fill="none" stroke={gpuOff ? "rgba(150,170,200,.08)" : "rgba(150,170,200,.16)"} strokeWidth="6" strokeDasharray={gpuOff ? "3 4" : undefined} />
                {!gpuOff && (
                  <circle cx="32" cy="32" r={ringR} fill="none" stroke={gpuPct > 80 ? "#ff5d73" : gpuPct > 50 ? "#f5a524" : "#3ddc97"} strokeWidth="6" strokeLinecap="round" strokeDasharray={ringC} strokeDashoffset={ringOff} transform="rotate(-90 32 32)" style={{ transition: "stroke-dashoffset 0.6s cubic-bezier(.16,1,.3,1)" }} />
                )}
                <text x="32" y="32" textAnchor="middle" dominantBaseline="central" fill={gpuOff ? "#8a94a8" : "#eef2f8"} fontFamily='"IBM Plex Mono", monospace' fontSize="13" fontWeight="600">
                  {gpuOff ? "\u2014" : `${Math.round(gpuPct)}%`}
                </text>
              </svg>
              <Box sx={{ width: 64, mt: 1 }}>
                <Box sx={{ height: 4, borderRadius: 2, bgcolor: "rgba(150,170,200,.16)", overflow: "hidden" }}>
                  <Box sx={{ width: gpuOff ? "0%" : `${gpuPct}%`, height: "100%", bgcolor: "#f5a524", borderRadius: 2, transition: "width 0.6s cubic-bezier(.16,1,.3,1)" }} />
                </Box>
                <Typography sx={{ fontFamily: '"IBM Plex Mono", monospace', fontSize: "0.59375rem", color: "#8a94a8", mt: 0.5, textAlign: "center", background: "none !important" }}>
                  vram {gpuOff ? "\u00b7 no signal" : latestSample?.vram_total_mb ? `${latestSample.vram_total_mb.toFixed(0)} MiB` : ""}
                </Typography>
              </Box>
            </Box>
            <Box>
              <Box sx={{ display: "flex", flexDirection: "column", gap: "3px" }}>
                <Typography sx={{ fontFamily: '"IBM Plex Sans", sans-serif', fontWeight: 600, fontSize: "0.8125rem", color: "#eef2f8", background: "none !important" }}>
                  {gpuOff ? "no model loaded" : (latestSample?.gpu_device_name || "GPU")}
                </Typography>
                {!gpuOff && (
                  <Box component="span" sx={{ fontFamily: '"IBM Plex Mono", monospace', fontSize: "0.625rem", color: "#9b7bff", alignSelf: "flex-start", px: 0.5, py: 0.125, border: "1px solid rgba(155,123,255,.35)", borderRadius: "4px", background: "none !important" }}>
                    {latestSample?.sensor_backend || "\u2014"}
                  </Box>
                )}
                <Typography sx={{ fontFamily: '"IBM Plex Mono", monospace', fontSize: "0.6875rem", color: "#8a94a8", background: "none !important" }}>
                  {gpuOff ? "" : `${latestSample?.hip_version ? `HIP ${latestSample.hip_version}` : ""} \u00b7 torch ${latestSample?.torch_version || "\u2014"}`}
                </Typography>
              </Box>
              <Box component="ol" sx={{ listStyle: "none", display: "flex", alignItems: "flex-start", gap: 0, m: "12px 0 0", p: 0 }}>
                {["embed", "retrieve", "generate", "publish"].map((s, i) => {
                  const state = gpuOff ? "idle" : i < 2 ? "done" : i === 2 ? "live" : "";
                  return (
                    <Box key={s} component="li" sx={{ position: "relative", display: "flex", flexDirection: "column", alignItems: "center", gap: "7px", flex: 1, minWidth: 0, background: "none !important" }}>
                      <Box sx={{ width: 8, height: 8, borderRadius: "50%", zIndex: 1, bgcolor: state === "done" ? "#3ddc97" : state === "live" ? "#9b7bff" : "rgba(150,170,200,.16)", boxShadow: state === "live" ? "0 0 0 4px rgba(155,123,255,.22)" : "none", transition: "background var(--t, 0.26s) var(--ease, cubic-bezier(.22,.61,.36,1)), box-shadow var(--t, 0.26s) var(--ease, cubic-bezier(.22,.61,.36,1))" }} />
                      {i < 3 && <Box sx={{ position: "absolute", top: "3.5px", left: "50%", width: "100%", height: "1.5px", bgcolor: state === "done" ? "rgba(61,220,151,.55)" : state === "live" ? "rgba(155,123,255,.55)" : "rgba(150,170,200,.08)", zIndex: 0 }} />}
                      <Typography sx={{ fontFamily: '"IBM Plex Mono", monospace', fontSize: "0.59375rem", color: state && state !== "idle" ? "#c2cbda" : "#8a94a8", lineHeight: 1, background: "none !important" }}>
                        {s}
                      </Typography>
                    </Box>
                  );
                })}
              </Box>
              {gpuOff && (
                <Typography sx={{ fontFamily: '"IBM Plex Sans", sans-serif', fontSize: "0.6875rem", color: "#8a94a8", fontStyle: "italic", mt: 1, background: "none !important" }}>
                  pipeline idle · awaiting a reasoning pass
                </Typography>
              )}
              <Box sx={{ display: "flex", gap: "22px", mt: 1.5 }}>
                <Box sx={{ background: "none !important" }}>
                  <Typography sx={{ fontFamily: '"IBM Plex Mono", monospace', fontSize: "0.5625rem", color: "#8a94a8", textTransform: "uppercase", letterSpacing: "0.14em", background: "none !important" }}>
                    latency
                  </Typography>
                  <Box sx={{ display: "flex", alignItems: "baseline", gap: "4px", background: "none !important" }}>
                    <Typography sx={{ fontFamily: '"IBM Plex Mono", monospace', fontSize: "1.05rem", fontWeight: 600, color: gpuOff ? "#8a94a8" : "#eef2f8", fontFeatureSettings: '"tnum"', background: "none !important" }}>
                      {gpuOff ? "\u2014" : (latestSample?.p95_query_latency_ms?.toFixed(0) || "\u2014")}
                    </Typography>
                    <Typography sx={{ fontFamily: '"IBM Plex Mono", monospace', fontSize: "0.59375rem", color: "#8a94a8", background: "none !important" }}>
                      ms
                    </Typography>
                  </Box>
                </Box>
                <Box sx={{ background: "none !important" }}>
                  <Typography sx={{ fontFamily: '"IBM Plex Mono", monospace', fontSize: "0.5625rem", color: "#8a94a8", textTransform: "uppercase", letterSpacing: "0.14em", background: "none !important" }}>
                    throughput
                  </Typography>
                  <Box sx={{ display: "flex", alignItems: "baseline", gap: "4px", background: "none !important" }}>
                    <Typography sx={{ fontFamily: '"IBM Plex Mono", monospace', fontSize: "1.05rem", fontWeight: 600, color: gpuOff ? "#8a94a8" : "#eef2f8", fontFeatureSettings: '"tnum"', background: "none !important" }}>
                      {gpuOff ? "\u2014" : (latestSample?.embeds_per_sec_radeon?.toFixed(0) || "\u2014")}
                    </Typography>
                    <Typography sx={{ fontFamily: '"IBM Plex Mono", monospace', fontSize: "0.59375rem", color: "#8a94a8", background: "none !important" }}>
                      e/s
                    </Typography>
                  </Box>
                </Box>
              </Box>
            </Box>
          </Box>
        </CardContent>
      </Card>

      {/* ── Agents ── */}
      <Card sx={{ gridColumn: { xs: "span 12", md: "span 4" }, borderRadius: "var(--r-md, 10px)" }}>
        <CardContent>
          <Box sx={{ display: "flex", alignItems: "center", justifyContent: "space-between", mb: 1.5 }}>
            <Eyebrow>Agents</Eyebrow>
            <Typography variant="caption" sx={{ fontFamily: '"IBM Plex Mono", monospace', color: "#8a94a8" }}>
              {Object.keys(agentSummary).length} agents · {activities.length} events · {reasoningCount} reasoning
            </Typography>
          </Box>
          {Object.entries(agentSummary).slice(0, 4).map(([name, info]) => {
            const isRunning = info.lastStep !== "completed" && info.lastStep !== "error" && info.lastStep !== "idle";
            return (
              <Box key={name} sx={{ display: "flex", alignItems: "center", gap: 1, py: 0.5 }}>
                <Box sx={{ width: 6, height: 6, borderRadius: "50%", bgcolor: isRunning ? "#3ddc97" : "#8a94a8", boxShadow: isRunning ? "0 0 6px rgba(61,220,151,.5)" : "none" }} />
                <Typography variant="body2" sx={{ color: "#eef2f8", fontFamily: '"IBM Plex Mono", monospace', fontSize: "0.75rem", flex: 1 }}>
                  {name}
                </Typography>
                <Typography variant="caption" sx={{ color: "#8a94a8" }}>
                  {info.lastStep}
                </Typography>
                <Typography variant="caption" sx={{ fontFamily: '"IBM Plex Mono", monospace', color: "#8a94a8" }}>
                  {info.total}
                </Typography>
              </Box>
            );
          })}
        </CardContent>
      </Card>

      {/* ── Techniques ── */}
      <Card sx={{ gridColumn: { xs: "span 12", md: "span 4" }, borderRadius: "var(--r-md, 10px)" }}>
        <CardContent>
          <Box sx={{ display: "flex", alignItems: "center", justifyContent: "space-between", mb: 1.5 }}>
            <Eyebrow>Techniques</Eyebrow>
            <Typography variant="caption" onClick={() => onNavigate("/attack")} sx={{ fontFamily: '"IBM Plex Mono", monospace', color: "#8a94a8", cursor: "pointer", "&:hover": { color: "#c2cbda" } }}>
              all {Object.keys(attackCounts).length} {"\u2197"}
            </Typography>
          </Box>
          {topTechniques.map(([id, count]) => {
            const pct = count / maxAttackCount;
            const heat = pct > 0.7 ? "#ff5d73" : pct > 0.3 ? "#f5a524" : "#8a94a8";
            return (
              <Box key={id} sx={{ display: "flex", alignItems: "center", gap: 1, py: 0.4 }}>
                <Typography variant="caption" sx={{ fontFamily: '"IBM Plex Mono", monospace', color: "#8a94a8", width: 60, flexShrink: 0 }}>
                  {id}
                </Typography>
                <Box sx={{ flex: 1, height: 4, borderRadius: 2, bgcolor: "rgba(150,170,200,.08)", overflow: "hidden" }}>
                  <Box sx={{ width: `${pct * 100}%`, height: "100%", bgcolor: heat, borderRadius: 2, transition: "width 0.4s ease" }} />
                </Box>
                <Typography variant="caption" sx={{ fontFamily: '"Space Grotesk", sans-serif', fontWeight: 700, color: heat, width: 24, textAlign: "right" }}>
                  {count}
                </Typography>
              </Box>
            );
          })}
        </CardContent>
      </Card>

      {/* ── Fabric Graph ── */}
      <Card sx={{ gridColumn: { xs: "span 12", md: "span 4" }, borderRadius: "var(--r-md, 10px)" }}>
        <CardContent>
          <Box sx={{ display: "flex", alignItems: "center", justifyContent: "space-between", mb: 1.5 }}>
            <Eyebrow>Fabric Graph <Info k="provenance" /></Eyebrow>
            <Typography variant="caption" onClick={() => onNavigate("/provenance")} sx={{ fontFamily: '"IBM Plex Mono", monospace', color: "#8a94a8", cursor: "pointer", "&:hover": { color: "#c2cbda" } }}>
              open {"\u2197"}
            </Typography>
          </Box>
          <Box sx={{ display: "grid", gridTemplateColumns: "1fr auto", gap: "16px", alignItems: "center", mt: "12px" }}>
            <svg viewBox="0 0 120 96" preserveAspectRatio="xMidYMid meet" role="img" aria-label={`Knowledge graph: ${graphSummary.nodes} entities, ${graphSummary.edges} links`} style={{ width: "100%", height: 96, display: "block" }}>
              <g>
                {graphSummary.mini.edges.map((e, i) => {
                  const [a, b] = e.split(":");
                  const na = graphSummary.mini.nodes.find(n => n.id === a);
                  const nb = graphSummary.mini.nodes.find(n => n.id === b);
                  if (!na || !nb) return null;
                  return <line key={i} x1={na.x} y1={na.y} x2={nb.x} y2={nb.y} stroke="rgba(150,170,200,.16)" strokeWidth="0.5" />;
                })}
              </g>
              <g style={{ transformOrigin: "center", animation: "drift 26s ease-in-out infinite alternate" }}>
                {graphSummary.mini.nodes.map(n => (
                  <circle key={n.id} cx={n.x} cy={n.y} r={n.r} fill={TYPE_COLOR_GRAPH.finding} opacity={0.8}>
                    <title>{n.label}</title>
                  </circle>
                ))}
              </g>
              <style>{`@keyframes drift{from{transform:translate(0,0)} to{transform:translate(1.5px,-1px)}}`}</style>
            </svg>
            <Box sx={{ display: "flex", flexDirection: "column", gap: "9px", minWidth: 96 }}>
              <Box sx={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: "10px" }}>
                <Typography sx={{ fontFamily: '"IBM Plex Mono", monospace', fontWeight: 600, fontSize: "1.2rem", fontFeatureSettings: '"tnum"', color: "#eef2f8", background: "none !important" }}>
                  {graphSummary.nodes}
                </Typography>
                <Typography sx={{ fontFamily: '"IBM Plex Mono", monospace', fontWeight: 500, fontSize: "0.5625rem", letterSpacing: "0.14em", textTransform: "uppercase", color: "#8a94a8", background: "none !important" }}>
                  entities
                </Typography>
              </Box>
              <Box sx={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: "10px" }}>
                <Typography sx={{ fontFamily: '"IBM Plex Mono", monospace', fontWeight: 600, fontSize: "1.2rem", fontFeatureSettings: '"tnum"', color: "#eef2f8", background: "none !important" }}>
                  {graphSummary.edges}
                </Typography>
                <Typography sx={{ fontFamily: '"IBM Plex Mono", monospace', fontWeight: 500, fontSize: "0.5625rem", letterSpacing: "0.14em", textTransform: "uppercase", color: "#8a94a8", background: "none !important" }}>
                  links
                </Typography>
              </Box>
              <Box sx={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: "10px" }}>
                <Typography sx={{ fontFamily: '"IBM Plex Mono", monospace', fontWeight: 600, fontSize: "1.2rem", fontFeatureSettings: '"tnum"', color: "#eef2f8", background: "none !important" }}>
                  {graphSummary.clusters}
                </Typography>
                <Typography sx={{ fontFamily: '"IBM Plex Mono", monospace', fontWeight: 500, fontSize: "0.5625rem", letterSpacing: "0.14em", textTransform: "uppercase", color: "#8a94a8", background: "none !important" }}>
                  clusters
                </Typography>
              </Box>
              <Box sx={{ borderTop: "1px dashed rgba(150,170,200,.08)", pt: 1, mt: 0.5 }}>
                <Typography sx={{ fontFamily: '"IBM Plex Mono", monospace', fontWeight: 500, fontSize: "0.5625rem", letterSpacing: "0.14em", textTransform: "uppercase", color: "#8a94a8", mb: 0.25, background: "none !important" }}>
                  most connected
                </Typography>
                <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
                  <Box sx={{ width: 6, height: 6, borderRadius: "50%", bgcolor: TYPE_COLOR_GRAPH.finding }} />
                  <Typography sx={{ fontFamily: '"IBM Plex Sans", sans-serif', fontWeight: 500, fontSize: "0.75rem", color: "#eef2f8", background: "none !important" }}>
                    {graphSummary.hub.label}
                  </Typography>
                  <Typography sx={{ fontFamily: '"IBM Plex Mono", monospace', fontWeight: 500, fontSize: "0.625rem", color: "#8a94a8", ml: "auto", background: "none !important" }}>
                    deg {graphSummary.hub.deg}
                  </Typography>
                </Box>
              </Box>
            </Box>
          </Box>
          <Box component="ul" sx={{ listStyle: "none", display: "flex", flexWrap: "wrap", gap: "6px 12px", m: "12px 0 0", p: "10px 0 0", borderTop: "1px solid rgba(150,170,200,.08)" }}>
            {Object.entries(TYPE_COLOR_GRAPH).map(([t, c]) => (
              <Box key={t} component="li" sx={{ display: "flex", alignItems: "center", gap: "5px", fontFamily: '"IBM Plex Mono", monospace', fontWeight: 500, fontSize: "0.59375rem", letterSpacing: "0.06em", textTransform: "uppercase", color: "#8a94a8" }}>
                <Box sx={{ width: 6, height: 6, borderRadius: "50%", bgcolor: c }} />
                {t}
              </Box>
            ))}
          </Box>
        </CardContent>
      </Card>

      {/* ── Feed ── */}
      <Card sx={{ gridColumn: { xs: "span 12", md: "span 6" }, borderRadius: "var(--r-md, 10px)" }}>
        <CardContent>
          <Box sx={{ display: "flex", alignItems: "center", justifyContent: "space-between", mb: 1.5 }}>
            <Eyebrow>Feed</Eyebrow>
            <Typography variant="caption" sx={{ fontFamily: '"IBM Plex Mono", monospace', color: "#8a94a8", cursor: "pointer", "&:hover": { color: "#c2cbda" } }} onClick={() => onNavigate("/feed")}>
              all {totalArticles} {"\u2197"}
            </Typography>
          </Box>
          {feed.map((a) => (
            <Box
              key={a.id}
              onClick={() => onNavigate(`/article/${a.id}`)}
              sx={{
                display: "flex", alignItems: "center", gap: 1.5, py: 0.75,
                cursor: "pointer", borderRadius: "var(--r-sm, 6px)", px: 0.5, mx: -0.5,
                transition: "all var(--t, 0.26s) var(--ease, cubic-bezier(.22,.61,.36,1))",
                "&:hover": { bgcolor: "var(--bg-raised, #1c232f)", transform: "translateY(-1px)" },
                "&:hover .action-cluster": { opacity: 1 },
              }}
            >
              <SeverityRail type={a.type} trust={a.trust_score} />
              <Box sx={{ flex: 1, minWidth: 0 }}>
                <Chip
                  label={a.type}
                  size="small"
                  sx={{
                    height: 20, fontSize: "0.625rem", fontWeight: 600, mb: 0.25,
                    color: a.type === "finding" ? "#ff5d73" : a.type === "insight" ? "#9b7bff" : "#8a94a8",
                    bgcolor: a.type === "finding" ? "rgba(255,93,115,.12)" : a.type === "insight" ? "rgba(155,123,255,.12)" : "rgba(150,170,200,.08)",
                    "& .MuiChip-label": { px: 0.75 },
                  }}
                />
                <Typography variant="body2" sx={{ color: "#c2cbda", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontSize: "0.75rem" }}>
                  {a.content}
                </Typography>
              </Box>
              <Box className="action-cluster" sx={{ display: "flex", alignItems: "center", gap: 0.5, opacity: 0, transition: "opacity 0.14s ease" }}>
                <Typography variant="caption" sx={{ fontFamily: '"IBM Plex Mono", monospace', fontSize: "0.625rem", color: "#8a94a8" }}>
                  open {"\u2197"}
                </Typography>
              </Box>
            </Box>
          ))}
        </CardContent>
      </Card>

      {/* ── Orgs ── */}
      <Card sx={{ gridColumn: { xs: "span 12", md: "span 3" }, borderRadius: "var(--r-md, 10px)" }}>
        <CardContent>
          <Eyebrow>Organizations</Eyebrow>
          {Object.entries(byOrg).map(([org, count]) => {
            const pct = byOrgTotal > 0 ? (count / byOrgTotal) * 100 : 0;
            const color = ORG_COLORS[org] || "#6b7689";
            return (
              <Box key={org} sx={{ display: "flex", alignItems: "center", gap: 1, py: 0.5 }}>
                <Box sx={{ width: 6, height: 6, borderRadius: "50%", bgcolor: color }} />
                <Typography variant="body2" sx={{ color: "#eef2f8", flex: 1, fontSize: "0.75rem" }}>
                  {org === "soc-alpha" ? "SOC Alpha" : org === "soc-beta" ? "SOC Beta" : org}
                </Typography>
                <Box sx={{ width: 60, height: 4, borderRadius: 2, bgcolor: "rgba(150,170,200,.08)", overflow: "hidden" }}>
                  <Box sx={{ width: `${pct}%`, height: "100%", bgcolor: color, borderRadius: 2 }} />
                </Box>
                <Typography variant="caption" sx={{ fontFamily: '"IBM Plex Mono", monospace', color: "#8a94a8", width: 32, textAlign: "right" }}>
                  {count}
                </Typography>
              </Box>
            );
          })}
        </CardContent>
      </Card>

      {/* ── Scope ── */}
      <Card sx={{ gridColumn: { xs: "span 12", md: "span 3" }, borderRadius: "var(--r-md, 10px)" }}>
        <CardContent>
          <Box sx={{ display: "flex", alignItems: "center", justifyContent: "space-between", mb: 1.5 }}>
            <Eyebrow>Scope</Eyebrow>
            <Typography variant="caption" sx={{ fontFamily: '"IBM Plex Mono", monospace', color: "#8a94a8", cursor: "pointer", "&:hover": { color: "#c2cbda" } }} onClick={() => onNavigate("/scope")}>
              all {"\u2197"}
            </Typography>
          </Box>
          {["finding", "insight", "warning", "precedent", "procedure"].filter(t => byType[t]).map(type => {
            const count = byType[type];
            const pct = totalByType > 0 ? (count / totalByType) * 100 : 0;
            const color = TYPE_COLORS[type] || "#6b7689";
            return (
              <Box key={type} sx={{ display: "flex", alignItems: "center", gap: 1, py: 0.4 }}>
                <Box sx={{ width: 6, height: 6, borderRadius: "50%", bgcolor: color }} />
                <Typography variant="body2" sx={{ color: "#c2cbda", flex: 1, fontSize: "0.75rem", textTransform: "capitalize" }}>
                  {type}
                </Typography>
                <Box sx={{ width: 60, height: 4, borderRadius: 2, bgcolor: "rgba(150,170,200,.08)", overflow: "hidden" }}>
                  <Box sx={{ width: `${pct}%`, height: "100%", bgcolor: color, borderRadius: 2, transition: "width 0.4s ease" }} />
                </Box>
                <Typography variant="caption" sx={{ fontFamily: '"IBM Plex Mono", monospace', color: "#8a94a8", width: 32, textAlign: "right" }}>
                  {count}
                </Typography>
              </Box>
            );
          })}
        </CardContent>
      </Card>
    </Box>
  );
}
