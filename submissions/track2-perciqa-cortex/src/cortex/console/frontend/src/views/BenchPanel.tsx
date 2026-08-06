import { useState, useEffect } from "react";
import Box from "@mui/material/Box";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Chip from "@mui/material/Chip";
import CircularProgress from "@mui/material/CircularProgress";
import Grid from "@mui/material/Grid2";
import LinearProgress from "@mui/material/LinearProgress";
import Stack from "@mui/material/Stack";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import Cancel from "@mui/icons-material/Cancel";
import CheckCircle from "@mui/icons-material/CheckCircle";
import DesktopWindows from "@mui/icons-material/DesktopWindows";
import DeveloperBoard from "@mui/icons-material/DeveloperBoard";
import Memory from "@mui/icons-material/Memory";
import Psychology from "@mui/icons-material/Psychology";
import Sensors from "@mui/icons-material/Sensors";
import type { Article } from "../state/store";

interface BenchPanelProps {
  byNode: Record<string, any[]>;
  articles: Article[];
  activities: Article[];
  connected: boolean;
}

interface RocmInfo {
  mem_util_pct: number;
  vram_total_mb?: number;
  vram_used_mb?: number;
  device_name: string;
  sensor_backend: string;
  hip_version: string | null;
  torch_version: string | null;
  rocm_active: boolean;
}

interface LlmInfo {
  status: "online" | "offline";
  model: string;
  endpoint: string;
  error?: string;
}

const TYPE_COLORS: Record<string, string> = {
  finding: "error",
  insight: "secondary",
  warning: "warning",
  precedent: "info",
  procedure: "success",
  activity: "default",
};

const ORG_LABELS: Record<string, string> = {
  "did:percq:org:soc-alpha": "SOC Alpha",
  "did:percq:org:soc-beta": "SOC Beta",
};

import { useCountUp } from "../hooks/useCountUp";

