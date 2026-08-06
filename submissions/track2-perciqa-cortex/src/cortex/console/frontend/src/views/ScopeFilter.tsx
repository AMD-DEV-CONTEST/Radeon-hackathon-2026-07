import { useState, useMemo } from "react";
import Box from "@mui/material/Box";
import Typography from "@mui/material/Typography";
import Chip from "@mui/material/Chip";
import Stack from "@mui/material/Stack";
import Tooltip from "@mui/material/Tooltip";
import Collapse from "@mui/material/Collapse";
import IconButton from "@mui/material/IconButton";
import KeyboardArrowDown from "@mui/icons-material/KeyboardArrowDown";

const TYPE_CONFIG: Record<string, { color: string; label: string }> = {
  finding: { color: "#f43f5e", label: "Finding" },
  insight: { color: "#8b5cf6", label: "Insight" },
  warning: { color: "#f59e0b", label: "Warning" },
  precedent: { color: "#3b82f6", label: "Precedent" },
  procedure: { color: "#14b8a6", label: "Procedure" },
};

function trustMeterColor(value: number | null | undefined): string {
  if (value === null || value === undefined) return "#5d6678";
  if (value > 0.7) return "#14b8a6";
  if (value > 0.4) return "#f59e0b";
  return "#f43f5e";
}

function TrustMeter({ value }: { value: number | null | undefined }) {
  const isUnranked = value === null || value === undefined || value === 0;
  const pct = isUnranked ? 0 : Math.min(value! * 100, 100);
  const color = trustMeterColor(value);

  return (
    <Tooltip
      title={
        isUnranked
          ? "awaiting corroboration"
          : `trust: ${(value! * 100).toFixed(0)}%`
      }
      arrow
    >
      <Box
        sx={{
          width: 60,
          height: 4,
          borderRadius: 2,
          bgcolor: "rgba(150,170,200,.16)",
          overflow: "hidden",
          cursor: "pointer",
          position: "relative",
        }}
      >
        <Box
          sx={{
            width: isUnranked ? "100%" : `${pct}%`,
            height: "100%",
            bgcolor: isUnranked ? "transparent" : color,
            borderRadius: 2,
            opacity: isUnranked ? 0.5 : 1,
            border: isUnranked ? "1px dashed rgba(150,170,200,.4)" : "none",
            transition: "width 0.4s ease",
          }}
        />
      </Box>
    </Tooltip>
  );
}

