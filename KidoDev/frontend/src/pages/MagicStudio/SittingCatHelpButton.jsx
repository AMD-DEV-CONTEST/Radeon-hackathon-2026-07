// SittingCatHelpButton.jsx
import React from 'react';

/* ───────────────────────────────────────────────────────────────
   SITTING/CHILLING CAT HELP BUTTON
   ─────────────────────────────────────────────────────────────── */
export default function SittingCatHelpButton({ onClick, isMobile }) {
    const size = isMobile ? 38 : 44;
    return (
        <button
            onClick={onClick}
            data-kido-help-btn
            title="AI Hint"
            style={{
                background: 'linear-gradient(135deg, #ff9800, #ffa726)',
                border: '2px solid #fff',
                borderRadius: 8,
                cursor: 'pointer',
                padding: '3px',
                margin: 0,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                position: 'relative',
                width: size,
                height: size,
                transition: 'all 0.2s ease',
                overflow: 'visible',
                boxShadow: '0 4px 10px rgba(255, 152, 0, 0.3)',
            }}
            onMouseEnter={e => {
                e.currentTarget.style.transform = 'scale(1.12) translateY(-2.5px)';
                e.currentTarget.style.boxShadow = '0 6px 14px rgba(255, 152, 0, 0.45)';
            }}
            onMouseLeave={e => {
                e.currentTarget.style.transform = 'scale(1)';
                e.currentTarget.style.boxShadow = '0 4px 10px rgba(255, 152, 0, 0.3)';
            }}
        >
            <svg
                xmlns="http://www.w3.org/2000/svg"
                viewBox="0 0 100 100"
                style={{ width: '100%', height: '100%', overflow: 'visible' }}
            >
                <style>{`
                    .sc-tail {
                        transform-box: fill-box;
                        transform-origin: 20% 80%;
                        animation: scTailWag 2.5s ease-in-out infinite;
                    }
                    .sc-ear-l {
                        transform-box: fill-box;
                        transform-origin: 30% 30%;
                        animation: scEarTwitch 4s ease-in-out infinite;
                    }
                    .sc-ear-r {
                        transform-box: fill-box;
                        transform-origin: 70% 30%;
                        animation: scEarTwitch 4s ease-in-out infinite 0.5s;
                    }
                    .sc-head {
                        transform-box: fill-box;
                        transform-origin: center 40%;
                        animation: scHeadTilt 6s ease-in-out infinite;
                    }
                    .sc-eyes {
                        transform-box: fill-box;
                        transform-origin: center;
                        animation: scEyesBlink 3.5s ease-in-out infinite;
                    }
                    @keyframes scTailWag {
                        0%, 100% { transform: rotate(0deg); }
                        50% { transform: rotate(15deg); }
                    }
                    @keyframes scEarTwitch {
                        0%, 90%, 100% { transform: rotate(0deg); }
                        93% { transform: rotate(-8deg); }
                        96% { transform: rotate(8deg); }
                    }
                    @keyframes scHeadTilt {
                        0%, 100% { transform: rotate(0deg) translateY(0); }
                        25% { transform: rotate(-2deg) translateY(0.5px); }
                        75% { transform: rotate(2deg) translateY(-0.5px); }
                    }
                    @keyframes scEyesBlink {
                        0%, 88%, 92%, 100% { transform: scaleY(1); }
                        90% { transform: scaleY(0.1); }
                    }
                `}</style>

                <defs>
                    <radialGradient id="scHeadGrad" cx="35%" cy="30%" r="65%">
                        <stop offset="0%" stopColor="#FFE090" />
                        <stop offset="100%" stopColor="#FFA830" />
                    </radialGradient>
                    <radialGradient id="scBodyGrad" cx="45%" cy="38%" r="62%">
                        <stop offset="0%" stopColor="#FFD080" />
                        <stop offset="100%" stopColor="#E87818" />
                    </radialGradient>
                    <radialGradient id="scEyeGrad" cx="35%" cy="30%" r="65%">
                        <stop offset="0%" stopColor="#7A4A00" />
                        <stop offset="100%" stopColor="#3A1800" />
                    </radialGradient>
                </defs>

                <path
                    className="sc-tail"
                    d="M 30,85 C 10,80 5,60 15,50 C 20,45 28,48 25,56 C 22,64 16,72 32,78"
                    fill="none"
                    stroke="#E87818"
                    strokeWidth="7"
                    strokeLinecap="round"
                />

                <ellipse cx="50" cy="78" rx="28" ry="14" fill="#CC6810" />
                <ellipse cx="50" cy="76" rx="26" ry="12" fill="url(#scBodyGrad)" />

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

                <g className="sc-head">
                    <polygon className="sc-ear-l" points="26,38 18,14 40,30" fill="#CC6810" />
                    <polygon className="sc-ear-l" points="28,37 21,18 37,30" fill="#FFC050" />
                    <polygon className="sc-ear-l" points="30,36 24,24 35,31" fill="#FFD0CC" />

                    <polygon className="sc-ear-r" points="74,38 82,14 60,30" fill="#CC6810" />
                    <polygon className="sc-ear-r" points="72,37 79,18 63,30" fill="#FFA830" />
                    <polygon className="sc-ear-r" points="70,36 76,24 65,31" fill="#FFD0CC" />

                    <circle cx="50" cy="46" r="26" fill="#CC6810" />
                    <circle cx="50" cy="44" r="24" fill="url(#scHeadGrad)" />

                    <path d="M 40,24 C 40,32 42,38 43,42" fill="none" stroke="#D07010" strokeWidth="2" strokeLinecap="round" opacity="0.4" />
                    <path d="M 50,22 C 50,30 50,36 50,40" fill="none" stroke="#D07010" strokeWidth="2" strokeLinecap="round" opacity="0.4" />
                    <path d="M 60,24 C 60,32 58,38 57,42" fill="none" stroke="#D07010" strokeWidth="2" strokeLinecap="round" opacity="0.4" />

                    <ellipse cx="50" cy="53" rx="13" ry="9" fill="#FFF5E0" />

                    <g className="sc-eyes">
                        <circle cx="40" cy="42" r="6" fill="#CC6810" />
                        <circle cx="40" cy="42" r="5" fill="white" />
                        <circle cx="40" cy="42" r="4.2" fill="url(#scEyeGrad)" />
                        <circle cx="40" cy="42" r="2.5" fill="#0D0500" />
                        <circle cx="38" cy="39" r="2" fill="white" />
                        <circle cx="42" cy="44" r="0.8" fill="white" opacity="0.7" />

                        <circle cx="60" cy="42" r="6" fill="#CC6810" />
                        <circle cx="60" cy="42" r="5" fill="white" />
                        <circle cx="60" cy="42" r="4.2" fill="url(#scEyeGrad)" />
                        <circle cx="60" cy="42" r="2.5" fill="#0D0500" />
                        <circle cx="58" cy="39" r="2" fill="white" />
                        <circle cx="62" cy="44" r="0.8" fill="white" opacity="0.7" />
                    </g>

                    <ellipse cx="34" cy="48" rx="6" ry="3.5" fill="#FFB8C8" opacity="0.6" />
                    <ellipse cx="66" cy="48" rx="6" ry="3.5" fill="#FFB8C8" opacity="0.6" />

                    <path d="M 47,51 L 53,51 L 50,54 Z" fill="#FF9999" />

                    <path d="M 46,55 Q 50,59 54,55" fill="none" stroke="#CC6810" strokeWidth="1.8" strokeLinecap="round" />

                    <line x1="28" y1="52" x2="38" y2="53" stroke="#FFF5E0" strokeWidth="1.2" opacity="0.95" />
                    <line x1="26" y1="55" x2="38" y2="55" stroke="#FFF5E0" strokeWidth="1.2" opacity="0.95" />
                    <line x1="28" y1="58" x2="38" y2="57" stroke="#FFF5E0" strokeWidth="1.2" opacity="0.95" />

                    <line x1="72" y1="52" x2="62" y2="53" stroke="#FFF5E0" strokeWidth="1.2" opacity="0.95" />
                    <line x1="74" y1="55" x2="62" y2="55" stroke="#FFF5E0" strokeWidth="1.2" opacity="0.95" />
                    <line x1="72" y1="58" x2="62" y2="57" stroke="#FFF5E0" strokeWidth="1.2" opacity="0.95" />
                </g>
            </svg>

            <div className="cat-help-tooltip" style={{
                position: 'absolute',
                bottom: -32,
                left: '50%',
                transform: 'translateX(-50%) translateY(-5px)',
                background: '#ff9800',
                color: '#fff',
                fontSize: 10,
                fontWeight: 800,
                padding: '3px 8px',
                borderRadius: 8,
                boxShadow: '0 2px 6px rgba(0,0,0,0.2)',
                border: '1px solid #fff',
                whiteSpace: 'nowrap',
                opacity: 0,
                pointerEvents: 'none',
                transition: 'all 0.2s ease',
            }}>
                AI Hint
            </div>
            <style>{`
                [data-kido-help-btn]:hover .cat-help-tooltip {
                    opacity: 1;
                    transform: translateX(-50%) translateY(0);
                }
            `}</style>
        </button>
    );
}