function VramRing({ pct }: { pct: number }) {
  const animatedValue = useCountUp(Math.round(pct));
  const color = pct > 80 ? "error.main" : pct > 50 ? "warning.main" : "success.main";
  return (
    <Box sx={{ position: "relative", display: "inline-flex" }}>
      <CircularProgress
        variant="determinate"
        value={animatedValue}
        size={60}
        thickness={6}
        sx={{ color, "& .MuiCircularProgress-track": { color: "rgba(255,255,255,.06)" } }}
      />
      <Box sx={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center" }}>
        <Typography variant="caption" fontWeight={700} sx={{ color }}>
          {Math.round(animatedValue)}%
        </Typography>
      </Box>
    </Box>
  );
}

function GpuStatusCard({ rocm }: { rocm: RocmInfo | null }) {
  if (!rocm || !rocm.rocm_active) {
    return (
      <Card variant="outlined" sx={{ borderRadius: 2 }}>
        <CardContent>
          <Stack direction="row" spacing={1.5} alignItems="center" sx={{ mb: 1.5 }}>
            <DesktopWindows sx={{ fontSize: 20 }} />
            <Typography fontWeight={700}>GPU Status</Typography>
          </Stack>
          <Chip label="No GPU detected" variant="outlined" size="small" />
          <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
            Running on CPU fallback
          </Typography>
        </CardContent>
      </Card>
    );
  }

  const vramPct = Math.min(rocm.mem_util_pct, 100);
  const vramColor = vramPct > 80 ? "error" : vramPct > 50 ? "warning" : "success";

  return (
    <Card variant="outlined" sx={{ borderRadius: 2 }}>
      <CardContent>
        <Stack direction="row" spacing={1.5} alignItems="center" sx={{ mb: 2 }}>
          <DeveloperBoard sx={{ color: "error.main", fontSize: 24 }} />
          <Box sx={{ flex: 1 }}>
            <Stack direction="row" spacing={0.5} alignItems="center">
              <Typography variant="body2" fontWeight={700}>{rocm.device_name}</Typography>
              <Chip label={rocm.sensor_backend} size="small" color="success" variant="outlined" />
            </Stack>
            <Stack direction="row" spacing={0.5} sx={{ mt: 0.25 }}>
              <Typography variant="caption" color="text.secondary">HIP {rocm.hip_version || "—"}</Typography>
              <Typography variant="caption" color="text.secondary">·</Typography>
              <Typography variant="caption" color="text.secondary">torch {rocm.torch_version || "—"}</Typography>
            </Stack>
          </Box>
          <VramRing pct={vramPct} />
        </Stack>
        <LinearProgress variant="determinate" value={vramPct} color={vramColor} />
        <Typography variant="caption" color="text.secondary" sx={{ mt: 0.5 }}>VRAM utilization</Typography>
      </CardContent>
    </Card>
  );
}

function LlmStatusCard({ llm, reasoningCount }: { llm: LlmInfo | null; reasoningCount: number }) {
  const online = llm?.status === "online";
  const pipelineStages = ["embed", "retrieve", "generate", "publish"];
  const activeStage = reasoningCount > 0 ? Math.min(Math.floor(reasoningCount / 3) % 4, 3) : -1;
  const displayName = llm
    ? llm.model.split("/").pop()?.replace(/-/g, " ") ?? llm.model
    : "—";

  return (
    <Card
      variant="outlined"
      sx={{
        borderRadius: 2,
        ...(online ? { borderColor: "secondary.main", borderWidth: 1.5 } : {}),
      }}
    >
      <CardContent>
        <Stack direction="row" spacing={1.5} alignItems="center" sx={{ mb: 2 }}>
          <Box
            sx={
              online
                ? { width: 36, height: 36, borderRadius: 1.5, background: "linear-gradient(135deg, #7c3aed, #4f46e5)", display: "flex", alignItems: "center", justifyContent: "center" }
                : { width: 36, height: 36, borderRadius: 1.5, bgcolor: "grey.500", display: "flex", alignItems: "center", justifyContent: "center" }
            }
          >
            <Psychology sx={{ fontSize: 20, color: "#fff" }} />
          </Box>
          <Box sx={{ flex: 1 }}>
            <Stack direction="row" spacing={0.5} alignItems="center">
              <Typography variant="body2" fontWeight={700}>{displayName}</Typography>
              {online
                ? <Chip icon={<CheckCircle sx={{ fontSize: 14 }} />} label="vLLM · ROCm" size="small" color="secondary" variant="outlined" />
                : <Chip icon={<Cancel sx={{ fontSize: 14 }} />} label="offline" size="small" variant="outlined" />
              }
            </Stack>
            {llm && (
              <Typography variant="caption" color="text.secondary" sx={{ mt: 0.25, fontFamily: "monospace" }}>
                {llm.endpoint}
              </Typography>
            )}
          </Box>
        </Stack>

        {online ? (
          <Stack direction="row" spacing={3}>
            <Box>
              <Typography variant="caption" color="text.secondary">Reasoning steps</Typography>
              <Typography variant="h5" fontWeight={700} color="secondary.main">{reasoningCount}</Typography>
            </Box>
            <Box sx={{ flex: 1 }}>
              <Typography variant="caption" color="text.secondary" sx={{ mb: 0.5 }}>LLM pipeline</Typography>
              <Stack direction="row" spacing={0.5} sx={{ flexWrap: "nowrap" }} alignItems="center">
                {pipelineStages.map((stage, i) => (
                  <Box key={stage} sx={{ display: "flex", alignItems: "center", gap: 0.5 }}>
                    {i > 0 && (
                      <Box sx={{ display: "flex", alignItems: "center" }}>
                        <Box sx={{ width: 12, height: 1, bgcolor: i <= activeStage ? "#8b5cf6" : "rgba(255,255,255,.1)", transition: "background 0.3s ease" }} />
                        {activeStage >= i && (
                          <Box sx={{ width: 3, height: 3, borderRadius: "50%", bgcolor: "#8b5cf6", ml: -0.5 }} />
                        )}
                      </Box>
                    )}
                    <Chip
                      label={stage}
                      size="small"
                      color={i === activeStage ? "secondary" : "default"}
                      variant={i === activeStage ? "filled" : "outlined"}
                      sx={{
                        transition: "all 0.3s ease",
                        ...(i === activeStage ? { boxShadow: "0 0 8px rgba(139,92,246,.4)" } : {}),
                      }}
                    />
                  </Box>
                ))}
              </Stack>
            </Box>
          </Stack>
        ) : (
          <Typography variant="caption" color="text.secondary">
            {llm?.error ?? "vLLM pod not reachable. Start with COMPOSE_PROFILES=gpu."}
          </Typography>
        )}
      </CardContent>
    </Card>
  );
}

function NodeMetricsCard({ node, samples }: { node: string; samples: any[] }) {
  const latest = samples[samples.length - 1];
  if (!latest) return null;

  const radeon = latest.embeds_per_sec_radeon ?? 0;
  const cpuEmb = latest.embeds_per_sec_cpu ?? 0;
  const p95 = latest.p95_query_latency_ms ?? 0;
  const gpuMem = latest.gpu_mem_util_pct ?? 0;
  const deviceName = latest.gpu_device_name;
  const sensorBackend = latest.gpu_sensor_backend;
  const maxRate = Math.max(radeon, cpuEmb, 1);
  const radeonPct = (radeon / maxRate) * 100;
  const cpuPct = (cpuEmb / maxRate) * 100;

  return (
    <Card variant="outlined" sx={{ borderRadius: 2 }}>
      <CardContent>
        <Stack direction="row" spacing={1.5} alignItems="center" sx={{ mb: 1.5 }}>
          <Chip label={node} color="success" variant="outlined" />
          {deviceName && sensorBackend && (
            <Tooltip title={`${deviceName} · ${sensorBackend}`}>
              <DeveloperBoard sx={{ fontSize: 16, color: "error.main" }} />
            </Tooltip>
          )}
        </Stack>

        <Stack spacing={1}>
          <Box>
            <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 0.25 }}>
              <Stack direction="row" spacing={0.5} alignItems="center">
                <DeveloperBoard sx={{ fontSize: 14, color: "error.main" }} />
                <Typography variant="caption">Radeon</Typography>
              </Stack>
              <Typography variant="caption" fontWeight={600}>{radeon.toFixed(1)} embeds/s</Typography>
            </Stack>
            <LinearProgress variant="determinate" value={radeonPct} color="error" />
          </Box>

          <Box>
            <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 0.25 }}>
              <Stack direction="row" spacing={0.5} alignItems="center">
                <Memory sx={{ fontSize: 14 }} />
                <Typography variant="caption">CPU</Typography>
              </Stack>
              <Typography variant="caption" fontWeight={600}>{cpuEmb.toFixed(1)} embeds/s</Typography>
            </Stack>
            <LinearProgress variant="determinate" value={cpuPct} color="info" />
          </Box>

          <Stack direction="row" spacing={0.5} alignItems="center" sx={{ mt: 1 }}>
            <Sensors sx={{ fontSize: 14 }} />
            <Typography variant="caption" color="text.secondary">p95 latency: {p95.toFixed(1)} ms</Typography>
            <Typography variant="caption" color="text.secondary">·</Typography>
            <Typography variant="caption" color="text.secondary">GPU mem: {gpuMem.toFixed(0)}%</Typography>
          </Stack>
        </Stack>
      </CardContent>
    </Card>
  );
}

