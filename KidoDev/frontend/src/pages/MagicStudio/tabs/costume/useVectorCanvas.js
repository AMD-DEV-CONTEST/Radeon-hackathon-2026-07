
import {
    useCallback,
    useEffect,
    useRef,
} from 'react';
import * as fabric from 'fabric';
import { getCleanAssetUrl } from '../../constants';

/**
 * useVectorCanvas – all Fabric.js-related logic for the Costumes editor.
 *
 * Accepts shared refs and state from the parent component; returns action
 * callbacks that the parent wires into the toolbar UI and keyboard shortcuts.
 */
export function useVectorCanvas({
    costume, sprite, isVector, cvRef, fabricRef,
    undoStack, redoStack, isHistoryAction, clipboardRef,
    tool, setTool, fillColor, strokeColor, strokeWidth,
    setHasSel, _force, activeIdx,
}) {
    // ── Vector: shape-drawing mouse handlers (re-attach on tool change) ───────
    const drawState = useRef({ active: false, startX: 0, startY: 0, shape: null });

    /** Push current canvas state to undo stack */
    const saveHistory = useCallback(() => {
        if (!fabricRef.current || isHistoryAction.current) return;
        const json = fabricRef.current.toJSON();
        undoStack.current.push(json);
        if (undoStack.current.length > 40) undoStack.current.shift();
        redoStack.current = [];
    }, [fabricRef, isHistoryAction, undoStack, redoStack]);

    /** Render canvas → dataURL → update sprite preview thumbnail */
    const saveToSpritePreview = useCallback(() => {
        if (!fabricRef.current || !costume) return;
        try {
            const dataUrl = fabricRef.current.toDataURL({ format: 'png', quality: 1, multiplier: 1 });
            const img = new Image();
            img.src = dataUrl;
            img.onload = () => {
                /* MUTATION: sprite is mutated directly here */
                costume.img = img;
                sprite.img = img;
                costume.fabricJSON = fabricRef.current.toJSON();
                _force(x => x + 1);
            };
        } catch (err) { console.warn('saveToSpritePreview:', err); }
    }, [costume, sprite, _force, fabricRef]);

    /** Load a costume object onto the Fabric canvas */
    const loadCostume = useCallback((c, canvas) => {
        canvas.clear();
        canvas.backgroundColor = 'transparent';

        if (c.fabricJSON?.objects?.length) {
            canvas.loadFromJSON(c.fabricJSON).then(() => {
                // BUG FIX 3: Re-center objects if they are positioned off-canvas
                // after loading from saved JSON. Uses same centering math as the
                // img.src branch below: left = (480 - width)/2, top = (360 - height)/2
                const objs = canvas.getObjects();
                if (objs.length > 0) {
                    // Calculate bounding box of all objects
                    let minL = Infinity, minT = Infinity, maxR = -Infinity, maxB = -Infinity;
                    objs.forEach(o => {
                        const bound = o.getBoundingRect();
                        if (bound.left < minL) minL = bound.left;
                        if (bound.top < minT) minT = bound.top;
                        if (bound.left + bound.width > maxR) maxR = bound.left + bound.width;
                        if (bound.top + bound.height > maxB) maxB = bound.top + bound.height;
                    });
                    const groupW = maxR - minL;
                    const groupH = maxB - minT;
                    const centerX = minL + groupW / 2;
                    const centerY = minT + groupH / 2;

                    // If the center of all objects is far from the canvas center (240,180),
                    // re-center them. Threshold: if center is outside the canvas bounds.
                    const CANVAS_W = 480, CANVAS_H = 360;
                    if (centerX < 0 || centerX > CANVAS_W || centerY < 0 || centerY > CANVAS_H) {
                        const offsetX = (CANVAS_W - groupW) / 2 - minL;
                        const offsetY = (CANVAS_H - groupH) / 2 - minT;
                        objs.forEach(o => {
                            o.set({ left: o.left + offsetX, top: o.top + offsetY });
                            o.setCoords();
                        });
                    }
                }
                canvas.renderAll();
                undoStack.current = [c.fabricJSON];
                redoStack.current = [];
            }).catch(err => console.warn('loadFromJSON:', err));
            return;
        }

        if (!c.img?.src) { canvas.renderAll(); return; }

        fabric.FabricImage.fromURL(getCleanAssetUrl(c.img.src), { crossOrigin: 'anonymous' })
            .then(fImg => {
                const scale = Math.min(380 / fImg.width, 300 / fImg.height, 1);
                fImg.scale(scale);
                fImg.set({
                    left: (480 - fImg.getScaledWidth()) / 2,
                    top: (360 - fImg.getScaledHeight()) / 2,
                });
                canvas.add(fImg);
                canvas.renderAll();
                undoStack.current = [canvas.toJSON()];
                redoStack.current = [];
            })
            .catch(err => console.warn('FabricImage.fromURL:', err));
    }, [undoStack, redoStack]);

    /** Initialise (or re-initialise) the Fabric canvas */
    useEffect(() => {
        if (!isVector || !cvRef.current) return;

        // Dispose old instance
        if (fabricRef.current) {
            try { fabricRef.current.dispose(); } catch (_) { }
            fabricRef.current = null;
        }

        cvRef.current.width = 480;
        cvRef.current.height = 360;

        const canvas = new fabric.Canvas(cvRef.current, {
            width: 480, height: 360,
            preserveObjectStacking: true,
            selection: true,
            backgroundColor: 'transparent',
            enableRetinaScaling: false,
        });
        fabricRef.current = canvas;

        // Selection tracking
        const onSelChange = () => setHasSel(canvas.getActiveObjects().length > 0);
        canvas.on('selection:created', onSelChange);
        canvas.on('selection:updated', onSelChange);
        canvas.on('selection:cleared', () => setHasSel(false));

        // Auto-save
        canvas.on('object:modified', () => { saveHistory(); saveToSpritePreview(); });
        canvas.on('path:created', () => { saveHistory(); saveToSpritePreview(); });

        loadCostume(costume, canvas);

        return () => { try { canvas.dispose(); } catch (_) { } };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [activeIdx, isVector]);

    // ── Vector: shape-drawing mouse handlers (re-attach on tool change) ───────
    useEffect(() => {
        const canvas = fabricRef.current;
        if (!canvas || !isVector) return;

        // Free-draw (brush) mode
        canvas.isDrawingMode = tool === 'brush';
        if (tool === 'brush') {
            const brush = new fabric.PencilBrush(canvas);
            brush.color = strokeColor;
            brush.width = strokeWidth;
            canvas.freeDrawingBrush = brush;
        }

        // Object interactivity
        const canSelect = tool === 'select' || tool === 'reshape';
        canvas.getObjects().forEach(o => {
            o.selectable = canSelect;
            o.evented = canSelect;
        });
        if (!canSelect) canvas.discardActiveObject();
        canvas.renderAll();

        // ── Mouse handlers ──
        const onDown = (opt) => {
            if (tool === 'select' || tool === 'reshape' || tool === 'brush') return;
            const ptr = canvas.getPointer(opt.e);
            drawState.current = { active: true, startX: ptr.x, startY: ptr.y, shape: null };

            if (tool === 'eraser') {
                const target = canvas.findTarget(opt.e);
                if (target) { canvas.remove(target); saveHistory(); saveToSpritePreview(); }
                drawState.current.active = false;
                return;
            }
            // BUG FIX 1: Always set fill (interior color), never stroke.
            // Matches Scratch's paint-bucket which always recolors the interior/fill.
            if (tool === 'fill') {
                const target = canvas.findTarget(opt.e);
                if (target) {
                    target.set('fill', fillColor);
                    canvas.renderAll(); saveHistory(); saveToSpritePreview();
                }
                drawState.current.active = false;
                return;
            }
            if (tool === 'text') {
                const shape = new fabric.IText('Text', {
                    left: ptr.x, top: ptr.y,
                    fill: fillColor,
                    fontSize: Math.max(18, strokeWidth * 6),
                    selectable: false,
                });
                canvas.add(shape);
                setTool('select');
                canvas.setActiveObject(shape);
                shape.enterEditing(); shape.selectAll();
                canvas.renderAll();
                drawState.current.active = false;
                return;
            }

            let shape = null;
            const opts = { left: ptr.x, top: ptr.y, fill: fillColor, stroke: strokeColor, strokeWidth, selectable: false };
            if (tool === 'rect') shape = new fabric.Rect({ ...opts, width: 1, height: 1 });
            if (tool === 'circle') shape = new fabric.Circle({ ...opts, radius: 1 });
            if (tool === 'line') shape = new fabric.Line([ptr.x, ptr.y, ptr.x, ptr.y], { stroke: strokeColor, strokeWidth, selectable: false });
            if (shape) { drawState.current.shape = shape; canvas.add(shape); }
        };

        const onMove = (opt) => {
            if (!drawState.current.active || !drawState.current.shape) return;
            const ptr = canvas.getPointer(opt.e);
            const { startX, startY, shape } = drawState.current;
            if (tool === 'rect') {
                shape.set({
                    width: Math.abs(ptr.x - startX),
                    height: Math.abs(ptr.y - startY),
                    originX: ptr.x < startX ? 'right' : 'left',
                    originY: ptr.y < startY ? 'bottom' : 'top',
                });
            }
            if (tool === 'circle') {
                const r = Math.hypot(ptr.x - startX, ptr.y - startY) / 2;
                shape.set({
                    radius: Math.max(1, r),
                    originX: ptr.x < startX ? 'right' : 'left',
                    originY: ptr.y < startY ? 'bottom' : 'top',
                });
            }
            if (tool === 'line') shape.set({ x2: ptr.x, y2: ptr.y });
            canvas.renderAll();
        };

        const onUp = () => {
            if (!drawState.current.active) return;
            drawState.current.active = false;
            if (drawState.current.shape) {
                drawState.current.shape.setCoords();
                drawState.current.shape = null;
                saveHistory(); saveToSpritePreview();
            }
        };

        canvas.on('mouse:down', onDown);
        canvas.on('mouse:move', onMove);
        canvas.on('mouse:up', onUp);
        return () => {
            canvas.off('mouse:down', onDown);
            canvas.off('mouse:move', onMove);
            canvas.off('mouse:up', onUp);
        };
    }, [tool, fillColor, strokeColor, strokeWidth, isVector, saveHistory, saveToSpritePreview, fabricRef, setTool]);

    // ── Vector: undo / redo ───────────────────────────────────────────────────
    const handleUndo = useCallback(() => {
        if (!fabricRef.current || undoStack.current.length <= 1) return;
        isHistoryAction.current = true;
        redoStack.current.push(undoStack.current.pop());
        const prev = undoStack.current[undoStack.current.length - 1];
        fabricRef.current.loadFromJSON(prev).then(() => {
            fabricRef.current.renderAll();
            isHistoryAction.current = false;
            saveToSpritePreview();
        });
    }, [saveToSpritePreview, fabricRef, undoStack, redoStack, isHistoryAction]);

    const handleRedo = useCallback(() => {
        if (!fabricRef.current || !redoStack.current.length) return;
        isHistoryAction.current = true;
        const next = redoStack.current.pop();
        undoStack.current.push(next);
        fabricRef.current.loadFromJSON(next).then(() => {
            fabricRef.current.renderAll();
            isHistoryAction.current = false;
            saveToSpritePreview();
        });
    }, [saveToSpritePreview, fabricRef, undoStack, redoStack, isHistoryAction]);

    const handleDeleteSel = useCallback(() => {
        if (!fabricRef.current) return;
        fabricRef.current.getActiveObjects().forEach(o => fabricRef.current.remove(o));
        fabricRef.current.discardActiveObject();
        saveHistory(); saveToSpritePreview();
    }, [saveHistory, saveToSpritePreview, fabricRef]);

    const handleCopy = useCallback(async () => {
        if (!fabricRef.current) return;
        const active = fabricRef.current.getActiveObject();
        if (!active) return;
        const cloned = await active.clone();
        clipboardRef.current = cloned;
    }, [fabricRef, clipboardRef]);

    const handlePaste = useCallback(async () => {
        if (!fabricRef.current || !clipboardRef.current) return;
        const cloned = await clipboardRef.current.clone();
        fabricRef.current.discardActiveObject();
        cloned.set({ left: cloned.left + 10, top: cloned.top + 10, evented: true });
        if (cloned.type === 'activeSelection') {
            cloned.canvas = fabricRef.current;
            cloned.forEachObject(obj => fabricRef.current.add(obj));
            cloned.setCoords();
        } else {
            fabricRef.current.add(cloned);
        }
        fabricRef.current.setActiveObject(cloned);
        fabricRef.current.requestRenderAll();
        saveHistory(); saveToSpritePreview();
    }, [saveHistory, saveToSpritePreview, fabricRef, clipboardRef]);

    const groupSel = useCallback(() => {
        const c = fabricRef.current; if (!c) return;
        const a = c.getActiveObject();
        if (a?.type === 'activeSelection') { a.toGroup(); c.requestRenderAll(); saveHistory(); }
    }, [saveHistory, fabricRef]);

    const ungroupSel = useCallback(() => {
        const c = fabricRef.current; if (!c) return;
        const a = c.getActiveObject();
        if (a?.type === 'group') { a.toActiveSelection(); c.requestRenderAll(); saveHistory(); }
    }, [saveHistory, fabricRef]);

    const sendLayer = useCallback((dir) => {
        const c = fabricRef.current; if (!c) return;
        const obj = c.getActiveObject(); if (!obj) return;
        const layerMap = {
            front: 'bringToFront',
            forward: 'bringForward',
            backward: 'sendBackwards',
            back: 'sendToBack'
        };
        c[layerMap[dir]](obj);
        c.requestRenderAll(); saveHistory();
    }, [saveHistory, fabricRef]);

    const flip = useCallback((axis) => {
        const c = fabricRef.current; if (!c) return;
        const objs = c.getActiveObjects().length ? c.getActiveObjects() : c.getObjects();
        objs.forEach(o => axis === 'h' ? o.set('flipX', !o.flipX) : o.set('flipY', !o.flipY));
        c.requestRenderAll(); saveHistory(); saveToSpritePreview();
    }, [saveHistory, saveToSpritePreview, fabricRef]);

    return {
        saveHistory,
        saveToSpritePreview,
        handleUndo,
        handleRedo,
        handleDeleteSel,
        handleCopy,
        handlePaste,
        groupSel,
        ungroupSel,
        sendLayer,
        flip,
    };
}
