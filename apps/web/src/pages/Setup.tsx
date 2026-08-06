import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Card, CardContent } from '../components/ui/card'
import { Button, buttonVariants } from '../components/ui/button'
import { cn } from '../lib/utils'
import {
  ArrowRight,
  CheckCircle2,
  Copy,
  ExternalLink,
  Loader2,
  ShieldCheck,
  Usb,
  Play,
  Globe,
  Monitor,
  Apple,
  Terminal,
  XCircle,
  ChevronDown,
  MessageCircleQuestion,
} from 'lucide-react'
import {
  agentFetch,
  getCustomerAgentStartScript,
  getDevAgentStartScript,
  isLocalDev,
  probeLocalAgentHealth,
} from '../lib/localAgent'

interface Runtime {
  runtime_id: string
  robot_type: string
  display_name: string
  joint_count: number
}

type AgentStatus = 'checking' | 'connected' | 'disconnected'
type OsTab = 'linux' | 'macos' | 'windows'

const TRUST_CERT_URL = 'https://localhost:8002'
const HEALTH_URL = 'https://localhost:8002/api/setup/health'

const INSTALL_SCRIPTS: Record<OsTab, string> = {
  linux: `# 适用于：使用 BotverseX 云端网站、需要连接硬件的客户

# 0) 系统依赖（Ubuntu/Debian，首次执行）
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip python3-dev build-essential
sudo usermod -aG dialout $USER   # 串口权限，执行后需重新登录

# 1) 安装 Local Agent
git clone https://github.com/metahubaifeel/botversex-local-agent.git
cd botversex-local-agent
python3 -m venv .venv && source .venv/bin/activate
pip install "torch>=2.2,<2.11" "torchvision>=0.17,<0.26" \\
  --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/

# 2) 启动（保持终端窗口打开）
python run_api.py

# 3) 浏览器信任证书：打开 https://localhost:8002 并点「继续访问」
# 4) 回到本页点击「重新检测」`,
  macos: `# 适用于：使用 BotverseX 云端网站、需要连接硬件的客户

git clone https://github.com/metahubaifeel/botversex-local-agent.git
cd botversex-local-agent
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python run_api.py
# 浏览器打开 https://localhost:8002 信任证书后，回到本页点「重新检测」`,
  windows: `# 适用于：使用 BotverseX 云端网站、需要连接硬件的客户

git clone https://github.com/metahubaifeel/botversex-local-agent.git
cd botversex-local-agent
python -m venv .venv
.venv\\Scripts\\activate
pip install -r requirements.txt
python run_api.py
# 浏览器打开 https://localhost:8002 信任证书后，回到本页点「重新检测」`,
}

const SETUP_STEPS = [
  { id: 'install', title: '安装 Local Agent', titleEn: 'Install' },
  { id: 'run', title: '启动 Agent', titleEn: 'Run' },
  { id: 'trust', title: '信任 HTTPS 证书', titleEn: 'Trust cert' },
  { id: 'detect', title: '本页已连接', titleEn: 'Connected' },
] as const

function useSetupSteps() {
  return useMemo(
    () =>
      isLocalDev()
        ? SETUP_STEPS.filter((s) => s.id !== 'trust' && s.id !== 'install')
        : [...SETUP_STEPS],
    [],
  )
}

