import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  ArrowLeft,
  BadgeCheck,
  Beaker,
  Box,
  Cpu,
  ExternalLink,
  ShieldAlert,
  Sparkles,
} from 'lucide-react'
import { LazyUrdfPreview } from '../components/features/LazyUrdfPreview'
import { CommunityResources } from '../components/features/CommunityResources'
import { getRobotManifest, type RobotManifest } from '../lib/robotApi'
import { catalogMeta } from '../lib/robotCatalog'

interface PreviewDefinition {
  eyebrow: string
  statement: string
  urdf: string
  source: string
  sourceUrl: string
  available: string[]
  notAvailable: string[]
  specs: Array<[string, string]>
  next: string[]
}

const PREVIEWS: Record<string, PreviewDefinition> = {
  amazing_hand: {
    eyebrow: 'Dexterous end-effector · Labs',
    statement: '一只真正把 8 枚执行器装进手掌、而不是“几根圆柱体”的开源灵巧手。',
    urdf: '/api/urdf/amazing_hand/amazing_hand.urdf?v=official-cad-1',
    source: 'Pollen Robotics 官方 CAD / MJCF',
    sourceUrl: 'https://github.com/pollen-robotics/AmazingHand',
    available: [
      '官方右手 CAD/MJCF 零位姿态 3D 资产',
      '8 × Feetech SCS0009 串行舵机硬件定义',
      'Python / Arduino 基础控制参考与 Reachy2 腕部接口',
    ],
    notAvailable: [
      'BotverseX 真机连接与标定尚未完成',
      '闭链并联机构尚未接入浏览器物理仿真',
      'Quest/数据手套遥操与数据录制尚未开放',
    ],
    specs: [
      ['自由度', '8 DoF'],
      ['手指', '4 指 · 每指 2 DoF'],
      ['执行器', '8 × SCS0009'],
      ['重量', '约 400 g'],
      ['结构', '刚性骨架 + TPU 柔性外壳'],
      ['接口', '串行总线 / Reachy2 wrist'],
    ],
    next: ['Feetech runtime', '手指标定', 'Quest/手套映射', 'LeRobot 数据格式', 'VLA 灵巧操作'],
  },
  unitree_g1: {
    eyebrow: 'Whole-body intelligence · Labs',
    statement: '不是半截圆柱，而是 Unitree 官方 29 自由度本体与完整全身控制资产入口。',
    urdf: '/api/urdf/unitree_g1/unitree_g1.urdf?v=official-cad-1',
    source: 'Unitree Robotics 官方 URDF / MJCF',
    sourceUrl: 'https://github.com/unitreerobotics/unitree_ros/tree/master/robots/g1_description',
    available: [
      '官方 G1 29-DoF rev 1.0 URDF 与 39-link 高质量 mesh',
      '匹配的官方 MJCF，作为 MuJoCo / Isaac 工作流基础',
      'BotverseX Workflow 的人形仿真与策略资产入口',
    ],
    notAvailable: [
      '尚未接入 Unitree SDK2 真机控制',
      'UFO / humanoid walking 策略尚未封装为可运行节点',
      '没有真机时不会伪装成“可连接 runtime”',
    ],
    specs: [
      ['本体', 'Unitree G1'],
      ['模型', '29 DoF rev 1.0'],
      ['腿部', '6 DoF × 2'],
      ['腰部', '3 DoF'],
      ['手臂', '7 DoF × 2'],
      ['仿真', 'URDF + MJCF'],
    ],
    next: ['Isaac Lab 预训练', 'MuJoCo 回放', 'SDK2 bridge', '全身遥操', '策略评估与部署'],
  },
}

