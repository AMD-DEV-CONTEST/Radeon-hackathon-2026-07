/**
 * Tutorial Engine — Smart parser that converts simple admin descriptions
 * into actionable visual tutorial steps with CSS selectors for the GuidePointer.
 * 
 * The admin writes plain text like:
 *   "Open Motion category, pick Move 10 steps block, drag under flag, click Run"
 * 
 * This engine converts it into structured steps the tutorial agent understands.
 */

// ═══════════════════════════════════════════════════════════════
//  BLOCK KNOWLEDGE BASE — maps block names to categories & types
// ═══════════════════════════════════════════════════════════════
const BLOCK_DB = {
    // MOTION
    'move': { type: 's_move', category: 'Motion', label: 'Move 10 steps', emoji: '🔵' },
    'move 10 steps': { type: 's_move', category: 'Motion', label: 'Move 10 steps', emoji: '🔵' },
    'move forward': { type: 's_move', category: 'Motion', label: 'Move 10 steps', emoji: '🔵' },
    'motion': { type: 's_move', category: 'Motion', label: 'Move 10 steps', emoji: '🔵' },
    'vector': { type: 's_move', category: 'Motion', label: 'Move 10 steps', emoji: '🔵' },
    'translation': { type: 's_move', category: 'Motion', label: 'Move 10 steps', emoji: '🔵' },
    'glide': { type: 's_glide_xy', category: 'Motion', label: 'Glide to x,y', emoji: '🔵' },
    'glide 2 secs': { type: 's_glide_xy', category: 'Motion', label: 'Glide to x,y', emoji: '🔵' },
    'glide to': { type: 's_glide_xy', category: 'Motion', label: 'Glide to x,y', emoji: '🔵' },
    'smooth move': { type: 's_glide_xy', category: 'Motion', label: 'Glide', emoji: '🔵' },
    'change y': { type: 's_change_y', category: 'Motion', label: 'Change y by 10', emoji: '🔵' },
    'change x': { type: 's_change_x', category: 'Motion', label: 'Change x by 10', emoji: '🔵' },
    'jump up': { type: 's_change_y', category: 'Motion', label: 'Change y', emoji: '🔵' },
    'turn right': { type: 's_turn_r', category: 'Motion', label: 'Turn right 15 degrees', emoji: '🔵' },
    'turn left': { type: 's_turn_l', category: 'Motion', label: 'Turn left 15 degrees', emoji: '🔵' },
    'turn 15 degrees': { type: 's_turn_r', category: 'Motion', label: 'Turn right 15 degrees', emoji: '🔵' },
    'rotate': { type: 's_turn_r', category: 'Motion', label: 'Turn right', emoji: '🔵' },
    'go to x y': { type: 's_goto_xy', category: 'Motion', label: 'Go to x: y:', emoji: '🔵' },
    'go to position': { type: 's_goto_pos', category: 'Motion', label: 'Go to position', emoji: '🔵' },
    'point in direction': { type: 's_point_dir', category: 'Motion', label: 'Point in direction', emoji: '🔵' },
    'set x': { type: 's_set_x', category: 'Motion', label: 'Set x', emoji: '🔵' },
    'set y': { type: 's_set_y', category: 'Motion', label: 'Set y', emoji: '🔵' },
    'bounce': { type: 's_bounce', category: 'Motion', label: 'If on edge, bounce', emoji: '🔵' },
    'edge': { type: 's_bounce', category: 'Motion', label: 'If on edge, bounce', emoji: '🔵' },
    // LOOKS
    'say': { type: 's_say', category: 'Looks', label: 'Say Hello!', emoji: '🟣' },
    'say hello': { type: 's_say', category: 'Looks', label: 'Say Hello!', emoji: '🟣' },
    'talk': { type: 's_say', category: 'Looks', label: 'Say Hello!', emoji: '🟣' },
    'speak': { type: 's_say', category: 'Looks', label: 'Say Hello!', emoji: '🟣' },
    'text': { type: 's_say', category: 'Looks', label: 'Say Hello!', emoji: '🟣' },
    'say hello for 2 seconds': { type: 's_say_timed', category: 'Looks', label: 'Say for seconds', emoji: '🟣' },
    'think': { type: 's_think', category: 'Looks', label: 'Think', emoji: '🟣' },
    'switch costume': { type: 's_switch_costume', category: 'Looks', label: 'Switch costume', emoji: '🟣' },
    'next costume': { type: 's_next_costume', category: 'Looks', label: 'Next costume', emoji: '🟣' },
    'switch backdrop': { type: 's_backdrop', category: 'Looks', label: 'Next backdrop', emoji: '🟣' },
    'change backdrop': { type: 's_backdrop', category: 'Looks', label: 'Next backdrop', emoji: '🟣' },
    'set size': { type: 's_set_size', category: 'Looks', label: 'Set size', emoji: '🟣' },
    'change size': { type: 's_change_size', category: 'Looks', label: 'Change size', emoji: '🟣' },
    'grow': { type: 's_change_size', category: 'Looks', label: 'Change size by 10', emoji: '🟣' },
    'shrink': { type: 's_change_size', category: 'Looks', label: 'Shrink', emoji: '🟣' },
    'change color': { type: 's_change_effect', category: 'Looks', label: 'Change color effect', emoji: '🟣' },
    'clear effects': { type: 's_clear_fx', category: 'Looks', label: 'Clear graphic effects', emoji: '🟣' },
    'show': { type: 's_show', category: 'Looks', label: 'Show', emoji: '🟣' },
    'appear': { type: 's_show', category: 'Looks', label: 'Show', emoji: '🟣' },
    'hide': { type: 's_hide', category: 'Looks', label: 'Hide', emoji: '🟣' },
    'vanish': { type: 's_hide', category: 'Looks', label: 'Hide', emoji: '🟣' },
    'invisible': { type: 's_hide', category: 'Looks', label: 'Hide', emoji: '🟣' },
    // SOUND
    'play sound': { type: 's_play_sound', category: 'Sound', label: 'Play sound', emoji: '🎵' },
    'start sound': { type: 's_start_sound', category: 'Sound', label: 'Start sound', emoji: '🎵' },
    'meow': { type: 's_start_sound', category: 'Sound', label: 'Start Meow sound', emoji: '🎵' },
    'bark': { type: 's_start_sound', category: 'Sound', label: 'Start Bark sound', emoji: '🎵' },
    'music': { type: 's_start_sound', category: 'Sound', label: 'Play music', emoji: '🎵' },
    // CONTROL
    'wait': { type: 's_wait', category: 'Control', label: 'Wait 1 second', emoji: '🟠' },
    'pause': { type: 's_wait', category: 'Control', label: 'Wait 1 second', emoji: '🟠' },
    'repeat': { type: 's_repeat', category: 'Control', label: 'Repeat 10', emoji: '🟠' },
    'forever': { type: 's_forever', category: 'Control', label: 'Forever', emoji: '🟠' },
    'always': { type: 's_forever', category: 'Control', label: 'Forever', emoji: '🟠' },
    'if then': { type: 's_if', category: 'Control', label: 'If then', emoji: '🟠' },
    'if else': { type: 's_if_else', category: 'Control', label: 'If else', emoji: '🟠' },
    'stop': { type: 's_stop', category: 'Control', label: 'Stop all', emoji: '🟠' },
    // SENSING
    'touching mouse': { type: 's_touching_mouse', category: 'Sensing', label: 'Touching mouse?', emoji: '🔍' },
    'touching edge': { type: 's_touching_edge', category: 'Sensing', label: 'Touching edge?', emoji: '🔍' },
    'key pressed': { type: 's_key_pressed', category: 'Sensing', label: 'Key pressed?', emoji: '🔍' },
    // VARIABLES
    'set variable': { type: 's_set_var', category: 'Variables', label: 'Set variable', emoji: '📊' },
    'change variable': { type: 's_change_var', category: 'Variables', label: 'Change variable', emoji: '📊' },
    'score': { type: 's_change_var', category: 'Variables', label: 'Change score', emoji: '📊' },
    // EVENTS
    'when flag clicked': { type: 's_when_flag', category: 'Events', label: 'When flag clicked', emoji: '🟡' },
    'when clicked': { type: 's_when_flag', category: 'Events', label: 'When flag clicked', emoji: '🟡' },
    'flag': { type: 's_when_flag', category: 'Events', label: 'When flag clicked', emoji: '🟡' },
    'green flag': { type: 's_when_flag', category: 'Events', label: 'When flag clicked', emoji: '🟡' },
    'start': { type: 's_when_flag', category: 'Events', label: 'When flag clicked', emoji: '🟡' },
    'when key pressed': { type: 's_when_key', category: 'Events', label: 'When key pressed', emoji: '🟡' },
    'when this sprite clicked': { type: 's_when_clicked', category: 'Events', label: 'When this sprite clicked', emoji: '🟡' },
    'when sprite clicked': { type: 's_when_clicked', category: 'Events', label: 'When this sprite clicked', emoji: '🟡' },
    'click sprite': { type: 's_when_clicked', category: 'Events', label: 'When this sprite clicked', emoji: '🟡' },
    // PEN
    'pen down': { type: 's_pen_down', category: 'Pen', label: 'Pen down', emoji: '✏️' },
    'pen up': { type: 's_pen_up', category: 'Pen', label: 'Pen up', emoji: '✏️' },
    'erase all': { type: 's_pen_clear', category: 'Pen', label: 'Erase all', emoji: '✏️' },
    'clear': { type: 's_pen_clear', category: 'Pen', label: 'Erase all', emoji: '✏️' },
};

