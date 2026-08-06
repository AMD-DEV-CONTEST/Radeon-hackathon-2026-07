import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { 
  Sparkles, CheckCircle, AlertTriangle, ArrowRight, Loader2, 
  MapPin, ClipboardList, Briefcase, Plus, X, Lightbulb
} from 'lucide-react';
import { useNotification } from '../context/NotificationContext';
import { useAuth } from '../context/AuthContext';
import GlassCard from '../components/GlassCard';
import axios from 'axios';

export const SkillGapPage: React.FC = () => {
  const navigate = useNavigate();
  const { user, refreshProfile } = useAuth();
  const { showToast } = useNotification();
  
  const [dreamJob, setDreamJob] = useState(user?.targetCareer || '');
  const [currentSkills, setCurrentSkills] = useState<string[]>(user?.currentSkills || []);
  const [skillInput, setSkillInput] = useState('');
  
  const [analyzing, setAnalyzing] = useState(false);
  const [result, setResult] = useState<any>(null);

  useEffect(() => {
    if (user) {
      setDreamJob(user.targetCareer || '');
      setCurrentSkills(user.currentSkills || []);
    }
  }, [user]);

  const handleAddSkill = (e: React.FormEvent) => {
    e.preventDefault();
    const cleanInput = skillInput.trim();
    if (cleanInput && !currentSkills.includes(cleanInput)) {
      setCurrentSkills(prev => [...prev, cleanInput]);
      setSkillInput('');
    }
  };

  const handleRemoveSkill = (skill: string) => {
    setCurrentSkills(prev => prev.filter(s => s !== skill));
  };

  const handleAnalyzeGap = async () => {
    if (!dreamJob.trim()) {
      showToast('Please specify your dream career path first', 'error');
      return;
    }
    if (currentSkills.length === 0) {
      showToast('Please list at least one current technical skill', 'error');
      return;
    }

    setAnalyzing(true);
    try {
      showToast('Comparing skills and creating roadmap curriculum...', 'info');
      const response = await axios.post('/api/roadmap/analyze-gap', {
        dreamJob,
        currentSkills
      });
      setResult(response.data);
      showToast('Skill Gap evaluation completed!', 'success');
      await refreshProfile(); // Refresh dashboard stats
    } catch (err) {
      showToast('Could not evaluate skill gap logs', 'error');
    } finally {
      setAnalyzing(false);
    }
  };

  return (
    <div className="flex flex-col gap-8">
      
      {/* Page Header */}
      <div className="border-b border-dark-800/40 pb-6">
        <h2 className="text-3xl font-extrabold font-heading text-dark-50 tracking-tight flex items-center gap-2">
          <ClipboardList className="w-8 h-8 text-primary-400" />
          Skill Gap Analysis
        </h2>
        <p className="text-sm text-dark-400 mt-1">
          Contrast your current technology capabilities against targeted career paths to evaluate competencies and unlock plans.
        </p>
      </div>

      {/* WORKSPACE PANELS */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-start">
        
        {/* Form Inputs (Left) */}
        <div className="lg:col-span-5 flex flex-col gap-6">
          <GlassCard>
            <h3 className="font-heading font-bold text-base text-dark-100 mb-5 flex items-center gap-2">
              <Briefcase className="w-5 h-5 text-primary-400" />
              Career Details
            </h3>

            <div className="flex flex-col gap-5">
              
              {/* Dream job input field */}
              <div className="flex flex-col gap-1.5">
                <label className="text-xs font-bold text-dark-300">Dream Career Role</label>
                <input
                  type="text"
                  required
                  value={dreamJob}
                  onChange={(e) => setDreamJob(e.target.value)}
                  placeholder="e.g. Senior DevOps Architect"
                  className="w-full px-4 py-3 rounded-xl border glass-input text-sm text-dark-100"
                />
              </div>

              {/* Skills list manager */}
              <div className="flex flex-col gap-2">
                <label className="text-xs font-bold text-dark-300">Technical Competencies</label>
                <form onSubmit={handleAddSkill} className="flex gap-2">
                  <input
                    type="text"
                    value={skillInput}
                    onChange={(e) => setSkillInput(e.target.value)}
                    placeholder="e.g. Docker"
                    className="flex-1 px-4 py-2.5 rounded-xl border glass-input text-xs text-dark-100"
                  />
                  <button
                    type="submit"
                    className="px-4 py-2.5 bg-dark-900 border border-dark-800 hover:border-primary-500/20 text-dark-200 hover:text-primary-400 font-bold rounded-xl transition-all"
                  >
                    <Plus className="w-5 h-5" />
                  </button>
                </form>

                {/* Display items list */}
                <div className="flex flex-wrap gap-2 mt-3 p-3 bg-dark-950/20 rounded-xl border border-dark-900/50 min-h-[100px]">
                  {currentSkills.length === 0 ? (
                    <span className="text-[10px] text-dark-500 m-auto text-center">Add technical skills above</span>
                  ) : (
                    currentSkills.map(skill => (
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
                  )}
                </div>
              </div>

              <button
                onClick={handleAnalyzeGap}
                disabled={analyzing}
                className="w-full mt-2 py-3.5 bg-gradient-to-r from-primary-600 to-cyan-600 hover:from-primary-500 hover:to-cyan-500 text-white font-bold rounded-xl shadow-lg flex items-center justify-center gap-2 text-xs transition-all hover:scale-102 disabled:opacity-60"
              >
                {analyzing ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    Calculating Gap...
                  </>
                ) : (
                  <>
                    Perform Gap Audit
                    <ArrowRight className="w-4 h-4" />
                  </>
                )}
              </button>

            </div>
          </GlassCard>
        </div>

        {/* Results display (Right) */}
        <div className="lg:col-span-7 flex flex-col gap-6">
          {analyzing ? (
            <div className="glass-panel p-16 rounded-2xl text-center border border-dark-800/30 flex flex-col items-center justify-center gap-4 min-h-[400px]">
              <Loader2 className="w-12 h-12 text-primary-500 animate-spin" />
              <h3 className="font-bold text-lg text-dark-100 font-heading">Generating Curriculum Modules</h3>
              <p className="text-xs text-dark-400 max-w-sm leading-relaxed">
                We are mapping skill requirements for {dreamJob}, auditing your tech items list, computing estimated study hours, and organizing a 4-week timeline.
              </p>
            </div>
          ) : result ? (
            <div className="flex flex-col gap-6 animate-slide-up">
              
              {/* Summary cards info */}
              <GlassCard className="bg-gradient-to-br from-dark-950/60 to-primary-950/15 p-6 border-l-4 border-l-primary-500">
                <h3 className="text-lg font-bold font-heading text-dark-50">Curriculum generated successfully!</h3>
                <p className="text-xs text-dark-400 mt-1 leading-normal">
                  Our system mapped a 4-week tracking timeline. You can check study items off directly on your calendar view.
                </p>
                <div className="flex items-center gap-6 mt-4">
                  <div className="text-xs">
                    <span className="text-dark-400 block uppercase font-bold text-[8px] tracking-wider">Estimated study time</span>
                    <span className="text-sm font-black text-primary-400 mt-0.5 block">{result.completionTime || '4 Weeks'}</span>
                  </div>
                </div>
              </GlassCard>

              {/* Technologies to learn list card */}
              <GlassCard className="flex flex-col gap-4">
                <h4 className="font-bold text-sm text-dark-100 flex items-center gap-2">
                  <AlertTriangle className="w-4.5 h-4.5 text-yellow-400" />
                  Technologies Gaps Detected
                </h4>
                <p className="text-[11px] text-dark-400 leading-normal">
                  Our AI determined that the following tools are crucial for {dreamJob} but missing in your profile.
                </p>
                <div className="flex flex-wrap gap-2 mt-1">
                  {result.skillsToLearn && result.skillsToLearn.length > 0 ? (
                    result.skillsToLearn.map((skill: string) => (
                      <span
                        key={skill}
                        className="px-3 py-1 bg-yellow-500/10 border border-yellow-500/25 rounded-lg text-xs font-bold text-yellow-400"
                      >
                        + {skill}
                      </span>
                    ))
                  ) : (
                    <span className="text-xs text-dark-500">No technology gaps. You are corporate ready.</span>
                  )}
                </div>
              </GlassCard>

              {/* Suggestions items cards */}
              <GlassCard className="flex flex-col gap-4">
                <h4 className="font-bold text-sm text-dark-100 flex items-center gap-2">
                  <Lightbulb className="w-4.5 h-4.5 text-cyan-400" />
                  General Study Recommendations
                </h4>
                <div className="flex flex-col gap-3">
                  <div className="flex gap-2 text-xs text-dark-200 leading-relaxed">
                    <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 mt-1.5 shrink-0" />
                    <span>Follow the custom 4-week weekly roadmaps sequence in order.</span>
                  </div>
                  <div className="flex gap-2 text-xs text-dark-200 leading-relaxed">
                    <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 mt-1.5 shrink-0" />
                    <span>Create a Github repository for every technology checked off.</span>
                  </div>
                </div>
              </GlassCard>

              <button
                onClick={() => navigate('/roadmap')}
                className="py-3.5 bg-gradient-to-r from-primary-600 to-cyan-600 hover:from-primary-500 hover:to-cyan-500 text-white font-bold rounded-xl text-xs flex items-center justify-center gap-2 transition-all hover:scale-102"
              >
                Go to Interactive Learning Roadmap
                <ArrowRight className="w-4 h-4" />
              </button>

            </div>
          ) : (
            <div className="glass-panel p-16 rounded-2xl text-center border border-dark-800/30 flex flex-col items-center justify-center gap-4 min-h-[400px]">
              <ClipboardList className="w-14 h-14 text-dark-500 animate-float" />
              <h3 className="font-bold text-lg text-dark-200 font-heading">No gap data calculated</h3>
              <p className="text-xs text-dark-400 max-w-sm leading-relaxed">
                Provide your target career and technical skills list on the left to run gap metrics check.
              </p>
            </div>
          )}
        </div>

      </div>

    </div>
  );
};

export default SkillGapPage;
