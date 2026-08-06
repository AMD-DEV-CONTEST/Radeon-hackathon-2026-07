// AgentHintPanel.jsx — Multi-turn AI Agent Panel for Magic Studio
// Replaces the simple one-shot SittingCatHelpButton with a full conversational interface
import React, { useState, useRef, useEffect, useCallback } from 'react';
import { requestHint } from '../../agents/AgentOrchestrator';

// ─── Cat SVG (reused from SittingCatHelpButton) ─────────────────────────────
function CatSvg({ size = 36, isThinking = false }) {
    return (
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"
            style={{ width: size, height: size, overflow: 'visible' }}>
            <style>{`
                .scp-head { transform-box:fill-box; transform-origin:center 40%;
                    animation: ${isThinking ? 'scpThink 0.8s ease-in-out infinite' : 'scpTilt 6s ease-in-out infinite'}; }
                .scp-eyes { transform-box:fill-box; transform-origin:center;
                    animation: scpBlink 3.5s ease-in-out infinite; }
                @keyframes scpTilt { 0%,100%{transform:rotate(0deg)} 25%{transform:rotate(-2deg)} 75%{transform:rotate(2deg)} }
                @keyframes scpThink { 0%,100%{transform:rotate(-8deg) translateY(-2px)} 50%{transform:rotate(8deg) translateY(2px)} }
                @keyframes scpBlink { 0%,88%,92%,100%{transform:scaleY(1)} 90%{transform:scaleY(0.1)} }
            `}</style>
            <defs>
                <radialGradient id="cpHG" cx="35%" cy="30%" r="65%">
                    <stop offset="0%" stopColor="#FFE090" /><stop offset="100%" stopColor="#FFA830" />
                </radialGradient>
            </defs>
            <ellipse cx="50" cy="76" rx="26" ry="12" fill="#E87818" />
            <g className="scp-head">
                <polygon points="26,38 18,14 40,30" fill="#CC6810" />
                <polygon points="28,37 21,18 37,30" fill="#FFC050" />
                <polygon points="74,38 82,14 60,30" fill="#CC6810" />
                <polygon points="72,37 79,18 63,30" fill="#FFA830" />
                <circle cx="50" cy="44" r="24" fill="url(#cpHG)" />
                <ellipse cx="50" cy="53" rx="13" ry="9" fill="#FFF5E0" />
                <g className="scp-eyes">
                    <circle cx="40" cy="42" r="5" fill="white" />
                    <circle cx="40" cy="42" r="3" fill="#0D0500" />
                    <circle cx="38" cy="40" r="1.5" fill="white" />
                    <circle cx="60" cy="42" r="5" fill="white" />
                    <circle cx="60" cy="42" r="3" fill="#0D0500" />
                    <circle cx="58" cy="40" r="1.5" fill="white" />
                </g>
                <ellipse cx="34" cy="48" rx="6" ry="3.5" fill="#FFB8C8" opacity="0.6" />
                <ellipse cx="66" cy="48" rx="6" ry="3.5" fill="#FFB8C8" opacity="0.6" />
                <path d="M 47,51 L 53,51 L 50,54 Z" fill="#FF9999" />
            </g>
        </svg>
    );
}

// ─── Typing dots animation ────────────────────────────────────────────────────
function ThinkingDots() {
    return (
        <span style={{ display: 'inline-flex', gap: 3, alignItems: 'center', padding: '6px 12px' }}>
            {[0, 0.2, 0.4].map((delay, i) => (
                <span key={i} style={{
                    width: 6, height: 6, borderRadius: '50%', background: '#ff9800',
                    animation: `dotBounce 1.2s ease-in-out ${delay}s infinite`,
                }} />
            ))}
            <style>{`@keyframes dotBounce{0%,80%,100%{transform:scale(0.5);opacity:0.5}40%{transform:scale(1);opacity:1}}`}</style>
        </span>
    );
}

