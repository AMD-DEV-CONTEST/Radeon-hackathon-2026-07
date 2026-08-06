import React from 'react';
import {
  FileText,
  Award,
  Briefcase,
  Code,
  GraduationCap,
  Sparkles,
  TrendingUp,
  Upload,
  Bot,
  Eye,
  Trash2,
  ChevronRight,
  ArrowUpRight,
  ShieldCheck,
} from 'lucide-react';
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
  AreaChart,
  Area,
} from 'recharts';
import { DocumentItem, UserProfile, CareerInsightsData } from '../types';

interface DashboardOverviewProps {
  user: UserProfile;
  documents: DocumentItem[];
  insights: CareerInsightsData;
  onOpenUpload: () => void;
  onNavigate: (tab: string) => void;
  onSelectDocument: (doc: DocumentItem) => void;
  onDeleteDocument: (docId: string) => void;
}

export const DashboardOverview: React.FC<DashboardOverviewProps> = ({
  user,
  documents,
  insights,
  onOpenUpload,
  onNavigate,
  onSelectDocument,
  onDeleteDocument,
}) => {
  // Compute metric stats
  const totalDocs = documents.length;
  const certCount = documents.filter((d) => d.category === 'Certificates').length;
  const projCount = documents.filter((d) => d.category === 'Projects').length;
  const internCount = documents.filter((d) => d.category === 'Internships').length;
  const resumeCount = documents.filter((d) => d.category === 'Resume').length;

  const allSkills = Array.from(new Set(documents.flatMap((d) => d.skills)));

  // Category counts for Pie Chart
  const categoryCounts = [
    { name: 'Projects', value: projCount, color: '#4F9DFF' },
    { name: 'Certificates', value: certCount, color: '#6366F1' },
    { name: 'Internships', value: internCount, color: '#10B981' },
    { name: 'Resumes', value: resumeCount, color: '#F59E0B' },
    {
      name: 'Other',
      value: totalDocs - (projCount + certCount + internCount + resumeCount),
      color: '#EC4899',
    },
  ].filter((c) => c.value > 0);

  // Top Skills for Bar Chart
  const skillFreqMap = new Map<string, number>();
  documents.forEach((doc) => {
    doc.skills.forEach((s) => {
      skillFreqMap.set(s, (skillFreqMap.get(s) || 0) + 1);
    });
  });

  const skillsChartData = Array.from(skillFreqMap.entries())
    .map(([skill, count]) => ({ skill, count }))
    .sort((a, b) => b.count - a.count)
    .slice(0, 6);

  // Growth timeline mock area data
  const growthData = [
    { month: 'Jan 24', docs: 1, skills: 3 },
    { month: 'Jun 24', docs: 3, skills: 7 },
    { month: 'Oct 24', docs: 5, skills: 10 },
    { month: 'Mar 25', docs: 6, skills: 11 },
    { month: 'Summer 25', docs: 7, skills: 12 },
    { month: '2026 Today', docs: totalDocs, skills: allSkills.length },
  ];

  return (
    <div className="space-[#071326] text-white p-4 lg:p-8 space-y-8 max-w-7xl mx-auto">
      {/* Welcome Banner */}
      <div className="rounded-2xl bg-gradient-to-r from-[#0B1F3A] via-blue-950 to-indigo-950 border border-sky-500/20 p-6 lg:p-8 relative overflow-hidden shadow-xl">
        <div className="absolute top-0 right-0 w-80 h-80 bg-sky-500/10 rounded-full blur-3xl pointer-events-none" />

        <div className="relative z-10 flex flex-col md:flex-row items-start md:items-center justify-between gap-6">
          <div className="space-y-2">
            <div className="inline-flex items-center space-x-2 px-3 py-1 rounded-full bg-sky-500/15 border border-sky-500/30 text-sky-300 text-xs font-mono">
              <Sparkles className="w-3.5 h-3.5" />
              <span>AI Identity System Sync Complete</span>
            </div>

            <h1 className="text-2xl sm:text-3xl font-extrabold text-white">
              Welcome back, {user.name}!
            </h1>
            <p className="text-slate-300 text-xs sm:text-sm max-w-xl">
              Target Career: <span className="text-sky-400 font-semibold">{user.targetRole}</span> • {user.university}
            </p>
          </div>

          <div className="flex items-center space-x-3 shrink-0">
            <button
              onClick={() => onNavigate('chat')}
              className="px-4 py-2.5 rounded-xl bg-white/10 hover:bg-white/15 text-slate-200 text-xs font-semibold backdrop-blur-md flex items-center space-x-2 border border-white/10 transition-colors"
            >
              <Bot className="w-4 h-4 text-sky-400" />
              <span>Ask AI Assistant</span>
            </button>

            <button
              onClick={onOpenUpload}
              className="px-5 py-2.5 rounded-xl bg-gradient-to-r from-sky-500 to-blue-600 hover:from-sky-400 hover:to-blue-500 text-white text-xs font-semibold shadow-lg shadow-sky-500/20 flex items-center space-x-2 transition-all transform hover:-translate-y-0.5"
            >
              <Upload className="w-4 h-4" />
              <span>Upload Document</span>
            </button>
          </div>
        </div>
      </div>

      {/* Metrics Row */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-4">
        {[
          { label: 'Total Docs', value: totalDocs, icon: <FileText className="w-4 h-4 text-sky-400" /> },
          { label: 'Certificates', value: certCount, icon: <Award className="w-4 h-4 text-indigo-400" /> },
          { label: 'Projects', value: projCount, icon: <Code className="w-4 h-4 text-blue-400" /> },
          { label: 'Skills Mapped', value: allSkills.length, icon: <GraduationCap className="w-4 h-4 text-teal-400" /> },
          { label: 'Internships', value: internCount, icon: <Briefcase className="w-4 h-4 text-emerald-400" /> },
          { label: 'ATS Resume Score', value: `${insights.atsScore}/100`, icon: <TrendingUp className="w-4 h-4 text-purple-400" /> },
        ].map((card, idx) => (
          <div
            key={idx}
            className="p-4 rounded-xl bg-[#0B1F3A]/80 border border-white/10 hover:border-sky-500/30 transition-all backdrop-blur-md space-y-2"
          >
            <div className="flex items-center justify-between">
              <span className="text-[11px] text-slate-400 font-medium">{card.label}</span>
              <div className="p-1.5 rounded-lg bg-white/5">{card.icon}</div>
            </div>
            <div className="text-xl sm:text-2xl font-bold font-mono text-white">{card.value}</div>
          </div>
        ))}
      </div>

      {/* Charts Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Skills Distribution Bar Chart */}
        <div className="p-5 rounded-2xl bg-[#0B1F3A]/80 border border-white/10 space-y-4">
          <div className="flex items-center justify-between border-b border-white/10 pb-3">
            <h3 className="text-sm font-bold text-white flex items-center space-x-2">
              <Code className="w-4 h-4 text-sky-400" />
              <span>Skills Frequency</span>
            </h3>
            <span className="text-[10px] text-sky-400 font-mono">Mapped from Vault</span>
          </div>
          <div className="h-48">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={skillsChartData} layout="vertical">
                <XAxis type="number" hide />
                <YAxis dataKey="skill" type="category" stroke="#94A3B8" fontSize={11} width={100} />
                <Tooltip
                  contentStyle={{ backgroundColor: '#0B1F3A', borderColor: '#334155', borderRadius: '8px', fontSize: '12px' }}
                />
                <Bar dataKey="count" fill="#4F9DFF" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Documents by Category Donut Chart */}
        <div className="p-5 rounded-2xl bg-[#0B1F3A]/80 border border-white/10 space-y-4">
          <div className="flex items-center justify-between border-b border-white/10 pb-3">
            <h3 className="text-sm font-bold text-white flex items-center space-x-2">
              <FileText className="w-4 h-4 text-indigo-400" />
              <span>Vault Composition</span>
            </h3>
            <span className="text-[10px] text-slate-400 font-mono">{totalDocs} Items</span>
          </div>
          <div className="h-48 flex items-center justify-center">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie data={categoryCounts} innerRadius={45} outerRadius={70} paddingAngle={4} dataKey="value">
                  {categoryCounts.map((entry, index) => (
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

        {/* Growth & Timeline Area Chart */}
        <div className="p-5 rounded-2xl bg-[#0B1F3A]/80 border border-white/10 space-y-4">
          <div className="flex items-center justify-between border-b border-white/10 pb-3">
            <h3 className="text-sm font-bold text-white flex items-center space-x-2">
              <TrendingUp className="w-4 h-4 text-emerald-400" />
              <span>Journey Growth</span>
            </h3>
            <span className="text-[10px] text-emerald-400 font-mono">Trajectory</span>
          </div>
          <div className="h-48">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={growthData}>
                <XAxis dataKey="month" stroke="#94A3B8" fontSize={10} />
                <YAxis stroke="#94A3B8" fontSize={10} />
                <Tooltip
                  contentStyle={{ backgroundColor: '#0B1F3A', borderColor: '#334155', borderRadius: '8px', fontSize: '12px' }}
                />
                <Area type="monotone" dataKey="skills" stroke="#10B981" fill="#10B98120" />
                <Area type="monotone" dataKey="docs" stroke="#4F9DFF" fill="#4F9DFF20" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      {/* Quick AI Career Insights Recommendation Card */}
      <div className="p-6 rounded-2xl bg-gradient-to-r from-indigo-950/60 to-slate-900/90 border border-indigo-500/30 flex flex-col md:flex-row items-center justify-between gap-6">
        <div className="flex items-start space-x-4">
          <div className="p-3 rounded-xl bg-indigo-500/20 text-indigo-400 shrink-0">
            <Bot className="w-6 h-6" />
          </div>
          <div>
            <div className="flex items-center space-x-2 mb-1">
              <span className="text-xs font-bold text-indigo-300 uppercase tracking-wider font-mono">
                AI Career Insight
              </span>
              <span className="text-[10px] bg-indigo-500/20 text-indigo-300 px-2 py-0.5 rounded font-mono">
                ATS Score: {insights.atsScore}%
              </span>
            </div>
            <h4 className="text-base font-bold text-white mb-1">
              Match for {insights.recommendedCareers[0]?.title || 'AI/ML Engineer'} is high!
            </h4>
            <p className="text-xs text-slate-300 max-w-2xl leading-relaxed">
              Your Stanford Deep Learning certificate and Goldman Sachs internship position you strongly. Adding Kubernetes & System Design experience can boost your ATS match to 98%.
            </p>
          </div>
        </div>

        <button
          onClick={() => onNavigate('insights')}
          className="px-5 py-2.5 rounded-xl bg-indigo-500/20 hover:bg-indigo-500/30 border border-indigo-500/40 text-indigo-200 text-xs font-semibold whitespace-nowrap flex items-center space-x-2 transition-colors"
        >
          <span>View Full Career Insights</span>
          <ArrowUpRight className="w-4 h-4" />
        </button>
      </div>

      {/* Recent Uploaded Documents Table */}
      <div className="p-6 rounded-2xl bg-[#0B1F3A]/80 border border-white/10 space-y-4">
        <div className="flex items-center justify-between border-b border-white/10 pb-4">
          <div>
            <h3 className="text-base font-bold text-white">Recent Documents Vault</h3>
            <p className="text-xs text-slate-400">Indexed documents, certificates, and extracted skills</p>
          </div>

          <button
            onClick={() => onNavigate('documents')}
            className="text-xs font-semibold text-sky-400 hover:text-sky-300 flex items-center space-x-1"
          >
            <span>View All Documents</span>
            <ChevronRight className="w-4 h-4" />
          </button>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="text-slate-400 font-mono border-b border-white/10 uppercase text-[10px]">
                <th className="py-3 px-3">Title & File</th>
                <th className="py-3 px-3">Category</th>
                <th className="py-3 px-3">Issuer / Org</th>
                <th className="py-3 px-3">Extracted Skills</th>
                <th className="py-3 px-3">Status</th>
                <th className="py-3 px-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/5">
              {documents.slice(0, 5).map((doc) => (
                <tr key={doc.id} className="hover:bg-white/5 transition-colors">
                  <td className="py-3 px-3">
                    <strong className="text-white block font-semibold hover:text-sky-300 cursor-pointer" onClick={() => onSelectDocument(doc)}>
                      {doc.title}
                    </strong>
                    <span className="text-[10px] text-slate-400 font-mono">{doc.fileName} • {doc.fileSize}</span>
                  </td>
                  <td className="py-3 px-3">
                    <span className="px-2 py-0.5 rounded bg-sky-500/15 text-sky-300 font-mono text-[10px]">
                      {doc.category}
                    </span>
                  </td>
                  <td className="py-3 px-3 text-slate-300">{doc.organization}</td>
                  <td className="py-3 px-3">
                    <div className="flex flex-wrap gap-1 max-w-xs">
                      {doc.skills.slice(0, 3).map((s, idx) => (
                        <span key={idx} className="px-1.5 py-0.5 rounded bg-slate-800 text-slate-300 text-[10px]">
                          {s}
                        </span>
                      ))}
                      {doc.skills.length > 3 && (
                        <span className="text-[10px] text-slate-400">+{doc.skills.length - 3}</span>
                      )}
                    </div>
                  </td>
                  <td className="py-3 px-3">
                    <span className="inline-flex items-center space-x-1 text-emerald-400 font-mono text-[10px]">
                      <ShieldCheck className="w-3 h-3" />
                      <span>Indexed</span>
                    </span>
                  </td>
                  <td className="py-3 px-3 text-right space-x-2">
                    <button
                      onClick={() => onSelectDocument(doc)}
                      className="p-1.5 rounded-lg bg-sky-500/10 hover:bg-sky-500/20 text-sky-400"
                      title="View Details"
                    >
                      <Eye className="w-3.5 h-3.5" />
                    </button>
                    <button
                      onClick={() => onDeleteDocument(doc.id)}
                      className="p-1.5 rounded-lg bg-red-500/10 hover:bg-red-500/20 text-red-400"
                      title="Delete"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
