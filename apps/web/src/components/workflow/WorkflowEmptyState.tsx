import { Zap, CircleDot, Bot, Layers, X } from 'lucide-react';

const QUICK_START_DEMOS = [
  {
    id: 'qualia-three-branch',
    label: 'Qualia 三链工作流',
    desc: 'HF 增强 + World Model + URDF → Merge → 训练',
    icon: <Zap className="w-5 h-5" />,
  },
  {
    id: 'skill-factory',
    label: 'Skill Factory',
    desc: '数据集 → 训练 → 评估 → 发布 Skill',
    icon: <Layers className="w-5 h-5" />,
  },
  {
    id: 'so101-recording',
    label: 'SO-101 录制',
    desc: '真实 SO-101 数据采集',
    icon: <CircleDot className="w-5 h-5" />,
  },
  {
    id: 'reachy-recording',
    label: 'Reachy 录制',
    desc: 'Reachy 自定义动作录制',
    icon: <Bot className="w-5 h-5" />,
  },
] as const;

interface WorkflowEmptyStateProps {
  onLoadTemplate: (templateId: string) => void;
  onDismiss: () => void;
}

export function WorkflowEmptyState({ onLoadTemplate, onDismiss }: WorkflowEmptyStateProps) {
  return (
    <div className="absolute inset-0 z-10 flex items-center justify-center pointer-events-none">
      <div className="pointer-events-auto relative max-w-md w-full mx-4 p-6 rounded-xl border bg-card/95 shadow-lg backdrop-blur-sm text-center">
        <button
          type="button"
          onClick={onDismiss}
          className="absolute top-3 right-3 p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
          aria-label="关闭引导"
          title="关闭"
        >
          <X className="w-4 h-4" />
        </button>
        <h2 className="text-lg font-semibold mb-1 pr-6">开始搭建工作流</h2>
        <p className="text-sm text-muted-foreground mb-5">
          从模板一键载入，或从左侧 Palette 拖拽节点到画布
        </p>
        <p className="text-xs font-medium text-muted-foreground mb-2 text-left">从模板开始</p>
        <div className="grid gap-2 mb-4">
          {QUICK_START_DEMOS.map((t) => (
            <button
              key={t.id}
              type="button"
              onClick={() => onLoadTemplate(t.id)}
              className="w-full text-left p-3 rounded-lg border hover:border-primary hover:bg-muted/50 transition-colors flex items-start gap-3"
            >
              <div className="mt-0.5 text-primary shrink-0">{t.icon}</div>
              <div className="min-w-0">
                <div className="text-sm font-medium">{t.label}</div>
                <div className="text-xs text-muted-foreground">{t.desc}</div>
              </div>
            </button>
          ))}
        </div>
        <p className="text-[11px] text-muted-foreground">
          也可点击顶部 <span className="font-medium">Demos</span> 查看更多预设
        </p>
      </div>
    </div>
  );
}
