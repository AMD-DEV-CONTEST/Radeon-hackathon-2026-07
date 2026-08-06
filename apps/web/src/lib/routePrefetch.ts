/** Prefetch lazy route chunks on nav hover / idle — cuts "加载页面…" wait. */

const prefetched = new Set<string>()

const LOADERS: Record<string, () => Promise<unknown>> = {
  '/setup': () => import('../pages/Setup'),
  '/datasets': () => import('../pages/Datasets'),
  '/training': () => import('../pages/Training'),
  '/models': () => import('../pages/Models'),
  '/skills': () => import('../pages/Skills'),
  '/workflow': () => import('../components/workflow/WorkflowEditor'),
  '/robots/so101': () => import('../pages/RobotSO101'),
  '/robots/reachy_mini': () => import('../pages/RobotReachyMini'),
  '/robots/b601_rs': () => import('../pages/RobotB601'),
  '/robots/reachy_mini/apps': () => import('../pages/ReachyMiniApps'),
  '/teleop': () => import('../pages/Teleop'),
  '/inference': () => import('../pages/Inference'),
}

export function prefetchRoute(href: string): void {
  const path = href.split('?')[0]
  const loader = LOADERS[path]
  if (!loader || prefetched.has(path)) return
  prefetched.add(path)
  void loader()
}

export function prefetchCommonRoutes(): void {
  for (const path of ['/setup', '/datasets', '/training', '/models']) {
    prefetchRoute(path)
  }
}

/** Three.js chunk — used by robot 3D previews on /robots. */
export function prefetchThreeVendor(): void {
  if (prefetched.has('__three__')) return
  prefetched.add('__three__')
  void import('../components/features/UrdfViewer')
}
