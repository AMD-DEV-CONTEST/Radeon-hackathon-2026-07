function Shimmer({ className }: { className: string }) {
  return <div className={`animate-pulse rounded-lg bg-gray-200 dark:bg-white/[0.06] ${className}`} />;
}

export default function ChatLoading() {
  return (
    <div className="space-y-5">
      <div className="space-y-3">
        <Shimmer className="h-5 w-16 rounded-full" />
        <Shimmer className="h-10 w-32" />
        <Shimmer className="h-4 w-80" />
      </div>
      <div className="flex h-[calc(100vh-10rem)] flex-col gap-3">
        <div className="glass flex-1 rounded-2xl p-5">
          <div className="flex h-full items-center justify-center">
            <div className="space-y-3 text-center">
              <div className="mx-auto h-16 w-16 animate-pulse rounded-2xl border border-amber-400/20 bg-amber-400/5" />
              <Shimmer className="mx-auto h-4 w-48" />
              <Shimmer className="mx-auto h-3 w-64" />
            </div>
          </div>
        </div>
        <Shimmer className="h-16 w-full rounded-2xl" />
      </div>
    </div>
  );
}
