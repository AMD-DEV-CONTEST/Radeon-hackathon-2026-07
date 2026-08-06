import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { supabase } from '../utils/supabaseClient';
import {
    FaArrowLeft, FaLock, FaStar,
    FaTrophy, FaRocket, FaChevronRight,
    FaGift, FaShieldAlt, FaCompass,
    FaFlagCheckered, FaBolt, FaGamepad,
} from 'react-icons/fa';
import IslandWorldMap from './IslandWorldMap';
import { useTheme } from '../utils/ThemeContext';
import SpriteLoader from '../components/Loader/SpriteLoader';
import CatchDonut from './Games/CatchDonut';
import TrafficPatrol from './Games/TrafficControl';
import CoinMaze from './Games/CoinMaze';
import { useAudio } from './Games/AudioProvider';
import './Levels.scss';

/* ─────────────────────────────────────────
   CARD THEMES
   Each level gets its own vivid personality
───────────────────────────────────────── */
const THEMES = [
    { band: '#FF5C5C', ring: ['#FF5C5C', '#FF9A3C'], wash: 'rgba(255,92,92,.09)' },
    { band: '#00B4E6', ring: ['#00B4E6', '#00D9FF'], wash: 'rgba(0,180,230,.09)' },
    { band: '#00C98D', ring: ['#00C98D', '#00F0B5'], wash: 'rgba(0,201,141,.09)' },
    { band: '#FFD000', ring: ['#FFD000', '#FFEC6E'], wash: 'rgba(255,208,0,.09)' },
    { band: '#FF8FAB', ring: ['#FF8FAB', '#FFBDD0'], wash: 'rgba(255,143,171,.09)' },
    { band: '#8B5CF6', ring: ['#8B5CF6', '#C4B5FD'], wash: 'rgba(139,92,246,.09)' },
    { band: '#FF8C00', ring: ['#FF8C00', '#FFBE5C'], wash: 'rgba(255,140,0,.09)' },
    { band: '#06B6D4', ring: ['#06B6D4', '#67E8F9'], wash: 'rgba(6,182,212,.09)' },
    { band: '#10B981', ring: ['#10B981', '#6EE7B7'], wash: 'rgba(16,185,129,.09)' },
    { band: '#F43F5E', ring: ['#F43F5E', '#FB7185'], wash: 'rgba(244,63,94,.09)' },
];

/* Node colours for the map — warm, vivid */
const NODE_COLORS = [
    '#FF5C5C', '#00B4E6', '#00C98D', '#FFD000', '#FF8FAB',
    '#8B5CF6', '#FF8C00', '#06B6D4', '#10B981', '#F43F5E',
    '#3B82F6', '#FBBF24', '#EF4444', '#14B8A6', '#A855F7',
    '#FB923C', '#22D3EE', '#4ADE80',
];

const FEATURES = [
    { label: 'LAB', color: '#FF5C5C', title: 'Loop & Timing Lab', desc: 'Repeat and wait blocks keep your game alive and exciting.' },
    { label: 'SMART', color: '#00B4E6', title: 'Smart Decisions', desc: 'If / else blocks make your projects react the right way.' },
    { label: 'FULL', color: '#00C98D', title: 'Full Scratch Stack', desc: 'Motion, Looks, Sounds, Pen — every block fits inside.' },
    { label: 'AI', color: '#8B5CF6', title: 'AI Studio Guide', desc: 'Your own AI tutor walks you through every challenge.' },
];

/* Floating emoji decorations on the hero page */
const DECOS = ['STAR', 'GOAL', 'WIN', 'SPARK', 'PLAY'];

/* ─── MAP GEOMETRY ─── */
const NODE_R = 40;
const V_GAP = 148;
const H_MARGIN = 76;
const RING_R = 35;
const RING_C = 2 * Math.PI * RING_R;

function nodePos(i, W) {
    if (i === 0) return { x: W / 2, y: 80 };
    const row = Math.floor((i - 1) / 3);
    const col = (i - 1) % 3;
    const xs = [H_MARGIN, W / 2, W - H_MARGIN];
    return {
        x: row % 2 === 0 ? xs[col] : xs[2 - col],
        y: 80 + (row + 1) * V_GAP,
    };
}

function buildPath(W, n) {
    if (n === 0) return '';
    const pts = Array.from({ length: n }, (_, i) => nodePos(i, W));
    let d = `M ${pts[0].x} ${pts[0].y}`;
    for (let i = 1; i < pts.length; i++) {
        const p = pts[i - 1], c = pts[i];
        d += ` Q ${p.x} ${(p.y + c.y) / 2} ${c.x} ${c.y}`;
    }
    return d;
}

