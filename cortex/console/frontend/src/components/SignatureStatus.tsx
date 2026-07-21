import clsx from "clsx";

export interface SignatureStatusProps { sig?: string | null; label: string; }

export function SignatureStatus({ sig, label }: SignatureStatusProps) {
  const state = sig ? "valid" : "unsigned";
  const icon = sig ? "\u2713" : "\u2022";
  const color = sig ? "text-green-500" : "text-slate-400";
  return (
    <span data-testid={label === "agent" ? "sig-agent" : "sig-org"}
      className={clsx("inline-flex items-center gap-1 text-xs", color)}>
      <span>{icon}</span><span>{label}</span>
    </span>
  );
}
