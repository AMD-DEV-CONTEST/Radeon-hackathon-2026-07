function Shimmer({ className }: { className: string }) {
  return <div className={`animate-pulse rounded-lg bg-gray-200 dark:bg-white/[0.06] ${className}`} />;
}

export default function ProjectDetailLoading() {
  return (
    <div className="space-y-6">
      {/* header */}
      <div className="flex items-start justify-between gap-4">
        <div className="space-y-3">
          <Shimmer className="h-7 w-48" />
          <div className="flex gap-3">
            <Shimmer className="h-6 w-20 rounded-full" />
            <Shimmer className="h-6 w-16 rounded-full" />
          </div>
        </div>
        <Shimmer className="h-10 w-32 rounded-xl" />
      </div>
      {/* workflow tracker */}
      <div className="glass rounded-2xl p-6">
        <div className="flex items-center gap-2">
          {[...Array(6)].map((_, i) => (
            <div key={i} className="flex-1 space-y-2">
              <Shimmer className="h-10 w-full rounded-xl" />
              <Shimmer className="h-3 w-full" />
            </div>
          ))}
        </div>
      </div>
      {/* content grid */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2 glass rounded-2xl p-6 space-y-4">
          <Shimmer className="h-5 w-32" />
          {[...Array(5)].map((_, i) => (
            <div key={i} className="flex gap-3">
              <Shimmer className="h-8 w-8 rounded-lg flex-shrink-0" />
              <div className="space-y-2 flex-1">
                <Shimmer className="h-4 w-3/4" />
                <Shimmer className="h-3 w-1/2" />
              </div>
            </div>
          ))}
        </div>
        <div className="glass rounded-2xl p-6 space-y-4">
          <Shimmer className="h-5 w-24" />
          {[...Array(4)].map((_, i) => (
            <div key={i} className="space-y-2">
              <Shimmer className="h-4 w-20" />
              <Shimmer className="h-6 w-full rounded-lg" />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
