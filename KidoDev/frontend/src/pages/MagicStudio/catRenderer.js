export function drawCat(ctx, s, customImage) {
    if (!s.visible) return;
    ctx.save();

    // ── Build composite canvas filter from sprite effects ──
    // ghost → globalAlpha, colorHue → hue-rotate, brightness → brightness()
    ctx.globalAlpha = Math.max(0, 1 - (s.ghost || 0) / 100);

    const filterParts = [];
    if (s.colorHue) {
        // Scratch color effect: each unit = ~(360/200) degrees of hue rotation
        const hue = ((s.colorHue % 200) * 1.8).toFixed(1);
        filterParts.push(`hue-rotate(${hue}deg)`);
    }
    if (s.brightness) {
        // Scratch brightness: 0 = normal, positive = brighter, negative = darker
        // Map -100..100 Scratch range to 0..2 CSS brightness multiplier
        const bv = Math.max(0, 1 + (s.brightness || 0) / 100);
        filterParts.push(`brightness(${bv.toFixed(2)})`);
    }
    if (filterParts.length > 0) {
        ctx.filter = filterParts.join(' ');
    }

    ctx.translate(s.x, s.y);
    // Apply rotation only to the image/emoji, keeping speech unrotated
    ctx.rotate(((s.dir - 90) * Math.PI) / 180);
    const sc = (s.size || 100) / 100;
    ctx.scale(sc, sc);

    if (customImage && customImage.complete) {
        const iw = customImage.naturalWidth || 80;
        const ih = customImage.naturalHeight || 80;
        const scale = Math.min(80 / iw, 80 / ih);
        ctx.drawImage(customImage, -iw * scale / 2, -ih * scale / 2, iw * scale, ih * scale);
    } else {
        // Draw emoji
        ctx.font = '70px Fredoka, Arial, sans-serif';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(s.emoji || '⭐', 0, 0);
    }
    // ctx.restore() resets filter and globalAlpha automatically — no bleed to next sprite
    ctx.restore();

    // Speech bubble (unrotated)
    if (s.speech) {
        ctx.save();
        ctx.font = 'bold 14px Fredoka, sans-serif';
        const tw = Math.min(ctx.measureText(s.speech).width, 220);
        const bw = tw + 30, bh = 40, bx = s.x + 25, by = s.y - 75, r2 = 10;
        ctx.fillStyle = 'rgba(255,255,255,0.98)'; ctx.strokeStyle = '#CBD5E1'; ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.moveTo(bx + r2, by); ctx.lineTo(bx + bw - r2, by); ctx.arcTo(bx + bw, by, bx + bw, by + r2, r2);
        ctx.lineTo(bx + bw, by + bh - r2); ctx.arcTo(bx + bw, by + bh, bx + bw - r2, by + bh, r2);
        if (s.bubbleType === 'think') {
            ctx.lineTo(bx + 25, by + bh); ctx.arcTo(bx + 15, by + bh + 14, bx + 5, by + bh + 4, 8);
        } else {
            ctx.lineTo(bx + 25, by + bh); ctx.lineTo(bx + 15, by + bh + 14); ctx.lineTo(bx + 30, by + bh);
        }
        ctx.lineTo(bx + r2, by + bh); ctx.arcTo(bx, by + bh, bx, by + bh - r2, r2);
        ctx.lineTo(bx, by + r2); ctx.arcTo(bx, by, bx + r2, by, r2);
        ctx.closePath(); ctx.fill(); ctx.stroke();
        ctx.fillStyle = '#1E293B'; ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
        ctx.fillText(s.speech, bx + 15, by + bh / 2);
        ctx.restore();
    }
}
