import React, { useEffect, useRef, useState, useCallback } from 'react';

// ─────────────────────────────────────────────────────────────
// CONSTANTS
// ─────────────────────────────────────────────────────────────
const STOP_LINE_X_RATIO = 0.78;
const LIGHT_X_RATIO = 0.83;
const CAR_W = 70;
const CAR_H = 32;
const ROAD_LANES = 3;

const LEVELS = [
    { label: 'Easy', carsAtOnce: 1, spawnInterval: 3000, carSpeed: 85, penaltyRed: -10, penaltyMiss: -6, rewardStop: 10, rewardGo: 8, time: 60 },
    { label: 'Medium', carsAtOnce: 2, spawnInterval: 2000, carSpeed: 120, penaltyRed: -12, penaltyMiss: -8, rewardStop: 12, rewardGo: 8, time: 55 },
    { label: 'Hard', carsAtOnce: 3, spawnInterval: 1300, carSpeed: 160, penaltyRed: -18, penaltyMiss: -10, rewardStop: 15, rewardGo: 10, time: 50 },
];

const CAR_PALETTE = [
    { body: '#E53935', roof: '#B71C1C', glass: '#90CAF9' },
    { body: '#1E88E5', roof: '#0D47A1', glass: '#E3F2FD' },
    { body: '#F4A035', roof: '#C77800', glass: '#FFF8E1' },
    { body: '#8E24AA', roof: '#6A0080', glass: '#E1BEE7' },
    { body: '#00ACC1', roof: '#006064', glass: '#E0F7FA' },
    { body: '#43A047', roof: '#1B5E20', glass: '#C8E6C9' },
];

function laneYs(roadTop, roadH) {
    const laneH = roadH / ROAD_LANES;
    return Array.from({ length: ROAD_LANES }, (_, i) => roadTop + laneH * i + laneH / 2);
}

// ─────────────────────────────────────────────────────────────
// AUDIO
// ─────────────────────────────────────────────────────────────
let audioCtx = null;
function getAC() {
    if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    if (audioCtx.state === 'suspended') audioCtx.resume();
    return audioCtx;
}
function playTone(f1, f2, dur, type = 'sine', vol = 0.2) {
    try {
        const ac = getAC();
        const osc = ac.createOscillator();
        const g = ac.createGain();
        osc.connect(g); g.connect(ac.destination);
        osc.type = type;
        osc.frequency.setValueAtTime(f1, ac.currentTime);
        osc.frequency.exponentialRampToValueAtTime(f2, ac.currentTime + dur);
        g.gain.setValueAtTime(0, ac.currentTime);
        g.gain.linearRampToValueAtTime(vol, ac.currentTime + 0.02);
        g.gain.exponentialRampToValueAtTime(0.001, ac.currentTime + dur);
        osc.start(); osc.stop(ac.currentTime + dur);
    } catch (_) { }
}
const sfx = {
    green: () => playTone(440, 880, 0.15),
    red: () => playTone(320, 160, 0.22, 'triangle'),
    good: () => playTone(600, 900, 0.14),
    bad: () => playTone(220, 110, 0.3, 'sawtooth'),
    stop: () => playTone(300, 300, 0.12, 'square', 0.15),
    go: () => playTone(500, 700, 0.12, 'square', 0.15),
};

// ─────────────────────────────────────────────────────────────
// CAR FACTORY
// ─────────────────────────────────────────────────────────────
let carIdSeq = 0;
function makeCar(lane, laneY, speed) {
    return {
        id: carIdSeq++, lane,
        x: -CAR_W - 10, y: laneY,
        pal: CAR_PALETTE[Math.floor(Math.random() * CAR_PALETTE.length)],
        speed, currentSpeed: speed, targetSpeed: speed,
        redRunScored: false,
        stopScored: false,
        goScored: false,
        popTimer: 0, popLabel: '', popColor: '#4ADE80',
        waitGreenMs: 0,
    };
}

