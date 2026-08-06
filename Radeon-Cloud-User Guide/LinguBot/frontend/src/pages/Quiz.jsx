import React, { useState, useEffect } from 'react';
import api from '../services/api';
import { 
  FiBookOpen, FiClock, FiCheckCircle, FiXCircle, 
  FiAward, FiArrowRight, FiArrowLeft, FiAlertTriangle, FiZap, FiRefreshCw
} from 'react-icons/fi';

const Quiz = () => {
  // States for Configuration
  const [category, setCategory] = useState('Vocabulary');
  const [difficulty, setDifficulty] = useState('Medium');
  const [count, setCount] = useState(5);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  // States for Active Quiz
  const [activeQuiz, setActiveQuiz] = useState(null);
  const [currentQuestionIdx, setCurrentQuestionIdx] = useState(0);
  const [answers, setAnswers] = useState({}); // questionId -> selectedOption/text
  const [timeLeft, setTimeLeft] = useState(0); // in seconds
  const [timeTaken, setTimeTaken] = useState(0);
  const [isSubmitting, setIsSubmitting] = useState(false);

  // States for Results
  const [result, setResult] = useState(null);

  // States for History
  const [attempts, setAttempts] = useState([]);
  const [loadingHistory, setLoadingHistory] = useState(true);

  const categories = ['Vocabulary', 'Grammar', 'Common Verbs', 'Greetings', 'Phrasal Verbs'];
  const difficulties = ['Easy', 'Medium', 'Hard'];

  useEffect(() => {
    fetchAttempts();
  }, []);

  // Timer logic for active quiz
  useEffect(() => {
    if (activeQuiz && timeLeft > 0 && !result) {
      const tid = setTimeout(() => {
        setTimeLeft(prev => prev - 1);
        setTimeTaken(prev => prev + 1);
      }, 1000);
      return () => clearTimeout(tid);
    } else if (activeQuiz && timeLeft === 0 && !result) {
      handleSubmitQuiz();
    }
  }, [timeLeft, activeQuiz, result]);

  const fetchAttempts = async () => {
    try {
      const res = await api.get('/quizzes/attempts');
      setAttempts(res.data);
    } catch (err) {
      console.error("Failed to fetch quiz attempts", err);
    } finally {
      setLoadingHistory(false);
    }
  };

  const handleGenerateQuiz = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError('');
    setResult(null);
    setAnswers({});
    setCurrentQuestionIdx(0);
    setTimeTaken(0);

    try {
      const res = await api.post('/quizzes/generate', {
        category,
        difficulty,
        questionCount: count
      });
      setActiveQuiz(res.data);
      setTimeLeft(res.data.timeLimit * 60);
    } catch (err) {
      console.error("Quiz generation failed", err);
      setError(err.response?.data?.message || "Failed to generate quiz. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  const handleSelectAnswer = (questionId, optionValue) => {
    setAnswers({
      ...answers,
      [questionId]: optionValue
    });
  };

  const parseMatchPairs = (matchStr) => {
    const map = {};
    if (!matchStr) return map;
    matchStr.split('|').forEach(p => {
      const kv = p.split('=');
      if (kv.length === 2) map[kv[0].trim()] = kv[1].trim();
    });
    return map;
  };

  const handleMatchChange = (qId, leftItem, selectedRight) => {
    const currentMapping = parseMatchPairs(answers[qId] || '');
    
    if (selectedRight) {
      currentMapping[leftItem] = selectedRight;
    } else {
      delete currentMapping[leftItem];
    }
    
    const answerStr = Object.entries(currentMapping)
      .map(([l, r]) => `${l}=${r}`)
      .join('|');
      
    handleSelectAnswer(qId, answerStr);
  };

  const handleSubmitQuiz = async () => {
    if (!activeQuiz || isSubmitting) return;

    setIsSubmitting(true);
    try {
      const res = await api.post(`/quizzes/${activeQuiz.id}/submit`, {
        answers,
        timeTaken
      });
      setResult(res.data);
      fetchAttempts();
    } catch (err) {
      console.error("Quiz submission error", err);
      setError("Failed to grade your quiz. Please try again.");
    } finally {
      setIsSubmitting(false);
    }
  };

  const loadPastAttempt = async (attemptItem) => {
    setLoading(true);
    setError('');
    try {
      const quizRes = await api.get(`/quizzes/${attemptItem.quizId}`);
      setActiveQuiz(quizRes.data);
      
      const correctAnswersMap = {};
      quizRes.data.questions.forEach(q => {
        correctAnswersMap[q.id] = q.correctAnswer;
      });

      setAnswers(attemptItem.answers);
      setResult({
        attemptId: attemptItem.id,
        quizId: attemptItem.quizId,
        score: attemptItem.score,
        maxScore: attemptItem.maxScore,
        percentage: attemptItem.percentage,
        correctCount: (attemptItem.score / 10), 
        totalCount: quizRes.data.questions.length,
        passed: attemptItem.percentage >= 60.0,
        xpEarned: attemptItem.score * 2,
        unlockedBadges: [],
        unlockedAchievements: [],
        correctAnswers: correctAnswersMap
      });
    } catch (err) {
      console.error("Failed to load past attempt details", err);
      setError("Unable to recover quiz details for this review.");
    } finally {
      setLoading(false);
    }
  };

  const formatTime = (secs) => {
    const mins = Math.floor(secs / 60);
    const remainingSecs = secs % 60;
    return `${mins}:${remainingSecs < 10 ? '0' : ''}${remainingSecs}`;
  };

  // Get current active question and shuffle list
  const currentQuestion = activeQuiz?.questions[currentQuestionIdx];

  // Memoize shuffled match choices for the current Match question
  const shuffledRightChoices = React.useMemo(() => {
    if (!currentQuestion || currentQuestion.type !== 'MATCH') return [];
    const pairs = currentQuestion.correctAnswer.split('|');
    const rights = pairs.map(p => p.split('=')[1]);
    return [...rights].sort(() => Math.random() - 0.5);
  }, [currentQuestion]);

  return (
    <div className="space-y-6 text-left">
      <div>
        <h1 className="text-3xl font-extrabold tracking-tight text-gray-900 dark:text-white bg-gradient-to-r from-primary-600 to-violet-600 bg-clip-text text-transparent dark:from-primary-400 dark:to-violet-400">
          AI Quiz Generator
        </h1>
        <p className="mt-1 text-sm text-gray-500 dark:text-slate-400">
          Challenge yourself with custom language quizzes generated by AI.
        </p>
      </div>

      {error && (
        <div className="flex items-center gap-3 rounded-lg bg-red-50 dark:bg-red-950/20 border border-red-200 dark:border-red-800/30 p-4 text-sm text-red-850 dark:text-red-400">
          <FiAlertTriangle className="h-5 w-5 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Main Grid: Quiz Area & History */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        
        {/* Main Quiz Area (2 cols) */}
        <div className="lg:col-span-2 space-y-6">
          
          {/* STATE 1: Configuration Form */}
          {!activeQuiz && !result && (
            <div className="glass-panel p-6 rounded-2xl shadow-xl text-left bg-white/40 dark:bg-slate-900/30">
              <h3 className="text-lg font-bold text-gray-900 dark:text-white border-b border-gray-100 dark:border-slate-800 pb-3 mb-5">
                Quiz Customizer
              </h3>
              
              <form onSubmit={handleGenerateQuiz} className="space-y-6">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div>
                    <label className="block text-xs font-bold text-gray-700 dark:text-slate-350 mb-2 uppercase tracking-wide">
                      Topic Category
                    </label>
                    <select
                      value={category}
                      onChange={(e) => setCategory(e.target.value)}
                      className="w-full p-3 border border-gray-200 dark:border-slate-800 rounded-xl bg-white dark:bg-slate-950 text-sm text-gray-700 dark:text-slate-300 focus:ring-2 focus:ring-primary-500/20 focus:outline-none"
                    >
                      {categories.map(c => <option key={c} value={c}>{c}</option>)}
                    </select>
                  </div>

                  <div>
                    <label className="block text-xs font-bold text-gray-700 dark:text-slate-350 mb-2 uppercase tracking-wide">
                      Difficulty Level
                    </label>
                    <select
                      value={difficulty}
                      onChange={(e) => setDifficulty(e.target.value)}
                      className="w-full p-3 border border-gray-200 dark:border-slate-800 rounded-xl bg-white dark:bg-slate-950 text-sm text-gray-700 dark:text-slate-300 focus:ring-2 focus:ring-primary-500/20 focus:outline-none"
                    >
                      {difficulties.map(d => <option key={d} value={d}>{d}</option>)}
                    </select>
                  </div>
                </div>

                <div>
                  <label className="block text-xs font-bold text-gray-700 dark:text-slate-355 mb-2 uppercase tracking-wide">
                    Number of Questions
                  </label>
                  <div className="flex items-center gap-3">
                    {[5, 10, 15].map((num) => (
                      <button
                        key={num}
                        type="button"
                        onClick={() => setCount(num)}
                        className={`flex-1 py-2.5 rounded-xl border text-sm font-bold transition active:scale-[0.98] ${
                          count === num
                            ? 'border-primary-500 bg-primary-500/10 text-primary-600 dark:text-primary-400 font-extrabold'
                            : 'border-gray-200 dark:border-slate-800 hover:bg-gray-50/50 dark:hover:bg-slate-800/20 text-gray-600 dark:text-slate-400'
                        }`}
                      >
                        {num} Questions
                      </button>
                    ))}
                  </div>
                </div>

                <button
                  type="submit"
                  disabled={loading}
                  className="w-full flex items-center justify-center gap-2 bg-gradient-to-r from-primary-600 to-violet-600 hover:from-primary-500 hover:to-violet-500 text-white py-3.5 px-4 rounded-xl text-sm font-semibold active:scale-[0.98] transition-all disabled:opacity-50 disabled:cursor-not-allowed shadow-lg shadow-primary-500/10"
                >
                  {loading ? (
                    <div className="flex items-center gap-2">
                      <FiRefreshCw className="animate-spin h-4 w-4" />
                      Creating AI Quiz...
                    </div>
                  ) : (
                    <>
                      Generate AI Quiz <FiArrowRight />
                    </>
                  )}
                </button>
              </form>
            </div>
          )}

          {/* STATE 2: Active Testing Session */}
          {activeQuiz && !result && currentQuestion && (
            <div className="glass-panel p-6 rounded-2xl shadow-xl space-y-6 text-left bg-white/40 dark:bg-slate-900/30">
              
              {/* Header Timer */}
              <div className="flex items-center justify-between border-b border-gray-200/50 dark:border-slate-800/80 pb-4">
                <div>
                  <h3 className="text-base font-extrabold text-gray-900 dark:text-white truncate max-w-[250px]">
                    {activeQuiz.title}
                  </h3>
                  <p className="text-[10px] text-gray-400 uppercase font-semibold">
                    {activeQuiz.category} • {activeQuiz.difficulty}
                  </p>
                </div>

                <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-red-500/10 text-red-600 dark:text-red-400 border border-red-500/20">
                  <FiClock className="h-4 w-4 shrink-0" />
                  <span className="text-sm font-extrabold font-mono">{formatTime(timeLeft)}</span>
                </div>
              </div>

              {/* Progress Bar */}
              <div className="w-full bg-gray-100 dark:bg-slate-800 h-2 rounded-full overflow-hidden">
                <div
                  className="bg-gradient-to-r from-primary-500 to-indigo-500 h-2 transition-all duration-300"
                  style={{ width: `${((currentQuestionIdx + 1) / activeQuiz.questions.length) * 100}%` }}
                ></div>
              </div>

              {/* Question Text */}
              <div className="space-y-4">
                <div className="text-xs font-bold text-gray-400 uppercase tracking-widest">
                  Question {currentQuestionIdx + 1} of {activeQuiz.questions.length} ({currentQuestion.type})
                </div>
                <h4 className="text-lg font-bold text-gray-900 dark:text-white">
                  {currentQuestion.questionText}
                </h4>

                {/* Input Options rendering based on type */}
                <div className="space-y-3 mt-4">
                  {currentQuestion.type === 'FILL_IN_BLANKS' ? (
                    <input
                      type="text"
                      value={answers[currentQuestion.id] || ''}
                      onChange={(e) => handleSelectAnswer(currentQuestion.id, e.target.value)}
                      placeholder="Type your answer here..."
                      className="w-full p-4 border border-gray-250 dark:border-slate-800 rounded-xl bg-white dark:bg-slate-950 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500/20 dark:text-white"
                    />
                  ) : currentQuestion.type === 'TRUE_FALSE' ? (
                    <div className="flex gap-4">
                      {['True', 'False'].map((option) => (
                        <button
                          key={option}
                          type="button"
                          onClick={() => handleSelectAnswer(currentQuestion.id, option)}
                          className={`flex-1 py-3.5 rounded-xl border text-sm font-bold active:scale-[0.98] transition-all ${
                            answers[currentQuestion.id] === option
                              ? 'border-primary-500 bg-primary-500/10 text-primary-600 dark:text-primary-400 font-extrabold shadow'
                              : 'border-gray-200 dark:border-slate-800 hover:bg-gray-50/50 dark:hover:bg-slate-800/10'
                          }`}
                        >
                          {option}
                        </button>
                      ))}
                    </div>
                  ) : currentQuestion.type === 'MATCH' ? (
                    <div className="space-y-3.5">
                      <p className="text-xs text-gray-400 italic">Match the corresponding items below:</p>
                      {currentQuestion.options.map((leftItem) => {
                        const currentMapping = parseMatchPairs(answers[currentQuestion.id] || '');
                        const selectedRight = currentMapping[leftItem] || '';
                        return (
                          <div 
                            key={leftItem} 
                            className="flex items-center justify-between gap-4 p-3.5 border border-gray-200 dark:border-slate-800 rounded-xl bg-white/20 dark:bg-slate-900/15"
                          >
                            <span className="text-sm font-bold text-gray-800 dark:text-slate-200">{leftItem}</span>
                            <select
                              value={selectedRight}
                              onChange={(e) => handleMatchChange(currentQuestion.id, leftItem, e.target.value)}
                              className="p-2 text-xs border border-gray-200 dark:border-slate-800 rounded-lg bg-white dark:bg-slate-950 text-gray-700 dark:text-slate-350 focus:outline-none"
                            >
                              <option value="">-- Match --</option>
                              {shuffledRightChoices.map(rc => (
                                <option key={rc} value={rc}>{rc}</option>
                              ))}
                            </select>
                          </div>
                        );
                      })}
                    </div>
                  ) : (
                    // Default MCQ
                    currentQuestion.options.map((opt) => (
                      <div
                        key={opt}
                        onClick={() => handleSelectAnswer(currentQuestion.id, opt)}
                        className={`p-4 rounded-xl border text-sm font-semibold cursor-pointer active:scale-[0.99] transition-all ${
                          answers[currentQuestion.id] === opt
                            ? 'border-primary-500 bg-primary-500/10 text-primary-800 dark:text-primary-400 font-extrabold shadow'
                            : 'border-gray-200 dark:border-slate-800 hover:bg-gray-50/50 dark:hover:bg-slate-800/10'
                        }`}
                      >
                        {opt}
                      </div>
                    ))
                  )}
                </div>
              </div>

              {/* Navigation Footer */}
              <div className="flex justify-between items-center pt-4 border-t border-gray-150 dark:border-slate-805">
                <button
                  disabled={currentQuestionIdx === 0}
                  onClick={() => setCurrentQuestionIdx(currentQuestionIdx - 1)}
                  className="flex items-center gap-2 px-4 py-2 border border-gray-200 dark:border-slate-800 hover:bg-gray-100/50 dark:hover:bg-slate-800/20 rounded-lg text-sm transition disabled:opacity-50"
                >
                  <FiArrowLeft /> Previous
                </button>

                {currentQuestionIdx < activeQuiz.questions.length - 1 ? (
                  <button
                    onClick={() => setCurrentQuestionIdx(currentQuestionIdx + 1)}
                    className="flex items-center gap-2 px-4 py-2 bg-primary-600 hover:bg-primary-500 text-white rounded-lg text-sm transition"
                  >
                    Next <FiArrowRight />
                  </button>
                ) : (
                  <button
                    onClick={handleSubmitQuiz}
                    disabled={isSubmitting}
                    className="flex items-center gap-2 px-5 py-2.5 bg-green-600 hover:bg-green-500 text-white rounded-lg text-sm font-semibold shadow transition"
                  >
                    {isSubmitting ? 'Grading...' : 'Submit Quiz'}
                  </button>
                )}
              </div>
            </div>
          )}

          {/* STATE 3: Results Summary & Review */}
          {result && activeQuiz && (
            <div className="space-y-6 animate-fade-in">
              
              {/* Premium Result Score card */}
              <div className="glass-panel p-6 rounded-2xl shadow-xl bg-white/40 dark:bg-slate-900/30 text-center flex flex-col items-center gap-6 relative overflow-hidden">
                <div className="absolute top-0 inset-x-0 h-1.5 bg-gradient-to-r from-primary-500 via-violet-500 to-indigo-500"></div>

                <div className={`p-4 rounded-full ${
                  result.passed 
                    ? 'bg-green-500/10 text-green-500 border border-green-500/20' 
                    : 'bg-red-500/10 text-red-500 border border-red-500/20'
                }`}>
                  <FiAward className="h-12 w-12" />
                </div>
                
                <div>
                  <h3 className="text-2xl font-black text-gray-900 dark:text-white">
                    {result.passed ? 'Flawless Victory!' : 'Keep Practicing!'}
                  </h3>
                  <p className="text-xs text-gray-400 mt-1 uppercase tracking-widest font-semibold">Quiz Performance Report</p>
                </div>

                <div className="grid grid-cols-2 md:grid-cols-4 gap-4 w-full pt-4 border-t border-gray-100 dark:border-slate-800">
                  <div className="p-3 bg-gray-50/50 dark:bg-slate-900/30 border border-gray-100 dark:border-slate-850 rounded-2xl text-center">
                    <p className="text-[10px] text-gray-400 uppercase font-bold">Accuracy</p>
                    <p className="text-base font-black text-gray-800 dark:text-white mt-0.5">{result.percentage.toFixed(0)}%</p>
                  </div>
                  <div className="p-3 bg-gray-50/50 dark:bg-slate-900/30 border border-gray-100 dark:border-slate-850 rounded-2xl text-center">
                    <p className="text-[10px] text-gray-400 uppercase font-bold">Total Score</p>
                    <p className="text-base font-black text-primary-600 dark:text-primary-400 mt-0.5">{result.score} pts</p>
                  </div>
                  <div className="p-3 bg-gray-50/50 dark:bg-slate-900/30 border border-gray-100 dark:border-slate-850 rounded-2xl text-center">
                    <p className="text-[10px] text-gray-400 uppercase font-bold">XP Gained</p>
                    <p className="text-base font-black text-yellow-600 dark:text-yellow-500 mt-0.5 flex items-center justify-center gap-0.5">
                      <FiZap className="h-4 w-4 shrink-0 fill-current" /> +{result.xpEarned || (result.score * 2)}
                    </p>
                  </div>
                  <div className="p-3 bg-gray-50/50 dark:bg-slate-900/30 border border-gray-100 dark:border-slate-850 rounded-2xl text-center">
                    <p className="text-[10px] text-gray-400 uppercase font-bold">Correct Ans</p>
                    <p className="text-base font-black text-green-600 dark:text-green-400 mt-0.5">{result.correctCount} / {result.totalCount}</p>
                  </div>
                </div>

                {/* Display unlocked badges/achievements */}
                {((result.unlockedBadges && result.unlockedBadges.length > 0) || 
                  (result.unlockedAchievements && result.unlockedAchievements.length > 0)) && (
                  <div className="w-full p-4 rounded-xl bg-gradient-to-r from-yellow-500/10 to-orange-500/10 border border-yellow-500/20 text-left space-y-2 animate-bounce-short">
                    <p className="text-xs font-bold text-yellow-600 dark:text-yellow-500 uppercase flex items-center gap-1.5">
                      <FiAward /> Rewards Unlocked!
                    </p>
                    {result.unlockedBadges?.map(badge => (
                      <p key={badge} className="text-xs text-gray-700 dark:text-slate-300">
                        Earned Badge: <strong className="text-amber-500 font-extrabold uppercase">{badge} Status</strong>!
                      </p>
                    ))}
                    {result.unlockedAchievements?.map(ach => (
                      <p key={ach} className="text-xs text-gray-700 dark:text-slate-300">
                        Unlocked Achievement: <strong className="text-primary-600 dark:text-primary-400">{ach}</strong>!
                      </p>
                    ))}
                  </div>
                )}

                <div className="flex gap-4 w-full max-w-sm pt-2">
                  <button
                    onClick={() => {
                      setActiveQuiz(null);
                      setResult(null);
                    }}
                    className="flex-1 bg-gradient-to-r from-primary-600 to-violet-600 hover:from-primary-500 hover:to-violet-500 text-white font-bold py-2.5 px-4 rounded-xl text-xs transition"
                  >
                    Take Another Quiz
                  </button>
                  <button
                    onClick={() => {
                      setResult(null);
                      setAnswers({});
                      setCurrentQuestionIdx(0);
                      setTimeTaken(0);
                      setTimeLeft(activeQuiz.timeLimit * 60);
                    }}
                    className="flex-1 border border-gray-250 dark:border-slate-800 hover:bg-gray-50/50 dark:hover:bg-slate-800/20 font-bold py-2.5 px-4 rounded-xl text-xs text-gray-700 dark:text-slate-300 transition"
                  >
                    Retake Quiz
                  </button>
                </div>
              </div>

              {/* Review Panel */}
              <div className="glass-panel p-6 rounded-2xl shadow-xl space-y-6 text-left bg-white/40 dark:bg-slate-900/30">
                <h3 className="text-sm font-extrabold text-gray-900 dark:text-white border-b border-gray-150 dark:border-slate-805 pb-3">
                  Answer Key Review
                </h3>

                <div className="space-y-4">
                  {activeQuiz.questions.map((q, idx) => {
                    const userAns = answers[q.id];
                    const correctAns = result.correctAnswers[q.id];
                    
                    let isCorrect = false;
                    if (q.type === 'MATCH') {
                      const userMap = parseMatchPairs(userAns);
                      const correctMap = parseMatchPairs(correctAns);
                      isCorrect = Object.keys(correctMap).length > 0 && 
                        Object.keys(correctMap).every(k => userMap[k] === correctMap[k]);
                    } else {
                      isCorrect = userAns && userAns.trim().toLowerCase() === correctAns.trim().toLowerCase();
                    }

                    return (
                      <div key={q.id} className="p-4 rounded-xl bg-white/30 dark:bg-slate-900/30 border border-gray-200 dark:border-slate-800/80 space-y-3">
                        <div className="flex items-start justify-between gap-4">
                          <p className="text-xs font-bold text-gray-900 dark:text-white leading-relaxed">
                            {idx + 1}. {q.questionText}
                          </p>
                          <span className="shrink-0 mt-0.5">
                            {isCorrect ? (
                              <FiCheckCircle className="h-5 w-5 text-green-500" />
                            ) : (
                              <FiXCircle className="h-5 w-5 text-red-500" />
                            )}
                          </span>
                        </div>

                        {q.type === 'MATCH' ? (
                          <div className="space-y-2 pt-2 border-t border-gray-100/50 dark:border-slate-800">
                            {q.options.map(leftItem => {
                              const userMap = parseMatchPairs(userAns);
                              const correctMap = parseMatchPairs(correctAns);
                              const subCorrect = userMap[leftItem] === correctMap[leftItem];
                              return (
                                <div key={leftItem} className="flex justify-between items-center text-[11px] p-2 bg-gray-50/50 dark:bg-slate-950/20 rounded border border-gray-100 dark:border-slate-900">
                                  <span className="font-bold text-gray-700 dark:text-slate-300">{leftItem}</span>
                                  <div className="flex items-center gap-2">
                                    <span className={subCorrect ? 'text-green-600 dark:text-green-400 font-bold' : 'text-red-500 line-through'}>
                                      {userMap[leftItem] || '(No selection)'}
                                    </span>
                                    {!subCorrect && (
                                      <span className="text-green-600 dark:text-green-400 font-extrabold">
                                        → {correctMap[leftItem]}
                                      </span>
                                    )}
                                  </div>
                                </div>
                              );
                            })}
                          </div>
                        ) : (
                          <div className="grid grid-cols-1 md:grid-cols-2 gap-2.5 pt-1 text-xs">
                            <div className="p-2.5 rounded bg-white dark:bg-slate-950/50 border border-gray-200 dark:border-slate-850">
                              <span className="font-bold text-gray-400 uppercase tracking-wide block mb-1">Your Answer</span>
                              <span className={isCorrect ? 'text-green-600 dark:text-green-400 font-bold' : 'text-red-500 line-through'}>
                                {userAns || '(No Answer)'}
                              </span>
                            </div>
                            {!isCorrect && (
                              <div className="p-2.5 rounded bg-green-50/20 dark:bg-slate-950/50 border border-green-200 dark:border-slate-850">
                                <span className="font-bold text-green-500 uppercase tracking-wide block mb-1">Correct Answer</span>
                                <span className="text-green-600 dark:text-green-400 font-extrabold">
                                  {correctAns}
                                </span>
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>

            </div>
          )}

        </div>

        {/* Sidebar History Panel (1 col) */}
        <div className="lg:col-span-1 space-y-6">
          <div className="glass-panel p-6 rounded-2xl shadow-xl flex flex-col h-[520px] bg-white/40 dark:bg-slate-900/30">
            <h3 className="text-base font-bold text-gray-900 dark:text-white mb-4 flex items-center gap-2 border-b border-gray-100 dark:border-slate-800 pb-3">
              <FiClock className="text-primary-600 dark:text-primary-400" /> Quiz History
            </h3>

            <div className="flex-1 overflow-y-auto divide-y divide-gray-100 dark:divide-slate-850/50 pr-1">
              {loadingHistory ? (
                <div className="flex justify-center py-10">
                  <div className="h-6 w-6 animate-spin rounded-full border-2 border-t-primary-600 border-primary-100"></div>
                </div>
              ) : attempts.length === 0 ? (
                <p className="text-xs text-gray-400 py-10 text-center font-medium">No quiz attempts yet.</p>
              ) : (
                attempts.map((attempt) => (
                  <div
                    key={attempt.id}
                    onClick={() => loadPastAttempt(attempt)}
                    className="p-3 text-left hover:bg-gray-100/50 dark:hover:bg-slate-900/10 cursor-pointer transition rounded-xl my-1.5 border border-transparent hover:border-gray-200/20"
                  >
                    <div className="flex justify-between items-start gap-2">
                      <p className="text-xs font-bold text-gray-800 dark:text-slate-200 truncate">
                        Quiz score: {attempt.score} / {attempt.maxScore}
                      </p>
                      <span className={`text-[9px] px-1.5 py-0.5 rounded font-extrabold ${
                        attempt.percentage >= 60.0 
                          ? 'bg-green-500/10 text-green-600 border border-green-500/20' 
                          : 'bg-red-500/10 text-red-650 border border-red-500/20'
                      }`}>
                        {attempt.percentage.toFixed(0)}%
                      </span>
                    </div>
                    <div className="flex justify-between items-center mt-2 text-[9px] text-gray-400">
                      <span className="flex items-center gap-0.5 text-yellow-600">
                        <FiZap className="h-3 w-3" /> +{attempt.score * 2} XP
                      </span>
                      <span>{new Date(attempt.completedAt).toLocaleDateString()}</span>
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

export default Quiz;