// Category name → toolbox aria-label partial match
const CATEGORY_SELECTORS = {
    'Motion': '.blocklyTreeRow[aria-label*="Motion"]',
    'Looks': '.blocklyTreeRow[aria-label*="Looks"]',
    'Sound': '.blocklyTreeRow[aria-label*="Sound"]',
    'Control': '.blocklyTreeRow[aria-label*="Control"]',
    'Sensing': '.blocklyTreeRow[aria-label*="Sensing"]',
    'Operators': '.blocklyTreeRow[aria-label*="Operators"]',
    'Variables': '.blocklyTreeRow[aria-label*="Variables"]',
    'Lists': '.blocklyTreeRow[aria-label*="Lists"]',
    'Pen': '.blocklyTreeRow[aria-label*="Pen"]',
    'Events': '.blocklyTreeRow[aria-label*="Events"]',
    'My Blocks': '.blocklyTreeRow[aria-label*="My Blocks"]',
};

// Fuzzy match a block name from user description
function findBlock(text) {
    const lower = text.toLowerCase().trim();
    
    // 1. Direct match (highest priority)
    if (BLOCK_DB[lower]) return BLOCK_DB[lower];
    
    // 2. Exact word match (prevents "pen" matching "performance")
    const words = lower.split(/\s+/);
    for (const word of words) {
        if (word.length > 2 && BLOCK_DB[word]) return BLOCK_DB[word];
    }

    // 3. Category match
    if (lower.includes('motion')) return BLOCK_DB['move'];
    if (lower.includes('look')) return BLOCK_DB['say'];
    if (lower.includes('sound')) return BLOCK_DB['play sound'];
    if (lower.includes('event')) return BLOCK_DB['when flag clicked'];
    
    // 4. Multi-word partial match (stricter)
    for (const [key, val] of Object.entries(BLOCK_DB)) {
        if (key.length > 3 && lower.includes(key)) return val;
    }
    
    return null;
}

