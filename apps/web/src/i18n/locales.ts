export type Locale = 'zh' | 'en' | 'ja'

export const LOCALE_OPTIONS: Array<{
  id: Locale
  label: string
  short: string
}> = [
  { id: 'zh', label: '中文', short: '中' },
  { id: 'en', label: 'English', short: 'EN' },
  { id: 'ja', label: '日本語', short: '日' },
]

export type MessageTree = {
  common: {
    login: string
    register: string
    logout: string
    dashboard: string
    refresh: string
    comingSoon: string
  }
  nav: {
    robots: string
    setup: string
    lab: string
    settings: string
    datasets: string
    training: string
    models: string
    skills: string
    workflow: string
    teleop: string
    inference: string
    reachyApps: string
    remoteCompute: string
  }
  robots: {
    heroLine1: string
    heroLine2: string
    heroBody: string
    ctaPlay: string
    ctaSo101: string
    ctaOther: string
    tourHint: string
    syncing: string
    fleetEyebrow: string
    fleetTitle: string
    fleetBody: string
    available: string
    labs: string
    ready: string
    contactEyebrow: string
    contactTitle: string
    contactBody: string
    playNoHardware: string
    browserDirect: string
    localAgent: string
    getStarted: string
    workspace: string
    playVirtual: string
    haveHardware: string
    viewBoundary: string
    enterWorkspace: string
    enterWizard: string
    noPreview: string
  }
  catalog: Record<
    string,
    {
      title: string
      subtitle: string
      blurb: string
      formFactor: string
    }
  >
}

