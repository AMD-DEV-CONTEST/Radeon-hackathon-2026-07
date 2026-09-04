const { createClient } = require('@supabase/supabase-client');

const supabase = createClient(
    process.env.SUPABASE_URL || '',
    process.env.SUPABASE_SERVICE_ROLE_KEY || ''
);

// Actually, I'll use SQL via MCP because I don't have the service role key easily available in a script, 
// and the MCP tool is already authenticated.

const projects = [
    {
        id: "L1P1",
        xml: `<xml xmlns="https://developers.google.com/blockly/xml"><block type="s_when_flag" x="50" y="50"><next><block type="s_move"><value name="STEPS"><shadow type="math_number"><field name="NUM">10</field></shadow></value></block></next></block></xml>`,
        steps: [
            { msg: "🟡 Open the Events category!", target: ".blocklyTreeRow[aria-label*='Events']" },
            { msg: "🚩 Drag the 'When Flag Clicked' block to your workspace!", target: null, check_xml: "s_when_flag" },
            { msg: "🔵 Open Motion and pick 'Move 10 steps'!", target: ".blocklyTreeRow[aria-label*='Motion']" },
            { msg: "👇 Snap it under the flag and click ▶ Run!", target: "#run-btn" }
        ],
        tip: "Snap blocks together to make them work in order!",
        msg: "Great! You made the cat move!"
    },
    {
        id: "L1P2",
        xml: `<xml xmlns="https://developers.google.com/blockly/xml"><block type="s_when_flag" x="50" y="50"><next><block type="s_move"><value name="STEPS"><shadow type="math_number"><field name="NUM">10</field></shadow></value><next><block type="s_say"><value name="MSG"><shadow type="text"><field name="TEXT">Hello Kido!</field></shadow></value></block></next></block></next></block></xml>`,
        steps: [
            { msg: "🚩 Start with the 'When Flag Clicked' block!", target: null, check_xml: "s_when_flag" },
            { msg: "🔵 Add a 'Move 10 steps' block!", check_xml: "s_move" },
            { msg: "🟣 Now open Looks and add the 'Say Hello' block!", target: ".blocklyTreeRow[aria-label*='Looks']", check_xml: "s_say" },
            { msg: "▶ Click Run to see the cat move and talk!" }
        ],
        tip: "The cat will move FIRST, then it will talk!",
        msg: "Amazing! Your sprite can talk now!"
    },
    {
        id: "L1P3",
        xml: `<xml xmlns="https://developers.google.com/blockly/xml"><block type="s_when_flag" x="50" y="50"><next><block type="s_move"><value name="STEPS"><shadow type="math_number"><field name="NUM">10</field></shadow></value><next><block type="s_start_sound"><field name="SOUND">meow</field></block></next></block></next></block></xml>`,
        steps: [
            { msg: "🚩 Add the 'When Flag Clicked' block!", check_xml: "s_when_flag" },
            { msg: "🔵 Add 'Move 10 steps'!", check_xml: "s_move" },
            { msg: "🎵 Open Sound and add 'Start sound Meow'!", target: ".blocklyTreeRow[aria-label*='Sound']", check_xml: "s_start_sound" },
            { msg: "▶ Press Run and listen to the Meow!" }
        ],
        tip: "Try the Bark sound too by clicking the dropdown on the sound block!",
        msg: "Purr-fect! You added sound to your movement!"
    },
    {
        id: "L1P4",
        xml: `<xml xmlns="https://developers.google.com/blockly/xml"><block type="s_when_flag" x="50" y="50"><next><block type="s_repeat"><value name="N"><shadow type="math_number"><field name="NUM">5</field></shadow></value><statement name="DO"><block type="s_next_costume"><next><block type="s_wait"><value name="SECS"><shadow type="math_number"><field name="NUM">0.5</field></shadow></value><next><block type="s_start_sound"><field name="SOUND">meow</field></block></next></block></next></block></statement></block></next></block></xml>`,
        steps: [
            { msg: "🚩 Start with the Green Flag!", check_xml: "s_when_flag" },
            { msg: "🟠 Open Control and pick the 'Repeat 10' block!", target: ".blocklyTreeRow[aria-label*='Control']", check_xml: "s_repeat" },
            { msg: "🟣 Put 'Next Costume' inside the repeat block!", check_xml: "s_next_costume" },
            { msg: "🟠 Add a 'Wait 1 second' block and change it to 0.5!", check_xml: "s_wait" },
            { msg: "▶ Click Run and watch the dance!" }
        ],
        tip: "The 'Repeat' block makes things happen over and over again!",
        msg: "Wow! Look at that sprite dance!"
    },
    {
        id: "L1P5",
        xml: `<xml xmlns="https://developers.google.com/blockly/xml"><block type="s_when_flag" x="50" y="50"><next><block type="s_move"><value name="STEPS"><shadow type="math_number"><field name="NUM">50</field></shadow></value><next><block type="s_wait"><value name="SECS"><shadow type="math_number"><field name="NUM">1</field></shadow></value><next><block type="s_next_backdrop"></block></next></block></next></block></next></block></xml>`,
        steps: [
            { msg: "🚩 Start with 'When Flag Clicked'!", check_xml: "s_when_flag" },
            { msg: "🔵 Move the sprite by 50 steps!", check_xml: "s_move" },
            { msg: "🟠 Add a 'Wait 1 second' block!", check_xml: "s_wait" },
            { msg: "🟣 Add 'Next Backdrop' from the Looks category!", check_xml: "s_next_backdrop" },
            { msg: "▶ Run it to travel to a new world!" }
        ],
        tip: "You can change the background to any place you want!",
        msg: "You traveled to a whole new world!"
    },
    {
        id: "L1P6",
        xml: `<xml xmlns="https://developers.google.com/blockly/xml"><block type="s_when_flag" x="50" y="50"><next><block type="s_show"><next><block type="s_wait"><value name="SECS"><shadow type="math_number"><field name="NUM">1</field></shadow></value><next><block type="s_hide"></block></next></block></next></block></next></block></xml>`,
        steps: [
            { msg: "🚩 Start with the Flag!", check_xml: "s_when_flag" },
            { msg: "🟣 Pick the 'Show' block from Looks!", check_xml: "s_show" },
            { msg: "🟠 Add a 'Wait' block so we can see it!", check_xml: "s_wait" },
            { msg: "🟣 Now pick the 'Hide' block!", check_xml: "s_hide" },
            { msg: "▶ Click Run to see a magic trick!" }
        ],
        tip: "Use 'Show' and 'Hide' to make things appear and disappear!",
        msg: "Ta-da! A real magic trick!"
    },
    {
        id: "L1P7",
        xml: `<xml xmlns="https://developers.google.com/blockly/xml"><block type="s_when_sprite_clicked" x="50" y="50"><next><block type="s_change_effect"><field name="EFFECT">color</field><value name="VAL"><shadow type="math_number"><field name="NUM">25</field></shadow></value></block></next></block></xml>`,
        steps: [
            { msg: "🟡 Open Events and pick 'When this sprite clicked'!", target: ".blocklyTreeRow[aria-label*='Events']", check_xml: "s_when_sprite_clicked" },
            { msg: "🟣 Add 'Change color effect by 25'!", check_xml: "s_change_effect" },
            { msg: "▶ Now click on the actual sprite on the stage to see it change!" }
        ],
        tip: "Instead of a flag, this project starts when YOU touch the sprite!",
        msg: "Magic Touch! It changes colors!"
    },
    {
        id: "L1P8",
        xml: `<xml xmlns="https://developers.google.com/blockly/xml">
            <block type="s_when_key" x="20" y="20"><field name="KEY">up arrow</field><next><block type="s_change_y"><value name="AMT"><shadow type="math_number"><field name="NUM">10</field></shadow></value></block></next></block>
            <block type="s_when_key" x="20" y="120"><field name="KEY">down arrow</field><next><block type="s_change_y"><value name="AMT"><shadow type="math_number"><field name="NUM">-10</field></shadow></value></block></next></block>
            <block type="s_when_key" x="250" y="20"><field name="KEY">right arrow</field><next><block type="s_change_x"><value name="AMT"><shadow type="math_number"><field name="NUM">10</field></shadow></value></block></next></block>
            <block type="s_when_key" x="250" y="120"><field name="KEY">left arrow</field><next><block type="s_change_x"><value name="AMT"><shadow type="math_number"><field name="NUM">-10</field></shadow></value></block></next></block>
        </xml>`,
        steps: [
            { msg: "🟡 Add 'When key pressed' and change it to Up Arrow!", check_xml: "s_when_key" },
            { msg: "🔵 Add 'Change Y by 10' to move up!", check_xml: "s_change_y" },
            { msg: "🟡 Do the same for Down, Left, and Right arrows!", target: null },
            { msg: "⌨️ Use your keyboard to walk around!" }
        ],
        tip: "X moves Left and Right. Y moves Up and Down!",
        msg: "You built a keyboard controller!"
    },
    {
        id: "L1P9",
        xml: `<xml xmlns="https://developers.google.com/blockly/xml"><block type="s_when_flag" x="50" y="50"><next><block type="s_goto_xy"><value name="X"><shadow type="math_number"><field name="NUM">-200</field></shadow></value><value name="Y"><shadow type="math_number"><field name="NUM">0</field></shadow></value><next><block type="s_glide_xy"><value name="SECS"><shadow type="math_number"><field name="NUM">2</field></shadow></value><value name="X"><shadow type="math_number"><field name="NUM">200</field></shadow></value><value name="Y"><shadow type="math_number"><field name="NUM">0</field></shadow></value></block></next></block></next></block></xml>`,
        steps: [
            { msg: "🚩 Start with the Flag!", check_xml: "s_when_flag" },
            { msg: "🔵 Pick 'Go to X Y' and set X to -200!", check_xml: "s_goto_xy" },
            { msg: "🔵 Pick 'Glide 1 secs to X Y' and set X to 200!", check_xml: "s_glide_xy" },
            { msg: "▶ Click Run to see the smooth journey!" }
        ],
        tip: "Glide makes the movement look much smoother than teleporting!",
        msg: "What a smooth journey!"
    },
    {
        id: "L1P10",
        xml: `<xml xmlns="https://developers.google.com/blockly/xml"><block type="s_when_flag" x="50" y="50"><next><block type="s_repeat"><value name="N"><shadow type="math_number"><field name="NUM">4</field></shadow></value><statement name="DO"><block type="s_move"><value name="STEPS"><shadow type="math_number"><field name="NUM">50</field></shadow></value><next><block type="s_turn_r"><value name="DEG"><shadow type="math_number"><field name="NUM">90</field></shadow></value></block></next></block></statement><next><block type="s_say"><value name="MSG"><shadow type="text"><field name="TEXT">I graduated Level 1!</field></shadow></value></block></next></block></next></block></xml>`,
        steps: [
            { msg: "🎓 It's your graduation! Use everything you learned!", target: null },
            { msg: "🚩 Start with the Flag!", check_xml: "s_when_flag" },
            { msg: "🔵 Combine Move, Turn, and Say blocks!", target: null },
            { msg: "▶ Build your masterpiece!" }
        ],
        tip: "You can use Repeat blocks to make the sprite walk in a square!",
        msg: "Congratulations! You are now a Kido Dev Master!"
    }
];

// Generate SQL to update everything in one go
let sql = '';
for (const p of projects) {
    // Escape single quotes for SQL
    const xml = p.xml.replace(/'/g, "''");
    const msg = p.msg.replace(/'/g, "''");
    const tip = p.tip.replace(/'/g, "''");

    sql += `INSERT INTO tutor_solutions (lesson_id, xml, message, tip) VALUES ('${p.id}', '${xml}', '${msg}', '${tip}') ON CONFLICT (lesson_id) DO UPDATE SET xml = EXCLUDED.xml, message = EXCLUDED.message, tip = EXCLUDED.tip;\n`;

    sql += `DELETE FROM tutorial_steps WHERE lesson_id = '${p.id}';\n`;
    p.steps.forEach((s, idx) => {
        const stepMsg = s.msg.replace(/'/g, "''");
        const target = s.target ? `'${s.target}'` : 'NULL';
        const checkXml = s.check_xml ? `'${s.check_xml}'` : 'NULL';
        sql += `INSERT INTO tutorial_steps (lesson_id, step_index, message, target_selector, check_xml_contains) VALUES ('${p.id}', ${idx}, '${stepMsg}', ${target}, ${checkXml});\n`;
    });
}

console.log(sql);
