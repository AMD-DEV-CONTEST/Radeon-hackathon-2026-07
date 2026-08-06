'use client';

import type { ReactNode } from 'react';

interface SwitchProps {
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  disabled?: boolean;
  size?: 'sm' | 'default';
  className?: string;
}

/**
 * shadcn/ui-inspired Switch — clean, minimal, no decorative effects.
 * Solid accent when active, neutral when off. 200ms state transition.
 * Uses CSS variables for theme-aware colors.
 *
 * Ref: https://ui.shadcn.com/docs/components/switch
 */
export function Switch({ checked, onCheckedChange, disabled, size = 'default', className }: SwitchProps) {
  const isSm = size === 'sm';
  const trackW = isSm ? '36px' : '44px';
  const trackH = isSm ? '20px' : '24px';
  const thumbSize = isSm ? '14px' : '18px';
  const thumbTravel = isSm ? '16px' : '20px';

  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      data-state={checked ? 'checked' : 'unchecked'}
      disabled={disabled}
      onClick={() => onCheckedChange(!checked)}
      onKeyDown={(e) => {
        if (e.key === ' ' || e.key === 'Enter') {
          e.preventDefault();
          onCheckedChange(!checked);
        }
      }}
      className={`relative inline-flex shrink-0 cursor-pointer items-center rounded-full border outline-none transition-colors duration-200 focus-visible:ring-2 focus-visible:ring-accent/40 disabled:cursor-not-allowed disabled:opacity-50 ${className ?? ''}`}
      style={{
        width: trackW,
        height: trackH,
        borderWidth: '1px',
        borderColor: checked
          ? 'rgb(var(--accent) / 0.3)'
          : 'rgb(var(--border) / 0.1)',
        background: checked
          ? 'rgb(var(--accent))'
          : 'rgb(var(--surface) / 0.04)',
      }}
    >
      <span
        className="pointer-events-none block rounded-full transition-transform duration-200"
        style={{
          width: thumbSize,
          height: thumbSize,
          marginLeft: '2px',
          background: checked ? '#ffffff' : 'rgb(var(--text) / 0.7)',
          transform: checked ? `translateX(${thumbTravel})` : 'translateX(0)',
        }}
      />
    </button>
  );
}

/**
 * A labeled toggle row — combines Switch with label and description.
 */
export function ToggleRow({
  checked,
  onCheckedChange,
  label,
  description,
  icon,
  disabled,
}: {
  checked: boolean;
  onCheckedChange: (v: boolean) => void;
  label: string;
  description?: string;
  icon?: ReactNode;
  disabled?: boolean;
}) {
  return (
    <div className="group/toggle flex items-center justify-between gap-4 py-4 transition-colors duration-200 hover:bg-black/[0.015] dark:hover:bg-white/[0.015] -mx-2 px-2 rounded-lg">
      <div className="flex min-w-0 flex-1 items-start gap-3">
        {icon && (
          <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-black/[0.06] bg-black/[0.02] text-accent/70 transition-colors duration-200 group-hover/toggle:border-black/[0.12] dark:border-white/[0.06] dark:bg-white/[0.02] dark:group-hover/toggle:border-white/[0.12]">
            {icon}
          </div>
        )}
        <div className="min-w-0 flex-1">
          <p className="text-[14px] font-medium text-primary">{label}</p>
          {description && (
            <p className="mt-0.5 text-[12px] leading-relaxed text-tertiary">{description}</p>
          )}
        </div>
      </div>
      <Switch
        checked={checked}
        onCheckedChange={onCheckedChange}
        disabled={disabled}
      />
    </div>
  );
}
