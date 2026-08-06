import React, { useState, useEffect } from 'react';
import api from '../services/api';
import { 
  FiCheckCircle, FiAlertTriangle, FiBookOpen, 
  FiArrowRight, FiSmile, FiFileText, FiRefreshCw, FiClock 
} from 'react-icons/fi';

const Grammar = () => {
  const [text, setText] = useState('');
  const [tone, setTone] = useState('Professional');
  const [result, setResult] = useState(null);
  const [history, setHistory] = useState([]);
  const [checking, setChecking] = useState(false);
  const [loadingHistory, setLoadingHistory] = useState(true);
  const [error, setError] = useState('');

  // Extended Tone Selection Categories
  const tones = [
    { name: 'Professional', desc: 'Sleek & polished business language' },
    { name: 'Formal', desc: 'Highly polite, structured tone' },
    { name: 'Friendly', desc: 'Warm, engaging & personal style' },
    { name: 'Academic', desc: 'Rigorous, thesis-level phrasing' },
    { name: 'Casual', desc: 'Conversational, relaxed dialogue' }
  ];

  useEffect(() => {
    fetchHistory();
  }, []);

  const fetchHistory = async () => {
    try {
      const res = await api.get('/grammar/history');
      setHistory(res.data);
    } catch (err) {
      console.error("Failed to load grammar history", err);
    } finally {
      setLoadingHistory(false);
    }
  };

  const handleCheckGrammar = async (e) => {
    e.preventDefault();
    if (!text.trim()) return;

    setChecking(true);
    setError('');
    setResult(null);

    try {
      const res = await api.post('/grammar/check', { text, tone });
      setResult(res.data);
      fetchHistory(); // Refresh history log
    } catch (err) {
      console.error("Grammar check error", err);
      setError("AI was unable to process this grammar check. Please try again.");
    } finally {
      setChecking(false);
    }
  };

  const loadFromHistory = (item) => {
    setText(item.originalText);
    setTone(item.tone);
    setResult({
      originalText: item.originalText,
      correctedText: item.correctedText,
      explanations: item.explanations,
      tone: item.tone
    });
  };

  return (
    <div className="space-y-6 text-left">
      <div>
        <h1 className="text-3xl font-extrabold tracking-tight text-gray-900 dark:text-white bg-gradient-to-r from-primary-600 to-violet-600 bg-clip-text text-transparent dark:from-primary-400 dark:to-violet-400">
          AI Grammar Audit
        </h1>
        <p className="mt-1 text-sm text-gray-500 dark:text-slate-400">
          Paste your writing, select a target communication tone, and let AI identify errors and offer polish.
        </p>
      </div>

      {error && (
        <div className="flex items-center gap-3 rounded-lg bg-red-50 dark:bg-red-950/20 border border-red-200 dark:border-red-800/30 p-4 text-sm text-red-800 dark:text-red-400">
          <FiAlertTriangle className="h-5 w-5 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* Input/Editor Section */}
        <div className="lg:col-span-2 space-y-6">
          <div className="glass-panel p-6 rounded-2xl shadow-xl bg-white/40 dark:bg-slate-900/30">
            <form onSubmit={handleCheckGrammar} className="space-y-5">
              
              {/* Text Input area */}
              <div>
                <label className="block text-xs font-bold text-gray-700 dark:text-slate-350 mb-2 uppercase tracking-wide">
                  Paste your sentence or paragraph
                </label>
                <textarea
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                  rows={6}
                  maxLength={1000}
                  className="w-full p-4 border border-gray-200 dark:border-slate-800 rounded-xl bg-white dark:bg-slate-950 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500/20 dark:text-white"
                  placeholder="E.g. I wants to learns english because it is interesting language..."
                  required
                />
                <div className="flex justify-between mt-1 text-[10px] text-gray-400">
                  <span>Max 1000 characters</span>
                  <span>{text.length}/1000</span>
                </div>
              </div>

              {/* Tone Selection Group */}
              <div>
                <label className="block text-xs font-bold text-gray-700 dark:text-slate-350 mb-2 uppercase tracking-wide">
                  Communication Style Tone
                </label>
                <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-3">
                  {tones.map((t) => (
                    <div
                      key={t.name}
                      onClick={() => setTone(t.name)}
                      className={`p-3 rounded-xl border text-left cursor-pointer transition active:scale-[0.98] ${
                        tone === t.name
                          ? 'border-primary-500 bg-primary-500/10 text-primary-900 dark:text-primary-400 font-bold shadow-sm'
                          : 'border-gray-200 dark:border-slate-800/80 hover:bg-gray-50/50 dark:hover:bg-slate-800/10'
                      }`}
                    >
                      <p className="text-xs font-bold text-gray-800 dark:text-white">{t.name}</p>
                      <p className="text-[9px] text-gray-400 mt-1">{t.desc}</p>
                    </div>
                  ))}
                </div>
              </div>

              {/* Submit */}
              <button
                type="submit"
                disabled={checking || !text.trim()}
                className="w-full flex items-center justify-center gap-2 bg-gradient-to-r from-primary-600 to-violet-600 hover:from-primary-500 hover:to-violet-500 text-white py-3.5 px-4 rounded-xl text-sm font-semibold active:scale-[0.98] transition-all disabled:opacity-50 disabled:cursor-not-allowed shadow-lg shadow-primary-500/10"
              >
                {checking ? (
                  <>
                    <FiRefreshCw className="animate-spin" /> Checking writing style...
                  </>
                ) : (
                  <>
                    Run Grammar Audit <FiArrowRight />
                  </>
                )}
              </button>

            </form>
          </div>

          {/* Results section */}
          {result && (
            <div className="glass-panel p-6 rounded-2xl shadow-xl space-y-6 bg-white/40 dark:bg-slate-900/30 animate-fade-in">
              <h3 className="text-sm font-extrabold text-gray-900 dark:text-white border-b border-gray-150 dark:border-slate-805 pb-3">
                Audit Feedback Logs
              </h3>

              {/* Corrected Text Pane */}
              <div className="space-y-2 text-left">
                <p className="text-xs font-bold text-gray-400 uppercase tracking-wider">Polished Output ({result.tone})</p>
                <div className={`p-4 rounded-xl border text-xs leading-relaxed font-medium ${
                  result.explanations && result.explanations.length > 0 
                    ? 'bg-green-500/5 dark:bg-green-950/10 border-green-200/50 dark:border-green-800/30 text-green-950 dark:text-green-300' 
                    : 'bg-blue-500/5 dark:bg-blue-950/10 border-blue-200/50 dark:border-blue-800/30 text-blue-950 dark:text-blue-300'
                }`}>
                  {result.correctedText}
                </div>
              </div>

              {/* Explanations List */}
              <div className="space-y-4">
                <p className="text-xs font-bold text-gray-400 uppercase tracking-wider text-left">Identified Corrections ({result.explanations ? result.explanations.length : 0})</p>
                {result.explanations && result.explanations.length > 0 ? (
                  <div className="space-y-3">
                    {result.explanations.map((exp, i) => (
                      <div key={i} className="p-4 rounded-xl bg-white/40 dark:bg-slate-900/60 border border-gray-200 dark:border-slate-800 text-left space-y-2">
                        <div className="flex items-center gap-3 flex-wrap text-xs">
                          <span className="line-through text-red-500 font-medium px-1.5 py-0.5 rounded bg-red-500/5 dark:bg-red-950/20 border border-red-500/10">
                            {exp.mistake}
                          </span>
                          <FiArrowRight className="text-gray-400" />
                          <span className="text-green-600 dark:text-green-400 font-bold px-1.5 py-0.5 rounded bg-green-500/5 dark:bg-green-950/20 border border-green-500/10">
                            {exp.correction}
                          </span>
                        </div>
                        <p className="text-xs text-gray-500 dark:text-slate-400 font-medium pl-2.5 border-l-2 border-primary-500">
                          {exp.explanation}
                        </p>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="flex items-center gap-3 p-4 rounded-xl bg-blue-500/5 dark:bg-slate-900/40 border border-blue-250 dark:border-slate-800 text-blue-800 dark:text-blue-400 text-xs font-medium">
                    <FiCheckCircle className="h-5 w-5 shrink-0 text-blue-500" />
                    <span>Your text is flawless! No grammar mistakes were detected.</span>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>

        {/* History Sidebar Panel (Right) */}
        <div className="lg:col-span-1 space-y-6">
          <div className="glass-panel p-6 rounded-2xl shadow-xl flex flex-col h-[500px] bg-white/40 dark:bg-slate-900/30">
            <h3 className="text-base font-bold text-gray-900 dark:text-white mb-4 flex items-center gap-2 border-b border-gray-100 dark:border-slate-800 pb-3">
              <FiClock className="text-primary-600 dark:text-primary-400" /> Past Corrections
            </h3>

            <div className="flex-1 overflow-y-auto divide-y divide-gray-100 dark:divide-slate-850/50 pr-1">
              {loadingHistory ? (
                <div className="flex justify-center py-10">
                  <div className="h-6 w-6 animate-spin rounded-full border-2 border-t-primary-600 border-primary-100"></div>
                </div>
              ) : history.length === 0 ? (
                <p className="text-xs text-gray-400 py-10 text-center font-medium">No corrections on record.</p>
              ) : (
                history.map((item) => (
                  <div
                    key={item.id}
                    onClick={() => loadFromHistory(item)}
                    className="p-3 text-left hover:bg-gray-100/50 dark:hover:bg-slate-900/10 cursor-pointer transition rounded-xl my-1.5 border border-transparent hover:border-gray-200/20"
                  >
                    <p className="text-xs font-bold text-gray-850 dark:text-slate-200 truncate">
                      {item.originalText}
                    </p>
                    <div className="flex justify-between items-center mt-2 text-[9px] text-gray-400">
                      <span className="font-bold text-primary-500 uppercase">{item.tone}</span>
                      <span>{new Date(item.createdAt).toLocaleDateString()}</span>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>

      </div>
    </div>
  );
};

export default Grammar;
