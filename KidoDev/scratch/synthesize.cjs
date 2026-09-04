
const GROQ_API_KEY = process.env.GROQ_API_KEY || '';
const GROQ_API_URL = 'https://api.groq.com/openai/v1/chat/completions';

async function getGroqCompletion(systemPrompt, userPrompt) {
    const response = await fetch(GROQ_API_URL, {
        method: 'POST',
        headers: {
            'Authorization': `Bearer ${GROQ_API_KEY}`,
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            model: 'llama-3.3-70b-versatile',
            messages: [
                { role: 'system', content: systemPrompt },
                { role: 'user', content: userPrompt }
            ],
            temperature: 0.1,
        }),
    });
    const data = await response.json();
    return data.choices?.[0]?.message?.content || '';
}

const systemPrompt = `You are the Kido Dev Master Architect. Convert project into technical spec.
KIDO BLOCKLY SCHEMA:
- Motion: s_move(STEPS), s_turn_r(DEG), s_turn_l(DEG), s_goto_xy(X,Y), s_glide_xy(SECS,X,Y), s_point_dir(DIR), s_change_x(X), s_change_y(Y)
- Looks: s_say(MSG), s_say_timed(MSG, SECS), s_next_costume, s_next_backdrop, s_backdrop(BACKDROP), s_show, s_hide, s_set_size(SIZE)
- Sound: s_start_sound(SOUND), s_play_sound(SOUND), s_stop_sounds (Available sounds: meow, bark, croak, chomp, pop, laser, coin, dance, jungle, drum)
- Events: s_when_flag, s_when_clicked, s_when_key(KEY: space, up, down, left, right), s_when_receive(MSG), s_broadcast(MSG)
- Control: s_wait(SECS), s_repeat(N), s_forever, s_if(COND), s_if_else(COND)

XML RULES:
- IMPORTANT: Numeric inputs must be wrapped in <value name='NAME'><shadow type="math_number"><field name="NUM">X</field></shadow></value>
- IMPORTANT: String inputs must be wrapped in <value name='NAME'><shadow type="text"><field name="TEXT">X</field></shadow></value>
- IMPORTANT: Nested blocks MUST go inside <next> tags.
- Event blocks (s_when_flag, s_when_key, s_when_clicked) have NO previous statement.

OUTPUT FORMAT (JSON):
{
  "xml": "<xml xmlns=\"https://developers.google.com/blockly/xml\">...</xml>",
  "steps": [{"message": "🌟 Step description with emoji for a child", "check_xml_contains": "s_block_type"}],
  "solve_message": "Friendly high-five message",
  "solve_tip": "Pro tip for this project"
}
Respond ONLY with JSON.`;

async function run() {
    const projects = [
        { id: 'L1P1', title: 'Hello World!', objective: 'Make the cat walk 10 steps when flag clicked.' },
        { id: 'L1P2', title: 'Make It Talk', objective: 'Sprite moves 10 steps then says "Hello Kido!" for 2 seconds.' },
        { id: 'L1P3', title: 'Sound Walk', objective: 'When flag clicked, Sprite moves 10 steps, plays "meow" sound, and says "I am walking!"' },
        { id: 'L1P4', title: 'The Dancer', objective: 'When flag clicked, repeat 10 times: next costume, wait 0.5s, play "dance" sound.' },
        { id: 'L1P5', title: 'Scene Change', objective: 'When flag clicked, Sprite moves 50 steps, waits 1s, then switches to next backdrop.' },
        { id: 'L1P6', title: 'Appear & Disappear', objective: 'When flag clicked, Sprite shows, waits 2s, then hides.' },
        { id: 'L1P7', title: 'Magic Touch', objective: 'When sprite clicked: change color effect by 25 and play "pop" sound.' },
        { id: 'L1P8', title: 'Keyboard Control', objective: 'Use arrow keys: up (Y+10), down (Y-10), left (X-10), right (X+10). Create 4 separate scripts.' },
        { id: 'L1P9', title: 'Glide & Slide', objective: 'When flag clicked, Sprite glides to X:200, Y:0 in 2 seconds.' },
        { id: 'L1P10', title: 'The Grand Finale', objective: 'When flag clicked, repeat 4 times: move 100 steps, turn right 90 degrees. Then say "Level 1 Complete!"' }
    ];

    const results = [];
    for (const p of projects) {
        console.error(`Processing ${p.id}...`);
        const res = await getGroqCompletion(systemPrompt, `Project: ${p.title}\nObjective: ${p.objective}`);
        try {
            const clean = res.replace(/```json/g, '').replace(/```/g, '').trim();
            const parsed = JSON.parse(clean);
            results.push({ id: p.id, ...parsed });
        } catch (e) {
            console.error(`Error parsing ${p.id}:`, res);
        }
    }
    console.log(JSON.stringify(results, null, 2));
}

run();
