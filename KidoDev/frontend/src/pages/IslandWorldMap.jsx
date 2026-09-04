import React, { useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTheme } from '../utils/ThemeContext';
// Game node specific assets
import gameLevelNode from '../assets/no_bg_output/game_level_node.png';
import gamePrincessLevelImage from '../assets/no_bg_output/game_princess_level_image.png';

// Removed static level image imports to support dynamic theme switching
import { 
    FaStar, FaLock, FaArrowLeft, FaCheck, 
    FaTrophy, FaLightbulb, FaFlagCheckered, FaGamepad
} from 'react-icons/fa';

/* Precision Forest Map Coordinates (16 Points)
   Slightly congested for the central viewport.
*/
const NODE_COORDINATES = [
    { x: 82.0, y: 77.0 }, 
    { x: 67.0, y: 84.0 }, 
    { x: 50.0, y: 87.0 }, 
    { x: 33.0, y: 84.0 }, 
    { x: 19.0, y: 75.0 }, 
    { x: 17.0, y: 58.0 }, 
    { x: 27.0, y: 47.0 }, 
    { x: 42.0, y: 44.0 }, 
    { x: 58.0, y: 45.0 }, 
    { x: 73.0, y: 49.0 }, 
    { x: 85.0, y: 42.0 }, 
    { x: 83.0, y: 26.0 }, 
    { x: 67.0, y: 19.0 }, 
    { x: 50.0, y: 18.0 }, 
    { x: 34.0, y: 17.0 }, 
    { x: 19.0, y: 18.0 }, 
];

/* Path builder for the 'connected' look */
function buildMapPath(nodes) {
    if (nodes.length < 2) return "";
    let d = `M ${nodes[0].x} ${nodes[0].y}`;
    for (let i = 1; i < nodes.length; i++) {
        const p = nodes[i - 1];
        const c = nodes[i];
        const cpX = (p.x + c.x) / 2;
        const cpY = (p.y + c.y) / 2;
        // Using a Cubic Bezier for smoother, more elastic looking turns
        d += ` C ${p.x} ${cpY}, ${c.x} ${cpY}, ${c.x} ${c.y}`;
    }
    return d;
}