const BLOCK_PLACEMENT_MAP = {
    "s_when_flag": { name: "Green Flag", pos: "Top of workspace" },
    "s_when_key": { name: "Key Pressed", pos: "Top of key script" },
    "s_when_clicked": { name: "Sprite Clicked", pos: "Top of click script" },
    "s_broadcast": { name: "Broadcast", pos: "Below event trigger" },
    "s_move": { name: "Move Steps", pos: "Below Green Flag" },
    "s_turn_r": { name: "Turn Right", pos: "Below Move block" },
    "s_turn_l": { name: "Turn Left", pos: "Below Move block" },
    "s_goto": { name: "Go To Position", pos: "Below Green Flag" },
    "s_change_x": { name: "Change X", pos: "Below Green Flag or in loop" },
    "s_change_y": { name: "Change Y", pos: "Below Green Flag or in loop" },
    "s_repeat": { name: "Repeat Loop", pos: "Around motion blocks" },
    "s_forever": { name: "Forever Loop", pos: "Around main script" },
    "s_if": { name: "If Condition", pos: "Inside main loop" },
    "s_if_else": { name: "If-Else", pos: "Inside main loop" },
    "s_wait": { name: "Wait Timer", pos: "Between action blocks" },
    "s_say": { name: "Say Message", pos: "Below motion block" },
    "s_say_time": { name: "Say For Secs", pos: "Below motion block" },
    "s_next_costume": { name: "Next Costume", pos: "Inside loop next to Move" },
    "s_touching": { name: "Touching Sensor", pos: "Inside If condition slot" },
};

function formatBlockPill(blockType) {
    if (!blockType) return null;
    const info = BLOCK_PLACEMENT_MAP[blockType];
    if (info) {
        return `📍 Place ${info.pos} (${info.name}) 🎯`;
    }
    const cleanName = blockType.replace(/^s_/, '').replace(/_/g, ' ');
    return `📍 Snap ${cleanName} into script 🎯`;
}

