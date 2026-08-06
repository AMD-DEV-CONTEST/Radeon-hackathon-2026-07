import { LayoutGrid, List, Columns, Group, type LucideIcon } from 'lucide-react'

export type LayoutMode = 'grid' | 'list' | 'compact'
export type SortBy = 'status' | 'name' | 'agent_type'
export type GroupBy = 'none' | 'status' | 'agent_type'

export interface LayoutConfig {
  mode: LayoutMode
  sortBy: SortBy
  groupBy: GroupBy
}

const modeIcons: Record<LayoutMode, LucideIcon> = {
  grid: LayoutGrid,
  list: List,
  compact: Columns,
}

interface LayoutToolbarProps {
  config: LayoutConfig
  onChange: (config: LayoutConfig) => void
}

export function LayoutToolbar({ config, onChange }: LayoutToolbarProps) {
  const modes: { mode: LayoutMode; label: string }[] = [
    { mode: 'grid', label: 'Grid' },
    { mode: 'list', label: 'List' },
    { mode: 'compact', label: 'Compact' },
  ]

  const sorts: { sortBy: SortBy; label: string }[] = [
    { sortBy: 'status', label: 'Status' },
    { sortBy: 'name', label: 'Name' },
    { sortBy: 'agent_type', label: 'Type' },
  ]

  const groups: { groupBy: GroupBy; label: string }[] = [
    { groupBy: 'none', label: 'Flat' },
    { groupBy: 'status', label: 'By Status' },
    { groupBy: 'agent_type', label: 'By Agent' },
  ]

  return (
    <div className="layout-toolbar">
      <div className="layout-group">
        {modes.map(({ mode, label }) => {
          const Icon = modeIcons[mode]
          return (
            <button
              key={mode}
              className={`layout-btn ${config.mode === mode ? 'active' : ''}`}
              title={label}
              onClick={() => onChange({ ...config, mode })}
            >
              <Icon size={16} />
              <span>{label}</span>
            </button>
          )
        })}
      </div>

      <div className="layout-divider" />

      <div className="layout-group">
        <Group size={14} className="layout-label-icon" />
        {groups.map(({ groupBy, label }) => (
          <button
            key={groupBy}
            className={`layout-btn small ${config.groupBy === groupBy ? 'active' : ''}`}
            onClick={() => onChange({ ...config, groupBy })}
          >
            {label}
          </button>
        ))}
      </div>

      <div className="layout-divider" />

      <div className="layout-group">
        <span className="layout-label">Sort</span>
        {sorts.map(({ sortBy, label }) => (
          <button
            key={sortBy}
            className={`layout-btn small ${config.sortBy === sortBy ? 'active' : ''}`}
            onClick={() => onChange({ ...config, sortBy })}
          >
            {label}
          </button>
        ))}
      </div>
    </div>
  )
}
