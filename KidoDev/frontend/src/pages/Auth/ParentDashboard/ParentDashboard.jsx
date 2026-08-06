import React, { useState, useEffect, useMemo } from 'react';
import { supabase } from '../../../utils/supabaseClient';
import { useNavigate } from 'react-router-dom';
import { requestCurriculum } from '../../../agents/AgentOrchestrator';
import {
    FaUserGraduate, FaChartLine, FaKey, FaSignOutAlt,
    FaStar, FaTrophy, FaUsers, FaShieldAlt, FaLock, FaCog,
    FaSync, FaExclamationTriangle, FaCheckCircle, FaChevronRight,
    FaEye, FaEyeSlash, FaTimes, FaUserAlt, FaCircleNotch,
    FaChevronDown, FaChevronUp, FaChartBar
} from 'react-icons/fa';
import { useTheme } from '../../../utils/ThemeContext';
import SpriteLoader from '../../../components/Loader/SpriteLoader';

/* ─────────────────────────────────────
   HELPERS
   ───────────────────────────────────── */
const LEVEL_NAMES = {
    1: "Beginner", 2: "Explorer", 3: "Creator", 4: "Builder",
    5: "Expert", 6: "Wizard", 7: "Legend", 8: "Master"
};

const formatDate = (dateString) => {
    if (!dateString) return 'N/A';
    const d = new Date(dateString);
    if (isNaN(d.getTime())) return 'N/A';
    return d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
};

const getExpiryDaysLeft = (dateString) => {
    if (!dateString) return null;
    const approvalDate = new Date(dateString);
    if (isNaN(approvalDate.getTime())) return null;
    const expiryDate = new Date(approvalDate.getTime() + 30 * 24 * 60 * 60 * 1000);
    const today = new Date();
    const diffTime = expiryDate.getTime() - today.getTime();
    return Math.ceil(diffTime / (1000 * 60 * 60 * 24));
};

const numericLevel = (levelStr) => {
    const m = String(levelStr || '').match(/\d+/);
    return m ? parseInt(m[0]) : 1;
};

const scoreColor = (score) => {
    if (score >= 80) return '#10B981';
    if (score >= 50) return '#F59E0B';
    return '#EF4444';
};

const scoreLabel = (score) => {
    if (score >= 80) return 'Excellent';
    if (score >= 50) return 'Good';
    return 'Keep Practising';
};

const generateParentKey = () => {
    const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789';
    let key = '';
    for(let i=0; i<4; i++) {
        key += chars.charAt(Math.floor(Math.random() * chars.length));
    }
    return key;
};

/* ─────────────────────────────────────
   LESSON DETAIL PANEL
   ───────────────────────────────────── */
const LessonDetailPanel = ({ child, allLessons, completions }) => {
    const level = numericLevel(child.current_level);

    const levelLessons = useMemo(
        () => allLessons
            .filter(l => parseInt(l.class_level) === level)
            .sort((a, b) => (a.order_index || 0) - (b.order_index || 0)),
        [allLessons, level]
    );

    const childComps = completions[child.id] || [];
    const completedIds = new Set(childComps.map(c => c.lesson_id));
    const remainingLessons = levelLessons.filter(l => !completedIds.has(l.id));
    const nextLesson = remainingLessons[0] || null;

    const levelCompletions = childComps
        .filter(c => levelLessons.some(l => l.id === c.lesson_id))
        .sort((a, b) => new Date(b.completed_at) - new Date(a.completed_at));
    const lastComp = levelCompletions[0] || null;
    const currentLesson = lastComp ? allLessons.find(l => l.id === lastComp.lesson_id) : null;

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
            {/* ── Last Completed Lesson ── */}
            <div>
                <div className="lesson-section-label text-primary">Last Completed Lesson</div>
                {currentLesson ? (
                    <LessonInfoBox lesson={currentLesson} completion={lastComp} showScore />
                ) : (
                    <EmptyNote>No lessons completed in Level {level} yet. Encourage them to start!</EmptyNote>
                )}
            </div>

            {/* ── Next Lesson ── */}
            <div>
                <div className="lesson-section-label text-success">Next Lesson to Practice at Home</div>
                {nextLesson ? (
                    <LessonInfoBox lesson={nextLesson} isNext />
                ) : (
                    <EmptyNote>All lessons in Level {level} done! Ready for the next level.</EmptyNote>
                )}
            </div>

            {/* ── All Lessons in Level ── */}
            <div>
                <div className="lesson-section-label" style={{ color: '#0EA5E9' }}>All Lessons — Level {level}</div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                    {levelLessons.length === 0 ? (
                        <EmptyNote>No lessons found for this level.</EmptyNote>
                    ) : levelLessons.map((lesson, i) => {
                        const comp = childComps.find(c => c.lesson_id === lesson.id);
                        const done = !!comp;
                        return (
                            <div key={lesson.id} style={{
                                background: done ? '#F0FDF4' : '#fff',
                                border: `1px solid ${done ? '#BBF7D0' : '#E2E8F0'}`,
                                borderRadius: 14, padding: '10px 14px',
                                display: 'flex', alignItems: 'center', gap: 12
                            }}>
                                <div style={{
                                    width: 32, height: 32, borderRadius: 10, flexShrink: 0,
                                    background: done ? '#10B981' : '#F1F5F9',
                                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                                    color: done ? '#fff' : '#94A3B8', fontWeight: 900, fontSize: '0.75rem'
                                }}>
                                    {done ? '✓' : i + 1}
                                </div>
                                <div style={{ flex: 1, minWidth: 0 }}>
                                    <div style={{ fontWeight: 800, fontSize: '0.85rem', color: '#1E293B', marginBottom: 2 }}>
                                        {lesson.title}
                                    </div>
                                    <div style={{ fontSize: '0.75rem', color: '#64748B' }}>
                                        Goal: {lesson.objective}
                                    </div>
                                </div>
                                <div style={{ flexShrink: 0, textAlign: 'right' }}>
                                    {done ? (
                                        <>
                                            <div style={{ fontWeight: 900, fontSize: '0.82rem', color: scoreColor(comp.score || 0) }}>
                                                {comp.score ?? '--'}%
                                            </div>
                                            <div style={{ fontSize: '0.65rem', color: '#94A3B8', fontWeight: 700 }}>
                                                {comp.xp_earned || 0} XP
                                            </div>
                                        </>
                                    ) : (
                                        <span style={{
                                            fontSize: '0.7rem', fontWeight: 800, color: '#94A3B8',
                                            background: '#F1F5F9', borderRadius: 8, padding: '3px 10px'
                                        }}>Not yet</span>
                                    )}
                                </div>
                            </div>
                        );
                    })}
                </div>
            </div>

            {/* ── Parent Tip ── */}
            <div style={{
                background: 'linear-gradient(135deg, #FFFBEB, #FFF7ED)',
                border: '1px solid #FDE68A', borderRadius: 16, padding: '14px 18px'
            }}>
                <div style={{ fontWeight: 900, fontSize: '0.82rem', color: '#92400E', marginBottom: 5 }}>
                    How to Help at Home
                </div>
                <div style={{ fontSize: '0.8rem', color: '#78350F', lineHeight: 1.7 }}>
                    Ask your child to explain the <strong>next lesson steps</strong> to you out loud —
                    this is one of the best ways to reinforce their learning. You don't need to know
                    coding; just listen, encourage, and celebrate every small win!
                </div>
            </div>
        </div>
    );
};

/* ─────────────────────────────────────
   LESSON INFO BOX
   ───────────────────────────────────── */
