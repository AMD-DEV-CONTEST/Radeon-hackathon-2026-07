import { useState } from "react";
import Paper from "@mui/material/Paper";
import Typography from "@mui/material/Typography";
import Chip from "@mui/material/Chip";
import Stack from "@mui/material/Stack";
import Box from "@mui/material/Box";
import Collapse from "@mui/material/Collapse";
import IconButton from "@mui/material/IconButton";
import KeyboardArrowDown from "@mui/icons-material/KeyboardArrowDown";
import Search from "@mui/icons-material/Search";
import Psychology from "@mui/icons-material/Psychology";
import Publish from "@mui/icons-material/Publish";
import CheckCircleOutline from "@mui/icons-material/CheckCircleOutline";
import WarningAmber from "@mui/icons-material/WarningAmber";
import AutoAwesome from "@mui/icons-material/AutoAwesome";
import type { Article } from "../state/store";

interface AgentActivityProps {
  activities: Article[];
  onNavigate?: (path: string) => void;
}

const STEP_CONFIG: Record<string, { color: string; icon: React.ReactElement; label: string; timelineColor: string }> = {
  querying: { color: "primary", icon: <Search />, label: "Querying", timelineColor: "#3b82f6" },
  reasoning: { color: "secondary", icon: <Psychology />, label: "Reasoning", timelineColor: "#8b5cf6" },
  publishing: { color: "success", icon: <Publish />, label: "Publishing", timelineColor: "#14b8a6" },
  completed: { color: "success", icon: <CheckCircleOutline />, label: "Completed", timelineColor: "#14b8a6" },
  error: { color: "error", icon: <WarningAmber />, label: "Error", timelineColor: "#f43f5e" },
};

const ORG_LABELS: Record<string, string> = {
  "did:percq:org:soc-alpha": "SOC Alpha",
  "did:percq:org:soc-beta": "SOC Beta",
};

function TimelineNode({ color }: { color: string }) {
  return (
    <Box sx={{ position: "relative", display: "flex", flexDirection: "column", alignItems: "center", width: 20, flexShrink: 0 }}>
      <Box sx={{ width: 10, height: 10, borderRadius: "50%", bgcolor: color, boxShadow: `0 0 6px ${color}60`, zIndex: 1 }} />
    </Box>
  );
}

function TimelineLine() {
  return (
    <Box sx={{ width: 1, flex: 1, bgcolor: "rgba(255,255,255,.06)", mx: "auto" }} />
  );
}