// ─────────────────────────────────────────────────────────────
// DRAW HELPERS
// ─────────────────────────────────────────────────────────────
function drawBackground(ctx, W, H, roadTop, roadBot) {
    const sky = ctx.createLinearGradient(0, 0, 0, roadTop);
    sky.addColorStop(0, '#87CEEB'); sky.addColorStop(1, '#B8EDB0');
    ctx.fillStyle = sky; ctx.fillRect(0, 0, W, roadTop);
    ctx.fillStyle = '#59B95A'; ctx.fillRect(0, roadBot, W, H - roadBot);
    ctx.fillStyle = '#4e4e4e'; ctx.fillRect(0, roadTop, W, roadBot - roadTop);
    const laneH = (roadBot - roadTop) / ROAD_LANES;
    ctx.strokeStyle = 'rgba(255,255,255,0.4)'; ctx.lineWidth = 2; ctx.setLineDash([28, 20]);
    for (let i = 1; i < ROAD_LANES; i++) {
        const ly = roadTop + laneH * i;
        ctx.beginPath(); ctx.moveTo(0, ly); ctx.lineTo(W, ly); ctx.stroke();
    }
    ctx.setLineDash([]);
}

function drawStopLine(ctx, stopX, roadTop, roadBot) {
    ctx.fillStyle = 'rgba(255,255,255,0.85)';
    for (let y = roadTop + 8; y < roadBot; y += 18) ctx.fillRect(stopX - 8, y, 16, 10);
    ctx.strokeStyle = '#fff'; ctx.lineWidth = 4;
    ctx.beginPath(); ctx.moveTo(stopX, roadTop); ctx.lineTo(stopX, roadBot); ctx.stroke();
}

function drawTrafficLight(ctx, lx, roadTop, isGreen) {
    const boxW = 30, boxH = 80, bx = lx - boxW / 2, by = roadTop - boxH - 22;
    ctx.fillStyle = '#222';
    ctx.beginPath(); ctx.roundRect(bx, by, boxW, boxH, 8); ctx.fill();
    [['#FF1744', !isGreen], ['#FFC107', false], ['#00E676', isGreen]].forEach(([color, on], idx) => {
        const cy = by + 15 + idx * 25;
        ctx.fillStyle = on ? color : `${color}28`;
        ctx.beginPath(); ctx.arc(lx, cy, 9, 0, Math.PI * 2); ctx.fill();
    });
    const glowColor = isGreen ? '#00E676' : '#FF1744';
    const glowY = isGreen ? by + 65 : by + 15;
    ctx.shadowColor = glowColor; ctx.shadowBlur = 18;
    ctx.fillStyle = glowColor;
    ctx.beginPath(); ctx.arc(lx, glowY, 9, 0, Math.PI * 2); ctx.fill();
    ctx.shadowBlur = 0;
}

function drawCar(ctx, car, allStopped) {
    const { x, y, pal, popTimer, popLabel, popColor } = car;
    ctx.save(); ctx.translate(x, y);

    ctx.fillStyle = 'rgba(0,0,0,0.13)';
    ctx.beginPath(); ctx.ellipse(4, CAR_H * 0.55, CAR_W * 0.42, 6, 0, 0, Math.PI * 2); ctx.fill();

    ctx.fillStyle = allStopped ? '#FFD54F' : pal.body;
    ctx.beginPath(); ctx.roundRect(-CAR_W / 2, -CAR_H / 2, CAR_W, CAR_H, 7); ctx.fill();

    ctx.fillStyle = allStopped ? '#F9A825' : pal.roof;
    ctx.beginPath(); ctx.roundRect(-CAR_W * 0.26, -CAR_H / 2 - 15, CAR_W * 0.52, 19, 5); ctx.fill();

    ctx.fillStyle = pal.glass;
    ctx.beginPath(); ctx.roundRect(-13, -CAR_H / 2 - 12, 27, 13, 3); ctx.fill();

    [[-22, -16], [22, -16], [-22, 16], [22, 16]].forEach(([wx, wy]) => {
        ctx.fillStyle = '#111';
        ctx.beginPath(); ctx.ellipse(wx, wy, 8, 6, 0, 0, Math.PI * 2); ctx.fill();
    });

    if (allStopped) {
        ctx.fillStyle = '#FF1744';
        [[-CAR_W / 2 + 4, -9], [-CAR_W / 2 + 4, 4]].forEach(([bx, by]) => {
            ctx.beginPath(); ctx.roundRect(bx, by, 7, 5, 2); ctx.fill();
        });
    }

    ctx.restore();

    if (popTimer > 0) {
        const alpha = Math.min(1, popTimer / 300);
        ctx.save(); ctx.globalAlpha = alpha;
        ctx.font = 'bold 15px sans-serif'; ctx.textAlign = 'center';
        ctx.fillStyle = popColor;
        ctx.fillText(popLabel, x, y - 46);
        ctx.restore();
    }
}

