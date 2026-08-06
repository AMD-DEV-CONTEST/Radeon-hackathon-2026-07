import { useRef, useState } from 'react';

import defaultSpriteImg from '../../assets/no_bg_output/sprite-logo_nobg.webp';

const defaultCatImg = new Image();
defaultCatImg.src = defaultSpriteImg;

export function useStudioRefs() {
    const blocklyDiv = useRef(null);
    const canvasRef = useRef(null);
    const wsRef = useRef(null);
    const animId = useRef(null);
    const runRef = useRef(false);
    const bdropRef = useRef(0);
    const timerStart = useRef(Date.now());
    const dragRef = useRef(null);
    const answerReady = useRef(false);
    const answerVal = useRef('');
    const clones = useRef([]);
    const varsRef = useRef({ score: 0, lives: 3, health: 100, speed: 5, timer: 0, level: 1 });
    const penCanvas = useRef(null);
    const customSprite = useRef(null);
    const tempoRef = useRef(120);
    const listsRef = useRef({ myList: [], highScores: [], items: [] });
    const fileInputRef = useRef(null);
    const spritesRef = useRef([{
        id: 'cat', name: 'Sprite1', emoji: '', x: 240, y: 180, dir: 90,
        size: 100, ghost: 0, colorHue: 0, brightness: 0, visible: true,
        speech: null, bubbleType: 'say', img: defaultCatImg, xml: ''
    }]);
    const activeSpriteRef = useRef('cat');
    const soundsRef = useRef([]);
    const isMounted = useRef(true);
    const keysDown = useRef(new Set());
    const mousePosRef = useRef({ x: 240, y: 180 });
    const mouseIsDownRef = useRef(false);
    const assetCache = useRef({});
    const audioCache = useRef({});
    const projectBackdropsRef = useRef([]);
    const projectSoundsRef = useRef([]);

    const sp = {
        get current() {
            return spritesRef.current.find(s => s.id === activeSpriteRef.current) || spritesRef.current[0];
        },
        set current(v) { /* noop */ }
    };

    // React state
    const [running, setRunning] = useState(false);
    const [log, setLog] = useState([]);
    const [vars, setVars] = useState({ ...varsRef.current });
    const [lists, setLists] = useState({ ...listsRef.current });
    const [bdrop, setBdrop] = useState(0);
    const [asking, setAsking] = useState(null);
    const [answer, setAnswer] = useState('');
    const [spInfo, setSpInfo] = useState({ x: 0, y: 0, dir: 90, size: 100 });
    const [panelTab, setPanelTab] = useState('sprites');
    const [workspaceTab, setWorkspaceTab] = useState('code');
    const [libMode, setLibMode] = useState(null);
    const [libCategory, setLibCategory] = useState('All');
    const [searchQuery, setSearchQuery] = useState('');
    const [scratchLibrary, setScratchLibrary] = useState([]);
    const [scratchBackdrops, setScratchBackdrops] = useState([]);
    const [scratchSounds, setScratchSounds] = useState([]);
    const [loadingLib, setLoadingLib] = useState(false);
    const [tutorState, setTutorState] = useState({ active: false, message: '', solving: false });
    const [gradingResult, setGradingResult] = useState(null);
    const [isAgentSolved, setIsAgentSolved] = useState(false);
    const [tutorialStep, setTutorialStep] = useState(-1);
    const [sidebarOpen, setSidebarOpen] = useState(window.innerWidth > 900);
    const [, _force] = useState(0);

    const safeSet = (fn) => { if (isMounted.current) fn(); };
    const addLog = (msg) => safeSet(() => setLog(p => [...p.slice(-49), msg]));

    return {
        // refs
        blocklyDiv, canvasRef, wsRef, animId, runRef, bdropRef, timerStart,
        dragRef, answerReady, answerVal, clones, varsRef, penCanvas,
        customSprite, tempoRef, listsRef, fileInputRef, spritesRef,
        activeSpriteRef, soundsRef, isMounted, keysDown, mousePosRef,
        mouseIsDownRef, assetCache, audioCache,
        projectBackdropsRef, projectSoundsRef, sp,
        // state & setters
        running, setRunning, log, setLog, vars, setVars, lists, setLists,
        bdrop, setBdrop, asking, setAsking, answer, setAnswer, spInfo, setSpInfo,
        panelTab, setPanelTab, libMode, setLibMode, libCategory, setLibCategory,
        searchQuery, setSearchQuery, scratchLibrary, setScratchLibrary,
        scratchBackdrops, setScratchBackdrops, scratchSounds, setScratchSounds,
        loadingLib, setLoadingLib, tutorState, setTutorState, gradingResult,
        setGradingResult, isAgentSolved, setIsAgentSolved, tutorialStep, setTutorialStep, sidebarOpen, setSidebarOpen,
        workspaceTab, setWorkspaceTab,
        _force, safeSet, addLog,
    };
}
