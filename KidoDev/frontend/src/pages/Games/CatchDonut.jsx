import React, { useEffect, useRef, useState, useCallback } from 'react';
import { FaArrowLeft, FaTrophy, FaClock, FaTimesCircle } from 'react-icons/fa';
import spriteLogo from '../../assets/no_bg_output/sprite-logo_nobg.webp';
import { useAudio } from './AudioProvider';
import './CatchDonut.scss';

const DONUT_R = 26;
const CAT_W = 100;
const CAT_H = 100;
const SPAWN_MS = 1800;
const LEVELS = [
    { label: 'Easy', max: 3, speed: [0.5, 0.9], time: 60 },
    { label: 'Medium', max: 5, speed: [1.0, 1.8], time: 50 },
    { label: 'Hard', max: 7, speed: [1.9, 3.0], time: 40 },
];

let _id = 0;
function mkDonut(speedRange, W) {
    _id++;
    return {
        id: _id,
        x: DONUT_R + 30 + Math.random() * (W - DONUT_R * 2 - 60),
        y: -DONUT_R,
        vy: speedRange[0] + Math.random() * (speedRange[1] - speedRange[0]),
        caught: false, missed: false, catching: false, catchTimer: 0,
    };
}

// ✅ Lazy audioCtx — only created after a user gesture, never at module load
let audioCtx = null;
function getAudioCtx() {
    if (!audioCtx) {
        const AC = window.AudioContext || window.webkitAudioContext;
        audioCtx = new AC();
    }
    if (audioCtx.state === 'suspended') audioCtx.resume();
    return audioCtx;
}

function playCatchSound() {
    const ctx = getAudioCtx();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.type = 'sine';
    osc.frequency.setValueAtTime(800, ctx.currentTime);
    osc.frequency.exponentialRampToValueAtTime(1400, ctx.currentTime + 0.1);
    gain.gain.setValueAtTime(0, ctx.currentTime);
    gain.gain.linearRampToValueAtTime(0.3, ctx.currentTime + 0.05);
    gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.2);
    osc.start();
    osc.stop(ctx.currentTime + 0.2);
}

function playMissSound() {
    const ctx = getAudioCtx();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.type = 'triangle';
    osc.frequency.setValueAtTime(300, ctx.currentTime);
    osc.frequency.exponentialRampToValueAtTime(150, ctx.currentTime + 0.3);
    gain.gain.setValueAtTime(0, ctx.currentTime);
    gain.gain.linearRampToValueAtTime(0.3, ctx.currentTime + 0.05);
    gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.3);
    osc.start();
    osc.stop(ctx.currentTime + 0.3);
}

