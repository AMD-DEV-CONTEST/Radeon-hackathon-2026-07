"use client";

export function PresentationSkeleton() {
  return (
    <div
      className="mx-auto max-w-7xl space-y-6 px-4 py-6 sm:px-6"
      aria-busy="true"
      aria-label="Loading presentation dashboard"
    >
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <div className="h-44 animate-pulse rounded-2xl border border-white/10 bg-[#12121a]/80" />
        <div className="h-44 animate-pulse rounded-2xl border border-white/10 bg-[#12121a]/80" />
      </div>

      <div className="h-48 animate-pulse rounded-2xl border border-white/10 bg-[#12121a]/80" />

      <div className="grid gap-4 xl:grid-cols-3">
        {Array.from({ length: 3 }).map((_, index) => (
          <div
            key={`chart-${index}`}
            className="h-80 animate-pulse rounded-2xl border border-white/10 bg-[#12121a]/80"
          />
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="h-72 animate-pulse rounded-2xl border border-white/10 bg-[#12121a]/80" />
        <div className="h-72 animate-pulse rounded-2xl border border-white/10 bg-[#12121a]/80" />
      </div>
    </div>
  );
}
