import { supabase } from '../../utils/supabaseClient';
import { parseTutorialDescription } from './tutorialEngine';
import { getHelpedBlockTypes, resetHelpTracking } from './helpTracker'; // ← NEW

/* ─────────────────────────────────────────────
   🧠 XML PARSER
──────────────────────────────────────────── */
const extractBlockTypes = (xmlText) => {
    if (!xmlText) return [];
    try {
        const parser = new DOMParser();
        const xml = parser.parseFromString(xmlText, 'text/xml');
        const blocks = xml.getElementsByTagName('block');
        const types = [];
        for (let i = 0; i < blocks.length; i++) {
            const type = blocks[i].getAttribute('type');
            if (type && type !== 'math_number' && type !== 'text') {
                types.push(type);
            }
        }
        return [...new Set(types)];
    } catch (err) {
        console.error('XML Parse Error:', err);
        return [];
    }
};

/* ─────────────────────────────────────────────
   🏁 GRADER
──────────────────────────────────────────── */
export const getGrade = async (lessonId, currentXml) => {
    const xml = currentXml || '';
    const studentBlocks = extractBlockTypes(xml);

    // ✅ Grab help-used block types BEFORE we reset
    const helpedBlockTypes = getHelpedBlockTypes();
    console.log('🆘 Blocks placed with help:', [...helpedBlockTypes]);

    console.log('━━━━━━ SUBMIT DEBUG ━━━━━━');
    console.log('📦 Student Blocks:', studentBlocks);

    // ── No blocks at all ──────────────────────────────────────────────────
    if (studentBlocks.length === 0) {
        return {
            score: 0,
            xpEarned: 0,
            feedback: 'Your workspace is empty! Add some blocks to get started.',
            newBadgeLabels: [],
            debugInfo: { requiredMissing: [], extraBlocks: [], studentBlocks: [], helpedBlocks: [] },
        };
    }

    const HAT_BLOCKS = [
        's_when_flag', 's_when_key', 's_when_clicked',
        's_when_receive', 's_when_clone', 's_when_sprite_clicked',
    ];

    // ── Fetch solution ─────────────────────────────────────────────────────
    const { data: sol } = await supabase
        .from('tutor_solutions')
        .select('xml')
        .eq('lesson_id', lessonId)
        .maybeSingle();

    const solutionXml = sol?.xml;

    // ── Fallback (no solution stored) ─────────────────────────────────────
    if (!solutionXml) {
        const hasHat = studentBlocks.some(b => HAT_BLOCKS.includes(b));
        const rawScore = Math.min(100, studentBlocks.length * 15 + (hasHat ? 10 : 0));

        // ✅ Deduct for helped blocks even in fallback
        const helpedCount = studentBlocks.filter(b => helpedBlockTypes.has(b)).length;
        const totalBlocks = Math.max(1, studentBlocks.length);
        const helpPenaltyFraction = helpedCount / totalBlocks;
        const score = Math.max(0, Math.round(rawScore * (1 - helpPenaltyFraction)));

        return {
            score,
            xpEarned: Math.max(1, Math.floor(score / 10)),
            feedback: score >= 60 ? 'Great work! Keep experimenting.' : 'Try adding more blocks.',
            newBadgeLabels: score >= 90 ? ['Gold'] : score >= 70 ? ['Silver'] : [],
            debugInfo: { requiredMissing: [], extraBlocks: [], studentBlocks, helpedBlocks: [...helpedBlockTypes] },
        };
    }

    const solutionBlocks = extractBlockTypes(solutionXml);
    const requiredBlocks = [...new Set(solutionBlocks)].filter(b => !HAT_BLOCKS.includes(b));

    const wrongBlocks = studentBlocks.filter(
        b => !requiredBlocks.includes(b) && !HAT_BLOCKS.includes(b)
    );

    const missingBlocks = requiredBlocks.filter(b => !studentBlocks.includes(b));
    const matchedCount = requiredBlocks.filter(b => studentBlocks.includes(b)).length;

    // ✅ Which required blocks did the student place WITH help?
    // ✅ Any block actually placed using help
    const helpedUsedBlocks = studentBlocks.filter(b =>
        helpedBlockTypes.has(b)
    );

    // ✅ Required blocks specifically helped
    const helpedRequired = requiredBlocks.filter(b =>
        helpedBlockTypes.has(b)
    );

    // ✅ Independently solved required blocks
    const selfSolvedCount = Math.max(
        0,
        matchedCount - helpedRequired.length
    );

    

    // ── Edge case: solution has only hat blocks ────────────────────────────
    if (requiredBlocks.length === 0) {
        const hasHat = studentBlocks.some(b => HAT_BLOCKS.includes(b));
        let score = hasHat && wrongBlocks.length === 0 ? 100 : 30;
        if (hasHat && wrongBlocks.length > 0) score = 40;
        return {
            score,
            xpEarned: Math.max(1, Math.floor(score / 10)),
            feedback: hasHat
                ? 'Great start! Your event block is set up.'
                : 'Use the correct starter (event) block.',
            newBadgeLabels: score === 100 ? ['Starter Master'] : score >= 40 ? ['Bronze'] : [],
            debugInfo: { requiredMissing: missingBlocks, extraBlocks: wrongBlocks, studentBlocks, helpedBlocks: [...helpedBlockTypes] },
        };
    }

    /* ─────────────────────────────────────────────────────────────────────
       ✅ HELP-AWARE SCORING
       
       Core idea:
         - Score is based ONLY on blocks the student solved themselves.
         - Helped blocks count as "present" (no missing-block penalty) but
           contribute ZERO positive score.
         - Wrong blocks still penalise as before.

       Formula:
         selfSolvedFraction = selfSolvedCount / requiredBlocks.length
         baseScore          = selfSolvedFraction × 100
         - wrongPenalty     = wrongBlocks.length × 20
         - missingPenalty   = missingBlocks.length × 15
         + hatBonus         = 5  (if any hat block present)
         + perfectBonus     = 5  (if zero missing AND zero wrong)
    ───────────────────────────────────────────────────────────────────── */
    const hasHat = studentBlocks.some(b => HAT_BLOCKS.includes(b));

    // Only reward self-solved blocks
    const selfSolvedFraction = selfSolvedCount / requiredBlocks.length;
    let score = selfSolvedFraction * 100;
    score -= wrongBlocks.length * 20;
    score -= missingBlocks.length * 15;
    score += hasHat ? 5 : 0;
    // Perfect bonus only if the student solved everything themselves
    score += (missingBlocks.length === 0 && wrongBlocks.length === 0 && helpedRequired.length === 0) ? 5 : 0;
    score = Math.max(0, Math.min(100, Math.round(score)));

    // ── Threshold clamping (keep existing logic) ──────────────────────────
    if (wrongBlocks.length > 0 || missingBlocks.length > 0) {
        if (matchedCount > 0 || (requiredBlocks.length === 0 && hasHat)) {
            score = Math.max(40, score);
        } else {
            score = Math.min(score, 39);
        }
    }

    // ── If ALL required blocks were helped → cap score at 30 ─────────────
    // (They completed it but used help for everything — minimal reward)
    if (helpedRequired.length === requiredBlocks.length && requiredBlocks.length > 0) {
        score = Math.min(score, 30);
    }

    const xpEarned = Math.max(1, Math.floor(score / 10));

    // ── Badges ─────────────────────────────────────────────────────────────
    const newBadgeLabels = [];
    if (score >= 90) newBadgeLabels.push('Gold');
    else if (score >= 70) newBadgeLabels.push('Silver');
    else if (score >= 40) newBadgeLabels.push('Bronze');
    if (missingBlocks.length === 0 && wrongBlocks.length === 0 && helpedRequired.length === 0)
        newBadgeLabels.push('Complete Solution');

    // ── Feedback ─────────────────────────────────────────────────────────
    let feedback;
    if (score === 0 && matchedCount === 0) {
        feedback = 'None of the required blocks were used. Check the instructions and try again!';
    } else if (wrongBlocks.length > 0 && missingBlocks.length > 0) {
        feedback = `You used ${wrongBlocks.length} incorrect block(s) and are still missing ${missingBlocks.length} required block(s).`;
    } else if (wrongBlocks.length > 0) {
        feedback = `You used ${wrongBlocks.length} incorrect block(s). Remove the wrong blocks and try again!`;
    } else if (missingBlocks.length > 0) {
        feedback = `You're missing ${missingBlocks.length} required block(s). Keep going — you're close!`;
    } else if (helpedRequired.length > 0 && selfSolvedCount > 0) {
        // ✅ Mixed: some self-solved, some helped
        feedback = `You solved ${selfSolvedCount} of ${requiredBlocks.length} block(s) yourself! ${helpedRequired.length} block(s) used the hint — try those on your own next time.`;
    } else if (helpedRequired.length === requiredBlocks.length) {
        // ✅ All blocks were helped
        feedback = `You completed the level using hints for all blocks. Try solving it yourself to earn full marks!`;
    } else {
        feedback = 'Perfect solution! Every block solved on your own — excellent!';
    }

    console.log('🏁 FINAL SCORE:', score, '| BADGE:', newBadgeLabels);

    // ✅ Reset help tracking after grading so replays start fresh
    resetHelpTracking();

    return {
        score,
        xpEarned,
        feedback,
        newBadgeLabels,
        debugInfo: {
            requiredMissing: missingBlocks,
            extraBlocks: wrongBlocks,
            studentBlocks,
            helpedBlocks: [...helpedRequired],  // ✅ exposed for UI
        },
    };
};

/* ─────────────────────────────────────────────
   📘 TUTORIAL STEPS
──────────────────────────────────────────── */
export const fetchTutorialSteps = async (lessonId) => {
    const { data, error } = await supabase
        .from('tutorial_steps')
        .select('*')
        .eq('lesson_id', lessonId)
        .order('step_index', { ascending: true });

    if (error || !data?.length) return null;

    const firstStep = data[0];
    const isSmart = data.length === 1 && !firstStep.target_selector;

    if (isSmart) {
        return parseTutorialDescription(firstStep.message);
    }

    return data.map(step => ({
        action: step.target_selector ? 'legacy' : 'verify_block',
        msg: step.message,
        target: step.target_selector || null,
        checkType: step.check_xml_contains ? 'xml_contains' : 'manual',
        checkValue: step.check_xml_contains || null,
    }));
};