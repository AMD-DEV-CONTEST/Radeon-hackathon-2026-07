/**
 * /robots — product catalog surface (not a dashboard).
 * Composition: one hero (brand + one CTA + dominant 3D) → fleet editorial rows → quiet contact.
 */
import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowDown, ArrowRight, ArrowUpRight, Loader2 } from 'lucide-react'
import { LazyUrdfPreview } from '../components/features/LazyUrdfPreview'
import { HeroReachy } from '../components/virtual/HeroReachy'
import { listRobotManifests, type RobotManifest } from '../lib/robotApi'
import { FALLBACK_ROBOT_MANIFESTS } from '../lib/fallbackRobots'
import { friendlyRobotListError } from '../lib/friendlyErrors'
import { catalogMeta } from '../lib/robotCatalog'
import { B601_URDF_CATALOG } from '../lib/b601Urdf'
import { CONTACT } from '../config/contact'
import { useTourOptional } from '../components/onboarding/TourProvider'
import { prefetchThreeVendor } from '../lib/routePrefetch'
import { useT, getMessages, useLocale } from '../i18n'
import { cn } from '../lib/utils'

const FALLBACK_URDF: Record<string, string> = {
  so101: '/api/urdf/so101.urdf',
  reachy_mini: '/api/urdf/reachy_mini/reachy_mini.urdf',
  b601_rs: B601_URDF_CATALOG,
}

function createPreviewGate() {
  let resolve!: () => void
  const promise = new Promise<void>((r) => {
    resolve = r
  })
  return { promise, resolve }
}

function fleetCta(
  rt: RobotManifest,
  t: (key: string) => string,
): {
  primary: { to: string; label: string }
  secondary?: { to: string; label: string }
  /** Zero-install "play in browser" entry — every runtime has one. */
  play: { to: string; label: string }
} | null {
  const wizardPath = rt.ui?.route ?? null
  // Every runtime has a virtual play entry — pure frontend, no hardware.
  const play = { to: `/robots/${rt.runtimeId}/play`, label: t('robots.playNoHardware') }

  if (!wizardPath) {
    // Preview-only robots (AmazingHand / Unitree G1) — play is the only entry.
    return { primary: play, play }
  }
  if (rt.runtime_id === 'so101') {
    return {
      primary: { to: `${wizardPath}?mode=browser`, label: t('robots.browserDirect') },
      secondary: { to: `${wizardPath}?mode=agent`, label: t('robots.localAgent') },
      play,
    }
  }
  if (rt.runtime_id === 'b601_rs') {
    return {
      primary: { to: wizardPath, label: t('robots.getStarted') },
      secondary: { to: `${wizardPath}?tab=workspace`, label: t('robots.workspace') },
      play,
    }
  }
  if (rt.capabilities?.virtual) {
    // Reachy Mini: cloud virtual is richer than the generic frontend play.
    return {
      primary: { to: `${wizardPath}?guide=virtual&play=1`, label: t('robots.playVirtual') },
      secondary: { to: wizardPath, label: t('robots.haveHardware') },
      play,
    }
  }
  if (rt.preview) {
    return {
      primary: { to: wizardPath, label: t('robots.viewBoundary') },
      play,
    }
  }
  if (rt.runtime_id === 'lekiwi') {
    return {
      primary: { to: wizardPath, label: t('robots.enterWorkspace') },
      play,
    }
  }
  return {
    primary: { to: wizardPath, label: t('robots.enterWizard') },
    play,
  }
}

