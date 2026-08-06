function Shimmer({ className }: { className: string }) {
  return <div className={`animate-pulse rounded-lg bg-gray-200 dark:bg-white/[0.06] ${className}`} />;
}

export default function PricingLoading() {
  return (
    <div className="space-y-8">
      <div className="text-center space-y-3">
        <Shimmer className="h-8 w-48 mx-auto" />
        <Shimmer className="h-4 w-72 mx-auto" />
      </div>
      <div className="grid grid-cols-1 gap-6 sm:grid-cols-3">
        {[...Array(3)].map((_, i) => (
          <div key={i} className="glass rounded-2xl p-8 space-y-4">
            <Shimmer className="h-6 w-24" />
            <Shimmer className="h-10 w-32" />
            <div className="space-y-2">
              {[...Array(5)].map((_, j) => (
                <Shimmer key={j} className="h-3 w-full" />
              ))}
            </div>
            <Shimmer className="h-10 w-full rounded-xl" />
          </div>
        ))}
      </div>
    </div>
  );
}