export function RobotPreview({ runtimeId }: { runtimeId: string }) {
  const [manifest, setManifest] = useState<RobotManifest | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    void getRobotManifest(runtimeId)
      .then((next) => {
        if (!cancelled) setManifest(next)
      })
      .catch((cause) => {
        if (!cancelled) setError(cause instanceof Error ? cause.message : '加载失败')
      })
    return () => {
      cancelled = true
    }
  }, [runtimeId])

  const definition = PREVIEWS[runtimeId]
  const meta = catalogMeta(runtimeId)
  const title = meta?.title ?? manifest?.display_name ?? runtimeId

  if (!definition) {
    return <div className="container mx-auto px-4 py-8 text-sm text-muted-foreground">未知实验室资产：{runtimeId}</div>
  }

  return (
    <div className="container mx-auto px-4 py-6 space-y-5">
      <div className="bvx-page-header">
        <Link to="/robots" className="bvx-back-link">
          <ArrowLeft className="h-3.5 w-3.5" />
          机器人目录
        </Link>
        <div className="flex items-center justify-between gap-3">
          <div>
            <h1 className="bvx-page-title">{title}</h1>
            <p className="bvx-page-subtitle">
              此页面展示已纳入 BotverseX 的真实开源资产与明确接入边界。Preview 不等于真机支持。
            </p>
          </div>
          <span className="bvx-pill bvx-pill--labs">Labs · Preview</span>
        </div>
        <Link to={`/robots/${runtimeId}/play`} className="bvx-cta bvx-cta--ember w-fit">
          <Sparkles className="h-3.5 w-3.5" />
          立刻在浏览器里玩
        </Link>
      </div>

      <section className="relative overflow-hidden rounded-3xl border border-white/10 bg-[#080c14]">
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_16%_25%,rgba(56,189,248,0.13),transparent_38%),radial-gradient(circle_at_80%_20%,rgba(168,85,247,0.1),transparent_35%)]" />
        <div className="relative grid min-h-[480px] lg:grid-cols-[0.82fr_1.18fr]">
          <div className="flex flex-col justify-between p-7 lg:p-10">
            <div>
              <p className="bvx-eyebrow text-sky-300">{definition.eyebrow}</p>
              <p className="mt-4 max-w-xl text-lg leading-8 text-slate-300">{definition.statement}</p>
              <p className="mt-5 text-sm leading-7 text-slate-500">
                没真机也能玩：点上面的「立刻在浏览器里玩」，拖滑条让模型动。
              </p>
            </div>
            <a
              href={definition.sourceUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="mt-8 inline-flex w-fit items-center gap-2 rounded-full border border-white/10 bg-white/5 px-3 py-2 text-xs text-slate-300 hover:bg-white/10"
            >
              <BadgeCheck className="h-4 w-4 text-sky-300" />
              {definition.source}
              <ExternalLink className="h-3 w-3" />
            </a>
          </div>
          <div className="relative min-h-[380px] border-t border-white/10 lg:border-l lg:border-t-0">
            <LazyUrdfPreview
              urdfUrl={definition.urdf}
              runtimeId={runtimeId}
              stage
              waitForMeshes
              className="absolute inset-0"
            />
          </div>
        </div>
      </section>

      {error ? (
        <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-xs text-amber-200">{error}</div>
      ) : null}

      <div className="grid gap-5 lg:grid-cols-3">
        <section className="rounded-2xl border border-emerald-400/20 bg-emerald-400/5 p-5">
          <div className="flex items-center gap-2 text-sm font-semibold text-emerald-200">
            <Box className="h-4 w-4" />
            已进入平台的真实资产
          </div>
          <ul className="mt-4 space-y-3 text-xs leading-5 text-emerald-50/75">
            {definition.available.map((item) => (
              <li key={item} className="flex gap-2"><span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-emerald-400" />{item}</li>
            ))}
          </ul>
        </section>

        <section className="rounded-2xl border border-amber-400/20 bg-amber-400/5 p-5">
          <div className="flex items-center gap-2 text-sm font-semibold text-amber-200">
            <ShieldAlert className="h-4 w-4" />
            现在不能假装已完成
          </div>
          <ul className="mt-4 space-y-3 text-xs leading-5 text-amber-50/70">
            {definition.notAvailable.map((item) => (
              <li key={item} className="flex gap-2"><span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-amber-400" />{item}</li>
            ))}
          </ul>
        </section>

        <section className="rounded-2xl border border-sky-400/20 bg-sky-400/5 p-5">
          <div className="flex items-center gap-2 text-sm font-semibold text-sky-200">
            <Cpu className="h-4 w-4" />
            真实规格
          </div>
          <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3 text-xs">
            {definition.specs.map(([key, value]) => (
              <div key={key}>
                <dt className="text-slate-500">{key}</dt>
                <dd className="mt-0.5 text-slate-200">{value}</dd>
              </div>
            ))}
          </dl>
        </section>
      </div>

      <section className="rounded-2xl border border-border/70 bg-card/50 p-5">
        <div className="flex items-center gap-2">
          <Beaker className="h-4 w-4 text-violet-300" />
          <h2 className="text-sm font-semibold">从资产到可用能力的接入顺序</h2>
        </div>
        <div className="mt-4 flex flex-wrap items-center gap-2">
          {definition.next.map((item, index) => (
            <div key={item} className="flex items-center gap-2">
              <span className="rounded-full border border-white/10 bg-white/5 px-3 py-1.5 text-xs text-slate-300">
                {String(index + 1).padStart(2, '0')} · {item}
              </span>
              {index < definition.next.length - 1 ? <Sparkles className="h-3 w-3 text-slate-600" /> : null}
            </div>
          ))}
        </div>
      </section>

      {runtimeId === 'unitree_g1' && (
        <CommunityResources
          intro="Unitree G1 是商业人形机器人，官方公开社区入口较少——GitHub Issues 是主要求助渠道（官方 Discord/微信群无公开入口，如实说明）。"
          docs={[
            { label: '官方开发者文档（G1）', url: 'https://support.unitree.com/home/en/G1_developer' },
            { label: 'unitree_sdk2_python', url: 'https://github.com/unitreerobotics/unitree_sdk2_python' },
          ]}
          communities={[
            { label: 'GitHub Issues（unitreerobotics）', url: 'https://github.com/unitreerobotics/unitree_sdk2_python/issues' },
            { label: 'LeRobot 文档（G1）', url: 'https://huggingface.co/docs/lerobot/main/unitree_g1' },
          ]}
          faqs={[
            {
              q: 'SDK 高维指令失效？',
              a: '手柄按组合键进 debug 模式会关掉 ai_sport client；且 SDK 需要 EDU 版，普通版不给（issue #43）。',
            },
            {
              q: '连不上机器人？',
              a: '机器人固定 IP 192.168.123.161/.164，主机必须设同网段静态 IP，否则连接失败。',
            },
            {
              q: '低层状态读取报错？',
              a: 'ClientStub send request error / NoneType 报错常见于网络与服务状态（issue #28）。',
            },
            {
              q: '仿真部署到真机手臂抖动？',
              a: '仿真与真机关节索引不一致是常见原因（Isaac-GR00T issue #438）；MuJoCo 需用 unitree_hg IDL 而非 unitree_go（issue #42）。',
            },
            {
              q: 'G1 大概什么价格？',
              a: '基础版约 $16,000（教育配置），五指手 $21,000，研究配置 $35,000–45,000（2026 市场价，来自第三方买家指南）。',
            },
          ]}
        />
      )}
    </div>
  )
}
