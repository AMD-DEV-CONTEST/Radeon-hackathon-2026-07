import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '../services/api';
import { useAuth } from '../context/AuthContext';
import { 
  FiZap, FiAward, FiCheckCircle, FiGlobe, 
  FiClock, FiMessageSquare, FiBookOpen, FiPlay, FiAlertTriangle, FiBook
} from 'react-icons/fi';
import { Bar, Line } from 'react-chartjs-2';
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  BarElement,
  Title,
  Tooltip,
  Legend,
  Filler
} from 'chart.js';

ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  BarElement,
  Title,
  Tooltip,
  Legend,
  Filler
);

const Dashboard = () => {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    const fetchDashboard = async () => {
      try {
        const res = await api.get('/progress/dashboard');
        setData(res.data);
      } catch (err) {
        console.error("Failed to load dashboard statistics", err);
        setError("Unable to sync dashboard analytics with server.");
      } finally {
        setLoading(false);
      }
    };

    fetchDashboard();
  }, []);

  const getGreeting = () => {
    const hr = new Date().getHours();
    if (hr < 12) return 'Good morning';
    if (hr < 17) return 'Good afternoon';
    return 'Good evening';
  };

  // Generate date array for the last 28 days (4 weeks heatmap)
  const calendarHeatmap = React.useMemo(() => {
    const days = [];
    const today = new Date();
    for (let i = 27; i >= 0; i--) {
      const d = new Date(today);
      d.setDate(today.getDate() - i);
      days.push(d);
    }
    return days;
  }, []);

  // Compute active days set from actual activity log history
  const activeDaysSet = React.useMemo(() => {
    const active = new Set();
    if (data?.recentActivities) {
      data.recentActivities.forEach(act => {
        const dateStr = new Date(act.timestamp).toISOString().split('T')[0];
        active.add(dateStr);
      });
    }
    const todayStr = new Date().toISOString().split('T')[0];
    if (data?.streak > 0) {
      active.add(todayStr);
    }
    return active;
  }, [data]);

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <div className="h-10 w-10 animate-spin rounded-full border-4 border-t-primary-600 border-primary-200"></div>
      </div>
    );
  }

  // Setup Weekly Chart Options & Data
  const weeklyLabels = data?.weeklyActivity ? Object.keys(data.weeklyActivity).map(label => label.substring(0, 3)) : [];
  const weeklyValues = data?.weeklyActivity ? Object.values(data.weeklyActivity) : [];

  const weeklyChartData = {
    labels: weeklyLabels,
    datasets: [
      {
        label: 'Study Hours',
        data: weeklyValues,
        backgroundColor: 'rgba(139, 92, 246, 0.65)',
        borderColor: 'rgb(139, 92, 246)',
        borderRadius: 6,
        borderWidth: 1,
      },
    ],
  };

  const weeklyChartOptions = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { display: false },
      tooltip: {
        backgroundColor: 'rgba(15, 23, 42, 0.9)',
        titleColor: '#fff',
        bodyColor: '#fff',
        padding: 10,
        cornerRadius: 8,
      }
    },
    scales: {
      y: {
        grid: { color: 'rgba(156, 163, 175, 0.1)' },
        ticks: { color: 'rgba(156, 163, 175, 0.8)', font: { size: 10 } },
        beginAtZero: true,
      },
      x: {
        grid: { display: false },
        ticks: { color: 'rgba(156, 163, 175, 0.8)', font: { size: 10 } },
      },
    },
  };

  // Setup Monthly Chart
  const monthlyLabels = data?.monthlyActivity ? Object.keys(data.monthlyActivity) : [];
  const monthlyValues = data?.monthlyActivity ? Object.values(data.monthlyActivity) : [];

  const monthlyChartData = {
    labels: monthlyLabels,
    datasets: [
      {
        fill: true,
        label: 'Hours Spent',
        data: monthlyValues,
        borderColor: 'rgb(99, 102, 241)',
        backgroundColor: 'rgba(99, 102, 241, 0.1)',
        tension: 0.4,
      },
    ],
  };

  const monthlyChartOptions = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { display: false },
    },
    scales: {
      y: {
        grid: { color: 'rgba(156, 163, 175, 0.1)' },
        ticks: { color: 'rgba(156, 163, 175, 0.8)', font: { size: 10 } },
        beginAtZero: true,
      },
      x: {
        grid: { display: false },
        ticks: { color: 'rgba(156, 163, 175, 0.8)', font: { size: 10 } },
      },
    },
  };

  return (
    <div className="space-y-6 text-left">
      
      {/* Upper header with XP level progression */}
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4 border-b border-gray-200/50 dark:border-slate-800/80 pb-4">
        <div>
          <h1 className="text-3xl font-extrabold tracking-tight text-gray-900 dark:text-white bg-gradient-to-r from-primary-600 to-violet-600 bg-clip-text text-transparent dark:from-primary-400 dark:to-violet-400">
            {getGreeting()}, {user?.username}!
          </h1>
          <p className="mt-1 text-sm text-gray-500 dark:text-slate-400 font-medium">
            Let's make progress on your language learning goals today.
          </p>
        </div>

        {data && (
          <div className="w-full md:w-72 space-y-2 shrink-0">
            <div className="flex justify-between items-center text-xs">
              <span className="font-extrabold text-gray-700 dark:text-slate-300">LEVEL {data.level}</span>
              <span className="font-bold text-primary-500">{data.xp} XP</span>
            </div>
            <div className="w-full bg-gray-150 dark:bg-slate-800 h-2.5 rounded-full overflow-hidden border border-gray-200/20">
              <div 
                className="bg-gradient-to-r from-primary-500 to-violet-500 h-2.5 rounded-full transition-all duration-500"
                style={{ width: `${((data.xp % 500) / 500) * 100}%` }}
              ></div>
            </div>
          </div>
        )}
      </div>

      {error && (
        <div className="flex items-center gap-3 rounded-lg bg-yellow-50 dark:bg-yellow-950/20 border border-yellow-200 dark:border-yellow-800/30 p-4 text-sm text-yellow-800 dark:text-yellow-400">
          <FiAlertTriangle className="h-5 w-5 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Metrics Row */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
        
        {/* Streak */}
        <div className="glass-panel p-5 rounded-2xl flex items-center gap-4 bg-white/40 dark:bg-slate-900/30 shadow-md">
          <div className="p-3 bg-orange-500/10 text-orange-500 rounded-xl border border-orange-500/20">
            <FiZap className="h-6 w-6 fill-current" />
          </div>
          <div>
            <p className="text-[10px] uppercase font-bold text-gray-400">Day Streak</p>
            <p className="text-xl font-extrabold text-gray-800 dark:text-white mt-0.5">{data?.streak || 0}</p>
          </div>
        </div>

        {/* Quiz score */}
        <div className="glass-panel p-5 rounded-2xl flex items-center gap-4 bg-white/40 dark:bg-slate-900/30 shadow-md">
          <div className="p-3 bg-yellow-500/10 text-yellow-600 dark:text-yellow-500 rounded-xl border border-yellow-500/20">
            <FiAward className="h-6 w-6" />
          </div>
          <div>
            <p className="text-[10px] uppercase font-bold text-gray-400">Quiz Points</p>
            <p className="text-xl font-extrabold text-gray-800 dark:text-white mt-0.5">{data?.totalQuizScore || 0}</p>
          </div>
        </div>

        {/* Grammar check */}
        <div className="glass-panel p-5 rounded-2xl flex items-center gap-4 bg-white/40 dark:bg-slate-900/30 shadow-md">
          <div className="p-3 bg-green-500/10 text-green-600 dark:text-green-400 rounded-xl border border-green-500/20">
            <FiCheckCircle className="h-6 w-6" />
          </div>
          <div>
            <p className="text-[10px] uppercase font-bold text-gray-400">Grammar Acc.</p>
            <p className="text-xl font-extrabold text-gray-800 dark:text-white mt-0.5">{data?.averageGrammarAccuracy || 100}%</p>
          </div>
        </div>

        {/* Translations count */}
        <div className="glass-panel p-5 rounded-2xl flex items-center gap-4 bg-white/40 dark:bg-slate-900/30 shadow-md">
          <div className="p-3 bg-blue-500/10 text-blue-600 dark:text-blue-400 rounded-xl border border-blue-500/20">
            <FiGlobe className="h-6 w-6" />
          </div>
          <div>
            <p className="text-[10px] uppercase font-bold text-gray-400">Translations</p>
            <p className="text-xl font-extrabold text-gray-800 dark:text-white mt-0.5">{data?.totalTranslations || 0}</p>
          </div>
        </div>

        {/* Learning hours */}
        <div className="glass-panel col-span-2 lg:col-span-1 p-5 rounded-2xl flex items-center gap-4 bg-white/40 dark:bg-slate-900/30 shadow-md">
          <div className="p-3 bg-violet-500/10 text-violet-650 dark:text-violet-400 rounded-xl border border-violet-500/20">
            <FiClock className="h-6 w-6" />
          </div>
          <div>
            <p className="text-[10px] uppercase font-bold text-gray-400">Study Hours</p>
            <p className="text-xl font-extrabold text-gray-800 dark:text-white mt-0.5">{data?.totalHours?.toFixed(1) || 0.0}h</p>
          </div>
        </div>
      </div>

      {/* Main Grid: Charts & Heatmap */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        
        {/* Weekly Chart */}
        <div className="lg:col-span-2 glass-panel p-6 rounded-2xl space-y-4 bg-white/40 dark:bg-slate-900/30 shadow-xl">
          <h2 className="text-sm font-bold text-gray-850 dark:text-white uppercase tracking-wider">Weekly Learning intensity</h2>
          <div className="h-64 relative">
            <Bar data={weeklyChartData} options={weeklyChartOptions} />
          </div>
        </div>

        {/* Calendar Heatmap */}
        <div className="glass-panel p-6 rounded-2xl flex flex-col justify-between bg-white/40 dark:bg-slate-900/30 shadow-xl">
          <div>
            <h2 className="text-sm font-bold text-gray-850 dark:text-white uppercase tracking-wider mb-2">Study Heatmap</h2>
            <p className="text-[10px] text-gray-400 mb-4">Your daily study consistency over the last 28 days.</p>
            
            <div className="grid grid-cols-7 gap-2.5 items-center justify-center p-4 rounded-xl bg-white/30 dark:bg-slate-950/20 border border-gray-200/50 dark:border-slate-850">
              {calendarHeatmap.map((date, i) => {
                const dateStr = date.toISOString().split('T')[0];
                const isActive = activeDaysSet.has(dateStr);
                return (
                  <div
                    key={i}
                    title={`${date.toLocaleDateString()}: ${isActive ? 'Active Study Session' : 'No activity logged'}`}
                    className={`h-7 w-7 rounded-lg transition-all duration-200 cursor-help ${
                      isActive 
                        ? 'bg-gradient-to-tr from-primary-600 to-violet-550 shadow-md shadow-primary-500/20 scale-105' 
                        : 'bg-gray-200 dark:bg-slate-800 hover:bg-gray-300 dark:hover:bg-slate-700'
                    }`}
                  ></div>
                );
              })}
            </div>
            
            <div className="flex justify-between items-center text-[9px] text-gray-400 font-extrabold uppercase mt-4 px-1">
              <span>4 Weeks Ago</span>
              <span>Today</span>
            </div>
          </div>
        </div>

        {/* Monthly Trend Chart */}
        <div className="lg:col-span-2 glass-panel p-6 rounded-2xl space-y-4 bg-white/40 dark:bg-slate-900/30 shadow-xl">
          <h2 className="text-sm font-bold text-gray-850 dark:text-white uppercase tracking-wider font-semibold">Monthly Progress curve</h2>
          <div className="h-60 relative">
            <Line data={monthlyChartData} options={monthlyChartOptions} />
          </div>
        </div>

        {/* Quick Access learning navigation */}
        <div className="glass-panel p-6 rounded-2xl flex flex-col justify-between bg-white/40 dark:bg-slate-900/30 shadow-xl">
          <h2 className="text-sm font-bold text-gray-850 dark:text-white uppercase tracking-wider mb-4">Quick Workspaces</h2>
          <div className="space-y-3.5 flex-1">
            <button
              onClick={() => navigate('/chat')}
              className="w-full flex items-center justify-between p-3 rounded-xl bg-primary-500/5 dark:bg-primary-950/20 hover:bg-primary-500/10 dark:hover:bg-primary-950/35 border border-primary-500/10 group transition"
            >
              <div className="flex items-center gap-3">
                <FiMessageSquare className="h-5 w-5 text-primary-600 dark:text-primary-400" />
                <div className="text-left">
                  <p className="text-xs font-bold text-gray-850 dark:text-white">AI Tutor Chat</p>
                  <p className="text-[10px] text-gray-400">Practice conversational fluency</p>
                </div>
              </div>
              <FiPlay className="h-3.5 w-3.5 text-primary-600 opacity-0 group-hover:opacity-100 transition" />
            </button>

            <button
              onClick={() => navigate('/grammar')}
              className="w-full flex items-center justify-between p-3 rounded-xl bg-green-500/5 dark:bg-green-950/20 hover:bg-green-500/10 dark:hover:bg-green-950/35 border border-green-500/10 group transition"
            >
              <div className="flex items-center gap-3">
                <FiCheckCircle className="h-5 w-5 text-green-600 dark:text-green-400" />
                <div className="text-left">
                  <p className="text-xs font-bold text-gray-850 dark:text-white">Grammar Audit</p>
                  <p className="text-[10px] text-gray-400">Verify writing structure</p>
                </div>
              </div>
              <FiPlay className="h-3.5 w-3.5 text-green-600 opacity-0 group-hover:opacity-100 transition" />
            </button>

            <button
              onClick={() => navigate('/quiz')}
              className="w-full flex items-center justify-between p-3 rounded-xl bg-yellow-500/5 dark:bg-yellow-950/20 hover:bg-yellow-500/10 dark:hover:bg-yellow-950/35 border border-yellow-500/10 group transition"
            >
              <div className="flex items-center gap-3">
                <FiBookOpen className="h-5 w-5 text-yellow-600 dark:text-yellow-500" />
                <div className="text-left">
                  <p className="text-xs font-bold text-gray-850 dark:text-white">Test Quizzes</p>
                  <p className="text-[10px] text-gray-400">Challenge vocabulary retention</p>
                </div>
              </div>
              <FiPlay className="h-3.5 w-3.5 text-yellow-600 opacity-0 group-hover:opacity-100 transition" />
            </button>
          </div>
        </div>

      </div>
    </div>
  );
};

export default Dashboard;