export function Robots() {
  const t = useT()
  const locale = useLocale()
  const catalog = getMessages(locale).catalog
  const tour = useTourOptional()
  const [robots, setRobots] = useState<RobotManifest[]>(FALLBACK_ROBOT_MANIFESTS)
  const [err, setErr] = useState<string | null>(null)
  const [syncing, setSyncing] = useState(true)
  const previewGate = useMemo(() => createPreviewGate(), [])
  const b601PreviewGate = useMemo(() => createPreviewGate(), [])
  const [so101PreviewDone, setSo101PreviewDone] = useState(false)

  useEffect(() => {
    prefetchThreeVendor()

    const fallbackTimer = window.setTimeout(() => {
      setSo101PreviewDone(true)
      previewGate.resolve()
      b601PreviewGate.resolve()
    }, 45_000)

    void (async () => {
      try {
        const body = await listRobotManifests()
        setRobots(body.robots)
        setErr(null)
        if (!body.robots.some((r) => r.runtime_id === 'so101')) {
          setSo101PreviewDone(true)
          previewGate.resolve()
          b601PreviewGate.resolve()
        }
      } catch (e) {
        setErr(friendlyRobotListError((e as Error).message))
      } finally {
        setSyncing(false)
      }
    })()

    return () => window.clearTimeout(fallbackTimer)
  }, [previewGate, b601PreviewGate])

  const sortedRobots = useMemo(
    () =>
      [...robots].sort((a, b) => {
        const pa = catalogMeta(a.runtime_id)?.previewPriority ?? 99
        const pb = catalogMeta(b.runtime_id)?.previewPriority ?? 99
        return pa - pb
      }),
    [robots],
  )

  const availableCount = sortedRobots.filter((r) => !r.preview).length
  const labsCount = sortedRobots.filter((r) => r.preview).length

  return (
    <div className="relative w-full overflow-x-hidden bg-[var(--ink)] text-[var(--paper)]">
      {/* ─── Hero: one composition ─── */}
      <section className="robots-hero-glow relative min-h-[min(75vh,760px)]">
        <div className="robots-grid absolute inset-0" aria-hidden />
        <div className="robots-noise absolute inset-0" aria-hidden />

        <div className="relative mx-auto grid min-h-[min(75vh,760px)] max-w-7xl lg:grid-cols-[minmax(0,1.05fr)_minmax(0,1fr)]">
          <div className="flex flex-col justify-center px-5 pb-16 pt-10 sm:px-8 lg:px-10 lg:pb-24 lg:pt-16">
            <p className="robots-rise font-display text-[11px] font-semibold uppercase tracking-[0.28em] text-[var(--ember)]">
              BotverseX
            </p>
            <h1 className="robots-rise robots-rise-delay-1 font-display mt-5 max-w-[16ch] text-[clamp(2.6rem,6.5vw,4.75rem)] font-bold leading-[0.95] tracking-[-0.04em] text-[var(--paper)]">
              {t('robots.heroLine1')}
              <br />
              <span className="bg-gradient-to-r from-[var(--paper)] via-[#ffd0b0] to-[var(--ember)] bg-clip-text text-transparent">
                {t('robots.heroLine2')}
              </span>
            </h1>
            <p className="robots-rise robots-rise-delay-2 mt-6 max-w-md text-[15px] leading-relaxed text-slate-400 sm:text-base">
              {t('robots.heroBody')}
            </p>

            <div className="robots-rise robots-rise-delay-3 mt-9 flex flex-col items-start gap-3 sm:flex-row sm:flex-wrap sm:items-center">
              {/* 主入口 = 虚拟 Reachy：第一次来的访客大多没有真机，先让所有人「30 秒玩上」；
                  真机浏览器直连降为次级并标注需要硬件（M47，用户指令：首次访客都能玩） */}
              <Link
                to="/robots/reachy_mini?guide=virtual&play=1"
                data-tour="hero-virtual-cta"
                className="robots-cta text-[15px]"
              >
                {t('robots.ctaPlay')}
                <ArrowRight className="h-4 w-4" />
              </Link>
              <Link
                to="/robots/so101?mode=browser"
                className="inline-flex items-center gap-2 rounded-full border border-white/12 bg-white/[0.02] px-5 py-2.5 text-sm font-medium text-[var(--paper)] backdrop-blur-sm transition-colors hover:border-[var(--ember)]/45 hover:bg-white/[0.05]"
              >
                {t('robots.ctaSo101')}
                <span className="text-[10px] opacity-60">需 SO-101 真机</span>
              </Link>
              <a
                href="#fleet"
                className="group inline-flex items-center gap-2 text-sm text-slate-500 transition-colors hover:text-slate-300"
              >
                {t('robots.ctaOther')}
                <ArrowDown className="h-3.5 w-3.5 transition-transform group-hover:translate-y-0.5" />
              </a>
            </div>

            {tour && (
              <button
                type="button"
                onClick={() => tour.startTour()}
                className="robots-rise robots-rise-delay-3 mt-8 text-left text-xs text-slate-500 underline-offset-4 transition-colors hover:text-slate-300 hover:underline"
              >
                {t('robots.tourHint')}
              </button>
            )}

            {syncing && (
              <p className="mt-6 inline-flex items-center gap-1.5 text-[11px] text-slate-600">
                <Loader2 className="h-3 w-3 animate-spin" />
                {t('robots.syncing')}
              </p>
            )}
          </div>

          <div className="relative min-h-[320px] lg:min-h-0">
            <div
              className="pointer-events-none absolute inset-[8%] rounded-full bg-[radial-gradient(circle,rgba(232,93,28,0.16)_0%,transparent_68%)] blur-2xl"
              aria-hidden
            />
            <div className="robots-stage-drift absolute inset-0 lg:inset-y-8 lg:right-4 lg:left-0">
              <HeroReachy />
            </div>
            <div
              className="pointer-events-none absolute inset-x-0 bottom-0 h-32 bg-gradient-to-t from-[var(--ink)] to-transparent lg:hidden"
              aria-hidden
            />
          </div>
        </div>

        <div className="pointer-events-none absolute inset-x-0 bottom-0 h-px bg-gradient-to-r from-transparent via-[var(--ember)]/35 to-transparent" />
      </section>

      {err && (
        <div className="mx-auto max-w-7xl px-5 py-4 sm:px-8 lg:px-10">
          <div className="flex flex-wrap items-center justify-between gap-2 border border-amber-500/25 bg-amber-500/5 px-4 py-3 text-sm text-amber-100/90">
            <span>{err}</span>
            <button type="button" className="text-xs underline" onClick={() => window.location.reload()}>
              {t('common.refresh')}
            </button>
          </div>
        </div>
      )}

      {/* ─── Fleet: one job — pick hardware ─── */}
      <section id="fleet" className="relative scroll-mt-20 border-t border-white/[0.06] bg-[linear-gradient(180deg,#05070c_0%,#070b14_100%)]">
        <div className="mx-auto max-w-7xl px-5 py-16 sm:px-8 sm:py-20 lg:px-10">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <p className="font-display text-[11px] font-semibold uppercase tracking-[0.24em] text-slate-500">
                {t('robots.fleetEyebrow')}
              </p>
              <h2 className="font-display mt-2 text-3xl font-bold tracking-tight text-[var(--paper)] sm:text-4xl">
                {t('robots.fleetTitle')}
              </h2>
              <p className="mt-3 max-w-lg text-sm leading-relaxed text-slate-400">
                {t('robots.fleetBody')}
              </p>
            </div>
            <p className="font-display text-sm tabular-nums text-slate-500">
              <span className="text-[var(--paper)]">{availableCount}</span> {t('robots.available')}
              <span className="mx-2 opacity-30">·</span>
              <span className="text-[var(--paper)]">{labsCount}</span> {t('robots.labs')}
            </p>
          </div>

          <ul className="mt-12 divide-y divide-white/[0.06] border-y border-white/[0.06]">
            {sortedRobots.map((rt, index) => {
              const meta = catalogMeta(rt.runtime_id)
              const copy = catalog[rt.runtime_id]
              const isReachy = rt.runtime_id === 'reachy_mini'
              const isB601 = rt.runtime_id === 'b601_rs'
              const urdfUrl = isB601
                ? FALLBACK_URDF.b601_rs
                : rt.urdf_url || FALLBACK_URDF[rt.runtime_id]
              const cta = fleetCta(rt, t)
              const tourAnchor =
                rt.runtime_id === 'so101'
                  ? 'robot-so101'
                  : rt.runtime_id === 'reachy_mini'
                    ? 'robot-reachy'
                    : rt.runtime_id === 'b601_rs'
                      ? 'b601-card'
                      : undefined

              return (
                <li
                  key={rt.runtime_id}
                  data-tour={tourAnchor}
                  className={cn(
                    'robots-fleet-row group grid gap-6 px-1 py-8 sm:px-3 md:grid-cols-[minmax(0,220px)_minmax(0,1fr)_auto] md:items-center md:gap-8',
                    index === 0 && 'pt-6',
                  )}
                >
                  <div className="relative aspect-[4/3] overflow-hidden rounded-xl border border-white/[0.06] bg-[#0a1018] md:aspect-square">
                    {urdfUrl ? (
                      <LazyUrdfPreview
                        urdfUrl={urdfUrl}
                        runtimeId={rt.runtime_id}
                        stage
                        deferUntil={
                          isB601
                            ? b601PreviewGate.promise
                            : isReachy && !so101PreviewDone
                              ? previewGate.promise
                              : null
                        }
                        onFullyLoaded={() => {
                          if (rt.runtime_id === 'so101') {
                            setSo101PreviewDone(true)
                            previewGate.resolve()
                            if (!robots.some((r) => r.runtime_id === 'reachy_mini')) {
                              b601PreviewGate.resolve()
                            }
                          }
                          if (rt.runtime_id === 'reachy_mini') {
                            b601PreviewGate.resolve()
                          }
                        }}
                        className="!absolute inset-0 h-full w-full max-w-none rounded-none border-0"
                      />
                    ) : (
                      <div className="flex h-full items-center justify-center text-xs text-slate-600">
                        {t('robots.noPreview')}
                      </div>
                    )}
                  </div>

                  <div className="min-w-0">
                    <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                      <h3 className="font-display text-xl font-semibold tracking-tight text-[var(--paper)] sm:text-2xl">
                        {copy?.title ?? meta?.title ?? rt.display_name}
                      </h3>
                      <span
                        className={cn(
                          'text-[11px] font-medium tracking-wide',
                          rt.preview ? 'text-sky-300/80' : 'text-emerald-300/80',
                        )}
                      >
                        {rt.preview ? 'Labs' : t('robots.ready')}
                      </span>
                    </div>
                    <p className="mt-1 text-sm text-slate-500">
                      {copy?.subtitle ?? meta?.subtitle ?? rt.robot_type}
                    </p>
                    {(copy?.blurb ?? meta?.blurb) && (
                      <p className="mt-3 max-w-xl text-sm leading-relaxed text-slate-400">
                        {copy?.blurb ?? meta?.blurb}
                      </p>
                    )}
                  </div>

                  <div className="flex flex-col items-stretch gap-2 md:items-end">
                    {cta ? (
                      <>
                        <Link
                          to={cta.primary.to}
                          className="inline-flex items-center justify-center gap-1.5 rounded-full bg-[var(--paper)] px-5 py-2.5 text-sm font-semibold text-[var(--ink)] transition-transform hover:-translate-y-0.5"
                        >
                          {cta.primary.label}
                          <ArrowUpRight className="h-3.5 w-3.5" />
                        </Link>
                        <div className="flex flex-col gap-1 md:items-end">
                          <Link
                            to={cta.play.to}
                            className="text-center text-xs text-[var(--ember)] underline-offset-2 transition-colors hover:text-[var(--paper)] hover:underline md:text-right"
                          >
                            {cta.play.label}
                          </Link>
                          {cta.secondary && (
                            <Link
                              to={cta.secondary.to}
                              className="text-center text-xs text-slate-500 transition-colors hover:text-slate-300 md:text-right"
                            >
                              {cta.secondary.label}
                            </Link>
                          )}
                        </div>
                      </>
                    ) : (
                      <span className="text-xs text-slate-600">{t('common.comingSoon')}</span>
                    )}
                  </div>
                </li>
              )
            })}
          </ul>
        </div>
      </section>

      {/* ─── Contact: one quiet strip, not a card wall ─── */}
      <section className="border-t border-white/[0.06]">
        <div className="mx-auto flex max-w-7xl flex-col gap-6 px-5 py-14 sm:flex-row sm:items-end sm:justify-between sm:px-8 lg:px-10">
          <div>
            <p className="font-display text-[11px] font-semibold uppercase tracking-[0.24em] text-slate-500">
              {t('robots.contactEyebrow')}
            </p>
            <h2 className="font-display mt-2 text-2xl font-bold tracking-tight">{t('robots.contactTitle')}</h2>
            <p className="mt-2 max-w-md text-sm text-slate-400">{t('robots.contactBody')}</p>
          </div>
          <div className="flex flex-wrap gap-x-6 gap-y-2 text-sm">
            <a
              href={`https://t.me/${CONTACT.telegram.replace('@', '')}`}
              target="_blank"
              rel="noopener noreferrer"
              className="text-slate-300 underline-offset-4 hover:text-[var(--ember)] hover:underline"
            >
              Telegram {CONTACT.telegram}
            </a>
            <a
              href={`https://x.com/${CONTACT.twitter.replace('@', '')}`}
              target="_blank"
              rel="noopener noreferrer"
              className="text-slate-300 underline-offset-4 hover:text-[var(--ember)] hover:underline"
            >
              X {CONTACT.twitter}
            </a>
            <span className="text-slate-500">微信 {CONTACT.wechat}</span>
          </div>
        </div>
        <div className="border-t border-white/[0.04] py-5 text-center text-[11px] text-slate-600">
          © {new Date().getFullYear()} BotverseX
        </div>
      </section>
    </div>
  )
}
