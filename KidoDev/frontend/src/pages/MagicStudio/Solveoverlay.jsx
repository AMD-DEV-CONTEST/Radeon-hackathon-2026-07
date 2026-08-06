// SolveOverlay.jsx
import React, { useEffect, useState, useRef, useMemo } from "react";

/* ───────────────────────────────────────────────────────────────
   SOLVE OVERLAY — full-screen cat takeover while Auto-Solve runs
   Cats completely cover the screen in a dense grid pattern.
   ─────────────────────────────────────────────────────────────── */

function FlyingCat({ size = 90, uid = "0" }) {
    return (
        <svg viewBox="0 0 100 100" style={{ width: "100%", height: "100%", overflow: "visible" }}>
            <defs>
                <radialGradient id={`shGrad-${uid}`} cx="35%" cy="30%" r="65%">
                    <stop offset="0%" stopColor="#FFE090" />
                    <stop offset="100%" stopColor="#FFA830" />
                </radialGradient>
                <radialGradient id={`sbGrad-${uid}`} cx="45%" cy="38%" r="62%">
                    <stop offset="0%" stopColor="#FFD080" />
                    <stop offset="100%" stopColor="#E87818" />
                </radialGradient>
                <radialGradient id={`seGrad-${uid}`} cx="35%" cy="30%" r="65%">
                    <stop offset="0%" stopColor="#7A4A00" />
                    <stop offset="100%" stopColor="#3A1800" />
                </radialGradient>
            </defs>

            <path
                d="M 30,85 C 10,80 5,60 15,50 C 20,45 28,48 25,56 C 22,64 16,72 32,78"
                fill="none" stroke="#E87818" strokeWidth="7" strokeLinecap="round"
            />

            <ellipse cx="50" cy="78" rx="28" ry="14" fill="#CC6810" />
            <ellipse cx="50" cy="76" rx="26" ry="12" fill={`url(#sbGrad-${uid})`} />

            <g>
                <rect x="36" y="66" width="10" height="20" rx="5" fill="#CC6810" />
                <rect x="37" y="66" width="8" height="19" rx="4" fill="#FFA830" />
                <circle cx="41" cy="85" r="6" fill="#FFF5E0" />
            </g>
            <g>
                <rect x="54" y="66" width="10" height="20" rx="5" fill="#CC6810" />
                <rect x="55" y="66" width="8" height="19" rx="4" fill="#FFA830" />
                <circle cx="59" cy="85" r="6" fill="#FFF5E0" />
            </g>

            <polygon points="26,38 18,14 40,30" fill="#CC6810" />
            <polygon points="28,37 21,18 37,30" fill="#FFC050" />
            <polygon points="74,38 82,14 60,30" fill="#CC6810" />
            <polygon points="72,37 79,18 63,30" fill="#FFA830" />

            <circle cx="50" cy="46" r="26" fill="#CC6810" />
            <circle cx="50" cy="44" r="24" fill={`url(#shGrad-${uid})`} />

            <ellipse cx="50" cy="53" rx="13" ry="9" fill="#FFF5E0" />

            <circle cx="40" cy="42" r="6" fill="#CC6810" />
            <circle cx="40" cy="42" r="5" fill="white" />
            <circle cx="40" cy="42" r="4.2" fill={`url(#seGrad-${uid})`} />
            <circle cx="40" cy="42" r="2.5" fill="#0D0500" />
            <circle cx="38" cy="39" r="2" fill="white" />

            <circle cx="60" cy="42" r="6" fill="#CC6810" />
            <circle cx="60" cy="42" r="5" fill="white" />
            <circle cx="60" cy="42" r="4.2" fill={`url(#seGrad-${uid})`} />
            <circle cx="60" cy="42" r="2.5" fill="#0D0500" />
            <circle cx="58" cy="39" r="2" fill="white" />

            <path d="M 47,51 L 53,51 L 50,54 Z" fill="#FF9999" />
            <path d="M 46,55 Q 50,59 54,55" fill="none" stroke="#CC6810" strokeWidth="1.8" strokeLinecap="round" />
        </svg>
    );
}

/**
 * Full-screen "solving" takeover animation.
 * Cats completely cover the screen in a dense tiled pattern.
 *
 * Props:
 *  - active: boolean — true while solve is in progress (drives entry)
 *  - onExitComplete: () => void — called once the exit animation fully finishes
 *  - message: string — status text shown in the center
 */
