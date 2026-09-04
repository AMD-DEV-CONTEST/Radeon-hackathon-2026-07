import { useEffect } from 'react';
import * as Blockly from 'blockly';
import 'blockly/blocks';

import { defineAllScratchBlocks, SCRATCH_TOOLBOX } from '../../data/scratchBlocks';
import { BACKDROPS, getActiveBackdrop } from './constants';
import { drawCat } from './catRenderer';
import { recordBlockPlacedForEngagement } from '../../agents/memory/AgentMemoryStore';

/* ───────────────────────────────────────────── */
/* 🧠 AI Helper (SAFE / OPTIONAL)               */
/* ───────────────────────────────────────────── */

export function getAIReadyWorkspaceData(wsRef) {
    try {
        const ws = wsRef?.current;
        if (!ws || !Blockly?.Xml) return { currentBlocks: [], xml: '' };

        const currentBlocks = ws.getAllBlocks(false).map(b => b.type);
        const xml = Blockly.Xml.domToText(Blockly.Xml.workspaceToDom(ws));
        return { currentBlocks, xml };
    } catch (err) {
        console.warn('[AI Extractor Failed]', err);
        return { currentBlocks: [], xml: '' };
    }
}

/* ───────────────────────────────────────────── */
/* MAIN HOOK                                     */
/* ───────────────────────────────────────────── */

