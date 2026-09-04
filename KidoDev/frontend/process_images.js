/**
 * Kido Dev - No-BG Folder Synchronizer
 * Ensures the no_bg_output folder ONLY contains WebP images.
 * Converts existing PNG/JPG to WebP and removes the originals.
 */

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { dirname } from 'path';
import sharp from 'sharp';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

// Configuration
const TARGET_DIR = path.join(__dirname, 'src', 'assets', 'no_bg_output');
const IMAGE_EXTENSIONS = ['.jpg', '.jpeg', '.png', '.bmp', '.tiff'];

async function syncFolder() {
    console.log('--- 🌟 Synchronizing no_bg_output Folder 🌟 ---');

    if (!fs.existsSync(TARGET_DIR)) {
        console.error(`❌ Directory not found: ${TARGET_DIR}`);
        return;
    }

    const files = fs.readdirSync(TARGET_DIR);
    console.log(`📸 Found ${files.length} files in total.`);

    for (const file of files) {
        const fullPath = path.join(TARGET_DIR, file);
        const ext = path.extname(file).toLowerCase();
        const baseName = path.parse(file).name;
        const webpPath = path.join(TARGET_DIR, `${baseName}.webp`);

        // If it's already a WebP, we keep it and move on
        if (ext === '.webp') {
            continue;
        }

        // If it's a convertible image
        if (IMAGE_EXTENSIONS.includes(ext)) {
            try {
                // If the WebP version doesn't exist, create it
                if (!fs.existsSync(webpPath)) {
                    console.log(`🌀 Converting to WebP: ${file}`);
                    await sharp(fullPath)
                        .webp({ quality: 90 })
                        .toFile(webpPath);
                    console.log(`✅ Created: ${baseName}.webp`);
                } else {
                    console.log(`⏩ WebP version already exists for: ${file}`);
                }

                // Delete the non-webp original
                console.log(`🗑️ Removing original: ${file}`);
                fs.unlinkSync(fullPath);

            } catch (error) {
                console.error(`❌ Error processing ${file}:`, error.message);
            }
        } else {
            // Optional: Remove other non-image files if you want it strictly WebP
            // console.log(`ℹ️ Skipping non-image file: ${file}`);
        }
    }

    console.log('--- ✨ Folder is now Synchronized (WebP only) ✨ ---');
}

syncFolder();
