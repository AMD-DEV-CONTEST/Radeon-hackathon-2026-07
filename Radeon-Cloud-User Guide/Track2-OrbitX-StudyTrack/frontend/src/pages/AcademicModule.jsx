import React, { useState, useRef } from 'react'
import { api } from '../api'
import toast from 'react-hot-toast'
import { BookOpen, Upload, FileText, ChevronRight, CheckCircle, RotateCcw, Trophy } from 'lucide-react'

const STEPS = ['Setup', 'Quiz', 'Results']

function StepIndicator({ current }) {
  return (
    <div className="steps-container">
      {STEPS.map((s, i) => (
        <React.Fragment key={s}>
          <div className="step-item">
            <div className={`step-circle ${i < current ? 'done' : i === current ? 'active' : ''}`}>
              {i < current ? <CheckCircle size={14} /> : i + 1}
            </div>
          </div>
          {i < STEPS.length - 1 && <div className={`step-connector ${i < current ? 'done' : ''}`} />}
        </React.Fragment>
      ))}
    </div>
  )
}

function MCQQuestion({ q, index, answer, onSelect, showResult }) {
  return (
    <div className="card animate-fadeInUp" style={{ marginBottom: '1rem', animationDelay: `${index * 0.05}s` }}>
      <div style={{ display: 'flex', gap: '0.75rem', marginBottom: '1rem' }}>
        <span style={{ background: 'var(--primary)', color: '#FFFFFF', width: 26, height: 26, borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '0.75rem', fontWeight: 600, flexShrink: 0 }}>{index + 1}</span>
        <p style={{ fontSize: '0.9rem', lineHeight: 1.6 }}>{q.question}</p>
      </div>
      {q.options.map((opt, j) => {
        let cls = 'mcq-option'
        if (showResult) {
          if (opt === q.correct_answer) cls += ' correct'
          else if (opt === answer && opt !== q.correct_answer) cls += ' incorrect'
        } else if (opt === answer) cls += ' selected'
        return (
          <button key={j} className={cls} onClick={() => !showResult && onSelect(q.id, opt)}>
            <span className="option-letter">{String.fromCharCode(65 + j)}</span>
            {opt.replace(/^[A-D]\)\s*/, '')}
          </button>
        )
      })}
      {showResult && q.explanation && (
        <div className="alert alert-info" style={{ marginTop: '0.75rem', fontSize: '0.8rem' }}>
          {q.explanation}
        </div>
      )}
    </div>
  )
}

