import React, { useEffect, useState } from 'react';
import { useTheme } from '../../utils/ThemeContext';

const Icon = {
    Star: ({ filled, size = 32 }) => (
        <svg width={size} height={size} viewBox="0 0 24 24" fill={filled ? '#FBBF24' : 'none'}
            stroke={filled ? '#F59E0B' : '#CBD5E1'} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
        </svg>
    ),
    Check: () => (
        <svg width="28" height="28" viewBox="0 0 24 24" fill="none"
            stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="20 6 9 17 4 12" />
        </svg>
    ),
    X: () => (
        <svg width="28" height="28" viewBox="0 0 24 24" fill="none"
            stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
        </svg>
    ),
    Trophy: () => (
        <svg width="36" height="36" viewBox="0 0 24 24" fill="none"
            stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M6 9H3.5a2.5 2.5 0 010-5H6" /><path d="M18 9h2.5a2.5 2.5 0 000-5H18" />
            <path d="M4 22h16" /><path d="M10 22V18" /><path d="M14 22V18" />
            <path d="M6 4h12v8a6 6 0 01-12 0V4z" />
        </svg>
    ),
    AlertTriangle: () => (
        <svg width="36" height="36" viewBox="0 0 24 24" fill="none"
            stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
            <line x1="12" y1="9" x2="12" y2="13" /><line x1="12" y1="17" x2="12.01" y2="17" />
        </svg>
    ),
    Refresh: () => (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none"
            stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="23 4 23 10 17 10" /><polyline points="1 20 1 14 7 14" />
            <path d="M3.51 9a9 9 0 0114.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0020.49 15" />
        </svg>
    ),
    Map: () => (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none"
            stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <polygon points="1 6 1 22 8 18 16 22 23 18 23 2 16 6 8 2 1 6" />
            <line x1="8" y1="2" x2="8" y2="18" /><line x1="16" y1="6" x2="16" y2="22" />
        </svg>
    ),
    Arrow: () => (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none"
            stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <line x1="5" y1="12" x2="19" y2="12" /><polyline points="12 5 19 12 12 19" />
        </svg>
    ),
};

const THEME_PALETTE = {
    barbie: { primary: '#EC4899', light: '#FCE7F3', text: '#831843' },
    forest: { primary: '#10B981', light: '#D1FAE5', text: '#064E3B' },
    sky: { primary: '#0EA5E9', light: '#E0F2FE', text: '#0C4A6E' },
    dark: { primary: '#6366F1', light: '#EEF2FF', text: '#312E81' },
    default: { primary: '#16A34A', light: '#DCFCE7', text: '#14532D' },
};

const FAIL_PALETTE = { primary: '#EF4444', light: '#FEE2E2', text: '#7F1D1D' };

const BLOCK_LABELS = {
    s_move: 'Move steps', s_turn_r: 'Turn right', s_turn_l: 'Turn left',
    s_goto_xy: 'Go to x/y', s_glide_xy: 'Glide', s_bounce: 'Bounce',
    s_say: 'Say', s_say_timed: 'Say for secs', s_think: 'Think',
    s_think_timed: 'Think for secs', s_next_costume: 'Next costume',
    s_switch_costume: 'Switch costume', s_set_size: 'Set size',
    s_change_size: 'Change size', s_change_effect: 'Change effect',
    s_clear_fx: 'Clear effects', s_show: 'Show', s_hide: 'Hide',
    s_play_sound: 'Play sound', s_start_sound: 'Start sound', s_play_note: 'Play note',
    s_set_vol: 'Set volume', s_set_tempo: 'Set tempo',
    s_wait: 'Wait', s_repeat: 'Repeat', s_forever: 'Forever',
    s_if: 'If then', s_if_else: 'If else', s_stop: 'Stop',
    s_create_clone: 'Create clone',
    s_touching_mouse: 'Touching mouse?', s_touching_edge: 'Touching edge?',
    s_key_pressed: 'Key pressed?', s_ask: 'Ask and wait',
    s_set_var: 'Set variable', s_change_var: 'Change variable',
    s_when_flag: 'When flag clicked', s_when_key: 'When key pressed',
    s_when_sprite_clicked: 'When sprite clicked',
    s_pen_down: 'Pen down', s_pen_up: 'Pen up', s_pen_clear: 'Erase all',
    s_pen_stamp: 'Stamp', s_pen_color: 'Set pen color', s_pen_size: 'Set pen size',
};

