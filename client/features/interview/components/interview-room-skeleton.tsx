import { cn } from "@/lib/utils";

function SkeletonBlock({ className }: { className?: string }) {
  return (
    <div
      className={cn("animate-pulse rounded-xl bg-white/5", className)}
      aria-hidden="true"
    />
  );
}

export function InterviewRoomSkeleton() {
  return (
    <div
      className="mx-auto grid max-w-7xl gap-6 px-4 py-6 sm:px-6 xl:grid-cols-[minmax(0,1fr)_320px]"
      role="status"
      aria-label="Loading interview room"
    >
      <div className="space-y-4">
        <SkeletonBlock className="h-80" />
        <SkeletonBlock className="h-48" />
        <SkeletonBlock className="h-72" />
      </div>
      <div className="space-y-4">
        <SkeletonBlock className="h-36" />
        <SkeletonBlock className="h-40" />
        <SkeletonBlock className="h-64" />
        <SkeletonBlock className="h-72" />
      </div>
      <span className="sr-only">Loading interview room...</span>
    </div>
  );
}
