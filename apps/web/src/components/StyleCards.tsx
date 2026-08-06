import { useAppStore } from '../store/appStore'
import type { StyleTemplate } from '../api/client'
import { GlobeIcon, SmileIcon, CoinIcon, HexagonIcon, SparkleIcon, BoxIcon } from './icons'

const STYLE_ICON: Record<string, React.ComponentType<{ className?: string }>> = {
  realistic_3d: GlobeIcon,
  cartoon_3d: SmileIcon,
  relief_coin: CoinIcon,
  lowpoly_3d: HexagonIcon,
  voxel_3d: BoxIcon,
  clay_3d: SmileIcon,
  sketch_3d: SparkleIcon,
  relief_embossed: CoinIcon,
  relief_lithophane: CoinIcon,
  relief_silhouette: CoinIcon,
}

interface StyleCardsProps {
  compact?: boolean
}

export function StyleCards({ compact }: StyleCardsProps) {
  const styles = useAppStore((s) => s.styles)
  const selectedStyleId = useAppStore((s) => s.selectedStyleId)
  const setSelectedStyleId = useAppStore((s) => s.setSelectedStyleId)

  // For landing page, only show 4 primary styles; director shows all.
  const landingIds = ['realistic_3d', 'cartoon_3d', 'relief_coin', 'lowpoly_3d']
  const displayStyles: StyleTemplate[] = compact
    ? landingIds.map((id) => styles.find((s) => s.id === id)).filter(Boolean) as StyleTemplate[]
    : styles

  if (styles.length === 0) {
    return (
      <div className="grid grid-cols-4 gap-3">
        {landingIds.map((id, i) => (
          <div
            key={id}
            className={`flex items-center gap-3 rounded-xl border border-neutral-300 bg-white/60 px-4 py-3 ${i === 0 ? 'ring-1 ring-neutral-800' : ''}`}
          >
            <div className="h-5 w-5 rounded-full bg-neutral-200" />
            <span className="text-sm font-medium text-neutral-700 capitalize">{id.replace('_', ' ')}</span>
          </div>
        ))}
      </div>
    )
  }

  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
      {displayStyles.map((style) => {
        const Icon = STYLE_ICON[style.id] || BoxIcon
        const active = selectedStyleId === style.id
        return (
          <button
            key={style.id}
            type="button"
            onClick={() => setSelectedStyleId(style.id)}
            className={`
              flex items-center gap-3 rounded-xl border px-4 py-3 text-left transition
              ${active
                ? 'border-neutral-800 bg-neutral-800 text-white shadow-sm'
                : 'border-neutral-300 bg-white/60 text-neutral-700 hover:border-neutral-500 hover:bg-white'}
            `}
          >
            <Icon className={`h-5 w-5 ${active ? 'text-white' : 'text-neutral-500'}`} />
            <span className="text-sm font-medium">{style.name}</span>
          </button>
        )
      })}
    </div>
  )
}
