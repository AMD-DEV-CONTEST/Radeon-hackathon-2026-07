import React from 'react';
import { BarChart3, PieChart as PieIcon, TrendingUp, Calendar, ShieldCheck, Award } from 'lucide-react';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
  LineChart,
  Line,
} from 'recharts';
import { DocumentItem } from '../types';

interface AnalyticsViewProps {
  documents: DocumentItem[];
}

export const AnalyticsView: React.FC<AnalyticsViewProps> = ({ documents }) => {
  // Monthly uploads data
  const monthlyData = [
    { month: 'Jan', uploads: 1 },
    { month: 'Feb', uploads: 0 },
    { month: 'Mar', uploads: 1 },
    { month: 'Apr', uploads: 0 },
    { month: 'May', uploads: 0 },
    { month: 'Jun', uploads: 2 },
    { month: 'Jul', uploads: 1 },
    { month: 'Aug', uploads: 1 },
    { month: 'Sep', uploads: 1 },
    { month: 'Oct', uploads: 1 },
    { month: 'Nov', uploads: 1 },
    { month: 'Dec', uploads: 1 },
  ];

  // Category breakdown data
  const categoryMap = new Map<string, number>();
  documents.forEach((d) => {
    categoryMap.set(d.category, (categoryMap.get(d.category) || 0) + 1);
  });

  const categoryChartData = Array.from(categoryMap.entries()).map(([name, value], idx) => ({
    name,
    value,
    color: ['#4F9DFF', '#6366F1', '#10B981', '#F59E0B', '#EC4899', '#8B5CF6'][idx % 6],
  }));

  // ATS Score trend over versions
  const resumeScoreTrend = [
    { version: 'v1.0 (2024)', score: 72 },
    { version: 'v1.5 (Late 2024)', score: 79 },
    { version: 'v2.0 (Mid 2025)', score: 84 },
    { version: 'v3.0 (2026 Today)', score: 88 },
  ];

  return (
    <div className="p-4 lg:p-8 space-y-8 max-w-7xl mx-auto text-white">
      {/* Header */}
      <div className="border-b border-white/10 pb-6">
        <h1 className="text-2xl font-bold text-white flex items-center space-x-3">
          <BarChart3 className="w-6 h-6 text-sky-400" />
          <span>Analytics & Portfolio Metrics</span>
        </h1>
        <p className="text-xs text-slate-400 mt-1">
          Deep-dive visual analytics tracking document velocity, skill frequency, and ATS resume progression.
        </p>
      </div>

      {/* Grid of Recharts */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {/* Documents Uploaded Monthly */}
        <div className="p-5 rounded-2xl bg-[#0B1F3A]/90 border border-white/10 space-y-4 shadow-xl">
          <div className="flex items-center justify-between border-b border-white/10 pb-3">
            <h3 className="text-sm font-bold text-white flex items-center space-x-2">
              <Calendar className="w-4 h-4 text-sky-400" />
              <span>Monthly Upload Velocity</span>
            </h3>
            <span className="text-[10px] text-slate-400 font-mono">2024 - 2026</span>
          </div>
          <div className="h-48">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={monthlyData}>
                <XAxis dataKey="month" stroke="#94A3B8" fontSize={10} />
                <YAxis stroke="#94A3B8" fontSize={10} />
                <Tooltip
                  contentStyle={{ backgroundColor: '#0B1F3A', borderColor: '#334155', borderRadius: '8px', fontSize: '12px' }}
                />
                <Bar dataKey="uploads" fill="#4F9DFF" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Portfolio Categories Breakdown */}
        <div className="p-5 rounded-2xl bg-[#0B1F3A]/90 border border-white/10 space-y-4 shadow-xl">
          <div className="flex items-center justify-between border-b border-white/10 pb-3">
            <h3 className="text-sm font-bold text-white flex items-center space-x-2">
              <PieIcon className="w-4 h-4 text-indigo-400" />
              <span>Vault Composition</span>
            </h3>
            <span className="text-[10px] text-indigo-400 font-mono">{documents.length} Docs</span>
          </div>
          <div className="h-48 flex items-center justify-center">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie data={categoryChartData} innerRadius={45} outerRadius={70} paddingAngle={4} dataKey="value">
                  {categoryChartData.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={entry.color} />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={{ backgroundColor: '#0B1F3A', borderColor: '#334155', borderRadius: '8px', fontSize: '12px' }}
                />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* ATS Score Growth Trend */}
        <div className="p-5 rounded-2xl bg-[#0B1F3A]/90 border border-white/10 space-y-4 shadow-xl">
          <div className="flex items-center justify-between border-b border-white/10 pb-3">
            <h3 className="text-sm font-bold text-white flex items-center space-x-2">
              <TrendingUp className="w-4 h-4 text-emerald-400" />
              <span>ATS Score Progression</span>
            </h3>
            <span className="text-[10px] text-emerald-400 font-mono">+16 pts Gain</span>
          </div>
          <div className="h-48">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={resumeScoreTrend}>
                <XAxis dataKey="version" stroke="#94A3B8" fontSize={9} />
                <YAxis stroke="#94A3B8" fontSize={10} domain={[60, 100]} />
                <Tooltip
                  contentStyle={{ backgroundColor: '#0B1F3A', borderColor: '#334155', borderRadius: '8px', fontSize: '12px' }}
                />
                <Line type="monotone" dataKey="score" stroke="#10B981" strokeWidth={3} dot={{ r: 5, fill: '#10B981' }} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>
    </div>
  );
};