// ✅ Updated BlockChip with 'helped' variant
const BlockChip = ({ type, variant }) => {
    const label = BLOCK_LABELS[type] || type.replace(/^s_/, '').replace(/_/g, ' ');
    const variantStyles = {
        missing: { bg: '#FEF3C7', border: '#FCD34D', text: '#92400E' },
        wrong: { bg: '#FEE2E2', border: '#FCA5A5', text: '#7F1D1D' },
        helped: { bg: '#DBEAFE', border: '#93C5FD', text: '#1E3A8A' },
    }[variant] || { bg: '#F1F5F9', border: '#CBD5E1', text: '#475569' };

    const prefix = variant === 'missing' ? '⚠ '
        : variant === 'wrong' ? '✕ '
            : variant === 'helped' ? '💡 '
                : '';

    return (
        <span style={{
            display: 'inline-flex', alignItems: 'center', gap: 4,
            background: variantStyles.bg, border: `1px solid ${variantStyles.border}`,
            color: variantStyles.text, borderRadius: 6,
            padding: '3px 10px', fontSize: 12, fontWeight: 600,
            margin: '3px 3px 0 0', fontFamily: 'monospace',
        }}>
            {prefix}{label}
        </span>
    );
};

const StarRow = ({ count }) => (
    <div style={{ display: 'flex', justifyContent: 'center', gap: 8, padding: '4px 0' }}>
        {[1, 2, 3].map(i => (
            <div key={i} style={{
                transform: i === 2 ? 'scale(1.25) translateY(-4px)' : 'scale(1)',
                transition: `transform 0.3s ease ${i * 80}ms`,
            }}>
                <Icon.Star filled={i <= count} size={i === 2 ? 36 : 28} />
            </div>
        ))}
    </div>
);