export default function IslandWorldMap({ nodes, completions, selectedLevel, onBack, isUnlocked, getBadge, themeAssets, onPlayGame }) {
    const navigate = useNavigate();
    const { theme } = useTheme();

    const handleNodeClick = (node) => {
        if (node.isGame) {
            if (onPlayGame) {
                onPlayGame(node.gameId);
            }
            return;
        }
        sessionStorage.setItem('selectedLevelId', selectedLevel.id);
        navigate(`/studio/${node.id}`);
    };

    const realNodes = useMemo(() => nodes.filter(n => !n.locked && !n.id.startsWith('ph-')), [nodes]);
    const studyNodes = useMemo(() => realNodes.filter(n => !n.isGame), [realNodes]);
    const finishedNodes = useMemo(() => studyNodes.filter(n => completions[n.id]).length, [studyNodes, completions]);
    
    const obtainedStars = useMemo(() => {
        return studyNodes.reduce((acc, node) => {
            const comp = completions[node.id];
            if (comp) {
                const { stars } = getBadge(comp.badge);
                return acc + stars;
            }
            return acc;
        }, 0);
    }, [studyNodes, completions, getBadge]);

    const totalStars = studyNodes.length * 3;

    return (
        <div className="levels-map-container-seamless">
            
            {/* Back Button */}
            <button onClick={onBack} className="map-btn-back-floating">
                <FaArrowLeft />
            </button>

            {/* Premium Progress HUD - Left Side Stats */}
            <div className="map-stats-left-overlay">
                <div className="map-stat-capsule">
                    <FaStar className="sc-ico sc-ico--stars" style={{ color: '#FFD700' }} />
                    <div className="sc-val">
                        <strong>{obtainedStars}/{totalStars}</strong>
                        <small>Stars</small>
                    </div>
                </div>
                <div className="map-stat-capsule">
                    <FaLightbulb className="sc-ico sc-ico--xp" />
                    <div className="sc-val">
                        <strong>{finishedNodes * 50}</strong>
                        <small>XP Gained</small>
                    </div>
                </div>
            </div>

            {/* Premium Progress HUD - Right Side Stats (Missions) */}
            <div className="map-stats-right-overlay">
                <div className="map-stat-capsule">
                    <FaFlagCheckered className="sc-ico sc-ico--progress" />
                    <div className="sc-val">
                        <strong>{finishedNodes}/{studyNodes.length}</strong>
                        <small>Missions</small>
                    </div>
                </div>
            </div>

            <div className="map-world-seamless">
                <div className="map-scaling-layer">
                    <img src={themeAssets.levels_hero} alt="World Path" className="map-bg-seamless" />
                    
                    {/* The Connecting Path Overlay with Animation */}
                    <svg className="map-connecting-path" viewBox="0 0 100 100" preserveAspectRatio="none">
                        <defs>
                            <linearGradient id="shineGradient" x1="0%" y1="0%" x2="100%" y2="0%">
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

                        {/* Individual Vine Segments with Shiny Magic Swirl */}
                        {NODE_COORDINATES.slice(0, Math.max(0, realNodes.length - 1)).map((p1, idx) => {
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
                                    {/* The "Shiny Line" Sweep */}
                                    <rect 
                                        x={p1.x} 
                                        y={p1.y - 1} 
                                        width={dist} 
                                        height="2" 
                                        fill="url(#shineGradient)"
                                        transform={`rotate(${angle}, ${p1.x}, ${p1.y})`}
                                        style={{ mixBlendMode: 'plus-lighter', opacity: 0.6 }}
                                        pointerEvents="none"
                                    />
                                </g>
                            );
                        })}
                    </svg>
                    
                    <div className="map-hotspots-seamless">
                        {realNodes.map((node, i) => {
                            const coord = NODE_COORDINATES[i];
                            if (!coord) return null;

                            const unlocked = !node.locked && isUnlocked(i);
                            const completionData = completions[node.id];
                            const isDone = !!completionData;
                            const isLast = i === realNodes.length - 1;
                            const { stars } = getBadge(completionData?.badge);
                            const nodeImage = node.isGame 
                                ? (theme === 'princess' ? gamePrincessLevelImage : gameLevelNode)
                                : themeAssets.levels_node;
                            
                            return (
                                <div 
                                    key={node.id} 
                                    className={`map-node-hotspot ${unlocked ? 'unlocked' : 'locked'} ${isDone ? 'mastered' : ''} ${node.isGame ? 'game-hotspot' : ''} ${i % 2 === 0 ? 'node-even' : 'node-odd'}`}
                                    style={{ left: `${coord.x}%`, top: `${coord.y}%` }}
                                    onClick={() => unlocked && handleNodeClick(node)}
                                >
                                    <div className="node-content">
                                        <div className="node-icon">
                                            <img src={nodeImage} alt="Node Base" className="node-base-img" />
                                            <div className="node-status-overlay">
                                                <div className="node-info-group">
                                                    {node.isGame ? (
                                                        <FaGamepad className="node-marker-goal" style={{ color: '#FFD700', fontSize: '1.45rem', filter: 'drop-shadow(0 0 6px rgba(255,215,0,0.8))' }} />
                                                    ) : isLast ? (
                                                        <FaTrophy className={isDone ? "node-marker-done trophy-mastered" : "node-marker-goal"} />
                                                    ) : isDone ? (
                                                        <FaCheck className="node-marker-done" />
                                                    ) : unlocked ? (
                                                        <span className="node-num">{realNodes.slice(0, i + 1).filter(n => !n.isGame).length}</span>
                                                    ) : (
                                                        <FaLock className="node-marker-locked" />
                                                    )}

                                                    {isDone && !node.isGame && (
                                                        <div className="node-stars-inside">
                                                            {[...Array(3)].map((_, si) => (
                                                                <FaStar key={si} className={si < stars ? 'lc-star--lit' : 'lc-star--dim'} />
                                                            ))}
                                                        </div>
                                                    )}
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                </div>
            </div>
        </div>
    );
}
