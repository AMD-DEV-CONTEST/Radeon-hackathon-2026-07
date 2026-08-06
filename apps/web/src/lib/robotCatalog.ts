import type { LucideIcon } from 'lucide-react'
import { Axis3D, Bot } from 'lucide-react'

export interface RobotCatalogMeta {
  title: string
  subtitle: string
  blurb: string
  icon: LucideIcon
  /** Lower = load 3D preview first on /robots. */
  previewPriority: number
  meshConcurrency: number
  cameraPosition?: [number, number, number]
  stageCameraPosition?: [number, number, number]
  orbitTarget?: [number, number, number]
  modelCredit?: string
  formFactor?: string
}

export const ROBOT_CATALOG: Record<string, RobotCatalogMeta> = {
  so101: {
    title: 'SO-101 机械臂',
    subtitle: 'Feetech · 6 轴',
    blurb: '从连接机械臂到录制数据、训练模型，一条龙上手。',
    icon: Axis3D,
    previewPriority: 0,
    meshConcurrency: 12,
    cameraPosition: [0.6, 0.6, 0.6],
    orbitTarget: [0, 0.1, 0],
    formFactor: '固定机械臂',
  },
  reachy_mini: {
    title: 'Reachy Mini',
    subtitle: 'Pollen Robotics · 桌面机器人',
    blurb: '连接真机或虚拟孪生，编排动作、录制回放。',
    icon: Bot,
    previewPriority: 1,
    meshConcurrency: 8,
    cameraPosition: [0.35, 0.35, 0.35],
    orbitTarget: [0, 0.12, 0],
    formFactor: '桌面机器人',
  },
  b601_rs: {
    title: 'reBot B601',
    subtitle: 'Seeed · 7 轴 + Star Arm 102',
    blurb: 'RS（RobStride）/ DM（达妙）/ 双臂 DM 都从这里进。一键遥操、录示教、云端训练。',
    icon: Axis3D,
    previewPriority: 2,
    meshConcurrency: 2,
    cameraPosition: [0.55, 0.45, 0.55],
    orbitTarget: [0, 0.15, 0],
    formFactor: '7 轴机械臂',
  },
  lekiwi: {
    title: 'LeKiwi 移动机械臂',
    subtitle: 'LeRobot · 全向移动操作',
    blurb: '一条 STS3215 总线驱动 6 轴臂与三轮全向底盘，双相机数据经机器人端 Host 实时回传。',
    icon: Bot,
    previewPriority: 3,
    meshConcurrency: 8,
    cameraPosition: [0.62, 0.48, 0.46],
    stageCameraPosition: [0.52, 0.4, 0.4],
    orbitTarget: [0, 0.19, 0],
    modelCredit: '官方 CAD · SIGRobotics-UIUC',
    formFactor: '移动机械臂',
  },
  amazing_hand: {
    title: 'AmazingHand 灵巧手',
    subtitle: '8-DoF · 4 指并联机构',
    blurb: 'Pollen Robotics 开源灵巧手：8 枚 SCS0009 舵机内置于手掌，支持屈伸与展收。',
    icon: Bot,
    previewPriority: 4,
    meshConcurrency: 8,
    cameraPosition: [0.28, 0.22, 0.2],
    stageCameraPosition: [0.36, 0.28, 0.26],
    orbitTarget: [-0.005, 0.075, 0],
    modelCredit: '官方 CAD/MJCF · Pollen Robotics',
    formFactor: '灵巧末端',
  },
  unitree_g1: {
    title: 'Unitree G1 人形',
    subtitle: '29-DoF · 通用人形平台',
    blurb: 'Unitree 官方 29 自由度模型。面向 Isaac/MuJoCo 强化学习、全身控制与移动操作。',
    icon: Bot,
    previewPriority: 5,
    meshConcurrency: 8,
    cameraPosition: [1.2, 0.9, 0.85],
    stageCameraPosition: [1, 0.85, 0.72],
    orbitTarget: [0, 0.62, 0],
    modelCredit: '官方 URDF/MJCF · Unitree Robotics',
    formFactor: '全尺寸人形',
  },
}

export function catalogMeta(runtimeId: string): RobotCatalogMeta | null {
  return ROBOT_CATALOG[runtimeId] ?? null
}