/**
 * Parses a simple admin description into structured tutorial steps.
 */
export function parseTutorialDescription(description) {
    const steps = [];
    if (!description) return steps;

    // Always start with: pick the "When Flag Clicked" block from Events
    steps.push({
        action: 'open_category',
        category: 'Events',
        msg: "🟡 First, let's start by opening the Events category! Look where my hand is pointing! ☝️",
        target: CATEGORY_SELECTORS['Events'],
        checkType: 'category_selected',
        checkValue: 'Events',
    });

    steps.push({
        action: 'verify_block',
        msg: "Great! You should have the 🚩 'When Flag Clicked' block on your workspace. This is where every project starts!",
        target: null,
        checkType: 'xml_contains',
        checkValue: 's_when_flag',
    });

    const parts = description
        .split(/[,;.\n]|then|next|after that|and then|now|finally/i)
        .map(p => p.trim())
        .filter(p => p.length > 3);

    for (const part of parts) {
        const lower = part.toLowerCase();
        if (lower.includes('flag') || lower.includes('when clicked')) continue;

        if (lower.includes('run') || lower.includes('play') || lower.includes('press run') || lower.includes('click run')) {
            steps.push({
                action: 'click_button',
                msg: "🎉 Amazing work! Now click the ▶ Run button to see the magic happen!",
                target: '#run-btn',
                checkType: 'manual',
                checkValue: null,
            });
            continue;
        }

        const block = findBlock(lower);
        if (block) {
            steps.push({
                action: 'open_category',
                category: block.category,
                msg: `${block.emoji} Now open the ${block.category} category! Look where my hand is pointing! ☝️`,
                target: CATEGORY_SELECTORS[block.category],
                checkType: 'category_selected',
                checkValue: block.category,
            });

            steps.push({
                action: 'pick_block',
                blockType: block.type,
                msg: `👆 Perfect! Now pick the '${block.label}' block and drag it to snap under your blocks on the workspace!`,
                target: `.blocklyFlyout .blocklyDraggable`,
                checkType: 'xml_contains',
                checkValue: block.type,
            });
        }
    }

    if (!steps.some(s => s.action === 'click_button')) {
        steps.push({
            action: 'click_button',
            msg: "🎉 You did it! Now click the ▶ Run button to see your creation come to life!",
            target: '#run-btn',
            checkType: 'manual',
            checkValue: null,
        });
    }

    return steps;
}

