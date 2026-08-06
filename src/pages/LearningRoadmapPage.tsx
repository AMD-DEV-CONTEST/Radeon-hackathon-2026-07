import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { 
  Map, CheckCircle, Square, CheckSquare, Calendar, Award, 
  ArrowRight, Loader2, ClipboardList, Target, Compass
} from 'lucide-react';
import { useNotification } from '../context/NotificationContext';
import { useAuth } from '../context/AuthContext';
import EmptyState from '../components/EmptyState';
import GlassCard from '../components/GlassCard';
import axios from 'axios';

export const LearningRoadmapPage: React.FC = () => {
  const navigate = useNavigate();
  const { user } = useAuth();
  const { showToast } = useNotification();
  
  const [loading, setLoading] = useState(true);
  const [roadmap, setRoadmap] = useState<any>(null);
  const [activeWeek, setActiveWeek] = useState<number>(1);

  const fetchRoadmap = async () => {
    try {
      const response = await axios.get('/api/roadmap/latest');
      setRoadmap(response.data);
    } catch (err) {
      console.log('[Roadmap] No active roadmap in database');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchRoadmap();
  }, []);

  const handleToggleTask = async (taskId: string, currentStatus: boolean) => {
    try {
      await axios.put('/api/roadmap/toggle-task', { taskId, isCompleted: !currentStatus });
      showToast(currentStatus ? 'Task marked incomplete' : 'Task completed! Moving closer to job readiness.', 'success');
      fetchRoadmap(); // Refresh progress stats
    } catch (err) {
      showToast('Could not save task progress state', 'error');
    }
  };

  if (loading) {
    return (
      <div className="h-[80vh] flex flex-col items-center justify-center gap-4">
        <Loader2 className="w-10 h-10 animate-spin text-primary-500" />
        <p className="text-sm text-dark-400">Loading your learning timeline...</p>
      </div>
    );
  }

  if (!roadmap) {
    return (
      <div className="py-12">
        <EmptyState
          title="No Learning Roadmap Found"
          description="Identify your technology gaps by running a Skill Gap analysis first. We will then design a custom 4-week study roadmap curriculum."
          actionLabel="Analyze Skill Gaps"
          onActionClick={() => navigate('/skill-gap')}
          icon={Map}
        />
      </div>
    );
  }

  // Calculate metrics
  let totalTasks = 0;
  let completedTasks = 0;
  roadmap.weeklyPlan.forEach((week: any) => {
    week.tasks.forEach((task: any) => {
      totalTasks++;
      if (task.isCompleted) {
        completedTasks++;
      }
    });
  });
  const progressRate = totalTasks > 0 ? Math.round((completedTasks / totalTasks) * 100) : 0;

  const currentWeekData = roadmap.weeklyPlan.find((w: any) => w.weekNumber === activeWeek) || roadmap.weeklyPlan[0];

  return (
    <div className="flex flex-col gap-8">
      
      {/* Page Header */}
      <div className="border-b border-dark-800/40 pb-6 flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h2 className="text-3xl font-extrabold font-heading text-dark-50 tracking-tight flex items-center gap-2">
            <Compass className="w-8 h-8 text-primary-400 animate-spin-slow" />
            Learning Roadmap
          </h2>
          <p className="text-sm text-dark-400 mt-1">
            Weekly themes, checklist targets, and study progress metrics for <strong className="text-primary-400">{roadmap.dreamJob}</strong>.
          </p>
        </div>
        <span className="text-xs px-3 py-1 bg-dark-900 border border-dark-800 text-dark-300 rounded-xl font-semibold">
          Plan length: {roadmap.weeklyPlan.length} Weeks
        </span>
      </div>

      {/* OVERALL PROGRESS PANEL CARD */}
      <GlassCard className="p-8 bg-gradient-to-br from-dark-950/60 to-cyan-950/10 flex flex-col md:flex-row items-center justify-between gap-6 border-l-4 border-l-cyan-500">
        <div className="flex-1 w-full">
          <div className="flex justify-between items-center mb-2.5">
            <span className="text-xs font-bold text-dark-300">Curriculum Completion Progress</span>
            <span className="text-sm font-black text-cyan-400">{progressRate}%</span>
          </div>
          <div className="w-full bg-dark-900 h-3 rounded-full overflow-hidden shadow-inner">
            <div 
              className="bg-gradient-to-r from-cyan-500 via-primary-500 to-purple-500 h-full rounded-full transition-all duration-1000 shadow-lg shadow-primary-500/10"
              style={{ width: `${progressRate}%` }}
            />
          </div>
          <p className="text-[10px] text-dark-400 mt-2">
            You have checked off {completedTasks} out of {totalTasks} daily study tasks.
          </p>
        </div>

        {progressRate === 100 && (
          <div className="flex items-center gap-2.5 p-3 bg-yellow-500/10 border border-yellow-500/25 rounded-xl text-yellow-400 animate-pulse-glow">
            <Award className="w-5 h-5 shrink-0" />
            <div className="text-xs font-bold">
              <span>Roadmap Completed! Badge Unlocked</span>
            </div>
          </div>
        )}
      </GlassCard>

      {/* ROADMAP TIMELINE GRID */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-start">
        
        {/* Navigation timelines columns (Left) */}
        <div className="lg:col-span-4 flex flex-col gap-3.5">
          <h3 className="font-heading font-bold text-xs uppercase tracking-wider text-dark-400 mb-1 pl-1">
            Weekly Modules Sequence
          </h3>

          {roadmap.weeklyPlan.map((week: any) => {
            const weekTasksCount = week.tasks.length;
            const weekCompletedCount = week.tasks.filter((t: any) => t.isCompleted).length;
            const weekProgress = weekTasksCount > 0 ? Math.round((weekCompletedCount / weekTasksCount) * 100) : 0;
            const isActive = activeWeek === week.weekNumber;

            return (
              <div
                key={week.weekNumber}
                onClick={() => setActiveWeek(week.weekNumber)}
                className={`p-4.5 rounded-2xl border cursor-pointer transition-all flex flex-col gap-2.5 ${
                  isActive
                    ? 'border-primary-500 bg-primary-950/20 shadow-lg shadow-primary-500/5'
                    : 'border-dark-800 bg-dark-950/25 hover:border-dark-700/60 hover:bg-dark-900/10'
                }`}
              >
                <div className="flex justify-between items-start">
                  <div>
                    <span className={`text-[10px] font-bold uppercase tracking-widest ${isActive ? 'text-primary-400' : 'text-dark-400'}`}>
                      Week {week.weekNumber}
                    </span>
                    <h4 className={`text-xs font-bold mt-0.5 leading-snug ${isActive ? 'text-dark-100' : 'text-dark-300'}`}>
                      {week.theme}
                    </h4>
                  </div>
                  <span className={`px-2 py-0.5 rounded text-[9px] font-bold ${
                    weekProgress === 100
                      ? 'bg-emerald-950/40 border border-emerald-500/20 text-emerald-400'
                      : 'bg-dark-900 border border-dark-800 text-dark-400'
                  }`}>
                    {weekProgress}%
                  </span>
                </div>
                <div className="w-full bg-dark-900 h-1 rounded-full overflow-hidden">
                  <div 
                    className="bg-primary-500 h-full rounded-full transition-all"
                    style={{ width: `${weekProgress}%` }}
                  />
                </div>
              </div>
            );
          })}
        </div>

        {/* Detailed week goals & checklist (Right) */}
        <div className="lg:col-span-8 flex flex-col gap-6 animate-slide-up" key={activeWeek}>
          <GlassCard className="flex flex-col gap-5">
            <div className="flex items-center justify-between border-b border-dark-800/40 pb-3">
              <span className="text-xs font-bold text-cyan-400 uppercase tracking-widest">
                Module Details – Week {currentWeekData.weekNumber}
              </span>
              <span className="text-[10px] text-dark-400 font-semibold">{currentWeekData.theme}</span>
            </div>

            {/* Week Goals section */}
            <div className="flex flex-col gap-3 p-4 rounded-xl bg-dark-950/30 border border-dark-900/50">
              <span className="text-[10px] font-bold text-primary-400 uppercase tracking-wider flex items-center gap-1.5">
                <Target className="w-4 h-4" /> Key Study Goals
              </span>
              <div className="flex flex-col gap-2 mt-1">
                {currentWeekData.goals.map((goal: string, idx: number) => (
                  <div key={idx} className="flex gap-2 items-start text-xs text-dark-200">
                    <span className="w-1.5 h-1.5 rounded-full bg-primary-400 mt-1.5 shrink-0" />
                    <span>{goal}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Week Tasks checklist */}
            <div className="flex flex-col gap-3">
              <span className="text-[10px] font-bold text-dark-400 uppercase tracking-wider pl-1">
                Daily Study Checklist
              </span>
              <div className="flex flex-col gap-3">
                {currentWeekData.tasks.map((task: any) => (
                  <div
                    key={task.id}
                    onClick={() => handleToggleTask(task.id, task.isCompleted)}
                    className={`p-4 rounded-xl border flex items-start gap-4 cursor-pointer transition-all hover:bg-dark-900/30 ${
                      task.isCompleted
                        ? 'border-emerald-500/10 bg-emerald-950/5 opacity-55'
                        : 'border-dark-800/60 bg-dark-950/20 hover:border-primary-500/20'
                    }`}
                  >
                    <button className={`shrink-0 mt-0.5 ${task.isCompleted ? 'text-emerald-400' : 'text-dark-400'}`}>
                      {task.isCompleted ? <CheckSquare className="w-5 h-5" /> : <Square className="w-5 h-5" />}
                    </button>
                    <p className={`text-xs font-bold leading-relaxed ${task.isCompleted ? 'line-through text-dark-500' : 'text-dark-100'}`}>
                      {task.title}
                    </p>
                  </div>
                ))}
              </div>
            </div>

          </GlassCard>
        </div>

      </div>

    </div>
  );
};

export default LearningRoadmapPage;
