import React, { useState, useEffect } from 'react';
import api from '../services/api';
import { useAuth } from '../context/AuthContext';
import { 
  FiUsers, FiBookOpen, FiMessageSquare, FiShield, 
  FiTrash2, FiActivity, FiAward, FiStar, FiAlertTriangle 
} from 'react-icons/fi';

const Admin = () => {
  const { user: currentUser } = useAuth();
  const [activeTab, setActiveTab] = useState('users'); // 'users' | 'quizzes' | 'feedback'
  const [usersList, setUsersList] = useState([]);
  const [quizzesList, setQuizzesList] = useState([]);
  const [feedbackList, setFeedbackList] = useState([]);
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    fetchAdminData();
  }, []);

  const fetchAdminData = async () => {
    setLoading(true);
    setError('');
    try {
      const [usersRes, quizzesRes, feedbackRes, statsRes] = await Promise.all([
        api.get('/admin/users'),
        api.get('/admin/quizzes'),
        api.get('/admin/feedback'),
        api.get('/admin/stats')
      ]);

      setUsersList(usersRes.data);
      setQuizzesList(quizzesRes.data);
      setFeedbackList(feedbackRes.data);
      setStats(statsRes.data);
    } catch (err) {
      console.error("Failed to load administrative resources", err);
      setError("Authorization denied or API endpoint inaccessible. Admin rights required.");
    } finally {
      setLoading(false);
    }
  };

  const handleDeleteUser = async (userId) => {
    if (userId === currentUser.id) {
      alert("Error: You cannot delete your own administrative account.");
      return;
    }
    if (!window.confirm("WARNING: This will permanently delete the user profile and ALL their learning history. Proceed?")) return;

    try {
      await api.delete(`/admin/users/${userId}`);
      setUsersList(usersList.filter(u => u.id !== userId));
      // Refresh stats
      const statsRes = await api.get('/admin/stats');
      setStats(statsRes.data);
    } catch (err) {
      console.error("Failed to delete user", err);
      alert("Deletions Cascade Failed. Please try again.");
    }
  };

  const handleDeleteQuiz = async (quizId) => {
    if (!window.confirm("Are you sure you want to delete this quiz?")) return;
    try {
      await api.delete(`/admin/quizzes/${quizId}`);
      setQuizzesList(quizzesList.filter(q => q.id !== quizId));
      // Refresh stats
      const statsRes = await api.get('/admin/stats');
      setStats(statsRes.data);
    } catch (err) {
      console.error("Failed to delete quiz", err);
    }
  };

  const handleDeleteFeedback = async (feedbackId) => {
    if (!window.confirm("Are you sure you want to delete this feedback review?")) return;
    try {
      await api.delete(`/admin/feedback/${feedbackId}`);
      setFeedbackList(feedbackList.filter(f => f.id !== feedbackId));
      // Refresh stats
      const statsRes = await api.get('/admin/stats');
      setStats(statsRes.data);
    } catch (err) {
      console.error("Failed to delete feedback", err);
    }
  };

  const renderStars = (rating) => {
    return (
      <div className="flex gap-0.5 text-yellow-400">
        {[1, 2, 3, 4, 5].map((s) => (
          <FiStar key={s} fill={s <= rating ? "currentColor" : "none"} className="h-3.5 w-3.5" />
        ))}
      </div>
    );
  };

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <div className="h-10 w-10 animate-spin rounded-full border-4 border-t-primary-600 border-primary-200"></div>
      </div>
    );
  }

  return (
    <div className="space-y-6 text-left">
      <div>
        <h1 className="text-3xl font-extrabold tracking-tight text-gray-900 dark:text-white">Admin Console</h1>
        <p className="mt-1 text-sm text-gray-500 dark:text-slate-400">
          Manage user profiles, clean platform quizzes, view reviews, and monitor usage.
        </p>
      </div>

      {error && (
        <div className="flex items-center gap-3 rounded-lg bg-red-50 dark:bg-red-950/20 border border-red-200 dark:border-red-800/30 p-4 text-sm text-red-800 dark:text-red-400">
          <FiAlertTriangle className="h-5 w-5 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* KPI Stats Grid */}
      {stats && (
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
          <div className="glass-panel p-5 rounded-2xl flex items-center gap-4">
            <div className="p-3 bg-primary-100 dark:bg-primary-950/30 text-primary-600 dark:text-primary-400 rounded-xl">
              <FiUsers className="h-6 w-6" />
            </div>
            <div>
              <p className="text-[10px] uppercase font-bold text-gray-400">Total Users</p>
              <p className="text-xl font-extrabold text-gray-800 dark:text-white">{stats.totalUsers}</p>
            </div>
          </div>

          <div className="glass-panel p-5 rounded-2xl flex items-center gap-4">
            <div className="p-3 bg-violet-100 dark:bg-violet-950/30 text-violet-600 dark:text-violet-400 rounded-xl">
              <FiActivity className="h-6 w-6" />
            </div>
            <div>
              <p className="text-[10px] uppercase font-bold text-gray-400">Total Hours</p>
              <p className="text-xl font-extrabold text-gray-800 dark:text-white">{stats.totalHoursSum}h</p>
            </div>
          </div>

          <div className="glass-panel p-5 rounded-2xl flex items-center gap-4">
            <div className="p-3 bg-yellow-100 dark:bg-yellow-950/30 text-yellow-600 dark:text-yellow-500 rounded-xl">
              <FiBookOpen className="h-6 w-6" />
            </div>
            <div>
              <p className="text-[10px] uppercase font-bold text-gray-400">Quizzes Built</p>
              <p className="text-xl font-extrabold text-gray-800 dark:text-white">{stats.totalQuizzesGenerated}</p>
            </div>
          </div>

          <div className="glass-panel p-5 rounded-2xl flex items-center gap-4">
            <div className="p-3 bg-green-100 dark:bg-green-950/30 text-green-600 dark:text-green-400 rounded-xl">
              <FiAward className="h-6 w-6" />
            </div>
            <div>
              <p className="text-[10px] uppercase font-bold text-gray-400">Feedback Log</p>
              <p className="text-xl font-extrabold text-gray-800 dark:text-white">{stats.totalFeedbackSubmitted}</p>
            </div>
          </div>

          <div className="glass-panel col-span-2 lg:col-span-1 p-5 rounded-2xl flex items-center gap-4">
            <div className="p-3 bg-orange-100 dark:bg-orange-950/30 text-orange-600 dark:text-orange-450 rounded-xl">
              <FiAward className="h-6 w-6" />
            </div>
            <div>
              <p className="text-[10px] uppercase font-bold text-gray-400">Avg Streak</p>
              <p className="text-xl font-extrabold text-gray-800 dark:text-white">{stats.averageStreak}d</p>
            </div>
          </div>
        </div>
      )}

      {/* Main Panel layout */}
      <div className="glass-panel rounded-2xl shadow-sm border border-gray-200 dark:border-slate-800 overflow-hidden">
        
        {/* Navigation Tabs */}
        <div className="flex border-b border-gray-150 dark:border-slate-805 bg-gray-50/50 dark:bg-slate-900/10 px-4">
          {[
            { id: 'users', label: 'Users Management', icon: <FiUsers className="h-4 w-4" /> },
            { id: 'quizzes', label: 'Quiz Archives', icon: <FiBookOpen className="h-4 w-4" /> },
            { id: 'feedback', label: 'User Feedback', icon: <FiMessageSquare className="h-4 w-4" /> }
          ].map(tab => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex items-center gap-2 py-4 px-4 text-sm font-bold border-b-2 transition ${
                activeTab === tab.id
                  ? 'border-primary-600 text-primary-600 dark:text-primary-400'
                  : 'border-transparent text-gray-400 hover:text-gray-600 dark:hover:text-slate-200'
              }`}
            >
              {tab.icon}
              <span>{tab.label}</span>
            </button>
          ))}
        </div>

        {/* Tab Contents */}
        <div className="p-6 overflow-x-auto">
          
          {/* TAB 1: Users table */}
          {activeTab === 'users' && (
            <table className="w-full text-left border-collapse min-w-[700px]">
              <thead>
                <tr className="border-b border-gray-200 dark:border-slate-800 text-xs font-bold text-gray-400 uppercase">
                  <th className="pb-3 pr-2">Username</th>
                  <th className="pb-3 pr-2">Email</th>
                  <th className="pb-3 pr-2">Streak</th>
                  <th className="pb-3 pr-2">Study Time</th>
                  <th className="pb-3 pr-2">Quizzes</th>
                  <th className="pb-3 pr-2">Roles</th>
                  <th className="pb-3 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 dark:divide-slate-800 text-sm">
                {usersList.map((usr) => (
                  <tr key={usr.id} className="hover:bg-gray-50/40 dark:hover:bg-slate-900/10 transition">
                    <td className="py-4 font-bold text-gray-800 dark:text-white truncate max-w-[120px]">{usr.username}</td>
                    <td className="py-4 text-gray-500 dark:text-slate-400 truncate max-w-[150px]">{usr.email}</td>
                    <td className="py-4 font-bold text-orange-500">{usr.streak} days</td>
                    <td className="py-4 font-semibold text-gray-600 dark:text-slate-350">{usr.totalHours.toFixed(1)}h</td>
                    <td className="py-4 font-semibold text-gray-600 dark:text-slate-355">{usr.completedQuizzesCount}</td>
                    <td className="py-4">
                      {usr.roles.map(r => (
                        <span key={r} className="inline-block text-[9px] font-bold px-1.5 py-0.5 rounded bg-primary-50 dark:bg-primary-950/20 text-primary-600 dark:text-primary-400 border border-primary-100 dark:border-primary-900/10 mr-1 uppercase">
                          {r.replace('ROLE_', '')}
                        </span>
                      ))}
                    </td>
                    <td className="py-4 text-right">
                      <button
                        onClick={() => handleDeleteUser(usr.id)}
                        disabled={usr.id === currentUser.id}
                        className="p-2 rounded text-red-500 hover:bg-red-50 dark:hover:bg-red-950/10 disabled:opacity-30 transition"
                        title="Delete User Cascade"
                      >
                        <FiTrash2 className="h-4 w-4" />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          {/* TAB 2: Quizzes table */}
          {activeTab === 'quizzes' && (
            <table className="w-full text-left border-collapse min-w-[700px]">
              <thead>
                <tr className="border-b border-gray-200 dark:border-slate-800 text-xs font-bold text-gray-400 uppercase">
                  <th className="pb-3 pr-2">Title</th>
                  <th className="pb-3 pr-2">Category</th>
                  <th className="pb-3 pr-2">Difficulty</th>
                  <th className="pb-3 pr-2">Questions</th>
                  <th className="pb-3 pr-2">Created By</th>
                  <th className="pb-3 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 dark:divide-slate-800 text-sm">
                {quizzesList.map((quiz) => (
                  <tr key={quiz.id} className="hover:bg-gray-50/40 dark:hover:bg-slate-900/10 transition">
                    <td className="py-4 font-bold text-gray-800 dark:text-white truncate max-w-[200px]" title={quiz.title}>
                      {quiz.title}
                    </td>
                    <td className="py-4 text-gray-500 dark:text-slate-400 font-semibold">{quiz.category}</td>
                    <td className="py-4">
                      <span className={`inline-block text-[9px] font-extrabold px-1.5 py-0.5 rounded ${
                        quiz.difficulty === 'Easy' ? 'bg-green-100 text-green-800 dark:bg-green-950/20' :
                        quiz.difficulty === 'Medium' ? 'bg-yellow-100 text-yellow-800 dark:bg-yellow-950/20' :
                        'bg-red-100 text-red-800 dark:bg-red-950/20'
                      }`}>
                        {quiz.difficulty}
                      </span>
                    </td>
                    <td className="py-4 font-semibold text-gray-600 dark:text-slate-350">{quiz.questions.length} Qs</td>
                    <td className="py-4 text-xs font-semibold text-gray-400 uppercase">{quiz.createdBy}</td>
                    <td className="py-4 text-right">
                      <button
                        onClick={() => handleDeleteQuiz(quiz.id)}
                        className="p-2 rounded text-red-500 hover:bg-red-50 dark:hover:bg-red-950/10 transition"
                        title="Delete Quiz"
                      >
                        <FiTrash2 className="h-4 w-4" />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          {/* TAB 3: Feedback reviews list */}
          {activeTab === 'feedback' && (
            <div className="space-y-4">
              {feedbackList.length === 0 ? (
                <p className="text-sm text-gray-400 py-10 text-center">No feedback has been submitted yet.</p>
              ) : (
                feedbackList.map((fb) => (
                  <div key={fb.id} className="p-4 rounded-xl border border-gray-150 dark:border-slate-850 flex justify-between items-start gap-4">
                    <div className="space-y-2 text-left">
                      <div className="flex items-center gap-3 flex-wrap">
                        <p className="text-xs font-bold text-gray-800 dark:text-slate-200">{fb.username}</p>
                        {renderStars(fb.rating)}
                        <span className="text-[10px] text-gray-400">
                          {new Date(fb.createdAt).toLocaleDateString()}
                        </span>
                      </div>
                      <p className="text-sm text-gray-600 dark:text-slate-300 leading-relaxed">
                        {fb.feedbackText}
                      </p>
                    </div>

                    <button
                      onClick={() => handleDeleteFeedback(fb.id)}
                      className="p-2 rounded text-red-500 hover:bg-red-50 dark:hover:bg-red-950/10 shrink-0 transition"
                      title="Delete Feedback"
                    >
                      <FiTrash2 className="h-4 w-4" />
                    </button>
                  </div>
                ))
              )}
            </div>
          )}

        </div>
      </div>
    </div>
  );
};

export default Admin;