export function LevelComplete({ data = {}, onClose, onKeepPlaying }) {
    const { theme } = useTheme();
    const [visible, setVisible] = useState(false);
    const [detailsOpen, setDetailsOpen] = useState(false);

    useEffect(() => {
        const t = setTimeout(() => setVisible(true), 80);
        return () => clearTimeout(t);
    }, []);

    const isFailed = data?.failed;
    const isAgentSolved = data?.isAgentSolved;
    const score = Math.max(0, Math.min(100, Number(data?.score) || 0));

    const starsEarned = isFailed || isAgentSolved ? 0
        : score >= 90 ? 3
            : score >= 70 ? 2
                : score >= 40 ? 1
                    : 0;

    const themeKey = (typeof theme === 'string' ? theme : theme?.id || 'forest').toLowerCase();
    const palette = isFailed ? FAIL_PALETTE : (THEME_PALETTE[themeKey] || THEME_PALETTE.default);

    const debugInfo = data?.debugInfo || {};
    const missingList = debugInfo.requiredMissing || [];
    const wrongList = debugInfo.extraBlocks || [];
    const helpedList = debugInfo.helpedBlocks || []; // ✅ NEW

    const hasDebugInfo = !isAgentSolved && (
        missingList.length > 0 || wrongList.length > 0 || helpedList.length > 0
    );

    const RADIUS = 36;
    const CIRCUM = 2 * Math.PI * RADIUS;
    const dashOff = CIRCUM * (1 - (isAgentSolved ? 0 : score) / 100);

    return (
        <div style={styles.backdrop(visible)}>
            <div style={styles.clickZone} onClick={e => e.stopPropagation()} />

            <div
                role="dialog"
                aria-modal="true"
                aria-label={isFailed ? 'Level Failed' : isAgentSolved ? 'Solved by the Agent' : 'Level Complete'}
                style={styles.card(visible, palette.primary)}
            >
                {/* ── status badge ─────────────────────────────── */}
                <div style={styles.badgeRow}>
                    <span style={styles.iconCircle(palette.primary, isFailed, isAgentSolved)}>
                        {isFailed ? <Icon.X /> : isAgentSolved ? <Icon.Star filled={false} size={36} /> : <Icon.Trophy />}
                    </span>
                </div>

                {/* ── headline ─────────────────────────────────── */}
                <div style={styles.headline}>
                    <h2 style={styles.title(palette.primary)}>
                        {isFailed ? 'Level Failed' : isAgentSolved ? 'Solved by the Co-Mentor' : 'Level Complete!'}
                    </h2>
                    <p style={styles.subtitle}>
                        {isFailed
                            ? data?.feedback || 'Fix your blocks and try again.'
                            : isAgentSolved
                                ? 'This level was solved by the Co-Mentor. Solve it yourself to earn stars and XP!'
                                : data?.feedback || 'Great job!'}
                    </p>
                </div>

                {/* ── stars + score ring ───────────────────────── */}
                <div style={styles.metricsRow}>
                    <div style={styles.metricBox}>
                        <span style={styles.metricLabel}>Stars</span>
                        <StarRow count={starsEarned} />
                    </div>

                    <div style={styles.metricBox}>
                        <span style={styles.metricLabel}>Score</span>
                        <div style={{ position: 'relative', width: 88, height: 88 }}>
                            <svg width="88" height="88" viewBox="0 0 88 88">
                                <circle cx="44" cy="44" r={RADIUS}
                                    fill="none" stroke="#E2E8F0" strokeWidth="7" />
                                <circle cx="44" cy="44" r={RADIUS}
                                    fill="none"
                                    stroke={isFailed ? '#EF4444' : isAgentSolved ? '#CBD5E1' : palette.primary}
                                    strokeWidth="7" strokeLinecap="round"
                                    strokeDasharray={CIRCUM}
                                    strokeDashoffset={dashOff}
                                    transform="rotate(-90 44 44)"
                                    style={{ transition: 'stroke-dashoffset 1s ease 0.3s' }} />
                            </svg>
                            <div style={styles.ringInner}>
                                <span style={{
                                    fontSize: isAgentSolved ? 12 : 18,
                                    fontWeight: 700,
                                    color: isFailed ? '#EF4444' : isAgentSolved ? '#64748B' : palette.primary,
                                }}>
                                    {isAgentSolved ? 'No Marks' : score}
                                </span>
                                {!isAgentSolved && (
                                    <span style={{ fontSize: 10, color: '#94A3B8', marginTop: -2 }}>/ 100</span>
                                )}
                            </div>
                        </div>
                    </div>

                    {!isFailed && !isAgentSolved && (
                        <div style={styles.metricBox}>
                            <span style={styles.metricLabel}>XP Earned</span>
                            <div style={{ textAlign: 'center' }}>
                                <span style={{ fontSize: 28, fontWeight: 700, color: palette.primary }}>
                                    +{data?.xpEarned || 0}
                                </span>
                                <span style={{ display: 'block', fontSize: 11, color: '#94A3B8' }}>experience</span>
                            </div>
                        </div>
                    )}
                </div>

                {/* ── debug panel ──────────────────────────────── */}
                {hasDebugInfo && (
                    <div style={styles.debugPanel(palette)}>
                        <button
                            onClick={() => setDetailsOpen(o => !o)}
                            style={styles.debugToggle(palette)}
                        >
                            <span>{detailsOpen ? '▲' : '▼'} Block details</span>
                        </button>

                        {detailsOpen && (
                            <div style={{ marginTop: 10 }}>
                                {/* ✅ Helped blocks section */}
                                {helpedList.length > 0 && (
                                    <div style={{ marginBottom: 8 }}>
                                        <p style={styles.debugHeading('#1E40AF')}>
                                            💡 Placed using hints (no marks awarded)
                                        </p>
                                        <div>
                                            {helpedList.map(t => (
                                                <BlockChip key={t} type={t} variant="helped" />
                                            ))}
                                        </div>
                                    </div>
                                )}

                                {missingList.length > 0 && (
                                    <div style={{ marginBottom: 8 }}>
                                        <p style={styles.debugHeading('#92400E')}>
                                            ⚠ Missing required blocks
                                        </p>
                                        <div>
                                            {missingList.map(t => (
                                                <BlockChip key={t} type={t} variant="missing" />
                                            ))}
                                        </div>
                                    </div>
                                )}

                                {wrongList.length > 0 && (
                                    <div>
                                        <p style={styles.debugHeading('#7F1D1D')}>
                                            ✕ Incorrect blocks used
                                        </p>
                                        <div>
                                            {wrongList.map(t => (
                                                <BlockChip key={t} type={t} variant="wrong" />
                                            ))}
                                        </div>
                                    </div>
                                )}
                            </div>
                        )}
                    </div>
                )}

                {/* ── actions ──────────────────────────────────── */}
                <div style={styles.btnGroup}>
                    {isFailed ? (
                        <>
                            <button onClick={() => window.location.reload()} style={styles.btnPrimary(palette.primary)}>
                                <Icon.Refresh /> Try Again
                            </button>
                            <button onClick={onClose} style={styles.btnSecondary}>
                                <Icon.Map /> Back to Levels
                            </button>
                        </>
                    ) : (
                        <>
                            <button onClick={onClose} style={styles.btnPrimary(palette.primary)}>
                                Next Level <Icon.Arrow />
                            </button>
                            <button onClick={() => window.location.reload()} style={styles.btnSecondary}>
                                <Icon.Refresh /> Replay
                            </button>
                            {onKeepPlaying && (
                                <button onClick={onKeepPlaying} style={styles.btnSecondary}>
                                    <Icon.Star filled={false} size={16} /> Keep Playing
                                </button>
                            )}
                        </>
                    )}
                </div>

                {/* ── badge pills ──────────────────────────────── */}
                {!isFailed && data?.newBadgeLabels?.length > 0 && (
                    <div style={styles.badgePills}>
                        {data.newBadgeLabels.map(b => (
                            <span key={b} style={styles.pill(palette)}>{b}</span>
                        ))}
                    </div>
                )}
            </div>
        </div>
    );
}