/**
 * Generates the solution XML from the description for the "Solve" feature.
 */
export function generateSolutionXml(description) {
    if (!description) return null;
    
    const parts = description
        .split(/[,;.\n]|then|next|after that|and then|now|finally/i)
        .map(p => p.trim())
        .filter(p => p.length > 3);

    const blocks = [];
    for (const part of parts) {
        const lower = part.toLowerCase();
        // Only skip if it's clearly a UI button interaction like "Press play" or "Click run"
        if ((lower.includes('run') || lower.includes('press play') || lower.includes('click play')) && !lower.includes('sound')) continue;
        const block = findBlock(lower);
        if (block) blocks.push(block);
    }

    if (blocks.length === 0) return null;

    let starterBlock = 's_when_flag';
    const bodyBlocks = [];

    for (const b of blocks) {
        if (['s_when_flag', 's_when_clicked', 's_when_key', 's_when_broadcast'].includes(b.type)) {
            starterBlock = b.type;
        } else {
            bodyBlocks.push(b);
        }
    }

    // Chain blocks: first block wraps all subsequent ones in <next> tags
    let innerXml = '';
    for (let i = bodyBlocks.length - 1; i >= 0; i--) {
        let blockXml = getBlockXml(bodyBlocks[i].type);
        if (innerXml) {
            blockXml = blockXml.replace('</block>', `<next>${innerXml}</next></block>`);
        }
        innerXml = blockXml;
    }

    return `<xml xmlns="https://developers.google.com/blockly/xml"><block type="${starterBlock}" x="50" y="50">${innerXml ? `<next>${innerXml}</next>` : ''}</block></xml>`;
}