export const messages: Record<Locale, MessageTree> = {
  zh: {
    common: {
      login: '登录',
      register: '注册',
      logout: '登出',
      dashboard: 'Dashboard',
      refresh: '刷新',
      comingSoon: '即将支持',
    },
    nav: {
      robots: 'Robots',
      setup: 'Setup',
      lab: '实验室',
      settings: 'Settings',
      datasets: 'Datasets',
      training: 'Training',
      models: 'Models',
      skills: 'Skills',
      workflow: 'Workflow',
      teleop: '遥操',
      inference: '推理',
      reachyApps: 'Reachy Apps',
      remoteCompute: '算力节点',
    },
    robots: {
      heroLine1: '你也能让机器人',
      heroLine2: '动起来',
      heroBody:
        '零基础也能玩：点一下进虚拟 Reachy，3D 会动、动作能点。想快速上手？有 SO-101 就浏览器直连。下一步再搭你自己的闭环——录数据、训模型、真机复现。',
      ctaPlay: '零基础？先玩起来',
      ctaSo101: '快速上手：浏览器直连',
      ctaOther: '选机型，搭闭环',
      tourHint: '1 分钟新手引导 · 小白友好',
      syncing: '同步机型目录…',
      fleetEyebrow: 'Fleet',
      fleetTitle: '选机型，搭你的闭环',
      fleetBody: '从玩到真机：可用机型走通连接→采集→训练；实验室资产只展示真实模型与接入边界，不冒充已通。',
      available: '可用',
      labs: '实验室',
      ready: 'Ready',
      contactEyebrow: 'Contact',
      contactTitle: '一起把真机数据跑起来',
      contactBody: '有问题、合作或内测需求，直接找我们。',
      playNoHardware: '立刻玩（无硬件）',
      browserDirect: '浏览器直连',
      localAgent: 'Local Agent',
      getStarted: '开始上手',
      workspace: '工作台',
      playVirtual: '立刻玩（云端虚拟）',
      haveHardware: '我有真机',
      viewBoundary: '查看接入边界',
      enterWorkspace: '进入工作台',
      enterWizard: '进入向导',
      noPreview: '无预览',
    },
    catalog: {
      so101: {
        title: 'SO-101 机械臂',
        subtitle: 'Feetech · 6 轴',
        blurb: '从连接机械臂到录制数据、训练模型，一条龙上手。',
        formFactor: '固定机械臂',
      },
      reachy_mini: {
        title: 'Reachy Mini',
        subtitle: 'Pollen Robotics · 桌面机器人',
        blurb: '连接真机或虚拟孪生，编排动作、录制回放。',
        formFactor: '桌面机器人',
      },
      b601_rs: {
        title: 'reBot B601',
        subtitle: 'Seeed · 7 轴 + Star Arm 102',
        blurb: 'RS（RobStride）/ DM（达妙）/ 双臂 DM 都从这里进。一键遥操、录示教、云端训练。',
        formFactor: '7 轴机械臂',
      },
      lekiwi: {
        title: 'LeKiwi 移动机械臂',
        subtitle: 'LeRobot · 全向移动操作',
        blurb: '一条 STS3215 总线驱动 6 轴臂与三轮全向底盘，双相机数据经机器人端 Host 实时回传。',
        formFactor: '移动机械臂',
      },
      amazing_hand: {
        title: 'AmazingHand 灵巧手',
        subtitle: '8-DoF · 4 指并联机构',
        blurb: 'Pollen Robotics 开源灵巧手：8 枚 SCS0009 舵机内置于手掌，支持屈伸与展收。',
        formFactor: '灵巧末端',
      },
      unitree_g1: {
        title: 'Unitree G1 人形',
        subtitle: '29-DoF · 通用人形平台',
        blurb: 'Unitree 官方 29 自由度模型。面向 Isaac/MuJoCo 强化学习、全身控制与移动操作。',
        formFactor: '全尺寸人形',
      },
    },
  },
  en: {
    common: {
      login: 'Log in',
      register: 'Sign up',
      logout: 'Log out',
      dashboard: 'Dashboard',
      refresh: 'Refresh',
      comingSoon: 'Coming soon',
    },
    nav: {
      robots: 'Robots',
      setup: 'Setup',
      lab: 'Lab',
      settings: 'Settings',
      datasets: 'Datasets',
      training: 'Training',
      models: 'Models',
      skills: 'Skills',
      workflow: 'Workflow',
      teleop: 'Teleop',
      inference: 'Inference',
      reachyApps: 'Reachy Apps',
      remoteCompute: 'Compute nodes',
    },
    robots: {
      heroLine1: 'You can get a robot',
      heroLine2: 'moving too',
      heroBody:
        'Complete beginners welcome. Tap into virtual Reachy — the 3D model moves and dances. Want a fast start? Plug in an SO-101 and drive it from the browser. Then build your own loop: record, train, run on real hardware.',
      ctaPlay: 'Beginner? Play first',
      ctaSo101: 'Quick start: browser direct',
      ctaOther: 'Pick a robot, build a loop',
      tourHint: '1-minute tour · beginner friendly',
      syncing: 'Syncing robot catalog…',
      fleetEyebrow: 'Fleet',
      fleetTitle: 'Pick a robot. Build your loop.',
      fleetBody:
        'From play to real hardware: ready models cover connect → collect → train. Lab assets show real CAD and integration boundaries — not fake “done”.',
      available: 'ready',
      labs: 'labs',
      ready: 'Ready',
      contactEyebrow: 'Contact',
      contactTitle: 'Let’s get real robot data flowing',
      contactBody: 'Questions, partnerships, or private beta — reach out.',
      playNoHardware: 'Play now (no hardware)',
      browserDirect: 'Browser direct',
      localAgent: 'Local Agent',
      getStarted: 'Get started',
      workspace: 'Workbench',
      playVirtual: 'Play now (cloud virtual)',
      haveHardware: 'I have hardware',
      viewBoundary: 'View integration boundary',
      enterWorkspace: 'Open workbench',
      enterWizard: 'Open wizard',
      noPreview: 'No preview',
    },
    catalog: {
      so101: {
        title: 'SO-101 Arm',
        subtitle: 'Feetech · 6-DoF',
        blurb: 'Connect the arm, record data, train a model — one guided path.',
        formFactor: 'Fixed arm',
      },
      reachy_mini: {
        title: 'Reachy Mini',
        subtitle: 'Pollen Robotics · desktop robot',
        blurb: 'Connect real hardware or a virtual twin. Choreograph, record, replay.',
        formFactor: 'Desktop robot',
      },
      b601_rs: {
        title: 'reBot B601',
        subtitle: 'Seeed · 7-DoF + Star Arm 102',
        blurb: 'RS / Damiao / dual-arm Damiao in one place. Teleop, teach, cloud train.',
        formFactor: '7-DoF arm',
      },
      lekiwi: {
        title: 'LeKiwi mobile arm',
        subtitle: 'LeRobot · omnidirectional mobile manip.',
        blurb: 'One STS3215 bus for a 6-DoF arm and 3-wheel base; dual cameras stream from the on-robot host.',
        formFactor: 'Mobile manipulator',
      },
      amazing_hand: {
        title: 'AmazingHand',
        subtitle: '8-DoF · 4-finger parallel',
        blurb: 'Open-source dexterous hand from Pollen: eight SCS0009 servos in the palm.',
        formFactor: 'Dexterous end-effector',
      },
      unitree_g1: {
        title: 'Unitree G1',
        subtitle: '29-DoF · humanoid platform',
        blurb: 'Official 29-DoF model for Isaac/MuJoCo RL, whole-body control, and loco-manipulation.',
        formFactor: 'Full-size humanoid',
      },
    },
  },
  ja: {
    common: {
      login: 'ログイン',
      register: '登録',
      logout: 'ログアウト',
      dashboard: 'Dashboard',
      refresh: '更新',
      comingSoon: '近日対応',
    },
    nav: {
      robots: 'Robots',
      setup: 'Setup',
      lab: 'ラボ',
      settings: 'Settings',
      datasets: 'Datasets',
      training: 'Training',
      models: 'Models',
      skills: 'Skills',
      workflow: 'Workflow',
      teleop: '遠隔操作',
      inference: '推論',
      reachyApps: 'Reachy Apps',
      remoteCompute: '計算ノード',
    },
    robots: {
      heroLine1: 'あなたもロボットを',
      heroLine2: '動かせる',
      heroBody:
        'ゼロからでも大丈夫。仮想 Reachy を開けば 3D が動き、ダンスも見られます。早く始めたい？SO-101 を USB でブラウザ直結。その先は、収録→学習→実機再現の自分のループを作れます。',
      ctaPlay: '初心者？まず遊ぼう',
      ctaSo101: 'すぐ始める：ブラウザ直結',
      ctaOther: '機種を選んでループを組む',
      tourHint: '1 分ガイド · 初心者向け',
      syncing: '機種カタログを同期中…',
      fleetEyebrow: 'Fleet',
      fleetTitle: '機種を選んで、自分のループを',
      fleetBody:
        '遊びから実機へ。Ready は接続→収録→学習まで。Labs は実 CAD と接続境界のみ示し、未完成を完成扱いしません。',
      available: 'Ready',
      labs: 'Labs',
      ready: 'Ready',
      contactEyebrow: 'Contact',
      contactTitle: '実機データを一緒に回そう',
      contactBody: '質問・提携・クローズドベータはお気軽に。',
      playNoHardware: '今すぐ遊ぶ（実機不要）',
      browserDirect: 'ブラウザ直結',
      localAgent: 'Local Agent',
      getStarted: 'はじめる',
      workspace: 'ワークベンチ',
      playVirtual: '今すぐ遊ぶ（クラウド仮想）',
      haveHardware: '実機がある',
      viewBoundary: '接続境界を見る',
      enterWorkspace: 'ワークベンチへ',
      enterWizard: 'ウィザードへ',
      noPreview: 'プレビューなし',
    },
    catalog: {
      so101: {
        title: 'SO-101 アーム',
        subtitle: 'Feetech · 6 軸',
        blurb: '接続からデータ収録、学習まで一本道で始められます。',
        formFactor: '固定アーム',
      },
      reachy_mini: {
        title: 'Reachy Mini',
        subtitle: 'Pollen Robotics · デスクトップ',
        blurb: '実機または仮想ツインで、モーション編集・収録・再生。',
        formFactor: 'デスクトップロボット',
      },
      b601_rs: {
        title: 'reBot B601',
        subtitle: 'Seeed · 7 軸 + Star Arm 102',
        blurb: 'RS / 達妙 / 双腕達妙をここに集約。テレオペ・教示・クラウド学習。',
        formFactor: '7 軸アーム',
      },
      lekiwi: {
        title: 'LeKiwi 移動アーム',
        subtitle: 'LeRobot · 全方向移動マニピュレータ',
        blurb: 'STS3215 一本で 6 軸アームと三輪ベース。双カメラはロボット側 Host から返送。',
        formFactor: '移動マニピュレータ',
      },
      amazing_hand: {
        title: 'AmazingHand',
        subtitle: '8-DoF · 4 指パラレル',
        blurb: 'Pollen のオープンな手先：掌内 8 個の SCS0009。屈曲・開閉に対応。',
        formFactor: '手先エンドエフェクタ',
      },
      unitree_g1: {
        title: 'Unitree G1',
        subtitle: '29-DoF · ヒューマノイド',
        blurb: 'Unitree 公式 29 自由度。Isaac/MuJoCo RL・全身制御・移動操作向け。',
        formFactor: 'フルサイズ人型',
      },
    },
  },
}
