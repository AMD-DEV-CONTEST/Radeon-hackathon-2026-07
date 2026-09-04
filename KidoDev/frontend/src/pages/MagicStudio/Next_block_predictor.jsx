import * as Blockly from 'blockly';
import { BLOCK_DB } from './tutorialEngine';
import { attachHandHint } from "./SpriteGuideAgent";
import { recordHelpRequested } from './helpTracker'; // ← NEW
import { generateLiveHint } from '../../utils/aiClient';

/* ─────────────────────────────────────────────────────────────
   LEVEL CONFIG
───────────────────────────────────────────────────────────── */

function getLevelNumber(lessonId = '') {
    const match = lessonId.match(/(\d+)/);
    return match ? parseInt(match[1], 10) : 1;
}

function getLevelConfig(lessonId) {
    const level = getLevelNumber(lessonId);
    return {
        level,
        enforceOrder: level >= 3,
        hintDetail: 3,
        showTip: true,
        showProgress: true,
    };
}

/* ─────────────────────────────────────────────────────────────
   SUPABASE FETCH
───────────────────────────────────────────────────────────── */

export async function fetchLessonSolution(supabase, lessonId) {
    if (!supabase || !lessonId) return null;

    try {
        const { data, error } = await supabase
            .from('tutor_solutions')
            .select('xml, message, tip')
            .eq('lesson_id', lessonId)
            .order('created_at', { ascending: false })
            .limit(1)
            .single();

        if (error) {
            console.error('❌ Supabase fetch error:', error.message);
            return null;
        }

        console.log('✅ Fetched lesson solution for:', lessonId, data);
        return data;
    } catch (err) {
        console.error('❌ Unexpected fetch error:', err);
        return null;
    }
}

/* ─────────────────────────────────────────────────────────────
   WORKSPACE ANALYSIS
───────────────────────────────────────────────────────────── */

function collectBlockChain(block, visited = new Set()) {
    if (!block || visited.has(block.id)) return [];
    visited.add(block.id);

    let list = [{ id: block.id, type: block.type }];

    const inputList = block.inputList || [];
    for (const input of inputList) {
        if (input.connection) {
            const target = input.connection.targetBlock();
            if (target && !visited.has(target.id)) {
                list = list.concat(collectBlockChain(target, visited));
            }
        }
    }

    const next = block.getNextBlock();
    if (next && !visited.has(next.id)) {
        list = list.concat(collectBlockChain(next, visited));
    }

    return list;
}

export function getWorkspaceState(ws) {
    if (!ws) return null;

    const blocks = ws.getAllBlocks(false);
    const types = blocks.map(b => b.type);
    const rootBlocks = blocks.filter(b => !b.getParent());

    const executionChains = rootBlocks.map(root => collectBlockChain(root));

    const xml = Blockly.Xml.domToText(Blockly.Xml.workspaceToDom(ws));

    return { types, xml, executionChains, blockCount: blocks.length };
}

/* ─────────────────────────────────────────────────────────────
   EXTRACT ORDERED STEPS FROM SOLUTION XML
───────────────────────────────────────────────────────────── */

function extractSolutionSteps(solutionXml) {
    if (!solutionXml) return [];

    const IGNORED_TYPES = ['math_number', 'text'];

    try {
        const dom = Blockly.utils.xml.textToDom(solutionXml);
        const steps = [];

        function walk(node) {
            if (!node) return;
            if (node.getAttribute?.('type')) {
                const type = node.getAttribute('type');
                if (!IGNORED_TYPES.includes(type) && node.tagName !== 'shadow') {
                    steps.push(type);
                }
            }
            let child = node.firstChild;
            while (child) {
                walk(child);
                child = child.nextSibling;
            }
        }

        walk(dom);
        return steps;
    } catch (err) {
        console.error('❌ XML parse failed:', err);
        return [];
    }
}

/* ─────────────────────────────────────────────────────────────
   BUILD HINT MESSAGE
───────────────────────────────────────────────────────────── */

function buildHintMessage(blockType, dbMessage, dbTip, config) {
    const metaKey = getBestKey(blockType);
    const meta = BLOCK_DB[metaKey] || {};
    const label = meta.label || blockType;
    const category = meta.category || 'Unknown';

    if (config.hintDetail === 1) {
        return dbMessage || `Keep going! Try adding a new block.`;
    }

    if (config.hintDetail === 2) {
        const base = `Try adding a block from the ${category} section.`;
        const tip = config.showTip && dbTip ? ` 💡 ${dbTip}` : '';
        return base + tip;
    }

    const base = dbMessage ? dbMessage : `Next: add the "${label}" block.`;
    const tip = config.showTip && dbTip ? ` 💡 ${dbTip}` : '';
    return base + tip;
}

/* ─────────────────────────────────────────────────────────────
   CORE PREDICTOR
───────────────────────────────────────────────────────────── */

