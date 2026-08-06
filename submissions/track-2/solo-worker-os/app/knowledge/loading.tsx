function Shimmer({ className }: { className: string }) {
  return <div className={`animate-pulse rounded-lg bg-gray-200 dark:bg-white/[0.06] ${className}`} />;
}

export default function KnowledgeLoading() {
  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <Shimmer className="h-7 w-40" />
        <Shimmer className="h-4 w-64" />
      </div>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {[...Array(6)].map((_, i) => (
          <div key={i} className="glass rounded-2xl p-5 space-y-3">
            <Shimmer className="h-5 w-3/4" />
            <Shimmer className="h-3 w-full" />
            <Shimmer className="h-3 w-5/6" />
            <div className="flex gap-2 pt-2">
              <Shimmer className="h-6 w-16 rounded-full" />
              <Shimmer className="h-6 w-12 rounded-full" />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
