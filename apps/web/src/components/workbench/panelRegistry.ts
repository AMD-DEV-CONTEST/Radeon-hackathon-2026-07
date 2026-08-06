/**
 * T2-2 · 通用工作台面板注册表
 *
 * 目标：让"新增一台机器人"的边际成本从 ~6000 行降到 ~200 行。
 *
 *   capability_tags: ["teleop", "record", "calibrate", "camera", "joints_live"]
 *          ↓
 *   GenericWorkbench → 按 capability_tags 渲染对应 Panel
 *
 * 一台新机型 = 1 条 manifest 条目 + 1 个 ~200 行的 runtime adapter + 0 个新页面 + 0 个新 API 路由。
 *
 * 当前阶段：仅建立注册表基础设施。LeKiwi 是试验田，下一步把它的面板逐个迁移过来；
 * Reachy 跟上；B601 最后迁或永不迁（4862 行 b601.py + 5023 行组件，风险高收益低）。
 *
 * 见 progress/M28-consolidation-execution-plan.md T2-2。
 */
import type { ComponentType } from 'react'
import type { RobotManifest } from '../../lib/robotApi'

export type WorkbenchPanelId =
  | 'connect'
  | 'teleop'
  | 'record'
  | 'calibrate'
  | 'camera'
  | 'joints_live'
  | 'inference'
  | 'handshake_loop'

export interface WorkbenchPanelProps {
  /** 当前机型的 manifest，面板可读 capability_tags / urdf_url / transport 等。 */
  manifest: RobotManifest
}

export interface WorkbenchPanelRegistration {
  id: WorkbenchPanelId
  title: string
  /** 决定该面板是否对某机型渲染。默认按 capability_tags 包含判断。 */
  matches: (manifest: RobotManifest) => boolean
  /** 面板组件，接收 manifest 作为 prop。 */
  component: ComponentType<WorkbenchPanelProps>
  /** 渲染顺序，越小越靠前。同序按 id 字母序。 */
  order?: number
}

const REGISTRY = new Map<WorkbenchPanelId, WorkbenchPanelRegistration>()

export function registerWorkbenchPanel(reg: WorkbenchPanelRegistration): void {
  REGISTRY.set(reg.id, reg)
}

export function getWorkbenchPanel(id: WorkbenchPanelId): WorkbenchPanelRegistration | undefined {
  return REGISTRY.get(id)
}

export function listWorkbenchPanels(): WorkbenchPanelRegistration[] {
  return Array.from(REGISTRY.values())
}

/**
 * 按 manifest 的 capability_tags 选出该机型应渲染的面板，按 order 升序排序。
 * capability_tags 在 manifest 里是字符串数组（如 ["teleop", "record", "camera"]），
 * 面板 id 与之同名即默认匹配；面板可通过 matches() 自定义更复杂的判定。
 *
 * connect 面板永远渲染（每台机器都需要连接步骤）。
 */
export function panelsForManifest(manifest: RobotManifest): WorkbenchPanelRegistration[] {
  const tags = new Set<string>(
    (manifest as { capability_tags?: string[] }).capability_tags ?? [],
  )
  return listWorkbenchPanels()
    .filter((reg) => reg.matches(manifest))
    .filter((reg) => tags.has(reg.id) || reg.id === 'connect')
    .sort((a, b) => (a.order ?? 100) - (b.order ?? 100))
}

/**
 * capability_tags 默认匹配器工厂：当 manifest 的 capability_tags 包含 panelId 时返回 true。
 */
export function matchByCapabilityTag(panelId: WorkbenchPanelId) {
  return (manifest: RobotManifest): boolean => {
    const tags = (manifest as { capability_tags?: string[] }).capability_tags ?? []
    return tags.includes(panelId)
  }
}
