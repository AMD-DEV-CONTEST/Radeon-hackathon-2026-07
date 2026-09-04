import { useCallback } from 'react';
import { playNote, playSound } from './soundEngine';
import { drawCat } from './catRenderer';

const delay = (ms) => new Promise(r => setTimeout(r, Math.max(0, ms)));

// ══════════════════════════════════════════════════════════════════════
//  Runtime Expression Evaluator
// ══════════════════════════════════════════════════════════════════════

export function evalExpr(expr, ctx) {
    if (expr === null || expr === undefined) return 0;
    const s = ctx.sprite;
    switch (expr.t) {
        case 'lit': return expr.v;
        case 'litS': return expr.v;
        // Math
        case 'op': {
            const a = Number(evalExpr(expr.a, ctx)) || 0;
            const b = Number(evalExpr(expr.b, ctx)) || 0;
            switch (expr.op) {
                case '+': return a + b;
                case '-': return a - b;
                case '*': return a * b;
                case '/': return b !== 0 ? a / b : 0;
                case '%': return b !== 0 ? a % b : 0;
                default: return 0;
            }
        }
        case 'round': return Math.round(Number(evalExpr(expr.a, ctx)) || 0);
        case 'random': {
            const lo = Number(evalExpr(expr.from, ctx)) || 0;
            const hi = Number(evalExpr(expr.to, ctx)) || 0;
            const mn = Math.min(lo, hi), mx = Math.max(lo, hi);
            if (Number.isInteger(mn) && Number.isInteger(mx)) return Math.floor(Math.random() * (mx - mn + 1)) + mn;
            return Math.random() * (mx - mn) + mn;
        }
        // Comparisons
        case 'cmp': {
            const a = evalExpr(expr.a, ctx), b = evalExpr(expr.b, ctx);
            switch (expr.op) {
                case '>': return Number(a) > Number(b);
                case '<': return Number(a) < Number(b);
                case '==': return String(a).toLowerCase() === String(b).toLowerCase();
                default: return false;
            }
        }
        // Logic
        case 'logic': return expr.op === '&&' ? (!!evalExpr(expr.a, ctx) && !!evalExpr(expr.b, ctx)) : (!!evalExpr(expr.a, ctx) || !!evalExpr(expr.b, ctx));
        case 'not': return !evalExpr(expr.a, ctx);
        // String
        case 'join': return String(evalExpr(expr.a, ctx) ?? '') + String(evalExpr(expr.b, ctx) ?? '');
        case 'length': return String(evalExpr(expr.a, ctx) ?? '').length;
        case 'contains': return String(evalExpr(expr.str, ctx) ?? '').toLowerCase().includes(String(evalExpr(expr.q, ctx) ?? '').toLowerCase());
        // Math ops
        case 'mathop': {
            const v = Number(evalExpr(expr.a, ctx)) || 0;
            switch (expr.op) {
                case 'abs': return Math.abs(v);
                case 'floor': return Math.floor(v);
                case 'ceiling': return Math.ceil(v);
                case 'sqrt': return Math.sqrt(Math.max(0, v));
                case 'sin': return Math.round(Math.sin(v * Math.PI / 180) * 1e10) / 1e10;
                case 'cos': return Math.round(Math.cos(v * Math.PI / 180) * 1e10) / 1e10;
                case 'tan': return Math.round(Math.tan(v * Math.PI / 180) * 1e10) / 1e10;
                case 'asin': return Math.asin(Math.max(-1, Math.min(1, v))) * 180 / Math.PI;
                case 'acos': return Math.acos(Math.max(-1, Math.min(1, v))) * 180 / Math.PI;
                case 'atan': return Math.atan(v) * 180 / Math.PI;
                case 'ln': return Math.log(Math.max(0.001, v));
                case 'log': return Math.log10(Math.max(0.001, v));
                case 'e^': return Math.exp(v);
                case '10^': return Math.pow(10, v);
                default: return v;
            }
        }
        // Sensing
        case 'touchingMouse': {
            const mx = ctx.mouseX(), my = ctx.mouseY();
            return Math.hypot(mx - s.x, my - s.y) < 44 * ((s.size || 100) / 100);
        }
        case 'touchingEdge': return s.x <= 22 || s.x >= 458 || s.y <= 22 || s.y >= 338;
        case 'keyPressed': {
            if (expr.key === 'any') return ctx.keysDown.size > 0;
            return ctx.keysDown.has(expr.key);
        }
        case 'mouseDown': return ctx.mouseIsDown;
        case 'mouseX': return ctx.mouseX() - 240;
        case 'mouseY': return 180 - ctx.mouseY();
        case 'distTo': {
            if (expr.target === 'mouse') return Math.hypot(ctx.mouseX() - s.x, ctx.mouseY() - s.y);
            return 0;
        }
        case 'answer': return ctx.answerVal?.current || '';
        case 'timer': return (Date.now() - (ctx.timerStart?.current || Date.now())) / 1000;
        case 'currentTime': {
            const d = new Date();
            switch (expr.which) {
                case 'year': return d.getFullYear();
                case 'month': return d.getMonth() + 1;
                case 'date': return d.getDate();
                case 'dayofweek': return d.getDay() + 1;
                case 'hour': return d.getHours();
                case 'minute': return d.getMinutes();
                case 'second': return d.getSeconds();
                default: return 0;
            }
        }
        // Sprite reporters
        case 'xPos': return Math.round(s.x - 240);
        case 'yPos': return Math.round(-(s.y - 180));
        case 'direction': return Math.round(s.dir);
        case 'sizeR': return s.size || 100;
        case 'costumeR': return expr.prop === 'name' ? (s.costumes?.[s.currentCostume]?.name || 'costume1') : ((s.currentCostume || 0) + 1);
        case 'tempoR': return ctx.tempoRef?.current || 120;
        case 'volR': return 100;
        // Variables
        case 'var': return ctx.vars[expr.name] ?? 0;
        // Lists
        case 'listItem': { const l = ctx.lists[expr.list]; const i = Math.round(Number(evalExpr(expr.idx, ctx)) || 1) - 1; return l ? (l[i] ?? '') : ''; }
        case 'listIdx': { const l = ctx.lists[expr.list]; const it = String(evalExpr(expr.item, ctx)); return l ? (l.indexOf(it) + 1) : 0; }
        case 'listLen': { const l = ctx.lists[expr.list]; return l ? l.length : 0; }
        case 'listContains': { const l = ctx.lists[expr.list]; const it = String(evalExpr(expr.item, ctx)); return l ? l.includes(it) : false; }
        default: return 0;
    }
}

