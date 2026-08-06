
import {
    useCallback,
    useEffect,
} from 'react';
import { getCleanAssetUrl } from '../../constants';

/** Convert a CSS hex color string to [r, g, b, a] array for ImageData manipulation */
function hexToRgba(hex) {
    if (hex === 'transparent') return [0, 0, 0, 0];
    const h = hex.replace('#', '');
    if (h.length === 3) {
        return [
            parseInt(h[0] + h[0], 16),
            parseInt(h[1] + h[1], 16),
            parseInt(h[2] + h[2], 16),
            255
        ];
    }
    if (h.length === 6) {
        return [
            parseInt(h.substring(0, 2), 16),
            parseInt(h.substring(2, 4), 16),
            parseInt(h.substring(4, 6), 16),
            255
        ];
    }
    return [0, 0, 0, 255];
}

/**
 * useBitmapCanvas – all bitmap / 2D-canvas-related logic for the Costumes editor.
 *
 * Accepts shared refs and state from the parent component; returns action
 * callbacks that the parent wires into the toolbar UI and keyboard shortcuts.
 */
export function useBitmapCanvas({
    costume, sprite, isVector, cvRef, bitmapRef, bmDraw,
    undoStack, redoStack, isHistoryAction,
    tool, fillColor, strokeWidth, _force, activeIdx,
}) {
    /** Save current bitmap canvas → costume thumbnail */
    const saveBitmapToSprite = useCallback(() => {
        if (!bitmapRef.current || !costume) return;
        const ctx = bitmapRef.current;
        const imageData = ctx.getImageData(0, 0, 480, 360);
        /* MUTATION: sprite is mutated directly here */
        costume.bitmapData = imageData;
        const dataUrl = cvRef.current.toDataURL('image/png');
        const img = new Image();
        img.src = dataUrl;
        img.onload = () => { costume.img = img; sprite.img = img; _force(x => x + 1); };
    }, [costume, sprite, _force, bitmapRef, cvRef]);

    /** Push bitmap snapshot to undo stack */
    const saveBitmapHistory = useCallback(() => {
        if (!bitmapRef.current || isHistoryAction.current) return;
        const snap = bitmapRef.current.getImageData(0, 0, 480, 360);
        undoStack.current.push(snap);
        if (undoStack.current.length > 30) undoStack.current.shift();
        redoStack.current = [];
    }, [bitmapRef, isHistoryAction, undoStack, redoStack]);

    const bitmapUndo = useCallback(() => {
        if (!bitmapRef.current || undoStack.current.length <= 1) return;
        isHistoryAction.current = true;
        redoStack.current.push(undoStack.current.pop());
        const prev = undoStack.current[undoStack.current.length - 1];
        bitmapRef.current.putImageData(prev, 0, 0);
        saveBitmapToSprite();
        isHistoryAction.current = false;
    }, [saveBitmapToSprite, bitmapRef, undoStack, redoStack, isHistoryAction]);

    const bitmapRedo = useCallback(() => {
        if (!bitmapRef.current || !redoStack.current.length) return;
        isHistoryAction.current = true;
        const next = redoStack.current.pop();
        undoStack.current.push(next);
        bitmapRef.current.putImageData(next, 0, 0);
        saveBitmapToSprite();
        isHistoryAction.current = false;
    }, [saveBitmapToSprite, bitmapRef, undoStack, redoStack, isHistoryAction]);

    /** Initialise bitmap canvas with rasterised image */
    useEffect(() => {
        if (isVector || !cvRef.current) return;
        const ctx = cvRef.current.getContext('2d');
        bitmapRef.current = ctx;

        // Clear
        ctx.clearRect(0, 0, 480, 360);

        // Draw existing bitmap data or rasterise from img
        if (costume?.bitmapData) {
            ctx.putImageData(costume.bitmapData, 0, 0);
        } else if (costume?.img?.src) {
            const img = new Image();
            img.crossOrigin = 'anonymous';
            img.onload = () => {
                const scale = Math.min(380 / img.width, 300 / img.height, 1);
                const w = img.width * scale;
                const h = img.height * scale;
                ctx.drawImage(img, (480 - w) / 2, (360 - h) / 2, w, h);
                saveBitmapToSprite();
            };
            img.src = getCleanAssetUrl(costume.img.src);
        }

        undoStack.current = [ctx.getImageData(0, 0, 480, 360)];
        redoStack.current = [];
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [activeIdx, isVector]);

    /** Bitmap canvas mouse handlers */
    useEffect(() => {
        if (isVector || !cvRef.current) return;
        const canvas = cvRef.current;
        const getPos = (e) => {
            const rect = canvas.getBoundingClientRect();
            const scaleX = 480 / rect.width;
            const scaleY = 360 / rect.height;
            const clientX = e.touches ? e.touches[0].clientX : e.clientX;
            const clientY = e.touches ? e.touches[0].clientY : e.clientY;
            return { x: (clientX - rect.left) * scaleX, y: (clientY - rect.top) * scaleY };
        };

        const onDown = (e) => {
            const ctx = bitmapRef.current; if (!ctx) return;
            const { x, y } = getPos(e);

            // BUG FIX 2: Flood-fill (paint bucket) for bitmap mode.
            // BFS-based flood fill on ImageData: fills all connected pixels of the
            // same color as the clicked pixel with fillColor.
            if (tool === 'fill') {
                const startX = Math.floor(x);
                const startY = Math.floor(y);
                if (startX >= 0 && startX < 480 && startY >= 0 && startY < 360) {
                    const imgData = ctx.getImageData(0, 0, 480, 360);
                    const data = imgData.data;

                    const targetIdx = (startY * 480 + startX) * 4;
                    const tr = data[targetIdx];
                    const tg = data[targetIdx + 1];
                    const tb = data[targetIdx + 2];
                    const ta = data[targetIdx + 3];

                    const [fr, fg, fb, fa] = hexToRgba(fillColor);

                    if (tr !== fr || tg !== fg || tb !== fb || ta !== fa) {
                        const stack = [[startX, startY]];
                        const visited = new Uint8Array(480 * 360);
                        visited[startY * 480 + startX] = 1;

                        while (stack.length > 0) {
                            const [cx, cy] = stack.pop();
                            const idx = (cy * 480 + cx) * 4;

                            data[idx] = fr;
                            data[idx + 1] = fg;
                            data[idx + 2] = fb;
                            data[idx + 3] = fa;

                            const neighbors = [
                                [cx + 1, cy],
                                [cx - 1, cy],
                                [cx, cy + 1],
                                [cx, cy - 1]
                            ];

                            for (const [nx, ny] of neighbors) {
                                if (nx >= 0 && nx < 480 && ny >= 0 && ny < 360) {
                                    const nIdx = ny * 480 + nx;
                                    if (!visited[nIdx]) {
                                        const pIdx = nIdx * 4;
                                        if (data[pIdx] === tr &&
                                            data[pIdx + 1] === tg &&
                                            data[pIdx + 2] === tb &&
                                            data[pIdx + 3] === ta) {
                                            visited[nIdx] = 1;
                                            stack.push([nx, ny]);
                                        }
                                    }
                                }
                            }
                        }
                        ctx.putImageData(imgData, 0, 0);
                        saveBitmapHistory();
                        saveBitmapToSprite();
                    }
                }
                return;
            }

            bmDraw.current.painting = true;
            bmDraw.current.lastX = x;
            bmDraw.current.lastY = y;
            bmDraw.current.startX = x;
            bmDraw.current.startY = y;
            bmDraw.current.snapshot = ctx.getImageData(0, 0, 480, 360);

            if (tool === 'brush') {
                ctx.beginPath();
                ctx.arc(x, y, strokeWidth / 2, 0, Math.PI * 2);
                ctx.fillStyle = fillColor;
                ctx.fill();
            }
            if (tool === 'eraser') {
                ctx.clearRect(x - strokeWidth, y - strokeWidth, strokeWidth * 2, strokeWidth * 2);
            }
        };

        const onMove = (e) => {
            if (!bmDraw.current.painting) return;
            const ctx = bitmapRef.current; if (!ctx) return;
            const { x, y } = getPos(e);

            if (tool === 'brush') {
                ctx.beginPath();
                ctx.moveTo(bmDraw.current.lastX, bmDraw.current.lastY);
                ctx.lineTo(x, y);
                ctx.strokeStyle = fillColor;
                ctx.lineWidth = strokeWidth;
                ctx.lineCap = 'round';
                ctx.lineJoin = 'round';
                ctx.stroke();
                bmDraw.current.lastX = x;
                bmDraw.current.lastY = y;
                return;
            }
            if (tool === 'eraser') {
                ctx.clearRect(x - strokeWidth, y - strokeWidth, strokeWidth * 2, strokeWidth * 2);
                bmDraw.current.lastX = x; bmDraw.current.lastY = y;
                return;
            }
            // Shape preview tools – restore snapshot then draw
            if (!bmDraw.current.snapshot) return;
            ctx.putImageData(bmDraw.current.snapshot, 0, 0);
            const sx = bmDraw.current.startX, sy = bmDraw.current.startY;

            if (tool === 'line') {
                ctx.beginPath(); ctx.moveTo(sx, sy); ctx.lineTo(x, y);
                ctx.strokeStyle = fillColor; ctx.lineWidth = strokeWidth; ctx.lineCap = 'round'; ctx.stroke();
            }
            if (tool === 'circle') {
                const rx = Math.abs(x - sx) / 2, ry = Math.abs(y - sy) / 2;
                const cx = (sx + x) / 2, cy = (sy + y) / 2;
                ctx.beginPath(); ctx.ellipse(cx, cy, rx, ry, 0, 0, Math.PI * 2);
                ctx.fillStyle = fillColor; ctx.fill();
            }
            if (tool === 'rect') {
                ctx.fillStyle = fillColor;
                ctx.fillRect(Math.min(sx, x), Math.min(sy, y), Math.abs(x - sx), Math.abs(y - sy));
            }
        };

        const onUp = (e) => {
            if (!bmDraw.current.painting) return;
            bmDraw.current.painting = false;
            const ctx = bitmapRef.current; if (!ctx) return;
            const { x, y } = getPos(e);
            const sx = bmDraw.current.startX, sy = bmDraw.current.startY;

            if (tool === 'text') {
                const text = prompt('Enter text:') || '';
                if (text) {
                    ctx.font = `bold ${Math.max(18, strokeWidth * 6)}px sans-serif`;
                    ctx.fillStyle = fillColor;
                    ctx.fillText(text, x, y);
                }
            }
            if (tool === 'circle') {
                // Already drawn in onMove
                if (bmDraw.current.snapshot) {
                    ctx.putImageData(bmDraw.current.snapshot, 0, 0);
                    const rx = Math.abs(x - sx) / 2, ry = Math.abs(y - sy) / 2;
                    ctx.beginPath(); ctx.ellipse((sx + x) / 2, (sy + y) / 2, rx, ry, 0, 0, Math.PI * 2);
                    ctx.fillStyle = fillColor; ctx.fill();
                }
            }
            if (tool === 'rect') {
                if (bmDraw.current.snapshot) {
                    ctx.putImageData(bmDraw.current.snapshot, 0, 0);
                    ctx.fillStyle = fillColor;
                    ctx.fillRect(Math.min(sx, x), Math.min(sy, y), Math.abs(x - sx), Math.abs(y - sy));
                }
            }
            saveBitmapHistory();
            saveBitmapToSprite();
            bmDraw.current.snapshot = null;
        };

        canvas.addEventListener('mousedown', onDown);
        canvas.addEventListener('mousemove', onMove);
        canvas.addEventListener('mouseup', onUp);
        canvas.addEventListener('touchstart', onDown, { passive: true });
        canvas.addEventListener('touchmove', onMove, { passive: true });
        canvas.addEventListener('touchend', onUp);
        return () => {
            canvas.removeEventListener('mousedown', onDown);
            canvas.removeEventListener('mousemove', onMove);
            canvas.removeEventListener('mouseup', onUp);
            canvas.removeEventListener('touchstart', onDown);
            canvas.removeEventListener('touchmove', onMove);
            canvas.removeEventListener('touchend', onUp);
        };
    }, [isVector, tool, fillColor, strokeWidth, saveBitmapHistory, saveBitmapToSprite, cvRef, bitmapRef, bmDraw]);

    // Bitmap flip helpers
    const bitmapFlip = useCallback((axis) => {
        const canvas = cvRef.current; if (!canvas) return;
        const ctx = canvas.getContext('2d');
        const tmp = document.createElement('canvas');
        tmp.width = 480; tmp.height = 360;
        const tCtx = tmp.getContext('2d');
        tCtx.save();
        if (axis === 'h') { tCtx.translate(480, 0); tCtx.scale(-1, 1); }
        else { tCtx.translate(0, 360); tCtx.scale(1, -1); }
        tCtx.drawImage(canvas, 0, 0);
        tCtx.restore();
        ctx.clearRect(0, 0, 480, 360);
        ctx.drawImage(tmp, 0, 0);
        saveBitmapHistory(); saveBitmapToSprite();
    }, [saveBitmapHistory, saveBitmapToSprite, cvRef]);

    return {
        saveBitmapToSprite,
        bitmapUndo,
        bitmapRedo,
        bitmapFlip,
    };
}
