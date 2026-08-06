import React from 'react';

interface GlassCardProps {
  children: React.ReactNode;
  className?: string;
  onClick?: () => void;
  hoverGlow?: boolean;
}

export const GlassCard: React.FC<GlassCardProps> = ({ 
  children, 
  className = '', 
  onClick, 
  hoverGlow = true 
}) => {
  return (
    <div
      onClick={onClick}
      className={`glass-card p-6 rounded-2xl relative overflow-hidden ${
        onClick ? 'cursor-pointer' : ''
      } ${
        hoverGlow 
          ? 'hover:border-primary-500/40 hover:shadow-primary-500/10' 
          : ''
      } ${className}`}
    >
      {/* Decorative gradient glow highlights inside card background */}
      {hoverGlow && (
        <div className="absolute -right-20 -top-20 w-40 h-40 rounded-full bg-primary-500/5 blur-3xl group-hover:bg-primary-500/10 pointer-events-none transition-all duration-500" />
      )}
      {children}
    </div>
  );
};

export default GlassCard;
