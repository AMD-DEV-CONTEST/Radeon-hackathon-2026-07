import Box from "@mui/material/Box";
import CircularProgress from "@mui/material/CircularProgress";
import Typography from "@mui/material/Typography";
import { useCountUp } from "../hooks/useCountUp";

export function TrustRing({ pct }: { pct: number }) {
  const animatedValue = useCountUp(Math.round(pct * 100));
  const color = pct > 0.7 ? "#14b8a6" : pct > 0.4 ? "#f59e0b" : "#f43f5e";
  return (
    <Box sx={{ position: "relative", display: "inline-flex" }}>
      <CircularProgress
        variant="determinate"
        value={animatedValue}
        size={48}
        thickness={4}
        sx={{ color, "& .MuiCircularProgress-track": { color: "rgba(255,255,255,.06)" } }}
      />
      <Box sx={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center" }}>
        <Typography variant="caption" sx={{ fontWeight: 700, color, fontSize: "0.75rem" }}>
          {Math.round(animatedValue)}
        </Typography>
      </Box>
    </Box>
  );
}