export default function SolveOverlay({ active, onExitComplete, message = "Professor Kido is solving it..." }) {
    // phase: 'hidden' | 'entering' | 'visible' | 'leaving'
    const [phase, setPhase] = useState("hidden");
    const wasActive = useRef(false);
    const exitTimer = useRef(null);
    const enterTimer = useRef(null);

    // Generate a dense grid of cats that covers the entire screen
    const cats = useMemo(() => {
        const catSize = 100;
        const overlap = 0.35; // 35% overlap for dense coverage
        const spacing = catSize * (1 - overlap);

        // Calculate grid dimensions for typical screens (over-generate to cover edges)
        const cols = Math.ceil(2000 / spacing);
        const rows = Math.ceil(1200 / spacing);

        const result = [];
        for (let row = 0; row < rows; row++) {
            for (let col = 0; col < cols; col++) {
                // Offset every other row for tighter packing
                const offsetX = (row % 2 === 0) ? 0 : spacing * 0.5;
                const x = col * spacing + offsetX - spacing;
                const y = row * spacing - spacing;

                // Add slight random variation in size for visual interest
                const sizeVariation = 0.85 + Math.random() * 0.3;
                const finalSize = catSize * sizeVariation;

                result.push({
                    x: `${x}px`,
                    y: `${y}px`,
                    size: finalSize,
                    delay: (row * 0.03 + col * 0.02) % 0.8,
                });
            }
        }
        return result;
    }, []);

    useEffect(() => {
        if (active && !wasActive.current) {
            clearTimeout(exitTimer.current);
            setPhase("entering");
            enterTimer.current = setTimeout(() => setPhase("visible"), 50);
            wasActive.current = true;
        }

        if (!active && wasActive.current) {
            setPhase("leaving");
            exitTimer.current = setTimeout(() => {
                setPhase("hidden");
                onExitComplete?.();
            }, 700);
            wasActive.current = false;
        }

        return () => {
            clearTimeout(enterTimer.current);
        };
    }, [active, onExitComplete]);

    useEffect(() => () => {
        clearTimeout(exitTimer.current);
        clearTimeout(enterTimer.current);
    }, []);

    if (phase === "hidden") return null;

    const isVisible = phase === "entering" || phase === "visible";

    return (
        <div
            style={{
                position: "fixed",
                inset: 0,
                zIndex: 99999,
                pointerEvents: "none",
                background: "radial-gradient(circle at center, rgba(255,152,0,0.92), rgba(230,81,0,0.96))",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                opacity: isVisible ? 1 : 0,
                transform: isVisible ? "scale(1)" : "scale(1.15)",
                transition: "opacity 0.7s cubic-bezier(0.4, 0, 0.2, 1), transform 0.7s cubic-bezier(0.4, 0, 0.2, 1)",
                overflow: "hidden",
            }}
        >
            <style>{`
                @keyframes solveCatFloat {
                    0%, 100% { transform: translateY(0) rotate(0deg); }
                    50% { transform: translateY(-8px) rotate(3deg); }
                }
                @keyframes solvePulseText {
                    0%, 100% { opacity: 0.7; }
                    50% { opacity: 1; }
                }
            `}</style>

            {/* Grid of cats covering the entire screen */}
            <div style={{ position: "absolute", inset: 0 }}>
                {cats.map((c, i) => (
                    <div
                        key={i}
                        style={{
                            position: "absolute",
                            left: c.x,
                            top: c.y,
                            width: c.size,
                            height: c.size,
                            opacity: isVisible ? 0.95 : 0,
                            transform: `scale(${isVisible ? 1 : 0.3})`,
                            transition: `opacity 0.4s ease ${c.delay}s, transform 0.4s cubic-bezier(0.34, 1.56, 0.64, 1) ${c.delay}s`,
                            animation: `solveCatFloat ${1.2 + (i % 5) * 0.1}s ease-in-out ${c.delay}s infinite`,
                        }}
                    >
                        <FlyingCat size={c.size} uid={i} />
                    </div>
                ))}
            </div>

            {/* Center message with backdrop for readability */}
            <div
                style={{
                    position: "relative",
                    zIndex: 10,
                    textAlign: "center",
                    opacity: isVisible ? 1 : 0,
                    transition: "opacity 0.5s ease 0.3s",
                }}
            >
                <div
                    style={{
                        background: "rgba(255,255,255,0.95)",
                        borderRadius: 20,
                        padding: "16px 32px",
                        boxShadow: "0 8px 32px rgba(0,0,0,0.3)",
                    }}
                >
                    <div
                        style={{
                            color: "#E65100",
                            fontSize: 22,
                            fontWeight: 900,
                            letterSpacing: 0.5,
                            animation: "solvePulseText 1.6s ease-in-out infinite",
                        }}
                    >
                        {message}
                    </div>
                </div>
            </div>
        </div>
    );
}
