"use client";

export function DashboardSkeleton() {
  return (
    <div
      className="mx-auto max-w-7xl space-y-6 px-4 py-6 sm:px-6"
      aria-busy="true"
      aria-label="Loading candidate dashboard"
    >
      <div className="space-y-3">
        <div className="h-6 w-48 animate-pulse rounded-full bg-white/10" />
        <div className="h-10 w-80 max-w-full animate-pulse rounded-xl bg-white/10" />
        <div className="h-4 w-96 max-w-full animate-pulse rounded-lg bg-white/5" />
      </div>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {Array.from({ length: 4 }).map((_, index) => (
          <div
            key={`metric-${index}`}
            className="h-32 animate-pulse rounded-2xl border border-white/10 bg-[#12121a]/80"
          />
        ))}
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
        <div className="h-[360px] animate-pulse rounded-2xl border border-white/10 bg-[#12121a]/80" />
        <div className="h-[360px] animate-pulse rounded-2xl border border-white/10 bg-[#12121a]/80" />
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        {Array.from({ length: 3 }).map((_, index) => (
          <div
            key={`mid-${index}`}
            className="h-72 animate-pulse rounded-2xl border border-white/10 bg-[#12121a]/80"
          />
        ))}
      </div>
    </div>
  );
}
