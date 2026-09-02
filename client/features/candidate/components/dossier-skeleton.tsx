import { cn } from "@/lib/utils";

function SkeletonBlock({ className }: { className?: string }) {
  return (
    <div
      className={cn("animate-pulse rounded-xl bg-white/5", className)}
      aria-hidden="true"
    />
  );
}

export function DossierSkeleton() {
  return (
    <div
      className="mx-auto grid max-w-7xl gap-6 px-4 py-6 sm:px-6 xl:grid-cols-[300px_minmax(0,1fr)_320px]"
      role="status"
      aria-label="Loading candidate dossier"
    >
      <div className="space-y-4">
        <SkeletonBlock className="h-72" />
        <SkeletonBlock className="h-40" />
        <SkeletonBlock className="h-48" />
      </div>
      <div className="space-y-4">
        <SkeletonBlock className="h-80" />
        <div className="grid gap-4 sm:grid-cols-2">
          <SkeletonBlock className="h-44" />
          <SkeletonBlock className="h-44" />
        </div>
      </div>
      <div className="space-y-4">
        <SkeletonBlock className="h-52" />
        <SkeletonBlock className="h-80" />
      </div>
      <span className="sr-only">Loading candidate dossier...</span>
    </div>
  );
}
