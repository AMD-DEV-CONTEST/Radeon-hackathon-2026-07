function Shimmer({ className }: { className: string }) {
  return <div className={`animate-pulse rounded-lg bg-gray-200 dark:bg-white/[0.06] ${className}`} />;
}

export default function TraceLoading() {
  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <Shimmer className="h-7 w-36" />
        <Shimmer className="h-4 w-60" />
      </div>
      <div className="glass rounded-2xl p-6 space-y-4">
        {[...Array(8)].map((_, i) => (
          <div key={i} className="flex items-center gap-4">
            <Shimmer className="h-8 w-8 rounded-full flex-shrink-0" />
            <div className="space-y-2 flex-1">
              <Shimmer className="h-4 w-3/4" />
              <Shimmer className="h-3 w-1/2" />
            </div>
            <Shimmer className="h-6 w-16 rounded-full" />
          </div>
        ))}
      </div>
    </div>
  );
}
