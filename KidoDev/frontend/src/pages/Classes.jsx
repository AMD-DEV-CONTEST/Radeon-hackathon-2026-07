import React, { useState, useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import { supabase } from '../utils/supabaseClient';
import { FaArrowLeft, FaLock, FaStar, FaTrophy, FaRocket, FaChevronRight, FaComment } from 'react-icons/fa';
import catSad from '../assets/cat/cat_sad.png';
import catNeutral from '../assets/cat/cat_neutral.png';
import catHappy from '../assets/cat/cat_happy.png';

const COLORS = [
    '#FF6B6B', '#FF9F43', '#FECA57', '#1DD1A1', '#54A0FF',
    '#5F27CD', '#FF9FF3', '#48DBFB', '#EE5A24', '#00D2D3',
    '#6C5CE7', '#FD79A8', '#10AC84', '#F9CA24', '#6AB04C',
    '#EB4D4B', '#22A6B3', '#BE2EDD',
];

const NODE_R = 44;
const V_GAP = 130;
const H_MARGIN = 60;

function nodePos(i, W) {
    if (i === 0) return { x: W / 2, y: 80 };
    const pos1 = i - 1;
    const row = Math.floor(pos1 / 3);
    const col = pos1 % 3;
    const y = 80 + (row + 1) * V_GAP;
    const xs = [H_MARGIN, W / 2, W - H_MARGIN];
    const x = row % 2 === 0 ? xs[col] : xs[2 - col];
    return { x, y };
}

function buildPath(W, count) {
    if (count === 0) return '';
    const pts = Array.from({ length: count }, (_, i) => nodePos(i, W));
    let d = `M ${pts[0].x} ${pts[0].y}`;
    for (let i = 1; i < pts.length; i++) {
        const prev = pts[i - 1];
        const cur = pts[i];
        const my = (prev.y + cur.y) / 2;
        d += ` Q ${prev.x} ${my} ${cur.x} ${cur.y}`;
    }
    return d;
}

const CARD_THEMES = [
    { from: '#667eea', to: '#764ba2' }, { from: '#f093fb', to: '#f5576c' },
    { from: '#4facfe', to: '#00f2fe' }, { from: '#43e97b', to: '#38f9d7' },
    { from: '#fa709a', to: '#fee140' }, { from: '#a18cd1', to: '#fbc2eb' },
    { from: '#fccb90', to: '#d57eeb' }, { from: '#a1c4fd', to: '#c2e9fb' },
    { from: '#fd7af9', to: '#ff758c' }, { from: '#696eed', to: '#f37055' },
];

// Returns star count and colour from score badge string
function getBadgeInfo(badge) {
    if (!badge) return { stars: 0, color: 'rgba(255,255,255,0.2)' };
    if (badge.includes('Gold')) return { stars: 3, color: '#F59E0B' };
    if (badge.includes('Silver')) return { stars: 2, color: '#94A3B8' };
    if (badge.includes('Bronze')) return { stars: 1, color: '#CD7F32' };
    return { stars: 1, color: '#6B7280' }; // Participant
}

import SpriteLoader from '../components/Loader/SpriteLoader';

const Levels = () => {
    const [view, setView] = useState('selection');
    const [selectedLevel, setSelectedLevel] = useState(null);
    const mapRef = useRef(null);
    const [mapW, setMapW] = useState(400);
    const [curriculum, setCurriculum] = useState([]);
    const [loading, setLoading] = useState(true);

    // ── NEW: map of lessonId → { score, badge } from lesson_completions
    const [completions, setCompletions] = useState({});

    useEffect(() => {
        const isHw = (item) => {
            if (!item) return false;
            if (item.is_homework || item.category === 'homework') return true;
            const str = `${item.title || ''} ${item.name || ''} ${item.id || ''} ${item.description || ''}`.toLowerCase();
            return str.includes('homework') || str.includes('home work');
        };

        const fetchAll = async () => {
            const [classesRes, lessonsRes] = await Promise.all([
                supabase.from('course_classes').select('*').order('level', { ascending: true }),
                supabase.from('lessons').select('*').order('order_index', { ascending: true }),
            ]);

            if (classesRes.data) {
                const mainClasses = classesRes.data.filter(c => c.level >= 1 && c.level <= 6 && !isHw(c));
                const curriculumData = mainClasses.map(c => ({
                    ...c,
                    id: `level-${c.level}`,
                    projects: lessonsRes.data
                        ? lessonsRes.data.filter(l => l.class_level === c.level && !isHw(l))
                        : []
                }));
                setCurriculum(curriculumData);
            }

            // Fetch completions for the current logged-in user
            const { data: { user } } = await supabase.auth.getUser();
            if (user) {
                const { data: comps } = await supabase
                    .from('lesson_completions')
                    .select('lesson_id, score, badge')
                    .eq('user_id', user.id);

                if (comps) {
                    const map = {};
                    comps.forEach(c => { map[c.lesson_id] = { score: c.score, badge: c.badge }; });
                    setCompletions(map);
                }
            }

            setLoading(false);
        };
        fetchAll();
    }, []);

    useEffect(() => {
        const el = mapRef.current;
        if (!el) return;
        const ro = new ResizeObserver(entries => setMapW(entries[0].contentRect.width || 400));
        ro.observe(el);
        setMapW(el.offsetWidth || 400);
        return () => ro.disconnect();
    }, [view]);

    useEffect(() => {
        const saved = sessionStorage.getItem('selectedLevelId');
        if (saved && curriculum.length > 0) {
            const found = curriculum.find(c => c.id === saved);
            if (found) { setSelectedLevel(found); setView('map'); }
            sessionStorage.removeItem('selectedLevelId');
        }
    }, [curriculum]);

    // Re-fetch completions when returning from studio
    useEffect(() => {
        if (view !== 'map') return;
        const refetch = async () => {
            const { data: { user } } = await supabase.auth.getUser();
            if (!user) return;
            const { data: comps } = await supabase
                .from('lesson_completions')
                .select('lesson_id, score, badge')
                .eq('user_id', user.id);
            if (comps) {
                const map = {};
                comps.forEach(c => { map[c.lesson_id] = { score: c.score, badge: c.badge }; });
                setCompletions(map);
            }
        };
        refetch();
    }, [view]);

    const openLevel = (cls) => { setSelectedLevel(cls); setView('map'); window.scrollTo(0, 0); };
    const goBack = () => { setView('selection'); setSelectedLevel(null); };

    if (loading) {
        return <SpriteLoader />;
    }

    // ── VIEW 1: LEVEL SELECTION
    if (view === 'selection' || !selectedLevel) {
        return (
            <div style={S.selPage}>
                <div style={{ ...S.blob, top: '-120px', left: '-80px', background: 'radial-gradient(circle,rgba(129,140,248,.35) 0%,transparent 70%)' }} />
                <div style={{ ...S.blob, bottom: '-100px', right: '-60px', background: 'radial-gradient(circle,rgba(244,114,182,.3) 0%,transparent 70%)' }} />
                <div className="container py-5">
                    <div className="text-center mb-5 pt-4">
                        <span style={S.pill}>🚀 KIDO LEARNING</span>
                        <h2 style={S.selHeading}>Your <span style={S.grad}>Coding Path</span></h2>
                        <p style={S.selSub}>Select a level and start building amazing projects!</p>
                    </div>
                    <div className="row g-4">
                        {curriculum.map((cls, idx) => {
                            const theme = CARD_THEMES[idx % CARD_THEMES.length];
                            const hasProjects = cls.projects && cls.projects.length > 0;
                            const firstProjectTitle = hasProjects ? cls.projects[0].title.replace(/^\d+\.\s*/, '') : 'Coming Soon';
                            return (
                                <div key={cls.id} className="col-lg-4 col-md-6">
                                    <div
                                        style={{ ...S.selCard, cursor: hasProjects ? 'pointer' : 'not-allowed', opacity: hasProjects ? 1 : 0.6 }}
                                        onClick={() => hasProjects && openLevel(cls)}
                                        onMouseEnter={e => { if (hasProjects) { e.currentTarget.style.transform = 'translateY(-14px)'; e.currentTarget.style.boxShadow = `0 30px 60px -12px ${theme.from}55`; } }}
                                        onMouseLeave={e => { if (hasProjects) { e.currentTarget.style.transform = 'translateY(0px)'; e.currentTarget.style.boxShadow = '0 4px 24px rgba(0,0,0,0.06)'; } }}
                                    >
                                        <div style={{ ...S.cardBadge, background: `linear-gradient(135deg, ${theme.from}, ${theme.to})`, opacity: hasProjects ? 1 : 0.5 }}>{idx + 1}</div>
                                        <h3 style={S.cardTitle}>{`Level ${cls.level}`}</h3>
                                        {hasProjects ? (
                                            <>
                                                <div style={{ ...S.cardMeta, color: '#334155', fontSize: 13, marginBottom: 8, fontWeight: 800 }}>
                                                    {firstProjectTitle}
                                                </div>
                                                <div style={S.cardMeta}><FaStar color="#d4f51c" size={12} /><span>{cls.projects.length} Projects</span></div>
                                                <div style={{ ...S.cardCta, color: theme.from }}>Enter Level <FaChevronRight size={11} style={{ marginLeft: 6 }} /></div>
                                            </>
                                        ) : (
                                            <div style={{ ...S.cardCta, color: '#94A3B8' }}>No projects yet <FaLock size={11} style={{ marginLeft: 6 }} /></div>
                                        )}
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                </div>
            </div>
        );
    }

    // ── VIEW 2: COILED PROJECT MAP
    const realProjects = selectedLevel.projects;

    // A project is unlocked if:
    //   - it's the first project (always unlocked), OR
    //   - the previous project has been completed (exists in completions)
    const isUnlocked = (idx) => {
        if (idx === 0) return true;
        const prevProject = realProjects[idx - 1];
        return prevProject && !!completions[prevProject.id];
    };

    const projectNodes = [...realProjects];
    while (projectNodes.length < 18) {
        projectNodes.push({ id: `locked-${projectNodes.length}`, title: '???', locked: true });
    }

    const svgH = nodePos(projectNodes.length - 1, mapW).y + 120;
    const pathD = buildPath(mapW, projectNodes.length);

    // Count completed projects in this level for the stats chip
    const completedCount = realProjects.filter(l => completions[l.id]).length;
    const progressPerc = realProjects.length > 0 ? (completedCount / realProjects.length) * 100 : 0;

    // Cat Mood & Dialogue Logic (Only for Level 1 for now)
    const isLevel1 = selectedLevel.level === 1;
    let catImg = catSad;
    let catMsg = "Hi! I'm Kido. I'm lost and hungry... Can you help me find my way by finishing projects? 😿";
    
    if (progressPerc >= 30 && progressPerc < 75) {
        catImg = catNeutral;
        catMsg = "You're doing amazing! I'm starting to feel much better. Let's finish more! 😺";
    } else if (progressPerc >= 75) {
        catImg = catHappy;
        catMsg = "Yay! You're a coding legend! I'm so happy and safe now. Thank you so much! 😻✨";
    }

    return (
        <div style={S.mapPage}>
            {/* Story Companion (Only Level 1) */}
            {isLevel1 && (
                <div style={S.storyBubbleContainer}>
                    <div id="storyBubble" style={S.storyBubble}>
                        <div id="storyCatWrapper" style={S.storyCatWrapper}>
                            <img src={catImg} alt="Cat" style={S.storyCat} />
                        </div>
                        <div style={S.storyTextWrapper}>
                            <div style={S.storyLabel}>KIDO SAYS:</div>
                            <div id="storyText" style={S.storyText}>{catMsg}</div>
                        </div>
                    </div>
                </div>
            )}
            {Array.from({ length: 20 }).map((_, i) => (
                <div key={i} style={{
                    position: 'absolute', borderRadius: '50%',
                    width: Math.random() * 6 + 2, height: Math.random() * 6 + 2,
                    top: `${Math.random() * 100}%`, left: `${Math.random() * 100}%`,
                    background: 'rgba(255,255,255,0.25)', pointerEvents: 'none',
                }} />
            ))}

            <div style={S.mapHeader}>
                <button style={S.backBtn} onClick={goBack}><FaArrowLeft style={{ marginRight: 8 }} /> Levels</button>
                <div style={{ textAlign: 'center' }}>
                    <h1 style={S.mapTitle}>{`Level ${selectedLevel.level}`}</h1>
                    <p style={S.mapSub}>Complete missions to unlock next! 🎮</p>
                </div>
                <div style={{ width: 110 }} />
            </div>

            <div style={S.statsRow}>
                <div style={S.chip}><FaTrophy color="#FFD700" size={13} style={{ marginRight: 5 }} />{completedCount}/{realProjects.length} Done</div>
                <div style={S.chip}><FaStar color="#FF6B6B" size={13} style={{ marginRight: 5 }} />Earn Stars</div>
                <div style={S.chip}><FaRocket color="#54A0FF" size={13} style={{ marginRight: 5 }} />Level Up</div>
            </div>

            <div style={S.mapScroll}>
                <div ref={mapRef} style={{ position: 'relative', width: '100%', maxWidth: 440, margin: '0 auto', minHeight: svgH + 40 }}>
                    <svg
                        style={{ position: 'absolute', top: 0, left: 0, width: '100%', overflow: 'visible', zIndex: 0 }}
                        height={svgH} viewBox={`0 0 ${mapW} ${svgH}`} preserveAspectRatio="none"
                    >
                        <path d={pathD} fill="none" stroke="rgba(0,0,0,0.2)" strokeWidth={18} strokeLinecap="round" strokeLinejoin="round" />
                        <path d={pathD} fill="none" stroke="rgba(255,255,255,0.15)" strokeWidth={14} strokeLinecap="round" strokeLinejoin="round" />
                        <path
                            d={pathD}
                            fill="none"
                            stroke="rgba(255,255,255,0.6)"
                            strokeWidth={6}
                            strokeDasharray="12 16"
                            style={{
                                animation: 'pathGlow 6s linear infinite'
                            }}
                        />
                    </svg>

                    {projectNodes.map((p, i) => {
                        const pos = nodePos(i, mapW);
                        const color = COLORS[i % COLORS.length];
                        const isRealProject = !p.locked;
                        const unlocked = isRealProject && isUnlocked(i);
                        const isFirst = i === 0;
                        const cleanTitle = p.title.replace(/^\d+\.\s*/, '');
                        const completion = completions[p.id];
                        const { stars, color: starColor } = getBadgeInfo(completion?.badge);
                        const isDone = !!completion;

                        return (
                            <div key={p.id} style={{
                                position: 'absolute',
                                left: pos.x - NODE_R, top: pos.y - NODE_R,
                                width: NODE_R * 2, height: NODE_R * 2,
                                zIndex: 5,
                            }}>
                                {isFirst && !isDone && <div style={S.pulseRing} />}

                                {/* Completed checkmark ring */}
                                {isDone && (
                                    <div style={{
                                        position: 'absolute', inset: -6, borderRadius: '50%',
                                        border: `3px solid ${starColor}`,
                                        boxShadow: `0 0 12px ${starColor}88`,
                                        zIndex: -1,
                                    }} />
                                )}

                                {unlocked ? (
                                    <Link
                                        to={`/studio/${p.id}`}
                                        onClick={() => sessionStorage.setItem('selectedLevelId', selectedLevel.id)}
                                        style={{
                                            ...S.node,
                                            background: isDone
                                                ? `linear-gradient(135deg, ${color}, ${color}cc)`
                                                : color,
                                            animation: 'float 3s ease-in-out infinite',
                                            boxShadow: `0 8px 0 ${color}99, 0 12px 30px ${color}55`,
                                            border: isFirst && !isDone
                                                ? '4px solid rgba(255,255,255,0.9)'
                                                : isDone
                                                    ? `3px solid ${starColor}`
                                                    : '3px solid rgba(255,255,255,0.5)',
                                            opacity: 1,
                                        }}
                                        className="node-hover"
                                        onMouseDown={e => e.currentTarget.style.animation = 'bounceClick 0.2s'}
                                    >
                                        {isDone && (
                                            <div style={{
                                                position: 'absolute',
                                                top: -4,
                                                right: -4,
                                                width: 24,
                                                height: 24,
                                                borderRadius: '50%',
                                                background: 'linear-gradient(135deg, #10B981, #06B6D4)',
                                                display: 'flex',
                                                alignItems: 'center',
                                                justifyContent: 'center',
                                                boxShadow: '0 2px 6px rgba(0,0,0,0.3)',
                                                animation: 'popCheck 0.4s ease-out forwards',
                                            }}>
                                                <span style={{ color: 'white', fontSize: 14 }}>✔️</span>
                                            </div>
                                        )}

                                        <style>{`
    @keyframes popCheck {
        0% { transform: scale(0); opacity: 0; }
        60% { transform: scale(1.2); opacity: 1; }
        100% { transform: scale(1); }
    }
`}</style>
                                        <span style={S.nodeNum}>{i + 1}</span>
                                        <span style={S.nodeLabel}>{cleanTitle}</span>

                                        {isFirst && !isDone && <span style={S.startTag}>▶ GO!</span>}

                                        {/* Stars: gold if earned, dim if not */}
                                        <div style={S.starsRow}>
                                            {[1, 2, 3].map(s => (
                                                <FaStar key={s} size={9}
                                                    color={s <= stars ? starColor : 'rgba(249, 216, 5, 0.96)'}
                                                    style={{ filter: s <= stars ? `drop-shadow(0 0 3px ${starColor})` : 'none' }}
                                                />
                                            ))}
                                        </div>

                                        {/* Dynamic Score Pill on completed nodes */ }
{isDone && completion.score != null && (() => {
                                            const score = completion.score;

                                            // Dynamically set color based on score
                                            let bgColor = '#F59E0B'; // default: gold
                                            if (score >= 90) bgColor = '#10B981'; // green for high score
                                            else if (score >= 60) bgColor = '#FBBF24'; // yellow/orange for medium
                                            else bgColor = '#EF4444'; // red for low

                                            return (
                                                <div style={{
                                                    position: 'absolute',
                                                    bottom: -20,
                                                    left: '50%',
                                                    transform: 'translateX(-50%) scale(0)',
                                                    background: bgColor,
                                                    color: 'white',
                                                    fontSize: 10,
                                                    fontWeight: 700,
                                                    padding: '2px 8px',
                                                    borderRadius: 20,
                                                    whiteSpace: 'nowrap',
                                                    boxShadow: `0 2px 8px ${bgColor}66`,
                                                    animation: 'scorePop 0.4s ease-out forwards',
                                                }}>
                                                    {score}/100
                                                </div>
                                            )
                                        })()}

                                        <style>{`
    @keyframes scorePop {
        0% { transform: translateX(-50%) scale(0); opacity: 0; }
        60% { transform: translateX(-50%) scale(1.2); opacity: 1; }
        100% { transform: translateX(-50%) scale(1); }
    }
`}</style>
                                    </Link>
                                ) : (
                                    <div style={{
                                        ...S.node,
                                        ...S.nodeLocked,
                                        // Faded colour hint for real projects waiting to be unlocked
                                        background: isRealProject
                                            ? `${color}33`
                                            : 'rgba(255,255,255,0.07)',
                                    }}>
                                        <FaLock size={18} color={isRealProject ? `${color}99` : '#94A3B8'} />
                                        <span style={S.nodeLockedLabel}>{cleanTitle}</span>
                                    </div>
                                )}
                            </div>
                        );
                    })}
                </div>
            </div>
        </div>
    );
};

const S = {
    selPage: { minHeight: '100vh', background: '#F8FAFF', position: 'relative', overflow: 'hidden', paddingTop: 80 },
    blob: { position: 'absolute', width: 500, height: 500, zIndex: 0, pointerEvents: 'none' },
    pill: { display: 'inline-flex', background: 'linear-gradient(135deg,#EEF2FF,#E0E7FF)', color: '#6366F1', padding: '6px 20px', borderRadius: 50, fontWeight: 900, fontSize: 13, letterSpacing: 1, marginBottom: 16, border: '1px solid #C7D2FE' },
    selHeading: { fontSize: 'clamp(30px,5vw,52px)', fontWeight: 900, color: '#1E293B', marginBottom: 12, lineHeight: 1.1 },
    grad: { background: 'linear-gradient(90deg,#6366F1,#EC4899)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' },
    selSub: { color: '#64748B', fontSize: 18, marginBottom: 0 },
    selCard: { background: 'white', borderRadius: 28, padding: '36px 28px', border: '2px solid #F1F5F9', cursor: 'pointer', textAlign: 'center', transition: 'all 0.35s cubic-bezier(0.34,1.56,0.64,1)', boxShadow: '0 4px 24px rgba(0,0,0,0.06)', position: 'relative', transformStyle: 'preserve-3d', },
    cardBadge: { width: 72, height: 72, borderRadius: 22, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 28, fontWeight: 900, margin: '0 auto 20px', color: 'white', boxShadow: '0 8px 20px rgba(0,0,0,0.2)' },
    cardTitle: { fontWeight: 900, fontSize: 17, color: '#0F172A', marginBottom: 8 },
    cardMeta: { display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6, color: '#94A3B8', fontSize: 12, fontWeight: 700, marginBottom: 4 },
    cardCta: { display: 'flex', alignItems: 'center', justifyContent: 'center', marginTop: 12, fontWeight: 800, fontSize: 13 },
    mapPage: {
        position: 'relative', overflow: 'hidden', paddingBottom: 80, paddingTop: 0, minHeight: '100vh',
        background: 'linear-gradient(270deg,#0F0C29,#302B63,#24243e)',
        backgroundSize: '400% 400%',
        animation: 'gradientShift 12s ease infinite',
},
    mapHeader: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '88px 32px 8px', position: 'relative', zIndex: 10 },
    backBtn: { display: 'flex', alignItems: 'center', background: 'rgba(255,255,255,0.12)', backdropFilter: 'blur(12px)', border: '2px solid rgba(255,255,255,0.25)', padding: '10px 22px', borderRadius: 50, fontWeight: 800, color: 'white', cursor: 'pointer', fontSize: 14, transition: 'all 0.2s', whiteSpace: 'nowrap' },
    mapTitle: { color: 'white', fontWeight: 900, fontSize: 'clamp(18px,3vw,28px)', marginBottom: 4, textShadow: '0 2px 20px rgba(0,0,0,0.4)' },
    mapSub: { color: 'rgba(255,255,255,0.65)', fontSize: 13, fontWeight: 600, margin: 0 },
    statsRow: { display: 'flex', justifyContent: 'center', gap: 10, padding: '12px 24px 0', position: 'relative', zIndex: 10 },
    chip: { display: 'flex', alignItems: 'center', background: 'rgba(255,255,255,0.10)', border: '1px solid rgba(255,255,255,0.18)', color: 'rgba(255,255,255,0.88)', padding: '6px 16px', borderRadius: 30, fontSize: 12, fontWeight: 700, backdropFilter: 'blur(8px)' },
    mapScroll: { overflowY: 'auto', overflowX: 'hidden', padding: '20px 16px 60px', position: 'relative', zIndex: 5 },
    node: { width: '100%', height: '100%', borderRadius: '50%', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', textDecoration: 'none', transition: 'transform 0.25s cubic-bezier(0.34,1.56,0.64,1)', cursor: 'pointer', position: 'relative', gap: 2 },
    nodeLocked: { background: 'rgba(255,255,255,0.07)', border: '2px solid rgba(255,255,255,0.12)', cursor: 'not-allowed', boxShadow: 'none', gap: 6 },
    nodeNum: { fontSize: 22, fontWeight: 900, color: 'white', lineHeight: 1, textShadow: '0 2px 8px rgba(0,0,0,0.3)' },
    nodeLabel: { fontSize: 9, fontWeight: 800, color: 'rgba(255,255,255,0.9)', textAlign: 'center', lineHeight: 1.2, maxWidth: 74, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' },
    nodeLockedLabel: { fontSize: 9, fontWeight: 700, color: 'rgba(255,255,255,0.3)', textAlign: 'center', lineHeight: 1.2, maxWidth: 74, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' },
    startTag: { background: 'rgba(255,255,255,0.28)', color: 'white', fontSize: 8, fontWeight: 900, padding: '2px 8px', borderRadius: 20, border: '1px solid rgba(255,255,255,0.5)', letterSpacing: 0.5 },
    starsRow: { display: 'flex', gap: 2, marginTop: 2 },
    pulseRing: { position: 'absolute', inset: -8, borderRadius: '50%', border: '3px solid rgba(255,255,255,0.6)', animation: 'pulse 2s ease-in-out infinite', zIndex: -1, pointerEvents: 'none' },
    
    // NEW Gamification Styles
    storyBubbleContainer: {
        position: 'fixed',
        bottom: 30,
        left: '50%',
        transform: 'translateX(-50%)',
        width: '90%',
        maxWidth: 550,
        zIndex: 100,
        pointerEvents: 'none',
    },
    storyBubble: {
        background: 'rgba(255, 255, 255, 0.15)',
        backdropFilter: 'blur(16px)',
        border: '2px solid rgba(255, 255, 255, 0.2)',
        borderRadius: 24,
        padding: '16px 20px',
        display: 'flex',
        alignItems: 'center',
        gap: 16,
        boxShadow: '0 12px 40px rgba(0,0,0,0.3)',
        animation: 'slideUp 0.6s cubic-bezier(0.19, 1, 0.22, 1)',
        pointerEvents: 'auto',
    },
    storyCatWrapper: {
        width: 70,
        height: 70,
        flexShrink: 0,
        position: 'relative',
    },
    storyCat: {
        width: '100%',
        height: '100%',
        objectFit: 'contain',
        animation: 'breathe 3s ease-in-out infinite',
    },
    storyTextWrapper: {
        flex: 1,
    },
    storyLabel: {
        fontSize: 10,
        fontWeight: 900,
        color: '#F97316',
        letterSpacing: 1,
        marginBottom: 4,
    },
    storyText: {
        fontSize: 14,
        color: 'white',
        fontWeight: 600,
        lineHeight: 1.4,
    },
};

const animations = `
@keyframes slideUp {
    from { transform: translateY(100px); opacity: 0; }
    to { transform: translateY(0); opacity: 1; }
}

@keyframes pulse {
    0% { transform: scale(1); opacity: 0.6; }
    100% { transform: scale(1.6); opacity: 0; }
}

/* 🌈 Gradient animation */
@keyframes gradientShift {
    0% { background-position: 0% 50%; }
    100% { background-position: 100% 50%; }
}

/* 🫧 Floating effect */
@keyframes float {
    0% { transform: translateY(0px); }
    50% { transform: translateY(-6px); }
    100% { transform: translateY(0px); }
}

/* 🧠 3D hover tilt illusion */
.node-hover:hover {
    transform: perspective(600px) rotateX(8deg) rotateY(-8deg) scale(1.08);
}

/* ✨ sparkle animation */
@keyframes sparkle {
    0% { opacity: 0; transform: scale(0); }
    50% { opacity: 1; transform: scale(1.2); }
    100% { opacity: 0; transform: scale(0); }
}

/* 💥 click bounce */
@keyframes bounceClick {
    0% { transform: scale(1); }
    50% { transform: scale(0.9); }
    100% { transform: scale(1); }
}

/* 🐱 cat breathing */
@keyframes breathe {
    0% { transform: scale(1); }
    50% { transform: scale(1.04); }
    100% { transform: scale(1); }
}

/* 🌟 glowing path */
@keyframes pathGlow {
    0% { stroke-dashoffset: 0; }
    100% { stroke-dashoffset: 100; }
}

@media (max-width: 600px) {
    #storyBubble {
        padding: 10px 14px !important;
        gap: 12px !important;
    }
    #storyCatWrapper {
        width: 50px !important;
        height: 50px !important;
    }
    #storyText {
        font-size: 12px !important;
    }
}
`;


if (typeof document !== 'undefined') {
    const style = document.createElement('style');
    style.id = 'kido-story-styles';
    style.innerHTML = animations;
    document.head.appendChild(style);
}

export default Levels;