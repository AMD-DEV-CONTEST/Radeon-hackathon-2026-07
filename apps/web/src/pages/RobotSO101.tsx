/**
 * SO-101 — two paths:
 *   mode=browser (default): WebSerial zero-install point-move
 *   mode=agent: classic Local Agent Setup wizard
 */
import { Link, useSearchParams } from 'react-router-dom'
import { ArrowLeft, Bot, Cable, Terminal } from 'lucide-react'
import { SetupProvider } from '../components/setup/SetupProvider'
import { SetupSidebar } from '../components/setup/SetupSidebar'
import { Step1Connect } from '../components/setup/steps/Step1Connect'
import { Step3Teleop } from '../components/setup/steps/Step3Teleop'
import { Step4Record } from '../components/setup/steps/Step4Record'
import { Step4Run } from '../components/setup/steps/Step4Run'
import { useSetup } from '../components/setup/SetupProvider'
import { BrowserDirectPanel } from '../components/so101/BrowserDirectPanel'
import { CommunityResources } from '../components/features/CommunityResources'
import { cn } from '../lib/utils'

function StepBody() {
  const { state } = useSetup()
  switch (state.currentStep) {
    case 'connect':
    case 'camera':
    case 'arm':
      return <Step1Connect />
    case 'teleop':
      return <Step3Teleop />
    case 'record':
      return <Step4Record />
    case 'run':
    case 'train':
    case 'inference':
      return <Step4Run />
    default:
      return <Step1Connect />
  }
}

function ModeTabs({ mode }: { mode: 'browser' | 'agent' }) {
  return (
    <div className="flex flex-wrap gap-2">
      <Link
        to="/robots/so101?mode=browser"
        className={cn(
          'inline-flex items-center gap-2 rounded-full px-4 py-2 text-sm font-medium transition-colors',
          mode === 'browser'
            ? 'bg-[var(--paper)] text-[var(--ink)]'
            : 'border border-white/10 text-stone-400 hover:text-[var(--paper)]',
        )}
      >
        <Cable className="h-3.5 w-3.5" />
        浏览器直连
      </Link>
      <Link
        to="/robots/so101?mode=agent"
        className={cn(
          'inline-flex items-center gap-2 rounded-full px-4 py-2 text-sm font-medium transition-colors',
          mode === 'agent'
            ? 'bg-[var(--paper)] text-[var(--ink)]'
            : 'border border-white/10 text-stone-400 hover:text-[var(--paper)]',
        )}
      >
        <Terminal className="h-3.5 w-3.5" />
        Local Agent（进阶）
      </Link>
    </div>
  )
}

export function RobotSO101() {
  const [params] = useSearchParams()
  const modeParam = params.get('mode')
  const mode: 'browser' | 'agent' = modeParam === 'agent' ? 'agent' : 'browser'

  return (
    <div className="container mx-auto space-y-5 px-4 py-6">
      <div className="bvx-page-header">
        <Link to="/robots" className="bvx-back-link">
          <ArrowLeft className="h-3.5 w-3.5" />
          机器人目录
        </Link>
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-[var(--ember)]/15 ring-1 ring-[var(--ember)]/25">
            <Bot className="h-5 w-5 text-[var(--ember)]" />
          </div>
          <div>
            <h1 className="bvx-page-title">SO-101</h1>
            <p className="bvx-page-subtitle">
              {mode === 'browser'
                ? '零安装：Chrome 里授权串口，扫舵机，拖滑条。'
                : '进阶：Local Agent 跑遥操、录制与训练闭环。'}
            </p>
          </div>
        </div>
        <ModeTabs mode={mode} />
      </div>

      {mode === 'browser' ? (
        <>
          <BrowserDirectPanel />
          <CommunityResources
            intro="SO-101 是 LeRobot 生态的开放机械臂，HF Hub 上有 58,000+ 个 lerobot 数据集录自它。遇到问题时先去社区找答案。"
            docs={[
              { label: 'LeRobot 官方文档（SO-101）', url: 'https://huggingface.co/docs/lerobot/so101' },
              { label: 'LeRobot GitHub', url: 'https://github.com/huggingface/lerobot' },
              { label: 'Seeed 中文组装指南', url: 'https://wiki.seeedstudio.com/cn/lerobot_so100m_new/' },
            ]}
            communities={[
              { label: 'LeRobot Discord', url: 'https://discord.gg/q8Dzzpym3f' },
              { label: 'GitHub Issues（求助主渠道）', url: 'https://github.com/huggingface/lerobot/issues' },
            ]}
            faqs={[
              {
                q: '扫不到舵机？',
                a: '最常见是供电不足——STS3215 额定 7.4V，需要独立电源。其次是 USB 数据线（部分线只充电不传数据）、串口被占用。页面上的「一键诊断」会帮你定位。',
              },
              {
                q: '校准时报 Incorrect status packet / checksum error？',
                a: '先查两件事：电机 ID 是否唯一化（lerobot-setup-motors，社区 issue #1244）；电源是否超压——STS3215 额定 7.4V，12V 会触发过压红灯（issue #1010）。',
              },
              {
                q: '个别舵机校准失败，其它正常？',
                a: '很可能是固件版本不一致：出厂有 3.9，LeRobot 要求 3.10，单个不匹配就破坏整臂校准（issue #1010）。',
              },
              {
                q: 'Linux 上校准失败？',
                a: '先试串口权限：sudo chmod 666 /dev/ttyACM0（issue #1342）。',
              },
              {
                q: '关节反向或角度不对？',
                a: '需要标定：跑 lerobot-calibrate 对齐 leader/follower 臂的零点与方向。',
              },
            ]}
          />
        </>
      ) : (
        <SetupProvider runtimeId="so101">
          <div className="mb-3 rounded-xl border border-white/10 bg-white/[0.02] px-4 py-3 text-xs text-stone-400">
            Local Agent 适合：主从遥操、长时间录制、本地存大数据集。只想先让关节动一下，请切回「浏览器直连」。
          </div>
          <div className="flex flex-col gap-5 md:flex-row">
            <SetupSidebar />
            <div className="min-w-0 flex-1">
              <StepBody />
            </div>
          </div>
        </SetupProvider>
      )}
    </div>
  )
}
