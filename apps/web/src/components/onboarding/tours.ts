export type TourVisual = 'overview' | 'wizard' | 'paths'
export type TourPath = 'hardware' | 'browse'

export interface TourStep {
  id: string
  target?: string
  route?: string
  title: string
  caption: string
  hint?: string
  placement?: 'top' | 'bottom' | 'left' | 'right'
  kind?: 'spotlight' | 'visual' | 'choice'
  visual?: TourVisual
  /** Which user path sees this step (default all). */
  path?: TourPath | 'all'
}

export interface TourDefinition {
  id: string
  storageKey: string
  steps: TourStep[]
}

export const GETTING_STARTED_TOUR: TourDefinition = {
  id: 'getting-started',
  storageKey: 'botversex_tour_v3',
  steps: [
    {
      id: 'intro',
      kind: 'visual',
      visual: 'overview',
      path: 'all',
      title: '30 秒看懂',
      caption: '网站管训练 · 机械臂在你电脑上',
    },
    {
      id: 'choose-path',
      kind: 'choice',
      path: 'all',
      route: '/robots',
      title: '你有机械臂吗？',
      caption: '选一个，我们带你走对应的路（必须点选）',
    },
    // —— 有机械臂 ——
    {
      id: 'nav-setup',
      kind: 'spotlight',
      path: 'hardware',
      target: '[data-tour="nav-setup"]',
      route: '/robots',
      title: '第 1 步 · Setup',
      caption: '在你电脑上装一次 Local Agent',
      hint: '只做一次；装好后本页变绿',
      placement: 'bottom',
    },
    {
      id: 'setup-install',
      kind: 'spotlight',
      path: 'hardware',
      target: '[data-tour="setup-install"]',
      route: '/setup',
      title: '在你电脑终端运行',
      caption: '复制命令 → 粘贴到终端（不是网站里点）',
      hint: '装完回 Setup 点「重新检测」',
      placement: 'top',
    },
    {
      id: 'setup-status',
      kind: 'spotlight',
      path: 'hardware',
      target: '[data-tour="setup-status"]',
      route: '/setup',
      title: '变绿 = 成功',
      caption: 'Agent 已连接，可以控机械臂了',
      hint: '然后点顶部 Robots',
      placement: 'bottom',
    },
    {
      id: 'pick-robot',
      kind: 'spotlight',
      path: 'hardware',
      target: '[data-tour="robot-so101"]',
      route: '/robots',
      title: '第 2 步 · 进入向导',
      caption: 'SO-101 四步：连接 → 遥操作 → 录制 → 训练',
      placement: 'top',
    },
    {
      id: 'pick-b601',
      kind: 'spotlight',
      path: 'hardware',
      target: '[data-tour="b601-card"]',
      route: '/robots',
      title: 'PCAN + LeRobot 实验室？',
      caption: 'B601-RS 实验台：CAN 从臂 + Star Arm 主臂，点这里',
      hint: '课题实验 / 论文复现',
      placement: 'top',
    },
    {
      id: 'wizard-flow',
      kind: 'visual',
      path: 'hardware',
      visual: 'wizard',
      route: '/robots',
      title: '向导里走 4 步',
      caption: '左侧步骤条，做完一步解锁下一步',
    },
    // —— 没机械臂 ——
    {
      id: 'robot-reachy',
      kind: 'spotlight',
      path: 'browse',
      target: '[data-tour="robot-reachy"]',
      route: '/robots',
      title: 'Reachy 虚拟模式',
      caption: '无需安装 Agent，直接体验演示',
      placement: 'top',
    },
    {
      id: 'browse-so101',
      kind: 'spotlight',
      path: 'browse',
      target: '[data-tour="robot-so101"]',
      route: '/robots',
      title: '也可以先看看 SO-101',
      caption: '进入向导浏览步骤（真录制仍需机械臂）',
      placement: 'top',
    },
    // —— 共用 ——
    {
      id: 'copilot',
      kind: 'spotlight',
      path: 'all',
      target: '[data-tour="copilot-fab"]',
      route: '/robots',
      title: '不懂就问',
      caption: '右下角「问问题」— 装完 Agent 下一步干嘛？',
      placement: 'left',
    },
  ],
}

export const TOURS: Record<string, TourDefinition> = {
  'getting-started': GETTING_STARTED_TOUR,
}

export function buildEffectiveSteps(
  steps: TourStep[],
  userPath: TourPath | null,
): TourStep[] {
  const intro = steps.filter((s) => s.id === 'intro')
  const choice = steps.filter((s) => s.kind === 'choice')
  if (!userPath) return [...intro, ...choice]
  const rest = steps.filter(
    (s) =>
      s.id !== 'intro' &&
      s.kind !== 'choice' &&
      (s.path === 'all' || s.path === userPath),
  )
  return [...intro, ...choice, ...rest]
}
