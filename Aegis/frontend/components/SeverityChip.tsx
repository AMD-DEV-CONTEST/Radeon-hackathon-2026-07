const SEVERITY_COLORS: Record<string, string> = {
  sev1: "var(--sev1)",
  sev2: "var(--sev2)",
  sev3: "var(--sev3)",
  sev4: "var(--sev4)",
};

export function SeverityChip({ severity }: { severity: string }) {
  const color = SEVERITY_COLORS[severity] ?? "var(--sev4)";
  return (
    <span
      className="severity-chip"
      style={{ color, background: `${color}1a`, border: `1px solid ${color}55` }}
    >
      {severity}
    </span>
  );
}
