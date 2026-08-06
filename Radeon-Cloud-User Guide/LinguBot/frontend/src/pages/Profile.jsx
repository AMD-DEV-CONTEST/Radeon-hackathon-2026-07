import React, { useEffect, useState } from 'react';
import { useAuth } from '../context/AuthContext';
import api from '../services/api';
import { 
  FiUser, FiMail, FiCalendar, FiShield, FiCheckCircle, 
  FiAlertTriangle, FiZap, FiAward, FiBookOpen, FiClock, FiDownload, FiStar
} from 'react-icons/fi';

const Profile = () => {
  const { user } = useAuth();
  const [profileData, setProfileData] = useState(null);
  const [progressDetails, setProgressDetails] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [downloadingCert, setDownloadingCert] = useState(false);

  useEffect(() => {
    fetchProfileAndProgress();
  }, []);

  const fetchProfileAndProgress = async () => {
    try {
      const [profileRes, progressRes] = await Promise.all([
        api.get('/auth/profile'),
        api.get('/progress')
      ]);
      setProfileData(profileRes.data);
      setProgressDetails(progressRes.data);
    } catch (err) {
      console.error("Failed to load user profile or progress", err);
      setError("Could not load full profile and learning statistics.");
    } finally {
      setLoading(false);
    }
  };

  const handleDownloadCertificate = async () => {
    setDownloadingCert(true);
    try {
      const res = await api.get('/progress/certificate/pdf', {
        responseType: 'blob'
      });
      const blob = new Blob([res.data], { type: 'application/pdf' });
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.setAttribute('download', `${userToShow?.username}_linguabot_certificate.pdf`);
      document.body.appendChild(link);
      link.click();
      link.remove();
    } catch (err) {
      console.error("Failed to download certificate", err);
      alert("Failed to download your PDF certificate. Please try again.");
    } finally {
      setDownloadingCert(false);
    }
  };

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <div className="h-10 w-10 animate-spin rounded-full border-4 border-t-primary-600 border-primary-200"></div>
      </div>
    );
  }

  const userToShow = profileData || user;
  const progress = progressDetails?.progress;
  const achievements = progressDetails?.achievements || [];
  const badges = progressDetails?.badges || [];
  const isCertificateEligible = progressDetails?.certificateEligible || false;

  // Render a visual representation of each badge tier
  const badgeColors = {
    'Bronze': 'from-amber-700 to-orange-500 shadow-amber-500/20 ring-amber-500/30',
    'Silver': 'from-slate-400 to-slate-200 shadow-slate-400/20 ring-slate-400/30',
    'Gold': 'from-yellow-500 to-amber-400 shadow-yellow-400/20 ring-yellow-400/30',
    'Diamond': 'from-cyan-500 to-sky-400 shadow-cyan-400/20 ring-cyan-400/30',
    'Legend': 'from-fuchsia-600 to-violet-500 shadow-fuchsia-500/20 ring-fuchsia-500/30'
  };

  return (
    <div className="space-y-6 text-left">
      <div>
        <h1 className="text-3xl font-extrabold tracking-tight text-gray-900 dark:text-white bg-gradient-to-r from-primary-600 to-violet-600 bg-clip-text text-transparent dark:from-primary-400 dark:to-violet-400">
          User Profile
        </h1>
        <p className="mt-1 text-sm text-gray-500 dark:text-slate-400">
          Track your course completion status, level points, unlocked credentials, and earned badges.
        </p>
      </div>

      {error && (
        <div className="flex items-center gap-3 rounded-lg bg-red-50 dark:bg-red-950/20 border border-red-200 dark:border-red-800/30 p-4 text-sm text-red-800 dark:text-red-400">
          <FiAlertTriangle className="h-5 w-5 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Main Profile Grid */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        
        {/* Left Side: Avatar & Core Info */}
        <div className="lg:col-span-1 space-y-6">
          <div className="glass-panel p-6 rounded-2xl shadow-xl text-center flex flex-col items-center bg-white/40 dark:bg-slate-900/30 relative overflow-hidden">
            <div className="absolute top-0 inset-x-0 h-1.5 bg-gradient-to-r from-primary-500 to-violet-500"></div>

            <div className="h-24 w-24 rounded-3xl bg-gradient-to-tr from-primary-600 to-violet-500 text-white flex items-center justify-center text-4xl font-extrabold shadow-lg shadow-primary-500/20 ring-4 ring-white dark:ring-slate-950 mt-2">
              {userToShow?.username?.charAt(0).toUpperCase()}
            </div>
            
            <h2 className="mt-4 text-xl font-bold text-gray-900 dark:text-white">{userToShow?.username}</h2>
            <p className="text-xs text-gray-400 mt-1">{userToShow?.email}</p>

            <div className="mt-5 flex flex-wrap justify-center gap-2">
              {userToShow?.roles?.map((role) => (
                <span
                  key={role}
                  className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-[10px] font-bold bg-primary-500/5 dark:bg-primary-950/30 text-primary-600 dark:text-primary-400 border border-primary-500/10"
                >
                  <FiShield className="h-3 w-3" />
                  {role.replace('ROLE_', '')}
                </span>
              ))}
            </div>

            {/* Level Progress Circle */}
            {progress && (
              <div className="w-full mt-6 pt-6 border-t border-gray-100 dark:border-slate-800 space-y-3">
                <div className="flex justify-between items-center text-xs">
                  <span className="font-extrabold text-gray-700 dark:text-slate-350 uppercase">Level {progress.level}</span>
                  <span className="font-bold text-primary-500">{progress.xp % 500} / 500 XP</span>
                </div>
                <div className="w-full bg-gray-100 dark:bg-slate-800 h-3 rounded-full overflow-hidden border border-gray-200/30 dark:border-slate-850">
                  <div 
                    className="bg-gradient-to-r from-primary-500 to-violet-500 h-3 rounded-full"
                    style={{ width: `${((progress.xp % 500) / 500) * 100}%` }}
                  ></div>
                </div>
                <p className="text-[10px] text-gray-400 font-bold uppercase tracking-wider">Total Experience Points: {progress.xp} XP</p>
              </div>
            )}
          </div>

          {/* Streaks Widget */}
          {progress && (
            <div className="glass-panel p-5 rounded-2xl shadow-xl bg-white/40 dark:bg-slate-900/30 grid grid-cols-2 gap-4 border-l-4 border-l-orange-500">
              <div className="text-center">
                <p className="text-[10px] text-gray-400 font-extrabold uppercase tracking-wider">Current Streak</p>
                <p className="text-2xl font-black text-orange-500 mt-1 flex items-center justify-center gap-1">
                  <FiZap className="h-5 w-5 fill-current" /> {progress.streak} days
                </p>
              </div>
              <div className="text-center border-l border-gray-100 dark:border-slate-800">
                <p className="text-[10px] text-gray-400 font-extrabold uppercase tracking-wider">Longest Streak</p>
                <p className="text-2xl font-black text-gray-800 dark:text-white mt-1">
                  {progress.longestStreak} days
                </p>
              </div>
            </div>
          )}
        </div>

        {/* Right Side: Badges Shelf, Achievements, and Certificate */}
        <div className="lg:col-span-2 space-y-6">
          
          {/* Certificate Claim Area */}
          {isCertificateEligible && (
            <div className="glass-panel p-6 rounded-2xl shadow-xl bg-gradient-to-r from-primary-600/10 via-violet-600/10 to-indigo-600/10 border border-primary-500/20 flex flex-col md:flex-row justify-between items-center gap-4">
              <div className="text-left space-y-1">
                <h4 className="text-base font-extrabold text-primary-900 dark:text-primary-400 flex items-center gap-2">
                  <FiAward className="h-5 w-5 animate-bounce-short text-amber-500" /> Complete Diploma Available!
                </h4>
                <p className="text-xs text-gray-600 dark:text-slate-350">
                  Congratulations! You have qualified for graduation. Click to generate and print your landscape A4 Completion Certificate.
                </p>
              </div>
              <button
                onClick={handleDownloadCertificate}
                disabled={downloadingCert}
                className="w-full md:w-auto shrink-0 flex items-center justify-center gap-2 bg-gradient-to-r from-primary-600 to-violet-600 hover:from-primary-500 hover:to-violet-500 text-white font-bold py-2.5 px-5 rounded-xl text-xs shadow-lg shadow-primary-500/15"
              >
                {downloadingCert ? 'Generating...' : <><FiDownload /> Download PDF Certificate</>}
              </button>
            </div>
          )}

          {/* Badges Shelf */}
          <div className="glass-panel p-6 rounded-2xl shadow-xl bg-white/40 dark:bg-slate-900/30 space-y-4">
            <h3 className="text-sm font-extrabold text-gray-900 dark:text-white border-b border-gray-150 dark:border-slate-805 pb-3">
              Badges Cabinet
            </h3>
            
            {badges.length === 0 ? (
              <p className="text-xs text-gray-400 text-center py-6 font-medium">No badges unlocked yet. Reach 100+ XP to earn your first Bronze trophy!</p>
            ) : (
              <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-4">
                {badges.map((badge) => {
                  const gradient = badgeColors[badge.name] || 'from-gray-500 to-gray-400';
                  return (
                    <div 
                      key={badge.id}
                      className="flex flex-col items-center p-3 rounded-2xl bg-white dark:bg-slate-950 border border-gray-200 dark:border-slate-800 shadow hover:scale-[1.03] transition duration-200"
                    >
                      <div className={`h-12 w-12 rounded-full bg-gradient-to-tr ${gradient} text-white flex items-center justify-center shadow-lg ring-4 ring-offset-2 dark:ring-offset-slate-950 mt-1`}>
                        <FiStar className="h-5 w-5 fill-current" />
                      </div>
                      <p className="text-xs font-bold text-gray-800 dark:text-white mt-3 uppercase tracking-wide">{badge.name}</p>
                      <p className="text-[8px] text-gray-400 mt-1 text-center line-clamp-2 leading-normal">{badge.description}</p>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* Achievements List */}
          <div className="glass-panel p-6 rounded-2xl shadow-xl bg-white/40 dark:bg-slate-900/30 space-y-4">
            <h3 className="text-sm font-extrabold text-gray-900 dark:text-white border-b border-gray-150 dark:border-slate-805 pb-3">
              Achievements Unlocked ({achievements.length})
            </h3>

            {achievements.length === 0 ? (
              <p className="text-xs text-gray-400 text-center py-6 font-medium">No achievements unlocked yet. Continue studying to claim awards!</p>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3.5">
                {achievements.map((ach) => (
                  <div 
                    key={ach.id}
                    className="flex gap-3.5 items-center p-3.5 rounded-xl border border-gray-200 dark:border-slate-800 bg-white/20 dark:bg-slate-900/10 hover:border-primary-500/20 transition-all duration-200"
                  >
                    <div className="h-9 w-9 rounded-lg bg-primary-100 dark:bg-primary-950/40 text-primary-600 dark:text-primary-400 flex items-center justify-center border border-primary-200/30 dark:border-primary-900/20 shrink-0">
                      <FiCheckCircle className="h-5 w-5" />
                    </div>
                    <div className="text-left overflow-hidden">
                      <p className="text-xs font-bold text-gray-800 dark:text-white truncate">{ach.title}</p>
                      <p className="text-[10px] text-gray-400 line-clamp-2 mt-0.5">{ach.description}</p>
                      <p className="text-[8px] text-primary-400 mt-1 uppercase font-bold">Unlocked: {new Date(ach.unlockedAt).toLocaleDateString()}</p>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

        </div>

      </div>
    </div>
  );
};

export default Profile;
