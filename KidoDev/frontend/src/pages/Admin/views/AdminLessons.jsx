import React, { useState, useEffect } from 'react';
import { supabase } from '../../../utils/supabaseClient';

/* ─────────────────────────────────────────────
   LEVEL BADGE
   ───────────────────────────────────────────── */
const LevelBadge = ({ level }) => {
    const colors = ['#6366F1', '#0EA5E9', '#10B981', '#F59E0B', '#EC4899', '#8B5CF6'];
    const c = colors[(level - 1) % colors.length] || '#64748B';
    return (
        <span style={{
            background: c + '18', color: c, border: `1px solid ${c}40`,
            borderRadius: 8, padding: '2px 10px', fontSize: '0.72rem', fontWeight: 800, letterSpacing: 0.3
        }}>Level {level}</span>
    );
};

/* ─────────────────────────────────────────────
   LESSON CARD
   ───────────────────────────────────────────── */
const LessonCard = ({ lesson, hasSolution, index }) => {
    const [open, setOpen] = useState(false);

    return (
        <div style={{
            background: '#fff',
            border: '1px solid #E2E8F0',
            borderRadius: 18,
            overflow: 'hidden',
            boxShadow: open ? '0 8px 32px rgba(99,102,241,0.1)' : '0 2px 8px rgba(0,0,0,0.04)',
            transition: 'box-shadow 0.25s, transform 0.2s',
            transform: open ? 'translateY(-1px)' : 'none',
            marginBottom: 14,
        }}>
            {/* Header row */}
            <div
                onClick={() => setOpen(v => !v)}
                style={{
                    display: 'flex', alignItems: 'center', gap: 14, padding: '18px 24px',
                    cursor: 'pointer', userSelect: 'none',
                    borderBottom: open ? '1px solid #F1F5F9' : 'none',
                    background: open ? '#FAFBFF' : '#fff',
                    transition: 'background 0.2s'
                }}
            >
                <div style={{
                    minWidth: 38, height: 38, borderRadius: 12,
                    background: 'linear-gradient(135deg, #6366F1, #8B5CF6)',
                    color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center',
                    fontWeight: 900, fontSize: '0.9rem', boxShadow: '0 4px 12px rgba(99,102,241,0.3)'
                }}>
                    {index + 1}
                </div>

                <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4, flexWrap: 'wrap' }}>
                        <span style={{ fontWeight: 800, fontSize: '0.97rem', color: '#1E293B' }}>{lesson.title}</span>
                        <LevelBadge level={lesson.class_level} />
                        {lesson.is_prompt_project && (
                            <span style={{
                                background: '#F0FDF4', color: '#16A34A', border: '1px solid #BBF7D0',
                                borderRadius: 8, padding: '2px 10px', fontSize: '0.7rem', fontWeight: 800
                            }}>Prompt Project</span>
                        )}
                        {!hasSolution && !lesson.is_prompt_project && (
                            <span style={{
                                background: '#FFF7ED', color: '#C2410C', border: '1px solid #FED7AA',
                                borderRadius: 8, padding: '2px 10px', fontSize: '0.7rem', fontWeight: 700
                            }}>No Solution</span>
                        )}
                    </div>
                    <div style={{ fontSize: '0.82rem', color: '#64748B' }}>
                        {lesson.objective}
                        <span style={{ marginLeft: 12, color: '#CBD5E1' }}>|</span>
                        <span style={{ marginLeft: 12 }}>{(lesson.steps || []).length} step{(lesson.steps || []).length !== 1 ? 's' : ''}</span>
                    </div>
                </div>

                <div style={{
                    minWidth: 28, height: 28, borderRadius: 8, background: '#F1F5F9',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    color: '#64748B', fontSize: '0.8rem', fontWeight: 900,
                    transform: open ? 'rotate(180deg)' : 'none', transition: 'transform 0.2s'
                }}></div>
            </div>

            {/* Expanded body — plain language only */}
            {open && (
                <div style={{ padding: '20px 24px 24px' }}>

                    <div style={{
                        fontSize: '0.72rem', fontWeight: 800, color: '#64748B',
                        textTransform: 'uppercase', letterSpacing: 1, marginBottom: 12
                    }}>
                        What the child does — step by step
                    </div>

                    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                        {(lesson.steps || []).length === 0 ? (
                            <div style={{ color: '#94A3B8', fontSize: '0.85rem', fontStyle: 'italic' }}>
                                No steps defined for this lesson yet.
                            </div>
                        ) : (lesson.steps || []).map((step, si) => (
                            <div key={si} style={{
                                display: 'flex', gap: 14, alignItems: 'flex-start',
                                background: '#F8FAFC', border: '1px solid #E2E8F0',
                                borderRadius: 14, padding: '14px 18px'
                            }}>
                                <div style={{
                                    minWidth: 28, height: 28, borderRadius: 8,
                                    background: 'linear-gradient(135deg, #6366F1, #8B5CF6)',
                                    color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center',
                                    fontWeight: 900, fontSize: '0.78rem', flexShrink: 0
                                }}>{si + 1}</div>
                                <div>
                                    <div style={{ fontWeight: 800, fontSize: '0.9rem', color: '#1E293B', marginBottom: 3 }}>
                                        {step.title}
                                    </div>
                                    <div style={{ fontSize: '0.85rem', color: '#475569', lineHeight: 1.6 }}>
                                        {step.desc}
                                    </div>
                                </div>
                            </div>
                        ))}
                    </div>

                    {/* Prompt projects: show the target prompt + milestone triggers */}
                    {lesson.is_prompt_project && lesson.perfect_prompt && (
                        <div style={{ marginTop: 22 }}>
                            <div style={{
                                fontSize: '0.72rem', fontWeight: 800, color: '#64748B',
                                textTransform: 'uppercase', letterSpacing: 1, marginBottom: 10
                            }}>
                                What they're aiming for
                            </div>
                            <div style={{
                                background: 'linear-gradient(135deg, #F0FDF4, #ECFDF5)',
                                border: '1px solid #BBF7D0', borderRadius: 14, padding: '14px 18px',
                                fontSize: '0.92rem', color: '#166534', lineHeight: 1.7, fontStyle: 'italic'
                            }}>
                                "{lesson.perfect_prompt}"
                            </div>

                            {(lesson.prompt_milestones || []).length > 0 && (
                                <div style={{ marginTop: 16 }}>
                                    <div style={{
                                        fontSize: '0.72rem', fontWeight: 800, color: '#64748B',
                                        textTransform: 'uppercase', letterSpacing: 1, marginBottom: 10
                                    }}>
                                        Keyword Triggers
                                    </div>
                                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                                        {lesson.prompt_milestones.map((ms, mi) => (
                                            <div key={mi} style={{
                                                background: '#fff', border: '1px solid #D1FAE5',
                                                borderRadius: 10, padding: '8px 14px', fontSize: '0.83rem'
                                            }}>
                                                <span style={{ fontWeight: 700, color: '#059669' }}>"{ms.keyword}"</span>
                                                <span style={{ color: '#94A3B8', margin: '0 6px' }}>→</span>
                                                <span style={{ color: '#64748B' }}>{ms.action}</span>
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            )}
                        </div>
                    )}
                </div>
            )}
        </div>
    );
};

/* ─────────────────────────────────────────────
   MAIN COMPONENT
   ───────────────────────────────────────────── */
const AdminLessons = () => {
    const [lessons, setLessons] = useState([]);
    const [solutions, setSolutions] = useState(new Set());
    const [loading, setLoading] = useState(true);
    const [search, setSearch] = useState('');
    const [levelFilter, setLevelFilter] = useState('all');
    const [typeFilter, setTypeFilter] = useState('all');

    useEffect(() => {
        const fetchAll = async () => {
            setLoading(true);
            try {
                const [lRes, sRes] = await Promise.all([
                    supabase.from('lessons').select('*').order('class_level').order('order_index'),
                    supabase.from('tutor_solutions').select('lesson_id')
                ]);
                const lessonsData = lRes.data || [];
                const solutionsData = sRes.data || [];
                setSolutions(new Set(solutionsData.map(s => s.lesson_id)));
                setLessons(lessonsData);
            } catch (e) {
                console.error(e);
            } finally {
                setLoading(false);
            }
        };
        fetchAll();
    }, []);

    const levels = [...new Set(lessons.map(l => l.class_level))].sort((a, b) => a - b);

    const filtered = lessons.filter(l => {
        const q = search.toLowerCase();
        const matchSearch = !q || l.title?.toLowerCase().includes(q) || l.objective?.toLowerCase().includes(q) || l.id?.toLowerCase().includes(q);
        const matchLevel = levelFilter === 'all' || String(l.class_level) === levelFilter;
        const matchType = typeFilter === 'all'
            || (typeFilter === 'prompt' && l.is_prompt_project)
            || (typeFilter === 'scratch' && !l.is_prompt_project);
        return matchSearch && matchLevel && matchType;
    });

    const grouped = {};
    filtered.forEach(l => {
        const key = l.class_level;
        if (!grouped[key]) grouped[key] = [];
        grouped[key].push(l);
    });
    const groupKeys = Object.keys(grouped).sort((a, b) => a - b);

    const missingCount = lessons.filter(l => !l.is_prompt_project && !solutions.has(l.id)).length;

    return (
        <div style={{ fontFamily: "'Fredoka', 'Nunito', sans-serif" }}>
            <div style={{ marginBottom: 28 }}>
                <h1 style={{ fontWeight: 900, fontSize: '1.7rem', color: '#1E293B', margin: 0, letterSpacing: '-0.5px' }}>
                    Lesson Explorer
                </h1>
                <p style={{ color: '#64748B', fontSize: '0.9rem', marginTop: 6, marginBottom: 0 }}>
                    Browse every project and see exactly what the child is asked to do — in plain language.
                </p>
            </div>

            {/* Summary KPIs */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 14, marginBottom: 24 }}>
                {[
                    { label: 'Total Lessons', value: lessons.length, color: '#6366F1', bg: '#EEF2FF', icon: '📖' },
                    { label: 'With Solutions', value: solutions.size, color: '#10B981', bg: '#F0FDF4', icon: '✅' },
                    { label: 'Prompt Projects', value: lessons.filter(l => l.is_prompt_project).length, color: '#0EA5E9', bg: '#F0F9FF', icon: '✨' },
                    { label: 'Missing Solutions', value: missingCount, color: missingCount > 0 ? '#EF4444' : '#10B981', bg: missingCount > 0 ? '#FFF1F2' : '#F0FDF4', icon: missingCount > 0 ? '⚠️' : '🎉' },
                    { label: 'Course Levels', value: levels.length, color: '#8B5CF6', bg: '#F5F3FF', icon: '🏅' },
                ].map((k, i) => (
                    <div key={i} style={{ background: k.bg, border: `1px solid ${k.color}30`, borderRadius: 16, padding: '16px 20px' }}>
                        <div style={{ fontWeight: 900, fontSize: '1.6rem', color: k.color, lineHeight: 1 }}>{k.value}</div>
                        <div style={{ fontSize: '0.78rem', fontWeight: 700, color: '#64748B', marginTop: 4 }}>{k.label}</div>
                    </div>
                ))}
            </div>

            {/* Filters */}
            <div style={{
                background: '#fff', border: '1px solid #E2E8F0', borderRadius: 16,
                padding: '16px 20px', marginBottom: 24,
                display: 'flex', gap: 14, flexWrap: 'wrap', alignItems: 'center'
            }}>
                <input
                    type="text"
                    placeholder="Search lessons, objectives..."
                    value={search}
                    onChange={e => setSearch(e.target.value)}
                    style={{
                        flex: 1, minWidth: 220, border: '1.5px solid #E2E8F0', borderRadius: 10,
                        padding: '8px 14px', fontSize: '0.88rem', outline: 'none', fontFamily: 'inherit',
                        color: '#1E293B', background: '#F8FAFC'
                    }}
                />
                <select value={levelFilter} onChange={e => setLevelFilter(e.target.value)} style={{
                    border: '1.5px solid #E2E8F0', borderRadius: 10, padding: '8px 14px',
                    fontSize: '0.88rem', fontFamily: 'inherit', color: '#1E293B',
                    background: '#F8FAFC', outline: 'none', cursor: 'pointer'
                }}>
                    <option value="all">All Levels</option>
                    {levels.map(l => <option key={l} value={String(l)}>Level {l}</option>)}
                </select>
                <select value={typeFilter} onChange={e => setTypeFilter(e.target.value)} style={{
                    border: '1.5px solid #E2E8F0', borderRadius: 10, padding: '8px 14px',
                    fontSize: '0.88rem', fontFamily: 'inherit', color: '#1E293B',
                    background: '#F8FAFC', outline: 'none', cursor: 'pointer'
                }}>
                    <option value="all">All Types</option>
                    <option value="scratch">Scratch Projects</option>
                    <option value="prompt">Prompt Projects</option>
                </select>
                {(search || levelFilter !== 'all' || typeFilter !== 'all') && (
                    <button onClick={() => { setSearch(''); setLevelFilter('all'); setTypeFilter('all'); }} style={{
                        background: '#FFF1F2', color: '#EF4444', border: '1px solid #FECACA',
                        borderRadius: 10, padding: '8px 14px', fontWeight: 800,
                        fontSize: '0.82rem', cursor: 'pointer', fontFamily: 'inherit'
                    }}>Clear</button>
                )}
                <div style={{ fontSize: '0.82rem', color: '#94A3B8', fontWeight: 600, marginLeft: 'auto' }}>
                    Showing {filtered.length} of {lessons.length}
                </div>
            </div>

            {/* Lesson List */}
            {loading ? (
                <div style={{ textAlign: 'center', padding: '60px 20px', color: '#94A3B8', fontSize: '0.95rem' }}>
                    Loading lesson library...
                </div>
            ) : filtered.length === 0 ? (
                <div style={{ textAlign: 'center', padding: '60px 20px', color: '#94A3B8' }}>
                    <div style={{ fontSize: '1rem', fontWeight: 700 }}>No lessons match your filters</div>
                    <div style={{ fontSize: '0.85rem', marginTop: 6 }}>Try adjusting your search or clearing filters</div>
                </div>
            ) : (
                groupKeys.map(lvl => (
                    <div key={lvl} style={{ marginBottom: 32 }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 16 }}>
                            <div style={{ height: 3, flex: 1, borderRadius: 2, background: 'linear-gradient(90deg, #6366F1, transparent)' }} />
                            <div style={{
                                background: 'linear-gradient(135deg, #6366F1, #8B5CF6)',
                                color: '#fff', borderRadius: 14, padding: '6px 18px',
                                fontWeight: 900, fontSize: '0.9rem', letterSpacing: 0.5,
                                boxShadow: '0 4px 14px rgba(99,102,241,0.3)'
                            }}>
                                Level {lvl} — {grouped[lvl].length} lesson{grouped[lvl].length !== 1 ? 's' : ''}
                            </div>
                            <div style={{ height: 3, flex: 1, borderRadius: 2, background: 'linear-gradient(90deg, transparent, #8B5CF6)' }} />
                        </div>

                        {grouped[lvl].map((lesson) => {
                            const globalIdx = lessons.findIndex(l => l.id === lesson.id);
                            return (
                                <LessonCard
                                    key={lesson.id}
                                    lesson={lesson}
                                    hasSolution={solutions.has(lesson.id)}
                                    index={globalIdx}
                                />
                            );
                        })}
                    </div>
                ))
            )}
        </div>
    );
};

export default AdminLessons;