const LessonInfoBox = ({ lesson, completion, showScore, isNext }) => (
    <div style={{
        background: isNext ? 'linear-gradient(135deg, #F0FDF4, #ECFDF5)' : '#fff',
        border: `1.5px solid ${isNext ? '#BBF7D0' : '#E2E8F0'}`,
        borderRadius: 16, padding: '16px 18px'
    }}>
        <div style={{ display: 'flex', gap: 12, alignItems: 'flex-start', marginBottom: 12 }}>
            <div style={{
                width: 40, height: 40, borderRadius: 12, flexShrink: 0,
                background: isNext ? '#10B981' : '#0EA5E9',
                color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontWeight: 900, fontSize: '0.62rem', letterSpacing: 0.5,
                boxShadow: isNext ? '0 4px 14px #10B98140' : '0 4px 14px #0EA5E940'
            }}>
                {isNext ? 'NEXT' : 'DONE'}
            </div>
            <div style={{ flex: 1 }}>
                <div style={{ fontWeight: 900, fontSize: '0.95rem', color: '#1E293B', marginBottom: 3 }}>
                    {lesson.title}
                </div>
                <div style={{ fontSize: '0.8rem', color: '#64748B', marginBottom: showScore ? 8 : 0 }}>
                    Goal: <strong>{lesson.objective}</strong>
                </div>
                {showScore && completion && (
                    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 6 }}>
                        <span style={{
                            background: scoreColor(completion.score || 0) + '18',
                            color: scoreColor(completion.score || 0),
                            border: `1px solid ${scoreColor(completion.score || 0)}40`,
                            borderRadius: 8, padding: '3px 10px', fontWeight: 900, fontSize: '0.75rem'
                        }}>
                            Score: {completion.score ?? '--'}% — {scoreLabel(completion.score || 0)}
                        </span>
                        <span style={{
                            background: '#FFFBEB', color: '#92400E', border: '1px solid #FDE68A',
                            borderRadius: 8, padding: '3px 10px', fontWeight: 900, fontSize: '0.75rem'
                        }}>
                            {completion.xp_earned || 0} XP earned
                        </span>
                    </div>
                )}
            </div>
        </div>

        {(lesson.steps || []).length > 0 && (
            <>
                <div style={{
                    fontSize: '0.68rem', fontWeight: 900, color: '#64748B',
                    textTransform: 'uppercase', letterSpacing: 1, marginBottom: 8
                }}>
                    {isNext ? 'Practice these steps at home:' : 'What this lesson covered:'}
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                    {lesson.steps.map((step, i) => (
                        <div key={i} style={{
                            display: 'flex', gap: 10, alignItems: 'flex-start',
                            background: '#fff', border: '1px solid #E2E8F0',
                            borderRadius: 12, padding: '10px 12px'
                        }}>
                            <div style={{
                                minWidth: 22, height: 22, borderRadius: 7, flexShrink: 0,
                                background: isNext ? '#10B981' : '#0EA5E9',
                                color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center',
                                fontWeight: 900, fontSize: '0.7rem'
                            }}>{i + 1}</div>
                            <div>
                                <div style={{ fontWeight: 800, fontSize: '0.82rem', color: '#1E293B', marginBottom: 2 }}>
                                    {step.title}
                                </div>
                                <div style={{ fontSize: '0.78rem', color: '#475569', lineHeight: 1.6 }}>
                                    {step.desc}
                                </div>
                            </div>
                        </div>
                    ))}
                </div>
                {isNext && (
                    <div style={{
                        marginTop: 12, background: '#EFF6FF', border: '1px solid #BFDBFE',
                        borderRadius: 12, padding: '10px 14px', fontSize: '0.78rem', color: '#1D4ED8', fontWeight: 700
                    }}>
                        Ask your child to open the Kido app and try this lesson. Sit with them and read each step together!
                    </div>
                )}
            </>
        )}

        {lesson.is_prompt_project && lesson.perfect_prompt && (
            <div style={{ marginTop: 12 }}>
                <div style={{ fontSize: '0.68rem', fontWeight: 900, color: '#64748B', textTransform: 'uppercase', letterSpacing: 1, marginBottom: 6 }}>
                    The perfect answer to type:
                </div>
                <div style={{
                    background: '#F0FDF4', border: '1px solid #BBF7D0',
                    borderRadius: 12, padding: '10px 14px',
                    fontSize: '0.85rem', color: '#166534', fontStyle: 'italic', lineHeight: 1.7
                }}>
                    "{lesson.perfect_prompt}"
                </div>
            </div>
        )}
    </div>
);

/* ─────────────────────────────────────
   EMPTY NOTE
   ───────────────────────────────────── */
const EmptyNote = ({ children }) => (
    <div style={{
        background: '#F8FAFC', border: '1px solid #E2E8F0', borderRadius: 12,
        padding: '14px 16px', fontSize: '0.83rem', color: '#64748B',
        fontStyle: 'italic', textAlign: 'center'
    }}>
        {children}
    </div>
);

/* ─────────────────────────────────────
   AI CHILD INSIGHTS PANEL (Practice These More & Data Insights)
   ───────────────────────────────────── */
const insightsCache = {};

