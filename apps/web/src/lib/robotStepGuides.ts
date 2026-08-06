/** Goal / success / Copilot hints for robot setup flows. */

export interface RobotStepGuide {
  id: string
  label: string
  goal: string
  successSignal: string
  copilotHint: string
}

export const REACHY_MINI_STEPS: RobotStepGuide[] = [
  {
    id: 'connect',
    label: '连接设备',
    goal: '让 Local Agent 能访问 Reachy Mini 的本地守护进程',
    successSignal: '页面显示「已连接」，实时状态流有数据',
    copilotHint: 'Reachy 守护进程连不上 / Local Agent 未启动',
  },
  {
    id: 'service',
    label: '启动服务',
    goal: '启动机器人服务或虚拟模式，使电机可控',
    successSignal: '电机模式可读，Wake / Sleep 有响应',
    copilotHint: '启动服务失败 / 虚拟模式打不开',
  },
  {
    id: 'play',
    label: '播放动作',
    goal: '试播一个预设动作，确认运动正常',
    successSignal: '选中动作后机器人完成一次可见运动',
    copilotHint: '动作播放没反应 / 电机模式不对',
  },
  {
    id: 'record',
    label: '录制与进阶',
    goal: '（可选）录制自定义动作或进入虚拟模式调试',
    successSignal: '自定义动作保存成功，或虚拟模式可交互',
    copilotHint: '录制失败 / 自定义动作保存不了',
  },
]

/** Pick the best-matching guide step from runtime signals. */
export function inferReachyGuideStep(opts: {
  daemonOnline: boolean
  virtualActive: boolean
  streamConnected: boolean
  hasPlayedMove: boolean
}): RobotStepGuide {
  if (!opts.daemonOnline && !opts.virtualActive) return REACHY_MINI_STEPS[0]
  if (!opts.streamConnected) return REACHY_MINI_STEPS[1]
  if (!opts.hasPlayedMove) return REACHY_MINI_STEPS[2]
  return REACHY_MINI_STEPS[3]
}
