import React, { useState } from 'react'
import { api } from '../api'
import toast from 'react-hot-toast'
import MonacoEditor from '@monaco-editor/react'
import {
  RadarChart, PolarGrid, PolarAngleAxis, Radar, ResponsiveContainer
} from 'recharts'
import { Briefcase, CheckCircle, Play, RotateCcw, Target, Code, BookOpen, TrendingUp } from 'lucide-react'

const STEPS = ['Career Goal', 'Skills Preview', 'Assessment', 'Results']

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

function ScoreRing({ score, size = 140, label }) {
  const r = (size - 16) / 2
  const circ = 2 * Math.PI * r
  const dash = (score / 100) * circ
  const color = score >= 75 ? 'var(--success)' : score >= 50 ? 'var(--warning)' : 'var(--danger)'
  return (
    <div style={{ position: 'relative', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: size, height: size }}>
      <svg width={size} height={size} style={{ transform: 'rotate(-90deg)' }}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--border)" strokeWidth={12} />
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={color} strokeWidth={12}
          strokeDasharray={`${dash} ${circ}`} strokeLinecap="round"
          style={{ transition: 'stroke-dasharray 1.5s cubic-bezier(0.4,0,0.2,1)' }} />
      </svg>
      <div style={{ position: 'absolute', textAlign: 'center' }}>
        <div style={{ fontSize: '1.75rem', fontWeight: 700, color, lineHeight: 1 }}>{score.toFixed(0)}%</div>
        <div style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', marginTop: 2 }}>{label || 'Score'}</div>
      </div>
    </div>
  )
}