/* ─── HELPERS ─── */
function getBadge(badge) {
    if (!badge) return { stars: 0, color: 'rgba(255,255,255,.35)' };
    if (badge.includes('Gold')) return { stars: 3, color: '#FFD000' };
    if (badge.includes('Silver')) return { stars: 2, color: '#B0B8C8' };
    if (badge.includes('Bronze')) return { stars: 1, color: '#D4845A' };
    return { stars: 1, color: '#B0B8C8' };
}

function catMood(p = 0) {
    if (p >= 75) return { icon: 'LEGEND', mood: 'Legendary!', msg: "You're on fire! The guide is glowing!", tier: 'Champion' };
    if (p >= 35) return { icon: 'GREAT', mood: 'Crushing it!', msg: 'Keep going and unlock more surprises!', tier: 'Explorer' };
    return { icon: 'READY', mood: "Let's Go!", msg: 'Finish a mission to power up your guide!', tier: 'Rookie' };
}

const cleanTitle = (t = '') =>
    t.replace(/^Class\s*\d+\s*[:\-–]*\s*/i, '')
        .replace(/^Level\s*\d+\s*[:\-–]*\s*/i, '')
        .trim();

/* ─── SVG Ring component ─── */
function Ring({ pct, colors, size = 72 }) {
    const id = `rg-${colors[0].replace('#', '')}-${colors[1].replace('#', '')}`;
    const offset = RING_C - (Math.min(pct, 100) / 100) * RING_C;
    const indicator = pct >= 100 ? 'SUCCESS' : pct > 0 ? 'START' : 'READY';
    return (
        <svg className="lc-ring" viewBox="0 0 74 74" width={size} height={size}>
            <defs>
                <linearGradient id={id} x1="0%" y1="0%" x2="100%" y2="100%">
                    <stop offset="0%" stopColor={colors[0]} />
                    <stop offset="100%" stopColor={colors[1]} />
                </linearGradient>
            </defs>
            <circle className="lc-ring-base" cx="37" cy="37" r={RING_R} />
            <circle
                className="lc-ring-fill"
                cx="37" cy="37" r={RING_R}
                stroke={`url(#${id})`}
                strokeDasharray={RING_C}
                strokeDashoffset={offset}
            />
            <text x="37" y="40" className="lc-ring-center">{indicator}</text>
        </svg>
    );
}

