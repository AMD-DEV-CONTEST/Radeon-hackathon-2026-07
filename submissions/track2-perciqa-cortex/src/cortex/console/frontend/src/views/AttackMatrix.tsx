import { useState, useMemo } from "react";
import Box from "@mui/material/Box";
import Typography from "@mui/material/Typography";
import Chip from "@mui/material/Chip";
import Stack from "@mui/material/Stack";
import Dialog from "@mui/material/Dialog";
import DialogTitle from "@mui/material/DialogTitle";
import DialogContent from "@mui/material/DialogContent";
import DialogContentText from "@mui/material/DialogContentText";
import IconButton from "@mui/material/IconButton";
import Close from "@mui/icons-material/Close";
import { ATTACK_TECHNIQUES } from "../data/attackTechniques";

export interface AttackMatrixProps {
  counts: Record<string, number>;
  articlesFor: (id: string) => { id: string; content: string }[];
}

const SEVERITY_ORDER = ["critical", "high", "medium", "low"] as const;
const SEVERITY_COLORS: Record<string, { dot: string; bg: string; text: string }> = {
  critical: { dot: "#f43f5e", bg: "rgba(244,63,94,.15)", text: "#f43f5e" },
  high: { dot: "#f59e0b", bg: "rgba(245,158,11,.12)", text: "#f59e0b" },
  medium: { dot: "#6366f1", bg: "rgba(99,102,241,.1)", text: "#6366f1" },
  low: { dot: "#14b8a6", bg: "rgba(20,184,166,.08)", text: "#14b8a6" },
};

function heatColor(count: number, max: number): string {
  if (max === 0) return "#5d6678";
  const t = count / max;
  if (t === 0) return "#5d6678";
  if (t < 0.3) return `hsl(40, 80%, ${50 - t * 40}%)`;
  if (t < 0.7) return `hsl(25, 90%, ${45 - (t - 0.3) * 30}%)`;
  return `hsl(0, 85%, ${40 - (t - 0.7) * 20}%)`;
}