export function Setup() {
  const [agentStatus, setAgentStatus] = useState<AgentStatus>('checking')
  const [connectedUrl, setConnectedUrl] = useState<string | null>(null)
  const [runtimes, setRuntimes] = useState<Runtime[]>([])
  const [osTab, setOsTab] = useState<OsTab>('linux')
  const [refreshing, setRefreshing] = useState(false)
  const [copied, setCopied] = useState(false)
  const [copiedStart, setCopiedStart] = useState(false)
  const [manualStep, setManualStep] = useState(0)
  const [probeHint, setProbeHint] = useState<string | null>(null)
  const localDev = isLocalDev()
  const setupSteps = useSetupSteps()
  const startScript = useMemo(
    () => (localDev ? getDevAgentStartScript() : getCustomerAgentStartScript()),
    [localDev],
  )

  const checkAgent = useCallback(async () => {
    const result = await probeLocalAgentHealth()
    if (result.ok && result.url) {
      setConnectedUrl(
        result.via === 'vite-proxy' ? `${result.url}（经 Vite 代理）` : result.url,
      )
      setProbeHint(null)
      setAgentStatus('connected')
      setManualStep(setupSteps.length)
      return true
    }
    setConnectedUrl(null)
    setProbeHint(result.lastError ?? null)
    setAgentStatus('disconnected')
    return false
  }, [setupSteps.length])

  useEffect(() => {
    void checkAgent()
    const interval = setInterval(() => void checkAgent(), 5000)
    return () => clearInterval(interval)
  }, [checkAgent])

  useEffect(() => {
    agentFetch('/api/runtimes')
      .then((r) => r.json())
      .then((d) => setRuntimes(d.runtimes || []))
      .catch(() => {})
  }, [agentStatus])

  const onRefresh = async () => {
    setRefreshing(true)
    setAgentStatus('checking')
    await checkAgent()
    setRefreshing(false)
  }

  const copyScript = async () => {
    try {
      await navigator.clipboard.writeText(INSTALL_SCRIPTS[osTab])
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      /* clipboard denied */
    }
  }

  const copyStartCommand = async () => {
    try {
      await navigator.clipboard.writeText(startScript)
      setCopiedStart(true)
      setManualStep((s) => Math.max(s, 0))
      setTimeout(() => setCopiedStart(false), 2000)
    } catch {
      /* clipboard denied */
    }
  }

  const stepDone = useMemo(() => {
    if (agentStatus === 'connected') return setupSteps.length
    return Math.min(manualStep, setupSteps.length - 1)
  }, [agentStatus, manualStep, setupSteps.length])

  return (
    <div className="container mx-auto px-4 py-8 max-w-4xl space-y-8">
      <div className="text-center space-y-3">
        <p className="bvx-eyebrow">BotverseX</p>
        <h1 className="bvx-page-title">Local Agent（进阶）</h1>
        <p className="bvx-page-subtitle mx-auto text-center">
          只在需要主从遥操、长时间录制或接 CAN 机型时安装。
          只想先让机器人动一下，请用下面的零安装入口。
        </p>
      </div>

      {/* 零安装双入口 — 产品主路径；本页其余部分是 Agent 进阶 */}
      <div className="grid gap-3 sm:grid-cols-2">
        <Link
          to="/play"
          className="rounded-2xl border border-[var(--ember)]/30 bg-gradient-to-br from-[var(--ember)]/10 to-transparent px-5 py-4 transition-colors hover:border-[var(--ember)]/50"
        >
          <p className="bvx-eyebrow">零安装 · 无硬件</p>
          <h2 className="mt-1 text-base font-semibold">立刻玩虚拟 Reachy</h2>
          <p className="mt-1 text-xs text-stone-400">能看 3D、能播动作，不用买机器人</p>
        </Link>
        <Link
          to="/robots/so101?mode=browser"
          className="rounded-2xl border border-white/10 bg-white/[0.02] px-5 py-4 transition-colors hover:border-[var(--ember)]/40"
        >
          <p className="bvx-eyebrow text-stone-400">零安装 · SO-101</p>
          <h2 className="mt-1 text-base font-semibold">浏览器直连真机</h2>
          <p className="mt-1 text-xs text-stone-400">Chrome 授权串口 → 拖滑条点动</p>
        </Link>
      </div>

      {/* Progress steps — customer journey (shorter on localhost dev) */}
      <div
        className={`grid gap-2 ${
          setupSteps.length <= 2 ? 'sm:grid-cols-2' : setupSteps.length === 3 ? 'sm:grid-cols-3' : 'sm:grid-cols-4'
        }`}
      >
        {setupSteps.map((step, i) => {
          const done = i < stepDone
          const active = i === stepDone && agentStatus !== 'connected'
          return (
            <div
              key={step.id}
              className={`rounded-lg border px-3 py-2 text-center text-xs transition-colors ${
                done
                  ? 'border-green-500/40 bg-green-500/10 text-green-400'
                  : active
                    ? 'border-primary/50 bg-primary/10 text-primary'
                    : 'border-border bg-muted/30 text-muted-foreground'
              }`}
            >
              <div className="font-medium">{step.title}</div>
              <div className="opacity-70">{step.titleEn}</div>
            </div>
          )
        })}
      </div>

      {/* Status card */}
      <Card
        data-tour="setup-status"
        className={
          agentStatus === 'connected'
            ? 'border-green-500/30 bg-green-500/5'
            : agentStatus === 'disconnected'
              ? 'border-amber-500/20'
              : ''
        }
      >
        <CardContent className="p-6 space-y-4">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
            <div className="flex items-start gap-3">
              {agentStatus === 'checking' && (
                <Loader2 className="h-7 w-7 shrink-0 text-muted-foreground animate-spin" />
              )}
              {agentStatus === 'connected' && (
                <CheckCircle2 className="h-7 w-7 shrink-0 text-green-500" />
              )}
              {agentStatus === 'disconnected' && (
                <XCircle className="h-7 w-7 shrink-0 text-amber-500" />
              )}
              <div className="space-y-1">
                <div className="text-lg font-semibold">
                  {agentStatus === 'checking' && '正在检测 Local Agent…'}
                  {agentStatus === 'connected' && 'Local Agent 已连接'}
                  {agentStatus === 'disconnected' && '尚未检测到 Local Agent'}
                </div>
                <p className="text-sm text-muted-foreground">
                  {agentStatus === 'connected'
                    ? '硬件接口已就绪，可进行遥操作、录制与标定。'
                    : localDev
                      ? '请在本机终端启动 Agent（见下方启动命令）。'
                      : '请在本机安装并启动 Agent；使用云端网站时还需信任 HTTPS 自签证书。'}
                </p>
                {connectedUrl && agentStatus === 'connected' && (
                  <p className="text-xs font-mono text-muted-foreground break-all">
                    {connectedUrl}
                  </p>
                )}
                {probeHint && agentStatus === 'disconnected' && (
                  <p className="text-xs text-amber-400/90 mt-1">检测详情：{probeHint}</p>
                )}
              </div>
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={() => void onRefresh()}
              disabled={refreshing || agentStatus === 'checking'}
              className="shrink-0"
            >
              {refreshing || agentStatus === 'checking' ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  检测中
                </>
              ) : (
                '重新检测'
              )}
            </Button>
          </div>

          {agentStatus === 'connected' && (
            <div className="flex flex-wrap gap-2 pt-1">
              <Link to="/robots" data-tour="setup-goto-robots" className={cn(buttonVariants({ variant: 'default' }))}>
                选择机器人，开始配置
                <ArrowRight className="h-4 w-4" />
              </Link>
              <a
                href={localDev ? '/api/setup/health' : HEALTH_URL}
                target="_blank"
                rel="noopener noreferrer"
                className={cn(buttonVariants({ variant: 'outline' }))}
              >
                查看健康检查
                <ExternalLink className="h-4 w-4" />
              </a>
            </div>
          )}

          {agentStatus === 'disconnected' && !localDev && (
            <div className="rounded-lg border border-primary/30 bg-primary/5 p-4 space-y-3">
              <div className="flex items-center gap-2 text-sm font-medium text-primary">
                <ShieldCheck className="h-4 w-4" />
                第三步：信任本机 HTTPS 证书（每个浏览器只需一次）
              </div>
              <p className="text-sm text-muted-foreground">
                云端网站使用 HTTPS，浏览器会拦截未信任的 <code className="text-xs">localhost</code> 连接。
                请先打开下面链接，在警告页选择「高级 → 继续访问」。
              </p>
              <div className="flex flex-wrap gap-2">
                <a
                  href={TRUST_CERT_URL}
                  target="_blank"
                  rel="noopener noreferrer"
                  onClick={() => setManualStep((s) => Math.max(s, 2))}
                  className={cn(buttonVariants({ variant: 'default' }))}
                >
                  打开 https://localhost:8002
                  <ExternalLink className="h-4 w-4" />
                </a>
                <Button variant="outline" onClick={() => void onRefresh()}>
                  我已信任，重新检测
                </Button>
              </div>
            </div>
          )}

          {agentStatus === 'disconnected' && (
            <div className="rounded-lg border border-border bg-muted/20 p-4 space-y-3">
              <div className="flex items-center gap-2 text-sm font-medium">
                <Terminal className="h-4 w-4 text-primary" />
                {localDev ? '启动 Local Agent' : '第二步：复制启动命令到终端'}
              </div>
              <p className="text-sm text-muted-foreground">
                浏览器<strong>不能</strong>替你一键启动本机程序（安全限制）。
                复制下面命令到终端并<strong>保持窗口不要关</strong>。
              </p>
              <pre className="text-xs bg-muted/50 rounded-lg p-3 overflow-x-auto whitespace-pre-wrap">
                {startScript}
              </pre>
              <div className="flex flex-wrap gap-2">
                <Button onClick={() => void copyStartCommand()}>
                  <Copy className="mr-2 h-4 w-4" />
                  {copiedStart ? '已复制启动命令' : '一键复制启动命令'}
                </Button>
                <Button variant="outline" onClick={() => void onRefresh()}>
                  已启动，重新检测
                </Button>
              </div>
              <p className="text-xs text-muted-foreground flex items-start gap-1.5">
                <MessageCircleQuestion className="h-3.5 w-3.5 shrink-0 text-indigo-400 mt-0.5" />
                安装报错、pip 慢、端口占用等问题 → 打开右下角 Copilot 自动诊断
              </p>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Developer hint — collapsed, localhost only */}
      {localDev && (
        <details className="rounded-lg border border-dashed border-[hsl(var(--border))]/60 bg-[hsl(var(--muted))]/10">
          <summary className="cursor-pointer list-none px-4 py-3 text-sm font-medium flex items-center gap-2">
            <ChevronDown className="h-4 w-4 text-muted-foreground" />
            工程师提示（本地开发，客户无需阅读）
          </summary>
          <div className="px-4 pb-4 space-y-2 text-xs text-muted-foreground">
            <p>
              你在 <code>localhost:5173</code> 开发 BotverseX。Agent 在 monorepo 的{' '}
              <code>apps/realtime</code>，通过 Vite 代理访问，<strong>无需信任 HTTPS 证书</strong>。
            </p>
            <p>
              另开终端运行 <code>cd apps/web && npm run dev</code>。
              Agent 启动命令：<code>python run_api.py --http</code>
            </p>
          </div>
        </details>
      )}

      {agentStatus !== 'connected' && !localDev && (
        <>
          <div className="space-y-4">
            <div>
              <h2 className="text-xl font-semibold">客户快速开始：安装 Local Agent</h2>
              <p className="text-sm text-muted-foreground mt-1">
                适用于使用 BotverseX 云端网站、需要连接摄像头或机械臂的用户。
              </p>
            </div>
            <div className="flex gap-1 border-b border-border">
              {([
                { id: 'linux' as OsTab, label: 'Linux', icon: Terminal },
                { id: 'macos' as OsTab, label: 'macOS', icon: Apple },
                { id: 'windows' as OsTab, label: 'Windows', icon: Monitor },
              ]).map((tab) => (
                <button
                  key={tab.id}
                  type="button"
                  onClick={() => setOsTab(tab.id)}
                  className={`flex items-center gap-2 px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                    osTab === tab.id
                      ? 'border-primary text-primary'
                      : 'border-transparent text-muted-foreground hover:text-foreground'
                  }`}
                >
                  <tab.icon className="h-4 w-4" />
                  {tab.label}
                </button>
              ))}
            </div>
            <Card data-tour="setup-install">
              <CardContent className="p-4 space-y-3">
                <div className="flex justify-end">
                  <Button variant="outline" size="sm" onClick={() => void copyScript()}>
                    <Copy className="mr-2 h-4 w-4" />
                    {copied ? '已复制' : '复制命令'}
                  </Button>
                </div>
                <pre
                  className="text-sm bg-muted/50 rounded-lg p-4 overflow-x-auto whitespace-pre-wrap select-all"
                  onFocus={() => setManualStep((s) => Math.max(s, 0))}
                >
                  {INSTALL_SCRIPTS[osTab]}
                </pre>
                <p className="text-xs text-muted-foreground">
                  启动成功后终端会显示 <code>https://localhost:8002</code>。
                  若 <code>git clone</code> 较慢或 pip 报错，请用 Copilot 获取对应修复步骤。
                </p>
              </CardContent>
            </Card>
          </div>

          <div className="space-y-4">
            <h2 className="text-xl font-semibold">工作原理</h2>
            <div className="grid gap-4 md:grid-cols-3">
              {[
                {
                  icon: Usb,
                  step: '1',
                  title: '连接硬件',
                  desc: 'USB 连接机械臂与摄像头。',
                },
                {
                  icon: Play,
                  step: '2',
                  title: '启动 Local Agent',
                  desc: '在本机运行，负责串口与相机。',
                },
                {
                  icon: Globe,
                  step: '3',
                  title: '使用网站',
                  desc: '本页自动检测，无需 VPN。',
                },
              ].map((item) => (
                <Card key={item.step}>
                  <CardContent className="p-6 text-center space-y-3">
                    <div className="flex justify-center">
                      <div className="flex h-12 w-12 items-center justify-center rounded-full bg-primary/10">
                        <item.icon className="h-6 w-6 text-primary" />
                      </div>
                    </div>
                    <div className="text-xs font-bold text-muted-foreground">步骤 {item.step}</div>
                    <h3 className="font-semibold">{item.title}</h3>
                    <p className="text-sm text-muted-foreground">{item.desc}</p>
                  </CardContent>
                </Card>
              ))}
            </div>
          </div>
        </>
      )}

      {runtimes.length > 0 && (
        <div className="space-y-4">
          <h2 className="text-xl font-semibold">支持的机器人</h2>
          <div className="grid gap-3 md:grid-cols-2">
            {runtimes.map((rt) => (
              <Card key={rt.runtime_id}>
                <CardContent className="flex items-center gap-4 p-4">
                  <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-primary/10">
                    <Usb className="h-5 w-5 text-primary" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="font-medium text-sm">{rt.display_name}</div>
                    <div className="text-xs text-muted-foreground">
                      {rt.joint_count} 关节 · {rt.robot_type}
                    </div>
                  </div>
                  {agentStatus === 'connected' && (
                    <Link
                      to={`/robots/${rt.runtime_id}`}
                      className={cn(buttonVariants({ variant: 'ghost', size: 'sm' }))}
                    >
                      进入
                    </Link>
                  )}
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      )}

      <div className="space-y-4">
        <h2 className="text-xl font-semibold">常见问题</h2>
        <div className="grid gap-3 md:grid-cols-2">
          <Card>
            <CardContent className="p-5">
              <h3 className="font-medium text-sm mb-1">为什么不能网页里一键启动？</h3>
              <p className="text-sm text-muted-foreground">
                出于安全策略，网页无法执行你电脑上的 <code>python run_api.py</code>。
                我们提供「一键复制命令」；你粘贴到终端运行即可。
              </p>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="p-5">
              <h3 className="font-medium text-sm mb-1">Agent 在跑但仍未连接？</h3>
              <p className="text-sm text-muted-foreground">
                {localDev ? (
                  <>
                    确认 Agent 终端在跑且 Vite 开发服已启动，然后点「重新检测」。
                    详细步骤见上方「工程师提示」。
                  </>
                ) : (
                  <>
                    在同一浏览器打开{' '}
                    <a href={TRUST_CERT_URL} className="text-primary underline" target="_blank" rel="noreferrer">
                      https://localhost:8002
                    </a>{' '}
                    并接受证书，再点「重新检测」。仍失败请用 Copilot 诊断。
                  </>
                )}
              </p>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="p-5">
              <h3 className="font-medium text-sm mb-1">数据留在本机</h3>
              <p className="text-sm text-muted-foreground">
                录制与数据集默认保存在你的电脑，除非你主动上传。
              </p>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  )
}
