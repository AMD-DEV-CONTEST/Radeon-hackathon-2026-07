import React, { useEffect, useState, useRef, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { FaBars, FaPlay, FaStop, FaUndo, FaMap, FaFlagCheckered } from 'react-icons/fa';
import lineConnectImg from '../../assets/level_line_connect.jpg';
import { supabase } from '../../utils/supabaseClient';
import * as Blockly from 'blockly';
import { BACKDROPS, getCleanAssetUrl, getActiveBackdrop } from './constants';
import { S } from './styles';
import { useStudioRefs } from './useStudioRefs';
import { useBlocklySetup } from './useBlocklySetup';
import { useActionExecutor } from './useActionExecutor';
import { useRunControls } from './useRunControls';
import { useSpriteControls } from './useSpriteControls';
import { fetchTutorialSteps, getGrade } from './tutorialLogic';
import { SidebarPanel } from './SidebarPanel';
import { StagePanel } from './StagePanel';
import { AssetModal } from './AssetModal';
import { WorkspaceTabs } from './WorkspaceTabs';
import { LevelComplete } from './LevelComplete';
import PromptWorkspace from './PromptWorkspace';
import SpriteLoader from '../../components/Loader/SpriteLoader';
import { useTheme } from '../../utils/ThemeContext';
import { highlightNextBlock } from './blockPointerEngine';
import { BLOCK_DB } from './tutorialEngine';
import { getNextBlockForHelp } from './Next_block_predictor';
import { recordBlockPlaced, resetHelpTracking } from './helpTracker';
import SolveOverlay from './Solveoverlay';
import SittingCatHelpButton from './SittingCatHelpButton';
import SaluteSprite from './SalutingCat';
import AgentHintPanel from './AgentHintPanel';
import { initSession, recordBlockPlacedForEngagement } from '../../agents/memory/AgentMemoryStore';

// Score at/above this is treated as a "best score" and triggers the salute.
// Matches the existing Gold-tier threshold used elsewhere (LevelComplete's
// 3-star cutoff, badge = 'Gold').
const SALUTE_SCORE_THRESHOLD = 90;

export default function MagicStudio() {
    const pointerRef = useRef(null);

    const clearHighlight = () => {
        if (!wsRef.current) return;
        wsRef.current.highlightBlock(null);
    };

    const highlightBlock = (blockType) => {
        if (!wsRef.current) return;
        const blocks = wsRef.current.getAllBlocks(false);
        const target = blocks.find(b => b.type === blockType);
        if (!target) return;
        wsRef.current.highlightBlock(target.id);
        wsRef.current.centerOnBlock(target.id);
        return target;
    };

    const { theme } = useTheme();
    const { lessonId } = useParams();
    const navigate = useNavigate();

    const themeBg = {
        barbie: 'linear-gradient(135deg, #F472B6, #FB7185, #F43F5E)',
        forest: 'linear-gradient(135deg, #059669, #10B981, #34D399)',
        sky: 'linear-gradient(135deg, #0EA5E9, #38BDF8, #7DD3FC)',
        dark: 'linear-gradient(135deg, #1E293B, #0F172A, #020617)',
        default: 'linear-gradient(135deg, #2E7D32, #689F38, #8BC34A, #1B5E20)',
    }[theme?.id?.toLowerCase() || theme?.toLowerCase()] || 'linear-gradient(135deg, #2E7D32, #689F38, #8BC34A, #1B5E20)';

    const [LESSON, setLESSON] = useState({
        title: '', objective: '', steps: [],
        is_prompt_project: false, perfect_prompt: '', prompt_milestones: [],
    });
    const tutorialStepsRef = useRef(null);
    const [levelComplete, setLevelComplete] = useState(null);

    // ── Salute gating ──────────────────────────────────────────────────────
    // pendingLevelComplete holds the result while the salute animation
    // plays; showSalute drives <SaluteSprite>. Once the salute finishes (or
    // immediately, for non-top scores) the data moves into `levelComplete`
    // and the LevelComplete card renders.
    const [pendingLevelComplete, setPendingLevelComplete] = useState(null);
    const [showSalute, setShowSalute] = useState(false);

    const revealLevelComplete = (data) => {
        const qualifiesForSalute =
            !data?.failed && !data?.isAgentSolved &&
            Number(data?.score) >= SALUTE_SCORE_THRESHOLD;

        if (qualifiesForSalute) {
            setPendingLevelComplete(data);
            setShowSalute(true);
        } else {
            setLevelComplete(data);
        }
    };

    const handleSaluteDone = useCallback(() => {
        setShowSalute(false);
        setLevelComplete(pendingLevelComplete);
        setPendingLevelComplete(null);
    }, [pendingLevelComplete]);

    const [isFullScreen, setIsFullScreen] = useState(false);
    const [screenWidth, setScreenWidth] = useState(window.innerWidth);
    const [loading, setLoading] = useState(true);
    const [isSubmitting, setIsSubmitting] = useState(false);

    useEffect(() => {
        const handleResize = () => setScreenWidth(window.innerWidth);
        window.addEventListener('resize', handleResize);
        return () => window.removeEventListener('resize', handleResize);
    }, []);

    const [levelStats, setLevelStats] = useState({
        totalStars: 0, obtainedStars: 0, totalMissions: 0, finishedMissions: 0,
    });

    // ── Refs / state from useStudioRefs ──────────────────────────────────────
    const {
        blocklyDiv, canvasRef, wsRef, runRef, bdropRef, timerStart, dragRef,
        answerReady, answerVal, clones, varsRef, penCanvas, customSprite, tempoRef,
        listsRef, fileInputRef, spritesRef, activeSpriteRef, soundsRef, isMounted,
        keysDown, mousePosRef, mouseIsDownRef,
        assetCache, audioCache, projectBackdropsRef, projectSoundsRef, sp,
        running, setRunning, log, setLog, vars, setVars, lists, setLists,
        bdrop, setBdrop, asking, setAsking, answer, setAnswer, spInfo, setSpInfo,
        panelTab, setPanelTab, libMode, setLibMode, libCategory, setLibCategory,
        searchQuery, setSearchQuery, scratchLibrary, setScratchLibrary,
        scratchBackdrops, setScratchBackdrops, scratchSounds, setScratchSounds,
        loadingLib, setLoadingLib, tutorState, setTutorState, gradingResult,
        setGradingResult, isAgentSolved, setIsAgentSolved, tutorialStep, setTutorialStep,
        sidebarOpen, setSidebarOpen, workspaceTab, setWorkspaceTab,
        _force, safeSet, addLog,
    } = useStudioRefs();

    // Mutable refs to prevent stale closures in Blockly listeners
    const isAgentSolvedRef = useRef(isAgentSolved);
    useEffect(() => { isAgentSolvedRef.current = isAgentSolved; }, [isAgentSolved]);

    const tutorStateRef = useRef(tutorState);
    useEffect(() => { tutorStateRef.current = tutorState; }, [tutorState]);

    // ── Agent session + live workspace block state ───────────────────────────
    const [agentWorkspaceBlocks, setAgentWorkspaceBlocks] = useState([]);
    useEffect(() => {
        const kidChildId = localStorage.getItem('kido_child_id');
        supabase.auth.getUser().then(({ data: { user } }) => {
            const userId = kidChildId || user?.id;
            if (userId) initSession(userId);
        });
    }, [lessonId]);

    // ── Help button ──────────────────────────────────────────────────────────
    const handleGetHelp = async () => {
        try {
            const workspace = wsRef.current;
            if (!workspace) { addLog('❌ Workspace not ready yet. Try again!'); return; }
            setTutorState(prev => ({ ...prev, active: true, message: '🤔 Let me check your project...' }));
            const result = await getNextBlockForHelp(workspace, supabase, lessonId, LESSON.objective || LESSON.title);
            if (!result) {
                addLog('⚠️ No suggestion available right now.');
                setTutorState(prev => ({ ...prev, message: "Keep experimenting! You're doing great." }));
                return;
            }
            setTutorState(prev => ({ ...prev, active: true, message: result.message }));
            addLog(`💡 ${result.message}`);
            if (result.blockType && result.existsInWorkspace && result.blockId) {
                workspace.centerOnBlock(result.blockId);
            } else if (result.blockType) {
                highlightNextBlock(result.blockType, workspace, BLOCK_DB);
            }
            setTimeout(() => setTutorState(prev => ({ ...prev, active: false })), 6000);
        } catch (err) {
            console.error('❌ Help failed:', err);
            addLog('❌ Could not get hint. Check your connection.');
            setTutorState(prev => ({
                ...prev, active: true,
                message: 'Hmm, I had trouble thinking! Try pressing Help again.',
            }));
        }
    };

    // ── Fetch lesson ─────────────────────────────────────────────────────────
    useEffect(() => {
        const fetchLesson = async () => {
            setLoading(true);
            resetHelpTracking();

            try {
                const { data } = await supabase
                    .from('lessons').select('*').eq('id', lessonId).single();

                if (data) {
                    setLESSON({
                        id: data.id, title: data.title, objective: data.objective,
                        steps: data.steps || [], class_level: data.class_level,
                        is_prompt_project: data.is_prompt_project,
                        perfect_prompt: data.perfect_prompt,
                        prompt_milestones: data.prompt_milestones || [],
                        required_blocks: data.required_blocks || [],
                    });

                    const [allLes, allComp] = await Promise.all([
                        supabase.from('lessons').select('id').eq('class_level', data.class_level),
                        supabase.from('lesson_completions')
                            .select('lesson_id,badge')
                            .eq('child_id', localStorage.getItem('kido_child_id') ||
                                (await supabase.auth.getUser()).data.user?.id),
                    ]);

                    if (allLes.data) {
                        const totalMissions = allLes.data.length;
                        const totalStars = totalMissions * 3;
                        const finishedMissions = allComp.data
                            ? allComp.data.filter(c => allLes.data.some(l => l.id === c.lesson_id)).length
                            : 0;
                        const obtainedStars = allComp.data
                            ? allComp.data.reduce((acc, c) => {
                                if (!allLes.data.some(l => l.id === c.lesson_id)) return acc;
                                const stars = c.badge?.includes('Gold') ? 3
                                    : c.badge?.includes('Silver') ? 2 : 1;
                                return acc + stars;
                            }, 0)
                            : 0;
                        setLevelStats({ totalStars, obtainedStars, totalMissions, finishedMissions });
                    }
                } else {
                    setLESSON({ id: lessonId, title: 'Studio', objective: '', steps: [] });
                }

                const steps = await fetchTutorialSteps(lessonId);
                tutorialStepsRef.current = steps;
            } catch (err) {
                console.error('Studio load error:', err);
                setLESSON({ id: lessonId, title: 'Studio', objective: '', steps: [] });
            } finally {
                setLoading(false);
            }
        };
        fetchLesson();
    }, [lessonId]);

    // ── Blockly setup ────────────────────────────────────────────────────────
    useBlocklySetup({
        blocklyDiv, wsRef, isMounted, canvasRef, penCanvas, bdropRef,
        projectBackdropsRef, scratchBackdrops, clones, spritesRef, activeSpriteRef,
        customSprite, varsRef, sp, setSpInfo, assetCache,
        isAgentSolvedRef, tutorStateRef, setIsAgentSolved, addLog,
    });

    // ── Blockly workspace change listener — keeps workspace blocks in sync ────
    useEffect(() => {
        let attempts = 0;
        const MAX_ATTEMPTS = 30;

        const attach = () => {
            const ws = wsRef.current;
            if (!ws) {
                if (attempts++ < MAX_ATTEMPTS) {
                    setTimeout(attach, 100);
                }
                return;
            }

            const syncBlocks = () => {
                if (ws) {
                    setAgentWorkspaceBlocks(ws.getAllBlocks(false).map(b => b.type));
                }
            };

            const onWorkspaceEvent = (event) => {
                if ([Blockly.Events.BLOCK_CREATE, Blockly.Events.BLOCK_DELETE, Blockly.Events.BLOCK_CHANGE].includes(event.type)) {
                    syncBlocks();
                }
                if (event.type === Blockly.Events.BLOCK_CREATE) {
                    const ids = event.ids || (event.blockId ? [event.blockId] : []);
                    for (const id of ids) {
                        const block = ws.getBlockById(id);
                        if (block) {
                            recordBlockPlaced(block.type);
                            recordBlockPlacedForEngagement();
                        }
                    }
                }
            };

            ws.addChangeListener(onWorkspaceEvent);
            syncBlocks(); // Immediate sync on attach
            console.log('[HelpTracker] Workspace change listener attached.');

            return () => {
                ws.removeChangeListener(onWorkspaceEvent);
            };
        };

        const cleanup = attach();
        return () => { if (typeof cleanup === 'function') cleanup(); };
    }, [lessonId]);

    // ── Pre-load local BACKDROPS images through the CORS proxy ───────────────
    useEffect(() => {
        BACKDROPS.forEach(b => {
            if (!b.url) return;
            if (b.img?.complete && b.img.naturalWidth > 0) return;

            const img = new Image();
            img.crossOrigin = 'anonymous';
            img.onload = () => {
                b.img = img;
                if (b.md5ext) assetCache.current[b.md5ext] = img;
                safeSet(() => _force(x => x + 1));
            };
            img.onerror = () => {
                if (!img.src.includes('corsproxy.io')) {
                    img.src = getCleanAssetUrl(b.url);
                }
            };
            img.src = getCleanAssetUrl(b.url);
        });
    }, []); // eslint-disable-line react-hooks/exhaustive-deps

    // ── Fetch Scratch libraries ──────────────────────────────────────────────
    useEffect(() => {
        const fetchLibs = async () => {
            setLoadingLib(true);
            try {
                const [sRes, bRes, sndRes] = await Promise.all([
                    fetch('https://cdn.jsdelivr.net/gh/scratchfoundation/scratch-gui@develop/src/lib/libraries/sprites.json'),
                    fetch('https://cdn.jsdelivr.net/gh/scratchfoundation/scratch-gui@develop/src/lib/libraries/backdrops.json'),
                    fetch('https://cdn.jsdelivr.net/gh/scratchfoundation/scratch-gui@develop/src/lib/libraries/sounds.json'),
                ]);
                const [sData, bData, sndData] = await Promise.all([sRes.json(), bRes.json(), sndRes.json()]);
                setScratchLibrary(sData);
                setScratchBackdrops(bData);
                setScratchSounds(sndData);
            } catch { /* silent */ }
            finally { setLoadingLib(false); }
        };
        fetchLibs();
    }, []);

    // ── Canvas mouse handlers ────────────────────────────────────────────────
    const onMouseDown = e => {
        const cv = canvasRef.current; if (!cv) return;
        const rect = cv.getBoundingClientRect();
        const mx = (e.clientX - rect.left) * (cv.width / rect.width);
        const my = (e.clientY - rect.top) * (cv.height / rect.height);
        mousePosRef.current = { x: mx, y: my };
        mouseIsDownRef.current = true;

        const sprites = [...spritesRef.current].reverse();
        let clickedSprite = null;
        for (const s of sprites) {
            if (s.visible !== false && Math.hypot(mx - s.x, my - s.y) < 44 * ((s.size || 100) / 100)) {
                clickedSprite = s;
                break;
            }
        }
        if (clickedSprite) {
            dragRef.current = { offX: mx - clickedSprite.x, offY: my - clickedSprite.y };
            if (clickedSprite.id !== activeSpriteRef.current && typeof switchSprite === 'function') {
                switchSprite(clickedSprite.id);
            }
            if (typeof fireSpriteClicked === 'function') {
                fireSpriteClicked(clickedSprite.id);
            }
        }
    };

    const onMouseMove = e => {
        const cv = canvasRef.current; if (!cv) return;
        const rect = cv.getBoundingClientRect();
        const mx = (e.clientX - rect.left) * (cv.width / rect.width);
        const my = (e.clientY - rect.top) * (cv.height / rect.height);
        mousePosRef.current = { x: mx, y: my };
        if (dragRef.current) {
            sp.current.x = mx - dragRef.current.offX;
            sp.current.y = my - dragRef.current.offY;
        }
    };

    const onMouseUp = () => { dragRef.current = null; mouseIsDownRef.current = false; };

    // ── switchBackdrop ───────────────────────────────────────────────────────
    const switchBackdrop = (indexOrId) => {
        bdropRef.current = indexOrId;
        setBdrop(indexOrId);
        const bd = getActiveBackdrop(indexOrId, projectBackdropsRef);
        console.log('Backdrop selected:', bd?.name ?? indexOrId);
    };

    // ── Action executor ──────────────────────────────────────────────────────
    const { execActions } = useActionExecutor({
        sp, runRef, addLog, safeSet, setVars, setLists, varsRef, listsRef,
        clones, penCanvas, customSprite, tempoRef, timerStart, answerReady,
        answerVal, setAsking, _force,
        keysDown, mousePosRef, mouseIsDownRef,
        projectSoundsRef,
        switchBackdrop, bdrop, backdrops: BACKDROPS,
        bdropRef, projectBackdropsRef,
    });

    // ── Run controls ─────────────────────────────────────────────────────────
    const {
        handleRun: _handleRunOriginal,
        handleStop,
        handleReset,
        submitAnswer: _submitAnswer,
        fireSpriteClicked,
    } = useRunControls({
        running, wsRef, spritesRef, activeSpriteRef, sp, runRef, safeSet,
        setLog, setRunning, answerReady, answerVal,
        setGradingResult: () => { },
        lessonId, addLog, bdrop, varsRef, listsRef, penCanvas, tempoRef,
        clones, execActions, setVars, setLists, setAsking, setAnswer,
        timerStart,
        setLevelComplete: () => { },
        keysDown, mousePosRef, mouseIsDownRef,
        isAgentSolved, setIsAgentSolved, switchBackdrop,
    });

    const handleRunToggle = () => {
        if (running) {
            addLog('[System] Project stopped.');
            handleStop();
        } else {
            addLog('[System] Running project (test mode — click "Submit Level" to save & complete)');
            _handleRunOriginal();
        }
    };

    // ── Submit / grade ───────────────────────────────────────────────────────
    const handleSubmit = async () => {
        if (isSubmitting || running) return;
        setIsSubmitting(true);
        addLog('[System] Submitting level...');

        try {
            const workspace = wsRef.current;
            if (!workspace) { addLog('[Error] Workspace not ready.'); return; }

            const kidChildId = localStorage.getItem('kido_child_id');
            const { data: { user } } = await supabase.auth.getUser();

            // ── Agent-solved path ─────────────────────────────────────────────
            if (isAgentSolved) {
                addLog('[System] Project solved by the Co-Mentor. Level completed with no marks and no stars.');

                const saveProgress = async (matchField, id) => {
                    const { data: prev } = await supabase
                        .from('lesson_completions')
                        .select('score, xp_earned, badge')
                        .eq(matchField, id).eq('lesson_id', lessonId).maybeSingle();

                    const bestScore = Math.max(prev?.score || 0, 0);
                    const bestXp = Math.max(prev?.xp_earned || 0, 0);
                    const currentBadge = prev?.badge || 'None';

                    await supabase.from('lesson_completions').upsert({
                        [matchField]: id, lesson_id: lessonId,
                        score: bestScore, xp_earned: bestXp, badge: currentBadge,
                        completed_at: new Date().toISOString(),
                    }, { onConflict: `${matchField},lesson_id` });

                    const { data: all } = await supabase
                        .from('lesson_completions').select('xp_earned').eq(matchField, id);
                    const totalXp = all?.reduce((s, l) => s + (l.xp_earned || 0), 0) || 0;
                    return { bestScore, totalXp };
                };

                let totalXp = 0;
                if (kidChildId) {
                    const { data: child } = await supabase
                        .from('children').select('id, parent_id').eq('id', kidChildId).maybeSingle();
                    if (child) {
                        const res = await saveProgress('child_id', kidChildId);
                        totalXp = res.totalXp;
                        await supabase.from('children').update({ total_xp: totalXp }).eq('id', kidChildId);
                    }
                } else if (user) {
                    const res = await saveProgress('user_id', user.id);
                    totalXp = res.totalXp;
                    await supabase.from('child_profiles').update({ total_xp: totalXp }).eq('id', user.id);
                }

                revealLevelComplete({
                    failed: false, isAgentSolved: true, score: 0,
                    feedback: 'Solved by the Co-Mentor', xpEarned: 0, totalXp,
                    newLevel: 'Co-Mentor Solve', levelUp: false,
                    newBadgeLabels: [], isFirstTime: false, debugInfo: {},
                });
                setIsSubmitting(false);
                return;
            }

            // ── Grade ─────────────────────────────────────────────────────────
            const xml = Blockly.Xml.domToText(Blockly.Xml.workspaceToDom(workspace));
            console.log('XML:', xml);

            const result = await getGrade(lessonId, xml);
            console.log('RAW GRADE RESULT:', result);

            let {
                score = 0,
                xpEarned = 0,
                feedback = 'No feedback',
                newBadgeLabels = [],
                debugInfo = {},
            } = result || {};

            score = Math.max(0, Math.min(100, Number(score) || 0));
            xpEarned = Math.max(0, Number(xpEarned) || 0);

            const badge = score >= 90 ? 'Gold' : score >= 70 ? 'Silver' : score >= 40 ? 'Bronze' : 'None';
            const isFailed = score < 40;

            console.log('score:', score, '| badge:', badge, '| failed:', isFailed);

            if (isFailed) {
                revealLevelComplete({
                    failed: true, score, feedback, xpEarned: 0,
                    totalXp: levelStats.obtainedStars, newLevel: 'Failed',
                    levelUp: false, newBadgeLabels, isFirstTime: false, debugInfo,
                });
                return;
            }

            const saveProgress = async (matchField, id) => {
                const { data: prev } = await supabase
                    .from('lesson_completions')
                    .select('score, xp_earned')
                    .eq(matchField, id).eq('lesson_id', lessonId).maybeSingle();

                const bestScore = Math.max(prev?.score || 0, score);
                const bestXp = Math.max(prev?.xp_earned || 0, xpEarned);

                await supabase.from('lesson_completions').upsert({
                    [matchField]: id, lesson_id: lessonId,
                    score: bestScore, xp_earned: bestXp, badge,
                    completed_at: new Date().toISOString(),
                }, { onConflict: `${matchField},lesson_id` });

                const { data: all } = await supabase
                    .from('lesson_completions').select('xp_earned').eq(matchField, id);
                const totalXp = all?.reduce((s, l) => s + (l.xp_earned || 0), 0) || 0;
                return { bestScore, totalXp };
            };

            let totalXp = 0;
            let bestScore = score;

            if (kidChildId) {
                const { data: child } = await supabase
                    .from('children').select('id, parent_id').eq('id', kidChildId).maybeSingle();
                if (child) {
                    const res = await saveProgress('child_id', kidChildId);
                    bestScore = res.bestScore; totalXp = res.totalXp;
                    await supabase.from('children').update({ total_xp: totalXp }).eq('id', kidChildId);
                }
            } else if (user) {
                const res = await saveProgress('user_id', user.id);
                bestScore = res.bestScore; totalXp = res.totalXp;
                await supabase.from('child_profiles').update({ total_xp: totalXp }).eq('id', user.id);
            }

            revealLevelComplete({
                failed: false, score: bestScore, feedback, xpEarned, totalXp,
                newLevel: badge, levelUp: false,
                newBadgeLabels: newBadgeLabels?.length ? newBadgeLabels : [badge],
                isFirstTime: true, debugInfo,
            });

        } catch (err) {
            console.error('[Error] Submit failed:', err);
            revealLevelComplete({
                failed: true, score: 0,
                feedback: 'Something went wrong while submitting. Please try again.',
                xpEarned: 0, totalXp: 0, newLevel: 'Failed',
                levelUp: false, newBadgeLabels: [], isFirstTime: false, debugInfo: {},
            });
        } finally {
            setIsSubmitting(false);
        }
    };

    const submitAnswer = () => { _submitAnswer(answer); setAnswer(''); };

    // ── Sprite controls ──────────────────────────────────────────────────────
    const {
        createNewSprite, switchSprite, deleteSprite,
        handleSpriteUpload, clearCustomSprite, solveProject,
    } = useSpriteControls({
        spritesRef, activeSpriteRef, wsRef, sp, bdrop, bdropRef, setBdrop,
        penCanvas, customSprite, addLog, _force, setTutorState, tutorState,
        fileInputRef, setWorkspaceTab, setIsAgentSolved,
    });

    // ── Reset help tracking when the workspace is manually cleared/reset ─────
    const handleResetWithTracking = () => {
        resetHelpTracking();
        handleReset();
    };

    // ── Tutorial ─────────────────────────────────────────────────────────────
    const startTutorial = () => {
        setTutorialStep(0);
        if (window.innerWidth < 900) setSidebarOpen(false);
        setTutorState({
            active: true,
            message: "I'll guide you through this project! Just follow my pointer.",
            solving: false,
        });
    };

    useEffect(() => {
        if (workspaceTab === 'code' && wsRef.current) {
            setTimeout(() => { if (wsRef.current) Blockly.svgResize(wsRef.current); }, 50);
        }
    }, [workspaceTab]);

    useEffect(() => {
        if (tutorialStep < 0 || !wsRef.current) return;
        const steps = tutorialStepsRef.current;
        if (!steps || tutorialStep >= steps.length) {
            if (tutorialStep >= (steps?.length || 0)) {
                setTutorialStep(-1);
                setTutorState(p => ({
                    ...p,
                    message: "Tutorial complete! You're a coding superstar now!",
                    active: true,
                }));
                setTimeout(() => setTutorState(p => ({ ...p, active: false })), 4000);
            }
            return;
        }
        const step = steps[tutorialStep];
        setTutorState(p => ({ ...p, message: step.msg, active: true }));

        const checkHandler = () => {
            const xml = Blockly.Xml.domToText(Blockly.Xml.workspaceToDom(wsRef.current));
            switch (step.checkType) {
                case 'xml_contains':
                    if (step.checkValue && xml.includes(step.checkValue))
                        setTutorialStep(s => s + 1);
                    break;
                case 'category_selected': {
                    const selectedRow = document.querySelector('.blocklyTreeRow.blocklyTreeSelected');
                    if (selectedRow?.getAttribute('aria-label')?.includes(step.checkValue))
                        setTutorialStep(s => s + 1);
                    break;
                }
                case 'manual':
                default:
                    break;
            }
        };

        const checkTimer = setInterval(checkHandler, 300);
        wsRef.current.addChangeListener(checkHandler);
        return () => {
            clearInterval(checkTimer);
            wsRef.current?.removeChangeListener(checkHandler);
        };
    }, [tutorialStep, lessonId]);

    useEffect(() => {
        if (wsRef.current) setTimeout(() => Blockly.svgResize(wsRef.current), 100);
    }, [sidebarOpen]);

    const isMobile = screenWidth < 900;
    const themeId = (typeof theme === 'string' ? theme : theme?.id || 'forest').toLowerCase();

    // ── Prompt project completion ─────────────────────────────────────────────
    const handlePromptComplete = async () => {
        if (isAgentSolved) {
            revealLevelComplete({
                score: 0, feedback: 'Project solved by the Co-Mentor', xpEarned: 0,
                totalXp: levelStats.obtainedStars, newLevel: 'Co-Mentor Solve',
                levelUp: false, newBadgeLabels: [], isFirstTime: false,
                isAgentSolved: true,
            });
            return;
        }
        try {
            const score = 100;
            const attemptXp = 50;
            const starBadge = 'Gold';
            const kidChildId = localStorage.getItem('kido_child_id');
            const { data: { user } } = await supabase.auth.getUser();

            if (kidChildId) {
                const { data: childRow } = await supabase
                    .from('children').select('id, parent_id').eq('id', kidChildId).maybeSingle();
                if (childRow) {
                    const { data: prevComp } = await supabase
                        .from('lesson_completions').select('score, xp_earned, badge')
                        .eq('child_id', kidChildId).eq('lesson_id', lessonId).maybeSingle();

                    const bestScore = Math.max(prevComp?.score || 0, score);
                    const bestXp = Math.max(prevComp?.xp_earned || 0, attemptXp);

                    await supabase.from('lesson_completions').upsert({
                        child_id: kidChildId, parent_id: childRow.parent_id,
                        lesson_id: lessonId, score: bestScore,
                        xp_earned: bestXp, badge: starBadge,
                        completed_at: new Date().toISOString(),
                    }, { onConflict: 'child_id,lesson_id' });

                    const { data: allKidLessons } = await supabase
                        .from('lesson_completions').select('xp_earned').eq('child_id', kidChildId);
                    const totalXp = allKidLessons?.reduce((s, l) => s + (l.xp_earned || 0), 0) || 0;

                    await supabase.from('children').update({ total_xp: totalXp }).eq('id', kidChildId);
                    revealLevelComplete({
                        score, feedback: 'Perfect Prompts!', xpEarned: attemptXp, totalXp,
                        newLevel: 'Explorer', levelUp: false,
                        newBadgeLabels: [], isFirstTime: !prevComp,
                    });
                }
            } else if (user) {
                const { data: prevCompletion } = await supabase
                    .from('lesson_completions').select('xp_earned, badge')
                    .eq('user_id', user.id).eq('lesson_id', lessonId).maybeSingle();

                const updatedXp = Math.max(prevCompletion?.xp_earned || 0, attemptXp);

                await supabase.from('lesson_completions').upsert({
                    user_id: user.id, lesson_id: lessonId,
                    score, xp_earned: updatedXp, badge: starBadge,
                    completed_at: new Date().toISOString(),
                }, { onConflict: 'user_id,lesson_id' });

                const { data: allLessons } = await supabase
                    .from('lesson_completions').select('xp_earned').eq('user_id', user.id);
                const totalXp = allLessons?.reduce((sum, l) => sum + (l.xp_earned || 0), 0) || 0;

                await supabase.from('child_profiles').update({ total_xp: totalXp }).eq('id', user.id);
                revealLevelComplete({
                    score, feedback: 'Perfect Prompts!', xpEarned: attemptXp, totalXp,
                    newLevel: 'Gold', levelUp: false,
                    newBadgeLabels: [], isFirstTime: !prevCompletion,
                });
            } else {
                revealLevelComplete({
                    score, feedback: 'Perfect Prompts!', xpEarned: 0, totalXp: 0,
                    newLevel: 'Bronze', levelUp: false, newBadgeLabels: [], isFirstTime: true,
                });
            }
        } catch (err) {
            console.error('Error saving prompt completion:', err);
            revealLevelComplete({ score: 100, xp: 50, badge: 'Gold' });
        }
    };

    const submitBtnStyle = {
        ...S.btn,
        background: isSubmitting
            ? 'rgba(255,255,255,0.3)'
            : 'linear-gradient(135deg, #FFD700, #FFA000)',
        color: '#1a1a1a',
        border: '2px solid #fff',
        fontWeight: 700,
        boxShadow: isSubmitting ? 'none' : '0 0 12px rgba(255,215,0,0.6)',
        opacity: isSubmitting ? 0.7 : 1,
        cursor: isSubmitting ? 'not-allowed' : 'pointer',
        padding: isMobile ? '4px 10px' : '6px 15px',
        display: 'flex', alignItems: 'center', gap: 4,
        transition: 'all 0.2s ease',
        whiteSpace: 'nowrap',
    };

    // ── Render ───────────────────────────────────────────────────────────────
    return (
        <div className={`theme-${themeId}`} style={{
            ...S.root, background: themeBg,
            height: '100vh', overflow: 'hidden', position: 'relative',
        }}>
            {/* ── TOP BAR ───────────────────────────────────────────────── */}
            <div style={{
                ...S.bar, position: 'relative',
                borderBottom: '4px solid rgba(255,255,255,0.2)',
                overflow: 'hidden', justifyContent: 'space-between',
                opacity: loading ? 0 : 1,
                pointerEvents: loading ? 'none' : 'auto',
                zIndex: 1000,
            }}>
                <div style={{ position: 'absolute', inset: 0, background: 'rgba(0,0,0,0.2)', zIndex: 1 }} />

                {/* Left */}
                <div style={{ display: 'flex', alignItems: 'center', gap: isMobile ? 6 : 12, position: 'relative', zIndex: 2 }}>
                    <button
                        onClick={() => setSidebarOpen(!sidebarOpen)}
                        style={{ background: 'none', border: 'none', color: '#fff', fontSize: 20, cursor: 'pointer', padding: '0 5px', display: 'flex', alignItems: 'center' }}
                    >
                        <FaBars size={18} />
                    </button>

                    {!isMobile && (
                        <>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                                <span style={{ ...S.logo, color: '#fff', textShadow: '0 2px 10px rgba(0,0,0,0.5)' }}>
                                    Kido Dev Studio
                                </span>
                            </div>
                            <span style={{ ...S.badge, border: '1px solid rgba(255,255,255,0.6)', fontSize: '12px', padding: '4px 12px' }}>
                                {LESSON.title}
                            </span>
                        </>
                    )}
                </div>

                {/* Right */}
                <div style={{ display: 'flex', gap: isMobile ? 4 : 10, alignItems: 'center', position: 'relative', zIndex: 2 }}>
                    {pointerRef.current && (
                        <div style={{ position: 'absolute', left: pointerRef.current.x, top: pointerRef.current.y, zIndex: 9999, fontSize: 32, pointerEvents: 'none', animation: 'bounce 1s infinite' }}>
                            👆
                        </div>
                    )}


                    {/* RUN / STOP */}
                    <button
                        onClick={handleRunToggle}
                        style={{
                            ...S.btn,
                            background: running
                                ? 'linear-gradient(135deg, #D32F2F, #F44336)'
                                : 'linear-gradient(135deg, #43A047, #66BB6A)',
                            border: '2px solid #fff', color: '#fff',
                            padding: isMobile ? '3px 8px' : '4px 10px',
                            minWidth: isMobile ? 62 : 72, height: isMobile ? 28 : 32,
                            display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 4,
                            fontWeight: 700, fontSize: isMobile ? 10 : 11,
                            transition: 'all 0.2s ease',
                            transform: running ? 'scale(1.02)' : 'scale(1)',
                            boxShadow: running ? '0 0 10px rgba(244,67,54,0.4)' : '0 0 10px rgba(76,175,80,0.4)',
                            borderRadius: 8, whiteSpace: 'nowrap',
                        }}
                        title={running ? 'Stop Project' : 'Run Project'}
                    >
                        {running ? <FaStop size={9} /> : <FaPlay size={9} />}
                        <span style={{ fontSize: isMobile ? 11 : 12, letterSpacing: 0.2, lineHeight: 1 }}>
                            {running ? 'STOP' : 'RUN'}
                        </span>
                    </button>

                    {/* RESET */}
                    <button
                        onClick={handleResetWithTracking}
                        style={{ ...S.btn, background: '#8BC34A', color: '#fff', border: '2px solid #fff', padding: isMobile ? '4px 10px' : '6px 15px' }}
                    >
                        <FaUndo size={10} /> {!isMobile && 'Reset'}
                    </button>

                    {/* BACKDROP SELECT */}
                    {!isMobile && (
                        <select
                            value={typeof bdrop === 'number' ? bdrop : ''}
                            onChange={e => switchBackdrop(Number(e.target.value))}
                            style={{ ...S.sel, background: 'rgba(255,255,255,0.9)', border: '2px solid #8BC34A' }}
                        >
                            {BACKDROPS.map((b, i) => (
                                <option key={i} value={i}>{b.name}</option>
                            ))}
                        </select>
                    )}

                    {/* SUBMIT */}
                    <button
                        onClick={handleSubmit}
                        disabled={isSubmitting || running}
                        style={submitBtnStyle}
                        title="Save your project and complete the level"
                    >
                        {isSubmitting
                            ? <span style={{ fontSize: isMobile ? 12 : 14 }}>⏳</span>
                            : <FaFlagCheckered size={isMobile ? 10 : 12} />}
                        <span style={{ fontSize: isMobile ? 10 : 13, fontWeight: 700 }}>
                            {isSubmitting
                                ? (isMobile ? '...' : 'Saving...')
                                : (isMobile ? 'Done!' : 'Submit Level')}
                        </span>
                    </button>

                    {/* MAP / BACK */}
                    <button
                        onClick={() => navigate(-1)}
                        style={{ ...S.btn, background: 'rgba(255,255,255,0.2)', color: '#fff', border: '2px solid #fff', backdropFilter: 'blur(5px)', padding: isMobile ? '4px 10px' : '6px 15px' }}
                    >
                        <FaMap size={12} /> {!isMobile && 'Map'}
                    </button>
                </div>
            </div>

            {/* ── MAIN CONTENT ──────────────────────────────────────────── */}
            <div style={{
                display: 'flex', flexDirection: isMobile ? 'column' : 'row',
                flex: 1, overflow: isMobile ? 'auto' : 'hidden',
                minHeight: 0, position: 'relative', zIndex: 500,
            }}>
                <SpriteLoader show={loading} />

                {/* SIDEBAR */}
                <div style={{
                    overflow: 'hidden', minWidth: 0,
                    position: isMobile ? 'absolute' : 'relative',
                    left: 0, top: 0, bottom: 0,
                    width: sidebarOpen ? (isMobile ? 280 : 260) : 0,
                    zIndex: 1001,
                    boxShadow: (sidebarOpen && isMobile) ? '10px 0 50px rgba(0,0,0,0.5)' : 'none',
                    transition: '0.3s cubic-bezier(0.4, 0, 0.2, 1)',
                    height: '100%', background: '#F1F8E9',
                    opacity: loading ? 0 : 1, pointerEvents: loading ? 'none' : 'auto',
                }}>
                    <SidebarPanel
                        sidebarOpen={sidebarOpen} LESSON={LESSON} solveProject={solveProject}
                        tutorState={tutorState} tutorialStep={tutorialStep} startTutorial={startTutorial}
                        log={log} setLog={setLog} levelStats={levelStats}
                        isPromptProject={LESSON.is_prompt_project}
                    />
                </div>

                {isMobile && sidebarOpen && (
                    <div
                        onClick={() => setSidebarOpen(false)}
                        style={{ position: 'absolute', inset: 0, background: 'rgba(0,0,0,0.3)', zIndex: 1000 }}
                    />
                )}

                {/* ── MOBILE ────────────────────────────────────────────── */}
                {isMobile ? (
                    <div style={{ display: 'flex', flexDirection: 'column', flex: 1, overflowY: 'auto', opacity: loading ? 0 : 1, pointerEvents: loading ? 'none' : 'auto' }}>
                        <div style={{ height: '360px', width: '100%', flexShrink: 0, borderBottom: '4px solid #8BC34A' }}>
                            <StagePanel
                                isFullScreen={isFullScreen} setIsFullScreen={setIsFullScreen}
                                canvasRef={canvasRef} running={running} asking={asking}
                                answer={answer} setAnswer={setAnswer} submitAnswer={submitAnswer}
                                gradingResult={gradingResult} setGradingResult={setGradingResult}
                                tutorState={tutorState} tutorialStep={tutorialStep}
                                lessonId={lessonId} spInfo={spInfo} vars={vars} lists={lists}
                                panelTab={panelTab} setPanelTab={setPanelTab}
                                bdrop={bdrop} spritesRef={spritesRef}
                                activeSpriteRef={activeSpriteRef} switchSprite={switchSprite}
                                deleteSprite={deleteSprite} fileInputRef={fileInputRef}
                                handleSpriteUpload={handleSpriteUpload}
                                clearCustomSprite={clearCustomSprite} setLibMode={setLibMode}
                                setLibCategory={setLibCategory} setSearchQuery={setSearchQuery}
                                projectSoundsRef={projectSoundsRef}
                                projectBackdrops={projectBackdropsRef.current}
                                onMouseDown={onMouseDown} onMouseMove={onMouseMove} onMouseUp={onMouseUp}
                                tutorialSteps={tutorialStepsRef.current} sp={sp} _force={_force}
                            />
                        </div>
                        <div style={{ height: '600px', display: 'flex', flexDirection: 'column', background: '#F1F8E9', flexShrink: 0 }}>
                            {LESSON.is_prompt_project ? (
                                <PromptWorkspace
                                    lesson={LESSON} sp={sp} switchBackdrop={switchBackdrop}
                                    scratchBackdrops={scratchBackdrops}
                                    projectBackdropsRef={projectBackdropsRef}
                                    addLog={addLog} onComplete={handlePromptComplete} _force={_force}
                                />
                            ) : (
                                <WorkspaceTabs
                                    activeTab={workspaceTab} setTab={setWorkspaceTab}
                                    blocklyDiv={blocklyDiv} wsRef={wsRef} isMobile={isMobile}
                                    activeSprite={sp.current} sprites={spritesRef.current}
                                    sp={sp} spritesRef={spritesRef} activeSpriteRef={activeSpriteRef}
                                    projectSoundsRef={projectSoundsRef} _force={_force}
                                    addLog={addLog} fileInputRef={fileInputRef} setLibMode={setLibMode}
                                />
                            )}
                        </div>
                    </div>
                ) : (
                    /* ── DESKTOP ────────────────────────────────────────── */
                    <div style={{ display: 'contents', opacity: loading ? 0 : 1, pointerEvents: loading ? 'none' : 'auto' }}>
                        <div style={{
                            flex: sidebarOpen ? 1.5 : 0,
                            width: !sidebarOpen ? 480 : 'auto',
                            minWidth: !sidebarOpen ? 480 : 0,
                            display: 'flex', flexDirection: 'column',
                            overflow: 'hidden', background: '#F1F8E9',
                            borderRight: '4px solid #8BC34A',
                            opacity: loading ? 0 : 1, pointerEvents: loading ? 'none' : 'auto',
                        }}>
                            {LESSON.is_prompt_project ? (
                                <PromptWorkspace
                                    lesson={LESSON} sp={sp} switchBackdrop={switchBackdrop}
                                    scratchBackdrops={scratchBackdrops}
                                    projectBackdropsRef={projectBackdropsRef}
                                    addLog={addLog} onComplete={handlePromptComplete} _force={_force}
                                />
                            ) : (
                                <WorkspaceTabs
                                    activeTab={workspaceTab} setTab={setWorkspaceTab}
                                    blocklyDiv={blocklyDiv} wsRef={wsRef} isMobile={isMobile}
                                    activeSprite={sp.current} sprites={spritesRef.current}
                                    sp={sp} spritesRef={spritesRef} activeSpriteRef={activeSpriteRef}
                                    projectSoundsRef={projectSoundsRef} _force={_force}
                                    addLog={addLog} fileInputRef={fileInputRef} setLibMode={setLibMode}
                                />
                            )}
                        </div>
                        <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
                            <StagePanel
                                isFullScreen={isFullScreen} setIsFullScreen={setIsFullScreen}
                                canvasRef={canvasRef} running={running} asking={asking}
                                answer={answer} setAnswer={setAnswer} submitAnswer={submitAnswer}
                                gradingResult={gradingResult} setGradingResult={setGradingResult}
                                tutorState={tutorState} tutorialStep={tutorialStep}
                                lessonId={lessonId} spInfo={spInfo} vars={vars} lists={lists}
                                panelTab={panelTab} setPanelTab={setPanelTab}
                                bdrop={bdrop} spritesRef={spritesRef}
                                activeSpriteRef={activeSpriteRef} switchSprite={switchSprite}
                                deleteSprite={deleteSprite} fileInputRef={fileInputRef}
                                handleSpriteUpload={handleSpriteUpload}
                                clearCustomSprite={clearCustomSprite} setLibMode={setLibMode}
                                setLibCategory={setLibCategory} setSearchQuery={setSearchQuery}
                                projectSoundsRef={projectSoundsRef}
                                projectBackdrops={projectBackdropsRef.current}
                                onMouseDown={onMouseDown} onMouseMove={onMouseMove} onMouseUp={onMouseUp}
                                tutorialSteps={tutorialStepsRef.current} sp={sp} _force={_force}
                            />
                        </div>
                    </div>
                )}
            </div>

            <SolveOverlay active={tutorState.solving} />

            {/* ── AGENT HINT PANEL (multi-turn, memory-aware) ─────────────── */}
            {!LESSON.is_prompt_project && (
                <AgentHintPanel
                    isMobile={isMobile}
                    workspaceBlocks={agentWorkspaceBlocks}
                    getLiveWorkspaceBlocks={() => wsRef.current ? wsRef.current.getAllBlocks(false).map(b => b.type) : agentWorkspaceBlocks}
                    objective={LESSON.objective || LESSON.title || ''}
                    lessonId={lessonId}
                    onBlockHighlight={(blockType) => highlightNextBlock(blockType, wsRef.current, BLOCK_DB)}
                />
            )}

            {/* Salute plays first for a best-score (Gold-tier) submit, then
                LevelComplete reveals via handleSaluteDone. */}
            <SaluteSprite active={showSalute} onDone={handleSaluteDone} />

            {/* ── MODALS ────────────────────────────────────────────────── */}
            <AssetModal
                libMode={libMode} setLibMode={setLibMode} libCategory={libCategory}
                setLibCategory={setLibCategory} searchQuery={searchQuery}
                setSearchQuery={setSearchQuery} scratchLibrary={scratchLibrary}
                scratchBackdrops={scratchBackdrops} scratchSounds={scratchSounds}
                loadingLib={loadingLib} switchBackdrop={switchBackdrop}
                spritesRef={spritesRef} projectBackdropsRef={projectBackdropsRef}
                projectSoundsRef={projectSoundsRef} assetCache={assetCache}
                _force={_force} addLog={addLog}
            />

            {levelComplete && !showSalute && (
                <LevelComplete
                    data={levelComplete}
                    onClose={() => { setLevelComplete(null); navigate(-1); }}
                    onKeepPlaying={() => setLevelComplete(null)}
                />
            )}
        </div>
    );
}