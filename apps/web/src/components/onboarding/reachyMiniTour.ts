export type ReachyGuideMode = 'virtual' | 'hardware'

export interface ReachyGuideStep {
  id: string
  title: string
  caption?: string
  target?: string
  kind: 'visual' | 'spotlight'
  whenDone?: (ctx: ReachyGuideContext) => boolean
  /** Auto-run a demo when this step appears */
  demo?: 'play-hello'
  modes: ReachyGuideMode[]
}

export interface ReachyGuideContext {
  virtualActive: boolean
  daemonOnline: boolean
  streamConnected: boolean
  hasPlayedMove: boolean
}

/** Virtual mode: 3 steps, almost no text — show by doing */
const VIRTUAL_STEPS: ReachyGuideStep[] = [
  {
    id: 'virtual-btn',
    kind: 'spotlight',
    modes: ['virtual'],
    target: '[data-tour="reachy-virtual"]',
    title: '点「虚拟模式」',
    whenDone: (c) => c.virtualActive,
  },
  {
    id: 'play-panel',
    kind: 'spotlight',
    modes: ['virtual'],
    target: '[data-tour="reachy-play-panel"]',
    title: '点「播放」',
    demo: 'play-hello',
    whenDone: (c) => c.hasPlayedMove,
  },
  {
    id: 'viewer',
    kind: 'spotlight',
    modes: ['virtual'],
    target: '[data-tour="reachy-viewer"]',
    title: '看它动 · 拖一下旋转',
    whenDone: (c) => c.hasPlayedMove,
  },
]

const HARDWARE_STEPS: ReachyGuideStep[] = [
  {
    id: 'welcome',
    kind: 'visual',
    modes: ['hardware'],
    title: 'Reachy Mini',
    caption: '真机需 Setup + USB',
  },
  {
    id: 'daemon-btn',
    kind: 'spotlight',
    modes: ['hardware'],
    target: '[data-tour="reachy-daemon"]',
    title: '启动机器人',
    whenDone: (c) => c.daemonOnline,
  },
  {
    id: 'play-panel',
    kind: 'spotlight',
    modes: ['hardware'],
    target: '[data-tour="reachy-play-panel"]',
    title: '点「播放」',
    whenDone: (c) => c.hasPlayedMove,
  },
]

export const REACHY_GUIDE_STEPS: ReachyGuideStep[] = [...VIRTUAL_STEPS, ...HARDWARE_STEPS]

export function stepsForMode(mode: ReachyGuideMode): ReachyGuideStep[] {
  return mode === 'virtual' ? VIRTUAL_STEPS : HARDWARE_STEPS
}

export function stepIndexForId(mode: ReachyGuideMode, stepId: string): number {
  const steps = stepsForMode(mode)
  const idx = steps.findIndex((s) => s.id === stepId)
  return idx >= 0 ? idx : 0
}
