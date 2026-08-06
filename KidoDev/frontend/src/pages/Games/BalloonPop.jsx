import React, { useEffect, useRef, useState, useCallback } from 'react';
import './BalloonPop.scss';

// ─── Constants ───────────────────────────────────────────────
const BALLOON_R = 28;
const LEVELS = [
    { label: 'Easy', spawnMs: 1400, speedRange: [0.8, 1.4], time: 60, max: 8 },
    { label: 'Medium', spawnMs: 900, speedRange: [1.4, 2.4], time: 50, max: 12 },
    { label: 'Hard', spawnMs: 500, speedRange: [2.4, 4.0], time: 40, max: 18 },
];

const BALLOON_COLORS = [
    { body: '#FF6B6B', shine: '#FF9E9E', shadow: '#C0392B', label: 'red' },
    { body: '#4DABF7', shine: '#92D0FF', shadow: '#1971C2', label: 'blue' },
    { body: '#69DB7C', shine: '#A5E8B2', shadow: '#2F9E44', label: 'green' },
    { body: '#FFD43B', shine: '#FFE899', shadow: '#E67700', label: 'yellow' },
    { body: '#DA77F2', shine: '#EDB3F8', shadow: '#9C36B5', label: 'purple' },
    { body: '#FF922B', shine: '#FFB871', shadow: '#D9480F', label: 'orange' },
];

const GAME_EVENTS = [
    { id: 'double_points', label: '2× Points!', color: '#FFD43B', duration: 8000 },
    { id: 'speed_mode', label: '⚡ Speed!', color: '#FF6B6B', duration: 6000 },
    { id: 'balloon_storm', label: '🎈 Storm!', color: '#4DABF7', duration: 5000 },
    { id: 'rainbow_mode', label: '🌈 Rainbow!', color: '#DA77F2', duration: 7000 },
];

let _id = 0;
function mkBalloon(speedRange, W, colorOverride) {
    _id++;
    const col = colorOverride || BALLOON_COLORS[Math.floor(Math.random() * BALLOON_COLORS.length)];
    return {
        id: _id,
        x: BALLOON_R + 20 + Math.random() * (W - BALLOON_R * 2 - 40),
        y: window.innerHeight + BALLOON_R,
        vy: -(speedRange[0] + Math.random() * (speedRange[1] - speedRange[0])),
        vx: (Math.random() - 0.5) * 0.8,
        col,
        popping: false,
        popTimer: 0,
        popScale: 1,
        rainbow: false,
        string: Math.random() * 10 - 5,
    };
}

// ─── Audio ───────────────────────────────────────────────────
let _audioCtx = null;
function getAudio() {
    if (!_audioCtx) {
        _audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    }
    if (_audioCtx.state === 'suspended') _audioCtx.resume();
    return _audioCtx;
}
function playPop() {
    try {
        const ctx = getAudio();
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.connect(gain); gain.connect(ctx.destination);
        osc.type = 'triangle';
        osc.frequency.setValueAtTime(600, ctx.currentTime);
        osc.frequency.exponentialRampToValueAtTime(1200, ctx.currentTime + 0.05);
        osc.frequency.exponentialRampToValueAtTime(300, ctx.currentTime + 0.15);
        gain.gain.setValueAtTime(0.4, ctx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.18);
        osc.start(); osc.stop(ctx.currentTime + 0.18);
    } catch { }
}
function playMiss() {
    try {
        const ctx = getAudio();
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.connect(gain); gain.connect(ctx.destination);
        osc.type = 'sawtooth';
        osc.frequency.setValueAtTime(250, ctx.currentTime);
        osc.frequency.exponentialRampToValueAtTime(100, ctx.currentTime + 0.25);
        gain.gain.setValueAtTime(0.25, ctx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.25);
        osc.start(); osc.stop(ctx.currentTime + 0.25);
    } catch { }
}
function playEvent() {
    try {
        const ctx = getAudio();
        [0, 200, 400].forEach((delay, i) => {
            const osc = ctx.createOscillator();
            const gain = ctx.createGain();
            osc.connect(gain); gain.connect(ctx.destination);
            osc.type = 'sine';
            const t = ctx.currentTime + delay / 1000;
            osc.frequency.setValueAtTime([523, 659, 784][i], t);
            gain.gain.setValueAtTime(0.2, t);
            gain.gain.exponentialRampToValueAtTime(0.01, t + 0.3);
            osc.start(t); osc.stop(t + 0.3);
        });
    } catch { }
}

