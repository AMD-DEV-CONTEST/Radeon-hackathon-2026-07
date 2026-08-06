import React, { useState } from 'react';
import {
  TrendingUp,
  Target,
  Sparkles,
  Award,
  BookOpen,
  AlertCircle,
  CheckCircle2,
  RefreshCw,
  Zap,
  ChevronRight,
  ShieldCheck,
  Star,
} from 'lucide-react';
import { CareerInsightsData, UserProfile } from '../types';

interface CareerInsightsViewProps {
  user: UserProfile;
  insights: CareerInsightsData;
  onRefreshInsights: () => void;
}

export const CareerInsightsView: React.FC<CareerInsightsViewProps> = ({
  user,
  insights,
  onRefreshInsights,
}) => {
  const [isRefreshing, setIsRefreshing] = useState(false);

  const handleRefresh = async () => {
    setIsRefreshing(true);
    await onRefreshInsights();
    setIsRefreshing(false);
  };

  return (
    <div className="p-4 lg:p-8 space-y-8 max-w-6xl mx-auto text-white">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-white/10 pb-6">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center space-x-3">
            <TrendingUp className="w-6 h-6 text-sky-400" />
            <span>AI Career Insights & ATS Evaluator</span>
          </h1>
          <p className="text-xs text-slate-400 mt-1">
            Automated ATS resume scoring, skill gap analysis, and tailored learning roadmaps for{' '}
            <span className="text-sky-300 font-semibold">{user.targetRole}</span>.
          </p>
        </div>

        <button
          onClick={handleRefresh}
          disabled={isRefreshing}
          className="px-5 py-2.5 rounded-xl bg-gradient-to-r from-sky-500 to-blue-600 hover:from-sky-400 hover:to-blue-500 text-white font-semibold text-xs shadow-lg shadow-sky-500/20 flex items-center space-x-2 shrink-0 disabled:opacity-50"
        >
          <RefreshCw className={`w-4 h-4 ${isRefreshing ? 'animate-spin' : ''}`} />
          <span>Re-Evaluate Vault with Gemini</span>
        </button>
      </div>

      {/* Top Row: ATS Score Circular Gauge & Breakdown */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {/* Gauge Card */}
        <div className="p-6 rounded-2xl bg-gradient-to-b from-[#0B1F3A] to-blue-950 border border-sky-500/30 flex flex-col items-center justify-center text-center space-y-4 shadow-2xl relative overflow-hidden">
          <div className="absolute top-0 right-0 w-32 h-32 bg-sky-500/10 rounded-full blur-2xl pointer-events-none" />

          <span className="text-[10px] text-sky-400 font-mono uppercase tracking-wider font-bold">
            ATS Resume Score
          </span>

          {/* Score Circular Graphic */}
          <div className="relative w-36 h-36 flex items-center justify-center">
            <svg className="w-full h-full transform -rotate-90" viewBox="0 0 36 36">
              <path
                className="text-slate-800"
                strokeWidth="3.5"
                stroke="currentColor"
                fill="none"
                d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
              />
              <path
                className="text-sky-400 transition-all duration-1000 ease-out"
                strokeDasharray={`${insights.atsScore}, 100`}
                strokeWidth="3.5"
                strokeLinecap="round"
                stroke="currentColor"
                fill="none"
                d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
              />
            </svg>
            <div className="absolute flex flex-col items-center">
              <span className="text-3xl font-extrabold font-mono text-white">{insights.atsScore}%</span>
              <span className="text-[10px] text-emerald-400 font-semibold uppercase">Strong Match</span>
            </div>
          </div>

          <p className="text-xs text-slate-300 max-w-xs leading-relaxed">
            Your document vault matches 88% of requirements for Tier-1 AI & Machine Learning Engineering positions.
          </p>
        </div>

        {/* Breakdown Breakdown Grid */}
        <div className="md:col-span-2 p-6 rounded-2xl bg-[#0B1F3A]/90 border border-white/10 space-y-5 shadow-xl">
          <h3 className="text-sm font-bold text-white flex items-center space-x-2 border-b border-white/10 pb-3">
            <Target className="w-4 h-4 text-sky-400" />
            <span>ATS Evaluation Categories</span>
          </h3>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs">
            {[
              { label: 'Keywords Match', score: insights.atsBreakdown.keywordsScore, color: 'bg-sky-400' },
              { label: 'Formatting & Layout', score: insights.atsBreakdown.formattingScore, color: 'bg-indigo-400' },
              { label: 'Impact & Quantified Metrics', score: insights.atsBreakdown.impactMetricsScore, color: 'bg-emerald-400' },
              { label: 'Target Role Relevance', score: insights.atsBreakdown.relevanceScore, color: 'bg-purple-400' },
            ].map((cat, idx) => (
              <div key={idx} className="p-3.5 rounded-xl bg-slate-900/80 border border-white/5 space-y-2">
                <div className="flex items-center justify-between text-slate-300">
                  <span>{cat.label}</span>
                  <strong className="text-white font-mono">{cat.score}%</strong>
                </div>
                <div className="w-full h-2 rounded-full bg-slate-800 overflow-hidden">
                  <div className={`h-full ${cat.color} rounded-full`} style={{ width: `${cat.score}%` }} />
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Top Skills vs Missing Industry Skills */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Top Verified Skills */}
        <div className="p-6 rounded-2xl bg-[#0B1F3A]/90 border border-white/10 space-y-4 shadow-xl">
          <h3 className="text-sm font-bold text-white flex items-center space-x-2 border-b border-white/10 pb-3">
            <CheckCircle2 className="w-4 h-4 text-emerald-400" />
            <span>Top Verified Vault Skills</span>
          </h3>

          <div className="space-y-3">
            {insights.topSkills.map((sk, idx) => (
              <div key={idx} className="p-3 rounded-xl bg-slate-900/80 border border-white/5 space-y-1">
                <div className="flex items-center justify-between text-xs">
                  <strong className="text-white">{sk.name}</strong>
                  <span className="text-[10px] text-sky-400 font-mono">
                    {sk.level}% Proficiency ({sk.docCount} Docs)
                  </span>
                </div>
                <div className="w-full h-1.5 rounded-full bg-slate-800 overflow-hidden">
                  <div className="h-full bg-sky-400 rounded-full" style={{ width: `${sk.level}%` }} />
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Missing High-Demand Skills */}
        <div className="p-6 rounded-2xl bg-[#0B1F3A]/90 border border-white/10 space-y-4 shadow-xl">
          <h3 className="text-sm font-bold text-white flex items-center space-x-2 border-b border-white/10 pb-3">
            <AlertCircle className="w-4 h-4 text-amber-400" />
            <span>Missing Industry High-Demand Skills</span>
          </h3>

          <div className="space-y-3">
            {insights.missingSkills.map((sk, idx) => (
              <div key={idx} className="p-3.5 rounded-xl bg-slate-900/80 border border-amber-500/20 space-y-1 text-xs">
                <div className="flex items-center justify-between">
                  <strong className="text-amber-200">{sk.name}</strong>
                  <span className="px-2 py-0.5 rounded bg-amber-500/20 text-amber-300 font-mono text-[10px]">
                    {sk.importance} Priority
                  </span>
                </div>
                <p className="text-slate-300 text-[11px] leading-relaxed">{sk.reason}</p>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Recommended Career Paths */}
      <div className="p-6 rounded-2xl bg-[#0B1F3A]/90 border border-white/10 space-y-4 shadow-xl">
        <h3 className="text-sm font-bold text-white flex items-center space-x-2 border-b border-white/10 pb-3">
          <Star className="w-4 h-4 text-sky-400" />
          <span>Recommended Career Paths Based on Vault</span>
        </h3>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {insights.recommendedCareers.map((car, idx) => (
            <div key={idx} className="p-4 rounded-xl bg-slate-900/80 border border-white/5 space-y-2 text-xs">
              <div className="flex items-center justify-between">
                <span className="px-2 py-0.5 rounded bg-sky-500/15 text-sky-300 font-mono font-bold text-[10px]">
                  {car.matchPercentage}% Match
                </span>
                <span className="text-[10px] text-emerald-400 font-mono">{car.demandLevel} Demand</span>
              </div>
              <h4 className="text-sm font-bold text-white">{car.title}</h4>
              <p className="text-slate-300 text-[11px] leading-relaxed">{car.description}</p>
            </div>
          ))}
        </div>
      </div>

      {/* Actionable Learning Roadmap */}
      <div className="p-6 rounded-2xl bg-[#0B1F3A]/90 border border-white/10 space-y-4 shadow-xl">
        <h3 className="text-sm font-bold text-white flex items-center space-x-2 border-b border-white/10 pb-3">
          <BookOpen className="w-4 h-4 text-sky-400" />
          <span>Step-by-Step AI Learning Roadmap</span>
        </h3>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {insights.learningRoadmap.map((rm, idx) => (
            <div key={idx} className="p-4 rounded-xl bg-slate-900/80 border border-sky-500/20 space-y-3 text-xs">
              <div className="flex items-center justify-between">
                <span className="px-2 py-0.5 rounded bg-sky-500/20 text-sky-300 font-mono font-bold text-[10px]">
                  {rm.phase}
                </span>
                <span className="text-[10px] text-slate-400 font-mono">{rm.duration}</span>
              </div>
              <h4 className="text-sm font-bold text-white">{rm.title}</h4>
              <p className="text-slate-300 text-[11px] leading-relaxed">{rm.description}</p>

              <div className="space-y-1.5 pt-2 border-t border-white/5">
                {rm.actionItems.map((act, aIdx) => (
                  <div key={aIdx} className="flex items-start space-x-2 text-[11px] text-slate-300">
                    <CheckCircle2 className="w-3.5 h-3.5 text-sky-400 shrink-0 mt-0.5" />
                    <span>{act}</span>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Suggested Certifications & Actionable Improvement Tips */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div className="p-6 rounded-2xl bg-[#0B1F3A]/90 border border-white/10 space-y-4 shadow-xl">
          <h3 className="text-sm font-bold text-white flex items-center space-x-2 border-b border-white/10 pb-3">
            <Award className="w-4 h-4 text-indigo-400" />
            <span>Suggested Certifications</span>
          </h3>

          <div className="space-y-3">
            {insights.suggestedCertifications.map((cert, idx) => (
              <div key={idx} className="p-3.5 rounded-xl bg-slate-900/80 border border-white/5 space-y-2 text-xs">
                <div className="flex items-center justify-between">
                  <strong className="text-white">{cert.title}</strong>
                  <span className="text-[10px] text-sky-400 font-mono">{cert.estimatedHours}</span>
                </div>
                <div className="text-[10px] text-slate-400">Provider: {cert.provider}</div>
                <div className="flex flex-wrap gap-1">
                  {cert.skillsCovered.map((sk, sIdx) => (
                    <span key={sIdx} className="px-2 py-0.5 rounded bg-slate-800 text-slate-300 text-[10px]">
                      {sk}
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="p-6 rounded-2xl bg-[#0B1F3A]/90 border border-white/10 space-y-4 shadow-xl">
          <h3 className="text-sm font-bold text-white flex items-center space-x-2 border-b border-white/10 pb-3">
            <Zap className="w-4 h-4 text-yellow-400" />
            <span>Actionable Improvement Tips</span>
          </h3>

          <div className="space-y-3">
            {insights.improvementTips.map((tip, idx) => (
              <div key={idx} className="p-3 rounded-xl bg-slate-900/80 border border-white/5 flex items-start space-x-3 text-xs">
                <span className="w-5 h-5 rounded-full bg-sky-500/20 text-sky-400 font-mono font-bold flex items-center justify-center shrink-0 mt-0.5 text-[10px]">
                  {idx + 1}
                </span>
                <p className="text-slate-200 leading-relaxed">{tip}</p>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};