export function predictNextBlock(ws, lessonData, lessonId = '') {
    const state = getWorkspaceState(ws);
    if (!state) return fallback();

    if (!lessonData?.xml) {
        console.warn('⚠️ No lesson data → fallback');
        return fallback();
    }

    const config = getLevelConfig(lessonId);
    const solutionSteps = extractSolutionSteps(lessonData.xml);

    console.log('📘 Solution steps:', solutionSteps);
    console.log('🧠 Workspace blocks:', state.types);
    console.log('⚙️  Level config:', config);

    if (!solutionSteps.length) {
        console.warn('⚠️ Empty solution steps → fallback');
        return fallback();
    }

    const total = solutionSteps.length;

    if (config.enforceOrder) {
        const workspaceOrdered = state.executionChains.flat().map(b => b.type);

        for (let i = 0; i < solutionSteps.length; i++) {
            if (workspaceOrdered[i] !== solutionSteps[i]) {
                const blockType = solutionSteps[i];
                const progress = config.showProgress ? ` (Step ${i + 1} of ${total})` : '';
                const message =
                    buildHintMessage(blockType, lessonData.message, lessonData.tip, config) + progress;
                return suggest(blockType, message, i, total);
            }
        }
    } else {
        const HAT_BLOCKS = ['s_when_flag', 's_when_key', 's_when_clicked', 's_when_receive', 's_when_clone', 's_when_sprite_clicked'];
        const validChains = state.executionChains.filter(
            chain => chain.length > 0 && HAT_BLOCKS.includes(chain[0].type)
        );
        const validTypes = validChains.flatMap(chain => chain.map(b => b.type));

        for (let i = 0; i < solutionSteps.length; i++) {
            const step = solutionSteps[i];

            if (!validTypes.includes(step)) {
                const progress = config.showProgress ? ` (Step ${i + 1} of ${total})` : '';

                if (state.types.includes(step) && !HAT_BLOCKS.includes(step)) {
                    const metaKey = step.replace(/^s_/, '').replace(/_/g, ' ');
                    const meta = BLOCK_DB[step] || BLOCK_DB[metaKey] || {};
                    const label = meta.label || step;
                    return suggest(step, `You have the "${label}" block! Now snap it under the event block.` + progress, i, total);
                }

                const message = buildHintMessage(step, lessonData.message, lessonData.tip, config) + progress;
                return suggest(step, message, i, total);
            }
        }
    }

    return {
        blockType: null,
        message: lessonData.message ? `🎉 ${lessonData.message}` : '🎉 Lesson complete! Great job.',
        category: 'Done',
        label: 'Completed',
        emoji: '✅',
        progress: { current: total, total },
        isComplete: true,
    };
}

/* ─────────────────────────────────────────────────────────────
   HELP BUTTON — async version
   ✅ NOW records help so grader can penalise helped blocks
───────────────────────────────────────────────────────────── */

export async function getNextBlockForHelp(ws, supabase, lessonId, objective) {
    let prediction = null;
    
    try {
        const state = getWorkspaceState(ws);
        const liveHint = await generateLiveHint(state?.types || [], objective || 'Complete the lesson');
        if (liveHint && liveHint.blockType) {
            prediction = suggest(liveHint.blockType, liveHint.message, 0, 1);
        }
    } catch (err) {
        console.error("Live hint failed, falling back to static logic", err);
    }

    if (!prediction) {
        const lessonData = await fetchLessonSolution(supabase, lessonId);
        prediction = predictNextBlock(ws, lessonData, lessonId);
    }

    console.log("🧠 Prediction:", prediction);

    if (prediction?.blockType) {
        // ✅ Record that the user asked for help with this block type
        recordHelpRequested(prediction.blockType);

        attachHandHint(ws, {
            type: prediction.blockType,
            category: prediction.category,
            label: prediction.label
        });
    }

    return prediction;
}

/* ─────────────────────────────────────────────────────────────
   HELPERS
───────────────────────────────────────────────────────────── */

function suggest(blockType, message, stepIndex, total) {
    const metaKey = getBestKey(blockType);
    const meta = BLOCK_DB[metaKey] || {};

    return {
        blockType,
        category: meta.category || 'Unknown',
        label: meta.label || blockType,
        emoji: meta.emoji || '🧩',
        message,
        progress: { current: stepIndex + 1, total },
        isComplete: false,
    };
}

function fallback() {
    return {
        blockType: 's_when_flag',
        category: 'Events',
        label: 'When flag clicked',
        emoji: '🟡',
        message: 'Start with the 🚩 green flag block.',
        progress: null,
        isComplete: false,
    };
}

function getBestKey(type) {
    if (!type) return null;
    for (const [key, val] of Object.entries(BLOCK_DB)) {
        if (val.type === type) return key;
    }
    return null;
}