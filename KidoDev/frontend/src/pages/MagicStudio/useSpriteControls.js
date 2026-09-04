import * as Blockly from 'blockly';
import { supabase } from '../../utils/supabaseClient';
import { generateSolutionXml } from './tutorialEngine';
import { generateLiveSolution } from '../../utils/aiClient';
import { BACKDROPS } from './constants';

export function useSpriteControls({
    spritesRef, activeSpriteRef, wsRef, sp, bdrop, bdropRef, setBdrop,
    penCanvas, customSprite, addLog, _force, setTutorState, tutorState,
    fileInputRef, setWorkspaceTab, setIsAgentSolved
}) {
    const switchBackdrop = (i) => {
        bdropRef.current = i;
        setBdrop(i);
        const bd = BACKDROPS[i] || BACKDROPS[0];
        console.log("Backdrop selected:", bd ? bd.name : i);
    };

    const createNewSprite = () => {
        spritesRef.current.push({
            id: 'spr_' + Math.random().toString(36).substr(2, 6),
            name: 'Sprite' + (spritesRef.current.length + 1),
            x: 240, y: 180, dir: 90, size: 100, ghost: 0, colorHue: 0,
            brightness: 0, visible: true, speech: null, bubbleType: 'say', img: null, xml: ''
        });
        _force(x => x + 1);
        addLog('Created a new Sprite');
    };

    const switchSprite = (id) => {
        const curXml = Blockly.Xml.domToText(Blockly.Xml.workspaceToDom(wsRef.current));
        const old = spritesRef.current.find(s => s.id === activeSpriteRef.current);
        if (old) old.xml = curXml;
        activeSpriteRef.current = id;
        const newSpr = spritesRef.current.find(s => s.id === id);
        wsRef.current.clear();
        if (newSpr && newSpr.xml) {
            try { Blockly.Xml.domToWorkspace(Blockly.utils.xml.textToDom(newSpr.xml), wsRef.current); } catch (e) { }
        }
        _force(x => x + 1);
        addLog('Switched to ' + newSpr?.name);
    };

    const deleteSprite = (id) => {
        if (spritesRef.current.length <= 1) return alert('Need at least 1 sprite');
        spritesRef.current = spritesRef.current.filter(s => s.id !== id);
        if (activeSpriteRef.current === id) switchSprite(spritesRef.current[0].id);
        _force(x => x + 1);
    };

    const handleSpriteUpload = (e) => {
        const file = e.target.files[0]; if (!file) return;
        const curArgs = sp.current;
        const url = URL.createObjectURL(file);
        const img = new Image();
        img.onload = () => { curArgs.img = img; addLog('Costume updated: ' + file.name); _force(x => x + 1); };
        img.src = url;
        e.target.value = '';
    };

    const clearCustomSprite = () => {
        if (sp.current) sp.current.img = null;
        addLog('Back to Kido');
        _force(x => x + 1);
    };

    // ─── Clean XML from database ──────────────────────────────────────────────
    const cleanXmlString = (raw) => {
        let xml = raw;
        try {
            let prev = '';
            while (prev !== xml) {
                prev = xml;
                xml = xml.replace(/\\"/g, '"').replace(/\\\\/g, '\\');
            }
        } catch (e) { /* ignore */ }

        if (!xml.trim().startsWith('<xml')) {
            xml = `<xml xmlns="https://developers.google.com/blockly/xml">${xml}</xml>`;
        } else if (!xml.includes('xmlns=')) {
            xml = xml.replace('<xml', '<xml xmlns="https://developers.google.com/blockly/xml"');
        }

        return xml;
    };

    // ─── Inject XML into Blockly workspace ───────────────────────────────────
    const injectXml = (xmlString) => {
        if (!wsRef.current) return false;
        try {
            Blockly.Events.disable();
            wsRef.current.clear();
            const dom = Blockly.utils.xml.textToDom(xmlString);
            Blockly.Xml.domToWorkspace(dom, wsRef.current);
            Blockly.Events.enable();
            wsRef.current.render();
            Blockly.svgResize(wsRef.current);
            const top = wsRef.current.getTopBlocks(false);
            if (top.length > 0) wsRef.current.centerOnBlock(top[0].id);
            return true;
        } catch (err) {
            console.error('Blockly inject error:', err, xmlString.slice(0, 200));
            Blockly.Events.enable();
            return false;
        }
    };
    
    const MIN_OVERLAY_MS = 450; // just enough to avoid a flash-of-overlay on instant solves

    const solveProject = async (LESSON) => {
        if (tutorState?.solving) return;

        const startedAt = Date.now();

        
        setTutorState({ active: false, message: '', solving: true });

        let finalMessage = '';
        let solvedOk = false;

        try {
            // 1. Try database
            let sol = null;
            try {
                const { data } = await supabase
                    .from('tutor_solutions')
                    .select('xml, message, tip')
                    .eq('lesson_id', LESSON.id)
                    .maybeSingle();
                if (data?.xml) sol = data;
            } catch (e) { console.error('DB fetch error', e); }

            // 2. Fallback: generate from objective + lesson info using Gemma
            if (!sol?.xml) {
                const liveSolution = await generateLiveSolution(LESSON.objective || LESSON.title || '');
                if (liveSolution && liveSolution.xml) {
                    sol = liveSolution;
                } else {
                    const generated = generateSolutionXml(LESSON.objective || LESSON.title || '');
                    if (generated) {
                        sol = {
                            xml: generated,
                            message: "I read the mission and figured out the perfect solution!",
                            tip: "The blocks are ready! Click RUN to see the magic!"
                        };
                    }
                }
            }

            // 3. Hard fail
            if (!sol?.xml) {
                finalMessage = "I'm still learning this project. Try dragging the blocks yourself!";
                return;
            }

            
            if (setWorkspaceTab) setWorkspaceTab('code');
            const xmlLower = sol.xml.toLowerCase();
            const cats = [];
            if (xmlLower.includes('s_move') || xmlLower.includes('s_glide') || xmlLower.includes('s_turn') || xmlLower.includes('s_goto')) cats.push('Motion');
            if (xmlLower.includes('s_say') || xmlLower.includes('s_hide') || xmlLower.includes('s_show') || xmlLower.includes('s_change_size') || xmlLower.includes('s_change_effect')) cats.push('Looks');
            if (xmlLower.includes('s_play') || xmlLower.includes('s_play_note')) cats.push('Sound');
            if (xmlLower.includes('s_forever') || xmlLower.includes('s_repeat') || xmlLower.includes('s_if') || xmlLower.includes('s_wait')) cats.push('Control');
            if (xmlLower.includes('s_pen')) cats.push('Pen');
            if (xmlLower.includes('s_set_var') || xmlLower.includes('s_change_var')) cats.push('Variables');

            for (const cat of cats) {
                const el = document.querySelector(`.blocklyTreeRow[aria-label*="${cat}"]`);
                if (el) el.click();
            }

            // Inject
            const cleanXml = cleanXmlString(sol.xml);
            const ok = injectXml(cleanXml);

            if (ok) {
                setIsAgentSolved(true);
                addLog('Co-Mentor: project solved!');
                solvedOk = true;
                finalMessage = sol.tip || "Done! Click RUN to see the magic!";
            } else {
                finalMessage = "Hmm, there was a small hiccup loading the blocks. Try the tutorial instead!";
            }
        } finally {
            // Make sure the overlay was visible for at least MIN_OVERLAY_MS
            // total, so a near-instant DB hit doesn't look like a glitch/flash.
            const elapsed = Date.now() - startedAt;
            const remaining = MIN_OVERLAY_MS - elapsed;
            if (remaining > 0) {
                await new Promise(r => setTimeout(r, remaining));
            }

            // Exit solving mode — overlay starts its own ~700ms fade-out now.
            setTutorState({ active: false, message: '', solving: false });

        
            setTimeout(() => {
                setTutorState(p => ({ ...p, active: true, message: finalMessage, solving: false }));
                setTimeout(() => setTutorState(p => ({ ...p, active: false })), solvedOk ? 4000 : 3000);
            }, 750);
        }
    };

    return { switchBackdrop, createNewSprite, switchSprite, deleteSprite, handleSpriteUpload, clearCustomSprite, solveProject };
}