function ActivityEntry({ activity, onNavigate, isLast }: { activity: Article; onNavigate?: (path: string) => void; isLast: boolean }) {
  const step = (activity.payload?.activity_step as string) || "querying";
  const config = STEP_CONFIG[step] || STEP_CONFIG.querying;
  const agentName = (activity.payload?.agent_name as string) || "Unknown Agent";
  const message = (activity.payload?.activity_message as string) || activity.content;
  const findingIds = activity.payload?.finding_ids as string[] | undefined;
  const insightId = activity.payload?.insight_id as string | undefined;
  const isReasoning = step === "reasoning";

  return (
    <Box sx={{ display: "flex", gap: 1.5 }}>
      <Box sx={{ display: "flex", flexDirection: "column", alignItems: "center", width: 20, flexShrink: 0 }}>
        <TimelineNode color={config.timelineColor} />
        {!isLast && <TimelineLine />}
      </Box>
      <Box sx={{ flex: 1, pb: isLast ? 0 : 2 }}>
        <Box
          sx={{
            p: 1.5,
            borderRadius: 2,
            border: "1px solid",
            borderColor: isReasoning
              ? "rgba(139,92,246,.3)"
              : "rgba(255,255,255,.06)",
            position: "relative",
            overflow: "hidden",
            transition: "border-color 0.2s ease",
            "&:hover": {
              borderColor: isReasoning
? "rgba(139,92,246,.5)"
                : "rgba(255,255,255,.12)",
            },
          }}
        >
          {isReasoning && (
            <Box
              sx={{
                position: "absolute",
                inset: 0,
                background: "linear-gradient(90deg, transparent 0%, rgba(139,92,246,.04) 50%, transparent 100%)",
                backgroundSize: "200% 100%",
                animation: "shimmer 3s ease-in-out infinite",
                "@keyframes shimmer": {
                  "0%": { backgroundPosition: "200% 0" },
                  "100%": { backgroundPosition: "-200% 0" },
                },
              }}
            />
          )}
          <Box sx={{ position: "relative", zIndex: 1 }}>
            <Box sx={{ display: "flex", alignItems: "center", gap: 1, mb: 0.5 }}>
              <Chip
                label={isReasoning ? "LLM Reasoning" : config.label}
                color={isReasoning ? "secondary" : (config.color as any)}
                variant={isReasoning ? "filled" : "outlined"}
                icon={isReasoning ? <AutoAwesome /> : config.icon}
                size="small"
                sx={{
                  textTransform: "none",
                  fontWeight: 500,
                  ...(isReasoning
                    ? { boxShadow: "0 0 12px rgba(139,92,246,.3)" }
                    : {}),
                }}
              />
              {isReasoning && (
                <Box sx={{ display: "flex", gap: 0.5 }}>
                  {[0, 1, 2].map(i => (
                    <Box
                      key={i}
                      sx={{
                        width: 4,
                        height: 4,
                        borderRadius: "50%",
                        bgcolor: "#8b5cf6",
                        animation: `bounce 1.4s ease-in-out ${i * 0.2}s infinite`,
                        "@keyframes bounce": {
                          "0%, 80%, 100%": { transform: "scale(0.6)", opacity: 0.4 },
                          "40%": { transform: "scale(1)", opacity: 1 },
                        },
                      }}
                    />
                  ))}
                </Box>
              )}
              <Typography variant="caption" sx={{ color: "#5d6678", ml: "auto", fontFamily: '"IBM Plex Mono", monospace' }}>
                {new Date().toLocaleTimeString()}
              </Typography>
            </Box>
            <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
              <Typography variant="body2" sx={{ color: "#9aa4b6", fontWeight: 500 }}>
                {agentName}
              </Typography>
              <Typography variant="body2" sx={{ color: isReasoning ? "#c4b5fd" : "#5d6678" }}>
                {message}
              </Typography>
            </Box>
            {step === "completed" && findingIds && findingIds.length > 0 && (
              <Stack direction="row" spacing={0.5} sx={{ mt: 0.75, flexWrap: "wrap" }}>
                <Typography variant="caption" sx={{ color: "#5d6678", lineHeight: "24px" }}>
                  Published:
                </Typography>
                {findingIds.slice(0, 3).map(fid => (
                  <Chip
                    key={fid}
                    label={fid.slice(0, 8) + "…"}
                    size="small"
                    variant="outlined"
                    sx={{
                      borderColor: "rgba(244,63,94,.3)",
                      color: "#f43f5e",
                      fontSize: "0.6875rem",
                      height: 22,
                      fontFamily: '"IBM Plex Mono", monospace',
                      cursor: "pointer",
                      "&:hover": { borderColor: "#f43f5e" },
                    }}
                    onClick={() => onNavigate?.(`/article/${fid}`)}
                  />
                ))}
                {insightId && (
                  <Chip
                    label={"insight " + insightId.slice(0, 8) + "…"}
                    size="small"
                    variant="outlined"
                    sx={{
                      borderColor: "rgba(139,92,246,.3)",
                      color: "#8b5cf6",
                      fontSize: "0.6875rem",
                      height: 22,
                      fontFamily: '"IBM Plex Mono", monospace',
                      cursor: "pointer",
                      "&:hover": { borderColor: "#8b5cf6" },
                    }}
                    onClick={() => onNavigate?.(`/article/${insightId}`)}
                  />
                )}
              </Stack>
            )}
          </Box>
        </Box>
      </Box>
    </Box>
  );
}

