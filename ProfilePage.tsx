import React, { useState } from 'react';
import { 
  User, Mail, Briefcase, Award, CheckCircle, Lock, 
  MapPin, Calendar, Compass, Sparkles, BookOpen, Clock
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { useNotification } from '../context/NotificationContext';
import GlassCard from '../components/GlassCard';

export const ProfilePage: React.FC = () => {
  const { user, updateProfileSettings } = useAuth();
  const { showToast } = useNotification();
  
  const [skillInput, setSkillInput] = useState('');
  const [saving, setSaving] = useState(false);

  // List of all possible achievement badges in the app system for collection display
  const allPossibleBadges = [
    { id: 'welcome_pilot', title: 'Welcome Pilot', desc: 'Created an account and took the first step.', icon: 'compass' },
    { id: 'profile_builder', title: 'Profile Completed', desc: 'Set target career and listed competencies.', icon: 'user-check' },
    { id: 'resume_uploaded', title: 'Resume Critic', desc: 'Uploaded and parsed first PDF resume.', icon: 'file-text' },
    { id: 'ats_master', title: 'ATS Master', desc: 'Achieved an ATS score of 80% or higher.', icon: 'shield-check' },
    { id: 'first_mock', title: 'Interview Explorer', desc: 'Completed first Mock interview simulator.', icon: 'users' },
    { id: 'mock_star', title: 'Mock Superstar', desc: 'Aced an interview loop score above 8.0/10.', icon: 'award' },
    { id: 'roadmap_created', title: 'Roadmap Planner', desc: 'Generated first weekly learning timeline.', icon: 'map' },
    { id: 'first_task', title: 'Pathfinder', desc: 'Checked off first daily roadmap task.', icon: 'check-circle' },
    { id: 'roadmap_wizard', title: 'Placement Graduate', desc: 'Completed 100% of study roadmap curriculum.', icon: 'graduation-cap' },
    { id: 'first_convo', title: 'AI Explorer', desc: 'Had first AI career consultation.', icon: 'message-square' },
    { id: 'chatty_pilot', title: 'Deep Thinker', desc: 'Maintained 5 or more AI chats logs.', icon: 'brain' }
  ];

  const handleAddSkill = async (e: React.FormEvent) => {
    e.preventDefault();
    const cleanSkill = skillInput.trim();
    if (!cleanSkill) return;
    
    if (user?.currentSkills?.includes(cleanSkill)) {
      showToast('Skill already exists in your profile', 'info');
      return;
    }

    setSaving(true);
    try {
      const updatedSkills = [...(user?.currentSkills || []), cleanSkill];
      await updateProfileSettings({ currentSkills: updatedSkills });
      setSkillInput('');
    } catch (err) {
      showToast('Failed to append skill details', 'error');
    } finally {
      setSaving(false);
    }
  };

  const handleRemoveSkill = async (skill: string) => {
    setSaving(true);
    try {
      const updatedSkills = (user?.currentSkills || []).filter(s => s !== skill);
      await updateProfileSettings({ currentSkills: updatedSkills });
    } catch (err) {
      showToast('Failed to delete skill details', 'error');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="flex flex-col gap-8 animate-fade-in">
      
      {/* Page Header */}
      <div className="border-b border-dark-800/40 pb-6">
        <h2 className="text-3xl font-extrabold font-heading text-dark-50 tracking-tight flex items-center gap-2">
          <User className="w-8 h-8 text-primary-400" />
          Profile & Achievement Badges
        </h2>
        <p className="text-sm text-dark-400 mt-1">
          Review career objectives, edit core competencies, and track placement milestone awards.
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-start">
        
        {/* Profile Info & Skills Panel (Left) */}
        <div className="lg:col-span-5 flex flex-col gap-6">
          <GlassCard className="flex flex-col gap-5">
            <div className="flex items-center gap-4.5 border-b border-dark-800/40 pb-4">
              <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center font-bold text-white uppercase text-2xl shadow-lg shadow-indigo-500/10">
                {user?.name ? user.name.substring(0, 2) : 'CP'}
              </div>
              <div className="min-w-0">
                <h3 className="font-heading font-extrabold text-lg text-dark-50 truncate">{user?.name}</h3>
                <span className="text-[11px] text-dark-400 font-semibold truncate flex items-center gap-1 mt-0.5">
                  <Briefcase className="w-3.5 h-3.5 text-primary-400" />
                  {user?.targetCareer || 'Career Explorer'}
                </span>
              </div>
            </div>

            <div className="flex flex-col gap-3.5 text-xs text-dark-300">
              <div className="flex items-center gap-2.5">
                <Mail className="w-4.5 h-4.5 text-dark-500 shrink-0" />
                <span className="truncate">{user?.email}</span>
              </div>
              <div className="flex items-center gap-2.5">
                <Compass className="w-4.5 h-4.5 text-dark-500 shrink-0" />
                <span>Language preference: {user?.language === 'en' ? 'English (EN)' : 'Other'}</span>
              </div>
            </div>
          </GlassCard>

          {/* Edit Skills Badge list */}
          <GlassCard className="flex flex-col gap-4">
            <h4 className="font-bold text-sm text-dark-100 flex items-center gap-2">
              <BookOpen className="w-4.5 h-4.5 text-primary-400" />
              Core Competencies
            </h4>
            <p className="text-[11px] text-dark-400 leading-normal">
              List the technologies you are comfortable with. These will be referenced during Skill Gap comparisons.
            </p>

            <form onSubmit={handleAddSkill} className="flex gap-2 mt-1">
              <input
                type="text"
                required
                value={skillInput}
                onChange={(e) => setSkillInput(e.target.value)}
                placeholder="e.g. Next.js"
                className="flex-1 px-4 py-2.5 rounded-xl border glass-input text-xs"
              />
              <button
                type="submit"
                disabled={saving}
                className="px-4 py-2.5 bg-gradient-to-r from-primary-600 to-cyan-600 hover:from-primary-500 hover:to-cyan-500 text-white font-bold rounded-xl text-xs hover:scale-102 transition-all"
              >
                Add
              </button>
            </form>

            <div className="flex flex-wrap gap-2 mt-2 p-3 bg-dark-950/20 rounded-xl border border-dark-900/50 min-h-[80px]">
              {user?.currentSkills && user.currentSkills.length > 0 ? (
                user.currentSkills.map(skill => (
                  <span
                    key={skill}
                    className="px-2.5 py-1 bg-primary-950/20 border border-primary-500/10 text-primary-400 text-xs font-bold rounded-lg flex items-center gap-1.5"
                  >
                    {skill}
                    <X 
                      className="w-3.5 h-3.5 text-dark-400 hover:text-rose-400 cursor-pointer"
                      onClick={() => handleRemoveSkill(skill)}
                    />
                  </span>
                ))
              ) : (
                <span className="text-[10px] text-dark-500 m-auto">No skills added yet</span>
              )}
            </div>
          </GlassCard>
        </div>

        {/* Achievements Badge Grid (Right) */}
        <div className="lg:col-span-7 flex flex-col gap-6">
          <h3 className="font-heading font-bold text-base text-dark-100 uppercase tracking-wider pl-1">
            Unlocked Achievements Collection
          </h3>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {allPossibleBadges.map(badge => {
              // Check if user unlocked this badge
              const unlockedBadge = user?.achievements?.find(a => a.id === badge.id);
              const isUnlocked = !!unlockedBadge;

              return (
                <div
                  key={badge.id}
                  className={`p-4.5 rounded-2xl border transition-all flex items-start gap-4 relative overflow-hidden ${
                    isUnlocked
                      ? 'border-yellow-500/30 bg-gradient-to-br from-dark-950/40 to-yellow-950/5 shadow-md shadow-yellow-500/5'
                      : 'border-dark-800/40 bg-dark-950/10 opacity-50'
                  }`}
                >
                  {/* Glowing background for unlocked achievements */}
                  {isUnlocked && (
                    <div className="absolute -right-10 -top-10 w-20 h-20 rounded-full bg-yellow-500/5 blur-xl pointer-events-none" />
                  )}

                  <div className={`p-3 rounded-xl shrink-0 ${
                    isUnlocked ? 'bg-yellow-500/10 text-yellow-400' : 'bg-dark-900 text-dark-500'
                  }`}>
                    <Award className="w-6 h-6" />
                  </div>

                  <div className="min-w-0">
                    <div className="flex items-center gap-1.5">
                      <h4 className={`text-xs font-bold ${isUnlocked ? 'text-dark-100 font-extrabold' : 'text-dark-400'}`}>
                        {badge.title}
                      </h4>
                      {isUnlocked && <CheckCircle className="w-3.5 h-3.5 text-yellow-400 shrink-0" />}
                    </div>
                    <p className="text-[10px] text-dark-400 leading-normal mt-1 pr-1">{badge.desc}</p>
                    {isUnlocked && unlockedBadge.unlockedAt && (
                      <span className="text-[8px] text-dark-500 block mt-2 tracking-wide font-semibold flex items-center gap-1">
                        <Clock className="w-3 h-3 text-yellow-500/60" />
                        Unlocked {new Date(unlockedBadge.unlockedAt).toLocaleDateString()}
                      </span>
                    )}
                  </div>

                </div>
              );
            })}
          </div>
        </div>

      </div>

    </div>
  );
};

export default ProfilePage;