/* ════════════════════════════════════════════════════
   MAIN COMPONENT
════════════════════════════════════════════════════ */
export default function Levels() {
    const { theme, themeAssets } = useTheme();
    const [view, setView] = useState('selection');
    const [selectedLevel, setSelectedLevel] = useState(null);
    const mapRef = useRef(null);
    const [mapW, setMapW] = useState(440);
    const [curriculum, setCurriculum] = useState([]);
    const [loading, setLoading] = useState(true);
    const [mapLoading, setMapLoading] = useState(false);
    const [completions, setCompletions] = useState({});
    const [paymentStatus, setPaymentStatus] = useState('loading');
    const [currentGame, setCurrentGame] = useState(null);
    const { pause } = useAudio();
    const navigate = useNavigate();
    
    const [limitMinutes, setLimitMinutes] = useState(null);
    const [timeLeftMinutes, setTimeLeftMinutes] = useState(null);

    /* Role-based access control */
    useEffect(() => {
        const role = localStorage.getItem('kido_auth_role');
        if (role !== 'kid') {
            if (role === 'school') navigate('/school-dashboard', { replace: true });
            else if (role === 'parent') navigate('/parent-dashboard', { replace: true });
            else navigate('/auth', { replace: true });
        }
    }, [navigate]);

    /* Time Left calculator */
    useEffect(() => {
        if (limitMinutes === null) return;
        const localChildId = localStorage.getItem('kido_child_id');
        if (!localChildId) return;

        const updateTimeLeft = () => {
            const todayStr = new Date().toISOString().split('T')[0];
            let usage = null;
            try {
                usage = JSON.parse(localStorage.getItem(`kido_usage_${localChildId}`) || 'null');
            } catch (e) {
                usage = null;
            }
            const used = (usage && usage.date === todayStr) ? usage.minutesUsed : 0;
            const remaining = Math.max(0, limitMinutes - used);
            setTimeLeftMinutes(remaining);
        };

        updateTimeLeft();
        const interval = setInterval(updateTimeLeft, 10000);
        return () => clearInterval(interval);
    }, [limitMinutes]);

    /* fetch */
    useEffect(() => {
        const initLevels = async () => {
            const localChildId = localStorage.getItem('kido_child_id');
            const targetCol = localChildId ? 'child_id' : 'user_id';
            
            // Check cache for instant rendering
            let hasCache = false;
            const isHw = (item) => {
                if (!item) return false;
                if (item.is_homework || item.category === 'homework') return true;
                const str = `${item.title || ''} ${item.name || ''} ${item.id || ''} ${item.description || ''}`.toLowerCase();
                return str.includes('homework') || str.includes('home work');
            };

            try {
                const cachedCurr = sessionStorage.getItem('kido_curriculum_cache');
                const cachedComps = sessionStorage.getItem('kido_completions_cache');
                if (cachedCurr) {
                    const parsed = JSON.parse(cachedCurr);
                    const filteredCache = parsed.filter(c => !isHw(c)).map(c => ({
                        ...c,
                        projects: (c.projects || []).filter(p => !isHw(p))
                    }));
                    setCurriculum(filteredCache);
                    if (cachedComps) setCompletions(JSON.parse(cachedComps));
                    setLoading(false);
                    hasCache = true;
                }
            } catch (e) {
                // Ignore cache parse error
            }

            if (!hasCache) {
                setLoading(true);
            }

            const safetyTimeout = setTimeout(() => {
                setLoading(false);
            }, 10000);

            try {
                // Fetch curriculum and user profile data concurrently
                const [clsR, lesR, childRes, compsRes] = await Promise.all([
                    supabase.from('course_classes').select('*').order('level', { ascending: true }),
                    supabase.from('lessons').select('*').order('order_index', { ascending: true }),
                    localChildId ? supabase.from('children').select('payment_status, daily_limit_minutes').eq('id', localChildId).maybeSingle() : Promise.resolve(null),
                    localChildId ? supabase.from('lesson_completions').select('lesson_id,score,badge').eq('child_id', localChildId) : Promise.resolve(null)
                ]);
                
                if (clsR.data) {
                    // Filter strictly for active curriculum levels (1 to 6)
                    const mainLevels = clsR.data.filter(c => c.level >= 1 && c.level <= 6 && !isHw(c));
                    const formatted = mainLevels.map(c => ({
                        ...c,
                        id: `level-${c.level}`,
                        projects: lesR.data ? lesR.data.filter(l => l.class_level === c.level && !isHw(l)) : [],
                    }));
                    setCurriculum(formatted);
                    try { sessionStorage.setItem('kido_curriculum_cache', JSON.stringify(formatted)); } catch(e){}
                }

                // Payment & Limits check
                let isPending = false;
                if (localChildId && childRes?.data) {
                    if (childRes.data.payment_status === 'pending') isPending = true;
                    if (childRes.data.daily_limit_minutes) {
                        setLimitMinutes(childRes.data.daily_limit_minutes);
                    }
                } else if (!localChildId) {
                    const { data: { user } } = await supabase.auth.getUser();
                    if (user) {
                        const [{ data: parentProfile }, { data: schoolProfile }] = await Promise.all([
                            supabase.from('parent_profiles').select('payment_status').eq('id', user.id).maybeSingle(),
                            supabase.from('schools').select('payment_status').eq('id', user.id).maybeSingle()
                        ]);
                        if (parentProfile?.payment_status === 'pending' || schoolProfile?.payment_status === 'pending') isPending = true;

                        const { data: userComps } = await supabase.from('lesson_completions').select('lesson_id,score,badge').eq('user_id', user.id);
                        if (userComps) {
                            const m = {};
                            userComps.forEach(c => { m[c.lesson_id] = { score: c.score, badge: c.badge }; });
                            setCompletions(m);
                            try { sessionStorage.setItem('kido_completions_cache', JSON.stringify(m)); } catch(e){}
                        }
                    }
                }
                
                setPaymentStatus(isPending ? 'pending' : 'paid');

                if (localChildId && compsRes?.data && !isPending) {
                    const m = {};
                    compsRes.data.forEach(c => { m[c.lesson_id] = { score: c.score, badge: c.badge }; });
                    setCompletions(m);
                    try { sessionStorage.setItem('kido_completions_cache', JSON.stringify(m)); } catch(e){}
                }
            } catch (err) {
                console.error("Levels data sync error:", err);
            } finally {
                setLoading(false);
                clearTimeout(safetyTimeout);
                window.scrollTo({ top: 0, behavior: 'instant' });
            }
        };

        initLevels();
    }, []);

    /* map resize */
    useEffect(() => {
        const el = mapRef.current;
        if (!el) return;
        const ro = new ResizeObserver(e => setMapW(e[0].contentRect.width || 440));
        ro.observe(el);
        setMapW(el.offsetWidth || 440);
        return () => ro.disconnect();
    }, [view]);

    /* restore session */
    useEffect(() => {
        const id = sessionStorage.getItem('selectedLevelId');
        if (id && curriculum.length) {
            const found = curriculum.find(c => c.id === id);
            if (found) { setSelectedLevel(found); setView('map'); }
            sessionStorage.removeItem('selectedLevelId');
        }
    }, [curriculum]);

    /* derived */
    const levelPct = useMemo(() => {
        const m = {};
        curriculum.forEach(c => {
            const ls = c.projects || [];
            m[c.level] = ls.length ? Math.round(ls.filter(l => completions[l.id]).length / ls.length * 100) : 0;
        });
        return m;
    }, [curriculum, completions]);

    const overall = useMemo(() => {
        const total = curriculum.reduce((s, c) => s + (c.projects?.length || 0), 0);
        const finished = curriculum.reduce((s, c) => s + (c.projects?.filter(p => completions[p.id]).length || 0), 0);
        return { total, finished, pct: total ? Math.round(finished / total * 100) : 0 };
    }, [curriculum, completions]);

    const mood = catMood(overall.pct);

    const openLevel = (cls) => {
        setSelectedLevel(cls);
        setView('map');
        window.scrollTo(0, 0);
    };
    const goBack = () => { setView('selection'); setSelectedLevel(null); };

    if (loading || mapLoading) return <SpriteLoader />;

    if (currentGame === 'catch-donut') {
        return (
            <CatchDonut
                onBack={() => {
                    pause();
                    setCurrentGame(null);
                }}
            />
        );
    }
    if (currentGame === 'traffic-patrol') {
        return (
            <TrafficPatrol
                onBack={() => {
                    pause();
                    setCurrentGame(null);
                }}
            />
        );
    }
    if (currentGame === 'coin-maze') {
        return (
            <CoinMaze
                onBack={() => {
                    pause();
                    setCurrentGame(null);
                }}
            />
        );
    }

    if (paymentStatus === 'pending') {
        return (
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', minHeight: '100vh', background: '#0F172A', color: 'white', fontFamily: 'var(--font-main)' }}>
                <FaShieldAlt style={{ fontSize: '4rem', color: '#F59E0B', marginBottom: '24px' }} />
                <h2 style={{ fontSize: '2.5rem', marginBottom: '16px', fontWeight: 'bold' }}>Payment Required</h2>
                <p style={{ maxWidth: '450px', textAlign: 'center', color: '#94A3B8', marginBottom: '32px', fontSize: '1.1rem', lineHeight: '1.6' }}>
                    Your account registration is incomplete. Please ask your parent or teacher to complete the payment to unlock Playland!
                </p>
                <button
                    onClick={() => {
                        localStorage.removeItem('kido_auth_role');
                        localStorage.removeItem('kido_user_name');
                        localStorage.removeItem('kido_child_id');
                        supabase.auth.signOut().then(() => window.location.href = '/');
                    }}
                    style={{ padding: '12px 24px', background: 'transparent', border: '1px solid #64748B', color: '#CBD5E1', borderRadius: '8px', cursor: 'pointer' }}
                >
                    Return Home
                </button>
            </div>
        );
    }

    /* ════════════════════════════════════════════════════
       SELECTION VIEW
    ════════════════════════════════════════════════════ */
    if (view === 'selection' || !selectedLevel) return (
        <div className="levels-selection-page">
            {/* PREMIUM STATS BADGES */}
            <div className="floating-stats-badges">
                <div className="stat-badge-premium xp-badge">
                    <div className="badge-info">
                        <span className="badge-label">XP</span>
                        <span className="badge-value">{Math.round((overall.finished * 50) + (overall.total * 10))}</span>
                    </div>
                </div>
                <div className="stat-badge-premium levels-badge">
                    <div className="badge-info">
                        <span className="badge-label">MISSIONS</span>
                        <span className="badge-value">{overall.finished} / {overall.total}</span>
                    </div>
                </div>
                <div className="stat-badge-premium rank-badge">
                    <div className="badge-info">
                        <span className="badge-label">RANK</span>
                        <span className="badge-value">LVL {Math.floor((overall.finished * 50) / 200) + 1}</span>
                    </div>
                </div>
            </div>

            {/* HEADER REMOVED AS REQUESTED */}


            {/* FLOATING DECORATIONS */}
            {DECOS.map((deco, idx) => (
                <div key={idx} className={`floating-deco deco-${deco.toLowerCase()}`}>
                    {deco === 'STAR' && <FaStar />}
                    {deco === 'GOAL' && <FaFlagCheckered />}
                    {deco === 'WIN' && <FaTrophy />}
                    {deco === 'SPARK' && <FaBolt />}
                    {deco === 'PLAY' && <FaGamepad />}
                </div>
            ))}

            <section className="levels-grid">
                {curriculum.map((cls, idx) => {
                    const hasProj = cls.projects?.length > 0;
                    const firstProj = hasProj ? cls.projects[0] : null;
                    const sub = firstProj ? firstProj.title.replace(/^\d+\.\s*/, '') : 'Coming soon';
                    const pct = levelPct[cls.level] || 0;
                    const unlocked = true; // Always unlocked as requested
                    const canOpen = hasProj && unlocked;
                    const LEVEL_NAMES = {
                        1: "Beginner",
                        2: "Explorer",
                        3: "Creator",
                        4: "Builder",
                        5: "AI Seekho 1",
                        6: "AI Seekho 2"
                    };
                    const label = LEVEL_NAMES[cls.level] || `Quest ${cls.level}`;
                    const starsList = Array.from({ length: 3 }, (_, i) => i < Math.round(pct / 100 * 3));
                    const xp = hasProj ? cls.projects.length * 20 : 0;

                    return (
                        <article
                            key={cls.id}
                            className={`level-stone-card ${!unlocked ? 'level-stone-card--locked' : ''} ${!hasProj ? 'level-stone-card--coming' : ''}`}
                            onClick={() => canOpen && openLevel(cls)}
                        >
                            <div className={`stone-status-badge ${unlocked ? 'is-unlocked' : 'is-locked'}`}>
                                {unlocked ? 'Unlocked' : 'Locked'}
                            </div>

                            <img src={themeAssets.levels_stone} className="stone-bg" alt="Level Stone" />

                            <div className="stone-content">
                                <div className="stone-class-info">{label}</div>
                                
                                <div className="stone-progress-circle-wrapper">
                                    <svg className="stone-circle-svg" viewBox="0 0 100 100">
                                        <circle className="stone-circle-bg" cx="50" cy="50" r="40" />
                                        <circle
                                            className="stone-circle-fill"
                                            cx="50" cy="50" r="40"
                                            style={{ strokeDashoffset: 251.2 - (251.2 * pct) / 100 }}
                                        />
                                        <text x="50" y="55" className="stone-circle-text">{pct}%</text>
                                    </svg>
                                    <div className="stone-progress-label">Mastery</div>
                                </div>

                                <div className="stone-stats-centered">
                                    <div className="stone-xp-badge">
                                        <FaTrophy />
                                        <span>+{xp} XP</span>
                                    </div>
                                    <div className="stone-mission-count">{cls.projects?.length || 0} missions</div>
                                </div>

                                {unlocked && hasProj ? (
                                    <div className="stone-enter-btn">Enter</div>
                                ) : (
                                    <div className="stone-locked-placeholder" />
                                )}
                            </div>
                        </article>
                    );
                })}

            </section>
        </div>
    );

    /* ════════════════════════════════════════════════════
       MAP VIEW — Full-Screen Island World
    ════════════════════════════════════════════════════ */
    const real = selectedLevel.projects || [];
    const isUnlocked = (i) => true; // Always unlocked as requested

    let nodes = [...real];
    if (selectedLevel.level === 1 && real.length >= 9) {
        const newNodes = [];
        real.forEach((proj, idx) => {
            newNodes.push(proj);
            if (idx === 2) {
                newNodes.push({ id: 'game-catch-donut', isGame: true, gameId: 'catch-donut', title: 'Catch the Donut' });
            } else if (idx === 5) {
                newNodes.push({ id: 'game-traffic-patrol', isGame: true, gameId: 'traffic-patrol', title: 'Traffic Patrol' });
            } else if (idx === 8) {
                newNodes.push({ id: 'game-coin-maze', isGame: true, gameId: 'coin-maze', title: 'Coin Maze' });
            }
        });
        nodes = newNodes;
    }

    while (nodes.length < 18) nodes.push({ id: `ph-${nodes.length}`, title: '???', locked: false });

    return (
        <div className="levels-map-main-container">
            <div className="levels-map-content">
                <IslandWorldMap
                    nodes={nodes}
                    completions={completions}
                    selectedLevel={selectedLevel}
                    onBack={goBack}
                    isUnlocked={isUnlocked}
                    getBadge={getBadge}
                    themeAssets={themeAssets}
                    onPlayGame={(gameId) => setCurrentGame(gameId)}
                />
            </div>
        </div>
    );
}