function TheoryQuestion({ q, index, answer, onChange, result, showResult }) {
  return (
    <div className="card animate-fadeInUp" style={{ marginBottom: '1rem', animationDelay: `${index * 0.05}s` }}>
      <div style={{ display: 'flex', gap: '0.75rem', marginBottom: '1rem', alignItems: 'flex-start' }}>
        <span style={{ background: 'var(--primary)', color: '#FFFFFF', width: 26, height: 26, borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '0.75rem', fontWeight: 600, flexShrink: 0 }}>T</span>
        <p style={{ fontSize: '0.9rem', lineHeight: 1.6 }}>{q.question}</p>
      </div>
      <textarea
        className="form-textarea"
        placeholder="Write your detailed answer here..."
        value={answer || ''}
        onChange={e => !showResult && onChange(q.id, e.target.value)}
        disabled={showResult}
        style={{ minHeight: '120px' }}
      />
      {showResult && result && (
        <div style={{ marginTop: '0.75rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.5rem' }}>
            <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Score</span>
            <span style={{ fontWeight: 600, color: result.score >= 60 ? 'var(--success)' : result.score >= 40 ? 'var(--warning)' : 'var(--danger)' }}>{result.score.toFixed(0)}%</span>
          </div>
          {result.feedback && <div className="alert alert-info" style={{ fontSize: '0.8rem' }}>{result.feedback}</div>}
          {result.missed_points?.length > 0 && (
            <div style={{ marginTop: '0.5rem' }}>
              <p style={{ fontSize: '0.75rem', color: 'var(--danger)', marginBottom: '0.25rem' }}>Missed points:</p>
              <ul style={{ paddingLeft: '1rem' }}>
                {result.missed_points.slice(0, 3).map((p, i) => <li key={i} style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', marginBottom: '0.15rem' }}>{p}</li>)}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function ShortQuestion({ q, index, answer, onChange, result, showResult }) {
  return (
    <div className="card animate-fadeInUp" style={{ marginBottom: '1rem', animationDelay: `${index * 0.05}s` }}>
      <div style={{ display: 'flex', gap: '0.75rem', marginBottom: '0.75rem', alignItems: 'flex-start' }}>
        <span style={{ background: 'var(--warning)', color: '#FFFFFF', width: 26, height: 26, borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '0.75rem', fontWeight: 600, flexShrink: 0 }}>S</span>
        <p style={{ fontSize: '0.9rem', lineHeight: 1.6 }}>{q.question}</p>
      </div>
      <input
        type="text"
        className="form-input"
        placeholder="Your answer..."
        value={answer || ''}
        onChange={e => !showResult && onChange(q.id, e.target.value)}
        disabled={showResult}
      />
      {showResult && result && (
        <div style={{ marginTop: '0.5rem', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>{result.feedback}</span>
          <span style={{ fontWeight: 600, fontSize: '0.85rem', color: result.score >= 60 ? 'var(--success)' : 'var(--danger)' }}>{result.score.toFixed(0)}%</span>
        </div>
      )}
    </div>
  )
}

export default function AcademicModule() {
  const [step, setStep] = useState(0)
  const [subject, setSubject] = useState('')
  const [topic, setTopic] = useState('')
  const [file, setFile] = useState(null)
  const [textContent, setTextContent] = useState('')
  const [quiz, setQuiz] = useState(null)
  const [answers, setAnswers] = useState({})  // {mcq_1:'opt', theory_1:'text', short_1:'text'}
  const [submitting, setSubmitting] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [results, setResults] = useState(null)
  const [activeTab, setActiveTab] = useState('mcq')
  const [dragOver, setDragOver] = useState(false)
  const fileRef = useRef()

  const handleFile = (f) => {
    if (!f) return
    if (f.size > 10 * 1024 * 1024) { toast.error('File too large (max 10MB)'); return }
    setFile(f)
    toast.success(`File loaded: ${f.name}`)
  }

  const generateQuiz = async () => {
    if (!subject.trim() || !topic.trim()) { toast.error('Enter subject and topic'); return }
    setGenerating(true)
    try {
      const formData = new FormData()
      formData.append('subject', subject)
      formData.append('topic', topic)
      formData.append('content', textContent)
      if (file) formData.append('file', file)
      const res = await api.post('/api/academic/generate-quiz', formData, { headers: { 'Content-Type': 'multipart/form-data' } })
      setQuiz(res.data.quiz)
      setAnswers({})
      setStep(1)
      toast.success('Quiz generated!')
    } catch (e) {
      toast.error(e.response?.data?.error || 'Failed to generate quiz')
    } finally {
      setGenerating(false)
    }
  }

  const submitQuiz = async () => {
    const total = totalQuestions
    const answered = Object.keys(answers).length
    if (answered < total * 0.5) {
      const ok = window.confirm(`You've only answered ${answered}/${total} questions. Submit anyway?`)
      if (!ok) return
    }
    setSubmitting(true)
    try {
      const res = await api.post('/api/academic/submit-quiz', { subject, topic, quiz, answers })
      setResults(res.data)
      setStep(2)
      toast.success('Quiz submitted! Analyzing your answers...')
    } catch (e) {
      toast.error(e.response?.data?.error || 'Failed to submit quiz')
    } finally {
      setSubmitting(false)
    }
  }

  const getScoreColor = (s) => s >= 75 ? 'var(--success)' : s >= 50 ? 'var(--warning)' : 'var(--danger)'

  const totalQuestions = (quiz?.mcqs?.length || 0) + (quiz?.theory_questions?.length || 0) + (quiz?.short_answer_questions?.length || 0)

  return (
    <div className="page-container">
      <div className="module-header card">
        <div className="icon-tile">
          <BookOpen size={22} />
        </div>
        <div>
          <span className="badge badge-purple" style={{ marginBottom:'0.75rem' }}>Academic Journal</span>
          <h1 style={{ fontSize:'2rem', marginBottom:'0.5rem' }}>Adaptive Learning Studio</h1>
          <p style={{ color:'var(--text-secondary)', maxWidth:680 }}>Generate editorial quizzes, capture notes, and review skill gaps in a calm study workspace.</p>
        </div>
      </div>

      <StepIndicator current={step} />

      {/* STEP 0: Setup */}
      {step === 0 && (
        <div className="animate-fadeInUp editorial-form-panel" style={{ maxWidth:760, margin:'0 auto' }}>
          <div className="card" style={{ marginBottom:'1.25rem' }}>
            <h3 style={{ marginBottom:'1.25rem', fontSize:'1.1rem' }}>Configure Your Quiz</h3>
            <div className="editorial-form-grid">
              <div className="form-group">
                <label className="form-label">Academic Subject</label>
                <input id="academic-subject" className="form-input" placeholder="e.g. Data Structures, Computer Networks, Physics" value={subject} onChange={e => setSubject(e.target.value)} />
              </div>
              <div className="form-group">
                <label className="form-label">Topic to Assess</label>
                <input id="academic-topic" className="form-input" placeholder="e.g. Binary Trees, Routing Algorithms, Quantum Mechanics" value={topic} onChange={e => setTopic(e.target.value)} />
              </div>
            </div>
          </div>

          <div className="card" style={{ marginBottom:'1.25rem' }}>
            <h3 style={{ marginBottom:'1rem', fontSize:'1rem' }}>Upload Study Material <span style={{ color:'var(--text-muted)', fontSize:'0.8rem', fontWeight:400 }}>(optional)</span></h3>

            <div
              className={`upload-zone ${dragOver ? 'drag-over' : ''} ${file ? 'has-file' : ''}`}
              onClick={() => fileRef.current?.click()}
              onDragOver={e => { e.preventDefault(); setDragOver(true) }}
              onDragLeave={() => setDragOver(false)}
              onDrop={e => { e.preventDefault(); setDragOver(false); handleFile(e.dataTransfer.files[0]) }}
              id="academic-upload-zone"
            >
              <input ref={fileRef} type="file" accept=".pdf,.txt" style={{ display:'none' }} onChange={e => handleFile(e.target.files[0])} />
              {file ? (
                <>
<FileText size={32} style={{ color:'var(--success)', marginBottom:'0.5rem' }} />
                    <p style={{ color:'var(--success)', fontWeight:600, fontSize:'0.9rem' }}>{file.name}</p>
                  <p style={{ color:'var(--text-muted)', fontSize:'0.75rem', marginTop:'0.25rem' }}>Click to change</p>
                </>
              ) : (
                <>
                  <Upload size={32} style={{ color:'var(--text-muted)', marginBottom:'0.75rem' }} />
                  <p style={{ fontWeight:600, marginBottom:'0.25rem' }}>Drag and drop or click to upload</p>
                  <p style={{ color:'var(--text-muted)', fontSize:'0.8rem' }}>PDF or TXT files of your notes</p>
                </>
              )}
            </div>

            <p style={{ textAlign:'center', color:'var(--text-muted)', fontSize:'0.8rem', margin:'0.75rem 0' }}>or paste notes directly</p>
            <textarea
              id="academic-notes"
              className="form-textarea"
              placeholder="Paste your notes, textbook content, or any study material here..."
              value={textContent}
              onChange={e => setTextContent(e.target.value)}
              style={{ minHeight:'100px' }}
            />
          </div>

          <button id="academic-generate-btn" className="btn btn-primary btn-lg" style={{ width:'100%' }} onClick={generateQuiz} disabled={generating || !subject || !topic}>
            {generating ? (
              <><span className="spinner" /> Generating Quiz with AI...</>
            ) : (
              <><ChevronRight size={20} /> Generate AI Quiz (7 MCQ + 4 Theory + 4 Short Answer)</>
            )}
          </button>
        </div>
      )}

      {/* STEP 1: Quiz */}
      {step === 1 && quiz && (
        <div className="animate-fadeIn">
          <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between', marginBottom:'1.5rem' }}>
            <div>
              <h2 style={{ fontSize:'1.25rem' }}>{subject} — <span style={{ color:'var(--primary)' }}>{topic}</span></h2>
              <p style={{ color:'var(--text-muted)', fontSize:'0.85rem' }}>Answer all questions. MCQs are auto-scored; theory answers are AI-graded.</p>
            </div>
            <div style={{ display:'flex', gap:'0.75rem' }}>
              <span className="badge badge-purple">{(quiz.mcqs?.length||0) + (quiz.theory_questions?.length||0) + (quiz.short_answer_questions?.length||0)} Questions</span>
              <span className="badge badge-cyan">Answered: {Object.keys(answers).length}</span>
            </div>
          </div>

          {/* Tabs */}
          <div className="tabs">
            {[['mcq','MCQs',quiz.mcqs?.length||0,'var(--primary)'],['theory','Theory',quiz.theory_questions?.length||0,'var(--secondary)'],['short','Short Answer',quiz.short_answer_questions?.length||0,'var(--warning)']].map(([id, label, count, color]) => (
              <button key={id} id={`tab-${id}`} className={`tab-btn ${activeTab===id?'active':''}`} onClick={() => setActiveTab(id)} style={activeTab===id?{color}:{}}>
                {label} ({count})
              </button>
            ))}
          </div>

          {activeTab === 'mcq' && quiz.mcqs?.map((q, i) => (
            <MCQQuestion key={q.id} q={q} index={i} answer={answers[`mcq_${q.id}`]} onSelect={(id, v) => setAnswers(p => ({...p, [`mcq_${id}`]:v}))} showResult={false} />
          ))}
          {activeTab === 'theory' && quiz.theory_questions?.map((q, i) => (
            <TheoryQuestion key={q.id} q={q} index={i} answer={answers[`theory_${q.id}`]} onChange={(id, v) => setAnswers(p => ({...p, [`theory_${id}`]:v}))} showResult={false} />
          ))}
          {activeTab === 'short' && quiz.short_answer_questions?.map((q, i) => (
            <ShortQuestion key={q.id} q={q} index={i} answer={answers[`short_${q.id}`]} onChange={(id, v) => setAnswers(p => ({...p, [`short_${id}`]:v}))} showResult={false} />
          ))}

          <div style={{ marginTop:'1.5rem', display:'flex', gap:'1rem' }}>
            <button className="btn btn-ghost" onClick={() => { setStep(0); setQuiz(null); setAnswers({}) }}>Back to Setup</button>
            <button id="academic-submit-btn" className="btn btn-primary btn-lg" style={{ flex:1 }} onClick={submitQuiz} disabled={submitting}>
              {submitting ? <><span className="spinner" /> Submitting & Analyzing...</> : <><Trophy size={18} /> Submit Quiz</>}
            </button>
          </div>
        </div>
      )}

      {/* STEP 2: Results */}
      {step === 2 && results && (
        <div className="animate-fadeIn">
          {/* Score Overview */}
          <div className="grid-4" style={{ marginBottom:'2rem' }}>
            {[
              { label:'Overall', value: results.scores.overall, color: getScoreColor(results.scores.overall) },
              { label:'MCQ', value: results.scores.mcq, color: 'var(--primary)' },
              { label:'Theory', value: results.scores.theory, color: 'var(--secondary)' },
              { label:'Short Answer', value: results.scores.short_answer, color: 'var(--warning)' },
            ].map(({ label, value, color }) => (
              <div key={label} className="stat-card animate-fadeInUp" style={{ textAlign:'center' }}>
                <div className="stat-value" style={{ color }}>{value.toFixed(0)}%</div>
                <div className="stat-label">{label} Score</div>
                <div className="progress-bar-container" style={{ marginTop:'0.5rem' }}>
                  <div className="progress-bar-fill" style={{ width:`${value}%`, background:color }} />
                </div>
              </div>
            ))}
          </div>

          <div className="grid-2" style={{ marginBottom:'2rem' }}>
            {/* AI Analysis */}
            <div className="card">
              <h3 style={{ marginBottom:'1rem', fontSize:'1rem' }}>AI Mistake Analysis</h3>
              {results.weak_areas?.length > 0 ? (
                <>
                  <p style={{ color:'var(--text-secondary)', fontSize:'0.875rem', marginBottom:'1rem', lineHeight:1.7 }}>{results.ai_analysis}</p>
                  <div style={{ marginBottom:'1rem' }}>
                    <p style={{ fontSize:'0.8rem', color:'var(--text-muted)', marginBottom:'0.5rem', fontWeight:600 }}>WEAK CONCEPTS IDENTIFIED</p>
                    <div style={{ display:'flex', flexWrap:'wrap', gap:'0.5rem' }}>
                      {results.weak_areas.map(w => <span key={w} className="badge badge-weak">{w}</span>)}
                    </div>
                  </div>
                  {Object.entries(results.specific_gaps || {}).length > 0 && (
                    <div>
                      <p style={{ fontSize:'0.8rem', color:'var(--text-muted)', marginBottom:'0.5rem', fontWeight:600 }}>SPECIFIC GAPS</p>
                      {Object.entries(results.specific_gaps).map(([c, desc]) => (
                        <div key={c} style={{ padding:'0.625rem', background:'var(--danger-soft)', borderRadius:'var(--radius-sm)', marginBottom:'0.375rem', border:'1px solid rgba(220,38,38,0.15)' }}>
                          <span style={{ color:'var(--danger)', fontWeight:600, fontSize:'0.8rem' }}>{c}:</span>
                          <span style={{ color:'var(--text-secondary)', fontSize:'0.8rem', marginLeft:'0.375rem' }}>{desc}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </>
              ) : (
                <div className="alert alert-success">
                  Excellent performance! No significant weak areas detected.
                </div>
              )}
            </div>

            {/* Personalized Recommendations */}
            <div className="card" style={{ background:'var(--grad-card)' }}>
              <h3 style={{ marginBottom:'1rem', fontSize:'1rem' }}>Personalized Study Plan</h3>
              <p style={{ color:'var(--text-secondary)', fontSize:'0.875rem', lineHeight:1.8, whiteSpace:'pre-line' }}>{results.recommendations}</p>
            </div>
          </div>

          {/* Detailed Review Tabs */}
          <div className="card" style={{ marginBottom:'1.5rem' }}>
            <h3 style={{ marginBottom:'1rem', fontSize:'1rem' }}>Detailed Question Review</h3>
            <div className="tabs">
              {[['mcq','MCQs'],['theory','Theory'],['short','Short Answer']].map(([id,label]) => (
                <button key={id} className={`tab-btn ${activeTab===id?'active':''}`} onClick={() => setActiveTab(id)}>{label}</button>
              ))}
            </div>

            {activeTab === 'mcq' && results.mcq_results?.map((r, i) => (
              <MCQQuestion key={r.id} q={{...quiz.mcqs[i], id:r.id}}
                index={i} answer={r.student_answer}
                onSelect={() => {}} showResult={true} />
            ))}
            {activeTab === 'theory' && results.theory_results?.map((r, i) => (
              <TheoryQuestion key={r.id} q={quiz.theory_questions[i]}
                index={i} answer={r.student_answer}
                onChange={() => {}} result={r} showResult={true} />
            ))}
            {activeTab === 'short' && results.short_results?.map((r, i) => (
              <ShortQuestion key={r.id} q={quiz.short_answer_questions[i]}
                index={i} answer={r.student_answer}
                onChange={() => {}} result={r} showResult={true} />
            ))}
          </div>

          <div style={{ display:'flex', gap:'1rem' }}>
            <button id="academic-retry-btn" className="btn btn-primary" onClick={() => { setStep(0); setAnswers({}); setQuiz(null); setResults(null) }}>
              <RotateCcw size={16} /> New Quiz
            </button>
            <button className="btn btn-secondary" onClick={() => { setStep(1) }}>
              Review My Answers
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
