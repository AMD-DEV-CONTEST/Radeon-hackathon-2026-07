import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
    FaStar,
    FaLock,
    FaArrowLeft,
    FaLightbulb,
    FaFlagCheckered,
    FaGamepad,
} from 'react-icons/fa';

import { useTheme } from '../../utils/ThemeContext';
import { useAudio } from './AudioProvider';

import CatchDonut from './CatchDonut';
import TrafficPatrol from './TrafficControl';
import CoinMaze from './CoinMaze';

import './GamesHub.scss';

const NODE_COORDINATES = [
    { x: 50.0, y: 78.0 },
    { x: 67.0, y: 72.0 },
    { x: 80.0, y: 60.0 },
    { x: 78.0, y: 46.0 },
    { x: 65.0, y: 36.0 },
    { x: 50.0, y: 30.0 },
    { x: 35.0, y: 36.0 },
    { x: 22.0, y: 46.0 },
    { x: 20.0, y: 60.0 },
    { x: 33.0, y: 72.0 },
];

const GAME_NODES = [
    { id: 'catch-donut', label: 'Catch the Donut' },
    { id: 'traffic-patrol', label: 'Traffic Patrol' },
    { id: 'coin-maze', label: 'Coin Maze' },
    { id: 'g4', label: 'Game 4' },
    { id: 'g5', label: 'Game 5' },
    { id: 'g6', label: 'Game 6' },
    { id: 'g7', label: 'Game 7' },
    { id: 'g8', label: 'Game 8' },
    { id: 'g9', label: 'Game 9' },
    { id: 'g10', label: 'Game 10' },
];

export default function GamesHub() {
    const navigate = useNavigate();
    const { themeAssets } = useTheme();
    const { pause } = useAudio();

    const [currentGame, setCurrentGame] = useState(null);

    useEffect(() => {
        const role = localStorage.getItem('kido_auth_role');

        if (role !== 'kid') {
            if (role === 'school') navigate('/school-dashboard', { replace: true });
            else if (role === 'parent') navigate('/parent-dashboard', { replace: true });
            else navigate('/auth', { replace: true });
        }
    }, [navigate]);

    // ── Active game renderers ─────────────────────────────────────────────────

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

    // ── Map screen ────────────────────────────────────────────────────────────

    return (
        <div className="levels-map-main-container">
            <div className="levels-map-content">
                <div className="levels-map-container-seamless">

                    {/* BACK BUTTON */}
                    <button
                        onClick={() => navigate('/levels')}
                        className="map-btn-back-floating"
                        type="button"
                    >
                        <FaArrowLeft />
                    </button>

                    {/* Premium Progress HUD - Left Side Stats */}
                    <div className="map-stats-left-overlay">
                        <div className="map-stat-capsule">
                            <FaStar
                                className="sc-ico sc-ico--stars"
                                style={{ color: '#FFD700' }}
                            />
                            <div className="sc-val">
                                <strong>0 / {GAME_NODES.length * 3}</strong>
                                <small>Stars</small>
                            </div>
                        </div>

                        <div className="map-stat-capsule">
                            <FaLightbulb className="sc-ico sc-ico--xp" />
                            <div className="sc-val">
                                <strong>0</strong>
                                <small>XP Gained</small>
                            </div>
                        </div>
                    </div>

                    {/* Premium Progress HUD - Right Side Stats (Missions/Games) */}
                    <div className="map-stats-right-overlay">
                        <div className="map-stat-capsule">
                            <FaFlagCheckered className="sc-ico sc-ico--progress" />
                            <div className="sc-val">
                                <strong>0 / {GAME_NODES.length}</strong>
                                <small>Games</small>
                            </div>
                        </div>
                    </div>

                    {/* WORLD */}
                    <div className="map-world-seamless">
                        <div className="map-scaling-layer">

                            <img
                                src={themeAssets.levels_hero}
                                alt="Games World"
                                className="map-bg-seamless"
                            />

                            {/* PATHS */}
                            <svg
                                className="map-connecting-path"
                                viewBox="0 0 100 100"
                                preserveAspectRatio="none"
                            >
                                <defs>
                                    <linearGradient
                                        id="ghShineGradient"
                                        x1="0%"
                                        y1="0%"
                                        x2="100%"
                                        y2="0%"
                                    >
                                        <stop offset="0%" stopColor="rgba(255,255,255,0)">
                                            <animate attributeName="offset" values="-1; 2" dur="3s" repeatCount="indefinite" />
                                        </stop>
                                        <stop offset="10%" stopColor="rgba(180,255,100,0.8)">
                                            <animate attributeName="offset" values="-0.9; 2.1" dur="3s" repeatCount="indefinite" />
                                        </stop>
                                        <stop offset="20%" stopColor="rgba(255,255,255,0)">
                                            <animate attributeName="offset" values="-0.8; 2.2" dur="3s" repeatCount="indefinite" />
                                        </stop>
                                    </linearGradient>
                                </defs>

                                {NODE_COORDINATES
                                    .slice(0, NODE_COORDINATES.length - 1)
                                    .map((p1, idx) => {
                                        const p2 = NODE_COORDINATES[idx + 1];
                                        if (!p2) return null;
                                        const dx = p2.x - p1.x;
                                        const dy = p2.y - p1.y;
                                        const dist = Math.sqrt(dx * dx + dy * dy);
                                        const angle = Math.atan2(dy, dx) * (180 / Math.PI);

                                        return (
                                            <g key={idx}>
                                                <image
                                                    href={themeAssets.levels_line}
                                                    x={p1.x}
                                                    y={p1.y - 5}
                                                    width={dist}
                                                    height="10"
                                                    transform={`rotate(${angle}, ${p1.x}, ${p1.y})`}
                                                    className="leaf-trail-segment living-vine"
                                                    preserveAspectRatio="none"
                                                />
                                                <rect
                                                    x={p1.x}
                                                    y={p1.y - 1}
                                                    width={dist}
                                                    height="2"
                                                    fill="url(#ghShineGradient)"
                                                    transform={`rotate(${angle}, ${p1.x}, ${p1.y})`}
                                                    style={{ mixBlendMode: 'plus-lighter', opacity: 0.6 }}
                                                    pointerEvents="none"
                                                />
                                            </g>
                                        );
                                    })}
                            </svg>

                            {/* GAME NODES — all unlocked, no lock icons */}
                            <div className="map-hotspots-seamless">
                                {GAME_NODES.map((game, i) => {
                                    const coord = NODE_COORDINATES[i];
                                    if (!coord) return null;
                                    const isFirst = i === 0;

                                    return (
                                        <div
                                            key={game.id}
                                            className={`map-node-hotspot unlocked ${i % 2 === 0 ? 'node-even' : 'node-odd'}`}
                                            style={{
                                                left: `${coord.x}%`,
                                                top: `${coord.y}%`,
                                                cursor: 'pointer',
                                            }}
                                            onClick={() => setCurrentGame(game.id)}
                                        >
                                            <div className="node-content">
                                                <div className="node-icon">
                                                    <img
                                                        src={themeAssets.levels_node}
                                                        alt="Node"
                                                        className="node-base-img"
                                                    />
                                                    <div className="node-status-overlay">
                                                        <div className="node-info-group">
                                                            {isFirst ? (
                                                                <FaGamepad className="gh-node-icon-main" />
                                                            ) : (
                                                                <span className="node-num">{i + 1}</span>
                                                            )}
                                                        </div>
                                                    </div>
                                                </div>
                                                <div className="gh-node-label">{game.label}</div>
                                            </div>
                                        </div>
                                    );
                                })}
                            </div>

                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
}