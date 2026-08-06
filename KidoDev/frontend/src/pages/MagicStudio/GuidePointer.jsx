import React, { useState, useEffect, useRef } from 'react';

const isElementVisible = (el) => {
    if (!el) return false;
    
    // Check Blockly-specific flyout visibility
    const flyout = el.closest('.blocklyFlyout');
    if (flyout) {
        if (flyout.getAttribute('display') === 'none' || 
            flyout.style.display === 'none' || 
            window.getComputedStyle(flyout).display === 'none') {
            return false;
        }
    }
    
    // Check Blockly toolbox visibility
    const toolbox = el.closest('.blocklyToolboxDiv');
    if (toolbox) {
        if (toolbox.style.display === 'none' || 
            window.getComputedStyle(toolbox).display === 'none') {
            return false;
        }
    }

    let current = el;
    while (current && current !== document.body) {
        const style = window.getComputedStyle(current);
        if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') {
            return false;
        }
        if (current.getAttribute && (current.getAttribute('display') === 'none' || current.getAttribute('visibility') === 'hidden')) {
            return false;
        }
        current = current.parentElement || current.parentNode;
    }
    
    const rect = el.getBoundingClientRect();
    if (rect.width === 0 && rect.height === 0) {
        return false;
    }
    
    // Viewport check (if element is shifted off-screen)
    if (rect.right <= 0 || rect.bottom <= 0 || rect.left >= window.innerWidth || rect.top >= window.innerHeight) {
        return false;
    }
    
    return true;
};

export function GuidePointer({ tutorialStep, lessonId, tutorialSteps }) {
    const [pos, setPos] = useState(null);
    const pulseRef = useRef(null);

    useEffect(() => {
        if (tutorialStep < 0 || !tutorialSteps || !tutorialSteps[tutorialStep]) {
            setPos(null);
            return;
        }

        const findEl = () => {
            const step = tutorialSteps[tutorialStep];
            if (!step || !step.target) { setPos(null); return; }

            let el = null;

            if (step.action === 'pick_block') {
                // For block picking, search in the flyout for the correct block type
                const flyoutBlocks = document.querySelectorAll('.blocklyFlyout .blocklyDraggable');
                for (const block of flyoutBlocks) {
                    // Check if the block has the correct data-type or find by examining
                    const blockSvg = block.closest('[data-type]') || block;
                    if (blockSvg.getAttribute('data-type') === step.blockType) {
                        el = block;
                        break;
                    }
                }
                // Fallback: just point to the first flyout block
                if (!el && flyoutBlocks.length > 0) {
                    el = flyoutBlocks[0];
                }
            } else {
                // For categories and buttons, use the target selector directly
                el = document.querySelector(step.target);
            }

            const isVisible = isElementVisible(el);
            if (isVisible) {
                try {
                    // Force scroll into view if inside scrollable containers like flyout, toolbox, or workspace
                    if (el.closest('.blocklyFlyout') || el.closest('.blocklyToolboxDiv') || el.closest('.blocklyWorkspace')) {
                        el.scrollIntoView({ behavior: 'auto', block: 'nearest', inline: 'nearest' });
                    }
                } catch (e) {
                    console.warn('Scroll into view failed:', e);
                }
                const rect = el.getBoundingClientRect();
                setPos({ x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 });
            } else {
                setPos(null);
            }
        };

        const id = setInterval(findEl, 150);
        findEl(); // Run immediately
        return () => clearInterval(id);
    }, [tutorialStep, tutorialSteps]);

    if (!pos) return null;

    return (
        <>
            {/* Glowing ring behind the pointer */}
            <div style={{
                position: 'fixed',
                left: pos.x - 35,
                top: pos.y - 35,
                width: 70,
                height: 70,
                borderRadius: '50%',
                border: '3px solid #FBBF24',
                background: 'rgba(251, 191, 36, 0.15)',
                boxShadow: '0 0 20px rgba(251, 191, 36, 0.6)',
                animation: 'tutorialPulse 1.5s infinite',
                opacity: 0.8,
                zIndex: 10000,
                pointerEvents: 'none',
                transition: 'all 0.15s ease-out',
            }} />

            {/* Pointing hand */}
            <div style={{
                position: 'fixed',
                left: pos.x,
                top: pos.y,
                transform: 'translate(-20%, -20%) rotate(-45deg)',
                zIndex: 10001,
                pointerEvents: 'none',
                transition: 'all 0.15s ease-out',
            }}>
                <div style={{
                    fontSize: 50,
                    animation: 'handPoint 0.6s infinite alternate',
                    filter: 'drop-shadow(0 0 15px rgba(251, 191, 36, 1)) drop-shadow(0 0 30px rgba(251, 191, 36, 0.5))',
                    userSelect: 'none',
                }}>☝️</div>
            </div>

            {/* Injected CSS animations */}
            <style>{`
                @keyframes handPoint {
                    from { transform: translateY(0px); }
                    to { transform: translateY(-12px); }
                }
                @keyframes tutorialPulse {
                    0% { transform: scale(1); opacity: 0.6; }
                    50% { transform: scale(1.3); opacity: 0.2; }
                    100% { transform: scale(1); opacity: 0.6; }
                }
            `}</style>
        </>
    );
}