function getBlockXml(type) {
    const templates = {
        's_move': '<block type="s_move"><value name="STEPS"><shadow type="math_number"><field name="NUM">10</field></shadow></value></block>',
        's_turn_r': '<block type="s_turn_r"><value name="DEG"><shadow type="math_number"><field name="NUM">15</field></shadow></value></block>',
        's_turn_l': '<block type="s_turn_l"><value name="DEG"><shadow type="math_number"><field name="NUM">15</field></shadow></value></block>',
        's_say_timed': '<block type="s_say_timed"><value name="MSG"><shadow type="text"><field name="TEXT">Hello Kido!</field></shadow></value><value name="SECS"><shadow type="math_number"><field name="NUM">2</field></shadow></value></block>',
        's_say': '<block type="s_say"><value name="MSG"><shadow type="text"><field name="TEXT">Hello Kido!</field></shadow></value></block>',
        's_think_timed': '<block type="s_think_timed"><value name="MSG"><shadow type="text"><field name="TEXT">Hmm...</field></shadow></value><value name="SECS"><shadow type="math_number"><field name="NUM">2</field></shadow></value></block>',
        's_repeat': '<block type="s_repeat"><value name="N"><shadow type="math_number"><field name="NUM">10</field></shadow></value><statement name="DO"></statement></block>',
        's_forever': '<block type="s_forever"><statement name="DO"></statement></block>',
        's_wait': '<block type="s_wait"><value name="SECS"><shadow type="math_number"><field name="NUM">1</field></shadow></value></block>',
        's_start_sound': '<block type="s_start_sound"><field name="SOUND">meow</field></block>',
        's_play_sound': '<block type="s_play_sound"><field name="SOUND">meow</field></block>',
        's_change_effect': '<block type="s_change_effect"><field name="EFFECT">color</field><value name="VAL"><shadow type="math_number"><field name="NUM">25</field></shadow></value></block>',
        's_set_size': '<block type="s_set_size"><value name="SIZE"><shadow type="math_number"><field name="NUM">100</field></shadow></value></block>',
        's_change_size': '<block type="s_change_size"><value name="AMT"><shadow type="math_number"><field name="NUM">10</field></shadow></value></block>',
        's_goto_xy': '<block type="s_goto_xy"><value name="X"><shadow type="math_number"><field name="NUM">0</field></shadow></value><value name="Y"><shadow type="math_number"><field name="NUM">0</field></shadow></value></block>',
        's_bounce': '<block type="s_bounce"></block>',
        's_pen_down': '<block type="s_pen_down"></block>',
        's_pen_up': '<block type="s_pen_up"></block>',
        's_pen_clear': '<block type="s_pen_clear"></block>',
        's_if': '<block type="s_if"><statement name="DO"></statement></block>',
        's_set_var': '<block type="s_set_var"><field name="VAR">score</field><value name="VAL"><shadow type="math_number"><field name="NUM">0</field></shadow></value></block>',
        's_change_var': '<block type="s_change_var"><field name="VAR">score</field><value name="AMT"><shadow type="math_number"><field name="NUM">1</field></shadow></value></block>',
        's_next_costume': '<block type="s_next_costume"></block>',
        's_switch_costume': '<block type="s_switch_costume"><field name="COSTUME">costume1</field></block>',
        's_show': '<block type="s_show"></block>',
        's_hide': '<block type="s_hide"></block>',
        's_clear_fx': '<block type="s_clear_fx"></block>',
        's_stop': '<block type="s_stop"><field name="WHICH">all</field></block>',
        's_create_clone': '<block type="s_create_clone"><field name="TARGET">myself</field></block>',
        's_pen_stamp': '<block type="s_pen_stamp"></block>',
        's_pen_color': '<block type="s_pen_color"><value name="COLOR"><shadow type="text"><field name="TEXT">#ff0000</field></shadow></value></block>',
        's_pen_size': '<block type="s_pen_size"><value name="SIZE"><shadow type="math_number"><field name="NUM">3</field></shadow></value></block>',
        's_when_clicked': '<block type="s_when_clicked"></block>',
        's_glide_xy': '<block type="s_glide_xy"><value name="SECS"><shadow type="math_number"><field name="NUM">1</field></shadow></value><value name="X"><shadow type="math_number"><field name="NUM">0</field></shadow></value><value name="Y"><shadow type="math_number"><field name="NUM">0</field></shadow></value></block>',
        's_broadcast': '<block type="s_broadcast"><value name="MSG"><shadow type="text"><field name="TEXT">message1</field></shadow></value></block>',
        's_when_broadcast': '<block type="s_when_broadcast"><field name="MSG">message1</field></block>',
        's_next_backdrop': '<block type="s_next_backdrop"></block>',
        's_backdrop': '<block type="s_backdrop"><field name="BACKDROP">backdrop1</field></block>',
        's_switch_backdrop': '<block type="s_backdrop"><field name="BACKDROP">backdrop1</field></block>',
    };
    return templates[type] || `<block type="${type}"></block>`;
}

export { BLOCK_DB, CATEGORY_SELECTORS, findBlock };

