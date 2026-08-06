import React, { useState, useEffect, useRef } from 'react';
import { 
  Users, Mic, MicOff, Volume2, VolumeX, ArrowRight, Loader2, 
  Send, RefreshCw, Trophy, Play, CheckCircle, HelpCircle, 
  ChevronRight, Terminal, Award
} from 'lucide-react';
import { useSpeech } from '../hooks/useSpeech';
import { useNotification } from '../context/NotificationContext';
import { useAuth } from '../context/AuthContext';
import GlassCard from '../components/GlassCard';
import axios from 'axios';

export const InterviewPrepPage: React.FC = () => {
  const { refreshProfile } = useAuth();
  const { showToast } = useNotification();
  
  const {
    supported: speechSupported,
    isListening,
    transcript,
    setTranscript,
    startListening,
    stopListening,
    speak,
    cancelSpeech
  } = useSpeech();

  const [role, setRole] = useState('');
  const [type, setType] = useState<'technical' | 'hr'>('technical');
  const [starting, setStarting] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  
  // Session details
  const [question, setQuestion] = useState<any>(null);
  const [answer, setAnswer] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [lastEvaluation, setLastEvaluation] = useState<any>(null);
  const [finalReport, setFinalReport] = useState<any>(null);
  const [codeSnippet, setCodeSnippet] = useState('// Type your coding response here\nfunction solveQuestion() {\n  \n}');
  
  const [voiceEnabled, setVoiceEnabled] = useState(true);
  const [history, setHistory] = useState<any[]>([]);

  // Sync transcription from hook
  useEffect(() => {
    if (transcript) {
      setAnswer(prev => prev ? `${prev} ${transcript}` : transcript);
    }
  }, [transcript]);

  // Read question aloud if voice enabled
  useEffect(() => {
    if (question?.question && voiceEnabled) {
      speak(question.question);
    }
    return () => cancelSpeech();
  }, [question, voiceEnabled]);

  const handleStart = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!role.trim()) {
      showToast('Please specify the role you are preparing for', 'error');
      return;
    }

    setStarting(true);
    setFinalReport(null);
    setLastEvaluation(null);
    setHistory([]);
    try {
      const response = await axios.post('/api/interview/start', { type, role });
      setSessionId(response.data.sessionId);
      setQuestion(response.data.nextQuestion);
      setAnswer('');
      showToast('Mock session initialized successfully!', 'success');
    } catch (err) {
      showToast('Could not initialize interview session', 'error');
    } finally {
      setStarting(false);
    }
  };

  const handleSubmitAnswer = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!answer.trim()) {
      showToast('Please type or record an answer response first', 'error');
      return;
    }
    if (!sessionId) return;

    setSubmitting(true);
    cancelSpeech();
    try {
      const payload = type === 'technical' 
        ? `${answer}\n\n[Candidate Code Submission]:\n${codeSnippet}`
        : answer;

      const response = await axios.post(`/api/interview/${sessionId}/answer`, { answer: payload });
      
      setLastEvaluation(response.data.evaluation);
      
      if (response.data.status === 'completed') {
        setFinalReport(response.data.finalReport);
        setQuestion(null);
        showToast('Mock Interview completed! View report details.', 'success');
        await refreshProfile(); // Refresh achievements
      } else {
        setQuestion(response.data.nextQuestion);
        setAnswer('');
        showToast('Answer recorded. Moving to next question.', 'success');
      }
    } catch (err) {
      showToast('Could not submit answer evaluation', 'error');
    } finally {
      setSubmitting(false);
    }
  };

  const handleToggleVoice = () => {
    if (voiceEnabled) {
      cancelSpeech();
    } else if (question?.question) {
      speak(question.question);
    }
    setVoiceEnabled(!voiceEnabled);
  };

  const handleToggleMic = () => {
    if (isListening) {
      stopListening();
    } else {
      startListening();
      showToast('Microphone active. Start speaking...', 'info');
    }
  };

  return (
    <div className="flex flex-col gap-8">
      
      {/* Page Header */}
      <div className="border-b border-dark-800/40 pb-6 flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h2 className="text-3xl font-extrabold font-heading text-dark-50 tracking-tight flex items-center gap-2">
            <Users className="w-8 h-8 text-primary-400" />
            Mock Interview Simulator
          </h2>
          <p className="text-sm text-dark-400 mt-1">
            Rehearse corporate screening loops, receive AI feedback critiques, and speak inputs natively.
          </p>
        </div>
        {sessionId && !finalReport && (
          <button
            onClick={handleToggleVoice}
            className={`px-4 py-2 border rounded-xl text-xs font-bold transition-all flex items-center gap-2 ${
              voiceEnabled 
                ? 'bg-primary-950/20 border-primary-500/30 text-primary-400' 
                : 'bg-dark-900/50 border-dark-800 text-dark-400'
            }`}
          >
            {voiceEnabled ? <Volume2 className="w-4 h-4" /> : <VolumeX className="w-4 h-4" />}
            AI Audio Voice: {voiceEnabled ? 'ON' : 'OFF'}
          </button>
        )}
      </div>

      {/* WORKSPACE AREA */}
      {!sessionId ? (
        
        /* Step 1: Config and Setup Form */
        <div className="max-w-xl mx-auto w-full animate-slide-up">
          <GlassCard className="p-8">
            <h3 className="font-heading font-bold text-lg text-dark-100 mb-6 flex items-center gap-2">
              <Play className="w-5 h-5 text-cyan-400" />
              Configure Session
            </h3>

            <form onSubmit={handleStart} className="flex flex-col gap-5">
              
              {/* Select role name */}
              <div className="flex flex-col gap-1.5">
                <label className="text-xs font-bold text-dark-300">Target Career Position</label>
                <input
                  type="text"
                  required
                  value={role}
                  onChange={(e) => setRole(e.target.value)}
                  placeholder="e.g. Full Stack Engineer"
                  className="w-full px-4 py-3 rounded-xl border glass-input text-sm text-dark-100"
                />
              </div>

              {/* Select Interview loop type */}
              <div className="flex flex-col gap-1.5">
                <label className="text-xs font-bold text-dark-300">Interview Loop Category</label>
                <div className="grid grid-cols-2 gap-4">
                  
                  <div
                    onClick={() => setType('technical')}
                    className={`p-4 rounded-xl border cursor-pointer transition-all text-center flex flex-col gap-1.5 ${
                      type === 'technical'
                        ? 'border-primary-500 bg-primary-950/20 text-primary-300'
                        : 'border-dark-800 bg-dark-950/20 text-dark-400 hover:border-dark-700'
                    }`}
                  >
                    <span className="font-heading font-bold text-sm block">Technical Round</span>
                    <span className="text-[10px] opacity-75">Coding challenges, designs, and queries</span>
                  </div>

                  <div
                    onClick={() => setType('hr')}
                    className={`p-4 rounded-xl border cursor-pointer transition-all text-center flex flex-col gap-1.5 ${
                      type === 'hr'
                        ? 'border-primary-500 bg-primary-950/20 text-primary-300'
                        : 'border-dark-800 bg-dark-950/20 text-dark-400 hover:border-dark-700'
                    }`}
                  >
                    <span className="font-heading font-bold text-sm block">HR Behavioral</span>
                    <span className="text-[10px] opacity-75">Cultural matches, scenarios, and values</span>
                  </div>

                </div>
              </div>

              <button
                type="submit"
                disabled={starting}
                className="w-full py-3.5 bg-gradient-to-r from-primary-600 to-cyan-600 hover:from-primary-500 hover:to-cyan-500 text-white font-bold rounded-xl shadow-lg flex items-center justify-center gap-2 text-sm transition-all hover:scale-102 disabled:opacity-60"
              >
                {starting ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    Starting Loop...
                  </>
                ) : (
                  <>
                    Begin Mock Interview
                    <ArrowRight className="w-4 h-4" />
                  </>
                )}
              </button>

            </form>
          </GlassCard>
        </div>

      ) : finalReport ? (

        /* Step 3: Complete Interview Evaluation Report Panel */
        <div className="flex flex-col gap-8 animate-slide-up">
          
          <GlassCard className="bg-gradient-to-br from-dark-950/60 to-indigo-950/15 p-8 border border-yellow-500/20 relative">
            <div className="absolute top-4 right-4 bg-yellow-500/10 text-yellow-400 border border-yellow-500/30 px-3 py-1 rounded-full text-xs font-bold flex items-center gap-1">
              <Award className="w-4 h-4 animate-bounce" /> Unlocked "Interview Explorer"
            </div>
            
            <div className="flex flex-col md:flex-row items-center gap-8">
              {/* Circular aggregate rating score */}
              <div className="w-32 h-32 rounded-full border-[8px] border-dark-800 flex flex-col items-center justify-center font-heading relative shrink-0">
                <span className="text-3xl font-black text-dark-50">{finalReport.overallScore}</span>
                <span className="text-[10px] font-bold text-dark-400 mt-1 uppercase tracking-widest">Average</span>
                <svg className="absolute top-[-8px] left-[-8px] w-32 h-32 rotate-[-90deg]">
                  <circle
                    cx="64"
                    cy="64"
                    r="60"
                    fill="transparent"
                    stroke="#eab308"
                    strokeWidth="8"
                    strokeDasharray="377"
                    strokeDashoffset={377 - (377 * finalReport.overallScore) / 10}
                    strokeLinecap="round"
                  />
                </svg>
              </div>

              <div>
                <h3 className="text-2xl font-bold font-heading text-dark-50">Evaluation Report: {role}</h3>
                <p className="text-xs text-dark-400 mt-1.5 leading-relaxed max-w-xl">
                  You have completed the mock {type} loop. Review your structured communication advice, overall sentiment score, and transcripts below to identify preparation gaps.
                </p>
                <div className="flex items-center gap-4 mt-4">
                  <div className="text-xs">
                    <span className="text-dark-400 block font-semibold uppercase text-[9px] tracking-wider">Communication Sentiment</span>
                    <span className="text-sm font-bold text-cyan-400 mt-0.5 block">{finalReport.confidenceScore}% (Confident)</span>
                  </div>
                </div>
              </div>
            </div>
          </GlassCard>

          <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-start">
            
            {/* Communication advice tips list */}
            <div className="lg:col-span-4">
              <GlassCard className="flex flex-col gap-4">
                <h4 className="font-bold text-sm text-dark-100 flex items-center gap-2 border-b border-dark-800/40 pb-3">
                  <CheckCircle className="w-4.5 h-4.5 text-cyan-400" />
                  Key Placement Tips
                </h4>
                <div className="flex flex-col gap-4.5">
                  {finalReport.communicationTips.map((tip: string, idx: number) => (
                    <div key={idx} className="flex gap-3 items-start text-xs text-dark-200 leading-relaxed">
                      <span className="w-5 h-5 rounded-full bg-cyan-950/20 text-cyan-400 flex items-center justify-center font-bold text-[10px] shrink-0 mt-0.5">
                        {idx + 1}
                      </span>
                      <span>{tip}</span>
                    </div>
                  ))}
                </div>
              </GlassCard>
            </div>

            {/* Questions Transcript History list */}
            <div className="lg:col-span-8 flex flex-col gap-6">
              <h3 className="font-heading font-bold text-base text-dark-100 uppercase tracking-wider">
                Full Dialogue Transcript
              </h3>
              {finalReport.questions.map((q: any, idx: number) => (
                <GlassCard key={q.id || idx} className="flex flex-col gap-4">
                  
                  {/* Question and score */}
                  <div className="flex justify-between items-start gap-4">
                    <h4 className="font-bold text-sm text-dark-100">
                      Question {idx + 1}: {q.question}
                    </h4>
                    <span className="px-2 py-0.5 bg-yellow-500/10 border border-yellow-500/25 rounded text-[10px] font-black text-yellow-400 shrink-0">
                      Score: {q.score} / 10
                    </span>
                  </div>

                  {/* Answer response */}
                  <div className="flex flex-col gap-1 bg-dark-950/30 p-3 rounded-xl border border-dark-900/50">
                    <span className="text-[9px] text-dark-500 uppercase tracking-widest font-bold">Your Response</span>
                    <p className="text-xs text-dark-300 whitespace-pre-wrap leading-relaxed mt-1">
                      {q.userAnswer}
                    </p>
                  </div>

                  {/* AI feedback critique */}
                  <div className="flex flex-col gap-1 bg-primary-950/10 p-3 rounded-xl border border-primary-500/10">
                    <span className="text-[9px] text-primary-400 uppercase tracking-widest font-bold">Critique & Feedback</span>
                    <p className="text-xs text-primary-200 leading-relaxed mt-1">
                      {q.feedback}
                    </p>
                  </div>

                </GlassCard>
              ))}

              <button
                onClick={() => setSessionId(null)}
                className="py-3 bg-dark-900 hover:bg-dark-800 border border-dark-800 text-dark-300 font-bold rounded-xl text-xs flex items-center justify-center gap-2 transition-all hover:scale-102"
              >
                <RefreshCw className="w-4 h-4" />
                Start a New Mock loop
              </button>
            </div>

          </div>

        </div>

      ) : (
        
        /* Step 2: Active Interview Loop Panel */
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-start animate-slide-up">
          
          {/* Question panel and recording box */}
          <div className={`${type === 'technical' ? 'lg:col-span-7' : 'lg:col-span-12'} flex flex-col gap-6`}>
            <GlassCard className="flex flex-col gap-5 p-7">
              <div className="flex items-center justify-between border-b border-dark-800/40 pb-3">
                <span className="text-xs font-bold text-primary-400 uppercase tracking-widest">
                  Question {question.number} of {INTERVIEW_LENGTH}
                </span>
                <span className="px-2 py-0.5 bg-dark-900 border border-dark-800 rounded text-[10px] text-dark-400">
                  Loop: {type.toUpperCase()}
                </span>
              </div>

              {/* Big question container */}
              <div className="p-4 rounded-2xl bg-dark-900/40 border border-dark-800/50 relative overflow-hidden">
                <p className="text-sm font-bold text-dark-100 leading-relaxed relative z-10">
                  {question.question}
                </p>
              </div>

              {/* Real-time Answer critique helper widget */}
              {lastEvaluation && (
                <div className="p-4 rounded-2xl bg-emerald-950/15 border border-emerald-500/25 flex flex-col gap-1.5 animate-slide-up">
                  <div className="flex justify-between items-center">
                    <span className="text-[10px] font-bold text-emerald-400 uppercase tracking-wider">
                      Last Answer Critique Score: {lastEvaluation.score}/10
                    </span>
                  </div>
                  <p className="text-xs text-emerald-200/90 leading-relaxed">{lastEvaluation.feedback}</p>
                  <p className="text-[10px] text-cyan-300 font-semibold mt-1">💡 Tip: {lastEvaluation.communicationTip}</p>
                </div>
              )}

              {/* Form Input answer details */}
              <form onSubmit={handleSubmitAnswer} className="flex flex-col gap-4">
                <div className="flex flex-col gap-1.5">
                  <div className="flex justify-between items-center">
                    <label className="text-xs font-bold text-dark-300">Answer Response</label>
                    <span className="text-[10px] text-dark-500">Record voice or type below</span>
                  </div>
                  <textarea
                    required
                    value={answer}
                    onChange={(e) => setAnswer(e.target.value)}
                    rows={type === 'technical' ? 4 : 6}
                    placeholder="Provide your structured response..."
                    className="w-full px-4 py-3 rounded-xl border glass-input text-xs text-dark-100 resize-none leading-relaxed"
                  />
                </div>

                {/* Submitting controls buttons */}
                <div className="flex items-center justify-between gap-4 mt-2">
                  <button
                    type="button"
                    onClick={handleToggleMic}
                    disabled={!speechSupported}
                    className={`px-5 py-3 rounded-xl border text-xs font-bold flex items-center gap-2 transition-all hover:scale-102 ${
                      isListening
                        ? 'bg-rose-950/20 border-rose-500/30 text-rose-400 ring-2 ring-rose-500/25 animate-pulse'
                        : 'bg-dark-900 border-dark-800 text-dark-300 hover:border-dark-700'
                    }`}
                  >
                    {isListening ? <MicOff className="w-4 h-4" /> : <Mic className="w-4 h-4" />}
                    {isListening ? 'Stop Mic' : 'Record Voice'}
                  </button>

                  <button
                    type="submit"
                    disabled={submitting}
                    className="px-6 py-3 bg-gradient-to-r from-primary-600 to-cyan-600 hover:from-primary-500 hover:to-cyan-500 text-white font-bold rounded-xl shadow-lg flex items-center justify-center gap-2 text-xs transition-all hover:scale-102 disabled:opacity-60"
                  >
                    {submitting ? (
                      <>
                        <Loader2 className="w-4 h-4 animate-spin" />
                        Evaluating...
                      </>
                    ) : (
                      <>
                        Submit Response
                        <Send className="w-4 h-4" />
                      </>
                    )}
                  </button>
                </div>
              </form>

            </GlassCard>
          </div>

          {/* Technical code sandbox stub (Right) */}
          {type === 'technical' && (
            <div className="lg:col-span-5 flex flex-col gap-6">
              <GlassCard className="flex flex-col gap-4 font-mono text-xs text-slate-300">
                <div className="flex items-center justify-between border-b border-dark-800/40 pb-2.5">
                  <span className="text-[10px] text-slate-400 flex items-center gap-1.5 font-bold uppercase tracking-wider font-sans">
                    <Terminal className="w-4.5 h-4.5 text-cyan-400" />
                    Sandbox Code Playground
                  </span>
                  <div className="flex gap-1.5">
                    <span className="w-2 h-2 rounded-full bg-rose-500" />
                    <span className="w-2 h-2 rounded-full bg-yellow-500" />
                    <span className="w-2 h-2 rounded-full bg-emerald-500" />
                  </div>
                </div>
                <textarea
                  value={codeSnippet}
                  onChange={(e) => setCodeSnippet(e.target.value)}
                  rows={15}
                  className="w-full bg-[#080a10] border border-slate-900 rounded-xl p-4 text-[11px] text-cyan-400 code-editor-stub outline-none resize-none leading-relaxed"
                />
                <span className="text-[9px] text-slate-500 font-sans block">
                  * Note: Code submitted inside this editor will be attached to your response for technical AI checks.
                </span>
              </GlassCard>
            </div>
          )}

        </div>

      )}

    </div>
  );
};

export default InterviewPrepPage;
