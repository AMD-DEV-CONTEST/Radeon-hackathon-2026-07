export const S = {
    // Vibrant, kid-friendly root background
    root: { 
        display: 'flex', 
        flexDirection: 'column', 
        height: '100vh', 
        background: 'linear-gradient(135deg, #2E7D32, #689F38, #8BC34A, #1B5E20)', 
        fontFamily: 'Inter, sans-serif', 
        overflow: 'hidden' 
    },
    // Bright, high-contrast bar
    bar: { 
        display: 'flex', 
        alignItems: 'center', 
        justifyContent: 'space-between', 
        padding: '10px 20px', 
        background: 'rgba(255, 255, 255, 0.9)', 
        borderBottom: '4px solid #FFD166', 
        flexShrink: 0, 
        boxShadow: '0 4px 20px rgba(0, 0, 0, 0.1)', 
        zIndex: 100 
    },
    logo: { 
        color: '#C8E6C9', 
        fontWeight: 900, 
        fontSize: 22, 
        letterSpacing: '-.5px', 
        textShadow: '0 2px 10px rgba(0,0,0,0.5)' 
    },
    badge: { 
        background: '#4CAF50', 
        color: '#fff', 
        fontSize: 12, 
        fontWeight: 800, 
        borderRadius: 20, 
        padding: '4px 14px', 
        border: '2px solid rgba(255,255,255,0.8)', 
        maxWidth: 200, 
        overflow: 'hidden', 
        textOverflow: 'ellipsis', 
        whiteSpace: 'nowrap',
        boxShadow: '0 4px 10px rgba(0,0,0,0.2)'
    },
    btn: { 
        padding: '8px 16px', 
        borderRadius: 24, 
        fontWeight: 800, 
        fontSize: 13, 
        border: 'none', 
        cursor: 'pointer', 
        transition: 'all 0.2s', 
        display: 'flex', 
        alignItems: 'center', 
        gap: '6px' 
    },
    sel: { 
        padding: '6px 12px', 
        borderRadius: 12, 
        border: '2px solid #4ECDC4', 
        background: '#fff', 
        color: '#1A535C', 
        fontSize: 12, 
        fontWeight: 800, 
        cursor: 'pointer', 
        outline: 'none' 
    },
    side: { 
        width: 260, 
        background: '#F1F8E9', 
        borderRight: '4px solid #8BC34A', 
        display: 'flex', 
        flexDirection: 'column', 
        flexShrink: 0, 
        minHeight: 0 
    },
    stage: { 
        width: '100%', 
        background: '#fff', 
        borderLeft: 'none', 
        display: 'flex', 
        flexDirection: 'column', 
        flexShrink: 0, 
        overflowY: 'auto',
        overflowX: 'hidden'
    },
};