export function useBlocklySetup({
    blocklyDiv,
    wsRef,
    isMounted,
    canvasRef,
    penCanvas,
    bdropRef,
    projectBackdropsRef,
    clones,
    spritesRef,
    activeSpriteRef,
    customSprite,
    sp,
    setSpInfo,
    assetCache,
    isAgentSolvedRef,
    tutorStateRef,
    setIsAgentSolved,
    addLog,
}) {

    /* ─────────────────────────────────────────── */
    /* 1. BLOCKLY INIT                             */
    /* ─────────────────────────────────────────── */

    useEffect(() => {
        let retries = 0;
        const MAX_RETRIES = 10;
        let timeout;

        const init = () => {
            if (!isMounted.current) return;
            if (wsRef.current) return;

            const el = blocklyDiv.current;
            if (!el || el.offsetWidth === 0) {
                if (retries++ < MAX_RETRIES) timeout = setTimeout(init, 150);
                return;
            }

            try {
                defineAllScratchBlocks();

                wsRef.current = Blockly.inject(el, {
                    toolbox: SCRATCH_TOOLBOX,
                    scrollbars: true,
                    trashcan: true,
                    maxTrashcanContents: 32,
                    media: 'https://unpkg.com/blockly@12.4.1/media/',
                    move: { drag: true, wheel: true, scrollbars: true },
                    grid: { spacing: 40, length: 2, colour: '#e5e5e5', snap: true },
                    zoom: { controls: true, wheel: true, startScale: 0.8, maxScale: 4, minScale: 0.3, scaleSpeed: 1.3 },
                    renderer: 'zelos',
                    sounds: false,
                });

                setTimeout(() => {
                    if (wsRef.current) Blockly.svgResize(wsRef.current);
                }, 100);

                if (wsRef.current) {
                    wsRef.current.addChangeListener((event) => {
                        if (event.type === Blockly.Events.BLOCK_CREATE || event.type === Blockly.Events.BLOCK_MOVE) {
                            recordBlockPlacedForEngagement();
                        }
                        if (
                            isAgentSolvedRef?.current &&
                            tutorStateRef &&
                            !tutorStateRef.current?.solving &&
                            (
                                event.type === Blockly.Events.BLOCK_CREATE ||
                                event.type === Blockly.Events.BLOCK_DELETE ||
                                event.type === Blockly.Events.BLOCK_CHANGE ||
                                event.type === Blockly.Events.BLOCK_MOVE
                            )
                        ) {
                            setIsAgentSolved(false);
                            addLog?.('[System] You modified the blocks! Agent solve status cleared, stars are now active.');
                        }
                    });
                }

            } catch (err) {
                console.error('[Blockly Init Error]', err);
            }
        };

        timeout = setTimeout(init, 100);

        return () => {
            clearTimeout(timeout);
            if (wsRef.current) {
                wsRef.current.dispose();
                wsRef.current = null;
            }
        };
    }, []); // eslint-disable-line react-hooks/exhaustive-deps

    /* ─────────────────────────────────────────── */
    /* 2. CANVAS RENDER LOOP                       */
    /* ─────────────────────────────────────────── */

    useEffect(() => {
        const canvas = canvasRef.current;
        if (!canvas) return;

        const ctx = canvas.getContext('2d');
        let frame;

        const render = () => {
            if (!isMounted.current) return;

            ctx.clearRect(0, 0, canvas.width, canvas.height);

            /* ── BACKDROP ────────────────────────────────────────────────── */
            //
            // getActiveBackdrop handles both cases:
            //   • bdropRef.current is a NUMBER → local BACKDROPS[n]
            //   • bdropRef.current is a STRING → runtime Scratch CDN backdrop
            //     stored in projectBackdropsRef (added via AssetModal)
            //
            const bd = getActiveBackdrop(bdropRef.current, projectBackdropsRef);

            let drawn = false;

            if (bd) {
                // Priority 1: bd.img set directly on the backdrop object
                //             (local BACKDROPS pre-load into bd.img,
                //              AssetModal sets existing.img on Scratch backdrops)
                let bdImg = bd.img;

                // Priority 2: look up by md5ext in assetCache
                //             (AssetModal stores images as assetCache[md5ext])
                if (!bdImg && bd.md5ext) {
                    bdImg = assetCache?.current?.[bd.md5ext] ?? null;
                }

                // Priority 3: look up by full URL in assetCache (legacy fallback)
                if (!bdImg && bd.url) {
                    bdImg = assetCache?.current?.[bd.url] ?? null;
                }

                // Draw image if it has finished loading
                if (bdImg?.complete && bdImg.naturalWidth > 0) {
                    try {
                        ctx.drawImage(bdImg, 0, 0, canvas.width, canvas.height);
                        drawn = true;
                    } catch (e) {
                        console.error('Error drawing backdrop image:', e);
                    }
                }
            }

            // Solid colour fallback while image is loading (or colour-only entries)
            if (!drawn) {
                ctx.fillStyle = bd?.color || '#ffffff';
                ctx.fillRect(0, 0, canvas.width, canvas.height);
            }

            /* ── PEN LAYER ───────────────────────────────────────────────── */
            if (penCanvas.current) {
                ctx.drawImage(penCanvas.current, 0, 0);
            }

            /* ── SPRITES ─────────────────────────────────────────────────── */
            const allSprites = [
                ...clones.current,
                ...spritesRef.current,
            ];

            allSprites.forEach(s => {
                const img =
                    (s.id === 'custom' && customSprite.current)
                        ? customSprite.current
                        : s.img;
                drawCat(ctx, s, img);
            });

            /* ── HUD INFO ────────────────────────────────────────────────── */
            const active = sp.current;
            if (active) {
                setSpInfo({
                    x: Math.round(active.x - 240),
                    y: Math.round(180 - active.y),
                    dir: Math.round(active.dir),
                    size: Math.round(active.size),
                });
            }

            frame = requestAnimationFrame(render);
        };

        frame = requestAnimationFrame(render);
        return () => cancelAnimationFrame(frame);
    }, [canvasRef.current]); // eslint-disable-line react-hooks/exhaustive-deps

    /* ─────────────────────────────────────────── */
    /* 3. RESIZE HANDLER                           */
    /* ─────────────────────────────────────────── */

    useEffect(() => {
        const onResize = () => {
            if (wsRef.current && Blockly?.svgResize) {
                Blockly.svgResize(wsRef.current);
            }
        };
        window.addEventListener('resize', onResize);
        return () => window.removeEventListener('resize', onResize);
    }, []);
}