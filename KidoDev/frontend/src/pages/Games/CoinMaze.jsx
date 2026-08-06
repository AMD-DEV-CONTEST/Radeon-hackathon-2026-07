import { useState, useEffect, useCallback, useRef } from "react";

// ─── Audio ────────────────────────────────────────────────────────────────────
let audioCtx = null;
function getAC() {
    if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    if (audioCtx.state === "suspended") audioCtx.resume();
    return audioCtx;
}
function playTone(f1, f2, dur, type = "sine", vol = 0.18) {
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
    coin: () => { playTone(660, 990, 0.10, "sine", 0.20); setTimeout(() => playTone(990, 1320, 0.10, "sine", 0.16), 100); },
    step: () => playTone(180, 200, 0.04, "square", 0.05),
    locked: () => { playTone(300, 200, 0.15, "sawtooth", 0.18); setTimeout(() => playTone(200, 130, 0.18, "sawtooth", 0.14), 140); },
    win: () => { [0, 120, 240, 380].forEach((d, i) => setTimeout(() => playTone([523, 659, 784, 1047][i], [659, 784, 1047, 1300][i], 0.14, "sine", 0.18), d)); },
    start: () => playTone(440, 660, 0.16, "sine", 0.14),
    timeWarn: () => playTone(880, 880, 0.08, "square", 0.12),
};

// ─── Constants ────────────────────────────────────────────────────────────────
const COLS = 15;
const ROWS = 12;
const EMPTY = 0, WALL = 1, COIN = 2, DOOR = 3, PLAYER_START = 4;

const LEVELS = [
    { label: "Easy", coins: 5, time: 0, wallColor: "#b8d4f0", floorColor: "#eaf4ff", accent: "#2196f3", accentLight: "#e3f2fd", accentBorder: "#90caf9", wallInner: "#d6e8f8" },
    { label: "Medium", coins: 8, time: 60, wallColor: "#a8d5a2", floorColor: "#f1fbef", accent: "#43a047", accentLight: "#e8f5e9", accentBorder: "#81c784", wallInner: "#c8e6c9" },
    { label: "Hard", coins: 10, time: 40, wallColor: "#f0b8a8", floorColor: "#fff5f2", accent: "#e53935", accentLight: "#fce4ec", accentBorder: "#ef9a9a", wallInner: "#ffccbc" },
];