// Global styles for tutor animation, blockly toolbox, and active glowing
const styleTag = document.createElement('style');
styleTag.innerHTML = `
/* Animations */
@keyframes tutorFloat {
    0% { transform: translateY(0px) rotate(0deg); }
    50% { transform: translateY(-10px) rotate(2deg); }
    100% { transform: translateY(0px) rotate(0deg); }
}
@keyframes slideUp {
    0% { transform: translateY(20px); opacity: 0; }
    100% { transform: translateY(0); opacity: 1; }
}
/* Premium Button Hover - only for real HTML buttons, not Blockly SVG */
button:not(.blocklyTreeRow):not([class*="blockly"]) { transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1) !important; }
button:hover:not(:disabled):not([class*="blockly"]) { filter: brightness(1.1); }
button:active:not(:disabled):not([class*="blockly"]) { filter: brightness(0.9); }

@keyframes glowPulse {
    0% { box-shadow: 0 0 10px rgba(34, 197, 94, 0.4), inset 0 0 10px rgba(34, 197, 94, 0.2); border-color: rgba(34, 197, 94, 0.6); }
    50% { box-shadow: 0 0 25px rgba(34, 197, 94, 0.8), inset 0 0 20px rgba(34, 197, 94, 0.4); border-color: rgba(34, 197, 94, 1); }
    100% { box-shadow: 0 0 10px rgba(34, 197, 94, 0.4), inset 0 0 10px rgba(34, 197, 94, 0.2); border-color: rgba(34, 197, 94, 0.6); }
}

/* Blockly Glassmorphism & High Contrast Overrides */
/* Toolbox Container */
.blocklyToolboxDiv {
    background-color: #FFFFFF !important;
    border-right: 1px solid #DDDDDD !important;
    padding-top: 10px;
    width: 85px !important; /* Slightly wider for labels */
    box-shadow: 2px 0 10px rgba(0,0,0,0.05);
}
/* 🔥 AI Tutor Highlight */
// .blocklyHighlightedBlock {
//     animation: glowPulse 1.5s infinite;
//     stroke: #22C55E !important;
//     stroke-width: 4px !important;
// }

/* Pointer arrow */
.ai-pointer {
    position: absolute;
    z-index: 99999;
    font-size: 28px;
    animation: tutorFloat 1s infinite;
    pointer-events: none;
}
    /* 🔥 NEXT BLOCK GLOW */
// .next-block-glow {
//     animation: glowPulse 1.5s infinite;
//     stroke: #22c55e !important;
//     stroke-width: 4px !important;
//     filter: drop-shadow(0 0 10px #22c55e);
// }
@keyframes slowBounce {
    0%   { transform: translateY(0px) rotate(-90deg) scale(1); }
    50%  { transform: translateY(-8px) rotate(-90deg) scale(1.06); }
    100% { transform: translateY(0px) rotate(-90deg) scale(1); }
}
@keyframes blockGlow {
    0% { transform: scale(1); }
    50% { transform: scale(1.08); }
    100% { transform: scale(1); }
}

/* Category Rows */
.blocklyTreeRow {
    display: flex !important;
    flex-direction: column !important;
    align-items: center !important;
    justify-content: center !important;
    height: auto !important;
    margin-bottom: 4px !important;
    padding: 10px 0 !important;
    background: transparent !important;
    border: none !important;
    transition: all 0.2s !important;
}

/* Category Text (High contrast) */
.blocklyTreeLabel {
    color: #575E75 !important;
    font-family: 'Fredoka', sans-serif !important;
    font-size: 10px !important;
    font-weight: 600 !important;
    margin-top: 4px !important;
}

/* Category Icons */
.blocklyTreeIcon {
    width: 32px !important;
    height: 32px !important;
    border-radius: 50% !important;
    display: block !important;
    background-image: none !important;
    border: 1px solid rgba(0,0,0,0.1) !important;
}

/* Specific Category Colors */
.cat-icon-motion .blocklyTreeIcon { background-color: #4C97FF !important; }
.cat-icon-looks .blocklyTreeIcon { background-color: #9966FF !important; }
.cat-icon-sound .blocklyTreeIcon { background-color: #CF63CF !important; }
.cat-icon-events .blocklyTreeIcon { background-color: #FFAB19 !important; }
.cat-icon-control .blocklyTreeIcon { background-color: #FFAB19 !important; }
.cat-icon-sensing .blocklyTreeIcon { background-color: #5CB1D6 !important; }
.cat-icon-operators .blocklyTreeIcon { background-color: #59C059 !important; }
.cat-icon-variables .blocklyTreeIcon { background-color: #FF8C1A !important; }
.cat-icon-lists .blocklyTreeIcon { background-color: #FF8C1A !important; }
.cat-icon-pen .blocklyTreeIcon { background-color: #59C059 !important; }
.cat-icon-myblocks .blocklyTreeIcon { background-color: #FF6680 !important; }

/* Category Icon Symbols (Scratch Style) */
.blocklyTreeIcon::before {
    display: block;
    width: 100%;
    height: 100%;
    line-height: 30px;
    text-align: center;
    font-size: 16px;
    color: white;
}
.cat-icon-motion .blocklyTreeIcon::before { content: "➔"; }
.cat-icon-looks .blocklyTreeIcon::before { content: "👕"; }
.cat-icon-sound .blocklyTreeIcon::before { content: "🔊"; }
.cat-icon-events .blocklyTreeIcon::before { content: "🚩"; }
.cat-icon-control .blocklyTreeIcon::before { content: "🔁"; }
.cat-icon-sensing .blocklyTreeIcon::before { content: "🔍"; }
.cat-icon-operators .blocklyTreeIcon::before { content: "➕"; }
.cat-icon-variables .blocklyTreeIcon::before { content: "📦"; }
.cat-icon-lists .blocklyTreeIcon::before { content: "📋"; }
.cat-icon-pen .blocklyTreeIcon::before { content: "✏️"; }
.cat-icon-myblocks .blocklyTreeIcon::before { content: "🧱"; }

/* Selected State */
.blocklyTreeSelected .blocklyTreeIcon {
    transform: scale(1.1) !important;
    box-shadow: 0 0 15px rgba(0,0,0,0.2) !important;
}
.blocklyTreeSelected.cat-icon-motion .blocklyTreeIcon { box-shadow: 0 0 12px #4C97FF !important; }
.blocklyTreeSelected.cat-icon-looks .blocklyTreeIcon { box-shadow: 0 0 12px #9966FF !important; }
.blocklyTreeSelected.cat-icon-sound .blocklyTreeIcon { box-shadow: 0 0 12px #CF63CF !important; }
.blocklyTreeSelected.cat-icon-events .blocklyTreeIcon { box-shadow: 0 0 12px #FFAB19 !important; }
.blocklyTreeSelected.cat-icon-control .blocklyTreeIcon { box-shadow: 0 0 12px #FFAB19 !important; }
.blocklyTreeSelected.cat-icon-sensing .blocklyTreeIcon { box-shadow: 0 0 12px #5CB1D6 !important; }
.blocklyTreeSelected.cat-icon-operators .blocklyTreeIcon { box-shadow: 0 0 12px #59C059 !important; }
.blocklyTreeSelected.cat-icon-variables .blocklyTreeIcon { box-shadow: 0 0 12px #FF8C1A !important; }
.blocklyTreeSelected.cat-icon-lists .blocklyTreeIcon { box-shadow: 0 0 12px #FF8C1A !important; }
.blocklyTreeSelected.cat-icon-pen .blocklyTreeIcon { box-shadow: 0 0 12px #59C059 !important; }
.blocklyTreeSelected.cat-icon-myblocks .blocklyTreeIcon { box-shadow: 0 0 12px #FF6680 !important; }

/* Block Text contrast - FIXED: Don't force white if renderer handles it */
.blocklyText {
    font-family: 'Fredoka', sans-serif !important;
    font-weight: 600 !important; 
    font-size: 12px !important;
}

/* Flyout Background */
.blocklyFlyoutBackground {
    fill: #F9F9F9 !important;
    fill-opacity: 1 !important;
}


.blocklyFlyout {
    filter: drop-shadow(4px 0px 8px rgba(0,0,0,0.15)) !important;
}

/* Workspace Background - Dynamic based on theme */
.blocklyMainBackground {
    fill: #FFFFFF !important;
}

/* Theme Overrides for Workspace */
.theme-forest .blocklyMainBackground { fill: #F0FDF4 !important; }
.theme-barbie .blocklyMainBackground { fill: #FFF1F2 !important; }
.theme-sky .blocklyMainBackground { fill: #F0F9FF !important; }
.theme-dark .blocklyMainBackground { fill: #0F172A !important; }
.theme-dark .blocklyFlyoutBackground { fill: #1E293B !important; }
.theme-dark .blocklyToolboxDiv { background-color: #020617 !important; border-color: #1E293B !important; }
.theme-dark .blocklyTreeLabel { color: #94A3B8 !important; }


/* Dragging z-index fix */
.blocklyBlockDragSurface {
    z-index: 9999 !important;
}
.blocklyDragging {
    z-index: 9999 !important;
}

/* Zoom controls and trash */
.blocklyTrash, .blocklyZoom {
    display: inline !important;
    visibility: visible !important;
    opacity: 0.9 !important;
    pointer-events: auto !important;
}
.blocklyTrash:hover, .blocklyZoom:hover {
    opacity: 1 !important;
}
.blocklyZoom>image, .blocklyTrash>image, .blocklyTrash .blocklyTrashLid, .blocklyTrash .blocklyTrashBody {
    display: inline !important;
    visibility: visible !important;
    opacity: 0.9 !important;
}
.blocklyZoom>image:hover {
    opacity: 1 !important;
}

/* Scrollbar */
.blocklyScrollbarHandle {
    fill: rgba(148, 163, 184, 0.4) !important;
}

/* Stage Glowing effect */
.stage-live {
    animation: glowPulse 2s infinite;
    border: 2px solid transparent;
}

/* Full Screen Overlay */
.stage-fullscreen-wrap {
    position: fixed !important;
    top: 0; left: 0; right: 0; bottom: 0;
    z-index: 10000;
    background: radial-gradient(circle at center, #1E1B4B 0%, #0F172A 100%);
    display: flex !important;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    width: 100vw !important;
    height: 100vh !important;
    padding: 20px;
    box-sizing: border-box;
}

/* To ensure internal coordinate system (480x360) is preserved while scaling visually */
.stage-fullscreen-canvas {
    height: 85vh !important;
    width: auto !important;
    max-width: calc(85vh * 1.33) !important; /* 4/3 aspect ratio */
    aspect-ratio: 4 / 3 !important;
    image-rendering: pixelated; /* Optional: standard for scratch-like apps if desired, or keep smooth */
    object-fit: contain;
    border: 4px solid rgba(255, 255, 255, 0.1) !important;
    border-radius: 12px;
    box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5), 0 0 40px rgba(99, 102, 241, 0.2);
    background: #000;
}

.exit-fullscreen-btn {
    position: absolute;
    top: 30px;
    right: 30px;
    background: rgba(255, 255, 255, 0.1);
    color: #fff;
    border: 1px solid rgba(255, 255, 255, 0.2);
    padding: 10px 20px;
    border-radius: 30px;
    font-weight: 800;
    cursor: pointer;
    transition: all 0.2s;
    backdrop-filter: blur(10px);
}
.exit-fullscreen-btn:hover {
    background: #EF4444;
    border-color: #EF4444;
    transform: scale(1.05);
    box-shadow: 0 0 20px rgba(239, 68, 68, 0.4);
}
`;
document.head.appendChild(styleTag);