function drawDonut(ctx, x, y, r, label, scale = 1) {
    ctx.save();
    ctx.translate(x, y);
    ctx.scale(scale, scale);
    ctx.beginPath();
    ctx.arc(0, 0, r, 0, Math.PI * 2);
    ctx.fillStyle = '#C8892A';
    ctx.fill();
    ctx.beginPath();
    ctx.arc(0, 0, r - 3, 0, Math.PI * 2);
    const g = ctx.createRadialGradient(-r * 0.2, -r * 0.2, 0, 0, 0, r - 3);
    g.addColorStop(0, '#FFD97D');
    g.addColorStop(0.5, '#F4A035');
    g.addColorStop(1, '#D4781A');
    ctx.fillStyle = g;
    ctx.fill();
    [{ a: 0, c: '#FF6B9D' }, { a: 60, c: '#4DABF7' }, { a: 120, c: '#6BCB77' },
    { a: 180, c: '#FF6B9D' }, { a: 240, c: '#FFD93D' }, { a: 300, c: '#4DABF7' }].forEach(s => {
        const rad = (s.a * Math.PI) / 180;
        ctx.save();
        ctx.translate(Math.cos(rad) * r * 0.55, Math.sin(rad) * r * 0.55);
        ctx.rotate(rad + 0.5);
        ctx.fillStyle = s.c;
        ctx.beginPath();
        ctx.roundRect(-4.5, -1.8, 9, 3.5, 1.8);
        ctx.fill();
        ctx.restore();
    });
    ctx.save();
    ctx.globalCompositeOperation = 'destination-out';
    ctx.beginPath();
    ctx.arc(0, 0, r * 0.35, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
    if (scale === 1) {
        ctx.font = 'bold 11px Inter, sans-serif';
        const tw = ctx.measureText(label).width + 14;
        ctx.fillStyle = 'rgba(30,30,60,0.85)';
        ctx.beginPath();
        ctx.roundRect(-tw / 2, -r - 24, tw, 18, 5);
        ctx.fill();
        ctx.fillStyle = '#fff';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(label, 0, -r - 15);
    }
    ctx.restore();
}

function drawCat(ctx, cx, floorY, mouthOpen, img) {
    const by = floorY - CAT_H + 10;
    ctx.save();
    ctx.translate(cx, by);
    ctx.save();
    ctx.globalAlpha = 0.15;
    ctx.fillStyle = '#000';
    ctx.beginPath();
    ctx.ellipse(0, CAT_H, CAT_W * 0.45, 7, 0, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
    if (img && img.complete && img.naturalWidth > 0) {
        const scaleY = mouthOpen ? 0.96 : 1;
        ctx.save();
        ctx.scale(1, scaleY);
        ctx.drawImage(img, -CAT_W / 2, mouthOpen ? CAT_H * 0.04 : 0, CAT_W, CAT_H);
        if (mouthOpen) {
            const mx = 12, my = 48;
            ctx.strokeStyle = '#7A3A10';
            ctx.lineWidth = 1.5;
            ctx.lineCap = 'round';
            ctx.fillStyle = '#C0392B';
            ctx.beginPath();
            ctx.ellipse(mx, my, 12, 10, 0, 0, Math.PI * 2);
            ctx.fill();
            ctx.stroke();
            ctx.fillStyle = '#FF6B9D';
            ctx.beginPath();
            ctx.ellipse(mx, my + 4, 8, 6, 0, 0, Math.PI * 2);
            ctx.fill();
            ctx.fillStyle = '#FFF';
            ctx.beginPath();
            ctx.roundRect(mx - 8, my - 9, 16, 5, 2);
            ctx.fill();
        }
        ctx.restore();
    } else {
        ctx.fillStyle = '#E8843A';
        ctx.beginPath();
        ctx.roundRect(-CAT_W / 2, 0, CAT_W, CAT_H, 10);
        ctx.fill();
    }
    const pawG = ctx.createLinearGradient(-CAT_W / 2 - 12, 0, CAT_W / 2 + 12, 0);
    pawG.addColorStop(0, '#F4A84E');
    pawG.addColorStop(0.5, '#FDE7B5');
    pawG.addColorStop(1, '#F4A84E');
    ctx.fillStyle = pawG;
    ctx.strokeStyle = 'rgba(180,90,20,0.4)';
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.roundRect(-CAT_W / 2 - 12, CAT_H - 12, CAT_W + 24, 16, 8);
    ctx.fill();
    ctx.stroke();
    ctx.restore();
}

function drawBg(ctx, W, H, floorY) {
    const sky = ctx.createLinearGradient(0, 0, 0, H);
    sky.addColorStop(0, '#C8E8FA');
    sky.addColorStop(0.55, '#D8EFFA');
    sky.addColorStop(1, '#BDD8F0');
    ctx.fillStyle = sky;
    ctx.fillRect(0, 0, W, H);
    [[W * 0.10, H * 0.12], [W * 0.35, H * 0.08], [W * 0.62, H * 0.14], [W * 0.85, H * 0.09]].forEach(([cx, cy]) => {
        ctx.fillStyle = 'rgba(255,255,255,0.88)';
        ctx.beginPath(); ctx.ellipse(cx, cy, 52, 26, 0, 0, Math.PI * 2); ctx.fill();
        ctx.beginPath(); ctx.ellipse(cx + 36, cy + 6, 36, 20, 0, 0, Math.PI * 2); ctx.fill();
        ctx.beginPath(); ctx.ellipse(cx - 30, cy + 9, 32, 18, 0, 0, Math.PI * 2); ctx.fill();
    });
    const gG = ctx.createLinearGradient(0, floorY, 0, H);
    gG.addColorStop(0, '#81C784');
    gG.addColorStop(1, '#388E3C');
    ctx.fillStyle = gG;
    ctx.fillRect(0, floorY, W, H - floorY);
    ctx.strokeStyle = 'rgba(56,142,60,0.5)';
    ctx.lineWidth = 2;
    ctx.beginPath(); ctx.moveTo(0, floorY); ctx.lineTo(W, floorY); ctx.stroke();
    ctx.strokeStyle = '#4CAF50';
    ctx.lineWidth = 2;
    for (let i = 0; i < W; i += 28) {
        ctx.beginPath();
        ctx.moveTo(i, floorY);
        ctx.quadraticCurveTo(i + 4, floorY - 8, i + 8, floorY);
        ctx.stroke();
    }
}

export default function CatchDonut({ onBack }) {
    const canvasRef = useRef(null);
    const containerRef = useRef(null);
    const sizeRef = useRef({ W: 1200, H: 650, floorY: 580 });
    const spriteImgRef = useRef(new Image());
    const { play } = useAudio(); // ✅ pull bg music play from context

    const s = useRef({
        donuts: [], catX: 600, score: 0, missed: 0,
        running: false, timeLeft: 60, level: 0,
        inputMode: null, inputBuffer: '',
        mouthOpenTimer: 0, spawnTimer: 0,
    });
    const [ui, setUi] = useState({
        screen: 'menu', score: 0, missed: 0, timeLeft: 60,
        levelIdx: 0, inputMode: null, inputBuffer: '',
    });
    const rafRef = useRef(null);
    const clockRef = useRef(null);
    const lastTsRef = useRef(null);

    useEffect(() => {
        spriteImgRef.current.src = spriteLogo;
    }, []);

    useEffect(() => {
        const resize = () => {
            const c = containerRef.current;
            const canvas = canvasRef.current;
            if (!c || !canvas) return;
            const W = c.clientWidth;
            const H = c.clientHeight;
            canvas.width = W;
            canvas.height = H;
            const floorY = H - Math.round(H * 0.1);
            sizeRef.current = { W, H, floorY };
            s.current.catX = W / 2;
            const ctx = canvas.getContext('2d');
            drawBg(ctx, W, H, floorY);
            drawCat(ctx, W / 2, floorY, false, spriteImgRef.current);
        };
        resize();
        window.addEventListener('resize', resize);
        return () => window.removeEventListener('resize', resize);
    }, []);

    const draw = useCallback(() => {
        const canvas = canvasRef.current;
        if (!canvas) return;
        const ctx = canvas.getContext('2d');
        const { W, H, floorY } = sizeRef.current;
        const st = s.current;
        drawBg(ctx, W, H, floorY);
        st.donuts.forEach(d => {
            if (d.caught || d.missed) return;
            const scale = d.catching ? Math.max(0, d.catchTimer / 200) : 1;
            drawDonut(ctx, d.x, d.y, DONUT_R, `(${Math.round(d.x)}, ${Math.round(d.y)})`, scale);
        });
        drawCat(ctx, st.catX, floorY, st.mouthOpenTimer > 0, spriteImgRef.current);
        if (st.inputMode) {
            ctx.fillStyle = 'rgba(30,50,100,0.80)';
            const bw = Math.min(420, W * 0.5);
            ctx.beginPath();
            ctx.roundRect(W / 2 - bw / 2, H - 60, bw, 44, 10);
            ctx.fill();
            ctx.font = `bold ${Math.round(H * 0.022)}px Inter, sans-serif`;
            ctx.fillStyle = '#FFD93D';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.fillText(`Enter ${st.inputMode}-coordinate: ${st.inputBuffer || '_'}  [Enter = confirm]`, W / 2, H - 38);
        }
    }, []);

    const loop = useCallback((ts) => {
        if (!s.current.running) return;
        const dt = lastTsRef.current ? ts - lastTsRef.current : 16;
        lastTsRef.current = ts;
        const st = s.current;
        const cfg = LEVELS[st.level];
        const { W, floorY } = sizeRef.current;
        st.spawnTimer += dt;
        if (st.spawnTimer >= SPAWN_MS && st.donuts.filter(d => !d.caught && !d.missed).length < cfg.max) {
            st.spawnTimer = 0;
            st.donuts.push(mkDonut(cfg.speed, W));
        }
        const catchY = floorY - CAT_H + 30;
        st.donuts.forEach(d => {
            if (d.caught || d.missed) return;
            if (d.catching) {
                d.catchTimer -= dt;
                const mouthX = st.catX + 12;
                const mouthY = floorY - CAT_H + 58;
                d.x += (mouthX - d.x) * 0.35;
                d.y += (mouthY - d.y) * 0.35;
                if (d.catchTimer <= 0) d.caught = true;
                return;
            }
            d.y += d.vy;
            if (d.y + DONUT_R >= catchY && d.y - DONUT_R <= catchY + 60 &&
                d.x >= st.catX - CAT_W / 2 - 15 && d.x <= st.catX + CAT_W / 2 + 15) {
                d.catching = true;
                d.catchTimer = 200;
                st.score += 10;
                st.mouthOpenTimer = 500;
                playCatchSound();
            }
            if (d.y - DONUT_R > floorY + 10 && !d.caught && !d.catching) {
                d.missed = true;
                st.missed += 1;
                playMissSound();
            }
        });
        st.donuts = st.donuts.filter(d => !d.caught && !d.missed);
        if (st.mouthOpenTimer > 0) st.mouthOpenTimer -= dt;
        setUi(prev => ({ ...prev, score: st.score, missed: st.missed, inputMode: st.inputMode, inputBuffer: st.inputBuffer }));
        draw();
        rafRef.current = requestAnimationFrame(loop);
    }, [draw]);

    // Only this function changes — rest of CatchDonut stays identical
    const startGame = useCallback((lvl) => {
        play();          // ✅ starts here — difficulty button IS the user gesture
        getAudioCtx();   // warm up Web Audio for sound effects

        _id = 0;
        lastTsRef.current = null;
        const cfg = LEVELS[lvl];
        const { W } = sizeRef.current;
        s.current = {
            donuts: [], catX: W / 2, score: 0, missed: 0, running: true,
            timeLeft: cfg.time, level: lvl, inputMode: null, inputBuffer: '',
            mouthOpenTimer: 0, spawnTimer: SPAWN_MS,
        };
        setUi({ screen: 'playing', score: 0, missed: 0, timeLeft: cfg.time, levelIdx: lvl, inputMode: null, inputBuffer: '' });
        if (clockRef.current) clearInterval(clockRef.current);
        clockRef.current = setInterval(async () => {
            s.current.timeLeft -= 1;
            const t = s.current.timeLeft;
            setUi(p => ({ ...p, timeLeft: t }));
            if (t <= 0) {
                s.current.running = false;
                clearInterval(clockRef.current);
                setUi(p => ({ ...p, screen: 'gameover' }));
                try {
                    const childId = localStorage.getItem('kido_child_id');
                    if (childId && s.current.score > 0) {
                        const { supabase } = await import('../../utils/supabaseClient');
                        await supabase.from('lesson_completions').upsert({
                            child_id: childId,
                            lesson_id: 'catch-donut',
                            score: s.current.score,
                            xp_earned: s.current.score,
                            badge: 'Donut Catcher'
                        }, { onConflict: 'child_id,lesson_id' });
                    }
                } catch (e) {
                    console.error('Failed to save score:', e);
                }
            }
        }, 1000);
        rafRef.current = requestAnimationFrame(loop);
    }, [loop, play]);
    
    const stop = useCallback(() => {
        s.current.running = false;
        if (rafRef.current) cancelAnimationFrame(rafRef.current);
        if (clockRef.current) clearInterval(clockRef.current);
    }, []);

    useEffect(() => () => stop(), [stop]);

    useEffect(() => {
        if (ui.screen !== 'playing') {
            const canvas = canvasRef.current;
            if (!canvas) return;
            const { W, H, floorY } = sizeRef.current;
            const ctx = canvas.getContext('2d');
            drawBg(ctx, W, H, floorY);
            drawCat(ctx, W / 2, floorY, false);
        }
    }, [ui.screen]);

    useEffect(() => {
        const onKey = (e) => {
            const st = s.current;
            if (!st.running) return;
            const k = e.key.toUpperCase();
            if ((k === 'X' || k === 'Y') && !st.inputMode) {
                e.preventDefault();
                st.inputMode = k; st.inputBuffer = '';
                setUi(p => ({ ...p, inputMode: k, inputBuffer: '' }));
                return;
            }
            if (st.inputMode) {
                if (/^\d$/.test(e.key)) { st.inputBuffer += e.key; setUi(p => ({ ...p, inputBuffer: st.inputBuffer })); return; }
                if (e.key === 'Backspace') { st.inputBuffer = st.inputBuffer.slice(0, -1); setUi(p => ({ ...p, inputBuffer: st.inputBuffer })); return; }
                if (e.key === 'Escape') { st.inputMode = null; st.inputBuffer = ''; setUi(p => ({ ...p, inputMode: null, inputBuffer: '' })); return; }
                if (e.key === 'Enter' && st.inputBuffer) {
                    const v = parseInt(st.inputBuffer, 10);
                    const { W } = sizeRef.current;
                    if (st.inputMode === 'X') st.catX = Math.max(CAT_W / 2 + 12, Math.min(W - CAT_W / 2 - 12, v));
                    st.inputMode = null; st.inputBuffer = '';
                    setUi(p => ({ ...p, inputMode: null, inputBuffer: '' }));
                    return;
                }
                return;
            }
            const { W } = sizeRef.current;
            const step = Math.round(W * 0.018);
            if (e.key === 'ArrowLeft') st.catX = Math.max(CAT_W / 2 + 12, st.catX - step);
            if (e.key === 'ArrowRight') st.catX = Math.min(W - CAT_W / 2 - 12, st.catX + step);
        };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
    }, []);

    const onMouseMove = useCallback((e) => {
        const st = s.current;
        if (!st.running || st.inputMode) return;
        const r = canvasRef.current.getBoundingClientRect();
        const { W } = sizeRef.current;
        const raw = (e.clientX - r.left) * (W / r.width);
        st.catX = Math.max(CAT_W / 2 + 12, Math.min(W - CAT_W / 2 - 12, raw));
    }, []);

    const onTouch = useCallback((e) => {
        const st = s.current;
        if (!st.running || st.inputMode) return;
        const r = canvasRef.current.getBoundingClientRect();
        const { W } = sizeRef.current;
        const raw = (e.touches[0].clientX - r.left) * (W / r.width);
        st.catX = Math.max(CAT_W / 2 + 12, Math.min(W - CAT_W / 2 - 12, raw));
    }, []);

    return (
        <div className="cdg-fullpage" ref={containerRef}>
            <div className="cdg-floating-hud">
                <button className="cdg-back" onClick={onBack} type="button" aria-label="Back">
                    <FaArrowLeft />
                </button>
                <h1 className="cdg-title">Catch the Falling Donut</h1>
                {ui.screen === 'playing' && (
                    <div className="cdg-hud">
                        <div className="hud-pill hud-pill-score">
                            <FaTrophy style={{ color: '#fff' }} />
                            <strong>{ui.score}</strong>
                        </div>
                        <div className="hud-pill" style={ui.timeLeft <= 10 ? { background: 'linear-gradient(180deg, #FF6B6B 0%, #E03131 100%)', borderColor: '#FFE3E3', boxShadow: '0 4px 0 #C92A2A, 0 6px 10px rgba(0,0,0,0.25)' } : {}}>
                            <FaClock />
                            <strong>{ui.timeLeft}s</strong>
                        </div>
                        <div className="hud-pill hud-pill-miss">
                            <FaTimesCircle />
                            <strong>{ui.missed}</strong>
                        </div>
                    </div>
                )}
            </div>

            <canvas
                ref={canvasRef}
                className="cdg-canvas-fullpage"
                onMouseMove={onMouseMove}
                onTouchMove={onTouch}
            />

            {ui.screen === 'menu' && (
                <div className="cdg-overlay">
                    <div className="cdg-panel" style={{ position: 'relative' }}>
                        <button
                            onClick={onBack}
                            style={{
                                position: 'absolute',
                                top: '16px',
                                right: '20px',
                                background: 'transparent',
                                border: 'none',
                                color: '#888',
                                fontSize: '28px',
                                fontWeight: 'bold',
                                cursor: 'pointer',
                                transition: 'color 0.2s',
                                padding: '4px 8px',
                                lineHeight: '1',
                            }}
                            onMouseEnter={(e) => e.target.style.color = '#ff6b6b'}
                            onMouseLeave={(e) => e.target.style.color = '#888'}
                            title="Close"
                        >
                            &times;
                        </button>
                        <h2 className="cdg-panel-title" style={{ fontSize: '1.6rem', marginBottom: '8px' }}>Catch the Falling Donut</h2>
                        <p className="cdg-panel-desc" style={{ fontSize: '0.85rem', marginBottom: '14px', lineHeight: '1.5' }}>
                            Donuts fall from the sky with live coordinates. Move the cat using your mouse, arrows, or type coordinates to catch them!
                        </p>
                        <p className="cdg-choose-label" style={{ fontSize: '0.7rem', marginBottom: '8px' }}>Choose Difficulty</p>
                        <div className="cdg-lvl-row">
                            {LEVELS.map((lv, i) => (
                                <button key={i} className={`cdg-lvl-btn cdg-lvl-${lv.label.toLowerCase()}`}
                                    onClick={() => startGame(i)} type="button" style={{ padding: '8px 18px' }}>
                                    <span className="lvl-name" style={{ fontSize: '0.95rem' }}>{lv.label}</span>
                                    <span className="lvl-sub" style={{ fontSize: '0.75rem' }}>{lv.time}s &middot; max {lv.max}</span>
                                </button>
                            ))}
                        </div>
                    </div>
                </div>
            )}

            {ui.screen === 'gameover' && (
                <div className="cdg-overlay">
                    <div className="cdg-panel cdg-panel--result">
                        <h2 className="cdg-panel-title">
                            {ui.score >= 100 ? 'Outstanding!' : ui.score >= 50 ? 'Well Done!' : 'Keep Practising!'}
                        </h2>
                        <div className="result-grid">
                            <div className="result-cell"><span className="rc-label">Score</span><span className="rc-val">{ui.score}</span></div>
                            <div className="result-cell"><span className="rc-label">Missed</span><span className="rc-val">{ui.missed}</span></div>
                            <div className="result-cell"><span className="rc-label">Level</span><span className="rc-val">{LEVELS[ui.levelIdx].label}</span></div>
                        </div>
                        <div className="cdg-lvl-row">
                            <button className="cdg-lvl-btn cdg-lvl-easy" onClick={() => startGame(ui.levelIdx)} type="button">
                                <span className="lvl-name">Play Again</span>
                            </button>
                            <button className="cdg-lvl-btn cdg-lvl-medium" onClick={() => setUi(p => ({ ...p, screen: 'menu' }))} type="button">
                                <span className="lvl-name">Menu</span>
                            </button>
                        </div>
                    </div>
                </div>
            )}

            <div className="cdg-legend">
                {[['Mouse / Arrows', 'Move cat'], ['X key', 'Type X-coord'], ['Y key', 'Predict arrival'], ['Enter', 'Confirm'], ['Esc', 'Cancel']].map(([k, v]) => (
                    <div key={k} className="lg-item"><kbd>{k}</kbd><span>{v}</span></div>
                ))}
            </div>
        </div>
    );
}