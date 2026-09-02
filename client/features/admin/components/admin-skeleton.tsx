"use client";

export function AdminSkeleton() {
  return (
    <div
      className="mx-auto max-w-7xl space-y-6 px-4 py-6 sm:px-6"
      aria-busy="true"
      aria-label="Loading admin dashboard"
    >
      <div className="space-y-3">
        <div className="h-6 w-64 max-w-full animate-pulse rounded-full bg-white/10" />
        <div className="h-10 w-80 max-w-full animate-pulse rounded-xl bg-white/10" />
      </div>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {Array.from({ length: 4 }).map((_, index) => (
          <div
            key={`kpi-${index}`}
            className="h-32 animate-pulse rounded-2xl border border-white/10 bg-[#12121a]/80"
          />
        ))}
      </div>
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
        <div className="h-80 animate-pulse rounded-2xl border border-white/10 bg-[#12121a]/80" />
        <div className="h-80 animate-pulse rounded-2xl border border-white/10 bg-[#12121a]/80" />
      </div>
    </div>
  );
}
