function Shimmer({ className, style }: { className: string; style?: React.CSSProperties }) {
  return <div className={`animate-pulse rounded-lg bg-gray-200 dark:bg-white/[0.06] ${className}`} style={style} />;
}

export default function ProjectsLoading() {
  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div className="space-y-3">
          <Shimmer className="h-5 w-20 rounded-full" />
          <Shimmer className="h-10 w-40" />
          <Shimmer className="h-4 w-24" />
        </div>
        <Shimmer className="h-9 w-32 rounded-xl" />
      </div>

      {/* Search + filter */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <Shimmer className="h-11 flex-1 rounded-xl" />
        <Shimmer className="h-11 w-72 rounded-xl" />
      </div>

      {/* Table skeleton */}
      <div className="glass overflow-hidden rounded-2xl">
        <div className="border-b border-gray-200 dark:border-white/[0.06] bg-gray-100 dark:bg-white/[0.02] px-5 py-3.5">
          <div className="flex gap-8">
            {[80, 60, 72, 56, 64, 48].map((w, i) => (
              <Shimmer key={i} className={`h-3 rounded w-${w}`} style={{ width: w }} />
            ))}
          </div>
        </div>
        {[...Array(6)].map((_, i) => (
          <div key={i} className="flex items-center gap-8 px-5 py-4 border-b border-gray-200 dark:border-white/[0.06] last:border-0">
            <Shimmer className="h-4 w-28" />
            <Shimmer className="h-4 w-20" />
            <Shimmer className="h-4 w-16 font-mono" />
            <Shimmer className="h-6 w-16 rounded-full" />
            <Shimmer className="h-4 w-20 font-mono" />
            <Shimmer className="h-4 w-14" />
          </div>
        ))}
      </div>
    </div>
  );
}
