import Chip from "@mui/material/Chip";

export function SignatureStatus({ sig, label }: { sig?: string | null; label: string }) {
  const ok = Boolean(sig && sig.length > 0);
  return (
    <Chip
      label={`${ok ? "✓" : "•"} ${label}`}
      size="small"
      sx={{
        color: ok ? "#14b8a6" : "#6b7280",
        bgcolor: ok ? "rgba(20,184,166,0.1)" : "rgba(107,114,128,0.1)",
        fontWeight: 500, fontSize: "0.75rem", height: 24,
      }}
    />
  );
}
