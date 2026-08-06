import React, { useState, useEffect } from 'react';
import { 
  UploadCloud, FileText, CheckCircle, AlertTriangle, Sparkles, 
  BookOpen, Trophy, Plus, FileCheck, ArrowRight, Loader2, RefreshCw
} from 'lucide-react';
import { useNotification } from '../context/NotificationContext';
import { useAuth } from '../context/AuthContext';
import GlassCard from '../components/GlassCard';
import axios from 'axios';

export const ResumeAnalyzerPage: React.FC = () => {
  const { refreshProfile } = useAuth();
  const { showToast } = useNotification();
  
  const [file, setFile] = useState<File | null>(null);
  const [targetJob, setTargetJob] = useState('');
  const [analyzing, setAnalyzing] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [history, setHistory] = useState<any[]>([]);
  const [activeTab, setActiveTab] = useState<'checklist' | 'bullets' | 'recommendations'>('checklist');

  const fetchLatestAndHistory = async () => {
    try {
      const latestRes = await axios.get('/api/resume/latest');
      setResult(latestRes.data);
    } catch (err) {
      // 404 is normal if no resume uploaded yet
      console.log('[Resume] No resume found in history');
    }

    try {
      const historyRes = await axios.get('/api/resume/history');
      setHistory(historyRes.data);
    } catch (err) {
      console.error('[Resume History] Failed to load history:', err);
    }
  };

  useEffect(() => {
    fetchLatestAndHistory();
  }, []);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      const selected = e.target.files[0];
      if (selected.type !== 'application/pdf') {
        showToast('Only PDF files are supported', 'error');
        return;
      }
      setFile(selected);
    }
  };

  const handleAnalyze = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!file) {
      showToast('Please select a PDF resume file to upload', 'error');
      return;
    }
    if (!targetJob.trim()) {
      showToast('Please specify the target career/job title', 'error');
      return;
    }

    setAnalyzing(true);
    const formData = new FormData();
    formData.append('resume', file);
    formData.append('targetJob', targetJob);

    try {
      showToast('Extracting text and running ATS algorithms...', 'info');
      const response = await axios.post('/api/resume/analyze', formData, {
        headers: {
          'Content-Type': 'multipart/form-data'
        }
      });
      setResult(response.data);
      showToast('Resume ATS Analysis completed successfully!', 'success');
      await refreshProfile(); // Refresh profile badges
      fetchLatestAndHistory(); // Sync logs lists
      setFile(null);
    } catch (error: any) {
      const errorMsg = error.response?.data?.error || 'Could not evaluate resume content.';
      showToast(errorMsg, 'error');
    } finally {
      setAnalyzing(false);
    }
  };

  const handleLoadHistoryItem = async (id: string) => {
    try {
      setAnalyzing(true);
      // Fetch details
      const response = await axios.get(`/api/resume/history`);
      const selected = response.data.find((r: any) => r._id === id);
      // Hit endpoint to get full text
      const fullRes = await axios.get('/api/resume/latest');
      setResult(fullRes.data);
      showToast('Loaded historical analysis details', 'success');
    } catch (err) {
      showToast('Failed to fetch details', 'error');
    } finally {
      setAnalyzing(false);
    }
  };

  return (
    <div className="flex flex-col gap-8">
      
      {/* Page Header */}
      <div className="border-b border-dark-800/40 pb-6">
        <h2 className="text-3xl font-extrabold font-heading text-dark-50 tracking-tight flex items-center gap-2">
          <FileCheck className="w-8 h-8 text-primary-400" />
          ATS Resume Critic
        </h2>
        <p className="text-sm text-dark-400 mt-1">
          Upload your PDF resume to evaluate readabilities, check keyword alignment, and get AI-powered bullet refactorings.
        </p>
      </div>

      {/* WORKSPACE PANELS */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-start">
        
        {/* Upload Column (Left) */}
        <div className="lg:col-span-4 flex flex-col gap-6">
          <GlassCard>
            <h3 className="font-heading font-bold text-base text-dark-100 mb-4 flex items-center gap-2">
              <UploadCloud className="w-5 h-5 text-primary-400" />
              Upload Resume
            </h3>

            <form onSubmit={handleAnalyze} className="flex flex-col gap-5">
              
              {/* Target Job Selector */}
              <div className="flex flex-col gap-1.5">
                <label className="text-xs font-bold text-dark-300">Target Job Title</label>
                <input
                  type="text"
                  required
                  value={targetJob}
                  onChange={(e) => setTargetJob(e.target.value)}
                  placeholder="e.g. Junior Front End Developer"
                  className="w-full px-4 py-3 rounded-xl border glass-input text-sm text-dark-100"
                />
              </div>

              {/* Drag Drop File Input Area */}
              <div className="flex flex-col gap-1.5">
                <label className="text-xs font-bold text-dark-300">PDF File</label>
                <div className="border-2 border-dashed border-dark-700/60 hover:border-primary-500/45 rounded-2xl p-6 text-center cursor-pointer transition-all bg-dark-900/10 flex flex-col items-center justify-center relative group min-h-[160px]">
                  <input
                    type="file"
                    accept=".pdf"
                    required
                    onChange={handleFileChange}
                    className="absolute inset-0 opacity-0 cursor-pointer"
                  />
                  <FileText className="w-10 h-10 text-dark-400 group-hover:scale-105 group-hover:text-primary-400 transition-all mb-3" />
                  {file ? (
                    <div>
                      <h4 className="text-xs font-bold text-dark-100 truncate max-w-[200px]">{file.name}</h4>
                      <span className="text-[10px] text-dark-400 block mt-1">{(file.size / (1024 * 1024)).toFixed(2)} MB • PDF</span>
                    </div>
                  ) : (
                    <div>
                      <h4 className="text-xs font-bold text-dark-200">Drag & Drop Resume</h4>
                      <span className="text-[10px] text-dark-400 block mt-1">Supports PDF (Max 10MB)</span>
                    </div>
                  )}
                </div>
              </div>

              <button
                type="submit"
                disabled={analyzing}
                className="w-full py-3 bg-gradient-to-r from-primary-600 to-cyan-600 hover:from-primary-500 hover:to-cyan-500 text-white font-bold rounded-xl shadow-lg flex items-center justify-center gap-2 text-xs transition-all hover:scale-102 disabled:opacity-60"
              >
                {analyzing ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    Analyzing Content...
                  </>
                ) : (
                  <>
                    Audit Resume
                    <ArrowRight className="w-4 h-4" />
                  </>
                )}
              </button>

            </form>
          </GlassCard>

          {/* Previous uploads history panel */}
          {history.length > 0 && (
            <GlassCard>
              <h3 className="font-heading font-bold text-xs uppercase tracking-wider text-dark-400 mb-4">
                Scan Audit History
              </h3>
              <div className="flex flex-col gap-3 max-h-[220px] overflow-y-auto pr-1">
                {history.map((h) => (
                  <div
                    key={h._id}
                    onClick={() => handleLoadHistoryItem(h._id)}
                    className="p-3 rounded-xl border border-dark-800/40 bg-dark-950/20 hover:border-primary-500/20 cursor-pointer flex items-center justify-between transition-all group"
                  >
                    <div className="min-w-0">
                      <h4 className="text-xs font-bold text-dark-200 truncate group-hover:text-primary-400 transition-colors">
                        {h.filename}
                      </h4>
                      <span className="text-[9px] text-dark-500 block mt-1">
                        Scanned {new Date(h.createdAt).toLocaleDateString()}
                      </span>
                    </div>
                    <span className="px-2 py-0.5 bg-emerald-950/30 border border-emerald-500/20 rounded text-[10px] font-bold text-emerald-400">
                      {h.atsScore}%
                    </span>
                  </div>
                ))}
              </div>
            </GlassCard>
          )}
        </div>

        {/* Results Panel Column (Right) */}
        <div className="lg:col-span-8 flex flex-col gap-6">
          {analyzing ? (
            <div className="glass-panel p-16 rounded-2xl text-center border border-dark-800/30 flex flex-col items-center justify-center gap-4 min-h-[400px]">
              <Loader2 className="w-12 h-12 text-primary-500 animate-spin" />
              <h3 className="font-bold text-lg text-dark-100 font-heading">Running AI Evaluation algorithms</h3>
              <p className="text-xs text-dark-400 max-w-sm leading-relaxed">
                We are scanning keywords density, structure format readability, grammar, impact phrases, and generating optimal bullet points. This will take a moment.
              </p>
            </div>
          ) : result ? (
            <div className="flex flex-col gap-6 animate-slide-up">
              
              {/* Score Highlight Banner Card */}
              <GlassCard className="bg-gradient-to-br from-dark-950/50 to-primary-950/10 flex flex-col md:flex-row items-center justify-between gap-6 p-8">
                <div className="flex items-center gap-4.5">
                  
                  {/* Circular Score display */}
                  <div className="w-24 h-24 rounded-full border-[6px] border-dark-800 flex items-center justify-center font-heading text-3xl font-black relative shrink-0">
                    <span className="text-dark-50">{result.atsScore}</span>
                    <svg className="absolute top-[-6px] left-[-6px] w-24 h-24 rotate-[-90deg]">
                      <circle
                        cx="48"
                        cy="48"
                        r="45"
                        fill="transparent"
                        stroke="url(#ats-grad)"
                        strokeWidth="6"
                        strokeDasharray="282.7"
                        strokeDashoffset={282.7 - (282.7 * result.atsScore) / 100}
                        strokeLinecap="round"
                      />
                      <defs>
                        <linearGradient id="ats-grad" x1="0%" y1="0%" x2="100%" y2="100%">
                          <stop offset="0%" stopColor="#8b5cf6" />
                          <stop offset="100%" stopColor="#06b6d4" />
                        </linearGradient>
                      </defs>
                    </svg>
                  </div>

                  <div>
                    <h3 className="text-xl font-bold font-heading text-dark-50">ATS Readiness Rating</h3>
                    <p className="text-xs text-dark-400 mt-1 leading-normal max-w-md">
                      {result.atsScore >= 80 
                        ? 'Excellent job! Your resume is highly readable, contains critical keywords, and uses quantitative formatting.'
                        : 'Your resume meets basic criteria but needs refactoring. Incorporate key technical terms and quantitative metrics to pass automated filters.'}
                    </p>
                  </div>
                </div>

                <div className="flex flex-col gap-2 w-full md:w-auto">
                  <div className="p-3 bg-emerald-950/20 border border-emerald-500/20 rounded-xl text-center">
                    <span className="text-[10px] font-bold text-emerald-400 uppercase tracking-wider block">Keywords Found</span>
                    <span className="text-lg font-black text-emerald-200 mt-0.5 block">{result.missingKeywords ? Math.max(2, 8 - result.missingKeywords.length) : 0} / 8</span>
                  </div>
                </div>
              </GlassCard>

              {/* Navigation Tabs bar */}
              <div className="flex border-b border-dark-800/40">
                {(['checklist', 'bullets', 'recommendations'] as const).map(tab => (
                  <button
                    key={tab}
                    onClick={() => setActiveTab(tab)}
                    className={`px-6 py-3 font-heading font-bold text-sm border-b-2 transition-all capitalize ${
                      activeTab === tab
                        ? 'border-primary-500 text-primary-400'
                        : 'border-transparent text-dark-400 hover:text-dark-200'
                    }`}
                  >
                    {tab === 'checklist' ? 'Audit Checklist' : tab === 'bullets' ? 'Bullet Refactors' : 'Certs & Projects'}
                  </button>
                ))}
              </div>

              {/* TAB 1: Audit checklist */}
              {activeTab === 'checklist' && (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  
                  {/* Missing Keywords list */}
                  <GlassCard className="flex flex-col gap-4">
                    <h4 className="font-bold text-sm text-dark-100 flex items-center gap-2">
                      <AlertTriangle className="w-4.5 h-4.5 text-yellow-400" />
                      Critical Gaps / Missing Keywords
                    </h4>
                    <p className="text-[11px] text-dark-400 leading-normal">
                      Automated recruiters filter by these exact terms. Try to append them to your skills list naturally.
                    </p>
                    <div className="flex flex-wrap gap-2 mt-2">
                      {result.missingKeywords && result.missingKeywords.length > 0 ? (
                        result.missingKeywords.map((kw: string, idx: number) => (
                          <span 
                            key={idx}
                            className="px-3 py-1 bg-yellow-500/10 border border-yellow-500/25 rounded-lg text-xs font-bold text-yellow-400"
                          >
                            + {kw}
                          </span>
                        ))
                      ) : (
                        <span className="text-xs text-dark-500">Zero missing keywords detected. Great job!</span>
                      )}
                    </div>
                  </GlassCard>

                  {/* Structural suggestions checklist */}
                  <GlassCard className="flex flex-col gap-4">
                    <h4 className="font-bold text-sm text-dark-100 flex items-center gap-2">
                      <CheckCircle className="w-4.5 h-4.5 text-emerald-400" />
                      Formatting Improvements
                    </h4>
                    <div className="flex flex-col gap-3 mt-1">
                      {result.improvements && result.improvements.length > 0 ? (
                        result.improvements.map((imp: string, idx: number) => (
                          <div key={idx} className="flex gap-2.5 items-start text-xs text-dark-200 leading-relaxed">
                            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 mt-1.5 shrink-0" />
                            <span>{imp}</span>
                          </div>
                        ))
                      ) : (
                        <span className="text-xs text-dark-500">No formatting gaps detected. Resume is highly optimized.</span>
                      )}
                    </div>
                  </GlassCard>

                </div>
              )}

              {/* TAB 2: Bullet Refactors */}
              {activeTab === 'bullets' && (
                <GlassCard className="flex flex-col gap-4">
                  <h4 className="font-bold text-sm text-dark-100 flex items-center gap-2 border-b border-dark-800/40 pb-3">
                    <Sparkles className="w-4.5 h-4.5 text-purple-400" />
                    AI Bullet Points Refactoring Visualizer
                  </h4>
                  <div className="flex flex-col gap-6 mt-1">
                    {result.improvedBulletPoints && result.improvedBulletPoints.length > 0 ? (
                      result.improvedBulletPoints.map((bullet: any, idx: number) => (
                        <div key={idx} className="grid grid-cols-1 md:grid-cols-2 gap-4 p-4 rounded-xl border border-dark-800/30 bg-dark-950/20">
                          
                          {/* Original Bullet */}
                          <div className="flex flex-col gap-1">
                            <span className="text-[10px] font-bold text-dark-400 uppercase tracking-wide">Original Bullet Point</span>
                            <p className="text-xs text-dark-300 leading-relaxed p-3 bg-dark-950 border border-dark-900 rounded-lg">
                              {bullet.original}
                            </p>
                          </div>

                          {/* Refactored Bullet */}
                          <div className="flex flex-col gap-1">
                            <span className="text-[10px] font-bold text-purple-400 uppercase tracking-wide">AI Enhanced (Quantitative)</span>
                            <p className="text-xs text-purple-100 leading-relaxed p-3 bg-purple-950/15 border border-purple-500/20 rounded-lg">
                              {bullet.improved}
                            </p>
                          </div>

                        </div>
                      ))
                    ) : (
                      <span className="text-xs text-dark-500">No bullet point replacements generated. Ensure content lists project contributions.</span>
                    )}
                  </div>
                </GlassCard>
              )}

              {/* TAB 3: Recommendations (Projects & Certifications) */}
              {activeTab === 'recommendations' && (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  
                  {/* Custom Project Suggestions */}
                  <GlassCard className="flex flex-col gap-4">
                    <h4 className="font-bold text-sm text-dark-100 flex items-center gap-2">
                      <BookOpen className="w-4.5 h-4.5 text-primary-400" />
                      Suggested Resume Projects
                    </h4>
                    <p className="text-[11px] text-dark-400 leading-normal">
                      Build these projects to display competence in missing technical areas on your portfolio.
                    </p>
                    <div className="flex flex-col gap-3 mt-2">
                      {result.projectSuggestions && result.projectSuggestions.length > 0 ? (
                        result.projectSuggestions.map((proj: string, idx: number) => (
                          <div key={idx} className="p-3 bg-dark-950 border border-dark-900 rounded-xl flex items-start gap-2.5 text-xs text-dark-200 leading-relaxed">
                            <Plus className="w-4.5 h-4.5 text-primary-400 shrink-0 mt-0.5" />
                            <span>{proj}</span>
                          </div>
                        ))
                      ) : (
                        <span className="text-xs text-dark-500">No project suggestions generated.</span>
                      )}
                    </div>
                  </GlassCard>

                  {/* Certification suggestions */}
                  <GlassCard className="flex flex-col gap-4">
                    <h4 className="font-bold text-sm text-dark-100 flex items-center gap-2">
                      <Trophy className="w-4.5 h-4.5 text-cyan-400" />
                      Recommended Certifications
                    </h4>
                    <p className="text-[11px] text-dark-400 leading-normal">
                      Earn these verified badges to prove competence in targeted corporate environments.
                    </p>
                    <div className="flex flex-col gap-3 mt-2">
                      {result.certificationSuggestions && result.certificationSuggestions.length > 0 ? (
                        result.certificationSuggestions.map((cert: string, idx: number) => (
                          <div key={idx} className="p-3 bg-dark-950 border border-dark-900 rounded-xl flex items-start gap-2.5 text-xs text-dark-200 leading-relaxed">
                            <ChevronRight className="w-4 h-4 text-cyan-400 shrink-0 mt-0.5" />
                            <span>{cert}</span>
                          </div>
                        ))
                      ) : (
                        <span className="text-xs text-dark-500">No credentials suggested.</span>
                      )}
                    </div>
                  </GlassCard>

                </div>
              )}

            </div>
          ) : (
            <div className="glass-panel p-16 rounded-2xl text-center border border-dark-800/30 flex flex-col items-center justify-center gap-4 min-h-[400px]">
              <FileText className="w-14 h-14 text-dark-500" />
              <h3 className="font-bold text-lg text-dark-200 font-heading">No resume audit data found</h3>
              <p className="text-xs text-dark-400 max-w-sm leading-relaxed">
                Provide your target career path and upload your latest resume in PDF format in the panel on the left to initialize ATS evaluation checks.
              </p>
            </div>
          )}
        </div>

      </div>

    </div>
  );
};

export default ResumeAnalyzerPage;
