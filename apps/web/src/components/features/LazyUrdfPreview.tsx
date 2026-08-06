import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import { Loader2 } from 'lucide-react'
import { catalogMeta } from '../../lib/robotCatalog'
import { REACHY_MINI_HIDDEN_LINKS } from '../../lib/reachyVirtualPreview'
import { cn } from '../../lib/utils'

const UrdfViewer = lazy(() =>
  import('./UrdfViewer').then((m) => ({ default: m.UrdfViewer })),
)

interface LazyUrdfPreviewProps {
  urdfUrl: string
  runtimeId?: string
  className?: string
  deferUntil?: Promise<void> | null
  onFullyLoaded?: () => void
  /** false = show skeleton while meshes stream in (faster perceived load) */
  waitForMeshes?: boolean
  /** Stage embed: full area, load immediately (no catalog card chrome) */
  stage?: boolean
}

function LoadingPreview({ label }: { label: string }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-2 bg-[#0b0f1a] text-[hsl(var(--muted-foreground))]">
      <Loader2 className="h-5 w-5 animate-spin text-[hsl(var(--primary))]" />
      <span className="text-[11px]">{label}</span>
    </div>
  )
}

/**
 * Catalog 3D preview — contained in a fixed box, pointer-events-none so it never blocks the CTA below.
 * Meshes load fully before reveal (no piece-by-piece pop-in).
 */
export function LazyUrdfPreview({
  urdfUrl,
  runtimeId,
  className,
  deferUntil,
  onFullyLoaded,
  waitForMeshes = true,
  stage = false,
}: LazyUrdfPreviewProps) {
  const rootRef = useRef<HTMLDivElement>(null)
  const [visible, setVisible] = useState(stage)
  const [ready, setReady] = useState(!deferUntil)
  const onLoadedRef = useRef(onFullyLoaded)
  onLoadedRef.current = onFullyLoaded

  const meta = runtimeId ? catalogMeta(runtimeId) : null
  const meshConcurrency = meta?.meshConcurrency ?? 10

  useEffect(() => {
    if (!deferUntil) {
      setReady(true)
      return
    }
    let cancelled = false
    void deferUntil.finally(() => {
      if (!cancelled) setReady(true)
    })
    return () => {
      cancelled = true
    }
  }, [deferUntil])

  useEffect(() => {
    if (!ready || stage) return
    const el = rootRef.current
    if (!el) return

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry?.isIntersecting) {
          setVisible(true)
          observer.disconnect()
        }
      },
      { rootMargin: '80px', threshold: 0.05 },
    )
    observer.observe(el)
    return () => observer.disconnect()
  }, [ready, urdfUrl, stage])

  const isB601 = urdfUrl.includes('b601_rs')
  const isReachy = urdfUrl.includes('reachy_mini')

  return (
    <div
      ref={rootRef}
      className={cn(
        stage
          ? 'relative isolate h-full w-full overflow-hidden'
          : 'relative isolate h-[220px] w-full max-w-[360px] overflow-hidden rounded-xl border border-[hsl(var(--border))]/80 bg-[#0b0f1a] shadow-inner pointer-events-none',
        className,
      )}
    >
      {!ready || !visible ? (
        <LoadingPreview label={!ready ? '稍候…' : '加载 3D 模型…'} />
      ) : (
        <Suspense fallback={<LoadingPreview label="加载渲染器…" />}>
          <UrdfViewer
            urdfUrl={urdfUrl}
            className="!min-h-0 h-full"
            waitForMeshes={waitForMeshes}
            hideMeshProgress={waitForMeshes || stage}
            meshConcurrency={meshConcurrency}
            hiddenLinks={isReachy ? REACHY_MINI_HIDDEN_LINKS : undefined}
            onFullyLoaded={() => onLoadedRef.current?.()}
            cameraPosition={
              (stage ? meta?.stageCameraPosition : meta?.cameraPosition) ??
              meta?.cameraPosition ??
              (isReachy
                ? [0.35, 0.35, 0.35]
                : isB601
                  ? [0.55, 0.45, 0.55]
                  : [0.6, 0.6, 0.6])
            }
            orbitTarget={
              meta?.orbitTarget ??
              (isReachy ? [0, 0.12, 0] : isB601 ? [0, 0.15, 0] : [0, 0.1, 0])
            }
          />
        </Suspense>
      )}
    </div>
  )
}