// ─────────────────────────────────────────────────────────────
// MAIN COMPONENT
// ─────────────────────────────────────────────────────────────
export default function TrafficPatrol({ onBack }) {
    const canvasRef = useRef(null);
    const containerRef = useRef(null);

    const sizeRef = useRef({ W: 800, H: 500, roadTop: 140, roadBot: 410, stopX: 600, lightX: 650 });

    // allStopped = the ONE global toggle controlled by spacebar
    const s = useRef({
        isGreen: false,
        allStopped: false,   // ← single flag for ALL cars
        cars: [],
        score: 0, missed: 0,
        running: false,
        timeLeft: 60,
        level: 0,
        spawnTimer: 0,
        laneYArr: [],
    });

    const [ui, setUi] = useState({
        screen: 'menu',
        score: 0, missed: 0, timeLeft: 60,
        levelIdx: 0,
        isGreen: false,
        allStopped: false,
    });

    const rafRef = useRef(null);
    const clockRef = useRef(null);
    const lightRef = useRef(null);
    const lastTsRef = useRef(null);

    // ── RESIZE ──
    useEffect(() => {
        const resize = () => {
            const c = containerRef.current, canvas = canvasRef.current;
            if (!c || !canvas) return;
            const W = c.clientWidth, H = c.clientHeight;
            canvas.width = W; canvas.height = H;
            const roadTop = Math.round(H * 0.26);
            const roadBot = Math.round(H * 0.80);
            const stopX = Math.round(W * STOP_LINE_X_RATIO);
            const lightX = Math.round(W * LIGHT_X_RATIO);
            sizeRef.current = { W, H, roadTop, roadBot, stopX, lightX };
            s.current.laneYArr = laneYs(roadTop, roadBot - roadTop);
        };
        resize();
        window.addEventListener('resize', resize);
        return () => window.removeEventListener('resize', resize);
    }, []);

    // ── DRAW ──
    const draw = useCallback(() => {
        const canvas = canvasRef.current;
        if (!canvas) return;
        const ctx = canvas.getContext('2d');
        const { W, H, roadTop, roadBot, stopX, lightX } = sizeRef.current;
        drawBackground(ctx, W, H, roadTop, roadBot);
        drawStopLine(ctx, stopX, roadTop, roadBot);
        s.current.cars.forEach(car => drawCar(ctx, car, s.current.allStopped));
        drawTrafficLight(ctx, lightX, roadTop, s.current.isGreen);
    }, []);

    // ── SPACEBAR — single toggle for ALL cars ──
    // ── GLOBAL STOP/RUN TOGGLE ──
    useEffect(() => {
        const toggleCars = () => {
            if (ui.screen !== 'playing') return;

            const st = s.current;

            // Toggle ALL cars
            st.allStopped = !st.allStopped;

            // Reset wait timers
            st.cars.forEach(c => {
                c.waitGreenMs = 0;
            });

            // Sound
            st.allStopped ? sfx.stop() : sfx.go();

            // Update UI
            setUi(p => ({
                ...p,
                allStopped: st.allStopped
            }));
        };

        // Keyboard (Desktop)
        const onKey = (e) => {
            if (e.code === 'Space') {
                e.preventDefault();
                toggleCars();
            }
        };

        // Touch / Click (Mobile)
        const onTouch = (e) => {
            e.preventDefault();
            toggleCars();
        };

        window.addEventListener('keydown', onKey);

        // Mobile support
        window.addEventListener('touchstart', onTouch, { passive: false });

        // Mouse click support
        window.addEventListener('click', onTouch);

        return () => {
            window.removeEventListener('keydown', onKey);
            window.removeEventListener('touchstart', onTouch);
            window.removeEventListener('click', onTouch);
        };
    }, [ui.screen]);

    // ── TRAFFIC LIGHT SCHEDULER ──
    const scheduleLight = useCallback(() => {
        clearTimeout(lightRef.current);
        const delay = 2200 + Math.random() * 2800;
        lightRef.current = setTimeout(() => {
            if (!s.current.running) return;
            s.current.isGreen = !s.current.isGreen;
            s.current.isGreen ? sfx.green() : sfx.red();
            setUi(p => ({ ...p, isGreen: s.current.isGreen }));
            scheduleLight();
        }, delay);
    }, []);

    // ── GAME LOOP ──
    const loop = useCallback((ts) => {
        if (!s.current.running) return;
        const dt = Math.min(lastTsRef.current ? ts - lastTsRef.current : 16, 50);
        lastTsRef.current = ts;

        const st = s.current;
        const cfg = LEVELS[st.level];
        const { W, stopX } = sizeRef.current;

        // SPAWN
        st.spawnTimer += dt;
        if (st.spawnTimer >= cfg.spawnInterval) {
            st.spawnTimer = 0;
            const taken = new Set(st.cars.filter(c => c.x < 200).map(c => c.lane));
            const free = st.laneYArr.map((_, i) => i).filter(i => !taken.has(i));
            const n = Math.min(free.length, cfg.carsAtOnce);
            for (let i = 0; i < n; i++) {
                const idx = free.splice(Math.floor(Math.random() * free.length), 1)[0];
                st.cars.push(makeCar(idx, st.laneYArr[idx], cfg.carSpeed));
            }
        }

        // UPDATE CARS
        st.cars.forEach(car => {
            if (car.popTimer > 0) car.popTimer -= dt;

            // Car-following: don't ram the car ahead
            const front = st.cars
                .filter(c => c.lane === car.lane && c.id !== car.id && c.x > car.x)
                .sort((a, b) => a.x - b.x)[0];
            const gap = front ? front.x - car.x : Infinity;

            // ── SPEED CONTROL ──

            // Once car crosses the stop line,
            // it should NEVER stop again
            const passedIntersection = car.x > stopX + 20;

            if (passedIntersection) {
                // Keep moving normally forever
                car.targetSpeed = car.speed;
            }
            else if (st.allStopped) {
                // Stop only BEFORE crossing line
                car.targetSpeed = 0;
            }
            else if (gap < 90) {
                // Avoid crashing into front cars
                car.targetSpeed = Math.max(0, front.currentSpeed * 0.75);
            }
            else {
                // Normal driving
                car.targetSpeed = car.speed;
            }

            car.currentSpeed += (car.targetSpeed - car.currentSpeed) * 0.10;
            car.x += (car.currentSpeed * dt) / 1000;

            // ── SCORING ──

            // Penalty: ran red (cars were running when they shouldn't be)
            const crossedStop = car.x > stopX && car.x < stopX + 90;
            if (crossedStop && !st.isGreen && !car.redRunScored) {
                car.redRunScored = true;
                st.score = Math.max(0, st.score + cfg.penaltyRed);
                st.missed++;
                car.popTimer = 900; car.popLabel = `${cfg.penaltyRed}`; car.popColor = '#FF5252';
                sfx.bad();
            }

            // Reward: cars stopped before stop line on red
            const beforeStop = car.x >= stopX - 130 && car.x < stopX;
            if (beforeStop && st.allStopped && !st.isGreen && !car.stopScored) {
                car.stopScored = true;
                st.score += cfg.rewardStop;
                car.popTimer = 900; car.popLabel = `+${cfg.rewardStop}`; car.popColor = '#4ADE80';
                sfx.good();
            }

            // Reward: car cleared intersection on green
            if (car.x > stopX + 60 && st.isGreen && !car.goScored) {
                car.goScored = true;
                st.score += cfg.rewardGo;
                car.popTimer = 900; car.popLabel = `+${cfg.rewardGo}`; car.popColor = '#4ADE80';
                sfx.good();
            }

            // Penalty: holding cars stopped on green too long
            if (st.allStopped && st.isGreen && car.x < stopX + 40) {
                car.waitGreenMs += dt;
                if (car.waitGreenMs > 4500) {
                    st.score = Math.max(0, st.score + cfg.penaltyMiss);
                    st.missed++;
                    car.popTimer = 900; car.popLabel = `${cfg.penaltyMiss}`; car.popColor = '#FF5252';
                    car.waitGreenMs = 0;
                    sfx.bad();
                }
            } else {
                car.waitGreenMs = 0;
            }
        });

        st.cars = st.cars.filter(c => c.x < W + 150);
        setUi(prev => ({ ...prev, score: st.score, missed: st.missed }));
        draw();
        rafRef.current = requestAnimationFrame(loop);
    }, [draw]);

    // ── START GAME ──
    const startGame = useCallback((levelIdx) => {
        getAC();
        clearInterval(clockRef.current);
        clearTimeout(lightRef.current);
        cancelAnimationFrame(rafRef.current);
        lastTsRef.current = null;

        const cfg = LEVELS[levelIdx];
        const { roadTop, roadBot } = sizeRef.current;

        s.current = {
            isGreen: false,
            allStopped: false,
            cars: [],
            score: 0, missed: 0,
            running: true,
            timeLeft: cfg.time,
            level: levelIdx,
            spawnTimer: 0,
            laneYArr: laneYs(roadTop, roadBot - roadTop),
        };

        setUi({ screen: 'playing', score: 0, missed: 0, timeLeft: cfg.time, levelIdx, isGreen: false, allStopped: false });

        scheduleLight();

        clockRef.current = setInterval(() => {
            s.current.timeLeft--;
            setUi(p => ({ ...p, timeLeft: s.current.timeLeft }));
            if (s.current.timeLeft <= 0) {
                s.current.running = false;
                clearInterval(clockRef.current);
                clearTimeout(lightRef.current);
                setUi(p => ({ ...p, screen: 'gameover' }));
            }
        }, 1000);

        rafRef.current = requestAnimationFrame(loop);
    }, [loop, scheduleLight]);

    const goToMenu = useCallback(() => {
        s.current.running = false;
        clearInterval(clockRef.current);
        clearTimeout(lightRef.current);
        cancelAnimationFrame(rafRef.current);
        setUi(p => ({ ...p, screen: 'menu' }));
        setTimeout(draw, 50);
    }, [draw]);

    useEffect(() => { draw(); }, [draw]);

    // ── STYLES ──
    const hudBadge = (bg, extra = {}) => ({
        display: 'flex', alignItems: 'center', gap: 6,
        padding: '8px 14px', borderRadius: 12,
        fontWeight: 700, fontSize: 15, color: '#fff',
        background: bg, ...extra,
    });

    const overlayStyle = {
        position: 'absolute', inset: 0,
        background: 'rgba(0,0,0,0.72)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
    };

    const cardStyle = {
        background: '#fff', padding: '28px 32px',
        borderRadius: 22, textAlign: 'center',
        minWidth: 320, maxWidth: '90vw', color: '#1a1a1a',
        position: 'relative',
    };

    const btnStyle = (bg) => ({
        border: 'none', borderRadius: 12, padding: '12px 22px',
        background: bg, color: '#fff', fontWeight: 700,
        fontSize: 15, cursor: 'pointer', minWidth: 110,
    });

    // ── RENDER ──
    return (
        <div ref={containerRef} style={{
            position: 'fixed',
            top: '80px',
            bottom: 0,
            left: 0,
            right: 0,
            background: '#0d1117', overflow: 'hidden',
            zIndex: 10, fontFamily: 'sans-serif',
        }}>
            <canvas ref={canvasRef} style={{ position: 'absolute', inset: 0, width: '100%', height: '100%' }} />

            {/* HUD */}
            {ui.screen === 'playing' && (
                <div style={{
                    position: 'absolute', top: 0, left: 0, right: 0,
                    padding: '12px 16px',
                    display: 'flex', justifyContent: 'flex-start', alignItems: 'center',
                    gap: '16px',
                    zIndex: 50,
                }}>
                    <button onClick={goToMenu} style={{
                        width: 44, height: 44, borderRadius: '50%',
                        border: 'none', background: '#ef4444',
                        color: '#fff', cursor: 'pointer', fontSize: 18,
                    }}>←</button>

                    <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                        <div style={hudBadge('#22c55e')}>🏆 {ui.score}</div>

                        {/* Signal badge */}
                        <div style={hudBadge(
                            ui.isGreen ? '#15803d' : '#b91c1c',
                            { boxShadow: `0 0 14px ${ui.isGreen ? '#22c55e' : '#ef4444'}99`, fontSize: 16 }
                        )}>
                            {ui.isGreen ? '🟢 GREEN' : '🔴 RED'}
                        </div>

                        {/* Cars state badge */}
                        <div style={hudBadge(ui.allStopped ? '#f59e0b' : '#6366f1')}>
                            {ui.allStopped ? '🛑 STOPPED' : '🚗 RUNNING'}
                        </div>

                        <div style={hudBadge('#3b82f6')}>⏱ {ui.timeLeft}s</div>
                        <div style={hudBadge('#ef4444')}>❌ {ui.missed}</div>
                    </div>
                </div>
            )}

            {/* Hint */}
            {ui.screen === 'playing' && (
                <div style={{
                    position: 'absolute', bottom: 14,
                    left: '50%', transform: 'translateX(-50%)',
                    background: 'rgba(0,0,0,0.65)', color: '#fff',
                    fontSize: 14, padding: '8px 22px', borderRadius: 20,
                    zIndex: 15, pointerEvents: 'none', whiteSpace: 'nowrap',
                    fontWeight: 600, letterSpacing: 0.3,
                }}>
                    Press <kbd style={{ background: '#fff3', padding: '1px 8px', borderRadius: 6, fontFamily: 'monospace' }}>Space</kbd> to stop / run ALL cars
                </div>
            )}

            {/* MENU */}
            {ui.screen === 'menu' && (
                <div style={overlayStyle}>
                    <div style={cardStyle}>
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
                        <h1 style={{ fontSize: 34, color: '#16a34a', marginBottom: 8 }}>🚦 Traffic Patrol</h1>
                        <p style={{ color: '#555', fontSize: 14, marginBottom: 14 }}>
                            The light changes randomly. React fast!
                        </p>
                        <div style={{
                            background: '#f0fdf4', borderRadius: 12,
                            padding: '14px 18px', marginBottom: 22,
                            fontSize: 13, color: '#166534', textAlign: 'left', lineHeight: 2,
                        }}>
                            <strong>⌨ Press Space</strong> to <strong>stop or run all cars</strong> at once.<br />
                            ✅ Stop cars before the line on <span style={{ color: '#dc2626', fontWeight: 700 }}>🔴 RED</span> → <strong>+points</strong><br />
                            ✅ Let cars run through on <span style={{ color: '#16a34a', fontWeight: 700 }}>🟢 GREEN</span> → <strong>+points</strong><br />
                            ❌ Car runs a red light → <strong>penalty</strong><br />
                            ❌ Cars blocked on green too long → <strong>penalty</strong>
                        </div>
                        <div style={{ display: 'flex', gap: 12, justifyContent: 'center', flexWrap: 'wrap' }}>
                            {LEVELS.map((lv, i) => (
                                <button key={i} onClick={() => startGame(i)}
                                    style={btnStyle(i === 0 ? '#22c55e' : i === 1 ? '#f59e0b' : '#ef4444')}>
                                    {lv.label}
                                    <div style={{ fontSize: 11, fontWeight: 400, opacity: 0.85, marginTop: 3 }}>
                                        {lv.time}s · {lv.carSpeed} km/h
                                    </div>
                                </button>
                            ))}
                        </div>
                    </div>
                </div>
            )}

            {/* GAME OVER */}
            {ui.screen === 'gameover' && (
                <div style={overlayStyle}>
                    <div style={cardStyle}>
                        <h2 style={{ fontSize: 30, color: '#16a34a', marginBottom: 10 }}>Game Over</h2>
                        <p style={{ fontSize: 22, marginBottom: 6 }}>
                            Score: <strong style={{ color: '#16a34a' }}>{ui.score}</strong>
                        </p>
                        <p style={{ color: '#888', fontSize: 14, marginBottom: 24 }}>
                            Red light violations: <strong>{ui.missed}</strong>
                        </p>
                        <div style={{ display: 'flex', gap: 12, justifyContent: 'center' }}>
                            <button onClick={() => startGame(ui.levelIdx)} style={btnStyle('#22c55e')}>Play Again</button>
                            <button onClick={goToMenu} style={btnStyle('#f59e0b')}>Menu</button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}