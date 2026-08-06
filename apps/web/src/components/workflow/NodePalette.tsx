import React, { useMemo, useState, useEffect } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { nodeTemplates } from '../../store/workflowStore';
import { useAuth } from '../../lib/authContext';
import {
  canUseWorkflowNode,
  requiredTierForNode,
  tierAtLeast,
  type SubscriptionTier,
} from '../../lib/entitlements';
import { UpgradeModal } from '../billing/UpgradeModal';
import {
  Bot,
  Video,
  Database,
  Brain,
  Rocket,
  BarChart3,
  Package,
  Camera,
  Radio,
  Wrench,
  Lock,
  Target,
  Clapperboard,
  CheckCircle,
  Tag,
  CircleDot,
} from 'lucide-react';

const iconMap: Record<string, React.ReactNode> = {
  '🤖': <Bot className="w-5 h-5" />,
  '📹': <Video className="w-5 h-5" />,
  '📊': <BarChart3 className="w-5 h-5" />,
  '🧠': <Brain className="w-5 h-5" />,
  '🚀': <Rocket className="w-5 h-5" />,
  '📈': <BarChart3 className="w-5 h-5" />,
  '📦': <Package className="w-5 h-5" />,
  '🎥': <Camera className="w-5 h-5" />,
  '📡': <Radio className="w-5 h-5" />,
  '🛠️': <Wrench className="w-5 h-5" />,
  '💾': <Database className="w-5 h-5" />,
  '⚡': <Wrench className="w-5 h-5" />,
  '🎬': <Clapperboard className="w-5 h-5" />,
  '✅': <CheckCircle className="w-5 h-5" />,
  '🎯': <Target className="w-5 h-5" />,
  '🏷️': <Tag className="w-5 h-5" />,
  '🔵': <CircleDot className="w-5 h-5" />,
};

const LEGACY_TYPES = ['robot_connect', 'record', 'train', 'deploy', 'visualize'];
const API_PENDING_TYPES = new Set([
  'world_model_generator', 'depth_estimator', 'pose_action_extractor',
  'urdf_inpaint', 'idm_inverse_dynamics', 'reward_model_tuning',
]);

// Node types that have a template + type definition but NO executor case in
// workflowEngine.ts. Dragging them onto the canvas and clicking Run would
// throw "Unknown node type" — so we hide them from the palette entirely.
// Templates and type defs are kept in workflowStore.ts / workflow.ts so
// future executors can be wired without re-adding the palette entry.
// See progress/M28-consolidation-execution-plan.md T0-4.
const NO_EXECUTOR_TYPES = new Set([
  'isaac_sim_pretrain',
  'lekiwi_handshake_collect',
  'camera_denoise',
  'trajectory_optimize',
]);

const PALETTE_COLLAPSE_KEY = 'botverse_palette_collapsed';
const DEFAULT_OPEN = new Set(['qualia-data', 'qualia-models']);

function loadCollapsed(): Set<string> {
  try {
    const raw = localStorage.getItem(PALETTE_COLLAPSE_KEY);
    if (!raw) return new Set(DEFAULT_OPEN);
    const closed = JSON.parse(raw) as string[];
    const allIds = [
      'qualia-data', 'qualia-transforms', 'qualia-generative', 'qualia-outputs',
      'qualia-models', 'skill-factory', 'real-recording', 'skill-run',
      'reachy-actions', 'legacy',
    ];
    return new Set(allIds.filter((id) => !closed.includes(id)));
  } catch {
    return new Set(DEFAULT_OPEN);
  }
}

function saveCollapsed(open: Set<string>, allCategoryIds: string[]) {
  const closed = allCategoryIds.filter((id) => !open.has(id));
  localStorage.setItem(PALETTE_COLLAPSE_KEY, JSON.stringify(closed));
}

