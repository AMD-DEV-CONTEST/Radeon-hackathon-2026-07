import { useEffect } from 'react';
import { BACKDROPS } from './constants';
import { drawCat } from './catRenderer';

export function useStageAnimation({
    isMounted, canvasRef, penCanvas, bdropRef,
    projectBackdropsRef, scratchBackdrops, clones, spritesRef, activeSpriteRef,
    customSprite, sp, setSpInfo
}) {
    useEffect(() => {
        isMounted.current = true;
        const pc = document.createElement('canvas');
        pc.width = 480; pc.height = 360;
        penCanvas.current = pc;

        let frameId;
        function drawFrame() {
            const cv = canvasRef.current; if (!cv) return;
            const ctx = cv.getContext('2d');
            ctx.globalAlpha = 1.0;
            ctx.filter = 'none';
            const bd = BACKDROPS[bdropRef.current]
                || projectBackdropsRef.current.find(b => b.id === bdropRef.current)
                || scratchBackdrops.find(b => b.id === bdropRef.current)
                || BACKDROPS[0];
            
            let drawn = false;
            if (bd.img && bd.img.complete && bd.img.naturalHeight !== 0) {
                try {
                    ctx.drawImage(bd.img, 0, 0, cv.width, cv.height);
                    drawn = true;
                } catch (e) {
                    console.error("Error drawing backdrop image:", e);
                }
            }
            /* SOLID COLOR FALLBACK */
            
            if (!drawn) {
                ctx.fillStyle = bd.color || '#F0F9FF';
                ctx.fillRect(0, 0, cv.width, cv.height);
            }
            if (penCanvas.current) ctx.drawImage(penCanvas.current, 0, 0);
            
            clones.current.forEach(c => drawCat(ctx, c, c.img || customSprite.current));
            spritesRef.current.forEach(s => { if (s.id !== activeSpriteRef.current) drawCat(ctx, s, s.img); });
            const currActive = spritesRef.current.find(s => s.id === activeSpriteRef.current);
            if (currActive) drawCat(ctx, currActive, currActive.img);
        }
        function loop() {
            try { drawFrame(); } catch (e) { }
            frameId = requestAnimationFrame(loop);
        }
        frameId = requestAnimationFrame(loop);
        
        const infoTimer = setInterval(() => {
            if (!isMounted.current) return;
            const s = sp.current;
            setSpInfo({ x: Math.round(s.x - 240), y: Math.round(-(s.y - 180)), dir: Math.round(s.dir), size: s.size || 100 });
            if (s._penDown) {
                const prevX = s._penLastX ?? s.x, prevY = s._penLastY ?? s.y;
                if (Math.hypot(s.x - prevX, s.y - prevY) > 0.3 && penCanvas.current) {
                    const pctx = penCanvas.current.getContext('2d');
                    pctx.beginPath(); pctx.moveTo(prevX, prevY); pctx.lineTo(s.x, s.y);
                    pctx.strokeStyle = s._penColor || '#ff0000';
                    pctx.lineWidth = s._penSize || 3;
                    pctx.lineCap = 'round'; pctx.stroke();
                }
                s._penLastX = s.x; s._penLastY = s.y;
            }
        }, 100);
        
        return () => { isMounted.current = false; cancelAnimationFrame(frameId); clearInterval(infoTimer); };
        // eslint-disable-next-line
    }, []);
}
