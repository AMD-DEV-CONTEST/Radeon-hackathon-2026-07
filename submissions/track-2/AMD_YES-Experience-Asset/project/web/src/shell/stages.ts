import type { Milestone } from '../contracts/types';

export type ShellView = 'm1' | 'm2' | 'm3' | 'm4' | 'm5' | 'status';

/**
 * Stage order follows the product flow M1 -> M5, unlike the original header
 * nav which rendered M5 first. The ids keep the historical `view-*` naming so
 * existing selectors and URL semantics are unchanged.
 *
 * `milestone` is null for screens the backend does not track as a milestone.
 */
export const STAGES: ReadonlyArray<{
  id: ShellView;
  icon: string;
  label: string;
  milestone: Milestone | null;
}> = [
  { id: 'm1', icon: '◔', label: 'M1 边界与目标', milestone: 'M1' },
  { id: 'm2', icon: '◑', label: 'M2 关键时刻', milestone: 'M2' },
  { id: 'm3', icon: '◕', label: 'M3 决策账本', milestone: 'M3' },
  { id: 'm4', icon: '●', label: 'M4 洞察与边界', milestone: 'M4' },
  { id: 'm5', icon: '◈', label: 'M5 路由与分享', milestone: 'M5' },
  { id: 'status', icon: '◇', label: '系统状态', milestone: null },
];