export function NodePalette() {
  const { user } = useAuth();
  const [upgradeOpen, setUpgradeOpen] = useState(false);
  const [upgradeTier, setUpgradeTier] = useState<SubscriptionTier>('pro');
  const [upgradeReason, setUpgradeReason] = useState<string>();
  const [openCategories, setOpenCategories] = useState<Set<string>>(() => loadCollapsed());

  const ent = user?.entitlements;
  const tier = (user?.subscription_tier ?? ent?.tier ?? 'free') as SubscriptionTier;
  const showLegacy = ent?.limits.show_legacy_workflow_nodes ?? false;

  const visibleTemplates = useMemo(() => {
    return nodeTemplates.filter((t) => {
      if (NO_EXECUTOR_TYPES.has(t.type)) return false;
      if (LEGACY_TYPES.includes(t.type) && !showLegacy) return false;
      const min = (t.minTier ?? 'free') as SubscriptionTier;
      return tierAtLeast(tier, min);
    });
  }, [tier, showLegacy]);

  const onDragStart = (event: React.DragEvent, template: typeof nodeTemplates[0]) => {
    if (!canUseWorkflowNode(ent, template.type)) {
      event.preventDefault();
      setUpgradeTier(requiredTierForNode(template.type));
      setUpgradeReason(`节点「${template.label}」需要升级后使用`);
      setUpgradeOpen(true);
      return;
    }
    event.dataTransfer.setData('application/reactflow', JSON.stringify(template));
    event.dataTransfer.effectAllowed = 'move';
  };

  const categories: Array<{ id: string; label: string; color: string; hint?: string; types: string[] }> = [
    {
      id: 'qualia-data',
      label: 'DATA SOURCES',
      color: '#0ea5e9',
      hint: 'HF Dataset / Ego Video inputs',
      types: ['hf_dataset', 'ego_dataset'],
    },
    {
      id: 'qualia-transforms',
      label: 'TRANSFORMS',
      color: '#eab308',
      hint: 'Augmentation & preprocessing',
      types: ['camera_noise', 'trajectory_noise', 'depth_estimator', 'pose_action_extractor'],
    },
    {
      id: 'qualia-generative',
      label: 'GENERATIVE',
      color: '#64748b',
      hint: 'World Model / URDF Inpaint / IDM',
      types: ['world_model_generator', 'urdf_inpaint', 'idm_inverse_dynamics'],
    },
    {
      id: 'qualia-outputs',
      label: 'OUTPUTS',
      color: '#22c55e',
      hint: 'Output Dataset / Merge',
      types: ['output_dataset', 'merge_datasets'],
    },
    {
      id: 'qualia-models',
      label: 'FOUNDATION MODELS',
      color: '#f59e0b',
      hint: 'Finetune VLA / Reward / Monitor',
      types: ['qualia_finetune', 'reward_model_tuning', 'job_monitor'],
    },
    {
      id: 'skill-factory',
      label: 'SKILL FACTORY',
      color: '#8b5cf6',
      hint: 'Evaluate → Publish Skill',
      types: ['evaluate', 'publish_skill'],
    },
    {
      id: 'real-recording',
      label: 'ROBOT RECORDING',
      color: '#ef4444',
      hint: 'SO-101 / Reachy real APIs',
      types: ['record_dataset_start', 'recording_monitor', 'dataset_check', 'reachy_daemon_check', 'reachy_record_move', 'reachy_move_output'],
    },
    {
      id: 'reachy-actions',
      label: 'REACHY ACTIONS',
      color: '#f59e0b',
      hint: 'M24: 官方 HF 动作 + 对话 App',
      types: ['reachy_play_move', 'reachy_emotion', 'reachy_start_conversation', 'reachy_stop_app'],
    },
    {
      id: 'skill-run',
      label: 'RUN SKILL',
      color: '#f97316',
      hint: 'Invoke installed skills',
      types: ['skill_invoke'],
    },
    // SIMULATION and SCENARIOS categories removed — their only node types
    // (isaac_sim_pretrain, lekiwi_handshake_collect) have no executor in
    // workflowEngine.ts and would throw "Unknown node type" on Run.
    // See progress/M28-consolidation-execution-plan.md T0-4.
    {
      id: 'legacy',
      label: 'LEGACY',
      color: '#6b7280',
      hint: 'Old demo / compat nodes',
      types: ['robot_connect', 'record', 'train', 'deploy', 'visualize', 'dataset_load', 'camera_map', 'finetune_job'],
    },
  ];

  const categoryIds = categories.map((c) => c.id);

  useEffect(() => {
    saveCollapsed(openCategories, categoryIds);
  }, [openCategories, categoryIds.join(',')]);

  const toggleCategory = (id: string) => {
    setOpenCategories((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const lockedTemplates = nodeTemplates.filter((t) => {
    if (LEGACY_TYPES.includes(t.type) && !showLegacy) return false;
    const min = (t.minTier ?? 'free') as SubscriptionTier;
    return !tierAtLeast(tier, min);
  });

  return (
    <>
      <UpgradeModal
        open={upgradeOpen}
        onClose={() => setUpgradeOpen(false)}
        requiredTier={upgradeTier}
        reason={upgradeReason}
      />
      <div className="w-64 border-r bg-card flex flex-col">
        <div className="p-4 border-b">
          <h2 className="font-semibold text-sm">Node Palette</h2>
          <p className="text-xs text-muted-foreground mt-1">
            当前套餐：{ent?.display_name ?? tier}
          </p>
        </div>

        <div className="flex-1 overflow-y-auto p-3 space-y-4">
          {categories.map((category) => {
            const categoryNodes = visibleTemplates.filter((n) =>
              category.types.includes(n.type)
            );

            if (categoryNodes.length === 0) return null;

            const isOpen = openCategories.has(category.id);

            return (
              <div key={category.id}>
                <button
                  type="button"
                  className="w-full text-xs font-medium mb-1 flex items-center gap-2 hover:opacity-80"
                  style={{ color: category.color }}
                  onClick={() => toggleCategory(category.id)}
                >
                  {isOpen ? (
                    <ChevronDown className="w-3.5 h-3.5 shrink-0" />
                  ) : (
                    <ChevronRight className="w-3.5 h-3.5 shrink-0" />
                  )}
                  <div
                    className="w-2 h-2 rounded-full shrink-0"
                    style={{ backgroundColor: category.color }}
                  />
                  <span className="text-left">{category.label}</span>
                  <span className="text-[10px] text-muted-foreground ml-auto">
                    {categoryNodes.length}
                  </span>
                </button>
                {isOpen && category.hint && (
                  <p className="text-[10px] text-muted-foreground mb-2 ml-6">{category.hint}</p>
                )}

                {isOpen && <div className="space-y-2">
                  {categoryNodes.map((template) => {
                    const locked = !canUseWorkflowNode(ent, template.type);
                    return (
                      <div
                        key={template.type}
                        draggable={!locked}
                        onDragStart={(e) => onDragStart(e, template)}
                        className={`p-3 rounded-lg border bg-background transition-colors group ${
                          locked ? 'opacity-60 cursor-not-allowed' : 'cursor-move hover:border-primary'
                        }`}
                        style={{ borderLeftColor: template.color, borderLeftWidth: '3px' }}
                      >
                        <div className="flex items-center gap-2">
                          <div
                            className="w-8 h-8 rounded-lg flex items-center justify-center text-white shrink-0"
                            style={{ backgroundColor: template.color }}
                          >
                            {iconMap[template.icon] || template.icon}
                          </div>
                          <div className="flex-1 min-w-0">
                            <div className="text-sm font-medium truncate flex items-center gap-1">
                              {template.label}
                              {template.finetuneCore && (
                                <span className="text-[9px] uppercase px-1 py-0.5 rounded bg-primary/10 text-primary font-semibold">
                                  core
                                </span>
                              )}
                              {API_PENDING_TYPES.has(template.type) && (
                                <span className="text-[9px] uppercase px-1 py-0.5 rounded bg-orange-500/10 text-orange-600 font-semibold">
                                  API pending
                                </span>
                              )}
                              {locked && <Lock className="w-3 h-3 text-muted-foreground" />}
                            </div>
                            <div className="text-xs text-muted-foreground truncate">
                              {template.description}
                            </div>
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>}
              </div>
            );
          })}

          {lockedTemplates.length > 0 && (
            <div className="pt-2 border-t">
              <p className="text-xs text-muted-foreground mb-2">Pro 解锁</p>
              {lockedTemplates.map((template) => (
                <button
                  key={template.type}
                  type="button"
                  className="w-full text-left p-2 mb-1 rounded border border-dashed text-xs text-muted-foreground hover:border-primary"
                  onClick={() => {
                    setUpgradeTier(requiredTierForNode(template.type));
                    setUpgradeReason(`解锁「${template.label}」`);
                    setUpgradeOpen(true);
                  }}
                >
                  <Lock className="w-3 h-3 inline mr-1" />
                  {template.label}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </>
  );
}
