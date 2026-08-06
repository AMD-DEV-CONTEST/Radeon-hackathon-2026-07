/**
 * premiumBackdrops.js
 * 
 * Procedural Vector Art Generator for Magic Studio Backdrops.
 * Draws premium, highly realistic, kid-friendly vector illustrations
 * directly onto the HTML5 Canvas. Zero network latency, zero CORS errors!
 */

export function drawPremiumBackdrop(ctx, name, width = 480, height = 360) {
    const key = (name || '').toLowerCase().trim();

    ctx.save();
    
    // --- 1. BEDROOM 1 ---
    if (key.includes('bedroom')) {
        // Soft peach/wheat wall
        const wallGrad = ctx.createLinearGradient(0, 0, 0, height * 0.7);
        wallGrad.addColorStop(0, '#FFE8D6');
        wallGrad.addColorStop(1, '#F5C6A5');
        ctx.fillStyle = wallGrad;
        ctx.fillRect(0, 0, width, height * 0.7);

        // Cozy wooden floorboards
        ctx.fillStyle = '#8B5A2B';
        ctx.fillRect(0, height * 0.7, width, height * 0.3);
        ctx.strokeStyle = '#5C3A21';
        ctx.lineWidth = 1.5;
        for (let i = 0; i <= width; i += 40) {
            ctx.beginPath();
            ctx.moveTo(i, height * 0.7);
            ctx.lineTo(i - 40 + (i * 0.1), height);
            ctx.stroke();
        }

        // Bed frame & headboard
        ctx.fillStyle = '#6E473B'; // Wood headboard
        ctx.fillRect(40, height * 0.5, 30, height * 0.3);
        ctx.fillStyle = '#4F302B'; // Bed base
        ctx.fillRect(70, height * 0.68, width - 110, height * 0.1);

        // Fluffy blue mattress/blanket
        const blanketGrad = ctx.createLinearGradient(70, height * 0.58, width - 40, height * 0.58);
        blanketGrad.addColorStop(0, '#6366F1');
        blanketGrad.addColorStop(1, '#4F46E5');
        ctx.fillStyle = blanketGrad;
        ctx.beginPath();
        ctx.roundRect(70, height * 0.58, width - 110, height * 0.12, [8, 20, 0, 0]);
        ctx.fill();

        // White pillow
        ctx.fillStyle = '#FFFFFF';
        ctx.beginPath();
        ctx.roundRect(80, height * 0.53, 60, 25, 8);
        ctx.fill();

        // Glowing lamp on a bedside table
        ctx.fillStyle = '#5C3A21'; // table
        ctx.fillRect(width - 70, height * 0.58, 40, height * 0.2);
        
        // Lamp glow
        const glow = ctx.createRadialGradient(width - 50, height * 0.48, 5, width - 50, height * 0.48, 50);
        glow.addColorStop(0, 'rgba(254, 240, 138, 0.8)');
        glow.addColorStop(1, 'rgba(254, 240, 138, 0)');
        ctx.fillStyle = glow;
        ctx.beginPath();
        ctx.arc(width - 50, height * 0.48, 50, 0, Math.PI * 2);
        ctx.fill();

        ctx.fillStyle = '#F59E0B'; // Lamp shade
        ctx.beginPath();
        ctx.moveTo(width - 65, height * 0.52);
        ctx.lineTo(width - 35, height * 0.52);
        ctx.lineTo(width - 40, height * 0.46);
        ctx.lineTo(width - 60, height * 0.46);
        ctx.closePath();
        ctx.fill();

    // --- 2. JUNGLE / FOREST ---
    } else if (key.includes('jungle') || key.includes('forest')) {
        // Deep forest twilight gradient
        const skyGrad = ctx.createLinearGradient(0, 0, 0, height);
        skyGrad.addColorStop(0, '#064E3B');
        skyGrad.addColorStop(0.5, '#022C22');
        skyGrad.addColorStop(1, '#065F46');
        ctx.fillStyle = skyGrad;
        ctx.fillRect(0, 0, width, height);

        // Sun shafts / light rays
        ctx.fillStyle = 'rgba(254, 240, 138, 0.07)';
        for (let i = 0; i < 3; i++) {
            ctx.beginPath();
            ctx.moveTo(80 + i * 120, 0);
            ctx.lineTo(160 + i * 120, 0);
            ctx.lineTo(300 + i * 120, height);
            ctx.lineTo(100 + i * 120, height);
            ctx.closePath();
            ctx.fill();
        }

        // Distant tree layers (silhouettes)
        ctx.fillStyle = 'rgba(4, 47, 31, 0.4)';
        for (let i = 0; i < width; i += 60) {
            ctx.beginPath();
            ctx.arc(i + 30, height * 0.6, 50, 0, Math.PI * 2);
            ctx.fill();
        }

        // Layer of tree trunks
        ctx.fillStyle = '#451A03'; // Brown wood
        const trunks = [40, 160, 280, 400];
        trunks.forEach(x => {
            ctx.fillRect(x, 0, 24, height);
            // Vine curves
            ctx.strokeStyle = '#047857';
            ctx.lineWidth = 2.5;
            ctx.beginPath();
            ctx.moveTo(x + 12, 0);
            ctx.quadraticCurveTo(x - 20, height * 0.3, x + 12, height * 0.6);
            ctx.quadraticCurveTo(x + 40, height * 0.8, x + 12, height);
            ctx.stroke();
        });

        // Lush green leaves overlapping
        ctx.fillStyle = '#065F46';
        ctx.beginPath();
        ctx.arc(60, 40, 90, 0, Math.PI * 2);
        ctx.arc(220, 30, 100, 0, Math.PI * 2);
        ctx.arc(380, 50, 90, 0, Math.PI * 2);
        ctx.arc(width, 40, 80, 0, Math.PI * 2);
        ctx.fill();

        ctx.fillStyle = '#10B981'; // Highlights
        ctx.beginPath();
        ctx.arc(70, 20, 60, 0, Math.PI * 2);
        ctx.arc(230, 10, 70, 0, Math.PI * 2);
        ctx.arc(390, 30, 60, 0, Math.PI * 2);
        ctx.fill();

        // Fireflies / glowing spores
        for (let i = 0; i < 12; i++) {
            const fx = (i * 97 + 34) % width;
            const fy = (i * 123 + 150) % (height - 100);
            const size = (i % 3) + 2;
            const glow = ctx.createRadialGradient(fx, fy, 1, fx, fy, size * 4);
            glow.addColorStop(0, 'rgba(110, 231, 183, 1)');
            glow.addColorStop(1, 'rgba(110, 231, 183, 0)');
            ctx.fillStyle = glow;
            ctx.beginPath();
            ctx.arc(fx, fy, size * 4, 0, Math.PI * 2);
            ctx.fill();
        }

    // --- 3. SAVANNA / SAFARI ---
    } else if (key.includes('savanna') || key.includes('safari')) {
        // Sunset gradient
        const sunset = ctx.createLinearGradient(0, 0, 0, height);
        sunset.addColorStop(0, '#7C2D12'); // Dark brown-red
        sunset.addColorStop(0.3, '#C2410C'); // Orange
        sunset.addColorStop(0.6, '#F59E0B'); // Yellow
        sunset.addColorStop(0.8, '#FEF08A'); // Pale yellow
        ctx.fillStyle = sunset;
        ctx.fillRect(0, 0, width, height);

        // Big glowing sun
        const sunGlow = ctx.createRadialGradient(width * 0.7, height * 0.55, 10, width * 0.7, height * 0.55, 80);
        sunGlow.addColorStop(0, '#FFFFFF');
        sunGlow.addColorStop(0.3, '#FEF08A');
        sunGlow.addColorStop(1, 'rgba(245, 158, 11, 0)');
        ctx.fillStyle = sunGlow;
        ctx.beginPath();
        ctx.arc(width * 0.7, height * 0.55, 80, 0, Math.PI * 2);
        ctx.fill();

        // Distant mountains silhouette
        ctx.fillStyle = '#431407';
        ctx.beginPath();
        ctx.moveTo(0, height * 0.75);
        ctx.lineTo(80, height * 0.68);
        ctx.lineTo(180, height * 0.73);
        ctx.lineTo(310, height * 0.65);
        ctx.lineTo(440, height * 0.75);
        ctx.lineTo(width, height * 0.7);
        ctx.lineTo(width, height);
        ctx.lineTo(0, height);
        ctx.closePath();
        ctx.fill();

        // Savanna soil layer
        ctx.fillStyle = '#1C0A00'; // Deep African soil silhouette
        ctx.beginPath();
        ctx.ellipse(width * 0.3, height * 0.85, width * 0.5, height * 0.15, 0, 0, Math.PI * 2);
        ctx.ellipse(width * 0.8, height * 0.9, width * 0.4, height * 0.15, 0, 0, Math.PI * 2);
        ctx.fill();

        // Iconic Acacia tree silhouette
        ctx.fillStyle = '#1C0A00';
        // Trunk
        ctx.beginPath();
        ctx.moveTo(80, height * 0.85);
        ctx.quadraticCurveTo(85, height * 0.6, 95, height * 0.5);
        ctx.lineTo(105, height * 0.5);
        ctx.quadraticCurveTo(95, height * 0.62, 105, height * 0.85);
        ctx.closePath();
        ctx.fill();
        // Branches
        ctx.beginPath();
        ctx.moveTo(95, height * 0.54);
        ctx.quadraticCurveTo(60, height * 0.48, 40, height * 0.45);
        ctx.lineTo(40, height * 0.42);
        ctx.quadraticCurveTo(70, height * 0.46, 95, height * 0.52);
        
        ctx.moveTo(100, height * 0.52);
        ctx.quadraticCurveTo(130, height * 0.46, 160, height * 0.44);
        ctx.lineTo(160, height * 0.41);
        ctx.quadraticCurveTo(125, height * 0.44, 100, height * 0.5);
        ctx.closePath();
        ctx.fill();
        // Flat tree canopy
        ctx.beginPath();
        ctx.ellipse(40, height * 0.43, 35, 12, 0, 0, Math.PI * 2);
        ctx.ellipse(100, height * 0.48, 55, 14, 0, 0, Math.PI * 2);
        ctx.ellipse(160, height * 0.42, 35, 12, 0, 0, Math.PI * 2);
        ctx.fill();

    // --- 4. BLUE SKY ---
    } else if (key.includes('sky')) {
        // Bright blue sky gradient
        const sky = ctx.createLinearGradient(0, 0, 0, height);
        sky.addColorStop(0, '#0EA5E9');
        sky.addColorStop(0.7, '#38BDF8');
        sky.addColorStop(1, '#BAE6FD');
        ctx.fillStyle = sky;
        ctx.fillRect(0, 0, width, height);

        // Fluffy clouds
        ctx.fillStyle = '#FFFFFF';
        const drawCloud = (cx, cy, scale) => {
            ctx.beginPath();
            ctx.arc(cx, cy, 25 * scale, 0, Math.PI * 2);
            ctx.arc(cx + 20 * scale, cy - 10 * scale, 30 * scale, 0, Math.PI * 2);
            ctx.arc(cx + 45 * scale, cy, 22 * scale, 0, Math.PI * 2);
            ctx.arc(cx + 20 * scale, cy + 10 * scale, 25 * scale, 0, Math.PI * 2);
            ctx.fill();
        };
        drawCloud(80, 100, 1.0);
        drawCloud(280, 80, 1.2);
        drawCloud(400, 140, 0.8);

        // Glowing sun
        ctx.fillStyle = '#F59E0B';
        ctx.beginPath();
        ctx.arc(420, 50, 20, 0, Math.PI * 2);
        ctx.fill();
        // Rays
        ctx.strokeStyle = '#F59E0B';
        ctx.lineWidth = 3;
        for (let a = 0; a < Math.PI * 2; a += Math.PI / 4) {
            ctx.beginPath();
            ctx.moveTo(420 + Math.cos(a) * 28, 50 + Math.sin(a) * 28);
            ctx.lineTo(420 + Math.cos(a) * 40, 50 + Math.sin(a) * 40);
            ctx.stroke();
        }

        // Green grassy hills at the bottom
        ctx.fillStyle = '#10B981';
        ctx.beginPath();
        ctx.ellipse(120, height + 40, width * 0.6, 80, 0, 0, Math.PI * 2);
        ctx.fill();
        ctx.fillStyle = '#059669';
        ctx.beginPath();
        ctx.ellipse(360, height + 30, width * 0.6, 70, 0, 0, Math.PI * 2);
        ctx.fill();

    // --- 5. SPACE / GALAXY ---
    } else if (key.includes('space') || key.includes('galaxy') || key.includes('stars')) {
        // Deep space cosmic gradient
        const space = ctx.createRadialGradient(width/2, height/2, 20, width/2, height/2, width * 0.8);
        space.addColorStop(0, '#1E1B4B'); // Navy purple
        space.addColorStop(0.6, '#0F172A'); // Midnight blue
        space.addColorStop(1, '#020617'); // Pitch black
        ctx.fillStyle = space;
        ctx.fillRect(0, 0, width, height);

        // Cosmic nebula dust
        const nebula = ctx.createRadialGradient(120, 120, 10, 120, 120, 180);
        nebula.addColorStop(0, 'rgba(219, 39, 119, 0.15)'); // Soft pink
        nebula.addColorStop(1, 'rgba(219, 39, 119, 0)');
        ctx.fillStyle = nebula;
        ctx.beginPath();
        ctx.arc(120, 120, 180, 0, Math.PI * 2);
        ctx.fill();

        // Shimmering stars
        ctx.fillStyle = '#FFFFFF';
        for (let i = 0; i < 45; i++) {
            const sx = (i * 149 + 25) % width;
            const sy = (i * 223 + 45) % height;
            const size = (i % 3 === 0) ? 2.5 : 1;
            ctx.beginPath();
            ctx.arc(sx, sy, size, 0, Math.PI * 2);
            ctx.fill();
        }

        // Giant ringed planet (Saturn)
        const px = width * 0.75, py = height * 0.4;
        // Ring back
        ctx.strokeStyle = '#D97706';
        ctx.lineWidth = 10;
        ctx.save();
        ctx.translate(px, py);
        ctx.rotate(-Math.PI / 8);
        ctx.scale(2.2, 0.4);
        ctx.beginPath();
        ctx.arc(0, 0, 30, Math.PI, 2 * Math.PI);
        ctx.stroke();
        ctx.restore();

        // Planet body
        const planetGrad = ctx.createLinearGradient(px - 30, py - 30, px + 30, py + 30);
        planetGrad.addColorStop(0, '#F59E0B');
        planetGrad.addColorStop(1, '#B45309');
        ctx.fillStyle = planetGrad;
        ctx.beginPath();
        ctx.arc(px, py, 26, 0, Math.PI * 2);
        ctx.fill();

        // Ring front
        ctx.strokeStyle = '#FBBF24';
        ctx.lineWidth = 8;
        ctx.save();
        ctx.translate(px, py);
        ctx.rotate(-Math.PI / 8);
        ctx.scale(2.2, 0.4);
        ctx.beginPath();
        ctx.arc(0, 0, 30, 0, Math.PI);
        ctx.stroke();
        ctx.restore();

    // --- 6. UNDERWATER 2 / OCEAN ---
    } else if (key.includes('underwater') || key.includes('ocean')) {
        // Deep ocean water gradient
        const ocean = ctx.createLinearGradient(0, 0, 0, height);
        ocean.addColorStop(0, '#0284C7'); // Cyan water top
        ocean.addColorStop(0.5, '#0369A1');
        ocean.addColorStop(1, '#0C4A6E'); // Deep abyss blue bottom
        ctx.fillStyle = ocean;
        ctx.fillRect(0, 0, width, height);

        // Sunlight light rays
        ctx.fillStyle = 'rgba(255, 255, 255, 0.08)';
        for (let i = 0; i < 4; i++) {
            ctx.beginPath();
            ctx.moveTo(60 + i * 110, 0);
            ctx.lineTo(120 + i * 110, 0);
            ctx.lineTo(240 + i * 110, height);
            ctx.lineTo(140 + i * 110, height);
            ctx.closePath();
            ctx.fill();
        }

        // Bubbles rising up
        ctx.strokeStyle = 'rgba(255, 255, 255, 0.4)';
        ctx.lineWidth = 1;
        for (let i = 0; i < 15; i++) {
            const bx = (i * 87 + 45) % width;
            const by = (i * 153 + 90) % height;
            const radius = (i % 3) * 2.5 + 2;
            ctx.beginPath();
            ctx.arc(bx, by, radius, 0, Math.PI * 2);
            ctx.stroke();
            // Bubble highlight
            ctx.fillStyle = 'rgba(255, 255, 255, 0.3)';
            ctx.beginPath();
            ctx.arc(bx - radius*0.3, by - radius*0.3, radius*0.2, 0, Math.PI * 2);
            ctx.fill();
        }

        // Sandy floor
        ctx.fillStyle = '#EAB308'; // Golden sand
        ctx.beginPath();
        ctx.ellipse(100, height + 20, width * 0.4, 60, 0, 0, Math.PI * 2);
        ctx.ellipse(380, height + 10, width * 0.5, 50, 0, 0, Math.PI * 2);
        ctx.fill();

        // Seaweeds
        ctx.strokeStyle = '#065F46';
        ctx.lineWidth = 5;
        ctx.lineCap = 'round';
        const drawWeed = (wx, wh) => {
            ctx.beginPath();
            ctx.moveTo(wx, height);
            ctx.quadraticCurveTo(wx - 20, height - wh*0.5, wx - 10, height - wh);
            ctx.quadraticCurveTo(wx + 10, height - wh*0.5, wx, height);
            ctx.stroke();
        };
        drawWeed(60, 110);
        drawWeed(80, 140);
        drawWeed(400, 130);
        drawWeed(420, 150);

    // --- 7. NIGHT CITY ---
    } else if (key.includes('city') || key.includes('night')) {
        // Midnight dark sky
        const nightSky = ctx.createLinearGradient(0, 0, 0, height);
        nightSky.addColorStop(0, '#0F172A');
        nightSky.addColorStop(1, '#1E1B4B');
        ctx.fillStyle = nightSky;
        ctx.fillRect(0, 0, width, height);

        // Glowing moon
        ctx.fillStyle = '#F1F5F9';
        ctx.beginPath();
        ctx.arc(100, 80, 25, 0, Math.PI * 2);
        ctx.fill();
        // Moon shadows
        ctx.fillStyle = '#E2E8F0';
        ctx.beginPath();
        ctx.arc(90, 85, 16, 0, Math.PI * 2);
        ctx.fill();

        // City skyline back layer
        ctx.fillStyle = '#1E293B';
        ctx.fillRect(20, height * 0.4, 70, height * 0.6);
        ctx.fillRect(110, height * 0.32, 90, height * 0.68);
        ctx.fillRect(230, height * 0.45, 60, height * 0.55);
        ctx.fillRect(310, height * 0.28, 80, height * 0.72);
        ctx.fillRect(400, height * 0.38, 70, height * 0.62);

        // City skyline front layer
        ctx.fillStyle = '#0F172A';
        ctx.fillRect(50, height * 0.45, 80, height * 0.55);
        ctx.fillRect(160, height * 0.38, 80, height * 0.62);
        ctx.fillRect(260, height * 0.5, 70, height * 0.5);
        ctx.fillRect(350, height * 0.35, 90, height * 0.65);

        // Lit windows (yellow squares)
        ctx.fillStyle = '#FDE047';
        for (let w = 0; w < 40; w++) {
            const wx = (w * 37 + 55) % (width - 60);
            const wy = (w * 53 + 140) % (height - 180) + 140;
            // Check if window is inside building layers
            ctx.fillRect(wx, wy, 4, 6);
        }

    // --- 8. DESERT ---
    } else if (key.includes('desert')) {
        // Hot desert sunset sky
        const desertSky = ctx.createLinearGradient(0, 0, 0, height);
        desertSky.addColorStop(0, '#C2410C'); // Orange-red top
        desertSky.addColorStop(0.5, '#EA580C');
        desertSky.addColorStop(1, '#FBBF24'); // Yellow horizon
        ctx.fillStyle = desertSky;
        ctx.fillRect(0, 0, width, height);

        // Massive orange sun
        ctx.fillStyle = '#FEF08A';
        ctx.beginPath();
        ctx.arc(width/2, height*0.6, 50, 0, Math.PI * 2);
        ctx.fill();

        // Beautiful sand dunes
        ctx.fillStyle = '#D97706'; // Golden sand
        ctx.beginPath();
        ctx.moveTo(0, height);
        ctx.quadraticCurveTo(width * 0.35, height * 0.65, width * 0.7, height * 0.85);
        ctx.quadraticCurveTo(width * 0.85, height * 0.92, width, height * 0.78);
        ctx.lineTo(width, height);
        ctx.lineTo(0, height);
        ctx.closePath();
        ctx.fill();

        ctx.fillStyle = '#B45309'; // Shadow dune
        ctx.beginPath();
        ctx.moveTo(0, height);
        ctx.quadraticCurveTo(width * 0.25, height * 0.85, width * 0.5, height * 0.8);
        ctx.quadraticCurveTo(width * 0.75, height * 0.75, width, height * 0.9);
        ctx.lineTo(width, height);
        ctx.lineTo(0, height);
        ctx.closePath();
        ctx.fill();

        // Cactus silhouette
        ctx.fillStyle = '#451A03';
        // Main stem
        ctx.fillRect(60, height * 0.68, 10, 50);
        ctx.beginPath();
        ctx.arc(65, height * 0.68, 5, 0, Math.PI * 2);
        ctx.fill();
        // Arms
        ctx.fillRect(45, height * 0.73, 20, 6);
        ctx.fillRect(45, height * 0.65, 6, 12);
        ctx.fillRect(65, height * 0.78, 20, 6);
        ctx.fillRect(80, height * 0.7, 6, 12);

    // --- 9. SLOPES / SNOW / MOUNTAIN ---
    } else if (key.includes('slopes') || key.includes('snow') || key.includes('mountain')) {
        // Bright crisp winter sky
        const winterSky = ctx.createLinearGradient(0, 0, 0, height);
        winterSky.addColorStop(0, '#38BDF8'); // Ice blue
        winterSky.addColorStop(1, '#E0F2FE');
        ctx.fillStyle = winterSky;
        ctx.fillRect(0, 0, width, height);

        // Snow-capped mountains
        const drawMountain = (mx, my, mw, mh) => {
            // Mountain base
            ctx.fillStyle = '#64748B'; // slate blue-gray
            ctx.beginPath();
            ctx.moveTo(mx - mw/2, my);
            ctx.lineTo(mx, my - mh);
            ctx.lineTo(mx + mw/2, my);
            ctx.closePath();
            ctx.fill();

            // Snow cap
            ctx.fillStyle = '#F8FAFC';
            ctx.beginPath();
            ctx.moveTo(mx - mw*0.15, my - mh*0.7);
            ctx.lineTo(mx, my - mh);
            ctx.lineTo(mx + mw*0.15, my - mh*0.7);
            ctx.lineTo(mx + mw*0.08, my - mh*0.62);
            ctx.lineTo(mx, my - mh*0.68);
            ctx.lineTo(mx - mw*0.08, my - mh*0.62);
            ctx.closePath();
            ctx.fill();
        };

        drawMountain(120, height * 0.75, 240, 180);
        drawMountain(340, height * 0.75, 300, 220);
        drawMountain(230, height * 0.75, 180, 140);

        // Snowy ground slopes
        ctx.fillStyle = '#FFFFFF';
        ctx.beginPath();
        ctx.moveTo(0, height);
        ctx.quadraticCurveTo(width * 0.4, height * 0.65, width * 0.8, height * 0.78);
        ctx.quadraticCurveTo(width * 0.9, height * 0.8, width, height * 0.72);
        ctx.lineTo(width, height);
        ctx.lineTo(0, height);
        ctx.closePath();
        ctx.fill();

        ctx.fillStyle = '#F1F5F9'; // Shadow slope
        ctx.beginPath();
        ctx.moveTo(0, height);
        ctx.quadraticCurveTo(width * 0.3, height * 0.82, width, height * 0.86);
        ctx.lineTo(width, height);
        ctx.lineTo(0, height);
        ctx.closePath();
        ctx.fill();

    // --- 10. CASTLE ---
    } else if (key.includes('castle')) {
        // Dramatic dark purple-magenta sky
        const twilight = ctx.createLinearGradient(0, 0, 0, height);
        twilight.addColorStop(0, '#4C1D95');
        twilight.addColorStop(1, '#831843');
        ctx.fillStyle = twilight;
        ctx.fillRect(0, 0, width, height);

        // Stars
        ctx.fillStyle = 'rgba(255,255,255,0.7)';
        for (let i = 0; i < 20; i++) {
            ctx.fillRect((i * 179) % width, (i * 97) % (height - 120), 2, 2);
        }

        // Castle silhouette
        ctx.fillStyle = '#1E1B4B'; // Indigo shadow
        ctx.fillRect(width * 0.25, height * 0.45, width * 0.5, height * 0.55); // Main hall
        
        // Left tower
        ctx.fillRect(width * 0.2, height * 0.3, 35, height * 0.7);
        // Right tower
        ctx.fillRect(width * 0.7, height * 0.3, 35, height * 0.7);

        // Castle spires (triangles)
        ctx.beginPath();
        ctx.moveTo(width * 0.2, height * 0.3);
        ctx.lineTo(width * 0.2 + 17.5, height * 0.18);
        ctx.lineTo(width * 0.235, height * 0.3);
        ctx.closePath();
        ctx.fill();

        ctx.beginPath();
        ctx.moveTo(width * 0.7, height * 0.3);
        ctx.lineTo(width * 0.7 + 17.5, height * 0.18);
        ctx.lineTo(width * 0.735, height * 0.3);
        ctx.closePath();
        ctx.fill();

        // Gateway arch
        ctx.fillStyle = '#831843'; // Glowing light gateway
        ctx.beginPath();
        ctx.arc(width * 0.5, height * 0.85, 20, Math.PI, 2 * Math.PI);
        ctx.fill();
        ctx.fillRect(width * 0.5 - 20, height * 0.85, 40, height * 0.15);

    // --- 11. SOCCER / STADIUM ---
    } else if (key.includes('soccer') || key.includes('stadium') || key.includes('field')) {
        // Night sky with stadium glare
        const stadiumSky = ctx.createLinearGradient(0, 0, 0, height);
        stadiumSky.addColorStop(0, '#0F172A');
        stadiumSky.addColorStop(0.7, '#1E293B');
        stadiumSky.addColorStop(1, '#064E3B');
        ctx.fillStyle = stadiumSky;
        ctx.fillRect(0, 0, width, height);

        // Stadium floodlights
        const glow = ctx.createRadialGradient(80, 60, 5, 80, 60, 80);
        glow.addColorStop(0, '#FFFFFF');
        glow.addColorStop(0.3, 'rgba(254, 240, 138, 0.6)');
        glow.addColorStop(1, 'rgba(255, 255, 255, 0)');
        ctx.fillStyle = glow;
        ctx.beginPath();
        ctx.arc(80, 60, 80, 0, Math.PI * 2);
        ctx.arc(width - 80, 60, 80, 0, Math.PI * 2);
        ctx.fill();

        // Green field turf
        ctx.fillStyle = '#15803D';
        ctx.fillRect(0, height * 0.65, width, height * 0.35);

        // Green striping (lines of soccer field)
        ctx.fillStyle = '#166534';
        for (let i = 0; i < width; i += 60) {
            ctx.fillRect(i, height * 0.65, 30, height * 0.35);
        }

        // Penalty area (perspective line mapping)
        ctx.strokeStyle = '#FFFFFF';
        ctx.lineWidth = 3;
        ctx.beginPath();
        ctx.moveTo(width * 0.2, height);
        ctx.lineTo(width * 0.3, height * 0.75);
        ctx.lineTo(width * 0.7, height * 0.75);
        ctx.lineTo(width * 0.8, height);
        ctx.stroke();

    // --- 12. THEATER ---
    } else if (key.includes('theater') || key.includes('stage')) {
        // Stage background
        const back = ctx.createLinearGradient(0, 0, 0, height);
        back.addColorStop(0, '#111827');
        back.addColorStop(1, '#312E81');
        ctx.fillStyle = back;
        ctx.fillRect(0, 0, width, height);

        // Spotlight
        const spot = ctx.createRadialGradient(width/2, height * 0.8, 10, width/2, height * 0.8, 150);
        spot.addColorStop(0, 'rgba(254, 240, 138, 0.4)');
        spot.addColorStop(1, 'rgba(254, 240, 138, 0)');
        ctx.fillStyle = spot;
        ctx.beginPath();
        ctx.arc(width/2, height * 0.8, 150, 0, Math.PI * 2);
        ctx.fill();

        // Wooden stage floor
        ctx.fillStyle = '#78350F'; // Rich dark brown wood
        ctx.fillRect(0, height * 0.75, width, height * 0.25);
        ctx.fillStyle = '#451A03';
        for (let y = height * 0.75; y < height; y += 15) {
            ctx.fillRect(0, y, width, 2);
        }

        // Crimson curtains draped on the sides
        const drapeGrad = ctx.createLinearGradient(0, 0, 80, 0);
        drapeGrad.addColorStop(0, '#7F1D1D');
        drapeGrad.addColorStop(0.5, '#B91C1C');
        drapeGrad.addColorStop(1, '#991B1B');

        ctx.fillStyle = drapeGrad;
        // Left curtain
        ctx.beginPath();
        ctx.moveTo(0, 0);
        ctx.lineTo(80, 0);
        ctx.quadraticCurveTo(50, height * 0.4, 70, height * 0.8);
        ctx.lineTo(0, height * 0.85);
        ctx.closePath();
        ctx.fill();

        // Right curtain
        const drapeRight = ctx.createLinearGradient(width - 80, 0, width, 0);
        drapeRight.addColorStop(0, '#991B1B');
        drapeRight.addColorStop(0.5, '#B91C1C');
        drapeRight.addColorStop(1, '#7F1D1D');
        ctx.fillStyle = drapeRight;
        ctx.beginPath();
        ctx.moveTo(width, 0);
        ctx.lineTo(width - 80, 0);
        ctx.quadraticCurveTo(width - 50, height * 0.4, width - 70, height * 0.8);
        ctx.lineTo(width, height * 0.85);
        ctx.closePath();
        ctx.fill();

    // --- 13. BEACH MALIBU ---
    } else if (key.includes('beach') || key.includes('malibu')) {
        // Bright beach sunset sky
        const sunsetSky = ctx.createLinearGradient(0, 0, 0, height);
        sunsetSky.addColorStop(0, '#FF007F'); // Pink
        sunsetSky.addColorStop(0.4, '#FF7F00'); // Orange
        sunsetSky.addColorStop(0.7, '#FFD166'); // Golden yellow
        sunsetSky.addColorStop(1, '#4ECDC4'); // Turquoise horizon
        ctx.fillStyle = sunsetSky;
        ctx.fillRect(0, 0, width, height);

        // Glowing sun
        ctx.fillStyle = '#FEF08A';
        ctx.beginPath();
        ctx.arc(120, height * 0.55, 30, 0, Math.PI * 2);
        ctx.fill();

        // Turquoise ocean water breaking
        ctx.fillStyle = '#06B6D4';
        ctx.beginPath();
        ctx.moveTo(0, height * 0.72);
        ctx.quadraticCurveTo(width * 0.35, height * 0.68, width * 0.65, height * 0.76);
        ctx.lineTo(width, height * 0.7);
        ctx.lineTo(width, height);
        ctx.lineTo(0, height);
        ctx.closePath();
        ctx.fill();

        // Golden beach sand
        ctx.fillStyle = '#FEF08A';
        ctx.beginPath();
        ctx.moveTo(0, height * 0.8);
        ctx.quadraticCurveTo(width * 0.4, height * 0.78, width * 0.75, height * 0.85);
        ctx.lineTo(width, height * 0.82);
        ctx.lineTo(width, height);
        ctx.lineTo(0, height);
        ctx.closePath();
        ctx.fill();

        // Palm tree silhouette
        ctx.fillStyle = '#1E1B4B';
        // Trunk
        ctx.beginPath();
        ctx.moveTo(width - 50, height);
        ctx.quadraticCurveTo(width - 70, height * 0.6, width - 85, height * 0.4);
        ctx.lineTo(width - 75, height * 0.4);
        ctx.quadraticCurveTo(width - 60, height * 0.6, width - 40, height);
        ctx.closePath();
        ctx.fill();
        // Leaves
        const px = width - 80, py = height * 0.4;
        ctx.beginPath();
        ctx.ellipse(px - 20, py, 30, 10, -Math.PI/6, 0, Math.PI * 2);
        ctx.ellipse(px + 20, py, 30, 10, Math.PI/6, 0, Math.PI * 2);
        ctx.ellipse(px, py - 20, 10, 30, 0, 0, Math.PI * 2);
        ctx.fill();

    // --- 14. DEFAULT / FALLBACK BLUE SKY ---
    } else {
        // High quality premium sky gradient with ground
        const standard = ctx.createLinearGradient(0, 0, 0, height);
        standard.addColorStop(0, '#E0F2FE');
        standard.addColorStop(1, '#7DD3FC');
        ctx.fillStyle = standard;
        ctx.fillRect(0, 0, width, height);

        // Fluffy cloud
        ctx.fillStyle = '#FFFFFF';
        ctx.beginPath();
        ctx.arc(150, 120, 20, 0, Math.PI*2);
        ctx.arc(170, 110, 25, 0, Math.PI*2);
        ctx.arc(195, 120, 20, 0, Math.PI*2);
        ctx.fill();

        // Soft green ground
        ctx.fillStyle = '#86EFAC';
        ctx.beginPath();
        ctx.ellipse(width/2, height + 20, width * 0.7, 70, 0, 0, Math.PI * 2);
        ctx.fill();
    }
    
    ctx.restore();
}