export function BenchPanel({ byNode, articles, activities, connected }: BenchPanelProps) {
  const [rocm, setRocm] = useState<RocmInfo | null>(null);
  const [llm, setLlm] = useState<LlmInfo | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date>(new Date());

  useEffect(() => {
    const fetchRocm = () =>
      fetch("/api/rocm-info")
        .then(r => r.json())
        .then(data => { setRocm(data); setLastUpdated(new Date()); })
        .catch(() => setRocm(null));
    fetchRocm();

    const pollLlm = () =>
      fetch("/api/llm-info")
        .then(r => r.json())
        .then(data => { setLlm(data); setLastUpdated(new Date()); })
        .catch(() => setLlm(null));

    pollLlm();
    const id = setInterval(pollLlm, 15_000);
    return () => clearInterval(id);
  }, []);

  const timeSinceUpdate = Math.floor((Date.now() - lastUpdated.getTime()) / 1000);

  const nodes = Object.keys(byNode);
  const allArticles = [...articles, ...activities];

  const byType: Record<string, number> = {};
  for (const a of allArticles) byType[a.type] = (byType[a.type] || 0) + 1;

  const byOrg: Record<string, number> = {};
  for (const a of allArticles) {
    const org = a.src_org || "unknown";
    byOrg[org] = (byOrg[org] || 0) + 1;
  }

  const reasoningCount = activities.filter(
    a => (a.payload?.activity_step as string) === "reasoning"
  ).length;

  const total = allArticles.length;

  return (
      <Stack spacing={3}>
      <Box sx={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <Typography variant="h1" sx={{ fontSize: "1.5rem" }}>
          Bench Panel
        </Typography>
        <Typography variant="caption" sx={{ color: "#5d6678", fontFamily: '"IBM Plex Mono", monospace' }}>
          updated {timeSinceUpdate}s ago
        </Typography>
      </Box>

      <Grid container spacing={2}>
        <Grid size={{ xs: 12, md: 6 }}>
          <GpuStatusCard rocm={rocm} />
        </Grid>
        <Grid size={{ xs: 12, md: 6 }}>
          <LlmStatusCard llm={llm} reasoningCount={reasoningCount} />
        </Grid>
      </Grid>

      <Card variant="outlined" sx={{ borderRadius: 2 }}>
        <CardContent>
          <Stack direction="row" spacing={1.5} alignItems="center" sx={{ mb: 1.5 }}>
            <Chip
              label={`WebSocket ${connected ? "connected" : "disconnected"}`}
              color={connected ? "success" : "error"}
              variant="outlined"
            />
          </Stack>
          <Grid container spacing={2}>
            <Grid size={{ xs: 12, sm: 4 }}>
              <Typography variant="caption" color="text.secondary">Total Articles</Typography>
              <Typography variant="h5" fontWeight={700}>{total}</Typography>
            </Grid>
            <Grid size={{ xs: 12, sm: 4 }}>
              <Typography variant="caption" color="text.secondary">Findings</Typography>
              <Typography variant="h5" fontWeight={700} color="error.main">{byType.finding || 0}</Typography>
            </Grid>
            <Grid size={{ xs: 12, sm: 4 }}>
              <Typography variant="caption" color="text.secondary">LLM Insights</Typography>
              <Typography variant="h5" fontWeight={700} color="secondary.main">{byType.insight || 0}</Typography>
            </Grid>
          </Grid>
        </CardContent>
      </Card>

      <Card variant="outlined" sx={{ borderRadius: 2 }}>
        <CardContent>
          <Typography fontWeight={700} variant="body2" sx={{ mb: 1.5 }}>By Organization</Typography>
          <Stack spacing={1}>
            {Object.entries(byOrg).map(([org, count]) => {
              const label = ORG_LABELS[org] || org;
              const pct = total > 0 ? (count / total) * 100 : 0;
              return (
                <Box key={org}>
                  <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 0.25 }}>
                    <Typography variant="body2">{label}</Typography>
                    <Typography variant="body2" color="text.secondary">{count} ({pct.toFixed(0)}%)</Typography>
                  </Stack>
                  <LinearProgress
                    variant="determinate"
                    value={pct}
                    color={org.includes("alpha") ? "primary" : "warning"}
                  />
                </Box>
              );
            })}
          </Stack>
        </CardContent>
      </Card>

      <Card variant="outlined" sx={{ borderRadius: 2 }}>
        <CardContent>
          <Typography fontWeight={700} variant="body2" sx={{ mb: 1.5 }}>By Article Type</Typography>
          <Stack direction="row" spacing={1} sx={{ flexWrap: "wrap" }}>
            {Object.entries(byType).sort((a, b) => b[1] - a[1]).map(([type, count]) => (
              <Chip
                key={type}
                label={`${type}: ${count}`}
                color={(TYPE_COLORS[type] as any) || "default"}
              />
            ))}
          </Stack>
        </CardContent>
      </Card>

      {nodes.length > 0 && (
        <Stack spacing={1.5}>
          <Typography fontWeight={700} variant="body2">Node Performance</Typography>
          {nodes.map(node => (
            <NodeMetricsCard key={node} node={node} samples={byNode[node]} />
          ))}
        </Stack>
      )}
    </Stack>
  );
}