export function AttackMatrix({ counts, articlesFor }: AttackMatrixProps) {
  const [selected, setSelected] = useState<string | null>(null);
  const [view, setView] = useState<"grid" | "list">("grid");

  const maxCount = Math.max(...Object.values(counts), 1);

  const entries = useMemo(() => {
    const grouped: Record<string, { id: string; name: string; count: number }[]> = {};
    for (const s of SEVERITY_ORDER) grouped[s] = [];
    for (const [id, count] of Object.entries(counts)) {
      const tech = ATTACK_TECHNIQUES[id];
      const sev = tech?.severity || "medium";
      if (grouped[sev]) grouped[sev].push({ id, name: tech?.name || id, count });
    }
    for (const s of SEVERITY_ORDER) grouped[s].sort((a, b) => b.count - a.count);
    return grouped;
  }, [counts]);

  const totalEntries = Object.keys(counts).length;
  const totalCount = Object.values(counts).reduce((a, b) => a + b, 0);

  return (
    <Box>
      <Box sx={{ display: "flex", alignItems: "center", justifyContent: "space-between", mb: 3 }}>
        <Typography variant="h1" sx={{ fontSize: "1.5rem" }}>
          Attack Matrix
        </Typography>
        <Box sx={{ display: "flex", alignItems: "center", gap: 2 }}>
          <Typography variant="caption" sx={{ color: "#5d6678" }}>
            {totalEntries} techniques · {totalCount} findings
          </Typography>
          <Stack direction="row" spacing={0.5}>
            <Chip
              label="Grid"
              size="small"
              variant={view === "grid" ? "filled" : "outlined"}
              color={view === "grid" ? "primary" : undefined}
              onClick={() => setView("grid")}
              sx={{ cursor: "pointer" }}
            />
            <Chip
              label="Ranked"
              size="small"
              variant={view === "list" ? "filled" : "outlined"}
              color={view === "list" ? "primary" : undefined}
              onClick={() => setView("list")}
              sx={{ cursor: "pointer" }}
            />
          </Stack>
        </Box>
      </Box>

      {view === "grid" ? (
        <Stack spacing={2}>
          {SEVERITY_ORDER.filter(s => entries[s].length > 0).map(severity => {
            const group = entries[severity];
            const sColors = SEVERITY_COLORS[severity];
            return (
              <Box key={severity}>
                <Box sx={{ display: "flex", alignItems: "center", gap: 1, mb: 1 }}>
                  <Box sx={{ width: 10, height: 10, borderRadius: "50%", bgcolor: sColors.dot }} />
                  <Typography
                    variant="overline"
                    sx={{ color: sColors.text, letterSpacing: "0.12em" }}
                  >
                    {severity}
                  </Typography>
                  <Typography variant="caption" sx={{ color: "#5d6678" }}>
                    {group.length}
                  </Typography>
                </Box>
                <Box
                  sx={{
                    display: "grid",
                    gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))",
                    gap: 1,
                  }}
                >
                  {group.map(({ id, name, count }) => {
                    const pct = count / maxCount;
                    return (
                      <Box
                        key={id}
                        onClick={() => setSelected(id)}
                        sx={{
                          p: 1.5,
                          borderRadius: 2,
                          bgcolor: "rgba(255,255,255,.03)",
                          border: "1px solid rgba(255,255,255,.06)",
                          cursor: "pointer",
                          transition: "all 0.15s ease",
                          "&:hover": {
                            bgcolor: "rgba(255,255,255,.06)",
                            borderColor: "rgba(255,255,255,.12)",
                          },
                          position: "relative",
                          overflow: "hidden",
                        }}
                      >
                        <Box
                          sx={{
                            position: "absolute",
                            bottom: 0,
                            left: 0,
                            width: `${pct * 100}%`,
                            height: "100%",
                            bgcolor: heatColor(count, maxCount),
                            opacity: 0.1,
                            borderRadius: 1,
                            transition: "width 0.4s ease",
                          }}
                        />
                        <Box sx={{ position: "relative", zIndex: 1 }}>
                          <Typography variant="caption" sx={{ color: "#5d6678", fontFamily: '"IBM Plex Mono", monospace' }}>
                            {id}
                          </Typography>
                          <Typography
                            variant="body2"
                            sx={{
                              color: "#e8ecf4",
                              overflow: "hidden",
                              textOverflow: "ellipsis",
                              whiteSpace: "nowrap",
                              mb: 0.5,
                            }}
                          >
                            {name}
                          </Typography>
                          <Typography
                            variant="h4"
                            sx={{
                              fontFamily: '"Space Grotesk", sans-serif',
                              fontWeight: 700,
                              color: heatColor(count, maxCount),
                              fontSize: "1.25rem",
                            }}
                          >
                            {count}
                          </Typography>
                        </Box>
                      </Box>
                    );
                  })}
                </Box>
              </Box>
            );
          })}
        </Stack>
      ) : (
        <Stack spacing={0.5}>
          {Object.entries(counts)
            .sort(([, a], [, b]) => b - a)
            .map(([id, count]) => {
              const tech = ATTACK_TECHNIQUES[id];
              const sev = tech?.severity || "medium";
              const sColors = SEVERITY_COLORS[sev] || SEVERITY_COLORS.medium;
              const pct = count / maxCount;
              return (
                <Box
                  key={id}
                  onClick={() => setSelected(id)}
                  sx={{
                    display: "flex",
                    alignItems: "center",
                    gap: 1.5,
                    p: "6px 12px",
                    borderRadius: 1,
                    cursor: "pointer",
                    transition: "background 0.15s ease",
                    "&:hover": { bgcolor: "rgba(255,255,255,.04)" },
                  }}
                >
                  <Box sx={{ width: 6, height: 6, borderRadius: "50%", bgcolor: sColors.dot, flexShrink: 0 }} />
                  <Typography variant="caption" sx={{ color: "#5d6678", fontFamily: '"IBM Plex Mono", monospace', width: 70, flexShrink: 0 }}>
                    {id}
                  </Typography>
                  <Typography variant="body2" sx={{ color: "#e8ecf4", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {tech?.name || id}
                  </Typography>
                  <Box sx={{ width: 120, height: 6, borderRadius: 3, bgcolor: "rgba(255,255,255,.06)", overflow: "hidden", flexShrink: 0 }}>
                    <Box sx={{ width: `${pct * 100}%`, height: "100%", bgcolor: heatColor(count, maxCount), borderRadius: 3, transition: "width 0.4s ease" }} />
                  </Box>
                  <Typography variant="h6" sx={{ fontFamily: '"Space Grotesk", sans-serif', fontWeight: 700, color: heatColor(count, maxCount), fontSize: "0.9375rem", width: 32, textAlign: "right" }}>
                    {count}
                  </Typography>
                </Box>
              );
            })}
        </Stack>
      )}

      <Dialog open={!!selected} onClose={() => setSelected(null)} maxWidth="sm" fullWidth>
        <DialogTitle sx={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <Box>
            <Typography variant="overline" sx={{ color: "#5d6678", fontFamily: '"IBM Plex Mono", monospace' }}>
              {selected}
            </Typography>
            <Typography variant="h6">
              {selected ? ATTACK_TECHNIQUES[selected]?.name || selected : ""}
            </Typography>
          </Box>
          <IconButton onClick={() => setSelected(null)} size="small">
            <Close />
          </IconButton>
        </DialogTitle>
        <DialogContent>
          {selected && articlesFor(selected).map(a => (
            <DialogContentText key={a.id} sx={{ mb: 1, fontFamily: '"IBM Plex Mono", monospace', fontSize: "0.8125rem" }}>
              {a.content}
            </DialogContentText>
          ))}
        </DialogContent>
      </Dialog>
    </Box>
  );
}
