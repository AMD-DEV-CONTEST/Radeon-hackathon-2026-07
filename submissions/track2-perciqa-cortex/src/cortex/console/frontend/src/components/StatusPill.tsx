import Box from "@mui/material/Box";
import Typography from "@mui/material/Typography";
import { keyframes } from "@mui/material/styles";

const pulseRing = keyframes`
  0% { transform: scale(1); opacity: 0.6; }
  50% { transform: scale(2.5); opacity: 0; }
  100% { transform: scale(1); opacity: 0; }
`;

export function StatusPill({ connected }: { connected: boolean }) {
  return (
    <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
      <Box sx={{ position: "relative", display: "flex" }}>
        <Box
          sx={{
            width: 8,
            height: 8,
            borderRadius: "50%",
            bgcolor: connected ? "#14b8a6" : "#f43f5e",
            boxShadow: connected
              ? "0 0 6px rgba(20,184,166,0.6)"
              : "0 0 6px rgba(244,63,94,0.6)",
            position: "relative",
            zIndex: 1,
          }}
        />
        {connected && (
          <Box
            sx={{
              position: "absolute",
              inset: "-4px",
              borderRadius: "50%",
              border: "2px solid rgba(20,184,166,0.4)",
              animation: `${pulseRing} 2s ease-out infinite`,
            }}
          />
        )}
      </Box>
      <Box>
        <Typography variant="body2" sx={{ color: "#9aa4b6", fontWeight: 500 }}>
          {connected ? "Connected" : "Disconnected"}
        </Typography>
        {connected && (
          <Typography
            variant="caption"
            sx={{ color: "#5d6678", display: "block", lineHeight: 1 }}
          >
            WebSocket
          </Typography>
        )}
      </Box>
    </Box>
  );
}
