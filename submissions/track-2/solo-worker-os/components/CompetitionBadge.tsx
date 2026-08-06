import Link from 'next/link';

interface CompetitionBadgeProps {
  mode?: 'qwen' | 'casper' | 'default';
  variant?: 'badge' | 'inline';
  children?: React.ReactNode;
}

export default function CompetitionBadge({
  mode = 'default',
  variant = 'inline',
  children,
}: CompetitionBadgeProps) {
  const config = {
    qwen: {
      label: 'Qwen Global AI Hackathon',
      bg: 'bg-violet-400/10',
      border: 'border-violet-400/20',
      text: 'text-violet-300',
    },
    casper: {
      label: 'Casper Agentic Buildathon 2026',
      bg: 'bg-teal-400/10',
      border: 'border-teal-400/20',
      text: 'text-teal-300',
    },
    default: {
      label: 'Solo Worker OS',
      bg: 'bg-amber-400/10',
      border: 'border-amber-400/20',
      text: 'text-amber-300',
    },
  }[mode];

  if (variant === 'badge') {
    return (
      <div className={`inline-flex items-center gap-2 rounded-full border ${config.border} ${config.bg} px-3 py-1`}>
        <span className={`text-[11px] font-bold uppercase tracking-widest ${config.text}`}>
          {children ?? config.label}
        </span>
      </div>
    );
  }

  return (
    <span className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-[10px] font-bold ${config.border} ${config.bg} ${config.text}`}>
      {children ?? config.label}
    </span>
  );
}
