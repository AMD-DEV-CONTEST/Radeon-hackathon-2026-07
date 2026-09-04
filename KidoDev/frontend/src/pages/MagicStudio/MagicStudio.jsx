// MagicStudio.jsx
import React, { useState, useRef, useEffect } from "react";
import {
    createTutorialManager,
    GuidePointer,
    generateTutorResponse,
    solveProject,
    useTypingEffect
} from "./tutorialEngine";

import {
    gradeAndSaveProject,
    addSprite,
    switchBackdrop,
    createVariable,
    createList
} from "./cloud&Assests";
import { S, injectStudioStyles } from "./studioStyle";

export default function MagicStudio({ supabase, lessonId }) {
    // Inject global studio styles
    injectStudioStyles();

    // -------------------------------
    // Workspace / References
    // -------------------------------
    const wsRef = useRef(null);           // Blockly workspace ref
    const spritesRef = useRef([]);        // All sprites
    const variablesRef = useRef({});      // All variables
    const listsRef = useRef({});          // All lists

    // -------------------------------
    // Tutor / Tutorial State
    // -------------------------------
    const [tutorialStep, setTutorialStep] = useState(null);
    const [tutorState, setTutorState] = useState({ active: false, message: "" });
    const [logs, setLogs] = useState([]);
    const [currentBackdrop, setCurrentBackdrop] = useState(null);
    const [gradingResult, setGradingResult] = useState(null);

    const addLog = (msg) => {
        console.log(msg);
        setLogs((prev) => [...prev, msg]);
    };

    // -------------------------------
    // Tutorial Steps
    // -------------------------------
    const tutorialSteps = [
        { lessonId: "move_sprite", message: "Let's move the sprite 10 steps!" },
        { lessonId: "say_hello", message: "Now make the sprite say Hello!" }
    ];
    // const handleGetHelp = async () => {
    //     try {
    //         addLog("🤖 Asking KidoAI for help...");

    //         // 1. Extract Blockly state
    //         const curXml = wsRef.current
    //             ? Blockly.Xml.workspaceToDom(wsRef.current)
    //             : null;

    //         const currentBlocks = curXml
    //             ? Blockly.Xml.domToText(curXml)
    //             : "none";

    //         // 2. Call AI
    //         const result = await getKidoHint({
    //             goal: tutorialSteps[tutorialStep ?? 0]?.message || "Complete the task",
    //             currentBlocks: [currentBlocks], // simple fallback
    //             variables: variablesRef.current,
    //             lists: listsRef.current,
    //             lessonId
    //         });

    //         // 3. Log result
    //         console.log("🤖 AI RESPONSE:", result);
    //         addLog(`AI: ${result?.reason || result?.error || "No response"}`);

    //     } catch (err) {
    //         console.error(err);
    //         addLog("❌ AI request failed");
    //     }
    // };
    const tutorial = useRef(
        createTutorialManager({ steps: tutorialSteps, setCurrentStep: setTutorialStep, addLog })
    ).current;

    // Update tutor message when step changes
    useEffect(() => {
        if (tutorialStep !== null) {
            setTutorState({ active: true, message: tutorialSteps[tutorialStep].message });
        }
    }, [tutorialStep]);

    // Typing effect
    const typedMessage = useTypingEffect(tutorState.message, 20);

    // -------------------------------
    // Auto Solve
    // -------------------------------
    const handleSolve = () => {
        if (tutorialStep === null) return;
        const lesson = tutorialSteps[tutorialStep];
        solveProject({ lessonId: lesson.lessonId, workspaceRef: wsRef, Blockly: window.Blockly, addLog });
    };

    // -------------------------------
    // Run / Save Project
    // -------------------------------
    const handleRun = async () => {
        if (!supabase) {
            addLog("❌ Supabase not configured.");
            return;
        }

        const curXml = wsRef.current ? Blockly.Xml.workspaceToDom(wsRef.current) : null;
        const curXmlText = curXml ? Blockly.Xml.domToText(curXml) : "";

        const result = await gradeAndSaveProject({
            lessonId,
            curXml: curXmlText,
            sprites: spritesRef.current,
            backdrops: [],
            currentBackdrop,
            variables: variablesRef.current,
            lists: listsRef.current,
            supabase,
            getGrade: (lessonId, xml, sprites) => {
                // Dummy grading logic; replace with your actual grader
                return { score: 80, feedback: "Nice work!" };
            },
            addLog,
            setGradingResult
        });

        if (result) {
            addLog(`✅ Project graded: ${result.score}/100`);
        }
    };

    // -------------------------------
    // Example Asset Functions (optional)
    // -------------------------------
    const handleAddSprite = () => addSprite({ spriteData: { name: "MySprite" }, spritesRef, setSprites: (v) => (spritesRef.current = v), addLog });
    const handleCreateVariable = () => createVariable({ name: "score", variablesRef, setVariables: (v) => (variablesRef.current = v), addLog });
    const handleCreateList = () => createList({ name: "items", listsRef, setLists: (v) => (listsRef.current = v), addLog });

    return (
        <div style={S.root}>
            {/* Top Bar */}
            <div style={S.bar}>
                <button onClick={handleRun}>Run & Save</button>
                <button onClick={() => tutorial.next()}>Next Step</button>
                <button onClick={handleSolve}>Auto Solve</button>
                <button onClick={handleAddSprite}>Add Sprite</button>
                <button onClick={handleCreateVariable}>Create Variable</button>
                <button onClick={handleCreateList}>Create List</button>
                
            </div>

            {/* Tutor Message */}
            {tutorState.active && (
                <div
                    style={{
                        position: "absolute",
                        right: 20,
                        top: 80,
                        padding: 10,
                        background: "#fff",
                        border: "1px solid #ccc",
                        borderRadius: 8,
                        maxWidth: 250
                    }}
                >
                    {typedMessage}
                </div>
            )}

            {/* Guide Pointer */}
            {tutorialStep !== null && (
                <GuidePointer
                    x={100 + tutorialStep * 50} // Example position logic
                    y={150}
                />
            )}

            {/* Log Panel */}
            <div style={{ position: "absolute", bottom: 10, left: 10, maxHeight: 200, overflowY: "auto", background: "#f4f4f4", padding: 10, borderRadius: 8 }}>
                {logs.map((log, idx) => (
                    <div key={idx}>{log}</div>
                ))}
            </div>
        </div>
    );
}