import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { 
  FileText, Users, Map, MessageSquare, CheckSquare, 
  Square, Calendar, Award, ArrowRight, Loader2, Sparkles, TrendingUp
} from 'lucide-react';
import { 
  ResponsiveContainer, AreaChart, Area, XAxis, YAxis, CartesianGrid, 
  Tooltip, RadarChart, PolarGrid, PolarAngleAxis, Radar
} from 'recharts';
import { useAuth } from '../context/AuthContext';
import { useNotification } from '../context/NotificationContext';
import GlassCard from '../components/GlassCard';
import axios from 'axios';

export const DashboardPage: React.FC = () => {
  const navigate = useNavigate();
  const { user } = useAuth();
  const { showToast } = useNotification();
  
  const [loading, setLoading] = useState(true);
  const [data, setData] = useState<any>(null);

  // Fetch dashboard aggregator
  const fetchDashboardData = async () => {
    try {
      const response = await axios.get('/api/dashboard/overview');
      setData(response.data);
    } catch (error) {
      console.error('[Dashboard] Failed to fetch aggregate stats:', error);
      showToast('Could not load dashboard statistics', 'error');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchDashboardData();
  }, []);

  const handleToggleTask = async (taskId: string, currentStatus: boolean) => {
    try {
      await axios.put('/api/roadmap/toggle-task', { taskId, isCompleted: !currentStatus });
      showToast(currentStatus ? 'Task marked incomplete' : 'Task completed! Keep it up.', 'success');
      fetchDashboardData(); // Refresh overview numbers
    } catch (err) {
      showToast('Could not save task completion state', 'error');
    }
  };

  if (loading) {
    return (
      <div className="h-[80vh] flex flex-col items-center justify-center gap-4">
        <Loader2 className="w-10 h-10 animate-spin text-primary-500" />
        <p className="text-sm text-dark-400">Aggregating career diagnostics...</p>
      </div>
    );
  }

  // Fallback mocks for chart displays if no real history exists
  const performanceHistory = [
    { name: 'Week 1', score: 30, interview: 20 },
    { name: 'Week 2', score: 45, interview: 40 },
    { name: 'Week 3', score: 60, interview: 55 },
    { name: 'Week 4', score: data?.stats?.resumeScore || 65, interview: data?.stats?.interviewScore || 60 },
  ];

  // Skill radar map: match target skills vs current skills
  const skillsRadar = [
    { subject: 'Backend', A: 50, B: 85, fullMark: 100 },
    { subject: 'Frontend', A: 70, B: 90, fullMark: 100 },
    { subject: 'System Design', A: 30, B: 75, fullMark: 100 },
    { subject: 'DevOps', A: 20, B: 60, fullMark: 100 },
    { subject: 'Problem Solving', A: 60, B: 80, fullMark: 100 },
    { subject: 'Communication', A: 65, B: 85, fullMark: 100 },
  ];

  return (
    <div className="flex flex-col gap-8">
      
      {/* GREETING CARD */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-dark-800/40 pb-6">
        <div>
          <h2 className="text-3xl font-extrabold font-heading text-dark-50 tracking-tight flex items-center gap-2">
            Welcome onboard, {user?.name}!
            <Sparkles className="w-6 h-6 text-yellow-400 animate-pulse-glow" />
          </h2>
          <p className="text-sm text-dark-400 mt-1">
            Let us optimize your career readiness for the role of <strong className="text-primary-400">{user?.targetCareer || 'Career Explorer'}</strong>.
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => navigate('/resume-analyzer')}
            className="px-4 py-2.5 bg-dark-900 border border-dark-800 hover:border-primary-500/25 text-dark-200 hover:text-primary-400 text-xs font-bold rounded-xl transition-all flex items-center gap-2"
          >
            <FileText className="w-4 h-4" />
            Audit Resume
          </button>
          <button
            onClick={() => navigate('/interview')}
            className="px-4 py-2.5 bg-gradient-to-r from-primary-600 to-cyan-600 hover:from-primary-500 hover:to-cyan-500 text-white text-xs font-bold rounded-xl shadow-md transition-all hover:scale-102 flex items-center gap-2"
          >
            <Users className="w-4 h-4" />
            Mock Interview
          </button>
        </div>
      </div>

      {/* QUICK STATUS METRICS */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
        
        {/* Metric 1 */}
        <GlassCard className="flex flex-col justify-between min-h-[140px] group">
          <div className="flex items-start justify-between">
            <div>
              <span className="text-[10px] font-extrabold text-dark-400 tracking-wider uppercase">Resume Score</span>
              <h3 className="text-3xl font-extrabold font-heading text-dark-50 mt-1">
                {data.stats.resumeScore}%
              </h3>
            </div>
            <div className="p-3 bg-emerald-950/20 text-emerald-400 rounded-xl group-hover:scale-110 transition-transform">
              <FileText className="w-5 h-5" />
            </div>
          </div>
          <div className="w-full bg-dark-900 h-1.5 rounded-full mt-4 overflow-hidden">
            <div 
              className="bg-gradient-to-r from-emerald-500 to-teal-400 h-full rounded-full transition-all duration-1000"
              style={{ width: `${data.stats.resumeScore || 0}%` }}
            />
          </div>
          <span className="text-[10px] text-dark-400 mt-2 block">
            {data.stats.resumeScore > 0 ? 'Resume analyzed successfully' : 'No resume uploaded yet'}
          </span>
        </GlassCard>

        {/* Metric 2 */}
        <GlassCard className="flex flex-col justify-between min-h-[140px] group">
          <div className="flex items-start justify-between">
            <div>
              <span className="text-[10px] font-extrabold text-dark-400 tracking-wider uppercase">Interview Rating</span>
              <h3 className="text-3xl font-extrabold font-heading text-dark-50 mt-1">
                {data.stats.interviewScore ? `${data.stats.interviewScore / 10} / 10` : 'N/A'}
              </h3>
            </div>
            <div className="p-3 bg-indigo-950/20 text-indigo-400 rounded-xl group-hover:scale-110 transition-transform">
              <Users className="w-5 h-5" />
            </div>
          </div>
          <div className="w-full bg-dark-900 h-1.5 rounded-full mt-4 overflow-hidden">
            <div 
              className="bg-gradient-to-r from-indigo-500 to-purple-400 h-full rounded-full transition-all duration-1000"
              style={{ width: `${data.stats.interviewScore || 0}%` }}
            />
          </div>
          <span className="text-[10px] text-dark-400 mt-2 block">
            {data.stats.interviewScore > 0 ? 'Last technical review logged' : 'Start mock session to test'}
          </span>
        </GlassCard>

        {/* Metric 3 */}
        <GlassCard className="flex flex-col justify-between min-h-[140px] group">
          <div className="flex items-start justify-between">
            <div>
              <span className="text-[10px] font-extrabold text-dark-400 tracking-wider uppercase">Roadmap Progress</span>
              <h3 className="text-3xl font-extrabold font-heading text-dark-50 mt-1">
                {data.stats.learningProgress}%
              </h3>
            </div>
            <div className="p-3 bg-cyan-950/20 text-cyan-400 rounded-xl group-hover:scale-110 transition-transform">
              <Map className="w-5 h-5" />
            </div>
          </div>
          <div className="w-full bg-dark-900 h-1.5 rounded-full mt-4 overflow-hidden">
            <div 
              className="bg-gradient-to-r from-cyan-500 to-sky-400 h-full rounded-full transition-all duration-1000"
              style={{ width: `${data.stats.learningProgress || 0}%` }}
            />
          </div>
          <span className="text-[10px] text-dark-400 mt-2 block">
            {data.stats.completedTasks} of {data.stats.totalTasks} daily tasks checked off
          </span>
        </GlassCard>

        {/* Metric 4 */}
        <GlassCard className="flex flex-col justify-between min-h-[140px] group">
          <div className="flex items-start justify-between">
            <div>
              <span className="text-[10px] font-extrabold text-dark-400 tracking-wider uppercase">Milestone Badges</span>
              <h3 className="text-3xl font-extrabold font-heading text-dark-50 mt-1">
                {user?.achievements?.length || 0}
              </h3>
            </div>
            <div className="p-3 bg-yellow-950/20 text-yellow-400 rounded-xl group-hover:scale-110 transition-transform">
              <Award className="w-5 h-5" />
            </div>
          </div>
          <div className="flex items-center gap-1 mt-4 overflow-x-auto py-1">
            {user?.achievements && user.achievements.length > 0 ? (
              user.achievements.slice(0, 3).map((badge, idx) => (
                <span 
                  key={badge.id || idx} 
                  title={`${badge.title}: ${badge.description}`}
                  className="px-2 py-0.5 bg-yellow-500/10 border border-yellow-500/25 rounded-md text-[9px] font-bold text-yellow-400 tracking-wider whitespace-nowrap"
                >
                  🏅 {badge.title}
                </span>
              ))
            ) : (
              <span className="text-[10px] text-dark-400">Unlock your first badge</span>
            )}
          </div>
          <span className="text-[10px] text-dark-400 mt-2 block">
            Total unlocked profile achievements
          </span>
        </GlassCard>

      </div>

      {/* ANALYTICS CHARTS SECTION */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        
        {/* Progress area chart */}
        <GlassCard className="lg:col-span-2 flex flex-col gap-4">
          <div className="flex items-center justify-between border-b border-dark-800/40 pb-3">
            <h3 className="font-bold text-sm text-dark-100 flex items-center gap-2">
              <TrendingUp className="w-4 h-4 text-primary-400" />
              Placement Preparation Timeline
            </h3>
            <span className="text-[10px] text-dark-400 uppercase tracking-widest">Weekly stats</span>
          </div>
          <div className="h-64 w-full text-xs">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={performanceHistory} margin={{ top: 10, right: 10, left: -25, bottom: 0 }}>
                <defs>
                  <linearGradient id="colorScore" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#8b5cf6" stopOpacity={0.2}/>
                    <stop offset="95%" stopColor="#8b5cf6" stopOpacity={0}/>
                  </linearGradient>
                  <linearGradient id="colorInterview" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#06b6d4" stopOpacity={0.2}/>
                    <stop offset="95%" stopColor="#06b6d4" stopOpacity={0}/>
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" opacity={0.3} />
                <XAxis dataKey="name" stroke="#64748b" />
                <YAxis stroke="#64748b" domain={[0, 100]} />
                <Tooltip contentStyle={{ backgroundColor: '#0f172a', borderColor: '#1e293b', borderRadius: '12px' }} />
                <Area type="monotone" dataKey="score" stroke="#8b5cf6" strokeWidth={3} fillOpacity={1} fill="url(#colorScore)" name="ATS Score" />
                <Area type="monotone" dataKey="interview" stroke="#06b6d4" strokeWidth={3} fillOpacity={1} fill="url(#colorInterview)" name="Interview Score" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </GlassCard>

        {/* Skill radar metrics */}
        <GlassCard className="flex flex-col gap-4">
          <div className="flex items-center justify-between border-b border-dark-800/40 pb-3">
            <h3 className="font-bold text-sm text-dark-100 flex items-center gap-2">
              <Sparkles className="w-4 h-4 text-cyan-400" />
              Skill Radar Comparison
            </h3>
          </div>
          <div className="h-64 w-full text-[10px]">
            <ResponsiveContainer width="100%" height="100%">
              <RadarChart cx="50%" cy="50%" r="80%" data={skillsRadar}>
                <PolarGrid stroke="#334155" opacity={0.5} />
                <PolarAngleAxis dataKey="subject" stroke="#94a3b8" />
                <Radar name="Target Standards" dataKey="B" stroke="#06b6d4" fill="#06b6d4" fillOpacity={0.1} />
                <Radar name="Your Level" dataKey="A" stroke="#8b5cf6" fill="#8b5cf6" fillOpacity={0.2} />
              </RadarChart>
            </ResponsiveContainer>
          </div>
        </GlassCard>

      </div>

      {/* DETAILED TASKS & NOTIFICATIONS SPLIT */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        
        {/* Roadmap Tasks checklist panel */}
        <GlassCard className="flex flex-col gap-4">
          <div className="flex items-center justify-between border-b border-dark-800/40 pb-3">
            <h3 className="font-bold text-sm text-dark-100 flex items-center gap-2">
              <CheckSquare className="w-4.5 h-4.5 text-primary-400" />
              Upcoming Learning Tasks
            </h3>
            {data.stats.totalTasks > 0 && (
              <button 
                onClick={() => navigate('/roadmap')}
                className="text-[10px] text-primary-400 hover:text-primary-300 font-bold uppercase tracking-wider flex items-center gap-0.5"
              >
                Full Roadmap
                <ArrowRight className="w-3.5 h-3.5" />
              </button>
            )}
          </div>
          <div className="flex flex-col gap-3 max-h-[300px] overflow-y-auto pr-1">
            {data.upcomingTasks.length === 0 ? (
              <div className="text-center py-10 text-xs text-dark-500">
                No active tasks listed. Please generate a curriculum.
              </div>
            ) : (
              data.upcomingTasks.map((task: any) => (
                <div
                  key={task.id}
                  onClick={() => handleToggleTask(task.id, task.isCompleted)}
                  className={`p-3 rounded-xl border flex items-start gap-3.5 cursor-pointer transition-all hover:bg-dark-900/30 ${
                    task.isCompleted
                      ? 'border-emerald-500/10 bg-emerald-950/5 opacity-50'
                      : 'border-dark-800/60 bg-dark-950/25 hover:border-primary-500/20'
                  }`}
                >
                  <button className={`shrink-0 mt-0.5 ${task.isCompleted ? 'text-emerald-400' : 'text-dark-400'}`}>
                    {task.isCompleted ? <CheckSquare className="w-5 h-5" /> : <Square className="w-5 h-5" />}
                  </button>
                  <div className="flex-1 min-w-0">
                    <h4 className={`text-xs font-bold leading-snug truncate ${task.isCompleted ? 'line-through text-dark-500' : 'text-dark-100'}`}>
                      {task.title}
                    </h4>
                    <span className="text-[9px] font-semibold text-dark-400 block mt-1 tracking-wider uppercase">
                      Module: {task.weekTheme}
                    </span>
                  </div>
                </div>
              ))
            )}
          </div>
        </GlassCard>

        {/* Dashboard Notifications Logs */}
        <GlassCard className="flex flex-col gap-4">
          <div className="flex items-center justify-between border-b border-dark-800/40 pb-3">
            <h3 className="font-bold text-sm text-dark-100 flex items-center gap-2">
              <Calendar className="w-4.5 h-4.5 text-cyan-400" />
              Recent Consultations & Logs
            </h3>
            <button 
              onClick={() => navigate('/chat')}
              className="text-[10px] text-cyan-400 hover:text-cyan-300 font-bold uppercase tracking-wider flex items-center gap-0.5"
            >
              Start Consultation
              <ArrowRight className="w-3.5 h-3.5" />
            </button>
          </div>
          <div className="flex flex-col gap-3 max-h-[300px] overflow-y-auto">
            {data.recentChats.length === 0 ? (
              <div className="text-center py-10 text-xs text-dark-500">
                No recent chat mentoring sessions. Start a new session.
              </div>
            ) : (
              data.recentChats.map((chat: any) => (
                <div
                  key={chat.id}
                  onClick={() => navigate('/chat')}
                  className="p-3.5 rounded-xl border border-dark-800/60 bg-dark-950/25 hover:border-cyan-500/20 hover:bg-dark-900/30 cursor-pointer flex items-center justify-between group transition-all"
                >
                  <div className="flex items-center gap-3">
                    <div className="p-2 bg-cyan-950/20 text-cyan-400 rounded-lg group-hover:scale-105 transition-transform">
                      <MessageSquare className="w-4 h-4" />
                    </div>
                    <div>
                      <h4 className="text-xs font-bold text-dark-100 group-hover:text-cyan-400 transition-colors">
                        {chat.title}
                      </h4>
                      <span className="text-[9px] text-dark-500 block mt-1">
                        Updated {new Date(chat.updatedAt).toLocaleDateString()} at {new Date(chat.updatedAt).toLocaleTimeString()}
                      </span>
                    </div>
                  </div>
                  <ChevronRight className="w-4 h-4 text-dark-500 group-hover:text-cyan-400 transition-colors" />
                </div>
              ))
            )}
          </div>
        </GlassCard>

      </div>

    </div>
  );
};

export default DashboardPage;