// ─── Main Panel ───────────────────────────────────────────────────────────────
export default function AgentHintPanel({
    isMobile,
    workspaceBlocks = [],
    getLiveWorkspaceBlocks,
    objective = '',
    lessonId = '',
    onBlockHighlight,
}) {
    const [isOpen, setIsOpen] = useState(false);
    const [messages, setMessages] = useState([]);
    const [isThinking, setIsThinking] = useState(false);
    const [inputValue, setInputValue] = useState('');
    const [lastTrace, setLastTrace] = useState([]);
    const [showTrace, setShowTrace] = useState(false);
    const [gpuInfo, setGpuInfo] = useState(null);
    const messagesEndRef = useRef(null);
    const inputRef = useRef(null);

    const scrollToBottom = () => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    };

    useEffect(() => { scrollToBottom(); }, [messages]);



    const sendHintRequest = useCallback(async (userMessage = null) => {
        if (isThinking) return;
        setIsThinking(true);

        // Add user message to chat if it's a follow-up
        if (userMessage) {
            setMessages(prev => [...prev, { role: 'user', content: userMessage, ts: Date.now() }]);
            setInputValue('');
        }

        const activeBlocks = (typeof getLiveWorkspaceBlocks === 'function' ? getLiveWorkspaceBlocks() : null) || workspaceBlocks || [];

        try {
            const result = await requestHint({
                workspaceBlocks: activeBlocks,
                objective,
                lessonId,
                userMessage,
            });

            const agentMsg = {
                role: 'assistant',
                content: result.hintMessage,
                nextBlock: result.nextBlockType,
                memoryNote: result.agentMemoryNote,
                tokensGenerated: result.tokensGenerated,
                latencyMs: result.latencyMs,
                gpuType: result.gpuType,
                ts: Date.now(),
            };

            setMessages(prev => [...prev, agentMsg]);
            setLastTrace(result.reasoningTrace || []);
            setGpuInfo({ tokens: result.tokensGenerated, latency: result.latencyMs, gpu: result.gpuType });
        } catch (err) {
            setMessages(prev => [...prev, {
                role: 'assistant',
                content: 'I had trouble thinking just now. Try again in a moment!',
                ts: Date.now(),
            }]);
        } finally {
            setIsThinking(false);
        }
    }, [workspaceBlocks, getLiveWorkspaceBlocks, objective, lessonId, isThinking, onBlockHighlight]);

    const GREETING_MESSAGE = {
        role: 'assistant',
        content: "Hi there! I'm KidoBot, your AI coding buddy. How can I help you today? Ask me any question or request a hint!",
        ts: Date.now(),
    };

    const handleOpenAndHint = () => {
        setIsOpen(true);
        if (messages.length === 0) {
            setMessages([{ ...GREETING_MESSAGE, ts: Date.now() }]);
        }
        setTimeout(() => inputRef.current?.focus(), 300);
    };

    const handleSendMessage = (e) => {
        e.preventDefault();
        if (!inputValue.trim() || isThinking) return;
        sendHintRequest(inputValue.trim());
    };

    const size = isMobile ? 38 : 44;

    return (
        <>
            {/* ── Floating Trigger Button (Bottom Right Corner) ── */}
            <div style={{
                position: 'fixed',
                bottom: isMobile ? 16 : 24,
                right: isMobile ? 16 : 24,
                zIndex: 9999,
            }}>
                <button
                    onClick={handleOpenAndHint}
                    data-kido-help-btn
                    title="Need Help? Click to chat with KidoBot"
                    id="agent-hint-btn"
                    style={{
                        background: 'linear-gradient(135deg, #FF9800 0%, #F97316 100%)',
                        border: '2px solid #FFFFFF',
                        borderRadius: 50,
                        cursor: 'pointer',
                        padding: '6px 16px 6px 10px',
                        margin: 0,
                        display: 'flex',
                        alignItems: 'center',
                        gap: 8,
                        transition: 'all 0.25s cubic-bezier(0.34, 1.56, 0.64, 1)',
                        boxShadow: '0 8px 24px rgba(249, 115, 22, 0.35), 0 2px 6px rgba(0, 0, 0, 0.08)',
                    }}
                    onMouseEnter={e => {
                        e.currentTarget.style.transform = 'translateY(-3px) scale(1.05)';
                        e.currentTarget.style.boxShadow = '0 12px 28px rgba(249, 115, 22, 0.5)';
                    }}
                    onMouseLeave={e => {
                        e.currentTarget.style.transform = 'translateY(0) scale(1)';
                        e.currentTarget.style.boxShadow = '0 8px 24px rgba(249, 115, 22, 0.35)';
                    }}
                >
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                        <CatSvg size={32} isThinking={isThinking && isOpen} />
                    </div>
                    <span style={{
                        color: '#FFFFFF',
                        fontWeight: 800,
                        fontSize: 14,
                        fontFamily: 'inherit',
                        letterSpacing: '-0.2px',
                        whiteSpace: 'nowrap',
                    }}>
                        Need Help?
                    </span>
                    {isThinking && isOpen && (
                        <span style={{
                            width: 8, height: 8, borderRadius: '50%',
                            background: '#22C55E', border: '2px solid #FFFFFF',
                            animation: 'pulse 1s ease-in-out infinite',
                        }} />
                    )}
                    <style>{`@keyframes pulse{0%,100%{transform:scale(1);opacity:1}50%{transform:scale(1.3);opacity:0.7}}`}</style>
                </button>
            </div>

            {/* ── Panel Overlay (Light Theme matching Editor UI) ── */}
            {isOpen && (
                <div style={{
                    position: 'fixed',
                    bottom: isMobile ? 70 : 84,
                    right: isMobile ? 16 : 24,
                    width: isMobile ? 'calc(100vw - 32px)' : 380,
                    maxHeight: '70vh',
                    background: '#FFFFFF',
                    border: '1px solid #E2E8F0',
                    borderRadius: 20,
                    boxShadow: '0 20px 50px rgba(15, 23, 42, 0.15), 0 4px 12px rgba(0, 0, 0, 0.05)',
                    display: 'flex',
                    flexDirection: 'column',
                    zIndex: 9999,
                    overflow: 'hidden',
                    animation: 'panelIn 0.25s cubic-bezier(0.34,1.56,0.64,1) forwards',
                }}>
                    <style>{`
                        @keyframes panelIn{from{opacity:0;transform:translateY(12px) scale(0.96)}to{opacity:1;transform:translateY(0) scale(1)}}
                        .agent-msg-bubble{animation:msgIn 0.2s ease forwards}
                        @keyframes msgIn{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:translateY(0)}}
                        .agent-input:focus{outline:none;border-color:#2563EB!important;box-shadow:0 0 0 3px rgba(37,99,235,0.15)!important;}
                        .agent-send-btn:hover{background:linear-gradient(135deg, #EA580C, #D97706)!important;transform:scale(1.05);}
                        .agent-trace-btn:hover{background:#FFEDD5!important;}
                        .agent-close-btn:hover{background:#F1F5F9!important;color:#0F172A!important;}
                    `}</style>

                    {/* Header */}
                    <div style={{
                        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                        padding: '12px 16px',
                        background: 'linear-gradient(135deg, #FFF7ED 0%, #FFEDD5 100%)',
                        borderBottom: '1px solid #FED7AA',
                        flexShrink: 0,
                    }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                            <CatSvg size={30} isThinking={isThinking} />
                            <div>
                                <div style={{ color: '#0F172A', fontWeight: 800, fontSize: 15, letterSpacing: '-0.3px' }}>
                                    KidoBot Agent
                                </div>
                                <div style={{ color: '#C2410C', fontSize: 11, fontWeight: 700 }}>
                                    {isThinking ? 'Reasoning on Qwen (AMD GPU)...' : 'FastAPI via ngrok • Qwen AMD GPU'}
                                </div>
                            </div>
                        </div>
                        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                            {lastTrace.length > 0 && (
                                <button
                                    className="agent-trace-btn"
                                    onClick={() => setShowTrace(v => !v)}
                                    title="View agent reasoning trace"
                                    style={{
                                        background: showTrace ? '#FFEDD5' : '#FFFFFF',
                                        border: '1px solid #FDBA74',
                                        borderRadius: 8,
                                        padding: '4px 10px',
                                        color: '#C2410C',
                                        fontSize: 11,
                                        fontWeight: 700,
                                        cursor: 'pointer',
                                        transition: 'all 0.2s',
                                    }}
                                >
                                    Trace
                                </button>
                            )}
                            <button
                                className="agent-close-btn"
                                onClick={() => setIsOpen(false)}
                                style={{
                                    background: '#FFFFFF', border: '1px solid #FED7AA',
                                    borderRadius: 8, width: 28, height: 28,
                                    color: '#64748B', cursor: 'pointer',
                                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                                    fontSize: 14, fontWeight: 700, transition: 'all 0.2s',
                                }}
                            >✕</button>
                        </div>
                    </div>

                    {/* GPU Badge */}
                    {gpuInfo && (
                        <div style={{
                            padding: '5px 16px',
                            background: '#F8FAFC',
                            display: 'flex', alignItems: 'center', gap: 6,
                            borderBottom: '1px solid #E2E8F0',
                        }}>
                            <div style={{
                                width: 6, height: 6, borderRadius: '50%', background: '#16A34A',
                            }} />
                            <span style={{ color: '#64748B', fontSize: 10, fontWeight: 600, letterSpacing: '0.2px' }}>
                                {gpuInfo.gpu} · FastAPI via ngrok · {gpuInfo.tokens} tokens · {gpuInfo.latency}ms
                            </span>
                        </div>
                    )}

                    {/* Trace panel */}
                    {showTrace && lastTrace.length > 0 && (
                        <div style={{
                            padding: '10px 16px',
                            background: '#F8FAFC',
                            borderBottom: '1px solid #E2E8F0',
                            maxHeight: 110,
                            overflowY: 'auto',
                        }}>
                            <div style={{ color: '#C2410C', fontSize: 10, fontWeight: 800, marginBottom: 4, letterSpacing: '0.5px' }}>
                                REASONING TRACE
                            </div>
                            {lastTrace.map((step, i) => (
                                <div key={i} style={{ color: '#475569', fontSize: 10, lineHeight: 1.6, fontWeight: 500 }}>
                                    {step}
                                </div>
                            ))}
                        </div>
                    )}

                    {/* Messages */}
                    <div style={{ flex: 1, overflowY: 'auto', padding: '14px 16px', display: 'flex', flexDirection: 'column', gap: 12, background: '#FFFFFF' }}>
                        {messages.length === 0 && isThinking && (
                            <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
                                <CatSvg size={26} isThinking />
                                <div style={{
                                    background: '#F1F5F9', border: '1px solid #E2E8F0', borderRadius: '14px 14px 14px 4px',
                                    padding: '8px 12px',
                                }}>
                                    <ThinkingDots />
                                </div>
                            </div>
                        )}
                        {messages.map((msg, idx) => (
                            <div key={idx} className="agent-msg-bubble" style={{
                                display: 'flex',
                                flexDirection: msg.role === 'user' ? 'row-reverse' : 'row',
                                gap: 8,
                                alignItems: 'flex-start',
                            }}>
                                {msg.role === 'assistant' && <CatSvg size={26} />}
                                <div style={{
                                    maxWidth: '82%',
                                    background: msg.role === 'user'
                                        ? 'linear-gradient(135deg, #0284C7, #2563EB)'
                                        : '#F1F5F9',
                                    borderRadius: msg.role === 'user'
                                        ? '14px 14px 4px 14px'
                                        : '14px 14px 14px 4px',
                                    padding: '10px 14px',
                                    border: msg.role === 'assistant' ? '1px solid #E2E8F0' : 'none',
                                    boxShadow: msg.role === 'user' ? '0 4px 12px rgba(37,99,235,0.2)' : '0 2px 6px rgba(0,0,0,0.03)',
                                }}>
                                    {/* Memory note badge */}
                                    {msg.memoryNote && (
                                        <div style={{
                                            background: '#FEF3C7',
                                            border: '1px solid #FDE68A',
                                            borderRadius: 6,
                                            padding: '3px 8px',
                                            marginBottom: 6,
                                            fontSize: 10,
                                            fontWeight: 700,
                                            color: '#B45309',
                                            letterSpacing: '0.3px',
                                        }}>
                                            MEMORY: {msg.memoryNote}
                                        </div>
                                    )}
                                    {/* Engagement Intervention Badge */}
                                    {msg.isEngagementIntervention && (
                                        <div style={{
                                            background: '#EFF6FF',
                                            border: '1px solid #BFDBFE',
                                            borderRadius: 6,
                                            padding: '3px 8px',
                                            marginBottom: 6,
                                            fontSize: 10,
                                            fontWeight: 700,
                                            color: '#1D4ED8',
                                            letterSpacing: '0.3px',
                                        }}>
                                            ⚡ ENGAGEMENT AGENT: {msg.interventionType ? msg.interventionType.toUpperCase() : 'NUDGE'}
                                        </div>
                                    )}
                                    <p style={{
                                        margin: 0,
                                        color: msg.role === 'user' ? '#FFFFFF' : '#1E293B',
                                        fontSize: 13,
                                        lineHeight: 1.6,
                                        fontWeight: 500,
                                    }}>
                                        {msg.content}
                                    </p>
                                    {/* Next block chip */}
                                    {msg.nextBlock && (
                                        <button
                                            onClick={() => onBlockHighlight && onBlockHighlight(msg.nextBlock)}
                                            title="Click to locate this block in toolbox"
                                            style={{
                                                display: 'inline-flex',
                                                alignItems: 'center',
                                                gap: 4,
                                                marginTop: 8,
                                                background: '#DCFCE7',
                                                border: '1px solid #86EFAC',
                                                borderRadius: 8,
                                                padding: '4px 10px',
                                                fontSize: 11,
                                                fontWeight: 700,
                                                color: '#15803D',
                                                fontFamily: 'monospace',
                                                cursor: 'pointer',
                                                transition: 'all 0.15s',
                                            }}
                                            onMouseEnter={e => e.currentTarget.style.background = '#BBF7D0'}
                                            onMouseLeave={e => e.currentTarget.style.background = '#DCFCE7'}
                                        >
                                            {formatBlockPill(msg.nextBlock)}
                                        </button>
                                    )}
                                </div>
                            </div>
                        ))}
                        {isThinking && messages.length > 0 && (
                            <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
                                <CatSvg size={26} isThinking />
                                <div style={{
                                    background: '#F1F5F9',
                                    border: '1px solid #E2E8F0',
                                    borderRadius: '14px 14px 14px 4px',
                                    padding: '8px 12px',
                                }}>
                                    <ThinkingDots />
                                </div>
                            </div>
                        )}
                        <div ref={messagesEndRef} />
                    </div>

                    {/* Quick prompts */}
                    {messages.length > 0 && !isThinking && (
                        <div style={{
                            padding: '8px 14px',
                            display: 'flex', gap: 6, overflowX: 'auto',
                            flexShrink: 0,
                            background: '#F8FAFC',
                            borderTop: '1px solid #E2E8F0',
                        }}>
                            {['Give me a hint', 'What block next?', 'Why?'].map(q => (
                                <button
                                    key={q}
                                    onClick={() => sendHintRequest(q)}
                                    style={{
                                        background: '#EFF6FF',
                                        border: '1px solid #BFDBFE',
                                        borderRadius: 20,
                                        padding: '4px 12px',
                                        color: '#1D4ED8',
                                        fontSize: 11, fontWeight: 700,
                                        cursor: 'pointer', whiteSpace: 'nowrap',
                                        transition: 'all 0.15s',
                                    }}
                                    onMouseEnter={e => e.currentTarget.style.background = '#DBEAFE'}
                                    onMouseLeave={e => e.currentTarget.style.background = '#EFF6FF'}
                                >
                                    {q}
                                </button>
                            ))}
                        </div>
                    )}

                    {/* Input */}
                    <form onSubmit={handleSendMessage} style={{
                        display: 'flex', gap: 8, padding: '12px 14px',
                        borderTop: '1px solid #E2E8F0',
                        background: '#FFFFFF',
                        flexShrink: 0,
                    }}>
                        <input
                            ref={inputRef}
                            className="agent-input"
                            value={inputValue}
                            onChange={e => setInputValue(e.target.value)}
                            placeholder="Ask a follow-up question..."
                            disabled={isThinking}
                            style={{
                                flex: 1,
                                background: '#F8FAFC',
                                border: '1px solid #CBD5E1',
                                borderRadius: 12,
                                padding: '9px 14px',
                                color: '#0F172A',
                                fontSize: 13,
                                fontFamily: 'inherit',
                                transition: 'all 0.2s',
                            }}
                        />
                        <button
                            type="submit"
                            className="agent-send-btn"
                            disabled={!inputValue.trim() || isThinking}
                            style={{
                                background: 'linear-gradient(135deg, #FF9800, #F97316)',
                                border: 'none', borderRadius: 12,
                                width: 38, height: 38,
                                color: '#FFFFFF', cursor: 'pointer',
                                display: 'flex', alignItems: 'center', justifyContent: 'center',
                                fontSize: 16, fontWeight: 700,
                                opacity: (!inputValue.trim() || isThinking) ? 0.4 : 1,
                                transition: 'all 0.2s',
                                boxShadow: '0 4px 12px rgba(249, 115, 22, 0.25)',
                            }}
                        >
                            ↑
                        </button>
                    </form>
                </div>
            )}
        </>
    );
}