// ══════════════════════════════════════════════════════════════════════
//  Tree-Walking Interpreter
// ══════════════════════════════════════════════════════════════════════

export function useActionExecutor({
    sp, runRef, addLog, safeSet, setVars, setLists, varsRef, listsRef,
    clones, penCanvas, customSprite, tempoRef, timerStart, answerReady,
    answerVal, setAsking, _force,
    keysDown, mousePosRef, mouseIsDownRef, broadcastHandler,
    projectSoundsRef,
    switchBackdrop, bdrop, backdrops,
    bdropRef, projectBackdropsRef,
}) {

    const execActions = useCallback(async (actions, overrideSprite, ctx) => {
        // Build execution context
        const baseCtx = {
            sprite: overrideSprite || sp.current,
            vars: varsRef.current,
            lists: listsRef.current,
            mouseX: () => mousePosRef?.current?.x ?? 240,
            mouseY: () => mousePosRef?.current?.y ?? 180,
            mouseIsDown: mouseIsDownRef?.current ?? false,
            keysDown: keysDown?.current || new Set(),
            answerVal, timerStart, tempoRef,
            runRef,
            switchBackdrop, bdrop, 
            backdrops: [...backdrops, ...(projectBackdropsRef?.current || [])],
            bdropRef,
        };
        const context = { ...baseCtx, ...(ctx || {}) };

        for (const a of actions) {
            if (!runRef.current) break;
            const s = context.sprite;
            // Refresh context vars each iteration
            context.vars = varsRef.current;
            context.lists = listsRef.current;
            context.mouseIsDown = mouseIsDownRef?.current ?? false;
            try {
                switch (a.t) {
                    // ── Motion ──
                    case 'move': {
                        const steps = Number(evalExpr(a.steps, context)) || 10;
                        const rad = ((s.dir - 90) * Math.PI) / 180;
                        const dx = Math.cos(rad), dy = Math.sin(rad);
                        const frames = Math.max(1, Math.round(Math.abs(steps) / 3));
                        for (let f = 0; f < frames; f++) {
                            if (!runRef.current) break;
                            s.x = Math.max(0, Math.min(480, s.x + steps / frames * dx));
                            s.y = Math.max(0, Math.min(360, s.y + steps / frames * dy));
                            await delay(16);
                        }
                        break;
                    }
                    case 'turn': {
                        const deg = Number(evalExpr(a.deg, context)) || 15;
                        s.dir += deg;
                        await delay(16);
                        break;
                    }
                    case 'turnL': {
                        const deg = Number(evalExpr(a.deg, context)) || 15;
                        s.dir -= deg;
                        await delay(16);
                        break;
                    }
                    case 'goto': {
                        s.x = Number(evalExpr(a.x, context)) + 240;
                        s.y = -Number(evalExpr(a.y, context)) + 180;
                        break;
                    }
                    case 'gotoPos': {
                        if (a.pos === 'random') { s.x = Math.random() * 420 + 30; s.y = Math.random() * 300 + 30; }
                        else if (a.pos === 'mouse') { s.x = context.mouseX(); s.y = context.mouseY(); }
                        break;
                    }
                    case 'glide': {
                        const sx = s.x, sy = s.y;
                        const ex = Number(evalExpr(a.x, context)) + 240;
                        const ey = -Number(evalExpr(a.y, context)) + 180;
                        const secs = Number(evalExpr(a.secs, context)) || 1;
                        const frames = Math.max(1, Math.round(secs * 60));
                        for (let f = 0; f < frames; f++) {
                            if (!runRef.current) break;
                            const t = (f + 1) / frames;
                            s.x = sx + (ex - sx) * t; s.y = sy + (ey - sy) * t;
                            await delay(16);
                        }
                        break;
                    }
                    case 'glidePos': {
                        const sx = s.x, sy = s.y;
                        const ex = a.pos === 'mouse' ? context.mouseX() : Math.random() * 420 + 30;
                        const ey = a.pos === 'mouse' ? context.mouseY() : Math.random() * 300 + 30;
                        const secs = Number(evalExpr(a.secs, context)) || 1;
                        const frames = Math.max(1, Math.round(secs * 60));
                        for (let f = 0; f < frames; f++) {
                            if (!runRef.current) break;
                            const t = (f + 1) / frames;
                            s.x = sx + (ex - sx) * t; s.y = sy + (ey - sy) * t;
                            await delay(16);
                        }
                        break;
                    }
                    case 'pointDir': s.dir = Number(evalExpr(a.dir, context)) || 90; break;
                    case 'pointMouse': {
                        const mx = context.mouseX(), my = context.mouseY();
                        s.dir = 90 + Math.atan2(my - s.y, mx - s.x) * 180 / Math.PI;
                        break;
                    }
                    case 'setX': s.x = Number(evalExpr(a.x, context)) + 240; break;
                    case 'setY': s.y = -Number(evalExpr(a.y, context)) + 180; break;
                    case 'dx': s.x = Math.max(0, Math.min(480, s.x + Number(evalExpr(a.v, context)))); break;
                    case 'dy': s.y = Math.max(0, Math.min(360, s.y - Number(evalExpr(a.v, context)))); break;
                    case 'bounce': {
                        if (s.x <= 5 || s.x >= 475) s.dir = 180 - s.dir;
                        if (s.y <= 5 || s.y >= 355) s.dir = -s.dir;
                        s.x = Math.max(5, Math.min(475, s.x));
                        s.y = Math.max(5, Math.min(355, s.y));
                        break;
                    }
                    case 'rotStyle': break;

                    // ── Looks ──
                    case 'say': {
                        const msg = String(evalExpr(a.msg, context) ?? '');
                        s.speech = msg; s.bubbleType = a.bubble;
                        addLog(`${a.bubble === 'think' ? '[Think]' : '[Say]'} "${msg}"`);
                        if (a.timed) {
                            const ms = Number(evalExpr(a.secs, context)) * 1000;
                            if (ms > 0) { await delay(ms); s.speech = null; }
                        }
                        break;
                    }
                    case 'nextCostume': {
                        if (s.costumes && s.costumes.length > 1) {
                            s.currentCostume = (s.currentCostume + 1) % s.costumes.length;
                            s.img = s.costumes[s.currentCostume].img;
                            s.emoji = s.costumes[s.currentCostume].emoji;
                            safeSet(() => _force && _force(x => x + 1));
                        }
                        break;
                    }
                    case 'nextBackdrop': {
                        if (typeof context.switchBackdrop === 'function') {
                            let cur = context.bdropRef?.current || 0;
                            if (typeof cur === 'string') {
                                cur = context.backdrops.findIndex(b => (b.name === cur || b.id === cur));
                                if (cur === -1) cur = 0;
                            }
                            const total = context.backdrops?.length || 1;
                            const next = (cur + 1) % total;
                            context.switchBackdrop(next);
                            addLog(`[Backdrop] Next backdrop: ${next}`);
                        }
                        break;
                    }
                    case 'switchBackdrop': {
                        if (context.switchBackdrop && context.backdrops) {
                            const nameOrExpr = a.backdrop;
                            let name = "";
                            if (typeof nameOrExpr === 'object' && nameOrExpr.t) {
                                name = String(evalExpr(nameOrExpr, context));
                            } else {
                                name = String(nameOrExpr);
                            }
                            
                            const idx = context.backdrops.findIndex(b => b.name.toLowerCase() === name.toLowerCase());
                            if (idx !== -1) {
                                context.switchBackdrop(idx);
                                addLog(`[Backdrop] Switch backdrop to ${name}`);
                            }
                        }
                        break;
                    }
                    case 'size': s.size = Math.max(5, Math.min(500, Number(evalExpr(a.v, context)) || 100)); break;
                    case 'dsize': s.size = Math.max(5, Math.min(500, (s.size || 100) + Number(evalExpr(a.v, context)))); break;
                    case 'setEffect': {
                        const v = Number(evalExpr(a.v, context));
                        if (a.eff === 'ghost') s.ghost = v;
                        if (a.eff === 'color') s.colorHue = v;
                        if (a.eff === 'brightness') s.brightness = v;
                        break;
                    }
                    case 'deffect': {
                        const v = Number(evalExpr(a.v, context));
                        if (a.eff === 'ghost') s.ghost = Math.max(0, Math.min(100, (s.ghost || 0) + v));
                        if (a.eff === 'color') s.colorHue = (s.colorHue || 0) + v;
                        if (a.eff === 'brightness') s.brightness = (s.brightness || 0) + v;
                        break;
                    }
                    case 'clearFx': s.ghost = 0; s.colorHue = 0; s.brightness = 0; break;
                    case 'vis': s.visible = a.v; break;
                    case 'goLayer': case 'goLayerDir': break;

                    // ── Sound ──
                    case 'sound': {
                        const projectSounds = projectSoundsRef?.current || [];
                        const duration = await playSound(a.snd, projectSounds);
                        addLog(`[Sound] Play: ${a.snd}`);
                        
                        // If 'play sound until done', wait for the duration
                        if (a.wait) {
                            await delay(duration);
                        }
                        break;
                    }

                    case 'stopSounds': break;
                    case 'vol': break;
                    case 'dvol': break;

                    // ── Control — TRUE RUNTIME LOOPS ──
                    case 'wait': {
                        const ms = Number(evalExpr(a.secs, context)) * 1000;
                        await delay(ms);
                        break;
                    }
                    case 'repeat': {
                        const n = Math.round(Number(evalExpr(a.count, context)) || 10);
                        for (let i = 0; i < n && runRef.current; i++) {
                            await execActions(a.body, null, context);
                            await delay(0); // yield
                        }
                        break;
                    }
                    case 'forever': {
                        let iters = 0;
                        while (runRef.current) {
                            await execActions(a.body, null, context);
                            await delay(16); // ~60fps yield
                            if (++iters > 100000) break; // safety
                        }
                        break;
                    }
                    case 'if': {
                        if (evalExpr(a.cond, context)) {
                            await execActions(a.body, null, context);
                        }
                        break;
                    }
                    case 'ifElse': {
                        if (evalExpr(a.cond, context)) {
                            await execActions(a.body, null, context);
                        } else {
                            await execActions(a.else, null, context);
                        }
                        break;
                    }
                    case 'waitUntil': {
                        let waits = 0;
                        while (runRef.current && !evalExpr(a.cond, context) && waits++ < 60000) {
                            context.vars = varsRef.current;
                            context.lists = listsRef.current;
                            context.mouseIsDown = mouseIsDownRef?.current ?? false;
                            await delay(50);
                        }
                        break;
                    }
                    case 'repeatUntil': {
                        let iters = 0;
                        while (runRef.current && !evalExpr(a.cond, context) && iters++ < 100000) {
                            await execActions(a.body, null, context);
                            context.vars = varsRef.current;
                            context.lists = listsRef.current;
                            context.mouseIsDown = mouseIsDownRef?.current ?? false;
                            await delay(16);
                        }
                        break;
                    }
                    case 'stop': {
                        if (a.w === 'all' || a.w === 'script') runRef.current = false;
                        break;
                    }
                    case 'clone': {
                        clones.current = [...clones.current, { ...s, speech: null }];
                        break;
                    }
                    case 'delClone': {
                        clones.current = clones.current.slice(0, -1);
                        break;
                    }

                    // ── Sensing ──
                    case 'ask': {
                        const q = String(evalExpr(a.q, context));
                        answerReady.current = false; answerVal.current = '';
                        setAsking(q); addLog(`[Ask] ${q}`);
                        await new Promise(resolve => {
                            const id = setInterval(() => {
                                if (!runRef.current || answerReady.current) { clearInterval(id); resolve(); }
                            }, 100);
                        });
                        setAsking(null);
                        break;
                    }
                    case 'resetTimer': timerStart.current = Date.now(); break;

                    // ── Variables ──
                    case 'setVar': {
                        const v = evalExpr(a.v, context);
                        varsRef.current[a.name] = typeof v === 'string' ? v : (Number(v) || 0);
                        safeSet(() => setVars({ ...varsRef.current }));
                        break;
                    }
                    case 'dVar': {
                        varsRef.current[a.name] = (Number(varsRef.current[a.name]) || 0) + Number(evalExpr(a.v, context));
                        safeSet(() => setVars({ ...varsRef.current }));
                        break;
                    }
                    case 'showVar': case 'hideVar': break;

                    // ── Broadcast ──
                    case 'broadcast': {
                        const msg = String(evalExpr(a.msg, context));
                        addLog(`[Broadcast] ${msg}`);
                        if (broadcastHandler) {
                            const p = broadcastHandler(msg);
                            if (a.wait && p) await p;
                        }
                        break;
                    }

                    // ── Pen ──
                    case 'penDown': s._penDown = true; s._penLastX = s.x; s._penLastY = s.y; break;
                    case 'penUp': s._penDown = false; break;
                    case 'penClear': { const pc = penCanvas.current; if (pc) pc.getContext('2d').clearRect(0, 0, pc.width, pc.height); break; }
                    case 'penStamp': { const pc = penCanvas.current; if (pc) drawCat(pc.getContext('2d'), s, customSprite.current); break; }
                    case 'penColor': s._penColor = String(evalExpr(a.color, context)) || '#ff0000'; break;
                    case 'penDProp': case 'penSetProp': break;
                    case 'penSize': s._penSize = Math.max(1, Number(evalExpr(a.v, context)) || 3); break;
                    case 'penDSize': s._penSize = Math.max(1, (s._penSize || 3) + Number(evalExpr(a.v, context))); break;

                    // ── Music ──
                    case 'playNote': {
                        const note = Number(evalExpr(a.note, context)) || 60;
                        const beats = Number(evalExpr(a.beats, context)) || 0.25;
                        const ms = playNote(note, beats, tempoRef);
                        await delay(ms);
                        break;
                    }
                    case 'rest': {
                        const beats = Number(evalExpr(a.beats, context)) || 0.25;
                        const bpm = tempoRef?.current || 120;
                        await delay((60 / bpm) * beats * 1000);
                        break;
                    }
                    case 'tempo': tempoRef.current = Math.max(20, Math.min(500, Number(evalExpr(a.v, context)) || 120)); break;
                    case 'dtempo': tempoRef.current = Math.max(20, Math.min(500, (tempoRef.current || 120) + Number(evalExpr(a.v, context)))); break;

                    // ── Lists ──
                    case 'listAdd': { const it = String(evalExpr(a.item, context)); listsRef.current[a.list]?.push(it); setLists({ ...listsRef.current }); break; }
                    case 'listDel': { const idx = Math.round(Number(evalExpr(a.idx, context))) - 1; listsRef.current[a.list]?.splice(idx, 1); setLists({ ...listsRef.current }); break; }
                    case 'listClear': { listsRef.current[a.list] = []; setLists({ ...listsRef.current }); break; }
                    case 'listInsert': { const idx = Math.round(Number(evalExpr(a.idx, context))) - 1; const it = String(evalExpr(a.item, context)); listsRef.current[a.list]?.splice(idx, 0, it); setLists({ ...listsRef.current }); break; }
                    case 'listReplace': { const idx = Math.round(Number(evalExpr(a.idx, context))) - 1; const it = String(evalExpr(a.item, context)); if (listsRef.current[a.list]) listsRef.current[a.list][idx] = it; setLists({ ...listsRef.current }); break; }

                    // ── My Blocks ──
                    case 'myBlockCall': {
                        if (ctx?.myBlockDefs?.[a.name]) {
                            await execActions(ctx.myBlockDefs[a.name], null, context);
                        }
                        addLog(`[Call] ${a.name}`);
                        break;
                    }

                    default: break;
                }
            } catch (err) { console.warn('Action error:', a.t, err); }
        }
    }, []); // eslint-disable-line

    return { execActions };
}
