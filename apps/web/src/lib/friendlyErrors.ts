/** Map internal/dev errors to user-facing Chinese copy. */

export function friendlyRobotListError(raw: string): string {
  const s = raw.toLowerCase()
  if (s.includes('apps/realtime') || s.includes('实时服务') || s.includes('timeout') || s.includes('fetch')) {
    return '机器人列表暂时加载失败，已为你显示默认入口。可刷新页面，或点右下角「问问题」。'
  }
  if (s.includes('502') || s.includes('503')) {
    return '服务正在恢复中，请稍后再试。你可以先使用下方默认机器人入口。'
  }
  return '暂时无法加载机器人列表，请刷新或稍后再试。'
}

export function friendlyCopilotError(status?: number): string {
  if (status === 404) {
    return '助手服务未就绪（正在部署修复中）。你可以先看新手引导，或刷新页面后再试。'
  }
  if (status === 401) {
    return 'AI 问答需要登录；「系统诊断」无需登录即可使用。'
  }
  if (status === 429) {
    return '请求太频繁，请稍后再试。'
  }
  return '暂时无法连接助手，请检查网络后重试。'
}
