import * as Blockly from 'blockly';
import { compileAllScripts } from '../../data/scratchBlocks';
import { supabase } from '../../utils/supabaseClient';
import { getGrade } from './tutorialLogic';
import { getProjectBadge } from './ProgressEngine';

/**
 * Hook: run controls with full event dispatching & multi-sprite execution
 */
export function useRunControls({
    running, wsRef, spritesRef, activeSpriteRef, sp, runRef, safeSet,
    setLog, setRunning, answerReady, answerVal, setGradingResult,
    lessonId, addLog, bdrop, varsRef, listsRef, penCanvas, tempoRef,
    clones, execActions, setVars, setLists, setAsking, setAnswer,
    timerStart, setLevelComplete,
    keysDown, mousePosRef, mouseIsDownRef,
    isAgentSolved, setIsAgentSolved, switchBackdrop
}) {
    // ── Keyboard event setup ──
    const keyListenersRef = { current: null };
    const activeScriptsRef = { current: [] }; // track running script promises
    const spriteCompilationsRef = { current: [] };

    const buildContext = (sprite, myBlockDefs) => ({
        sprite,
        vars: varsRef.current,
        lists: listsRef.current,
        mouseX: () => mousePosRef?.current?.x ?? 240,
        mouseY: () => mousePosRef?.current?.y ?? 180,
        mouseIsDown: mouseIsDownRef?.current ?? false,
        keysDown: keysDown?.current || new Set(),
        answerVal, timerStart, tempoRef, runRef,
        myBlockDefs,
    });

    // Broadcast handler: finds and runs all matching s_when_receive scripts
    const broadcastHandlerRef = { current: null };

    const handleRun = async () => {
        if (running || !wsRef.current) return;

        // Save current sprite's XML
        const curXml = Blockly.Xml.domToText(Blockly.Xml.workspaceToDom(wsRef.current));
        const activeItem = spritesRef.current.find(s => s.id === activeSpriteRef.current);
        if (activeItem) activeItem.xml = curXml;

        setGradingResult(null);
        safeSet(() => { setLog(['Running...']); setRunning(true); });
        runRef.current = true;
        answerReady.current = false;
        answerVal.current = '';
        timerStart.current = Date.now();

        const blockCount = curXml.match(/type="s_/g)?.length || 0;

        // ══════════════════════════════════════════════════════════════
        //  STEP A: Compile ALL sprites and execute concurrently
        // ══════════════════════════════════════════════════════════════
        const allPromises = [];

        // Compile each sprite's workspace
        const spriteCompilations = [];
        for (const spr of spritesRef.current) {
            let compiled = null;
            if (spr.id === activeSpriteRef.current) {
                // Active sprite uses current workspace
                compiled = compileAllScripts(wsRef.current);
            } else if (spr.xml) {
                // Other sprites: create temporary workspace to compile their XML
                try {
                    const tempDiv = document.createElement('div');
                    tempDiv.style.display = 'none';
                    document.body.appendChild(tempDiv);
                    const tempWs = Blockly.inject(tempDiv, { toolbox: { kind: 'categoryToolbox', contents: [] } });
                    Blockly.Xml.domToWorkspace(Blockly.utils.xml.textToDom(spr.xml), tempWs);
                    compiled = compileAllScripts(tempWs);
                    tempWs.dispose();
                    document.body.removeChild(tempDiv);
                } catch (e) {
                    // silent failure
                }
            }
            if (compiled) {
                spriteCompilations.push({ sprite: spr, compiled });
            }
        }
        spriteCompilationsRef.current = spriteCompilations;

        // Setup broadcast handler
        broadcastHandlerRef.current = (msg) => {
            const promises = [];
            for (const { sprite, compiled } of spriteCompilations) {
                const received = compiled.scripts.receive.filter(r => r.msg === msg);
                for (const r of received) {
                    const ctx = buildContext(sprite, compiled.myBlockDefs);
                    promises.push(execActions(r.body, null, ctx));
                }
            }
            return Promise.all(promises);
        };

        // Run all green-flag scripts concurrently, per sprite
        for (const { sprite, compiled } of spriteCompilations) {
            for (const body of compiled.scripts.flag) {
                const ctx = buildContext(sprite, compiled.myBlockDefs);
                ctx.broadcastHandler = broadcastHandlerRef.current;
                allPromises.push(execActions(body, null, ctx));
            }
        }

        // ══════════════════════════════════════════════════════════════
        //  STEP B: Setup keyboard event listeners for s_when_key
        // ══════════════════════════════════════════════════════════════
        const keyDownHandler = (e) => {
            if (!runRef.current) return;
            const keyMap = {
                ' ': 'space', Enter: 'enter',
                ArrowUp: 'up', ArrowDown: 'down', ArrowLeft: 'left', ArrowRight: 'right',
            };
            const key = keyMap[e.key] || e.key.toLowerCase();
            keysDown.current.add(key);

            // Fire matching key-press hat scripts
            for (const { sprite, compiled } of spriteCompilations) {
                for (const ks of compiled.scripts.key) {
                    if (ks.key === key || ks.key === 'any') {
                        const ctx = buildContext(sprite, compiled.myBlockDefs);
                        ctx.broadcastHandler = broadcastHandlerRef.current;
                        execActions(ks.body, null, ctx); // fire-and-forget
                    }
                }
            }
        };
        const keyUpHandler = (e) => {
            const keyMap = {
                ' ': 'space', Enter: 'enter',
                ArrowUp: 'up', ArrowDown: 'down', ArrowLeft: 'left', ArrowRight: 'right',
            };
            keysDown.current.delete(keyMap[e.key] || e.key.toLowerCase());
        };

        document.addEventListener('keydown', keyDownHandler);
        document.addEventListener('keyup', keyUpHandler);
        keyListenersRef.current = { keyDownHandler, keyUpHandler };

        // ══════════════════════════════════════════════════════════════
        //  STEP C: Wait for all green-flag scripts, then grade
        // ══════════════════════════════════════════════════════════════
        // Don't await forever — allow scripts to run in background
        // Grade immediately based on the XML
        try {
            const gradeResult = await getGrade(lessonId, curXml, activeItem?.id);
            const { score, xpEarned: attemptXp, feedback, newBadgeLabels } = gradeResult;
            setGradingResult({ score, feedback });

            // Detect session type: kid (localStorage) vs parent (Supabase auth)
            const kidChildId = localStorage.getItem('kido_child_id');
            const { data: { user } } = await supabase.auth.getUser();

            // Calculate a clean badge string for star display on nodes
            // getBadge() in IslandWorldMap checks .includes('Gold') / 'Silver' / 'Bronze'
            const starBadge = score >= 90 ? 'Gold' : score >= 70 ? 'Silver' : score >= 50 ? 'Bronze' : 'Participant';

            if (isAgentSolved) {
                addLog('[System] Project solved by the agent. No XP awarded.');
                setGradingResult({ score: 0, feedback: "Project solved by the agent" });
                if (setLevelComplete) {
                    setLevelComplete({
                        score: 0, feedback: "Project solved by the agent", xpEarned: 0, totalXp: 0,
                        newLevel: 'Agent Solve', levelUp: false,
                        newBadgeLabels: [], isFirstTime: false,
                    });
                }
                return;
            }

            if (kidChildId) {
                // ── KID SESSION: save with child_id + parent_id ──────────────
                addLog('Saving your adventure...');

                // Fetch the child row to get parent_id
                const { data: childRow } = await supabase
                    .from('children')
                    .select('id, parent_id')
                    .eq('id', kidChildId)
                    .maybeSingle();

                if (!childRow) {
                    addLog('Could not find your profile. Score recorded locally.');
                } else {
                    // Fetch previous best for this child+lesson
                    const { data: prevComp } = await supabase
                        .from('lesson_completions')
                        .select('score, xp_earned, badge')
                        .eq('child_id', kidChildId)
                        .eq('lesson_id', lessonId)
                        .maybeSingle();

                    const prevScore = prevComp?.score || 0;
                    const prevXp = prevComp?.xp_earned || 0;
                    const bestScore = Math.max(prevScore, score);
                    const bestXp = Math.max(prevXp, attemptXp);
                    const bestBadge = score >= prevScore ? starBadge : (prevComp?.badge || starBadge);

                    // Upsert on (child_id, lesson_id) — keeps best score
                    await supabase.from('lesson_completions').upsert({
                        child_id: kidChildId,
                        parent_id: childRow.parent_id,
                        lesson_id: lessonId,
                        score: bestScore,
                        xp_earned: bestXp,
                        badge: bestBadge,
                        completed_at: new Date().toISOString(),
                    }, { onConflict: 'child_id,lesson_id' });

                    // Update child's total_xp in children table
                    const { data: allKidLessons } = await supabase
                        .from('lesson_completions')
                        .select('xp_earned')
                        .eq('child_id', kidChildId);
                    const totalXp = allKidLessons?.reduce((s, l) => s + (l.xp_earned || 0), 0) || 0;
                    await supabase.from('children').update({ total_xp: totalXp }).eq('id', kidChildId);

                    addLog(`Saved! Score: ${bestScore}/100 — ${bestBadge} star`);

                    if (setLevelComplete) {
                        setLevelComplete({
                            score, feedback, xpEarned: attemptXp, totalXp,
                            newLevel: 'Explorer', levelUp: false,
                            newBadgeLabels: newBadgeLabels || [], isFirstTime: !prevComp,
                        });
                    }
                }

            } else if (user) {
                // ── PARENT / AUTHENTICATED SESSION ───────────────────────────
                addLog('Saving project to cloud...');
                const projData = {
                    targets: spritesRef.current, backdrops: bdrop,
                    variables: varsRef.current, lists: listsRef.current,
                    lastUpdated: new Date().toISOString(),
                };
                const fileName = `project_${Date.now()}.sb3`;
                const filePath = `${user.id}/${lessonId}/${fileName}`;
                const blob = new Blob([JSON.stringify(projData)], { type: 'application/json' });

                const { error: uploadError } = await supabase.storage
                    .from('projects')
                    .upload(filePath, blob, { contentType: 'application/json', upsert: true });
                if (uploadError) throw uploadError;

                await supabase.from('projects').insert({
                    user_id: user.id,
                    student_name: user.user_metadata?.student_name || 'Explorer',
                    school_name: user.user_metadata?.school_name || 'Kido Dev Academy',
                    lesson_id: lessonId, file_path: filePath, score, feedback,
                    block_count: blockCount, xp_earned: attemptXp,
                    badge: getProjectBadge(score),
                    time_seconds: Math.floor((Date.now() - (timerStart?.current || Date.now())) / 1000),
                });

                addLog(`Kido marked it: ${score}/100`);
                addLog('Adventure saved to your cloud locker!');

                const { data: prevCompletion } = await supabase
                    .from('lesson_completions').select('xp_earned, badge')
                    .eq('user_id', user.id).eq('lesson_id', lessonId).maybeSingle();
                const prevXp = prevCompletion?.xp_earned || 0;
                const updatedXp = Math.max(prevXp, attemptXp);

                await supabase.from('lesson_completions').upsert({
                    user_id: user.id, lesson_id: lessonId, score,
                    xp_earned: updatedXp, badge: starBadge,
                    completed_at: new Date().toISOString(),
                }, { onConflict: 'user_id,lesson_id' });

                const isFirstTime = !prevCompletion;
                const { data: allLessons } = await supabase.from('lesson_completions').select('xp_earned').eq('user_id', user.id);
                const totalXp = allLessons?.reduce((sum, l) => sum + (l.xp_earned || 0), 0) || 0;
                await supabase.from('child_profiles').update({ total_xp: totalXp }).eq('id', user.id);

                if (setLevelComplete) {
                    const prevLevel = user.user_metadata?.level || 'Bronze';
                    const newLevel = calculateLevel(totalXp);
                    setLevelComplete({
                        score, feedback, xpEarned: attemptXp, totalXp, newLevel,
                        levelUp: prevLevel !== newLevel, newBadgeLabels: newBadgeLabels || [], isFirstTime,
                    });
                }

            } else {
                // No session at all
                addLog('Score calculated but not saved — no session found.');
                if (setLevelComplete) {
                    setLevelComplete({ score, feedback, xpEarned: 0, totalXp: 0, newLevel: 'Bronze', levelUp: false, newBadgeLabels: newBadgeLabels || [], isFirstTime: true });
                }
            }
        } catch (err) {
            addLog(`FAILED: ${err?.message || 'Unknown error'}`);
        }
        // Note: scripts continue running in background until Stop is pressed
        addLog('Grading complete! Scripts still running...');
    };

    const handleStop = () => {
        runRef.current = false;
        safeSet(() => { setRunning(false); setAsking(null); });
        if (sp?.current) sp.current.speech = null;
        // Cleanup keyboard listeners
        if (keyListenersRef.current) {
            document.removeEventListener('keydown', keyListenersRef.current.keyDownHandler);
            document.removeEventListener('keyup', keyListenersRef.current.keyUpHandler);
            keyListenersRef.current = null;
        }
        keysDown.current.clear();
        addLog('Stopped');
    };

    const handleReset = () => {
        runRef.current = false;
        setRunning(false); setAsking(null);
        if (keyListenersRef.current) {
            document.removeEventListener('keydown', keyListenersRef.current.keyDownHandler);
            document.removeEventListener('keyup', keyListenersRef.current.keyUpHandler);
            keyListenersRef.current = null;
        }
        keysDown.current.clear();
        if (switchBackdrop) switchBackdrop(0);
        spritesRef.current.forEach(s => Object.assign(s, {
            x: 240, y: 180, dir: 90, size: 100, ghost: 0,
            colorHue: 0, brightness: 0, visible: true,
            speech: null, bubbleType: 'say',
        }));
        varsRef.current = { score: 0, lives: 3, health: 100, speed: 5, timer: 0, level: 1 };
        listsRef.current = { myList: [], highScores: [], items: [] };
        setIsAgentSolved(false);
        const pc = penCanvas.current;
        if (pc) pc.getContext('2d').clearRect(0, 0, pc.width, pc.height);
        tempoRef.current = 120;
        clones.current = [];
        answerReady.current = false; answerVal.current = '';
        setVars({ ...varsRef.current }); setLists({ ...listsRef.current });
        setLog([]); setAnswer(''); setAsking(null);
        if (timerStart) timerStart.current = Date.now();
    };

    const submitAnswer = (answer) => {
        answerVal.current = answer;
        answerReady.current = true;
    };

    const fireSpriteClicked = (spriteId) => {
        // If not running, initialize the environment and compile the scripts on the fly
        if (!runRef.current) {
            // Save current sprite's XML
            const curXml = Blockly.Xml.domToText(Blockly.Xml.workspaceToDom(wsRef.current));
            const activeItem = spritesRef.current.find(s => s.id === activeSpriteRef.current);
            if (activeItem) activeItem.xml = curXml;

            safeSet(() => { setLog(['Running...']); setRunning(true); });
            runRef.current = true;
            answerReady.current = false;
            answerVal.current = '';
            timerStart.current = Date.now();

            const spriteCompilations = [];
            for (const spr of spritesRef.current) {
                let compiled = null;
                if (spr.id === activeSpriteRef.current) {
                    compiled = compileAllScripts(wsRef.current);
                } else if (spr.xml) {
                    try {
                        const tempDiv = document.createElement('div');
                        tempDiv.style.display = 'none';
                        document.body.appendChild(tempDiv);
                        const tempWs = Blockly.inject(tempDiv, { toolbox: { kind: 'categoryToolbox', contents: [] } });
                        Blockly.Xml.domToWorkspace(Blockly.utils.xml.textToDom(spr.xml), tempWs);
                        compiled = compileAllScripts(tempWs);
                        tempWs.dispose();
                        document.body.removeChild(tempDiv);
                    } catch (e) {
                        // ignore
                    }
                }
                if (compiled) {
                    spriteCompilations.push({ sprite: spr, compiled });
                }
            }
            spriteCompilationsRef.current = spriteCompilations;

            broadcastHandlerRef.current = (msg) => {
                const promises = [];
                for (const { sprite, compiled } of spriteCompilations) {
                    const received = compiled.scripts.receive.filter(r => r.msg === msg);
                    for (const r of received) {
                        const ctx = buildContext(sprite, compiled.myBlockDefs);
                        promises.push(execActions(r.body, null, ctx));
                    }
                }
                return Promise.all(promises);
            };
        }

        const comp = spriteCompilationsRef.current.find(c => c.sprite.id === spriteId);
        if (comp && comp.compiled.scripts.clicked.length > 0) {
            for (const body of comp.compiled.scripts.clicked) {
                const ctx = buildContext(comp.sprite, comp.compiled.myBlockDefs);
                ctx.broadcastHandler = broadcastHandlerRef.current;
                execActions(body, null, ctx); // fire-and-forget
            }
        }
    };

    return { handleRun, handleStop, handleReset, submitAnswer, fireSpriteClicked };
}

function calculateLevel(totalXp) {
    if (totalXp >= 200) return 'Platinum';
    if (totalXp >= 100) return 'Gold';
    if (totalXp >= 50) return 'Silver';
    return 'Bronze';
}