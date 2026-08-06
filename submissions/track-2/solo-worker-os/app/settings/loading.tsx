function Shimmer({ className }: { className: string }) {
  return <div className={`animate-pulse rounded-lg bg-gray-200 dark:bg-white/[0.06] ${className}`} />;
}

export default function SettingsLoading() {
  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <Shimmer className="h-7 w-32" />
        <Shimmer className="h-4 w-56" />
      </div>
      <div className="glass rounded-2xl p-6 space-y-5">
        {[...Array(4)].map((_, i) => (
          <div key={i} className="flex items-center justify-between gap-4">
            <div className="space-y-2 flex-1">
              <Shimmer className="h-4 w-32" />
              <Shimmer className="h-3 w-48" />
            </div>
            <Shimmer className="h-7 w-12 rounded-full" />
          </div>
        ))}
      </div>
      <div className="glass rounded-2xl p-6 space-y-4">
        <Shimmer className="h-5 w-24" />
        {[...Array(3)].map((_, i) => (
          <div key={i} className="flex items-center gap-3">
            <Shimmer className="h-9 w-9 rounded-lg" />
            <div className="space-y-2 flex-1">
              <Shimmer className="h-4 w-40" />
              <Shimmer className="h-3 w-56" />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