function AgentGroup({ agent, items, onNavigate }: { agent: string; items: Article[]; onNavigate?: (path: string) => void }) {
  const [collapsed, setCollapsed] = useState(false);
  const lastEvent = items[0]?.payload?.activity_step as string || "";
  const isRunning = lastEvent !== "completed" && lastEvent !== "error";

  const deduped = items.reduce((acc: Article[], item) => {
    const last = acc[acc.length - 1];
    const sameStep = last?.payload?.activity_step === item.payload?.activity_step;
    const sameMsg = last?.payload?.activity_message === item.payload?.activity_message;
    if (sameStep && sameMsg) {
      (last as any)._count = ((last as any)._count || 1) + 1;
      return acc;
    }
    (item as any)._count = 1;
    acc.push(item);
    return acc;
  }, []);

  return (
    <Paper sx={{ borderRadius: 2, overflow: "hidden", border: "1px solid rgba(255,255,255,.06)" }}>
      <Box
        sx={{
          display: "flex",
          alignItems: "center",
          gap: 1.5,
          px: 2,
          py: 1.5,
          cursor: "pointer",
          "&:hover": { bgcolor: "rgba(255,255,255,.02)" },
        }}
        onClick={() => setCollapsed(!collapsed)}
      >
        <Box sx={{ width: 8, height: 8, borderRadius: "50%", bgcolor: isRunning ? "#14b8a6" : "#5d6678", boxShadow: isRunning ? "0 0 6px rgba(20,184,166,.5)" : "none" }} />
        <Typography variant="body2" sx={{ fontWeight: 600, color: "#e8ecf4", flex: 1 }}>
          {agent}
        </Typography>
        <Typography variant="caption" sx={{ color: "#5d6678", fontFamily: '"IBM Plex Mono", monospace' }}>
          {items.length} events
        </Typography>
        {isRunning && (
          <Chip label="active" size="small" sx={{ color: "#14b8a6", bgcolor: "rgba(20,184,166,.1)", fontWeight: 500, fontSize: "0.6875rem", height: 22 }} />
        )}
        <IconButton size="small" sx={{ color: "#5d6678", transform: collapsed ? "rotate(-90deg)" : "none", transition: "transform 0.2s ease" }}>
          <KeyboardArrowDown fontSize="small" />
        </IconButton>
      </Box>
      <Collapse in={!collapsed}>
        <Box sx={{ px: 2, pb: 1.5 }}>
          <Box sx={{ pl: 0.5 }}>
            {deduped.map((a, i) => {
              const count = (a as any)._count;
              return (
                <Box key={a.id}>
                  <ActivityEntry activity={a} onNavigate={onNavigate} isLast={i === deduped.length - 1} />
                  {count > 1 && (
                    <Box sx={{ display: "flex", gap: 1.5, pl: "34px", mt: -1.5, mb: 1 }}>
                      <Chip
                        label={`×${count} repeated`}
                        size="small"
                        variant="outlined"
                        sx={{ borderColor: "rgba(255,255,255,.08)", color: "#5d6678", fontSize: "0.6875rem", height: 20 }}
                      />
                    </Box>
                  )}
                </Box>
              );
            })}
          </Box>
        </Box>
      </Collapse>
    </Paper>
  );
}

export function AgentActivity({ activities, onNavigate }: AgentActivityProps) {
  const grouped: Record<string, Article[]> = {};
  for (const a of activities) {
    const agent = (a.payload?.agent_name as string) || "Unknown";
    if (!grouped[agent]) grouped[agent] = [];
    grouped[agent].push(a);
  }

  return (
    <Box>
      <Box sx={{ display: "flex", alignItems: "center", justifyContent: "space-between", mb: 3 }}>
        <Typography variant="h1" sx={{ fontSize: "1.5rem" }}>
          Agent Activity
        </Typography>
        <Typography variant="caption" sx={{ color: "#5d6678" }}>
          {activities.length} events · {Object.keys(grouped).length} agents
        </Typography>
      </Box>

      {activities.length === 0 ? (
        <Paper
          sx={{
            p: 4,
            textAlign: "center",
            border: "1px dashed rgba(255,255,255,.1)",
            borderRadius: 2,
          }}
        >
          <Typography variant="body2" sx={{ color: "#5d6678" }}>
            No agent activity yet. Run an agent to see real-time steps.
          </Typography>
        </Paper>
      ) : (
        <Stack spacing={1.5}>
          {Object.entries(grouped).map(([agent, items]) => (
            <AgentGroup key={agent} agent={agent} items={items} onNavigate={onNavigate} />
          ))}
        </Stack>
      )}
    </Box>
  );
}
