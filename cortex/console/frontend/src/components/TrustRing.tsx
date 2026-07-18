import clsx from "clsx";

export interface TrustRingProps { pct: number; }

export function TrustRing({ pct }: TrustRingProps) {
  const v = Math.max(0, Math.min(100, Math.round(pct * 100)));
  const color = v >= 70 ? "text-green-500" : v >= 40 ? "text-yellow-500" : "text-red-500";
  return (
    <div className="relative w-12 h-12 inline-flex items-center justify-center">
      <svg viewBox="0 0 36 36" className="w-12 h-12">
        <circle cx="18" cy="18" r="16" fill="none" className="stroke-slate-700" strokeWidth="4" />
        <circle cx="18" cy="18" r="16" fill="none" className={clsx(color.replace("text-", "stroke-"))}
          strokeWidth="4" strokeDasharray={`${v}, 100`} strokeLinecap="round" transform="rotate(-90 18 18)" />
      </svg>
      <span className={clsx("absolute text-xs font-semibold", color)}>{v}</span>
    </div>
  );
}