// ─── Drawing ─────────────────────────────────────────────────
function drawBackground(ctx, W, H) {
    // Sky gradient
    const sky = ctx.createLinearGradient(0, 0, 0, H);
    sky.addColorStop(0, '#FFF8E7');
    sky.addColorStop(0.5, '#FFF0D4');
    sky.addColorStop(1, '#FFE4B0');
    ctx.fillStyle = sky;
    ctx.fillRect(0, 0, W, H);

    // Sun
    ctx.save();
    const sunX = W * 0.88, sunY = H * 0.1;
    const sunGlow = ctx.createRadialGradient(sunX, sunY, 0, sunX, sunY, 90);
    sunGlow.addColorStop(0, 'rgba(255,220,80,0.95)');
    sunGlow.addColorStop(0.4, 'rgba(255,190,60,0.5)');
    sunGlow.addColorStop(1, 'rgba(255,190,60,0)');
    ctx.fillStyle = sunGlow;
    ctx.beginPath(); ctx.arc(sunX, sunY, 90, 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = '#FFD43B';
    ctx.beginPath(); ctx.arc(sunX, sunY, 38, 0, Math.PI * 2); ctx.fill();
    ctx.restore();

    // Clouds
    const clouds = [
        { cx: W * 0.12, cy: H * 0.1, r: 38 },
        { cx: W * 0.3, cy: H * 0.07, r: 28 },
        { cx: W * 0.55, cy: H * 0.13, r: 34 },
        { cx: W * 0.72, cy: H * 0.08, r: 30 },
    ];
    clouds.forEach(({ cx, cy, r }) => {
        ctx.save();
        ctx.fillStyle = 'rgba(255,255,255,0.92)';
        ctx.shadowColor = 'rgba(255,200,100,0.3)';
        ctx.shadowBlur = 10;
        [[-r * 0.5, 0, r * 0.9], [0, -r * 0.3, r], [r * 0.5, 0, r * 0.85], [-r * 0.8, r * 0.2, r * 0.6], [r * 0.8, r * 0.2, r * 0.6]].forEach(([dx, dy, rad]) => {
            ctx.beginPath(); ctx.arc(cx + dx, cy + dy, rad, 0, Math.PI * 2); ctx.fill();
        });
        ctx.restore();
    });

    // Ground / grass strip
    const ground = ctx.createLinearGradient(0, H * 0.88, 0, H);
    ground.addColorStop(0, '#7BC67E');
    ground.addColorStop(1, '#4C9A52');
    ctx.fillStyle = ground;
    ctx.fillRect(0, H * 0.88, W, H * 0.12);

    // Grass blades
    ctx.strokeStyle = '#5BB86A';
    ctx.lineWidth = 2.5;
    for (let i = 0; i < W; i += 18) {
        ctx.beginPath();
        ctx.moveTo(i, H * 0.88);
        ctx.quadraticCurveTo(i + 4, H * 0.88 - 10, i + 8, H * 0.88);
        ctx.stroke();
    }

    // Festival banner strings
    ctx.save();
    ctx.strokeStyle = 'rgba(200,140,80,0.35)';
    ctx.lineWidth = 1.5;
    for (let i = 0; i < W; i += W / 5) {
        ctx.beginPath();
        ctx.moveTo(i, 0);
        ctx.quadraticCurveTo(i + W / 10, H * 0.06, i + W / 5, 0);
        ctx.stroke();
        // tiny pennants
        for (let j = 0; j < 5; j++) {
            const px = i + j * (W / 25);
            const py = H * 0.03 * Math.sin(j * 0.8) + H * 0.02;
            ctx.fillStyle = ['#FF6B6B', '#4DABF7', '#FFD43B', '#69DB7C', '#DA77F2'][j % 5];
            ctx.beginPath();
            ctx.moveTo(px, py); ctx.lineTo(px + 8, py + 10); ctx.lineTo(px - 8, py + 10);
            ctx.closePath(); ctx.fill();
        }
    }
    ctx.restore();
}

function drawBalloon(ctx, b, rainbow, multiplier) {
    const { x, y, col, popScale, rainbow: isRainbow } = b;
    const scale = b.popping ? popScale : 1;
    const alpha = b.popping ? Math.max(0, popScale) : 1;

    ctx.save();
    ctx.globalAlpha = alpha;
    ctx.translate(x, y);
    ctx.scale(scale, scale);

    // String
    if (!b.popping) {
        ctx.strokeStyle = 'rgba(100,60,20,0.4)';
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.moveTo(0, BALLOON_R);
        ctx.quadraticCurveTo(b.string, BALLOON_R + 18, b.string * 0.5, BALLOON_R + 30);
        ctx.stroke();
    }

    // Body
    const bodyColor = (isRainbow || rainbow) ? `hsl(${(Date.now() / 10 + b.id * 40) % 360}, 85%, 62%)` : col.body;
    const grad = ctx.createRadialGradient(-BALLOON_R * 0.3, -BALLOON_R * 0.35, 2, 0, 0, BALLOON_R);
    grad.addColorStop(0, (isRainbow || rainbow) ? 'rgba(255,255,255,0.9)' : col.shine);
    grad.addColorStop(0.5, bodyColor);
    grad.addColorStop(1, (isRainbow || rainbow) ? bodyColor : col.shadow);
    ctx.fillStyle = grad;
    ctx.beginPath();
    ctx.arc(0, 0, BALLOON_R, 0, Math.PI * 2);
    ctx.fill();

    // Knot
    ctx.fillStyle = (isRainbow || rainbow) ? bodyColor : col.shadow;
    ctx.beginPath();
    ctx.ellipse(0, BALLOON_R + 2, 4, 5, 0, 0, Math.PI * 2);
    ctx.fill();

    // Shine spot
    ctx.fillStyle = 'rgba(255,255,255,0.55)';
    ctx.beginPath();
    ctx.ellipse(-BALLOON_R * 0.28, -BALLOON_R * 0.3, BALLOON_R * 0.22, BALLOON_R * 0.14, -0.4, 0, Math.PI * 2);
    ctx.fill();

    // Double points star
    if (multiplier > 1 && !b.popping) {
        ctx.fillStyle = '#FFD43B';
        ctx.font = 'bold 13px Nunito, sans-serif';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText('★', 0, 0);
    }

    ctx.restore();
}

function drawPopEffect(ctx, b) {
    if (!b.popping) return;
    const t = 1 - b.popScale; // 0→1 as pop progresses
    if (t < 0.1) return;
    const count = 8;
    for (let i = 0; i < count; i++) {
        const angle = (i / count) * Math.PI * 2;
        const dist = t * 55;
        const px = b.x + Math.cos(angle) * dist;
        const py = b.y + Math.sin(angle) * dist;
        const r = (1 - t) * 6;
        ctx.save();
        ctx.globalAlpha = (1 - t) * 0.9;
        ctx.fillStyle = b.col.body;
        ctx.beginPath();
        ctx.arc(px, py, r, 0, Math.PI * 2);
        ctx.fill();
        ctx.restore();
    }
}

// ─── Component ───────────────────────────────────────────────
export default function BalloonPop({ onBack }) {
    const canvasRef = useRef(null);
    const containerRef = useRef(null);
    const sizeRef = useRef({ W: 800, H: 600 });
    const rafRef = useRef(null);
    const clockRef = useRef(null);
    const lastTsRef = useRef(null);
    const eventTimerRef = useRef(null);

    const s = useRef({
        balloons: [], score: 0, missed: 0, running: false,
        timeLeft: 60, level: 0, multiplier: 1,
        spawnTimer: 0, eventTimer: 15000, rainbow: false,
        currentEvent: null, eventLabel: null, eventColor: null,
    });

    const [ui, setUi] = useState({
        screen: 'menu', score: 0, missed: 0, timeLeft: 60,
        levelIdx: 0, eventLabel: null, eventColor: null,
    });

    // Resize
    useEffect(() => {
        const resize = () => {
            const c = containerRef.current;
            const canvas = canvasRef.current;
            if (!c || !canvas) return;
            const W = c.clientWidth;
            const H = c.clientHeight;
            canvas.width = W; canvas.height = H;
            sizeRef.current = { W, H };
        };
        resize();
        window.addEventListener('resize', resize);
        return () => window.removeEventListener('resize', resize);
    }, []);

    const draw = useCallback(() => {
        const canvas = canvasRef.current; if (!canvas) return;
        const ctx = canvas.getContext('2d');
        const { W, H } = sizeRef.current;
        const st = s.current;

        drawBackground(ctx, W, H);

        // draw balloons (dead first for z-order)
        st.balloons.forEach(b => {
            if (b.popping) {
                drawPopEffect(ctx, b);
                drawBalloon(ctx, b, st.rainbow, st.multiplier);
            }
        });
        st.balloons.forEach(b => {
            if (!b.popping) drawBalloon(ctx, b, st.rainbow, st.multiplier);
        });
    }, []);

    // Trigger event
    const triggerEvent = useCallback(() => {
        const st = s.current;
        const ev = GAME_EVENTS[Math.floor(Math.random() * GAME_EVENTS.length)];
        st.currentEvent = ev.id;
        st.eventLabel = ev.label;
        st.eventColor = ev.color;

        if (ev.id === 'double_points') st.multiplier = 2;
        if (ev.id === 'rainbow_mode') st.rainbow = true;
        if (ev.id === 'balloon_storm') {
            const cfg = LEVELS[st.level];
            const { W } = sizeRef.current;
            for (let i = 0; i < 14; i++) {
                setTimeout(() => {
                    if (st.running) st.balloons.push(mkBalloon(cfg.speedRange, W));
                }, i * 150);
            }
        }

        playEvent();
        setUi(p => ({ ...p, eventLabel: ev.label, eventColor: ev.color }));

        clearTimeout(eventTimerRef.current);
        eventTimerRef.current = setTimeout(() => {
            st.multiplier = 1;
            st.rainbow = false;
            st.currentEvent = null;
            st.eventLabel = null;
            st.eventColor = null;
            setUi(p => ({ ...p, eventLabel: null, eventColor: null }));
        }, ev.duration);
    }, []);

    const loop = useCallback((ts) => {
        if (!s.current.running) return;
        const dt = lastTsRef.current ? ts - lastTsRef.current : 16;
        lastTsRef.current = ts;

        const st = s.current;
        const cfg = LEVELS[st.level];
        const { W, H } = sizeRef.current;

        // Spawn
        st.spawnTimer += dt;
        const active = st.balloons.filter(b => !b.popping).length;
        if (st.spawnTimer >= cfg.spawnMs && active < cfg.max) {
            st.spawnTimer = 0;
            st.balloons.push(mkBalloon(cfg.speedRange, W));
        }

        // Event timer
        st.eventTimer -= dt;
        if (st.eventTimer <= 0 && !st.currentEvent) {
            st.eventTimer = 12000 + Math.random() * 8000;
            triggerEvent();
        }

        // Speed mode modifier
        const speedMult = st.currentEvent === 'speed_mode' ? 1.7 : 1;

        // Move balloons
        st.balloons.forEach(b => {
            if (b.popping) {
                b.popTimer -= dt;
                b.popScale = b.popTimer / 260;
                return;
            }
            b.y += b.vy * speedMult;
            b.x += b.vx;
            // zig-zag subtle
            b.vx = Math.sin(ts / 800 + b.id) * 0.5;

            // Escape at top
            if (b.y + BALLOON_R < -10) {
                b.popping = true;
                b.popTimer = 0;
                st.missed += 1;
                playMiss();
            }
        });

        // Cleanup fully-popped
        st.balloons = st.balloons.filter(b => !(b.popping && b.popTimer <= 0));

        draw();
        setUi(p => ({ ...p, score: st.score, missed: st.missed }));
        rafRef.current = requestAnimationFrame(loop);
    }, [draw, triggerEvent]);

    // Pop a balloon by id
    const popBalloon = useCallback((b) => {
        const st = s.current;
        if (b.popping) return;
        b.popping = true;
        b.popTimer = 260;
        b.popScale = 1;
        st.score += 10 * st.multiplier;
        playPop();
        setUi(p => ({ ...p, score: st.score }));
    }, []);

    // Canvas click → pop
    const onCanvasClick = useCallback((e) => {
        if (!s.current.running) return;
        const canvas = canvasRef.current;
        const rect = canvas.getBoundingClientRect();
        const scaleX = sizeRef.current.W / rect.width;
        const scaleY = sizeRef.current.H / rect.height;
        const cx = (e.clientX - rect.left) * scaleX;
        const cy = (e.clientY - rect.top) * scaleY;

        const st = s.current;
        for (let i = st.balloons.length - 1; i >= 0; i--) {
            const b = st.balloons[i];
            if (b.popping) continue;
            const dx = b.x - cx, dy = b.y - cy;
            if (Math.sqrt(dx * dx + dy * dy) <= BALLOON_R + 6) {
                popBalloon(b);
                break;
            }
        }
    }, [popBalloon]);

    // Canvas touch
    const onCanvasTouch = useCallback((e) => {
        e.preventDefault();
        if (!s.current.running) return;
        const canvas = canvasRef.current;
        const rect = canvas.getBoundingClientRect();
        const scaleX = sizeRef.current.W / rect.width;
        const scaleY = sizeRef.current.H / rect.height;

        Array.from(e.changedTouches).forEach(t => {
            const cx = (t.clientX - rect.left) * scaleX;
            const cy = (t.clientY - rect.top) * scaleY;
            const st = s.current;
            for (let i = st.balloons.length - 1; i >= 0; i--) {
                const b = st.balloons[i];
                if (b.popping) continue;
                const dx = b.x - cx, dy = b.y - cy;
                if (Math.sqrt(dx * dx + dy * dy) <= BALLOON_R + 10) {
                    popBalloon(b); break;
                }
            }
        });
    }, [popBalloon]);

    // Keyboard: Space = pop lowest balloon near center, Arrow keys = pop directionally
    useEffect(() => {
        const onKey = (e) => {
            const st = s.current;
            if (!st.running) return;
            const { W, H } = sizeRef.current;

            if (e.key === ' ' || e.key === 'Enter') {
                e.preventDefault();
                // Pop the balloon closest to screen center
                let best = null, bestDist = Infinity;
                st.balloons.forEach(b => {
                    if (b.popping) return;
                    const dx = b.x - W / 2, dy = b.y - H / 2;
                    const d = Math.sqrt(dx * dx + dy * dy);
                    if (d < bestDist) { bestDist = d; best = b; }
                });
                if (best) popBalloon(best);
            }
            if (e.key === 'ArrowUp') {
                e.preventDefault();
                // Pop topmost visible balloon
                const sorted = st.balloons.filter(b => !b.popping).sort((a, b) => a.y - b.y);
                if (sorted.length) popBalloon(sorted[0]);
            }
            if (e.key === 'ArrowLeft') {
                e.preventDefault();
                const sorted = st.balloons.filter(b => !b.popping).sort((a, b) => a.x - b.x);
                if (sorted.length) popBalloon(sorted[0]);
            }
            if (e.key === 'ArrowRight') {
                e.preventDefault();
                const sorted = st.balloons.filter(b => !b.popping).sort((a, b) => b.x - a.x);
                if (sorted.length) popBalloon(sorted[0]);
            }
            if (e.key === 'ArrowDown') {
                e.preventDefault();
                // Pop bottommost (closest to escaping top soon — lowest y)
                const sorted = st.balloons.filter(b => !b.popping).sort((a, b) => b.y - a.y);
                if (sorted.length) popBalloon(sorted[0]);
            }
        };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
    }, [popBalloon]);

    const startGame = useCallback((lvl) => {
        getAudio();
        _id = 0;
        lastTsRef.current = null;
        clearInterval(clockRef.current);
        clearTimeout(eventTimerRef.current);
        if (rafRef.current) cancelAnimationFrame(rafRef.current);

        const cfg = LEVELS[lvl];
        s.current = {
            balloons: [], score: 0, missed: 0, running: true,
            timeLeft: cfg.time, level: lvl, multiplier: 1,
            spawnTimer: cfg.spawnMs, eventTimer: 12000,
            rainbow: false, currentEvent: null, eventLabel: null, eventColor: null,
        };
        setUi({ screen: 'playing', score: 0, missed: 0, timeLeft: cfg.time, levelIdx: lvl, eventLabel: null, eventColor: null });

        clockRef.current = setInterval(() => {
            s.current.timeLeft -= 1;
            const t = s.current.timeLeft;
            setUi(p => ({ ...p, timeLeft: t }));
            if (t <= 0) {
                s.current.running = false;
                clearInterval(clockRef.current);
                clearTimeout(eventTimerRef.current);
                setUi(p => ({ ...p, screen: 'gameover' }));
            }
        }, 1000);

        rafRef.current = requestAnimationFrame(loop);
    }, [loop]);

    const stop = useCallback(() => {
        s.current.running = false;
        if (rafRef.current) cancelAnimationFrame(rafRef.current);
        clearInterval(clockRef.current);
        clearTimeout(eventTimerRef.current);
    }, []);

    useEffect(() => () => stop(), [stop]);

    // Draw static scene on non-playing screens
    useEffect(() => {
        if (ui.screen !== 'playing') {
            const canvas = canvasRef.current; if (!canvas) return;
            const { W, H } = sizeRef.current;
            const ctx = canvas.getContext('2d');
            drawBackground(ctx, W, H);
        }
    }, [ui.screen]);

    return (
        <div className="bp-fullpage" ref={containerRef}>
            {/* Floating HUD */}
            <div className="bp-floating-hud">
                {onBack && (
                    <button className="bp-back" onClick={onBack} type="button" aria-label="Back">
                        ←
                    </button>
                )}
                <h1 className="bp-title">🎈 Balloon Pop Festival</h1>

                {ui.screen === 'playing' && (
                    <div className="bp-hud">
                        <div className="hud-pill hud-score">
                            <span className="hud-icon">🏆</span>
                            <strong>{ui.score}</strong>
                        </div>
                        <div className={`hud-pill hud-time${ui.timeLeft <= 10 ? ' hud-time--danger' : ''}`}>
                            <span className="hud-icon">⏱</span>
                            <strong>{ui.timeLeft}s</strong>
                        </div>
                        <div className="hud-pill hud-miss">
                            <span className="hud-icon">💨</span>
                            <strong>{ui.missed}</strong>
                        </div>
                    </div>
                )}
            </div>

            {/* Event Banner */}
            {ui.eventLabel && ui.screen === 'playing' && (
                <div className="bp-event-banner" style={{ '--ev-color': ui.eventColor }}>
                    {ui.eventLabel}
                </div>
            )}

            {/* Canvas */}
            <canvas
                ref={canvasRef}
                className="bp-canvas"
                onClick={onCanvasClick}
                onTouchStart={onCanvasTouch}
                style={{ cursor: s.current.running ? 'crosshair' : 'default' }}
            />

            {/* Menu Overlay */}
            {ui.screen === 'menu' && (
                <div className="bp-overlay">
                    <div className="bp-panel">
                        <div className="bp-panel-emoji">🎈</div>
                        <h2 className="bp-panel-title">Balloon Pop Festival</h2>
                        <p className="bp-panel-desc">
                            Colorful balloons are floating up! <strong>Click</strong> them or use your <strong>keyboard</strong> to pop as many as you can before time runs out!
                        </p>

                        <div className="bp-controls-hint">
                            <div className="hint-row"><kbd>Click / Tap</kbd><span>Pop a balloon</span></div>
                            <div className="hint-row"><kbd>Space / Enter</kbd><span>Pop nearest balloon</span></div>
                            <div className="hint-row"><kbd>↑</kbd><span>Pop highest balloon</span></div>
                            <div className="hint-row"><kbd>← →</kbd><span>Pop left/right balloon</span></div>
                        </div>

                        <p className="bp-choose-label">Choose Difficulty</p>
                        <div className="bp-lvl-row">
                            {LEVELS.map((lv, i) => (
                                <button key={i} className={`bp-lvl-btn bp-lvl-${lv.label.toLowerCase()}`}
                                    onClick={() => startGame(i)} type="button">
                                    <span className="lvl-name">{lv.label}</span>
                                    <span className="lvl-sub">{lv.time}s</span>
                                </button>
                            ))}
                        </div>
                    </div>
                </div>
            )}

            {/* Game Over Overlay */}
            {ui.screen === 'gameover' && (
                <div className="bp-overlay">
                    <div className="bp-panel bp-panel--result">
                        <div className="bp-panel-emoji">
                            {ui.score >= 200 ? '🥇' : ui.score >= 100 ? '🥈' : '🥉'}
                        </div>
                        <h2 className="bp-panel-title">
                            {ui.score >= 200 ? 'Festival Champion!' : ui.score >= 100 ? 'Great Popper!' : 'Keep Practising!'}
                        </h2>
                        <div className="result-grid">
                            <div className="result-cell">
                                <span className="rc-label">Score</span>
                                <span className="rc-val">{ui.score}</span>
                            </div>
                            <div className="result-cell">
                                <span className="rc-label">Escaped</span>
                                <span className="rc-val">{ui.missed}</span>
                            </div>
                            <div className="result-cell">
                                <span className="rc-label">Level</span>
                                <span className="rc-val">{LEVELS[ui.levelIdx].label}</span>
                            </div>
                        </div>
                        <div className="bp-lvl-row">
                            <button className="bp-lvl-btn bp-lvl-easy" onClick={() => startGame(ui.levelIdx)} type="button">
                                <span className="lvl-name">Play Again</span>
                            </button>
                            <button className="bp-lvl-btn bp-lvl-medium" onClick={() => setUi(p => ({ ...p, screen: 'menu' }))} type="button">
                                <span className="lvl-name">Menu</span>
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {/* Legend */}
            <div className="bp-legend">
                {[['Click / Tap', 'Pop balloon'], ['Space', 'Pop nearest'], ['↑ ↓ ← →', 'Pop by direction']].map(([k, v]) => (
                    <div key={k} className="lg-item"><kbd>{k}</kbd><span>{v}</span></div>
                ))}
            </div>
        </div>
    );
}