const styles = {
    backdrop: (visible) => ({
        position: 'fixed', inset: 0, zIndex: 10000,
        background: 'transparent', backdropFilter: 'none',
        pointerEvents: 'none',
        display: 'flex', justifyContent: 'center', alignItems: 'center',
        padding: '16px', opacity: visible ? 1 : 0, transition: 'opacity 0.35s ease',
    }),
    clickZone: { position: 'absolute', inset: 0, pointerEvents: 'none' },
    card: (visible, accent) => ({
        position: 'relative', background: '#FFFFFF', width: '100%', maxWidth: 440,
        borderRadius: 20, padding: '28px 24px 24px',
        boxShadow: '0 20px 50px rgba(0,0,0,0.15), 0 0 0 1px rgba(0,0,0,0.06)',
        pointerEvents: 'auto',
        transform: visible ? 'scale(1) translateY(0)' : 'scale(0.92) translateY(16px)',
        transition: 'transform 0.4s cubic-bezier(0.34,1.56,0.64,1)',
        display: 'flex', flexDirection: 'column', gap: 20,
    }),
    badgeRow: { display: 'flex', justifyContent: 'center' },
    iconCircle: (color, isFailed, isAgentSolved) => ({
        width: 64, height: 64, borderRadius: '50%',
        background: isFailed ? '#FEE2E2' : isAgentSolved ? '#F1F5F9' : '#ECFDF5',
        color, display: 'flex', alignItems: 'center', justifyContent: 'center',
        border: `2px solid ${color}22`,
    }),
    headline: { textAlign: 'center' },
    title: (color) => ({
        margin: '0 0 6px', fontSize: 22, fontWeight: 700,
        color: '#0F172A', letterSpacing: '-0.3px',
    }),
    subtitle: { margin: 0, fontSize: 14, color: '#64748B', lineHeight: 1.55, fontWeight: 400 },
    metricsRow: {
        display: 'flex', justifyContent: 'space-around', alignItems: 'center',
        gap: 8, padding: '4px 0',
        borderTop: '1px solid #F1F5F9', borderBottom: '1px solid #F1F5F9',
    },
    metricBox: { display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8 },
    metricLabel: {
        fontSize: 11, fontWeight: 600, color: '#94A3B8',
        textTransform: 'uppercase', letterSpacing: '0.6px',
    },
    ringInner: {
        position: 'absolute', inset: 0, display: 'flex',
        flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
    },
    debugPanel: (palette) => ({
        background: '#FFF7ED', border: '1px solid #FED7AA',
        borderRadius: 10, padding: '10px 12px',
    }),
    debugToggle: (palette) => ({
        background: 'none', border: 'none', cursor: 'pointer',
        fontSize: 13, fontWeight: 600, color: '#92400E',
        padding: 0, width: '100%', textAlign: 'left',
        display: 'flex', justifyContent: 'space-between',
    }),
    debugHeading: (color) => ({
        margin: '0 0 5px', fontSize: 12, fontWeight: 700,
        color, textTransform: 'uppercase', letterSpacing: '0.4px',
    }),
    btnGroup: { display: 'flex', flexDirection: 'column', gap: 8 },
    btnPrimary: (color) => ({
        display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
        padding: '13px 20px', borderRadius: 12, background: color, color: '#fff',
        fontWeight: 700, fontSize: 15, border: 'none', cursor: 'pointer',
        letterSpacing: '-0.1px', transition: 'opacity 0.15s',
    }),
    btnSecondary: {
        display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
        padding: '11px 20px', borderRadius: 12, background: '#F8FAFC', color: '#475569',
        fontWeight: 600, fontSize: 14, border: '1px solid #E2E8F0',
        cursor: 'pointer', transition: 'background 0.15s',
    },
    badgePills: { display: 'flex', flexWrap: 'wrap', justifyContent: 'center', gap: 6, paddingTop: 4 },
    pill: (palette) => ({
        display: 'inline-block', padding: '4px 12px', borderRadius: 999,
        background: palette.light, color: palette.text, fontSize: 12, fontWeight: 700,
        border: `1px solid ${palette.primary}33`,
    }),
};