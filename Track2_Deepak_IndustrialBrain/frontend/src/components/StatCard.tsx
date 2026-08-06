import React from 'react';

interface StatCardProps {
  title: string;
  value: string | number;
  icon: string;
  variant?: 'blue' | 'purple' | 'amber' | 'teal';
}

export const StatCard: React.FC<StatCardProps> = ({ title, value, icon, variant = 'teal' }) => {
  return (
    <div className={`card stat-card ${variant}`}>
      <div className="stat-card-header">
        <h3 className="stat-card-title">{title}</h3>
        <span className="stat-card-icon">{icon}</span>
      </div>
      <div className="stat-card-value">
        {value}
      </div>
    </div>
  );
};
