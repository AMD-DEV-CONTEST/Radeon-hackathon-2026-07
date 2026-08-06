/* Shared skeleton shimmer */
function Shimmer({ className }: { className: string }) {
  return (
    <div className={`animate-pulse rounded-lg bg-gray-200 dark:bg-white/[0.06] ${className}`} />
  );
}

export default function DashboardLoading() {
  return (
    <div className="space-y-10">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div className="space-y-3">
          <Shimmer className="h-5 w-24 rounded-full" />
          <Shimmer className="h-10 w-64" />
          <Shimmer className="h-4 w-72" />
        </div>
        <Shimmer className="h-10 w-44 rounded-xl" />
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        {[...Array(4)].map((_, i) => (
          <div key={i} className="glass rounded-2xl p-5 space-y-3">
            <Shimmer className="h-3 w-20" />
            <Shimmer className="h-8 w-16" />
          </div>
        ))}
      </div>

      {/* Quick actions */}
      <div className="flex gap-2">
        {[...Array(4)].map((_, i) => (
          <Shimmer key={i} className="h-9 w-28 rounded-xl" />
        ))}
      </div>

      {/* Content */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2 space-y-3">
          <Shimmer className="h-5 w-32 mb-4" />
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {[...Array(4)].map((_, i) => (
              <div key={i} className="glass rounded-2xl p-5 space-y-3">
                <div className="flex justify-between">
                  <div className="space-y-2 flex-1">
                    <Shimmer className="h-4 w-28" />
                    <Shimmer className="h-3 w-20" />
                  </div>
                  <Shimmer className="h-6 w-16 rounded-full" />
                </div>
                <div className="flex justify-between pt-3 border-t border-gray-200 dark:border-white/[0.06]">
                  <Shimmer className="h-5 w-20" />
                  <Shimmer className="h-4 w-14" />
                </div>
              </div>
            ))}
          </div>
        </div>
        <div className="space-y-3">
          <Shimmer className="h-5 w-28 mb-4" />
          <div className="glass rounded-2xl p-4 space-y-3">
            {[...Array(5)].map((_, i) => (
              <div key={i} className="flex items-start gap-3 px-1 py-2">
                <Shimmer className="h-5 w-5 rounded-md flex-shrink-0 mt-0.5" />
                <div className="flex-1 space-y-1.5">
                  <Shimmer className="h-3 w-full" />
                  <Shimmer className="h-2.5 w-16" />
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
