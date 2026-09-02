"use client";

export function ReportSkeleton() {
  return (
    <div
      className="mx-auto max-w-7xl space-y-6 px-4 py-6 sm:px-6"
      aria-busy="true"
      aria-label="Loading interview report"
    >
      <div className="space-y-3">
        <div className="h-7 w-40 animate-pulse rounded-full bg-white/10" />
        <div className="h-10 w-72 max-w-full animate-pulse rounded-xl bg-white/10" />
        <div className="h-4 w-96 max-w-full animate-pulse rounded-lg bg-white/5" />
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        {Array.from({ length: 3 }).map((_, index) => (
          <div
            key={`top-${index}`}
            className="h-[340px] animate-pulse rounded-2xl border border-white/10 bg-[#12121a]/80"
          />
        ))}
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <div className="h-[420px] animate-pulse rounded-2xl border border-white/10 bg-[#12121a]/80" />
        <div className="h-[420px] animate-pulse rounded-2xl border border-white/10 bg-[#12121a]/80" />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="h-80 animate-pulse rounded-2xl border border-white/10 bg-[#12121a]/80" />
        <div className="h-80 animate-pulse rounded-2xl border border-white/10 bg-[#12121a]/80" />
      </div>

      <div className="h-36 animate-pulse rounded-2xl border border-white/10 bg-[#12121a]/80" />
    </div>
  );
}