export function ScopeFilter({ articles }: { articles: any[] }) {
  const [typeFilter, setTypeFilter] = useState<string>("all");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const typeCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const a of articles) {
      counts[a.type] = (counts[a.type] || 0) + 1;
    }
    return counts;
  }, [articles]);

  const types = ["all", ...new Set(articles.map(a => a.type))];
  const filtered = typeFilter === "all" ? articles : articles.filter(a => a.type === typeFilter);

  const toggleExpand = (id: string) => {
    setExpanded(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  return (
    <Box>
      <Box sx={{ display: "flex", alignItems: "center", justifyContent: "space-between", mb: 3 }}>
        <Typography variant="h1" sx={{ fontSize: "1.5rem" }}>
          Scope Filter
        </Typography>
        <Typography variant="caption" sx={{ color: "#5d6678" }}>
          {articles.length} articles
        </Typography>
      </Box>

      <Stack direction="row" spacing={1} sx={{ mb: 3, flexWrap: "wrap", gap: 0.5 }}>
        {types.map(t => {
          const config = t === "all" ? null : TYPE_CONFIG[t];
          const count = t === "all" ? articles.length : (typeCounts[t] || 0);
          return (
            <Chip
              key={t}
              label={
                <Box component="span" sx={{ display: "flex", alignItems: "center", gap: 0.5 }}>
                  {t === "all" ? "All" : (config?.label || t)}
                  <Box
                    component="span"
                    sx={{
                      fontFamily: '"IBM Plex Mono", monospace',
                      fontSize: "0.6875rem",
                      color: typeFilter === t ? "inherit" : "#5d6678",
                      ml: 0.25,
                    }}
                  >
                    {count}
                  </Box>
                </Box>
              }
              size="small"
              variant={typeFilter === t ? "filled" : "outlined"}
              color={typeFilter === t ? "primary" : undefined}
              onClick={() => setTypeFilter(t)}
              sx={{
                cursor: "pointer",
                ...(t !== "all" && typeFilter !== t
                  ? {
                      borderColor: config ? `${config.color}44` : undefined,
                      "& .MuiChip-label": { color: config?.color },
                    }
                  : {}),
              }}
            />
          );
        })}
      </Stack>

      <Stack spacing={0.5}>
        {filtered.map(a => {
          const config = TYPE_CONFIG[a.type] || TYPE_CONFIG.finding;
          const trustValue = a.trust_score ?? null;
          const isExpanded = expanded.has(a.id);
          const isUnranked = trustValue === null || trustValue === undefined || trustValue === 0;
          const colorIntensity = isUnranked ? 0.2 : Math.min(trustValue * 0.8 + 0.2, 1);

          return (
            <Box
              key={a.id}
              sx={{
                display: "flex",
                borderRadius: 1.5,
                overflow: "hidden",
                transition: "all 0.15s ease",
                "&:hover": { bgcolor: "rgba(255,255,255,.02)" },
              }}
            >
              <Box
                sx={{
                  width: 3,
                  flexShrink: 0,
                  bgcolor: config.color,
                  opacity: colorIntensity,
                  borderRadius: "0 2px 2px 0",
                }}
              />
              <Box sx={{ flex: 1, pl: 1.5, py: 1, pr: 1 }}>
                <Box sx={{ display: "flex", alignItems: "center", gap: 1.5 }}>
                  <Chip
                    label={config.label}
                    size="small"
                    sx={{
                      color: config.color,
                      bgcolor: `${config.color}18`,
                      fontWeight: 500,
                      fontSize: "0.6875rem",
                      height: 22,
                      "& .MuiChip-label": { px: 0.75 },
                    }}
                  />
                  <TrustMeter value={trustValue} />
                  {isUnranked && (
                    <Typography variant="caption" sx={{ color: "#5d6678", fontStyle: "italic" }}>
                      unranked
                    </Typography>
                  )}
                  <Typography
                    variant="body2"
                    sx={{
                      color: "#9aa4b6",
                      flex: 1,
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: isExpanded ? "normal" : "nowrap",
                      cursor: "pointer",
                    }}
                    onClick={() => toggleExpand(a.id)}
                  >
                    {a.content}
                  </Typography>
                  <Typography variant="caption" sx={{ color: "#5d6678", whiteSpace: "nowrap" }}>
                    {trustValue !== null && trustValue !== undefined
                      ? `${(trustValue * 100).toFixed(0)}%`
                      : "—"}
                  </Typography>
                  <IconButton
                    size="small"
                    onClick={() => toggleExpand(a.id)}
                    sx={{
                      color: "#5d6678",
                      transform: isExpanded ? "rotate(180deg)" : "none",
                      transition: "transform 0.2s ease",
                    }}
                  >
                    <KeyboardArrowDown fontSize="small" />
                  </IconButton>
                </Box>
                <Collapse in={isExpanded}>
                  <Box sx={{ pl: 1, pr: 1, pt: 1.5, pb: 0.5 }}>
                    <Typography variant="body2" sx={{ color: "#e8ecf4", mb: 1 }}>
                      {a.content}
                    </Typography>
                    <Stack direction="row" spacing={1} sx={{ flexWrap: "wrap", gap: 0.5 }}>
                      {a.src_org && (
                        <Chip
                          label={a.src_org}
                          size="small"
                          variant="outlined"
                          sx={{ borderColor: "rgba(255,255,255,.1)", color: "#9aa4b6", fontSize: "0.6875rem", height: 22 }}
                        />
                      )}
                      {a.agent_signature && (
                        <Chip
                          label={`agent: ${a.agent_signature.slice(0, 10)}…`}
                          size="small"
                          variant="outlined"
                          sx={{ borderColor: "rgba(255,255,255,.1)", color: "#9aa4b6", fontSize: "0.6875rem", height: 22 }}
                        />
                      )}
                      {a.cites && a.cites.map((c: string) => (
                        <Chip
                          key={c}
                          label={c.slice(0, 12)}
                          size="small"
                          variant="outlined"
                          sx={{
                            borderColor: "rgba(255,255,255,.1)",
                            color: "#5d6678",
                            fontSize: "0.6875rem",
                            height: 22,
                            fontFamily: '"IBM Plex Mono", monospace',
                            "&:hover": { borderColor: "rgba(255,255,255,.3)" },
                          }}
                        />
                      ))}
                    </Stack>
                  </Box>
                </Collapse>
              </Box>
            </Box>
          );
        })}
      </Stack>
    </Box>
  );
}