const MAPS = [
    [
        [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
        [1, 4, 0, 0, 2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1],
        [1, 0, 1, 1, 0, 1, 0, 1, 1, 1, 0, 1, 1, 0, 1],
        [1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1],
        [1, 2, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1],
        [1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1],
        [1, 0, 1, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 0, 1],
        [1, 0, 0, 0, 0, 0, 2, 0, 0, 0, 0, 0, 0, 2, 1],
        [1, 1, 1, 0, 1, 1, 0, 1, 1, 0, 1, 1, 0, 0, 1],
        [1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 1],
        [1, 2, 0, 1, 0, 1, 0, 0, 0, 1, 0, 0, 0, 3, 1],
        [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
    ],
    [
        [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
        [1, 4, 0, 0, 2, 0, 1, 0, 2, 0, 0, 0, 2, 0, 1],
        [1, 0, 1, 1, 0, 1, 1, 1, 0, 1, 1, 0, 1, 0, 1],
        [1, 0, 1, 2, 0, 0, 0, 0, 0, 0, 2, 0, 0, 0, 1],
        [1, 0, 1, 0, 1, 1, 0, 1, 1, 1, 0, 1, 1, 0, 1],
        [1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 2, 0, 1],
        [1, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 1, 0, 1],
        [1, 0, 1, 1, 1, 0, 1, 1, 0, 1, 1, 0, 1, 2, 1],
        [1, 2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1],
        [1, 0, 1, 0, 1, 1, 1, 0, 1, 1, 1, 0, 1, 0, 1],
        [1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 3, 1],
        [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
    ],
    [
        [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
        [1, 4, 0, 2, 1, 0, 2, 0, 1, 0, 2, 0, 1, 0, 1],
        [1, 1, 1, 0, 1, 1, 0, 1, 1, 1, 0, 1, 0, 1, 1],
        [1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 2, 0, 0, 2, 1],
        [1, 0, 1, 1, 1, 0, 1, 1, 0, 1, 1, 1, 1, 0, 1],
        [1, 2, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 1, 0, 1],
        [1, 1, 1, 0, 0, 1, 1, 0, 1, 1, 0, 0, 0, 0, 1],
        [1, 0, 0, 0, 1, 0, 2, 0, 0, 0, 1, 0, 1, 2, 1],
        [1, 0, 1, 1, 0, 1, 1, 1, 0, 1, 1, 0, 0, 0, 1],
        [1, 0, 0, 2, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1],
        [1, 1, 0, 0, 1, 1, 0, 2, 0, 1, 0, 0, 0, 3, 1],
        [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
    ],
];

function buildMap(lvl) { return MAPS[lvl].map(r => [...r]); }
function findTile(map, tile) {
    for (let r = 0; r < ROWS; r++)
        for (let c = 0; c < COLS; c++)
            if (map[r][c] === tile) return { r, c };
    return { r: 1, c: 1 };
}

let floatId = 0;

// ─── Inject styles once ───────────────────────────────────────────────────────
function injectStyles() {
    if (document.getElementById("coin-maze-v2-styles")) return;
    const s = document.createElement("style");
    s.id = "coin-maze-v2-styles";
    s.textContent = `
        @import url('https://fonts.googleapis.com/css2?family=Nunito:wght@400;600;700;800;900&display=swap');

        .cm-root { font-family: 'Nunito', 'Segoe UI', sans-serif; }

        @keyframes cmCoinSpin {
            0%   { transform: rotateY(0deg) scale(1); }
            50%  { transform: rotateY(180deg) scale(1.15); }
            100% { transform: rotateY(360deg) scale(1); }
        }
        @keyframes cmFloatUp {
            0%   { opacity:1; transform:translateY(0) scale(1); }
            100% { opacity:0; transform:translateY(-52px) scale(1.25); }
        }
        @keyframes cmShake {
            0%,100% { transform:translateX(0); }
            20%     { transform:translateX(-7px); }
            40%     { transform:translateX(7px); }
            60%     { transform:translateX(-4px); }
            80%     { transform:translateX(4px); }
        }
        @keyframes cmFadeIn {
            from { opacity:0; transform:translateY(8px); }
            to   { opacity:1; transform:translateY(0); }
        }
        @keyframes cmTimePulse {
            0%,100% { transform:scale(1); }
            50%     { transform:scale(1.1); }
        }
        @keyframes cmPulse {
            0%,100% { transform:scale(1); box-shadow: 0 4px 14px rgba(0,0,0,0.12); }
            50%     { transform:scale(1.15); box-shadow: 0 6px 20px rgba(0,0,0,0.2); }
        }
        @keyframes cmSlideIn {
            from { opacity:0; transform:translateY(-16px) scale(0.97); }
            to   { opacity:1; transform:translateY(0) scale(1); }
        }
        @keyframes cmWinPop {
            0%   { transform:scale(0.8); opacity:0; }
            70%  { transform:scale(1.05); }
            100% { transform:scale(1); opacity:1; }
        }
        @keyframes cmDoorGlow {
            0%,100% { box-shadow: 0 0 0 0 rgba(76,175,80,0); }
            50%     { box-shadow: 0 0 14px 4px rgba(76,175,80,0.35); }
        }

        .cm-board-cell { transition: background 0.15s; }
        .cm-player { transition: left 0.12s cubic-bezier(.25,.46,.45,.94), top 0.12s cubic-bezier(.25,.46,.45,.94); }

        .cm-lvl-btn {
            border: none; border-radius: 16px; padding: 14px 20px;
            color: #fff; font-weight: 800; font-size: 15px;
            cursor: pointer; min-width: 120px; letter-spacing: 0.3px;
            font-family: 'Nunito', 'Segoe UI', sans-serif;
            transition: transform 0.13s, box-shadow 0.13s;
            position: relative; overflow: hidden;
        }
        .cm-lvl-btn:hover { transform: translateY(-2px) scale(1.03); }
        .cm-lvl-btn:active { transform: translateY(1px) scale(0.98); }
        .cm-lvl-easy   { background: linear-gradient(160deg,#43b96a,#2e9e52); box-shadow: 0 4px 0 #1e7a3e, 0 6px 16px rgba(46,158,82,0.35); }
        .cm-lvl-medium { background: linear-gradient(160deg,#ff9f2e,#f07a00); box-shadow: 0 4px 0 #c06000, 0 6px 16px rgba(240,122,0,0.35); }
        .cm-lvl-hard   { background: linear-gradient(160deg,#f5524a,#d92d24); box-shadow: 0 4px 0 #a81e17, 0 6px 16px rgba(217,45,36,0.35); }

        .cm-action-btn {
            border: none; border-radius: 12px; padding: 11px 20px;
            color: #fff; font-weight: 700; font-size: 14px;
            cursor: pointer; font-family: 'Nunito', 'Segoe UI', sans-serif;
            transition: transform 0.12s, box-shadow 0.12s;
            box-shadow: 0 3px 10px rgba(0,0,0,0.15);
        }
        .cm-action-btn:hover { transform: translateY(-1px); }
        .cm-action-btn:active { transform: translateY(1px); }

        .cm-back-btn {
            background: #fff; border: 1.5px solid #e0e0e0; border-radius: 10px;
            padding: 7px 14px; color: #555; cursor: pointer; font-size: 13px;
            font-weight: 700; font-family: 'Nunito', 'Segoe UI', sans-serif;
            display: flex; align-items: center; gap: 5px;
            transition: background 0.12s, transform 0.1s;
            box-shadow: 0 2px 6px rgba(0,0,0,0.07);
        }
        .cm-back-btn:hover { background: #f5f5f5; transform: translateY(-1px); }

        .cm-hud-pill {
            display: flex; align-items: center; gap: 5px;
            padding: 6px 13px; border-radius: 20px; font-weight: 700;
            font-size: 14px; border: 1.5px solid transparent;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
            font-family: 'Nunito', 'Segoe UI', sans-serif;
        }
        .cm-coin-pulse { animation: cmPulse 0.3s ease; }

        .cm-card {
            background: #fff; padding: 20px 24px;
            border-radius: 26px; text-align: center;
            min-width: 340px; max-width: 94vw;
            box-shadow: 0 12px 50px rgba(0,0,0,0.14), 0 2px 8px rgba(0,0,0,0.06);
            border: 1.5px solid #eaecf4;
            animation: cmSlideIn 0.3s ease;
        }
        .cm-card--win { animation: cmWinPop 0.4s cubic-bezier(.34,1.56,.64,1); }
        .cm-result-grid {
            display: grid; grid-template-columns: 1fr 1fr 1fr;
            gap: 10px; margin: 18px 0;
        }
        .cm-result-cell {
            background: #f7f9fc; border-radius: 12px; padding: 12px 8px;
            border: 1.5px solid #eaecf4; display: flex;
            flex-direction: column; gap: 3px;
        }
        .cm-result-label { font-size: 11px; color: #888; font-weight: 700; letter-spacing: 0.5px; text-transform: uppercase; }
        .cm-result-val   { font-size: 22px; font-weight: 900; color: #1a1a2e; }
    `;
    document.head.appendChild(s);
}

// ─── Cat Sprite ───────────────────────────────────────────────────────────────
function CatSprite({ facing, size = 40 }) {
    const s = size / 40;
    return (
        <div style={{
            position: "relative", width: size, height: size,
            userSelect: "none", flexShrink: 0,
            transform: facing === "left" ? "scaleX(-1)" : "none",
            transition: "transform 0.08s",
        }}>
            <div style={{ position: "absolute", bottom: 0, left: size * 0.18, width: size * 0.64, height: size * 0.13, background: "rgba(0,0,0,0.12)", borderRadius: "50%" }} />
            <div style={{ position: "absolute", bottom: size * 0.1, left: size * 0.16, width: size * 0.62, height: size * 0.44, background: "#f5a623", borderRadius: "38% 38% 50% 50%", border: `${1.5 * s}px solid #c97d10`, boxShadow: "inset 0 2px 5px rgba(255,255,255,0.32)" }} />
            <div style={{ position: "absolute", bottom: size * 0.14, left: size * 0.3, width: size * 0.38, height: size * 0.28, background: "#fdd090", borderRadius: "40% 40% 50% 50%", border: `${s}px solid #e8a430` }} />
            <div style={{ position: "absolute", top: size * 0.03, left: size * 0.18, width: size * 0.58, height: size * 0.52, background: "#f5a623", borderRadius: "52% 52% 38% 38%", border: `${1.5 * s}px solid #c97d10`, boxShadow: "inset 0 2px 5px rgba(255,255,255,0.28)" }}>
                <div style={{ position: "absolute", top: -size * 0.18, left: size * 0.02, width: 0, height: 0, borderLeft: `${5 * s}px solid transparent`, borderRight: `${5 * s}px solid transparent`, borderBottom: `${9 * s}px solid #c97d10` }} />
                <div style={{ position: "absolute", top: -size * 0.16, left: size * 0.04, width: 0, height: 0, borderLeft: `${3.5 * s}px solid transparent`, borderRight: `${3.5 * s}px solid transparent`, borderBottom: `${6 * s}px solid #f5a623` }} />
                <div style={{ position: "absolute", top: -size * 0.18, right: size * 0.02, width: 0, height: 0, borderLeft: `${5 * s}px solid transparent`, borderRight: `${5 * s}px solid transparent`, borderBottom: `${9 * s}px solid #c97d10` }} />
                <div style={{ position: "absolute", top: -size * 0.16, right: size * 0.04, width: 0, height: 0, borderLeft: `${3.5 * s}px solid transparent`, borderRight: `${3.5 * s}px solid transparent`, borderBottom: `${6 * s}px solid #f5a623` }} />
                <div style={{ position: "absolute", top: "32%", left: "14%", width: `${5 * s}px`, height: `${6 * s}px`, background: "#1a6b50", borderRadius: "50%", border: `${s}px solid #111` }} />
                <div style={{ position: "absolute", top: "36%", left: "18%", width: `${2 * s}px`, height: `${3 * s}px`, background: "#111", borderRadius: "50%" }} />
                <div style={{ position: "absolute", top: "32%", right: "14%", width: `${5 * s}px`, height: `${6 * s}px`, background: "#1a6b50", borderRadius: "50%", border: `${s}px solid #111` }} />
                <div style={{ position: "absolute", top: "36%", right: "18%", width: `${2 * s}px`, height: `${3 * s}px`, background: "#111", borderRadius: "50%" }} />
                <div style={{ position: "absolute", top: "65%", left: "50%", transform: "translateX(-50%)", width: `${4 * s}px`, height: `${3 * s}px`, background: "#e8706a", borderRadius: "50%" }} />
                <div style={{ position: "absolute", top: "78%", left: "28%", width: `${3 * s}px`, height: `${2 * s}px`, borderBottom: `${1.5 * s}px solid #c97d10`, borderLeft: `${1.5 * s}px solid #c97d10`, borderRadius: "0 0 0 4px" }} />
                <div style={{ position: "absolute", top: "78%", right: "28%", width: `${3 * s}px`, height: `${2 * s}px`, borderBottom: `${1.5 * s}px solid #c97d10`, borderRight: `${1.5 * s}px solid #c97d10`, borderRadius: "0 0 4px 0" }} />
                <div style={{ position: "absolute", top: "60%", left: "-28%", width: `${9 * s}px`, height: `${s}px`, background: "#c97d10", opacity: 0.55 }} />
                <div style={{ position: "absolute", top: "68%", left: "-28%", width: `${9 * s}px`, height: `${s}px`, background: "#c97d10", opacity: 0.4 }} />
                <div style={{ position: "absolute", top: "60%", right: "-28%", width: `${9 * s}px`, height: `${s}px`, background: "#c97d10", opacity: 0.55 }} />
                <div style={{ position: "absolute", top: "68%", right: "-28%", width: `${9 * s}px`, height: `${s}px`, background: "#c97d10", opacity: 0.4 }} />
            </div>
            <div style={{ position: "absolute", bottom: size * 0.18, right: -size * 0.12, width: `${9 * s}px`, height: `${13 * s}px`, borderRight: `${2.5 * s}px solid #c97d10`, borderBottom: `${2.5 * s}px solid #c97d10`, borderRadius: `0 0 ${12 * s}px 0`, transform: "rotate(-10deg)" }} />
            <div style={{ position: "absolute", bottom: size * 0.04, left: size * 0.22, width: `${5 * s}px`, height: `${6 * s}px`, background: "#f5a623", borderRadius: "3px 3px 5px 5px", border: `${s}px solid #c97d10` }} />
            <div style={{ position: "absolute", bottom: size * 0.04, right: size * 0.22, width: `${5 * s}px`, height: `${6 * s}px`, background: "#f5a623", borderRadius: "3px 3px 5px 5px", border: `${s}px solid #c97d10` }} />
        </div>
    );
}

// ─── Main Component ───────────────────────────────────────────────────────────
export default function CoinMaze({ onBack }) {
    injectStyles();

    const [screen, setScreen] = useState("menu");
    const [levelIdx, setLevelIdx] = useState(0);

    const gameRef = useRef({
        map: buildMap(0),
        player: { r: 1, c: 1 },
        coins: 0,
        steps: 0,
        timeLeft: 0,
        phase: "playing",
        facing: "right",
    });

    const [renderKey, setRenderKey] = useState(0);
    const [floats, setFloats] = useState([]);
    const [doorShake, setDoorShake] = useState(false);
    const [coinPulse, setCoinPulse] = useState(false);

    const timerRef = useRef(null);
    const sync = useCallback(() => setRenderKey(k => k + 1), []);

    const cfg = LEVELS[levelIdx];

    const handleBack = useCallback(() => {
        clearInterval(timerRef.current);
        typeof onBack === "function" ? onBack() : setScreen("menu");
    }, [onBack]);

    const addFloat = useCallback((text, c, r, color, cell) => {
        const id = floatId++;
        setFloats(f => [...f, { id, text, x: c * cell, y: r * cell, color }]);
        setTimeout(() => setFloats(f => f.filter(i => i.id !== id)), 900);
    }, []);

    const startGame = useCallback((lvl) => {
        getAC();
        sfx.start();
        clearInterval(timerRef.current);
        const m = buildMap(lvl);
        const start = findTile(m, PLAYER_START);
        gameRef.current = {
            map: m,
            player: start,
            coins: 0,
            steps: 0,
            timeLeft: LEVELS[lvl].time,
            phase: "playing",
            facing: "right",
        };
        setLevelIdx(lvl);
        setFloats([]);
        setDoorShake(false);
        setCoinPulse(false);
        setScreen("playing");
        sync();

        const t = LEVELS[lvl].time;
        if (t > 0) {
            timerRef.current = setInterval(() => {
                const g = gameRef.current;
                if (g.timeLeft <= 1) {
                    clearInterval(timerRef.current);
                    g.timeLeft = 0;
                    setScreen("gameover");
                    sync();
                    return;
                }
                g.timeLeft -= 1;
                if (g.timeLeft <= 10) sfx.timeWarn();
                sync();
            }, 1000);
        }
    }, [sync]);

    const CELL = useRef(48);

    const move = useCallback((dr, dc) => {
        const g = gameRef.current;
        if (g.phase !== "playing") return;

        if (dc > 0) g.facing = "right";
        if (dc < 0) g.facing = "left";

        const nr = g.player.r + dr;
        const nc = g.player.c + dc;
        const cell = g.map[nr]?.[nc];

        if (cell === undefined || cell === WALL) { sync(); return; }

        sfx.step();
        g.steps += 1;

        if (cell === DOOR) {
            if (g.coins >= LEVELS[levelIdx].coins) {
                clearInterval(timerRef.current);
                sfx.win();
                g.phase = "win";
                setScreen("win");
            } else {
                setDoorShake(true);
                setTimeout(() => setDoorShake(false), 500);
                g.phase = "door-locked";
                setTimeout(() => { gameRef.current.phase = "playing"; sync(); }, 1600);
                sfx.locked();
                addFloat(`Need ${LEVELS[levelIdx].coins - g.coins} more!`, nc, nr, "#c62828", CELL.current);
            }
            sync();
            return;
        }

        if (cell === COIN) {
            g.map[nr][nc] = EMPTY;
            g.coins += 1;
            sfx.coin();
            addFloat("+1 🪙", nc, nr, "#e65100", CELL.current);
            setCoinPulse(true);
            setTimeout(() => setCoinPulse(false), 280);
        }

        g.player = { r: nr, c: nc };
        sync();
    }, [levelIdx, addFloat, sync]);

    useEffect(() => {
        const keyHandler = (e) => {
            if (screen !== "playing") return;

            const d = {
                ArrowUp: [-1, 0],
                ArrowDown: [1, 0],
                ArrowLeft: [0, -1],
                ArrowRight: [0, 1],
                w: [-1, 0],
                s: [1, 0],
                a: [0, -1],
                d: [0, 1],
                W: [-1, 0],
                S: [1, 0],
                A: [0, -1],
                D: [0, 1],
            }[e.key];

            if (d) {
                e.preventDefault();
                move(...d);
            }
        };

        window.addEventListener("keydown", keyHandler);

        let startX = 0;
        let startY = 0;

        // ─── SHARED MOVE LOGIC ───
        const handleDirectionalInput = (x, y) => {
            if (screen !== "playing") return;

            const w = window.innerWidth;
            const h = window.innerHeight;

            const centerX = w / 2;
            const centerY = h / 2;

            const diffX = x - centerX;
            const diffY = y - centerY;

            if (Math.abs(diffX) > Math.abs(diffY)) {
                if (diffX > 0) move(0, 1); // RIGHT
                else move(0, -1); // LEFT
            } else {
                if (diffY > 0) move(1, 0); // DOWN
                else move(-1, 0); // UP
            }
        };

        // ─── TOUCH START ───
        const handleTouchStart = (e) => {
            const touch = e.touches[0];
            startX = touch.clientX;
            startY = touch.clientY;
        };

        // ─── TOUCH END ───
        const handleTouchEnd = (e) => {
            if (screen !== "playing") return;

            const touch = e.changedTouches[0];

            const endX = touch.clientX;
            const endY = touch.clientY;

            const dx = endX - startX;
            const dy = endY - startY;

            const absX = Math.abs(dx);
            const absY = Math.abs(dy);

            // ─── SWIPE DETECTION ───
            if (absX > 40 || absY > 40) {
                if (absX > absY) {
                    if (dx > 0) move(0, 1);
                    else move(0, -1);
                } else {
                    if (dy > 0) move(1, 0);
                    else move(-1, 0);
                }
                return;
            }

            // ─── TAP DETECTION ───
            handleDirectionalInput(endX, endY);
        };

        // ─── MOUSE CLICK SUPPORT (Laptop/Desktop) ───
        const handleMouseClick = (e) => {
            handleDirectionalInput(e.clientX, e.clientY);
        };

        window.addEventListener("touchstart", handleTouchStart, { passive: true });
        window.addEventListener("touchend", handleTouchEnd, { passive: true });

        window.addEventListener("click", handleMouseClick);

        return () => {
            window.removeEventListener("keydown", keyHandler);
            window.removeEventListener("touchstart", handleTouchStart);
            window.removeEventListener("touchend", handleTouchEnd);

            window.removeEventListener("click", handleMouseClick);
        };
    }, [move, screen]);

    useEffect(() => () => clearInterval(timerRef.current), []);

    const g = gameRef.current;
    const progress = Math.min(g.coins / (cfg.coins || 1), 1);

    const containerRef = useRef(null);
    const [cellSize, setCellSize] = useState(48);
    useEffect(() => {
        const calc = () => {
            const vw = window.innerWidth;
            const vh = window.innerHeight;

            const isMobile = vw < 768;

            const horizontalPadding = isMobile ? 12 : 32;
            const reservedHeight = isMobile ? 170 : 150;

            const maxW = Math.floor((vw - horizontalPadding) / COLS);
            const maxH = Math.floor((vh - reservedHeight) / ROWS);

            const minCell = isMobile ? 22 : 28;
            const maxCell = isMobile ? 42 : 90;

            const c = Math.max(minCell, Math.min(maxCell, maxW, maxH));

            setCellSize(c);
            CELL.current = c;
        };
        calc();
        window.addEventListener("resize", calc);
        return () => window.removeEventListener("resize", calc);
    }, []);

    const boardW = COLS * cellSize;
    const boardH = ROWS * cellSize;

    // ─── MENU ─────────────────────────────────────────────────────────────────
    if (screen === "menu") return (
        <div className="cm-root" style={{
            position: "fixed",
            top: 0,
            paddingTop: "env(safe-area-inset-top, 0px)", bottom: 0, left: 0, right: 0, background: "#f0f4fb", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 10
        }}>
            <div className="cm-card" style={{ maxWidth: 420, position: "relative" }}>
                {onBack && (
                    <button
                        onClick={handleBack}
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
                            zIndex: 10,
                        }}
                        onMouseEnter={(e) => e.target.style.color = '#ff6b6b'}
                        onMouseLeave={(e) => e.target.style.color = '#888'}
                        title="Close"
                    >
                        &times;
                    </button>
                )}

                <div style={{ fontSize: 44, lineHeight: 1, marginBottom: 6 }}>🐱</div>
                <h1 style={{ fontSize: 24, fontWeight: 900, color: "#1a1a2e", margin: "0 0 4px", letterSpacing: 0.5 }}>Coin Maze</h1>
                <p style={{ color: "#6b7280", fontSize: 13, marginBottom: 14, lineHeight: 1.5 }}>
                    Guide the cat, collect all coins, and escape the maze! Swipe or tap screen sides to move.e maze! Use Arrow Keys or WASD to move.
                </p>

                <p style={{ fontSize: 11, fontWeight: 800, color: "#9ca3af", letterSpacing: 1, textTransform: "uppercase", marginBottom: 8 }}>
                    Choose Difficulty
                </p>
                <div style={{ display: "flex", gap: 12, justifyContent: "center", flexWrap: "wrap" }}>
                    {LEVELS.map((lv, i) => (
                        <button key={i} onClick={() => startGame(i)}
                            className={`cm-lvl-btn cm-lvl-${lv.label.toLowerCase()}`}>
                            <div style={{ fontSize: 16, fontWeight: 900 }}>{lv.label}</div>
                            <div style={{ fontSize: 11, opacity: 0.9, marginTop: 3, fontWeight: 600 }}>
                                {lv.coins} coins · {lv.time ? `${lv.time}s` : "No timer"}
                            </div>
                        </button>
                    ))}
                </div>
            </div>
        </div>
    );

    // ─── GAME OVER ────────────────────────────────────────────────────────────
    if (screen === "gameover") return (
        <div className="cm-root" style={{
            position: "fixed",
            top: 0,
            paddingTop: "env(safe-area-inset-top, 0px)", bottom: 0, left: 0, right: 0, background: "#f0f4fb", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 10
        }}>
            <div className="cm-card">
                <div style={{ fontSize: 52, marginBottom: 8 }}>⏰</div>
                <h2 style={{ fontSize: 26, fontWeight: 900, color: "#e03030", margin: "0 0 8px" }}>Time&apos;s Up!</h2>
                <p style={{ color: "#6b7280", fontSize: 14, marginBottom: 18 }}>Better luck next time!</p>
                <div className="cm-result-grid">
                    <div className="cm-result-cell">
                        <span className="cm-result-label">Coins</span>
                        <span className="cm-result-val" style={{ color: "#e07a00" }}>{g.coins}/{cfg.coins}</span>
                    </div>
                    <div className="cm-result-cell">
                        <span className="cm-result-label">Steps</span>
                        <span className="cm-result-val">{g.steps}</span>
                    </div>
                    <div className="cm-result-cell">
                        <span className="cm-result-label">Level</span>
                        <span className="cm-result-val" style={{ fontSize: 16 }}>{cfg.label}</span>
                    </div>
                </div>
                <div style={{ display: "flex", gap: 10, justifyContent: "center", flexWrap: "wrap" }}>
                    <button className="cm-action-btn cm-lvl-easy" onClick={() => startGame(levelIdx)}>Try Again</button>
                    <button className="cm-action-btn cm-lvl-medium" onClick={() => setScreen("menu")}>Level Select</button>
                    {onBack && <button className="cm-action-btn" style={{ background: "#78909c" }} onClick={handleBack}>← Back</button>}
                </div>
            </div>
        </div>
    );

    // ─── WIN ──────────────────────────────────────────────────────────────────
    if (screen === "win") return (
        <div className="cm-root" style={{
            position: "fixed", top: 0,
            paddingTop: "env(safe-area-inset-top, 0px)", bottom: 0, left: 0, right: 0, background: "#f0f4fb", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 10
        }}>
            <div className="cm-card cm-card--win">
                <div style={{ fontSize: 52, marginBottom: 8 }}>🎉</div>
                <h2 style={{ fontSize: 26, fontWeight: 900, color: "#2e7d32", margin: "0 0 8px" }}>Escaped!</h2>
                <p style={{ color: "#6b7280", fontSize: 14, marginBottom: 18 }}>You&apos;re a Maze Master!</p>
                <div style={{
                    fontSize: 15, fontWeight: 900, color: "#e07a00",
                    letterSpacing: 2, margin: "0 0 16px",
                    padding: "10px 20px", background: "#fff8e1",
                    borderRadius: 10, border: "1.5px solid #ffe082", display: "inline-block",
                }}>
                    ⭐ MAZE MASTER ⭐
                </div>
                <div className="cm-result-grid">
                    <div className="cm-result-cell">
                        <span className="cm-result-label">Coins</span>
                        <span className="cm-result-val" style={{ color: "#e07a00" }}>{g.coins}</span>
                    </div>
                    <div className="cm-result-cell">
                        <span className="cm-result-label">Steps</span>
                        <span className="cm-result-val">{g.steps}</span>
                    </div>
                    {cfg.time > 0 && (
                        <div className="cm-result-cell">
                            <span className="cm-result-label">Time Left</span>
                            <span className="cm-result-val" style={{ color: "#2e7d32", fontSize: 16 }}>{g.timeLeft}s</span>
                        </div>
                    )}
                </div>
                <div style={{ display: "flex", gap: 10, justifyContent: "center", flexWrap: "wrap" }}>
                    <button className="cm-action-btn cm-lvl-easy" onClick={() => startGame(levelIdx)}>Play Again</button>
                    <button className="cm-action-btn cm-lvl-medium" onClick={() => setScreen("menu")}>Level Select</button>
                    {onBack && <button className="cm-action-btn" style={{ background: "#78909c" }} onClick={handleBack}>← Back</button>}
                </div>
            </div>
        </div>
    );

    // ─── PLAYING ──────────────────────────────────────────────────────────────
    return (
        <div className="cdg-fullpage" ref={containerRef}>

            {/* ───────────── HUD ───────────── */}
            <div className="cdg-floating-hud">

                <button
                    className="cdg-back"
                    onClick={handleBack}
                    type="button"
                    aria-label="Back"
                >
                    ←
                </button>

                <h1 className="cdg-title">
                    Coin Maze
                </h1>

                {screen === "playing" && (
                    <div className="cdg-hud">

                        {/* Coins */}
                        <div
                            className={`hud-pill hud-pill-score ${coinPulse ? "cdg-pulse" : ""}`}
                        >
                            🪙 <strong>{g.coins}/{cfg.coins}</strong>
                        </div>

                        {/* Timer */}
                        {cfg.time > 0 && (
                            <div
                                className="hud-pill"
                                style={
                                    g.timeLeft <= 10
                                        ? {
                                            background:
                                                "linear-gradient(180deg, #FF6B6B 0%, #E03131 100%)",
                                            borderColor: "#FFE3E3",
                                            boxShadow:
                                                "0 4px 0 #C92A2A, 0 6px 10px rgba(0,0,0,0.25)",
                                        }
                                        : {}
                                }
                            >
                                ⏱ <strong>{g.timeLeft}s</strong>
                            </div>
                        )}

                        {/* Steps */}
                        <div className="hud-pill hud-pill-miss">
                            👣 <strong>{g.steps}</strong>
                        </div>

                        {/* Level */}
                        <div
                            className="hud-pill"
                            style={{
                                background: cfg.accentLight,
                                color: cfg.accent,
                                borderColor: cfg.accentBorder,
                            }}
                        >
                            <strong>{cfg.label}</strong>
                        </div>

                    </div>
                )}
            </div>

            {/* ───────────── MENU ───────────── */}
            {screen === "menu" && (
                <div className="cdg-overlay">
                    <div className="cdg-panel" style={{ position: "relative", maxWidth: 420 }}>

                        <button
                            onClick={handleBack}
                            style={{
                                position: "absolute",
                                top: "16px",
                                right: "20px",
                                background: "transparent",
                                border: "none",
                                color: "#888",
                                fontSize: "28px",
                                fontWeight: "bold",
                                cursor: "pointer",
                                padding: "4px 8px",
                                lineHeight: "1",
                            }}
                            onMouseEnter={(e) => (e.target.style.color = "#ff6b6b")}
                            onMouseLeave={(e) => (e.target.style.color = "#888")}
                        >
                            &times;
                        </button>

                        <div style={{ fontSize: 54, marginBottom: 8 }}>🐱</div>

                        <h2 className="cdg-panel-title">Coin Maze</h2>

                        <p className="cdg-panel-desc">
                            Guide the cat through the maze, collect coins, and unlock the door!
                        </p>

                        <p className="cdg-choose-label">Choose Difficulty</p>

                        <div className="cdg-lvl-row">
                            {LEVELS.map((lv, i) => (
                                <button
                                    key={i}
                                    className={`cdg-lvl-btn cdg-lvl-${lv.label.toLowerCase()}`}
                                    onClick={() => startGame(i)}
                                    type="button"
                                >
                                    <span className="lvl-name">{lv.label}</span>
                                    <span className="lvl-sub">
                                        {lv.coins} coins · {lv.time ? `${lv.time}s` : "No timer"}
                                    </span>
                                </button>
                            ))}
                        </div>
                    </div>
                </div>
            )}

            {/* ───────────── GAME OVER ───────────── */}
            {screen === "gameover" && (
                <div className="cdg-overlay">
                    <div className="cdg-panel cdg-panel--result">

                        <h2 className="cdg-panel-title">⏰ Time's Up!</h2>

                        <div className="result-grid">
                            <div className="result-cell">
                                <span className="rc-label">Coins</span>
                                <span className="rc-val">{g.coins}/{cfg.coins}</span>
                            </div>

                            <div className="result-cell">
                                <span className="rc-label">Steps</span>
                                <span className="rc-val">{g.steps}</span>
                            </div>

                            <div className="result-cell">
                                <span className="rc-label">Level</span>
                                <span className="rc-val">{cfg.label}</span>
                            </div>
                        </div>

                        <div className="cdg-lvl-row">
                            <button
                                className="cdg-lvl-btn cdg-lvl-easy"
                                onClick={() => startGame(levelIdx)}
                            >
                                <span className="lvl-name">Try Again</span>
                            </button>

                            <button
                                className="cdg-lvl-btn cdg-lvl-medium"
                                onClick={() => setScreen("menu")}
                            >
                                <span className="lvl-name">Menu</span>
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {/* ───────────── WIN ───────────── */}
            {screen === "win" && (
                <div className="cdg-overlay">
                    <div className="cdg-panel cdg-panel--result">

                        <h2 className="cdg-panel-title">🎉 Maze Escaped!</h2>

                        <div className="result-grid">
                            <div className="result-cell">
                                <span className="rc-label">Coins</span>
                                <span className="rc-val">{g.coins}</span>
                            </div>

                            <div className="result-cell">
                                <span className="rc-label">Steps</span>
                                <span className="rc-val">{g.steps}</span>
                            </div>

                            {cfg.time > 0 && (
                                <div className="result-cell">
                                    <span className="rc-label">Time Left</span>
                                    <span className="rc-val">{g.timeLeft}s</span>
                                </div>
                            )}
                        </div>

                        <div className="cdg-lvl-row">
                            <button
                                className="cdg-lvl-btn cdg-lvl-easy"
                                onClick={() => startGame(levelIdx)}
                            >
                                <span className="lvl-name">Play Again</span>
                            </button>

                            <button
                                className="cdg-lvl-btn cdg-lvl-medium"
                                onClick={() => setScreen("menu")}
                            >
                                <span className="lvl-name">Menu</span>
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {/* ───────────── GAME BOARD ───────────── */}
            {screen === "playing" && (
                <div
                    style={{
                        width: "100%",
                        height: "100%",
                        display: "flex",
                        flexDirection: "column",
                        alignItems: "center",
                        justifyContent: "center",
                        paddingTop: "90px",
                        paddingBottom: "20px",
                        overflow: "hidden",
                    }}
                >

                    {/* Progress */}
                    <div
                        style={{
                            width: Math.min(boardW, window.innerWidth - 24),
                            height: 8,
                            background: "#dde3ef",
                            borderRadius: 999,
                            marginBottom: 12,
                            overflow: "hidden",
                        }}
                    >
                        <div
                            style={{
                                width: `${progress * 100}%`,
                                height: "100%",
                                background: `linear-gradient(90deg, ${cfg.accentBorder}, ${cfg.accent})`,
                                transition: "width 0.3s",
                            }}
                        />
                    </div>

                    {/* Board */}
                    <div
                        style={{
                            position: "relative",
                            width: boardW,
                            height: boardH,
                            maxWidth: "95vw",
                            maxHeight: "75vh",
                            border: `2.5px solid ${cfg.accentBorder}`,
                            borderRadius: 14,
                            overflow: "hidden",
                            boxShadow:
                                `0 6px 32px rgba(0,0,0,0.12),
                             0 0 0 4px ${cfg.accentLight}`,
                            touchAction: "none",
                        }}
                    >
                        <div style={{ position: "relative", width: boardW, height: boardH }}>

                            {/* Tiles */}
                            {g.map.map((row, r) =>
                                row.map((tile, c) => {
                                    const key = `${r}-${c}`;
                                    const base = {
                                        position: "absolute",
                                        left: c * cellSize,
                                        top: r * cellSize,
                                        width: cellSize,
                                        height: cellSize,
                                        display: "flex",
                                        alignItems: "center",
                                        justifyContent: "center",
                                    };

                                    if (tile === WALL) return (
                                        <div
                                            key={key}
                                            style={{
                                                ...base,
                                                background: cfg.wallColor,
                                                boxShadow: "inset 0 0 8px rgba(0,0,0,0.08)",
                                                borderRight: `1px solid ${cfg.wallInner}`,
                                                borderBottom: `1px solid ${cfg.wallInner}`,
                                            }}
                                        />
                                    );

                                    const floor = {
                                        ...base,
                                        background: cfg.floorColor,
                                        borderRight: "1px solid rgba(0,0,0,0.03)",
                                        borderBottom: "1px solid rgba(0,0,0,0.03)",
                                    };

                                    if (tile === COIN) return (
                                        <div key={key} style={floor}>
                                            <span style={{
                                                fontSize: Math.round(cellSize * 0.44),
                                                animation: "cdg-coin-spin 3s linear infinite",
                                            }}>🪙</span>
                                        </div>
                                    );

                                    if (tile === DOOR) {
                                        const open = g.coins >= cfg.coins;

                                        return (
                                            <div
                                                key={key}
                                                style={{
                                                    ...floor,
                                                    ...(open ? { animation: "cdg-glow 1.5s infinite" } : {}),
                                                }}
                                            >
                                                <div style={{ textAlign: "center" }}>
                                                    <div style={{ fontSize: Math.round(cellSize * 0.46) }}>
                                                        {open ? "🔓" : "🚪"}
                                                    </div>
                                                    <div style={{
                                                        fontSize: Math.max(7, Math.round(cellSize * 0.16)),
                                                        fontWeight: 900,
                                                        color: open ? "#2e7d32" : "#e07a00",
                                                    }}>
                                                        {open ? "OPEN" : `${cfg.coins - g.coins}🪙`}
                                                    </div>
                                                </div>
                                            </div>
                                        );
                                    }

                                    return <div key={key} style={floor} />;
                                })
                            )}

                            {/* Player */}
                            <div
                                className="cdg-player"
                                style={{
                                    position: "absolute",
                                    left: g.player.c * cellSize,
                                    top: g.player.r * cellSize,
                                    width: cellSize,
                                    height: cellSize,
                                    display: "flex",
                                    alignItems: "center",
                                    justifyContent: "center",
                                    zIndex: 10,
                                }}
                            >
                                <CatSprite
                                    facing={g.facing}
                                    size={Math.round(cellSize * 0.82)}
                                />
                            </div>

                            {/* Float texts */}
                            {floats.map(f => (
                                <div
                                    key={f.id}
                                    style={{
                                        position: "absolute",
                                        left: f.x,
                                        top: f.y,
                                        fontWeight: 900,
                                        fontSize: 13,
                                        color: f.color,
                                        animation: "cdg-float-up 0.9s forwards",
                                        pointerEvents: "none",
                                        zIndex: 20,
                                    }}
                                >
                                    {f.text}
                                </div>
                            ))}

                            {/* Door locked */}
                            {g.phase === "door-locked" && (
                                <div className="cdg-overlay">
                                    <div className="cdg-panel">
                                        🔒 Need {cfg.coins - g.coins} more coins!
                                    </div>
                                </div>
                            )}

                        </div>
                    </div>
                </div>
            )}
        </div>
    )
};