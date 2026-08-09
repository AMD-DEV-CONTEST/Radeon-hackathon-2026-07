import React, { useEffect, useState } from 'react';

interface BarChartProps {
  data: { label: string; value: number }[];
  max: number;
}

export const BarChart: React.FC<BarChartProps> = ({ data, max }) => {
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  return (
    <div style={{ padding: '1rem 0' }}>
      {data.map((item, i) => {
        const width = mounted ? `${(item.value / max) * 100}%` : '0%';
        return (
          <div key={i} className="bar-chart-row">
            <div className="bar-label">{item.label}</div>
            <div className="bar-track">
              <div className="bar-fill" style={{ width }}></div>
            </div>
            <div className="bar-value">{item.value}</div>
          </div>
        );
      })}
    </div>
  );
};
