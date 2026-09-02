"use client";

export function SettingsSkeleton() {
  return (
    <div
      className="mx-auto max-w-7xl space-y-6 px-4 py-6 sm:px-6"
      aria-busy="true"
      aria-label="Loading settings"
    >
      <div className="space-y-3">
        <div className="h-6 w-48 animate-pulse rounded-full bg-white/10" />
        <div className="h-10 w-72 max-w-full animate-pulse rounded-xl bg-white/10" />
      </div>
      <div className="grid gap-6 lg:grid-cols-[280px_minmax(0,1fr)]">
        <div className="h-[520px] animate-pulse rounded-2xl border border-white/10 bg-[#12121a]/80" />
        <div className="h-[520px] animate-pulse rounded-2xl border border-white/10 bg-[#12121a]/80" />
      </div>
    </div>
  );
}
