// tutorialEngine.js
import React, { useEffect, useState } from "react";

// ============================================================
// TUTOR SOLUTIONS (AUTO-SOLVE XML TEMPLATES)
// ============================================================

export const TUTOR_SOLUTIONS = {
    move_sprite: `
  <xml xmlns="https://developers.google.com/blockly/xml">
    <block type="event_whenflagclicked" x="50" y="50">
      <next>
        <block type="motion_movesteps">
          <field name="STEPS">10</field>
        </block>
      </next>
    </block>
  </xml>
  `,

    say_hello: `
  <xml xmlns="https://developers.google.com/blockly/xml">
    <block type="event_whenflagclicked" x="50" y="50">
      <next>
        <block type="looks_sayforsecs">
          <field name="MESSAGE">Hello!</field>
          <field name="SECS">2</field>
        </block>
      </next>
    </block>
  </xml>
  `
};

// ============================================================
// AUTO SOLVE FUNCTION
// ============================================================

export function solveProject({ lessonId, workspaceRef, Blockly, addLog }) {
    if (!workspaceRef.current) return;

    const solutionXml = TUTOR_SOLUTIONS[lessonId];
    if (!solutionXml) {
        addLog("[System] No solution template available.");
        return;
    }

    try {
        workspaceRef.current.clear();
        const xmlDom = Blockly.Xml.textToDom(solutionXml);
        Blockly.Xml.domToWorkspace(xmlDom, workspaceRef.current);
        addLog("[System] Professor Kido solved it for you!");
    } catch (err) {
        console.error(err);
        addLog("[Error] Failed to auto-solve lesson.");
    }
}

// ============================================================
// TYPING EFFECT HOOK
// ============================================================

export function useTypingEffect(text, speed = 25) {
    const [displayedText, setDisplayedText] = useState("");

    useEffect(() => {
        if (!text) return;

        let i = 0;
        setDisplayedText("");

        const interval = setInterval(() => {
            setDisplayedText(prev => prev + text[i]);
            i++;
            if (i >= text.length) clearInterval(interval);
        }, speed);

        return () => clearInterval(interval);
    }, [text, speed]);

    return displayedText;
}

// ============================================================
// TUTORIAL STEP MANAGER
// ============================================================

export function createTutorialManager({ steps, setCurrentStep, addLog }) {
    let current = 0;

    function start() {
        current = 0;
        setCurrentStep(steps[current]);
        addLog("[System] Tutorial started!");
    }

    function next() {
        if (current < steps.length - 1) {
            current++;
            setCurrentStep(steps[current]);
        } else {
            addLog("[System] Tutorial completed!");
        }
    }

    function reset() {
        current = 0;
        setCurrentStep(null);
    }

    return { start, next, reset };
}

// ============================================================
// GUIDE POINTER COMPONENT
// ============================================================

export function GuidePointer({ x = 0, y = 0 }) {
    return (
        <svg
            width="50"
            height="50"
            viewBox="0 0 24 24"
            fill="none"
            stroke="#4F46E5"
            strokeWidth="2.5"
            strokeLinecap="round"
            strokeLinejoin="round"
            style={{
                position: "absolute",
                left: x,
                top: y,
                pointerEvents: "none",
                animation: "handPoint .8s infinite alternate",
                filter: "drop-shadow(0px 4px 6px rgba(0, 0, 0, 0.15))"
            }}
        >
            <path d="M15 15l-2 5L9 9l11 4-5 2zm0 0l5 5" />
        </svg>
    );
}

// ============================================================
// TUTOR RESPONSE GENERATOR
// ============================================================

export function generateTutorResponse({ lessonId, userXml, expectedKeywords = [] }) {
    if (!userXml) return "Start by dragging blocks into the workspace.";

    for (let keyword of expectedKeywords) {
        if (!userXml.includes(keyword)) {
            return `Try using a "${keyword}" block.`;
        }
    }

    return "Great work! That looks correct!";
}