const AiChildInsightsPanel = ({ child, completions }) => {
    const getCachedInsights = (childId) => {
        if (!childId) return null;
        if (insightsCache[childId]) return insightsCache[childId];
        try {
            const stored = sessionStorage.getItem(`kd_curriculum_cache_${childId}`);
            if (stored) return JSON.parse(stored);
        } catch {}
        return null;
    };

    const initialData = getCachedInsights(child?.id);
    const [loading, setLoading] = useState(!initialData);
    const [curriculum, setCurriculum] = useState(initialData);

    const handleRefresh = async () => {
        if (!child?.id) return;
        setLoading(true);
        try {
            const childComps = completions[child.id] || [];
            const data = await requestCurriculum({
                childId: child.id,
                completedLessons: childComps,
                level: child.current_level || `Class ${child.numericLevel || 1}`,
                totalXp: child.totalXp || (child.total_xp || 0),
                totalCompleted: child.totalCompleted || childComps.length,
                forceRefresh: true,
            });
            insightsCache[child.id] = data;
            setCurriculum(data);
        } catch (e) {
            console.warn("Curriculum refresh error:", e);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        if (!child?.id) return;

        const cached = getCachedInsights(child.id);
        if (cached) {
            setCurriculum(cached);
            setLoading(false);
            return;
        }

        let isMounted = true;
        const fetchInsights = async () => {
            setLoading(true);
            try {
                const childComps = completions[child.id] || [];
                const data = await requestCurriculum({
                    childId: child.id,
                    completedLessons: childComps,
                    level: child.current_level || `Class ${child.numericLevel || 1}`,
                    totalXp: child.totalXp || (child.total_xp || 0),
                    totalCompleted: child.totalCompleted || childComps.length,
                });
                insightsCache[child.id] = data;
                if (isMounted) setCurriculum(data);
            } catch (e) {
                console.warn("Curriculum fetch error:", e);
            } finally {
                if (isMounted) setLoading(false);
            }
        };
        fetchInsights();
        return () => { isMounted = false; };
    }, [child?.id]);

    if (loading) return (
        <div style={{ textAlign: 'center', padding: '24px 16px', background: '#F8FAFC', borderRadius: 16, border: '1px solid #E2E8F0', marginBottom: 20 }}>
            <FaCircleNotch className="fa-spin-custom text-primary mb-2" size={22} />
            <div style={{ fontSize: '0.82rem', color: '#64748B', fontWeight: 700 }}>
                AI is analyzing {child.name}'s performance data to generate practice recommendations...
            </div>
        </div>
    );

    if (!curriculum) return null;

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16, marginBottom: 20 }}>
            {/* AI Learning Summary */}
            <div style={{
                background: 'linear-gradient(135deg, #EFF6FF 0%, #E0F2FE 100%)',
                border: '1.5px solid #BAE6FD',
                borderRadius: 18, padding: '16px',
                boxShadow: '0 4px 14px rgba(2,132,199,0.06)'
            }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                    <div style={{ fontWeight: 900, fontSize: '0.8rem', color: '#0284C7', letterSpacing: '0.05em', textTransform: 'uppercase', display: 'flex', alignItems: 'center', gap: 6 }}>
                        <span>🧠</span> Performance Analysis &amp; Progress Summary
                    </div>
                    <button onClick={handleRefresh} disabled={loading} style={{ background: '#FFFFFF', border: '1px solid #BAE6FD', color: '#0284C7', borderRadius: 8, padding: '3px 8px', fontSize: '0.72rem', fontWeight: 700, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 4 }}>
                        <FaSync className={loading ? "fa-spin-custom" : ""} size={10} /> Refresh AI
                    </button>
                </div>
                <div style={{ fontSize: '0.85rem', color: '#0F172A', fontWeight: 600, lineHeight: 1.6, marginBottom: 12 }}>
                    {curriculum.learning_path_summary}
                </div>
                <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                    {curriculum.weekly_goal && (
                        <div style={{ background: '#F0FDF4', border: '1px solid #BBF7D0', borderRadius: 12, padding: '8px 12px', flex: 1, minWidth: 140 }}>
                            <div style={{ color: '#166534', fontWeight: 900, fontSize: '0.68rem', textTransform: 'uppercase', marginBottom: 2 }}>Weekly Goal</div>
                            <div style={{ color: '#15803D', fontSize: '0.8rem', fontWeight: 800 }}>{curriculum.weekly_goal}</div>
                        </div>
                    )}
                    {curriculum.next_challenge && (
                        <div style={{ background: '#FFFBEB', border: '1px solid #FDE68A', borderRadius: 12, padding: '8px 12px', flex: 1, minWidth: 140 }}>
                            <div style={{ color: '#92400E', fontWeight: 900, fontSize: '0.68rem', textTransform: 'uppercase', marginBottom: 2 }}>Next Challenge</div>
                            <div style={{ color: '#B45309', fontSize: '0.8rem', fontWeight: 800 }}>{curriculum.next_challenge}</div>
                        </div>
                    )}
                </div>
            </div>

            {/* Strengths & Weaknesses Grid */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                {/* Strengths */}
                <div style={{ background: '#F0FDF4', border: '1.5px solid #BBF7D0', borderRadius: 18, padding: '16px' }}>
                    <div style={{ fontWeight: 900, fontSize: '0.82rem', color: '#15803D', marginBottom: 10, display: 'flex', alignItems: 'center', gap: 6 }}>
                        <FaCheckCircle color="#10B981" /> Strengths
                    </div>
                    {curriculum.strengths?.length > 0 ? curriculum.strengths.map((s, i) => (
                        <div key={i} style={{ background: '#FFFFFF', border: '1px solid #DCFCE7', borderRadius: 10, padding: '8px 10px', marginBottom: 6, fontSize: '0.78rem', fontWeight: 700, color: '#166534', display: 'flex', alignItems: 'center', gap: 6 }}>
                            <span style={{ color: '#22c55e' }}>✓</span> {s}
                        </div>
                    )) : (
                        <div style={{ fontSize: '0.78rem', color: '#64748B', fontStyle: 'italic' }}>Complete more lessons to reveal strengths.</div>
                    )}
                </div>

                {/* Weaknesses / Skill Gaps */}
                <div style={{ background: '#FEF2F2', border: '1.5px solid #FECACA', borderRadius: 18, padding: '16px' }}>
                    <div style={{ fontWeight: 900, fontSize: '0.82rem', color: '#B91C1C', marginBottom: 10, display: 'flex', alignItems: 'center', gap: 6 }}>
                        <FaExclamationTriangle color="#EF4444" /> Areas to Improve
                    </div>
                    {curriculum.skill_gaps?.length > 0 ? curriculum.skill_gaps.map((g, i) => (
                        <div key={i} style={{ background: '#FFFFFF', border: '1px solid #FEE2E2', borderRadius: 10, padding: '8px 10px', marginBottom: 6, fontSize: '0.78rem', fontWeight: 700, color: '#991B1B', display: 'flex', alignItems: 'center', gap: 6 }}>
                            <span style={{ color: '#ef4444' }}>•</span> {g}
                        </div>
                    )) : (
                        <div style={{ fontSize: '0.78rem', color: '#64748B', fontStyle: 'italic' }}>No specific gaps identified yet.</div>
                    )}
                </div>
            </div>
        </div>
    );
};

/* ─────────────────────────────────────
   PROGRESS MODAL  — restyled with AI Insights
   ───────────────────────────────────── */
const ProgressModal = ({ child, allLessons, completions, onClose }) => {
    const [activeTab, setActiveTab] = useState('insights'); // 'insights' or 'lessons'
    const level = numericLevel(child.current_level);
    const levelName = LEVEL_NAMES[level] || 'Explorer';
    const childComps = completions[child.id] || [];
    const levelLessons = allLessons.filter(l => parseInt(l.class_level) === level);
    const completedInLevel = childComps.filter(c => levelLessons.some(ll => ll.id === c.lesson_id)).length;
    const mastery = levelLessons.length > 0 ? Math.round((completedInLevel / levelLessons.length) * 100) : 0;
    const headerBg = child.gender === 'Boy' ? '#2563EB' : '#DC2626';

    return (
        <div className="modal-overlay-premium" onClick={onClose}>
            <div
                className="modal-card-premium card border-0 shadow-2xl rounded-5 bg-white overflow-hidden"
                style={{ maxWidth: '540px' }}
                onClick={e => e.stopPropagation()}
            >
                {/* ── Header bar ── */}
                <div
                    className="p-3 px-4 text-white d-flex justify-content-between align-items-center position-relative"
                    style={{ background: headerBg }}
                >
                    <div className="d-flex align-items-center gap-3">
                        <div
                            className="bg-white rounded-circle fw-black fs-5 d-flex align-items-center justify-content-center shadow-sm flex-shrink-0"
                            style={{ width: 42, height: 42, color: headerBg }}
                        >
                            {child.name.charAt(0)}
                        </div>
                        <div>
                            <h5 className="fw-black mb-0 ls-tight">{child.name}</h5>
                            <p className="mb-0 fw-bold opacity-75 x-small">{levelName} · Level {level}</p>
                        </div>
                    </div>
                    <button onClick={onClose} className="btn-close-premium" style={{ position: 'static', width: 32, height: 32 }} aria-label="Close">
                        <FaTimes size={13} />
                    </button>
                </div>

                {/* ── Stats strip ── */}
                <div className="px-4 py-3 border-bottom d-flex gap-3 flex-wrap" style={{ background: '#F8FAFC' }}>
                    {/* Mastery bar */}
                    <div style={{ flex: '1 1 100%' }}>
                        <div className="d-flex justify-content-between mb-1">
                            <span className="fw-black text-muted x-small text-uppercase" style={{ letterSpacing: '0.08em' }}>Mission Mastery</span>
                            <span className="fw-black x-small" style={{ color: headerBg }}>{mastery}%</span>
                        </div>
                        <div className="progress rounded-pill bg-light border" style={{ height: 8 }}>
                            <div
                                className="progress-bar rounded-pill"
                                style={{ width: `${mastery}%`, background: headerBg, transition: 'width 0.8s ease-in-out' }}
                            />
                        </div>
                    </div>
                    {/* KPI chips */}
                    <div className="d-flex gap-2 w-100">
                        <div className="p-2 bg-white border rounded-4 text-center flex-fill shadow-sm">
                            <div className="fw-black small text-dark">{child.totalCompleted || 0}</div>
                            <div className="text-muted x-small fw-bold">Total Done</div>
                        </div>
                        <div className="p-2 bg-white border rounded-4 text-center flex-fill shadow-sm">
                            <div className="fw-black small text-dark">{child.totalXp || 0}</div>
                            <div className="text-muted x-small fw-bold">Total XP</div>
                        </div>
                        <div className="p-2 bg-white border rounded-4 text-center flex-fill shadow-sm">
                            <div className="fw-black small text-dark">{completedInLevel}/{levelLessons.length}</div>
                            <div className="text-muted x-small fw-bold">Level {level} Done</div>
                        </div>
                    </div>
                </div>

                {/* ── Tab Switcher ── */}
                <div className="px-4 pt-3 pb-0 bg-white border-bottom">
                    <div className="d-flex p-1 bg-light rounded-4 border">
                        <button
                            onClick={() => setActiveTab('insights')}
                            className={`btn flex-fill py-2 rounded-4 fw-black border-0 small transition-all ${activeTab === 'insights' ? 'btn-white shadow text-primary' : 'text-muted'}`}
                            style={{ fontSize: '0.78rem' }}
                        >
                            🧠 AI INSIGHTS &amp; STRENGTHS
                        </button>
                        <button
                            onClick={() => setActiveTab('lessons')}
                            className={`btn flex-fill py-2 rounded-4 fw-black border-0 small transition-all ${activeTab === 'lessons' ? 'btn-white shadow text-primary' : 'text-muted'}`}
                            style={{ fontSize: '0.78rem' }}
                        >
                            📚 LESSON ROADMAP
                        </button>
                    </div>
                </div>

                {/* ── Scrollable body ── */}
                <div className="progress-modal-body p-3 p-md-4">
                    {activeTab === 'insights' ? (
                        <AiChildInsightsPanel child={child} completions={completions} />
                    ) : (
                        <LessonDetailPanel child={child} allLessons={allLessons} completions={completions} />
                    )}
                </div>
            </div>
        </div>
    );
};

