import React, { useState, useEffect } from 'react';
import api from '../services/api';
import { 
  FiAward, FiZap, FiClock, FiCheckCircle, FiGlobe, 
  FiBookOpen, FiActivity, FiShield, FiFileText, FiDownload, FiInfo 
} from 'react-icons/fi';
import { Bar } from 'react-chartjs-2';
import { useAuth } from '../context/AuthContext';

const Progress = () => {
  const { user } = useAuth();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [certData, setCertData] = useState(null);
  const [loadingCert, setLoadingCert] = useState(false);
  const [showCertModal, setShowCertModal] = useState(false);

  useEffect(() => {
    fetchProgressDetails();
  }, []);

  const fetchProgressDetails = async () => {
    try {
      const res = await api.get('/progress');
      setData(res.data);
    } catch (err) {
      console.error("Failed to load progress details", err);
    } finally {
      setLoading(false);
    }
  };

  const handleClaimCertificate = async () => {
    setLoadingCert(true);
    try {
      const res = await api.get('/progress/certificate/pdf', {
        responseType: 'blob'
      });
      const blob = new Blob([res.data], { type: 'application/pdf' });
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.setAttribute('download', `${user?.username || 'learner'}_linguabot_certificate.pdf`);
      document.body.appendChild(link);
      link.click();
      link.remove();
    } catch (err) {
      console.error("Failed to download certificate", err);
      alert("Failed to generate and download your PDF certificate.");
    } finally {
      setLoadingCert(false);
    }
  };

  const printCertificate = () => {
    handleClaimCertificate();
  };

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <div className="h-10 w-10 animate-spin rounded-full border-4 border-t-primary-600 border-primary-200"></div>
      </div>
    );
  }

  const progress = data?.progress;
  const achievements = data?.achievements || [];
  const leaderboard = data?.leaderboard || [];

  // Setup Weekly Chart Data
  const weeklyLabels = progress?.weeklyActivity ? Object.keys(progress.weeklyActivity).map(label => label.substring(0, 3)) : [];
  const weeklyValues = progress?.weeklyActivity ? Object.values(progress.weeklyActivity) : [];

  const chartData = {
    labels: weeklyLabels,
    datasets: [
      {
        label: 'Study Hours',
        data: weeklyValues,
        backgroundColor: 'rgba(139, 92, 246, 0.65)',
        borderColor: 'rgb(139, 92, 246)',
        borderRadius: 6,
      },
    ],
  };

  const chartOptions = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { display: false }
    },
    scales: {
      y: { grid: { color: 'rgba(156, 163, 175, 0.1)' } },
      x: { grid: { display: false } }
    }
  };

  const achievementBadges = [
    { title: "Zap", label: "Dedicated Learner", req: "3+ streak days" },
    { title: "Clock", label: "Language Scholar", req: "5+ hours study time" },
    { title: "Globe", label: "Global Translator", req: "10+ translations" },
    { title: "Award", label: "Quiz Master", req: "3+ quizzes completed" }
  ];

  const getBadgeIcon = (iconName, active) => {
    const classes = `h-8 w-8 ${active ? 'text-primary-600 dark:text-primary-400' : 'text-gray-300 dark:text-slate-700'}`;
    switch (iconName) {
      case 'Zap': return <FiZap className={classes} />;
      case 'Clock': return <FiClock className={classes} />;
      case 'Globe': return <FiGlobe className={classes} />;
      case 'Award': return <FiAward className={classes} />;
      default: return <FiAward className={classes} />;
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-extrabold tracking-tight text-gray-900 dark:text-white">Progress Analytics</h1>
        <p className="mt-1 text-sm text-gray-500 dark:text-slate-400">
          Track study accomplishments, rank placements, and claim certificates.
        </p>
      </div>

      {/* Main grids split */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        
        {/* Left Side: Stats and Achievements (2 cols) */}
        <div className="lg:col-span-2 space-y-6">
          
          {/* Certificate Claim card */}
          <div className="glass-panel p-6 rounded-2xl shadow-sm text-left flex flex-col md:flex-row justify-between items-center gap-4 bg-gradient-to-r from-primary-500/10 to-violet-500/10 border-primary-500/20">
            <div className="space-y-1">
              <h3 className="text-base font-extrabold text-gray-900 dark:text-white flex items-center gap-2">
                <FiAward className="text-primary-600" /> Completion Certificate
              </h3>
              <p className="text-xs text-gray-500 dark:text-slate-400">
                Unlock your official diploma by completing at least 2 study hours and passing 2 quizzes.
              </p>
            </div>
            
            <button
              onClick={handleClaimCertificate}
              disabled={loadingCert || !data?.certificateEligible}
              className="shrink-0 bg-primary-600 hover:bg-primary-500 disabled:bg-gray-200 dark:disabled:bg-slate-800 disabled:text-gray-400 font-bold py-2.5 px-5 rounded-xl text-xs text-white shadow-md active:scale-95 transition"
            >
              {loadingCert ? 'Generating...' : data?.certificateEligible ? 'Claim Certificate' : 'Locked'}
            </button>
          </div>

          {/* Activity graphs */}
          <div className="glass-panel p-6 rounded-2xl shadow-sm space-y-4 text-left">
            <h3 className="text-base font-bold text-gray-800 dark:text-white">Weekly Performance Trends</h3>
            <div className="h-64 relative">
              <Bar data={chartData} options={chartOptions} />
            </div>
          </div>

          {/* Achievements shelf */}
          <div className="glass-panel p-6 rounded-2xl shadow-sm space-y-4 text-left">
            <h3 className="text-base font-bold text-gray-800 dark:text-white">Accomplishments Shelf</h3>
            
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              {achievementBadges.map((badge) => {
                const unlocked = achievements.some(a => a.title === badge.label);
                return (
                  <div
                    key={badge.label}
                    className={`p-4 rounded-xl border text-center flex flex-col items-center gap-3 transition ${
                      unlocked
                        ? 'bg-white dark:bg-slate-900 border-primary-200 dark:border-primary-900/30 shadow-sm'
                        : 'bg-gray-50/50 dark:bg-slate-950/20 border-gray-150 dark:border-slate-850 opacity-60'
                    }`}
                  >
                    <div className={`p-3 rounded-full ${unlocked ? 'bg-primary-50 dark:bg-primary-950/40' : 'bg-gray-100 dark:bg-slate-800'}`}>
                      {getBadgeIcon(badge.title, unlocked)}
                    </div>
                    <div>
                      <p className="text-xs font-extrabold text-gray-800 dark:text-slate-200">{badge.label}</p>
                      <p className="text-[9px] text-gray-400 mt-1">Req: {badge.req}</p>
                      <span className={`inline-block mt-2 text-[8px] font-bold px-1.5 py-0.5 rounded ${
                        unlocked ? 'bg-green-50 text-green-700' : 'bg-gray-100 text-gray-400'
                      }`}>
                        {unlocked ? 'Unlocked' : 'Locked'}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>

        {/* Right Side: Leaderboard (1 col) */}
        <div className="lg:col-span-1 space-y-6">
          <div className="glass-panel p-6 rounded-2xl shadow-sm flex flex-col h-[520px] text-left">
            <h3 className="text-base font-bold text-gray-900 dark:text-white mb-4 flex items-center gap-2 border-b border-gray-100 dark:border-slate-800 pb-3">
              <FiActivity className="text-primary-600" /> Platform Leaderboard
            </h3>

            <div className="flex-1 overflow-y-auto divide-y divide-gray-100 dark:divide-slate-800/60 pr-1">
              {leaderboard.map((item, i) => {
                const isCurrentUser = item.username === user?.username;
                return (
                  <div
                    key={item.userId}
                    className={`p-3 flex items-center justify-between rounded-lg transition my-1 ${
                      isCurrentUser 
                        ? 'bg-primary-50/40 dark:bg-primary-950/15 border border-primary-500/20 font-bold' 
                        : 'hover:bg-gray-50/50 dark:hover:bg-slate-900/20'
                    }`}
                  >
                    <div className="flex items-center gap-3 overflow-hidden">
                      <span className={`h-6 w-6 rounded-full flex items-center justify-center text-xs font-black shrink-0 ${
                        item.rank === 1 ? 'bg-yellow-100 text-yellow-800' :
                        item.rank === 2 ? 'bg-gray-100 text-gray-800' :
                        item.rank === 3 ? 'bg-orange-100 text-orange-850' : 'bg-gray-50 text-gray-500 dark:bg-slate-800'
                      }`}>
                        {item.rank}
                      </span>
                      <div className="text-left">
                        <p className="text-xs text-gray-800 dark:text-slate-200 truncate max-w-[120px]">
                          {item.username}
                        </p>
                        <p className="text-[9px] text-gray-400">{item.totalHours.toFixed(1)} study hours</p>
                      </div>
                    </div>

                    <div className="flex items-center gap-2 shrink-0">
                      <span className="flex items-center gap-0.5 text-[10px] font-bold text-orange-500">
                        <FiZap className="shrink-0" /> {item.streak}
                      </span>
                      <span className="text-[10px] font-extrabold text-primary-600 dark:text-primary-400 bg-primary-50 dark:bg-primary-950/30 px-2 py-0.5 rounded-full">
                        {item.totalQuizScore} pts
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>

      </div>

      {/* Certificate Modal */}
      {showCertModal && certData && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-md print:bg-white print:p-0">
          <div className="relative w-full max-w-2xl bg-white dark:bg-slate-950 border border-gray-200 dark:border-slate-800 shadow-2xl p-8 rounded-3xl text-center space-y-6 print:border-0 print:shadow-none print:w-screen print:h-screen print:flex print:flex-col print:justify-center">
            
            {/* Modal close handles */}
            <button
              onClick={() => setShowCertModal(false)}
              className="absolute top-4 right-4 p-2 rounded-lg text-gray-500 hover:bg-gray-100 dark:hover:bg-slate-800 print:hidden"
            >
              Close
            </button>

            {/* Certificate Outer Border Frame */}
            <div className="border-8 border-double border-primary-600 p-8 space-y-6 rounded-2xl relative bg-slate-50/50 dark:bg-slate-950">
              <div className="absolute top-4 left-4 text-xs font-mono text-gray-300 dark:text-slate-800 select-none">LINGUABOT</div>
              
              <div className="space-y-2">
                <FiAward className="mx-auto h-16 w-16 text-primary-600" />
                <h2 className="text-xl font-bold tracking-widest text-primary-600 uppercase">Certificate of Completion</h2>
                <p className="text-xs text-gray-400 uppercase tracking-widest">This is proudly presented to</p>
              </div>

              <div className="py-2 border-b-2 border-primary-600 max-w-sm mx-auto">
                <h3 className="text-2xl font-black text-gray-900 dark:text-white capitalize">{certData.recipientName}</h3>
              </div>

              <p className="text-sm text-gray-500 dark:text-slate-400 max-w-md mx-auto leading-relaxed">
                for demonstrating dedication and outstanding academic achievement in completing the comprehensive
                <strong className="block text-gray-800 dark:text-white mt-1">{certData.courseName}</strong>
              </p>

              <div className="grid grid-cols-2 gap-4 max-w-md mx-auto pt-6 border-t border-gray-200 dark:border-slate-850">
                <div className="text-left">
                  <p className="text-[9px] uppercase font-bold text-gray-400">Issue Date</p>
                  <p className="text-xs font-bold text-gray-800 dark:text-white">
                    {new Date(certData.issueDate).toLocaleDateString()}
                  </p>
                </div>
                <div className="text-right">
                  <p className="text-[9px] uppercase font-bold text-gray-400">Verification ID</p>
                  <p className="text-xs font-mono text-primary-600 font-extrabold">{certData.verificationCode}</p>
                </div>
              </div>
            </div>

            <div className="flex gap-3 justify-center pt-2 print:hidden">
              <button
                onClick={printCertificate}
                className="flex items-center gap-2 bg-primary-600 hover:bg-primary-500 text-white font-bold py-2.5 px-6 rounded-xl text-sm transition"
              >
                <FiDownload /> Print / Save PDF
              </button>
            </div>

          </div>
        </div>
      )}
    </div>
  );
};

export default Progress;