function CodeEditor({ code, onChange, onRun, runResult, running }) {
  return (
    <div style={{ marginTop: '0.75rem' }}>
      <div className="monaco-wrapper">
        <MonacoEditor
          height="220px"
          language="python"
          value={code}
          onChange={onChange}
          theme="vs-dark"
          options={{
            fontSize: 13,
            minimap: { enabled: false },
            scrollBeyondLastLine: false,
            lineNumbers: 'on',
            folding: false,
            automaticLayout: true,
            padding: { top: 12, bottom: 12 },
            fontFamily: "'JetBrains Mono', monospace",
            smoothScrolling: true,
          }}
        />
      </div>
      <div style={{ display: 'flex', gap: '0.75rem', marginTop: '0.75rem', alignItems: 'center' }}>
        <button onClick={onRun} disabled={running} className="btn btn-primary btn-sm">
          {running ? <><span className="spinner" style={{ width: 14, height: 14 }} /> Running...</> : <><Play size={14} /> Run Code</>}
        </button>
        {runResult && (
          <div style={{ flex: 1 }}>
            {runResult.stdout && (
              <div style={{ background: 'var(--success-soft)', border: '1px solid var(--border)', borderRadius: 16, padding: '0.5rem 0.75rem' }}>
                <p style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: '0.78rem', color: 'var(--success)', margin: 0, whiteSpace: 'pre-wrap' }}>{runResult.stdout}</p>
              </div>
            )}
            {runResult.stderr && (
              <div style={{ background: 'var(--danger-soft)', border: '1px solid var(--border)', borderRadius: 16, padding: '0.5rem 0.75rem', marginTop: '0.25rem' }}>
                <p style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: '0.78rem', color: 'var(--danger)', margin: 0, whiteSpace: 'pre-wrap' }}>{runResult.stderr}</p>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

export default function CareerModule() {
  const [step, setStep] = useState(0)
  const [careerGoal, setCareerGoal] = useState('')
  const [careerData, setCareerData] = useState(null)
  const [allQuestions, setAllQuestions] = useState({})
  const [answers, setAnswers] = useState({})
  const [codeRuns, setCodeRuns] = useState({})
  const [running, setRunning] = useState({})
  const [loadingSkills, setLoadingSkills] = useState(false)
  const [loadingQuestions, setLoadingQuestions] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [results, setResults] = useState(null)
  const [activeSkill, setActiveSkill] = useState(null)

  const identifySkills = async () => {
    if (!careerGoal.trim()) { toast.error('Enter your career goal'); return }
    setLoadingSkills(true)
    try {
      const res = await api.post('/api/career/identify-skills', { career_goal: careerGoal })
      setCareerData(res.data)
      setStep(1)
      toast.success(`Found ${res.data.required_skills?.length} required skills!`)
    } catch (err) {
      toast.error(err.response?.data?.error || 'Failed to identify skills')
    } finally {
      setLoadingSkills(false)
    }
  }

  const loadQuestionsForAll = async () => {
    if (!careerData?.required_skills?.length) return
    setLoadingQuestions(true)
    toast.loading('Generating assessment questions for all skills...', { id: 'qs' })
    try {
      const qs = {}
      for (const skill of careerData.required_skills) {
        const res = await api.post('/api/career/get-questions', {
          skill: skill.name,
          career_goal: careerGoal,
          skill_description: skill.description
        })
        qs[skill.name] = res.data.questions
      }
      setAllQuestions(qs)
      setActiveSkill(careerData.required_skills[0]?.name)
      setStep(2)
      toast.success('Assessment ready!', { id: 'qs' })
    } catch {
      toast.dismiss('qs')
      toast.error('Failed to generate questions')
    } finally {
      setLoadingQuestions(false)
    }
  }

  const setAnswer = (skill, key, value) => {
    setAnswers(p => ({ ...p, [skill]: { ...(p[skill] || {}), [key]: value } }))
  }

  const runCode = async (skill, qId, code) => {
    const key = `${skill}_coding_${qId}`
    setRunning(p => ({ ...p, [key]: true }))
    try {
      const res = await api.post('/api/career/run-code', { code, stdin: '' })
      setCodeRuns(p => ({ ...p, [key]: res.data }))
    } catch {
      toast.error('Code execution failed')
    } finally {
      setRunning(p => ({ ...p, [key]: false }))
    }
  }

  const submitAssessment = async () => {
    setSubmitting(true)
    try {
      const skills = careerData.required_skills.map(s => s.name)
      const res = await api.post('/api/career/submit-assessment', {
        career_goal: careerGoal,
        required_skills: skills,
        answers,
        questions: allQuestions
      })
      setResults(res.data)
      setStep(3)
      toast.success('Assessment complete!')
    } catch (err) {
      toast.error(err.response?.data?.error || 'Failed to submit')
    } finally {
      setSubmitting(false)
    }
  }

  const reset = () => {
    setStep(0); setCareerGoal(''); setCareerData(null)
    setAllQuestions({}); setAnswers({}); setResults(null)
    setActiveSkill(null); setCodeRuns({})
  }

  const SCORE_COLOR = (s) => s >= 75 ? 'var(--success)' : s >= 50 ? 'var(--warning)' : 'var(--danger)'

  return (
    <div className="page-container">
      <div className="module-header card">
        <div className="icon-tile">
          <Briefcase size={22} />
        </div>
        <div>
          <span className="badge badge-purple" style={{ marginBottom: '0.75rem' }}>Career Editorial</span>
          <h1 style={{ fontSize: '2rem', marginBottom: '0.5rem' }}>Career Readiness Journal</h1>
          <p style={{ color: 'var(--text-secondary)', maxWidth: 720 }}>Map target roles, assess skills, and build a refined roadmap.</p>
        </div>
      </div>

      <StepIndicator current={step} />

      {/* STEP 0: Career Goal */}
      {step === 0 && (
        <div className="animate-fadeInUp editorial-form-panel" style={{ maxWidth: 650, margin: '0 auto' }}>
          <div className="card" style={{ textAlign: 'center', paddingBlock: '3rem' }}>
            <div style={{ width: 56, height: 56, borderRadius: 16, background: 'var(--primary-soft)', display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '0 auto 1rem' }}>
              <Target size={28} style={{ color: 'var(--primary)' }} />
            </div>
            <h2 style={{ marginBottom: '0.5rem', fontSize: '1.5rem' }}>Target Career Role</h2>
            <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem', marginBottom: '2rem' }}>
              Enter your target role and our AI will identify required skills and assess your readiness.
            </p>
            <div className="form-group" style={{ marginBottom: '1.5rem', textAlign: 'left' }}>
              <label className="form-label">Target Career Role</label>
              <input
                id="career-goal-input"
                className="form-input"
                placeholder="Data Scientist, Software Engineer, AI Engineer, Cybersecurity Analyst"
                value={careerGoal}
                onChange={e => setCareerGoal(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && identifySkills()}
                style={{ fontSize: '1rem', padding: '0.875rem 1rem' }}
              />
            </div>
            <button id="career-identify-btn" className="btn btn-primary btn-lg" style={{ width: '100%' }} onClick={identifySkills} disabled={loadingSkills || !careerGoal}>
              {loadingSkills ? <><span className="spinner" /> Analyzing Career Requirements...</> : <><Target size={18} /> Identify Required Skills</>}
            </button>
          </div>
        </div>
      )}

      {/* STEP 1: Skills Preview */}
      {step === 1 && careerData && (
        <div className="animate-fadeInUp">
          <div className="card" style={{ marginBottom: '1.5rem' }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
              <h2 style={{ fontSize: '1.25rem', marginBottom: '0.25rem' }}>
                <span style={{ color: 'var(--primary)' }}>{careerData.career_title || careerGoal}</span>
              </h2>
              <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', maxWidth: 600 }}>{careerData.overview}</p>
              <span className="badge badge-purple">{careerData.required_skills?.length} Skills</span>
            </div>
            <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', fontStyle: 'italic', marginTop: '0.75rem' }}>{careerData.industry_context}</p>
          </div>

          <h3 style={{ marginBottom: '1rem', fontSize: '1rem', color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 600 }}>Required Skills</h3>
          <div className="grid-3" style={{ marginBottom: '1.5rem' }}>
            {careerData.required_skills?.map((skill, i) => (
              <div key={skill.name} className={`card animate-fadeInUp stagger-${Math.min(i + 1, 4)}`} style={{ padding: '1.25rem' }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.625rem' }}>
                  <h4 style={{ fontSize: '0.95rem', fontWeight: 600 }}>{skill.name}</h4>
                  <span className={`badge ${skill.importance === 'critical' ? 'badge-weak' : skill.importance === 'high' ? 'badge-moderate' : 'badge-purple'}`} style={{ fontSize: '0.7rem' }}>
                    {skill.importance}
                  </span>
                </div>
                <p style={{ color: 'var(--text-muted)', fontSize: '0.8rem', lineHeight: 1.5 }}>{skill.description}</p>
                <div style={{ marginTop: '0.5rem' }}>
                  <span className="badge badge-purple" style={{ fontSize: '0.65rem' }}>{skill.category}</span>
                </div>
              </div>
            ))}
          </div>

          <div className="alert alert-info" style={{ marginBottom: '1.5rem', fontSize: '0.875rem' }}>
            <BookOpen size={16} style={{ flexShrink: 0 }} />
            <span>You'll be assessed on each skill. Technical skills include both theory questions and coding challenges. The assessment generates personalized questions using AI.</span>
          </div>

          <div style={{ display: 'flex', gap: '1rem' }}>
            <button className="btn btn-ghost" onClick={() => setStep(0)}>Back</button>
            <button id="career-start-assessment-btn" className="btn btn-primary btn-lg" style={{ flex: 1 }} onClick={loadQuestionsForAll} disabled={loadingQuestions}>
              {loadingQuestions ? <><span className="spinner" /> Generating Questions...</> : <><Code size={18} /> Start Assessment</>}
            </button>
          </div>
        </div>
      )}

      {/* STEP 2: Assessment */}
      {step === 2 && careerData && (
        <div className="animate-fadeIn">
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1.5rem' }}>
            <div>
              <h2 style={{ fontSize: '1.25rem' }}>Assessment: <span style={{ color: 'var(--primary)' }}>{careerGoal}</span></h2>
              <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>Complete theory and coding questions for each skill</p>
            </div>
            <button id="career-submit-btn" className="btn btn-primary" onClick={submitAssessment} disabled={submitting}>
              {submitting ? <><span className="spinner" /> Analyzing...</> : <><TrendingUp size={16} /> Submit All</>}
            </button>
          </div>

          {/* Skill tabs */}
          <div className="tabs" style={{ overflowX: 'auto', flexWrap: 'nowrap' }}>
            {careerData.required_skills?.map(skill => (
              <button key={skill.name}
                className={`tab-btn ${activeSkill === skill.name ? 'active' : ''}`}
                onClick={() => setActiveSkill(skill.name)}
                id={`skill-tab-${skill.name.replace(/\s+/g, '-')}`}
              >
                {skill.name}
              </button>
            ))}
          </div>

          {activeSkill && allQuestions[activeSkill] && (
            <div className="animate-fadeIn">
              {/* Theory Questions */}
              {allQuestions[activeSkill].theory_questions?.length > 0 && (
                <div style={{ marginBottom: '1.5rem' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '1rem' }}>
                    <BookOpen size={16} style={{ color: 'var(--primary)' }} />
                    <h3 style={{ fontSize: '0.95rem', fontWeight: 600 }}>Theory Questions</h3>
                    <span className="badge badge-purple" style={{ fontSize: '0.7rem' }}>{allQuestions[activeSkill].theory_questions.length} Qs</span>
                  </div>
                  {allQuestions[activeSkill].theory_questions.map((q, i) => (
                    <div key={q.id} className="card animate-fadeInUp" style={{ marginBottom: '1rem' }}>
                      <div style={{ display: 'flex', gap: '0.75rem', marginBottom: '0.875rem', alignItems: 'flex-start' }}>
                        <span style={{ background: 'var(--primary)', color: '#FFFFFF', width: 26, height: 26, borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '0.75rem', fontWeight: 600, flexShrink: 0 }}>{i + 1}</span>
                        <p style={{ fontSize: '0.9rem', lineHeight: 1.6 }}>{q.question}</p>
                      </div>
                      <textarea
                        id={`career-theory-${activeSkill}-${q.id}`}
                        className="form-textarea"
                        placeholder="Write your detailed answer..."
                        value={answers[activeSkill]?.[`theory_${q.id}`] || ''}
                        onChange={e => setAnswer(activeSkill, `theory_${q.id}`, e.target.value)}
                        style={{ minHeight: '110px' }}
                      />
                    </div>
                  ))}
                </div>
              )}

              {/* Coding Questions */}
              {allQuestions[activeSkill].coding_questions?.length > 0 && (
                <div style={{ marginBottom: '1.5rem' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '1rem' }}>
                    <Code size={16} style={{ color: 'var(--primary)' }} />
                    <h3 style={{ fontSize: '0.95rem', fontWeight: 600 }}>Coding Challenge</h3>
                    <span className="badge badge-purple" style={{ fontSize: '0.7rem' }}>Monaco Editor</span>
                  </div>
                  {allQuestions[activeSkill].coding_questions.map((q) => (
                    <div key={q.id} className="card animate-fadeInUp" style={{ marginBottom: '1rem' }}>
                      <div style={{ display: 'flex', gap: '0.75rem', marginBottom: '0.875rem', alignItems: 'flex-start' }}>
                        <span style={{ background: 'var(--primary)', color: '#FFFFFF', width: 26, height: 26, borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '0.75rem', fontWeight: 600, flexShrink: 0 }}>
                          <Code size={13} />
                        </span>
                        <p style={{ fontSize: '0.9rem', lineHeight: 1.6 }}>{q.question}</p>
                      </div>
                      {q.test_cases?.length > 0 && (
                        <div className="alert alert-info" style={{ marginBottom: '0.75rem', fontSize: '0.78rem' }}>
                          <strong>Test cases:</strong> {q.test_cases.join(' | ')}
                        </div>
                      )}
                      <CodeEditor
                        code={answers[activeSkill]?.[`coding_${q.id}`] || q.starter_code || '# Write your solution here\n'}
                        onChange={val => setAnswer(activeSkill, `coding_${q.id}`, val)}
                        onRun={() => runCode(activeSkill, q.id, answers[activeSkill]?.[`coding_${q.id}`] || q.starter_code || '')}
                        runResult={codeRuns[`${activeSkill}_coding_${q.id}`]}
                        running={running[`${activeSkill}_coding_${q.id}`]}
                      />
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* STEP 3: Results */}
      {step === 3 && results && (
        <div className="animate-fadeIn">
          {/* Header Score */}
          <div className="card" style={{ marginBottom: '1.5rem', display: 'flex', alignItems: 'center', gap: '2rem', flexWrap: 'wrap' }}>
            <ScoreRing score={results.overall_readiness} size={140} label="Career Readiness" />
            <div style={{ flex: 1, minWidth: 200 }}>
              <h2 style={{ fontSize: '1.5rem', marginBottom: '0.25rem' }}>
                {results.career_goal}
              </h2>
              <div style={{ display: 'flex', gap: '1.5rem', marginBottom: '1rem', flexWrap: 'wrap' }}>
                <div>
                  <div style={{ fontSize: '1.25rem', fontWeight: 700, color: 'var(--primary)' }}>{results.theory_score?.toFixed(0)}%</div>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Theory Score</div>
                </div>
                <div>
                  <div style={{ fontSize: '1.25rem', fontWeight: 700, color: 'var(--success)' }}>{results.coding_score?.toFixed(0)}%</div>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Coding Score</div>
                </div>
              </div>
              <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap' }}>
                {results.gap_analysis?.strong_skills?.map(s => <span key={s} className="badge badge-strong" style={{ fontSize: '0.7rem' }}>Strong: {s}</span>)}
                {results.gap_analysis?.weak_skills?.map(s => <span key={s} className="badge badge-weak" style={{ fontSize: '0.7rem' }}>Needs work: {s}</span>)}
              </div>
            </div>
          </div>

          <div className="grid-2" style={{ marginBottom: '1.5rem' }}>
            {/* Skill Scores Bar Chart */}
            <div className="card">
              <h3 style={{ marginBottom: '1.25rem', fontSize: '1rem' }}>Skill Score Breakdown</h3>
              {Object.entries(results.skill_scores).map(([skill, score]) => (
                <div key={skill} className="skill-bar-row">
                  <span className="skill-bar-label">{skill}</span>
                  <div className="skill-bar-track">
                    <div className="skill-bar-fill" style={{ width: `${score}%`, background: score >= 75 ? 'var(--success)' : score >= 50 ? 'var(--warning)' : 'var(--danger)' }} />
                  </div>
                  <span className="skill-bar-pct" style={{ color: SCORE_COLOR(score) }}>{score}%</span>
                </div>
              ))}
              {Object.keys(results.skill_scores).length > 3 && (
                <div style={{ marginTop: '1rem' }}>
                  <ResponsiveContainer width="100%" height={160}>
                    <RadarChart data={Object.entries(results.skill_scores).map(([s, v]) => ({ subject: s.length > 10 ? s.slice(0, 10) + '…' : s, score: v }))}>
                      <PolarGrid stroke="var(--border)" />
                      <PolarAngleAxis dataKey="subject" tick={{ fill: 'var(--text-secondary)', fontSize: 10 }} />
                      <Radar dataKey="score" stroke="var(--primary)" fill="var(--primary)" fillOpacity={0.15} strokeWidth={2} />
                    </RadarChart>
                  </ResponsiveContainer>
                </div>
              )}
            </div>

            {/* Gap Analysis */}
            <div className="card">
              <h3 style={{ marginBottom: '1rem', fontSize: '1rem' }}>Gap Analysis</h3>
              <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', lineHeight: 1.7, marginBottom: '1rem' }}>
                {results.gap_analysis?.analysis}
              </p>
              {results.gap_analysis?.critical_gaps?.length > 0 && (
                <div>
                  <p style={{ fontSize: '0.78rem', color: 'var(--danger)', fontWeight: 600, marginBottom: '0.5rem' }}>⚠ CRITICAL GAPS</p>
                  {results.gap_analysis.critical_gaps.map(g => (
                    <div key={g.skill} style={{ padding: '0.625rem', background: 'var(--danger-soft)', borderRadius: 16, marginBottom: '0.375rem', border: '1px solid var(--border)' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.25rem' }}>
                        <span style={{ fontWeight: 600, fontSize: '0.85rem' }}>{g.skill}</span>
                        <span style={{ color: 'var(--danger)', fontSize: '0.8rem' }}>{g.current_level}%</span>
                      </div>
                      <p style={{ color: 'var(--text-secondary)', fontSize: '0.78rem' }}>{g.gap_description}</p>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Career Roadmap */}
          <div className="card" style={{ marginBottom: '1.5rem' }}>
            <h3 style={{ marginBottom: '0.5rem', fontSize: '1rem' }}>Your Personalized Career Roadmap</h3>
            <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', lineHeight: 1.7, marginBottom: '1.5rem', padding: '1rem', background: 'var(--primary-soft)', borderRadius: 16, border: '1px solid var(--border)' }}>
              {results.recommendations}
            </p>
            {results.roadmap?.map((item, i) => (
              <div key={i} className="roadmap-step">
                <div className="roadmap-number">{item.step || i + 1}</div>
                <div style={{ flex: 1 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '0.25rem' }}>
                    <h4 style={{ fontSize: '0.95rem', fontWeight: 600 }}>{item.action}</h4>
                    {item.duration && <span className="badge badge-purple" style={{ fontSize: '0.7rem' }}>{item.duration}</span>}
                  </div>
                  {item.resources?.length > 0 && (
                    <div style={{ display: 'flex', gap: '0.375rem', flexWrap: 'wrap', marginTop: '0.25rem' }}>
                      {item.resources.map((r, j) => (
                        <span key={j} style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', background: 'var(--card)', padding: '0.125rem 0.5rem', borderRadius: '4px' }}>{r}</span>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>

          <div style={{ display: 'flex', gap: '1rem' }}>
            <button id="career-restart-btn" className="btn btn-primary" onClick={reset}>
              <RotateCcw size={16} /> New Career Assessment
            </button>
          </div>
        </div>
      )}
    </div>
  )
}