/* ─────────────────────────────────────
   MAIN PARENT DASHBOARD
   ───────────────────────────────────── */
const ParentDashboard = () => {
    const { themeAssets } = useTheme();
    const [children, setChildren] = useState([]);
    const [loading, setLoading] = useState(true);
    const [hasInitialLoaded, setHasInitialLoaded] = useState(false);
    const [processing, setProcessing] = useState(false);
    const [selectedChild, setSelectedChild] = useState(null);
    const [progressChild, setProgressChild] = useState(null);
    const [isLoggingOut, setIsLoggingOut] = useState(false);
    const [parentProfile, setParentProfile] = useState(null);
    const [allLessons, setAllLessons] = useState([]);
    const [completions, setCompletions] = useState({});

    const [activeView, setActiveView] = useState('explorers'); // 'explorers' or 'enroll'
    const [newChild, setNewChild] = useState({ name: '', classLevel: 'Class 1', age: '', gender: 'Boy' });
    const [selectedChildIds, setSelectedChildIds] = useState([]);
    const [combineScreenshotFile, setCombineScreenshotFile] = useState(null);

    const [editingKey, setEditingKey] = useState(false);
    const [newSecretKey, setNewSecretKey] = useState('');
    const [error, setError] = useState('');
    const [success, setSuccess] = useState('');

    const navigate = useNavigate();

    useEffect(() => {
        const role = localStorage.getItem('kido_auth_role');
        if (role === 'kid') navigate('/levels');
        else if (role === 'school') navigate('/school-dashboard');
    }, [navigate]);

    useEffect(() => {
        window.scrollTo(0, 0);
        let isMounted = true;
        const safetyTimeout = setTimeout(() => {
            if (isMounted) { console.warn("Dashboard sync timed out."); setLoading(false); }
        }, 12000);
        fetchDashboardData(false).finally(() => { if (isMounted) clearTimeout(safetyTimeout); });
        return () => { isMounted = false; clearTimeout(safetyTimeout); };
    }, []);

    const generateSecretKey = (name, classLevel) => {
        const firstWord = (name || '').trim().split(/\s+/)[0];
        const classNum = (classLevel || '').replace(/\D/g, '');
        return `${firstWord}${classNum}`.toUpperCase();
    };

    const handleAddChild = async (e) => {
        e.preventDefault();
        setProcessing(true);
        setError('');
        setSuccess('');
        try {
            const secretKey = generateSecretKey(newChild.name, newChild.classLevel);
            const { error: insertError } = await supabase.from('children').insert([{
                parent_id: parentProfile.id,
                name: newChild.name,
                current_level: newChild.classLevel,
                age: newChild.age ? parseInt(newChild.age) : null,
                gender: newChild.gender,
                secret_key: secretKey,
                payment_status: 'unpaid',
                parent_cnic: parentProfile.cnic,
                parent_name: parentProfile.full_name,
                parent_email: parentProfile.email
            }]);
            if (insertError) throw insertError;
            setSuccess(`Explorer enrolled! Secret Key: ${secretKey}`);
            setNewChild({ name: '', classLevel: 'Class 1', age: '', gender: 'Boy' });
            fetchDashboardData(true);
        } catch (err) {
            setError(err.message);
        } finally {
            setProcessing(false);
        }
    };

    const handleCombinePaymentSubmit = async (e) => {
        if (e && typeof e.preventDefault === 'function') {
            e.preventDefault();
        }
        if (!combineScreenshotFile || selectedChildIds.length === 0) return;
        setProcessing(true);
        setError('');
        setSuccess('');
        try {
            const { data: { user: authUser } } = await supabase.auth.getUser();
            const parentId = parentProfile?.id || authUser?.id;
            if (!parentId) throw new Error("Could not identify parent profile ID. Please log in again.");

            const fileExt = (combineScreenshotFile.name.split('.').pop() || '').toLowerCase();
            const fileName = `parent_bulk_${parentId}_${Date.now()}.${fileExt}`;
            
            const { error: uploadError } = await supabase.storage
                .from('payments')
                .upload(fileName, combineScreenshotFile, {
                    contentType: combineScreenshotFile.type || 'application/octet-stream',
                    cacheControl: '3600',
                    upsert: true
                });
            if (uploadError) throw uploadError;

            const { data } = supabase.storage.from('payments').getPublicUrl(fileName);
            const publicUrl = data.publicUrl;

            const { error: dbError } = await supabase.from('children')
                .update({ screenshot_url: publicUrl, payment_status: 'pending' })
                .in('id', selectedChildIds);
            if (dbError) throw dbError;

            setSuccess("Payment screenshot submitted successfully!");
            setCombineScreenshotFile(null);
            setSelectedChildIds([]);
            fetchDashboardData(true);
        } catch (err) {
            console.error("Payment Submission Error details:", err);
            setError(err.message || "Failed to submit screenshot proof.");
        } finally {
            setProcessing(false);
        }
    };

    const fetchDashboardData = async (isSilent = false) => {
        if (!isSilent) setLoading(true);
        setProcessing(true);
        try {
            const { data: { user: authUser } } = await supabase.auth.getUser();
            if (!authUser) { navigate('/auth'); return; }

            const { data: profile } = await supabase
                .from('parent_profiles').select('*').eq('id', authUser.id).single();
            
            if (profile && !profile.co_mentor_key) {
                const newKey = generateParentKey();
                await supabase.from('parent_profiles').update({ co_mentor_key: newKey }).eq('id', authUser.id);
                profile.co_mentor_key = newKey;
            }

            setParentProfile(profile);

            let { data: childrenData, error: childError } = await supabase
                .from('children').select('*').eq('parent_id', authUser.id);
            if (childError || !childrenData) {
                await new Promise(r => setTimeout(r, 1000));
                const retry = await supabase.from('children').select('*').eq('parent_id', authUser.id);
                childrenData = retry.data;
            }
            if (!childrenData) throw new Error("Could not retrieve student data.");

            const { data: lessonsData } = await supabase
                .from('lessons')
                .select('id, title, objective, steps, class_level, order_index, is_prompt_project, perfect_prompt, prompt_milestones');
            setAllLessons(lessonsData || []);

            const childIds = childrenData.map(c => c.id).filter(Boolean);
            const secretKeys = childrenData.map(c => c.secret_key).filter(Boolean);
            const queryIds = Array.from(new Set([...childIds, ...secretKeys]));
            const isUUID = str => typeof str === 'string' && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(str);
            const validUuidQueryIds = queryIds.filter(isUUID);

            let completionsData = [];
            if (validUuidQueryIds.length > 0) {
                const [byChild, byUser] = await Promise.all([
                    supabase.from('lesson_completions').select('*').in('child_id', validUuidQueryIds),
                    supabase.from('lesson_completions').select('*').in('user_id', validUuidQueryIds)
                ]);
                const map = new Map();
                (byChild.data || []).forEach(item => {
                    const key = `${item.child_id || item.user_id}_${item.lesson_id}`;
                    map.set(key, item);
                });
                (byUser.data || []).forEach(item => {
                    const key = `${item.child_id || item.user_id}_${item.lesson_id}`;
                    map.set(key, item);
                });
                completionsData = Array.from(map.values());
            }


            const groupedCompletions = {};
            completionsData.forEach(comp => {
                const matchedChild = childrenData.find(c =>
                    c.id === comp.child_id || c.id === comp.user_id ||
                    c.secret_key === comp.child_id || c.secret_key === comp.user_id
                );
                const cId = matchedChild ? matchedChild.id : (comp.child_id || comp.user_id);
                if (cId) {
                    if (!groupedCompletions[cId]) groupedCompletions[cId] = [];
                    groupedCompletions[cId].push(comp);
                }
            });
            setCompletions(groupedCompletions);

            const enriched = childrenData.map(child => {
                const childComps = groupedCompletions[child.id] || [];
                const levelMatch = child.current_level?.match(/\d+/);
                const level = levelMatch ? parseInt(levelMatch[0]) : 1;
                const levelLessons = (lessonsData || []).filter(l => parseInt(l.class_level) === level);
                const completedInLevel = childComps.filter(c => levelLessons.some(ll => ll.id === c.lesson_id)).length;
                return {
                    ...child,
                    numericLevel: level,
                    totalCompleted: childComps.length,
                    levelMissionsTotal: levelLessons.length,
                    levelMissionsCompleted: completedInLevel,
                    mastery: levelLessons.length > 0 ? Math.round((completedInLevel / levelLessons.length) * 100) : 0,
                    totalXp: (child.total_xp || 0) || (childComps.length * 50)
                };
            });
            setChildren(enriched);
        } catch (err) {
            console.error("Dashboard Fetch Error:", err);
            setError("Failed to sync dashboard data.");
        } finally {
            setLoading(false);
            setHasInitialLoaded(true);
            setProcessing(false);
        }
    };

    const handleUpdateSecretKey = async (e) => {
        e.preventDefault();
        if (!selectedChild || !newSecretKey) return;
        setIsLoggingOut(true);
        setError('');
        try {
            const { data: { user } } = await supabase.auth.getUser();
            if (!user) throw new Error("Unauthorized");
            const { error: updateError } = await supabase
                .from('children').update({ secret_key: newSecretKey })
                .eq('id', selectedChild.id).eq('parent_id', user.id);
            if (updateError) throw updateError;
            setChildren(children.map(c => c.id === selectedChild.id ? { ...c, secret_key: newSecretKey } : c));
            setSelectedChild({ ...selectedChild, secret_key: newSecretKey });
            setEditingKey(false);
            setNewSecretKey('');
            setSuccess("Student secret key updated!");
            setTimeout(() => setSuccess(''), 3000);
        } catch (err) {
            setError(err.message);
        } finally {
            setIsLoggingOut(false);
        }
    };

    const stats = useMemo(() => {
        const totalXp = children.reduce((s, c) => s + (c.totalXp || 0), 0);
        const totalMissions = children.reduce((s, c) => s + (c.totalCompleted || 0), 0);
        const avgMastery = children.length > 0 ? Math.round(children.reduce((s, c) => s + (c.mastery || 0), 0) / children.length) : 0;
        return { totalXp, totalMissions, avgMastery };
    }, [children]);

    if (loading && !hasInitialLoaded) return <SpriteLoader />;

    return (
        <div className="parent-dashboard-premium bg-white min-vh-100 position-relative" style={{ paddingTop: '90px' }}>
            <div className="container-fluid px-3 px-lg-5">
                {/* ─── HEADER ─── */}
                <div className="row mb-4 align-items-center">
                    <div className="col-8">
                        <h1 className="fw-black text-dark ls-tight mb-1 mobile-fs-4">Parent Hub</h1>
                        <p className="text-muted fw-bold small d-none d-md-block">
                            Welcome back, <strong>{parentProfile?.full_name || 'Guardian'}</strong>
                        </p>
                    </div>
                    <div className="col-4 text-end">
                        <div className="d-flex justify-content-end gap-2">
                            <button onClick={() => fetchDashboardData(true)} disabled={processing} className="btn btn-light rounded-circle shadow-sm p-2 mobile-p-1">
                                <FaSync className={processing ? 'fa-spin-custom' : ''} />
                            </button>
                            <button
                                onClick={async () => {
                                    setIsLoggingOut(true);
                                    await supabase.auth.signOut();
                                    navigate('/auth');
                                }}
                                disabled={isLoggingOut}
                                className="btn btn-outline-danger rounded-circle p-2 mobile-p-1 d-flex align-items-center justify-content-center"
                            >
                                {isLoggingOut ? <FaCircleNotch className="fa-spin-custom" /> : <FaSignOutAlt />}
                            </button>
                        </div>
                    </div>
                </div>

                {/* ─── NAVIGATION ─── */}
                <div className="row mb-4">
                    <div className="col-12">
                        <div className="dashboard-nav-premium d-flex p-1 bg-light rounded-4 border shadow-sm">
                            <button onClick={() => setActiveView('explorers')} className={`btn flex-fill py-3 rounded-4 fw-black border-0 transition-all ${activeView === 'explorers' ? 'btn-white shadow text-primary' : 'text-muted'}`}>MY EXPLORERS</button>
                            <button onClick={() => setActiveView('enroll')} className={`btn flex-fill py-3 rounded-4 fw-black border-0 transition-all ${activeView === 'enroll' ? 'btn-white shadow text-primary' : 'text-muted'}`}>ADD EXPLORER</button>
                        </div>
                    </div>
                </div>

                {/* ─── MAIN CONTENT ─── */}
                <div className="dashboard-main-view pb-5 animate-fadeUp">
                    {activeView === 'explorers' ? (
                        <>
                            {/* Co-Mentor Key Banner */}
                            {parentProfile?.co_mentor_key && (
                                <div className="alert border-0 rounded-4 p-3 mb-4 shadow-sm text-center animate-fadeUp" style={{ background: 'linear-gradient(135deg, #e0f2fe, #f0f9ff)' }}>
                                    <div className="d-flex align-items-center justify-content-center gap-2 mb-2">
                                        <FaKey className="text-primary" />
                                        <h5 className="fw-black text-primary mb-0">Your Co-Mentor Key</h5>
                                    </div>
                                    <p className="mb-3 text-muted small fw-bold px-3">Provide this unique key to your child to unlock additional AI Co-Mentor uses during their session.</p>
                                    <div className="d-inline-block fw-black fs-4 font-monospace text-dark bg-white border px-4 py-2 rounded-4 shadow-sm" style={{ letterSpacing: '1px' }}>
                                        {parentProfile.co_mentor_key}
                                    </div>
                                </div>
                            )}

                            {/* KPI Row */}
                            <div className="row g-2 g-lg-4 mb-4">
                                <div className="col-6 col-md-4">
                                    <div className="p-3 p-lg-4 rounded-5 bg-white border shadow-sm h-100">
                                        <div className="fw-black text-muted small ls-1 d-block mb-1 text-uppercase">Total XP</div>
                                        <h2 className="fw-black text-primary mb-0 mobile-fs-3">{stats.totalXp.toLocaleString()}</h2>
                                    </div>
                                </div>
                                <div className="col-6 col-md-4">
                                    <div className="p-3 p-lg-4 rounded-5 bg-white border shadow-sm h-100">
                                        <div className="fw-black text-success small ls-1 d-block mb-1 text-uppercase">Missions Done</div>
                                        <h2 className="fw-black text-success mb-0 mobile-fs-3">{stats.totalMissions}</h2>
                                    </div>
                                </div>
                                <div className="col-12 col-md-4">
                                    <div className="p-3 p-lg-4 rounded-5 bg-white border shadow-sm h-100">
                                        <div className="fw-black text-warning small ls-1 d-block mb-1 text-uppercase">Avg Mastery</div>
                                        <h2 className="fw-black text-warning mb-0 mobile-fs-3">{stats.avgMastery}%</h2>
                                    </div>
                                </div>
                            </div>

                            {/* Combine Payment Box */}
                            {selectedChildIds.length > 0 && (
                                <div className="p-4 rounded-5 text-white mb-4 shadow-lg text-center text-md-start animate-fadeUp" style={{ background: 'linear-gradient(135deg, #0f172a 0%, #334155 100%)' }}>
                                    <div className="row align-items-center g-3">
                                        <div className="col-12 col-md-6">
                                            <h4 className="fw-black mb-1">Combine Fee: Rs {selectedChildIds.length * 500}</h4>
                                            <p className="mb-0 fw-bold opacity-75 small">Pay Rs 500 per child and upload payment proof screenshot here.</p>
                                        </div>
                                        <div className="col-12 col-md-4">
                                            <input type="file" accept="image/*,application/pdf" onChange={(e) => setCombineScreenshotFile(e.target.files[0])} className="form-control" />
                                        </div>
                                        <div className="col-12 col-md-2">
                                            <button onClick={handleCombinePaymentSubmit} disabled={processing || !combineScreenshotFile} className="btn btn-primary rounded-pill fw-black w-100 py-2 border-0">SUBMIT PROOF</button>
                                        </div>
                                    </div>
                                </div>
                            )}

                            {success && <div className="alert alert-success rounded-4 fw-bold shadow-sm mb-4">{success}</div>}
                            {error && <div className="alert alert-danger rounded-4 fw-bold shadow-sm mb-4">{error}</div>}

                            {/* Children Grid */}
                            <div className="row g-4">
                                {children.length > 0 ? children.map((child) => (
                                    <div key={child.id} className="col-12 col-md-6 col-lg-4 position-relative">
                                        <div className="card border-0 shadow-sm rounded-5 overflow-hidden h-100 bg-white" style={{ transition: 'all 0.3s ease' }}>
                                            <div className="p-4">
                                                {/* Select button for unpaid at top of the card */}
                                                {child.payment_status !== 'paid' && (
                                                    <div className="mb-3" style={{ zIndex: 10 }}>
                                                        {child.payment_status === 'pending' && child.screenshot_url ? (
                                                            <span className="badge bg-warning text-dark rounded-pill fw-black px-3 py-2 shadow-sm d-block text-center" style={{ fontSize: '0.7rem' }}>
                                                                ✓ PROOF SENT
                                                            </span>
                                                        ) : (
                                                            <button
                                                                onClick={() => {
                                                                    if (selectedChildIds.includes(child.id)) {
                                                                        setSelectedChildIds(selectedChildIds.filter(id => id !== child.id));
                                                                    } else {
                                                                        setSelectedChildIds([...selectedChildIds, child.id]);
                                                                    }
                                                                }}
                                                                className={`btn btn-sm rounded-pill fw-black px-3 py-2 shadow-sm transition-all w-100 text-center ${
                                                                    selectedChildIds.includes(child.id)
                                                                        ? 'btn-success text-white'
                                                                        : 'btn-outline-primary bg-white'
                                                                }`}
                                                                style={{ fontSize: '0.7rem' }}
                                                            >
                                                                {selectedChildIds.includes(child.id) ? '✓ SELECTED' : 'CLICK HERE TO PAY'}
                                                            </button>
                                                        )}
                                                    </div>
                                                )}

                                                {/* Avatar + Name */}
                                                <div className="d-flex align-items-center gap-3 mb-4">
                                                    <div className={`rounded-circle d-flex align-items-center justify-content-center fw-black shadow-sm ${child.gender === 'Boy' ? 'bg-primary text-white' : 'bg-danger text-white'}`}
                                                        style={{ width: 60, height: 60, minWidth: 60, fontSize: '1.5rem' }}>
                                                        {child.name.charAt(0)}
                                                    </div>
                                                    <div className="overflow-hidden">
                                                        <h4 className="fw-black text-dark mb-0 text-truncate">{child.name}</h4>
                                                        <span className="badge bg-light text-muted border rounded-pill px-3 py-1 fw-bold x-small">
                                                            {LEVEL_NAMES[child.numericLevel] || 'Explorer'} ({child.current_level})
                                                        </span>
                                                    </div>
                                                </div>

                                                {/* Mastery bar */}
                                                <div className="mb-4">
                                                    <div className="d-flex justify-content-between align-items-center mb-2">
                                                        <small className="fw-black text-muted text-uppercase ls-1 x-small">Mission Mastery</small>
                                                        <small className="fw-black text-primary">{child.mastery}%</small>
                                                    </div>
                                                    <div className="progress rounded-pill bg-light" style={{ height: '10px' }}>
                                                        <div className="progress-bar rounded-pill bg-primary shadow-sm"
                                                            style={{ width: `${child.mastery}%`, transition: 'width 1s ease-in-out' }} />
                                                    </div>
                                                </div>

                                                {/* Stats row */}
                                                <div className="row g-2 mb-4">
                                                    <div className="col-6">
                                                        <div className="p-2 bg-light rounded-4 text-center h-100 d-flex flex-column justify-content-center">
                                                            <div className="fw-black text-dark small">{child.totalCompleted}</div>
                                                            <div className="text-muted x-small fw-bold">Missions Done</div>
                                                        </div>
                                                    </div>
                                                    <div className="col-6">
                                                        <div className="p-2 bg-light rounded-4 text-center h-100 d-flex flex-column justify-content-center">
                                                            <div className="fw-black text-dark small">{child.age || 'N/A'}</div>
                                                            <div className="text-muted x-small fw-bold">Years Old</div>
                                                        </div>
                                                    </div>
                                                </div>

                                                {/* Status Details */}
                                                <div className="p-3 bg-light rounded-4 mb-3 small">
                                                    <div className="d-flex justify-content-between mb-1">
                                                        <span className="text-muted fw-bold">Status:</span>
                                                        <span className={`fw-black ${child.payment_status === 'paid' ? 'text-success' : child.payment_status === 'pending' ? 'text-warning' : 'text-danger'}`}>
                                                            {child.payment_status === 'paid' ? 'Paid' : child.payment_status === 'pending' ? 'Pending Approval' : 'Unpaid'}
                                                        </span>
                                                    </div>
                                                    {child.payment_status === 'paid' && child.status_changed_at && (
                                                        <>
                                                            <div className="d-flex justify-content-between mb-1">
                                                                <span className="text-muted fw-bold">Approved On:</span>
                                                                <span className="fw-black text-dark">{formatDate(child.status_changed_at)}</span>
                                                            </div>
                                                            <div className="d-flex justify-content-between">
                                                                <span className="text-muted fw-bold">Expires On:</span>
                                                                <span className="fw-black text-danger">
                                                                    {formatDate(new Date(new Date(child.status_changed_at).getTime() + 30 * 24 * 60 * 60 * 1000))}
                                                                </span>
                                                            </div>
                                                            {(() => {
                                                                const daysLeft = getExpiryDaysLeft(child.status_changed_at);
                                                                if (daysLeft !== null && daysLeft <= 5 && daysLeft >= 0) {
                                                                    return (
                                                                        <div className="text-warning fw-black mt-2 text-center x-small bg-warning-subtle p-1 rounded-pill border border-warning" style={{ fontSize: '0.65rem' }}>
                                                                            NEAR EXPIRY ({daysLeft} days left)
                                                                        </div>
                                                                    );
                                                                } else if (daysLeft !== null && daysLeft < 0) {
                                                                    return (
                                                                        <div className="text-danger fw-black mt-2 text-center x-small bg-danger-subtle p-1 rounded-pill border border-danger" style={{ fontSize: '0.65rem' }}>
                                                                            EXPIRED
                                                                        </div>
                                                                    );
                                                                }
                                                                return null;
                                                            })()}
                                                        </>
                                                    )}
                                                </div>

                                                {/* Action buttons */}
                                                <div className="d-flex flex-column gap-2">
                                                    <button onClick={() => setSelectedChild(child)} className="btn btn-primary rounded-pill py-2 fw-black shadow-sm border-0" style={{ background: '#0ea5e9' }}>
                                                        <FaKey className="me-2" /> GET LOGIN KEY
                                                    </button>

                                                    <button
                                                        onClick={() => setProgressChild(child)}
                                                        className="btn btn-light rounded-pill py-2 fw-black border"
                                                        style={{ color: '#475569' }}
                                                    >
                                                        <FaChartBar className="me-2" size={12} /> VIEW PROGRESS
                                                    </button>

                                                    {child.payment_status === 'pending' ? (
                                                        <div className="alert alert-warning py-2 px-3 rounded-pill mb-0 border-0 d-flex align-items-center justify-content-center gap-2">
                                                            <FaExclamationTriangle className="flex-shrink-0" />
                                                            <span className="fw-bold x-small">Activation Pending (Check Proof)</span>
                                                        </div>
                                                    ) : child.payment_status !== 'paid' ? (
                                                        <div className="alert alert-danger py-2 px-3 rounded-pill mb-0 border-0 d-flex align-items-center justify-content-center gap-2">
                                                            <FaExclamationTriangle className="flex-shrink-0" />
                                                            <span className="fw-bold x-small">Awaiting Payment (Rs 500)</span>
                                                        </div>
                                                    ) : (
                                                        <div className="alert alert-success py-2 px-3 rounded-pill mb-0 border-0 d-flex align-items-center justify-content-center gap-2">
                                                            <FaCheckCircle className="flex-shrink-0" />
                                                            <span className="fw-bold x-small">Active &amp; Ready to Play</span>
                                                        </div>
                                                    )}
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                )) : (
                                    <div className="col-12 text-center py-5">
                                        <div className="bg-light rounded-circle d-inline-flex align-items-center justify-content-center mb-4" style={{ width: 100, height: 100 }}>
                                            <FaUserAlt size={40} className="text-muted opacity-25" />
                                        </div>
                                        <h3 className="fw-black text-dark">No Explorers Linked</h3>
                                        <p className="text-muted fw-bold">Use the "Add Explorer" tab to register your kids directly.</p>
                                    </div>
                                )}
                            </div>
                        </>
                    ) : (
                        <div className="card border-0 shadow-lg rounded-5 overflow-hidden bg-white p-4 p-lg-5">
                            <h2 className="fw-black text-dark mb-4 ls-tight">Manual Enrollment</h2>
                            {error && <div className="alert alert-danger rounded-4 fw-bold shadow-sm mb-4">{error}</div>}
                            {success && <div className="alert alert-success rounded-4 fw-bold shadow-sm mb-4">{success}</div>}
                            <form onSubmit={handleAddChild} className="row g-3">
                                <div className="col-12">
                                    <div className="form-floating">
                                        <input className="form-control rounded-4 px-4 bg-light border-0 fw-bold" id="cName" placeholder="Name" required value={newChild.name} onChange={e => setNewChild({ ...newChild, name: e.target.value })} />
                                        <label htmlFor="cName">Child Name</label>
                                    </div>
                                </div>
                                <div className="col-md-6">
                                    <div className="form-floating">
                                        <select className="form-select rounded-4 px-4 bg-light border-0 fw-bold" id="cClass" value={newChild.classLevel} onChange={e => setNewChild({ ...newChild, classLevel: e.target.value })}>
                                            {Array.from({ length: 10 }, (_, i) => `Class ${i + 1}`).map(c => <option key={c} value={c}>{c}</option>)}
                                        </select>
                                        <label htmlFor="cClass">Grade</label>
                                    </div>
                                </div>
                                <div className="col-md-3">
                                    <div className="form-floating">
                                        <input className="form-control rounded-4 px-4 bg-light border-0 fw-bold" id="cAge" type="number" required value={newChild.age} onChange={e => setNewChild({ ...newChild, age: e.target.value })} />
                                        <label htmlFor="cAge">Age</label>
                                    </div>
                                </div>
                                <div className="col-md-3">
                                    <div className="form-floating">
                                        <select className="form-select rounded-4 px-4 bg-light border-0 fw-bold" id="cGender" value={newChild.gender} onChange={e => setNewChild({ ...newChild, gender: e.target.value })}>
                                            <option>Boy</option>
                                            <option>Girl</option>
                                        </select>
                                        <label htmlFor="cGender">Gender</label>
                                    </div>
                                </div>
                                <div className="col-12 mt-4">
                                    <button type="submit" disabled={processing} className="btn btn-primary btn-lg w-100 py-3 rounded-pill fw-black shadow-lg border-0" style={{ background: '#10B981' }}>
                                        {processing ? <FaCircleNotch className="fa-spin-custom" /> : 'CONFIRM ENROLLMENT'}
                                    </button>
                                </div>
                            </form>
                        </div>
                    )}
                </div>

            {/* ─── CREDENTIAL MODAL ─── */}
            {selectedChild && (
                <div className="modal-overlay-premium" onClick={() => { setSelectedChild(null); setEditingKey(false); }}>
                    <div className="modal-card-premium card border-0 shadow-2xl rounded-5 bg-white overflow-hidden" style={{ maxWidth: '380px' }} onClick={e => e.stopPropagation()}>
                        <div className={`p-2 px-4 ${selectedChild.gender === 'Boy' ? 'bg-primary' : 'bg-danger'} text-white d-flex justify-content-between align-items-center`}>
                            <h6 className="fw-black mb-0">Student Access</h6>
                            <button onClick={() => { setSelectedChild(null); setEditingKey(false); }} className="btn-close-premium" style={{ width: '28px', height: '28px' }}>
                                <FaTimes size={12} />
                            </button>
                        </div>
                        <div className="p-3 text-center">
                            <div className="mb-2">
                                <div className="bg-light rounded-circle d-inline-flex align-items-center justify-content-center mb-1 shadow-sm" style={{ width: 44, height: 44 }}>
                                    <FaKey size={18} className={selectedChild.gender === 'Boy' ? 'text-primary' : 'text-danger'} />
                                </div>
                                <h6 className="fw-black text-dark mb-0">{selectedChild.name}</h6>
                                <p className="text-muted fw-bold x-small mb-0">Student Credentials</p>
                            </div>

                            <div className="bg-light rounded-4 p-3 mb-3 border border-2 border-dashed position-relative">
                                {!editingKey ? (
                                    <>
                                        <div className="mb-2 pb-2 border-bottom border-secondary border-opacity-10">
                                            <small className="text-muted fw-black text-uppercase ls-1 x-small d-block mb-1">Username (CNIC)</small>
                                            <div className="fw-black text-dark fs-6 font-monospace">{selectedChild.parent_cnic}</div>
                                        </div>
                                        <div>
                                            <div className="d-flex justify-content-between align-items-center mb-1">
                                                <small className="text-muted fw-black text-uppercase ls-1 x-small">Password (Secret Key)</small>
                                                <button onClick={() => { setEditingKey(true); setNewSecretKey(selectedChild.secret_key); }} className="btn btn-primary px-4 py-2 rounded-pill fw-black text-decoration-none small shadow-sm">CHANGE</button>
                                            </div>
                                            <div className="fw-black text-primary fs-2 font-monospace" style={{ letterSpacing: '2px' }}>{selectedChild.secret_key}</div>
                                        </div>
                                    </>
                                ) : (
                                    <form onSubmit={handleUpdateSecretKey}>
                                        <div className="mb-3">
                                            <small className="text-muted fw-black text-uppercase ls-1 x-small d-block mb-2">New Secret Key</small>
                                            <input
                                                className="form-control text-center fw-black fs-4 font-monospace py-2 rounded-3 border-primary"
                                                value={newSecretKey}
                                                onChange={e => setNewSecretKey(e.target.value)}
                                                placeholder="Enter Key"
                                                maxLength={6}
                                                required
                                            />
                                        </div>
                                        <div className="d-flex gap-2">
                                            <button type="button" onClick={() => setEditingKey(false)} className="btn btn-light flex-fill fw-bold rounded-pill">Cancel</button>
                                            <button type="submit" disabled={isLoggingOut} className="btn btn-primary flex-fill fw-black rounded-pill">
                                                {isLoggingOut ? <FaCircleNotch className="fa-spin-custom" /> : 'SAVE KEY'}
                                            </button>
                                        </div>
                                    </form>
                                )}
                            </div>

                            {/* Parental Controls Section */}
                            <div className="bg-light rounded-4 p-3 mb-3 text-start">
                                <h6 className="fw-black text-dark mb-2 small text-uppercase" style={{ fontSize: '0.75rem' }}>Parental Control</h6>
                                <div className="mb-2">
                                    <label className="text-muted fw-bold x-small d-block mb-1">Daily Play Time Limit</label>
                                    <select 
                                        className="form-select form-select-sm rounded-pill px-3 py-1 fw-bold"
                                        value={selectedChild.daily_limit_minutes ?? '0'}
                                        onChange={async (e) => {
                                            const val = e.target.value;
                                            const limitVal = val === '0' ? null : parseInt(val);
                                            
                                            // 1. Update localStorage cache
                                            let savedLimits = {};
                                            try {
                                                savedLimits = JSON.parse(localStorage.getItem('kido_time_limits') || '{}') || {};
                                            } catch (err) {
                                                savedLimits = {};
                                            }
                                            if (val === '0') {
                                                delete savedLimits[selectedChild.id];
                                            } else {
                                                savedLimits[selectedChild.id] = limitVal;
                                            }
                                            localStorage.setItem('kido_time_limits', JSON.stringify(savedLimits));

                                            // 2. Update Database
                                            try {
                                                const { error: dbLimitError } = await supabase
                                                    .from('children')
                                                    .update({ daily_limit_minutes: limitVal })
                                                    .eq('id', selectedChild.id);
                                                if (dbLimitError) throw dbLimitError;
                                                
                                                // Update local states
                                                setChildren(children.map(c => c.id === selectedChild.id ? { ...c, daily_limit_minutes: limitVal } : c));
                                                setSelectedChild({ ...selectedChild, daily_limit_minutes: limitVal });
                                                
                                                setSuccess("Parental controls updated!");
                                                setTimeout(() => setSuccess(''), 2000);
                                            } catch (dbErr) {
                                                console.error("Failed to save limit to database:", dbErr);
                                                setError("Failed to update database limit.");
                                                setTimeout(() => setError(''), 3000);
                                            }
                                        }}
                                        style={{ fontSize: '0.8rem' }}
                                    >
                                        <option value="0">No Limit (Default)</option>
                                        <option value="1">1 Minute (Test)</option>
                                        <option value="15">15 Minutes</option>
                                        <option value="30">30 Minutes</option>
                                        <option value="45">45 Minutes</option>
                                        <option value="60">60 Minutes</option>
                                        <option value="120">2 Hours</option>
                                    </select>
                                </div>
                            </div>

                            {success && <div className="alert alert-success py-2 rounded-pill x-small fw-bold mb-2 animate-fadeUp">{success}</div>}
                            {error && <div className="alert alert-danger py-2 rounded-pill x-small fw-bold mb-2">{error}</div>}

                            <p className="x-small text-muted fw-bold mb-0 opacity-75">
                                <FaShieldAlt className="me-1 text-success" />
                                Access your personal learning island.
                            </p>
                        </div>
                    </div>
                </div>
            )}

            {/* ─── PROGRESS MODAL ─── */}
            {progressChild && (
                <ProgressModal
                    child={progressChild}
                    allLessons={allLessons}
                    completions={completions}
                    onClose={() => setProgressChild(null)}
                />
            )}

            <style>{`
                @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@400;500;600;700;800;900&display=swap');
                .parent-dashboard-premium { font-family: 'Outfit', sans-serif; overflow-x: hidden; }
                .fw-black { font-weight: 900 !important; }
                .ls-1 { letter-spacing: 0.1em; }
                .ls-tight { letter-spacing: -0.05em; }
                .x-small { font-size: 0.7rem !important; }

                /* ── Shared modal overlay ── */
                .modal-overlay-premium {
                    position: fixed; top: 0; left: 0; width: 100%; height: 100%;
                    background: rgba(15, 23, 42, 0.9);
                    backdrop-filter: blur(15px);
                    -webkit-backdrop-filter: blur(15px);
                    display: flex; align-items: center; justify-content: center;
                    z-index: 10000; padding: 20px;
                }
                .modal-card-premium {
                    width: 100%;
                    border-radius: 35px;
                    animation: modalIn 0.4s cubic-bezier(0.34, 1.56, 0.64, 1);
                    position: relative;
                }

                /* ── Progress modal scrollable body ── */
                .progress-modal-body {
                    max-height: calc(90vh - 160px);
                    overflow-y: auto;
                    -webkit-overflow-scrolling: touch;
                }
                .progress-modal-body::-webkit-scrollbar { width: 4px; }
                .progress-modal-body::-webkit-scrollbar-track { background: transparent; }
                .progress-modal-body::-webkit-scrollbar-thumb { background: #CBD5E1; border-radius: 99px; }

                /* ── Close button (shared) ── */
                .btn-close-premium {
                    background: rgba(255,255,255,0.2);
                    border: none; color: white;
                    width: 40px; height: 40px;
                    border-radius: 50%;
                    display: flex; align-items: center; justify-content: center;
                    transition: all 0.3s; cursor: pointer;
                    flex-shrink: 0;
                }
                .btn-close-premium:hover { background: rgba(255,255,255,0.35); transform: rotate(90deg); }

                @keyframes modalIn { 0% { transform: scale(0.9) translateY(20px); opacity: 0; } 100% { transform: scale(1) translateY(0); opacity: 1; } }

                .animate-fadeUp { animation: fadeUp 0.6s ease-out forwards; }
                @keyframes fadeUp { from { opacity: 0; transform: translateY(20px); } to { opacity: 1; transform: translateY(0); } }

                .fa-spin-custom { animation: spin 1s linear infinite; }
                @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }

                .lesson-section-label {
                    font-size: 0.68rem; font-weight: 900; text-transform: uppercase;
                    letter-spacing: 0.08em; margin-bottom: 10px;
                    display: flex; align-items: center; gap: 8px;
                }
                .lesson-section-label::after {
                    content: ''; flex: 1; height: 1px;
                    background: currentColor; opacity: 0.15; border-radius: 1px;
                }

                @media (max-width: 768px) {
                    .mobile-fs-4 { font-size: 1.4rem !important; }
                    .mobile-fs-3 { font-size: 1.15rem !important; }
                    .mobile-p-1 { padding: 6px !important; }
                    .container-fluid { padding-left: 12px !important; padding-right: 12px !important; }
                    .modal-card-premium { border-radius: 22px; }
                    .progress-modal-body { max-height: calc(92vh - 160px); }
                }
            `}</style>
            </div>
        </div>
    );
};

export default ParentDashboard;