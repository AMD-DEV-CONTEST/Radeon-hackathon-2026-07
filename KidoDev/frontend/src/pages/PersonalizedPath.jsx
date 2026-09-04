import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { supabase } from '../utils/supabaseClient';
import { requestCurriculum } from '../agents/AgentOrchestrator';
import { initSession } from '../agents/memory/AgentMemoryStore';

export default function PersonalizedPath() {
    const [loading, setLoading] = useState(true);
    const [curriculumData, setCurriculumData] = useState(null);
    const [profile, setProfile] = useState(null);
    const [error, setError] = useState(null);
    const navigate = useNavigate();

    useEffect(() => {
        loadPath();
    }, []);

    async function loadPath() {
        setLoading(true);
        setError(null);
        try {
            const kidChildId = localStorage.getItem('kido_child_id');
            const { data: authData } = await supabase.auth.getUser().catch(() => ({ data: { user: null } }));
            const user = authData?.user;
            const userId = kidChildId || user?.id || 'demo_student';

            // Initialize agent session
            initSession(userId);

            const isUUID = (str) => typeof str === 'string' && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(str);

            let profileData = { total_xp: 150, level: 'Bronze', badges: [] };
            let completedData = [];

            if (isUUID(userId)) {
                try {
                    const [pRes, cRes] = await Promise.all([
                        supabase.from('child_profiles').select('total_xp, level, badges').eq('id', userId).maybeSingle(),
                        supabase.from('lesson_completions').select('lesson_id, score, badge').eq(kidChildId ? 'child_id' : 'user_id', userId),
                    ]);
                    if (pRes?.data) profileData = pRes.data;
                    if (cRes?.data) completedData = cRes.data;
                } catch (dbErr) {
                    console.warn('[PersonalizedPath] DB query warning:', dbErr);
                }
            }

            setProfile(profileData);

            // Request personalized curriculum from the agent (with a 4-second timeout promise race)
            const curriculumPromise = requestCurriculum({
                completedLessons: completedData,
                weakBlockTypes: [],
                strongBlockTypes: [],
                level: profileData.level,
                totalXp: profileData.total_xp,
            });

            const timeoutPromise = new Promise((resolve) =>
                setTimeout(() => resolve(null), 4000)
            );

            const curriculum = await Promise.race([curriculumPromise, timeoutPromise]);

            if (curriculum) {
                setCurriculumData(curriculum);
            } else {
                // Fallback curriculum if agent request timed out
                setCurriculumData({
                    learning_path_summary: "Welcome to your personalized AI coding path! Complete visual block challenges in Magic Studio to earn XP and level badges.",
                    weekly_goal: "Complete 2 new coding challenges this week.",
                    next_challenge: "Try using loops and motion blocks in your next project.",
                    strengths: ["Visual Block Assembly", "Creative Logic"],
                    skill_gaps: ["Multi-Sprite Event Signal Broadcasting"],
                    recommended_lessons: [
                        { lesson_id: 'lesson_1', title: 'Sprite Movement Basics', reason: 'Master fundamental block navigation', priority: 'high' },
                        { lesson_id: 'lesson_2', title: 'Loop & Repeat Magic', reason: 'Learn how to repeat actions automatically', priority: 'medium' },
                        { lesson_id: 'lesson_3', title: 'Obstacle Dodge Challenge', reason: 'Practice collision detection and sensing', priority: 'high' }
                    ],
                    homework_assignments: [
                        {
                            title: "Loop Master Challenge",
                            objective: "Make your sprite walk in a perfect square by using a Repeat loop with Move and Turn blocks.",
                            target_block_types: ["s_when_flag", "s_repeat", "s_move", "s_turn_r"],
                            difficulty: "medium",
                            estimated_minutes: 10
                        }
                    ]
                });
            }
        } catch (err) {
            console.error('[PersonalizedPath]', err);
            setError('Could not load your learning path. Please try again.');
        } finally {
            setLoading(false);
        }
    }


    const levelColors = {
        Bronze: { bg: 'linear-gradient(135deg, #cd7f32, #a0522d)', text: '#fff' },
        Silver: { bg: 'linear-gradient(135deg, #c0c0c0, #808080)', text: '#fff' },
        Gold: { bg: 'linear-gradient(135deg, #FFD700, #FFA500)', text: '#1a1a1a' },
        Platinum: { bg: 'linear-gradient(135deg, #E5E4E2, #9E9E9E)', text: '#1a1a1a' },
        Diamond: { bg: 'linear-gradient(135deg, #b9f2ff, #00BFFF)', text: '#1a1a1a' },
    };
    const levelStyle = levelColors[profile?.level] || levelColors.Bronze;

    return (
        <div style={{
            minHeight: '100vh',
            background: 'linear-gradient(135deg, #F8FAFC 0%, #EFF6FF 50%, #F0FDF4 100%)',
            padding: '100px 24px 48px',
            fontFamily: "'Outfit', 'Inter', sans-serif",
            color: '#1E293B'
        }}>
            <div style={{ maxWidth: 900, margin: '0 auto' }}>
                {/* Back button */}
                <button
                    onClick={() => navigate(-1)}
                    style={{
                        background: '#FFFFFF', border: '1px solid #E2E8F0',
                        borderRadius: 12, padding: '8px 18px', color: '#475569',
                        fontWeight: 700, fontSize: 13, cursor: 'pointer',
                        marginBottom: 24, transition: 'all 0.2s',
                        display: 'flex', alignItems: 'center', gap: 8,
                        boxShadow: '0 2px 8px rgba(0,0,0,0.04)'
                    }}
                >
                    ← Back
                </button>

                {/* Header */}
                <div style={{ marginBottom: 32 }}>
                    <h1 style={{ color: '#0F172A', fontWeight: 900, fontSize: 32, margin: '0 0 8px', letterSpacing: '-0.5px' }}>
                        Child Learning Journey & AI Insights
                    </h1>
                    <p style={{ color: '#64748B', margin: 0, fontSize: 15, fontWeight: 600 }}>
                        Powered by KidoBot CurriculumAgent — Personalized AI Skill Analysis
                    </p>
                </div>

                {loading ? (
                    <div style={{ textAlign: 'center', padding: 80, background: '#FFFFFF', borderRadius: 24, boxShadow: '0 10px 30px rgba(0,0,0,0.04)', border: '1px solid #E2E8F0' }}>
                        <div style={{ marginBottom: 16 }}>
                            <div style={{
                                width: 48, height: 48, borderRadius: '50%',
                                border: '3px solid #E2E8F0',
                                borderTopColor: '#0EA5E9',
                                animation: 'spin 0.8s linear infinite',
                                margin: '0 auto',
                            }} />
                        </div>
                        <p style={{ color: '#64748B', fontWeight: 700 }}>
                            CurriculumAgent is analyzing your learning history...
                        </p>
                        <style>{`@keyframes spin{from{transform:rotate(0deg)}to{transform:rotate(360deg)}}`}</style>
                    </div>
                ) : error ? (
                    <div style={{
                        background: '#FEF2F2', border: '1px solid #FECACA',
                        borderRadius: 16, padding: 24, color: '#DC2626', textAlign: 'center', fontWeight: 700
                    }}>
                        {error}
                    </div>
                ) : (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
                        {/* Profile + Summary card */}
                        {profile && (
                            <div style={{
                                display: 'grid', gridTemplateColumns: '1fr 2fr', gap: 20,
                            }}>
                                {/* Level card */}
                                <div style={{
                                    background: levelStyle.bg,
                                    borderRadius: 20, padding: '24px',
                                    boxShadow: '0 10px 30px rgba(0,0,0,0.08)',
                                    display: 'flex', flexDirection: 'column', alignItems: 'center',
                                    justifyContent: 'center', textAlign: 'center',
                                }}>
                                    <div style={{ fontSize: 48 }}>
                                        {profile.level === 'Diamond' ? '💎' : profile.level === 'Gold' ? '🥇' : profile.level === 'Platinum' ? '🔱' : profile.level === 'Silver' ? '🥈' : '🥉'}
                                    </div>
                                    <div style={{ color: levelStyle.text, fontWeight: 900, fontSize: 22, marginTop: 8 }}>
                                        {profile.level} Tier
                                    </div>
                                    <div style={{ color: `${levelStyle.text}dd`, fontSize: 13, fontWeight: 700 }}>
                                        {profile.total_xp} XP Total
                                    </div>
                                </div>

                                {/* Summary card */}
                                <div style={{
                                    background: '#FFFFFF',
                                    border: '1px solid #E2E8F0',
                                    boxShadow: '0 10px 30px rgba(0,0,0,0.04)',
                                    borderRadius: 20, padding: '24px',
                                }}>
                                    <div style={{ color: '#0EA5E9', fontWeight: 900, fontSize: 12, marginBottom: 10, letterSpacing: '0.5px' }}>
                                        🧠 AI CURRICULUM SUMMARY
                                    </div>
                                    <p style={{ color: '#1E293B', fontSize: 14, lineHeight: 1.7, margin: '0 0 16px', fontWeight: 600 }}>
                                        {curriculumData?.learning_path_summary || 'Keep up the great work! Complete more lessons to unlock a personalized path.'}
                                    </p>
                                    <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                                        <div style={{
                                            background: '#F0FDF4',
                                            border: '1px solid #BBF7D0',
                                            borderRadius: 12, padding: '10px 14px',
                                            flex: 1,
                                        }}>
                                            <div style={{ color: '#166534', fontWeight: 900, fontSize: 11, marginBottom: 2 }}>WEEKLY GOAL</div>
                                            <div style={{ color: '#15803D', fontSize: 13, fontWeight: 700 }}>{curriculumData?.weekly_goal || 'Complete 2 new lessons'}</div>
                                        </div>
                                        <div style={{
                                            background: '#FFFBEB',
                                            border: '1px solid #FDE68A',
                                            borderRadius: 12, padding: '10px 14px',
                                            flex: 1,
                                        }}>
                                            <div style={{ color: '#92400E', fontWeight: 900, fontSize: 11, marginBottom: 2 }}>NEXT CHALLENGE</div>
                                            <div style={{ color: '#B45309', fontSize: 13, fontWeight: 700 }}>{curriculumData?.next_challenge || 'Try loop blocks'}</div>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        )}

                        {/* Skills analysis */}
                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
                            {/* Strengths */}
                            <div style={{
                                background: '#F0FDF4',
                                border: '1.5px solid #BBF7D0',
                                borderRadius: 20, padding: 20,
                                boxShadow: '0 4px 14px rgba(34,197,94,0.06)'
                            }}>
                                <h3 style={{ color: '#15803D', margin: '0 0 14px', fontWeight: 900, fontSize: 15, display: 'flex', alignItems: 'center', gap: 8 }}>
                                    <span>💪</span> Child's Strengths
                                </h3>
                                {(curriculumData?.strengths?.length > 0) ? (
                                    curriculumData.strengths.map((s, i) => (
                                        <div key={i} style={{
                                            display: 'flex', alignItems: 'center', gap: 10,
                                            marginBottom: 8, background: '#FFFFFF', padding: '8px 12px',
                                            borderRadius: 10, border: '1px solid #DCFCE7'
                                        }}>
                                            <div style={{
                                                width: 8, height: 8, borderRadius: '50%',
                                                background: '#22c55e', flexShrink: 0,
                                            }} />
                                            <span style={{ color: '#166534', fontSize: 13, fontWeight: 700 }}>{s}</span>
                                        </div>
                                    ))
                                ) : (
                                    <p style={{ color: '#64748B', fontSize: 12, margin: 0, fontStyle: 'italic' }}>
                                        Complete more lessons to discover your child's strengths.
                                    </p>
                                )}
                            </div>

                            {/* Weaknesses / Skill Gaps */}
                            <div style={{
                                background: '#FEF2F2',
                                border: '1.5px solid #FECACA',
                                borderRadius: 20, padding: 20,
                                boxShadow: '0 4px 14px rgba(239,68,68,0.06)'
                            }}>
                                <h3 style={{ color: '#B91C1C', margin: '0 0 14px', fontWeight: 900, fontSize: 15, display: 'flex', alignItems: 'center', gap: 8 }}>
                                    <span>⚠️</span> Areas to Improve (Weaknesses)
                                </h3>
                                {(curriculumData?.skill_gaps?.length > 0) ? (
                                    curriculumData.skill_gaps.map((g, i) => (
                                        <div key={i} style={{
                                            display: 'flex', alignItems: 'center', gap: 10,
                                            marginBottom: 8, background: '#FFFFFF', padding: '8px 12px',
                                            borderRadius: 10, border: '1px solid #FEE2E2'
                                        }}>
                                            <div style={{
                                                width: 8, height: 8, borderRadius: '50%',
                                                background: '#ef4444', flexShrink: 0,
                                            }} />
                                            <span style={{ color: '#991B1B', fontSize: 13, fontWeight: 700 }}>{g}</span>
                                        </div>
                                    ))
                                ) : (
                                    <p style={{ color: '#64748B', fontSize: 12, margin: 0, fontStyle: 'italic' }}>
                                        No specific gaps identified yet. Keep learning!
                                    </p>
                                )}
                            </div>
                        </div>

                        {/* Targeted Homework Missions */}
                        {curriculumData?.homework_assignments?.length > 0 && (
                            <div style={{
                                background: 'linear-gradient(135deg, #F0F9FF 0%, #E0F2FE 100%)',
                                border: '1.5px solid #BAE6FD',
                                borderRadius: 20, padding: 20,
                                boxShadow: '0 4px 14px rgba(14,165,233,0.08)'
                            }}>
                                <h2 style={{ color: '#0369A1', fontWeight: 900, fontSize: 18, margin: '0 0 14px', display: 'flex', alignItems: 'center', gap: 8 }}>
                                    <span>📚</span> Targeted AI Homework Missions
                                </h2>
                                <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                                    {curriculumData.homework_assignments.map((hw, i) => (
                                        <div key={i} style={{
                                            background: '#FFFFFF',
                                            border: '1px solid #E0F2FE',
                                            borderRadius: 16, padding: '16px 20px',
                                            boxShadow: '0 2px 8px rgba(0,0,0,0.03)'
                                        }}>
                                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                                                <div style={{ color: '#0F172A', fontWeight: 800, fontSize: 15 }}>
                                                    {hw.title}
                                                </div>
                                                <div style={{ display: 'flex', gap: 6 }}>
                                                    <span style={{
                                                        background: '#F1F5F9', border: '1px solid #CBD5E1',
                                                        borderRadius: 12, padding: '2px 8px', fontSize: 11, fontWeight: 700, color: '#475569'
                                                    }}>
                                                        ⏱️ {hw.estimated_minutes || 10} mins
                                                    </span>
                                                    <span style={{
                                                        background: hw.difficulty === 'hard' ? '#FEF2F2' : hw.difficulty === 'medium' ? '#FFFBEB' : '#F0FDF4',
                                                        border: `1px solid ${hw.difficulty === 'hard' ? '#FECACA' : hw.difficulty === 'medium' ? '#FDE68A' : '#BBF7D0'}`,
                                                        borderRadius: 12, padding: '2px 8px', fontSize: 11, fontWeight: 800,
                                                        color: hw.difficulty === 'hard' ? '#DC2626' : hw.difficulty === 'medium' ? '#D97706' : '#16A34A',
                                                        textTransform: 'capitalize'
                                                    }}>
                                                        {hw.difficulty}
                                                    </span>
                                                </div>
                                            </div>
                                            <div style={{ color: '#475569', fontSize: 13, fontWeight: 600, lineHeight: 1.5, marginBottom: 8 }}>
                                                {hw.objective}
                                            </div>
                                            {hw.target_block_types?.length > 0 && (
                                                <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                                                    <span style={{ fontSize: 11, fontWeight: 800, color: '#0284C7' }}>Target Blocks:</span>
                                                    {hw.target_block_types.map((blk, idx) => (
                                                        <code key={idx} style={{
                                                            background: '#E0F2FE', color: '#0369A1',
                                                            borderRadius: 6, padding: '2px 6px', fontSize: 11, fontWeight: 700
                                                        }}>
                                                            {blk}
                                                        </code>
                                                    ))}
                                                </div>
                                            )}
                                        </div>
                                    ))}
                                </div>
                            </div>
                        )}

                        {/* Recommended Lessons */}
                        {curriculumData?.recommended_lessons?.length > 0 && (
                            <div>
                                <h2 style={{ color: '#0F172A', fontWeight: 900, fontSize: 18, margin: '0 0 16px' }}>
                                    Recommended Next Lessons
                                </h2>
                                <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                                    {curriculumData.recommended_lessons.map((lesson, i) => {
                                        const priorityColors = { high: '#ef4444', medium: '#f59e0b', low: '#22c55e' };
                                        const pc = priorityColors[lesson.priority] || '#0ea5e9';
                                        return (
                                            <div key={i} style={{
                                                display: 'flex', alignItems: 'center', gap: 16,
                                                background: '#FFFFFF',
                                                border: '1px solid #E2E8F0',
                                                boxShadow: '0 4px 12px rgba(0,0,0,0.03)',
                                                borderRadius: 16, padding: '16px 20px',
                                                cursor: 'pointer', transition: 'all 0.2s',
                                            }}
                                                onMouseEnter={e => {
                                                    e.currentTarget.style.background = '#F8FAFC';
                                                    e.currentTarget.style.transform = 'translateX(4px)';
                                                }}
                                                onMouseLeave={e => {
                                                    e.currentTarget.style.background = '#FFFFFF';
                                                    e.currentTarget.style.transform = 'translateX(0)';
                                                }}
                                                onClick={() => navigate(`/studio/${lesson.lesson_id}`)}
                                            >
                                                {/* Number */}
                                                <div style={{
                                                    width: 44, height: 44, borderRadius: 14,
                                                    background: `${pc}15`,
                                                    border: `2px solid ${pc}33`,
                                                    display: 'flex', alignItems: 'center', justify: 'center',
                                                    color: pc, fontWeight: 900, fontSize: 18, flexShrink: 0,
                                                }}>
                                                    {i + 1}
                                                </div>
                                                {/* Content */}
                                                <div style={{ flex: 1 }}>
                                                    <div style={{ color: '#0F172A', fontWeight: 800, fontSize: 15, marginBottom: 4 }}>
                                                        {lesson.title || lesson.lesson_id}
                                                    </div>
                                                    <div style={{ color: '#64748B', fontSize: 12, fontWeight: 600 }}>
                                                        {lesson.reason}
                                                    </div>
                                                </div>
                                                {/* Priority badge */}
                                                <div style={{
                                                    background: `${pc}15`,
                                                    border: `1px solid ${pc}33`,
                                                    borderRadius: 20, padding: '4px 12px',
                                                    color: pc, fontSize: 10, fontWeight: 800,
                                                    textTransform: 'uppercase', letterSpacing: '0.5px',
                                                    flexShrink: 0,
                                                }}>
                                                    {lesson.priority}
                                                </div>
                                                <div style={{ color: '#94A3B8', fontSize: 18, fontWeight: 800 }}>→</div>
                                            </div>
                                        );
                                    })}
                                </div>
                            </div>
                        )}

                        {/* Refresh button */}
                        <button
                            onClick={loadPath}
                            style={{
                                alignSelf: 'center',
                                background: 'linear-gradient(135deg, #0EA5E9, #2563EB)',
                                border: 'none',
                                boxShadow: '0 4px 14px rgba(37,99,235,0.3)',
                                borderRadius: 14, padding: '12px 28px',
                                color: '#FFFFFF', fontWeight: 800, fontSize: 13,
                                cursor: 'pointer', transition: 'all 0.2s',
                            }}
                            onMouseEnter={e => e.currentTarget.style.opacity = '0.9'}
                            onMouseLeave={e => e.currentTarget.style.opacity = '1'}
                        >
                            Regenerate AI Learning Insights
                        </button>
                    </div>
                )}
            </div>
        </div>
    );
}
