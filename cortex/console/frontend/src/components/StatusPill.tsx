import clsx from "clsx";

export interface StatusPillProps {
  connected: boolean;
}

export function StatusPill({ connected }: StatusPillProps) {
  return (
    <span className={clsx(
      "inline-flex items-center gap-1 px-3 py-1 rounded-full text-xs font-medium",
      connected ? "bg-green-900 text-green-300" : "bg-amber-900 text-amber-300"
    )}>
      <span className={clsx("w-2 h-2 rounded-full", connected ? "bg-green-400" : "bg-amber-400 animate-pulse")} />
      {connected ? "connected" : "reconnecting"}
    </span>
  );
}
