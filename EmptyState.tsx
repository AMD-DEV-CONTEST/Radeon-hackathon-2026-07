import React from 'react';
import { LucideIcon } from 'lucide-react';

interface EmptyStateProps {
  title: string;
  description: string;
  actionLabel?: string;
  onActionClick?: () => void;
  icon: LucideIcon;
}

export const EmptyState: React.FC<EmptyStateProps> = ({
  title,
  description,
  actionLabel,
  onActionClick,
  icon: Icon
}) => {
  return (
    <div className="flex flex-col items-center justify-center p-12 text-center rounded-2xl border border-dashed border-dark-700/50 bg-dark-900/10 backdrop-blur-sm max-w-lg mx-auto animate-slide-up">
      <div className="p-4 bg-primary-500/10 rounded-full mb-5 text-primary-400 relative">
        <div className="absolute inset-0 rounded-full bg-primary-500/5 animate-ping opacity-75" />
        <Icon className="w-8 h-8" />
      </div>
      <h3 className="text-xl font-bold font-heading mb-2 text-dark-50">{title}</h3>
      <p className="text-sm text-dark-400 mb-6 max-w-sm leading-relaxed">{description}</p>
      {actionLabel && onActionClick && (
        <button
          onClick={onActionClick}
          className="px-6 py-2.5 bg-gradient-to-r from-primary-600 to-cyan-600 hover:from-primary-500 hover:to-cyan-500 text-white font-medium rounded-xl shadow-lg shadow-primary-500/15 hover:shadow-primary-500/25 transition-all text-sm duration-300 hover:scale-102"
        >
          {actionLabel}
        </button>
      )}
    </div>
  );
};

export default EmptyState;
