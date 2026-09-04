/**
 * Complete Scratch 3.0-faithful block definitions for Blockly.
 * Covers: Motion, Looks, Sound, Events, Control, Sensing, Operators, Variables, Pen, Lists, My Blocks
 */
import * as Blockly from 'blockly';

export const C = {
    MOTION: '#4C97FF',
    LOOKS: '#9966FF',
    SOUND: '#CF63CF',
    EVENTS: '#FFAB19',
    CONTROL: '#FFAB19',
    SENSING: '#5CB1D6',
    OPERATORS: '#59C059',
    VARIABLES: '#FF8C1A',
    LISTS: '#FF8C1A',
    PEN: '#59C059',
    MYBLOCKS: '#FF6680',
};

function def(name, fn) {
    if (!Blockly.Blocks[name]) Blockly.Blocks[name] = { init: fn };
}

export function defineAllScratchBlocks() {

    // ══════════════════════════════════════════════════════════
    //  EVENTS
    // ══════════════════════════════════════════════════════════
    def('s_when_flag', function () {
        this.appendDummyInput().appendField('🚩 when ▶ clicked');
        this.setNextStatement(true);
        this.setColour(C.EVENTS);
        this.setTooltip('Start when green flag clicked');
    });
    def('s_when_key', function () {
        this.appendDummyInput()
            .appendField('⌨️ when')
            .appendField(new Blockly.FieldDropdown([
                ['space', 'space'], ['enter', 'enter'],
                ['up arrow', 'up'], ['down arrow', 'down'],
                ['right arrow', 'right'], ['left arrow', 'left'],
                ['a', 'a'], ['b', 'b'], ['c', 'c'], ['d', 'd'],
                ['e', 'e'], ['f', 'f'], ['w', 'w'], ['s', 's'], ['any', 'any']
            ]), 'KEY')
            .appendField('key pressed');
        this.setNextStatement(true);
        this.setColour(C.EVENTS);
    });
    def('s_when_clicked', function () {
        this.appendDummyInput().appendField('🖱️ when this sprite clicked');
        this.setNextStatement(true);
        this.setColour(C.EVENTS);
    });
    // Broadcast blocks use a FieldDropdown (not ValueInput) to avoid flyout rendering issues
    const MSG_DD = [['message1', 'message1'], ['message2', 'message2'], ['message3', 'message3']];
    def('s_broadcast', function () {
        this.appendDummyInput()
            .appendField('📡 broadcast')
            .appendField(new Blockly.FieldDropdown(MSG_DD), 'MSG');
        this.setPreviousStatement(true);
        this.setNextStatement(true);
        this.setColour(C.EVENTS);
    });
    def('s_broadcast_wait', function () {
        this.appendDummyInput()
            .appendField('📡 broadcast')
            .appendField(new Blockly.FieldDropdown(MSG_DD), 'MSG')
            .appendField('and wait');
        this.setPreviousStatement(true);
        this.setNextStatement(true);
        this.setColour(C.EVENTS);
    });
    def('s_when_receive', function () {
        this.appendDummyInput()
            .appendField('📥 when I receive')
            .appendField(new Blockly.FieldDropdown(MSG_DD), 'MSG');
        this.setNextStatement(true);
        this.setColour(C.EVENTS);
    });

    // ══════════════════════════════════════════════════════════
    //  MOTION  (all 18 Scratch blocks)
    // ══════════════════════════════════════════════════════════
    def('s_move', function () { this.appendValueInput('STEPS').setCheck('Number').appendField('move'); this.appendDummyInput().appendField('steps'); this.setInputsInline(true); this.setPreviousStatement(true); this.setNextStatement(true); this.setColour(C.MOTION); });
    def('s_turn_r', function () { this.appendValueInput('DEG').setCheck('Number').appendField('↻ turn right'); this.appendDummyInput().appendField('degrees'); this.setInputsInline(true); this.setPreviousStatement(true); this.setNextStatement(true); this.setColour(C.MOTION); });
    def('s_turn_l', function () { this.appendValueInput('DEG').setCheck('Number').appendField('↺ turn left'); this.appendDummyInput().appendField('degrees'); this.setInputsInline(true); this.setPreviousStatement(true); this.setNextStatement(true); this.setColour(C.MOTION); });
    def('s_goto_xy', function () { this.appendValueInput('X').setCheck('Number').appendField('go to x:'); this.appendValueInput('Y').setCheck('Number').appendField('y:'); this.setInputsInline(true); this.setPreviousStatement(true); this.setNextStatement(true); this.setColour(C.MOTION); });
    def('s_goto_pos', function () { this.appendDummyInput().appendField('go to').appendField(new Blockly.FieldDropdown([['random position', 'random'], ['mouse-pointer', 'mouse']]), 'POS'); this.setPreviousStatement(true); this.setNextStatement(true); this.setColour(C.MOTION); });
    def('s_glide_xy', function () { this.appendValueInput('SECS').setCheck('Number').appendField('glide'); this.appendDummyInput().appendField('secs to x:'); this.appendValueInput('X').setCheck('Number'); this.appendDummyInput().appendField('y:'); this.appendValueInput('Y').setCheck('Number'); this.setInputsInline(true); this.setPreviousStatement(true); this.setNextStatement(true); this.setColour(C.MOTION); });
    def('s_glide_pos', function () { this.appendValueInput('SECS').setCheck('Number').appendField('glide'); this.appendDummyInput().appendField('secs to').appendField(new Blockly.FieldDropdown([['random position', 'random'], ['mouse-pointer', 'mouse']]), 'POS'); this.setInputsInline(true); this.setPreviousStatement(true); this.setNextStatement(true); this.setColour(C.MOTION); });
    def('s_point_dir', function () { this.appendValueInput('DIR').setCheck('Number').appendField('point in direction'); this.setInputsInline(true); this.setPreviousStatement(true); this.setNextStatement(true); this.setColour(C.MOTION); });
    def('s_point_to', function () { this.appendDummyInput().appendField('point towards').appendField(new Blockly.FieldDropdown([['mouse-pointer', 'mouse']]), 'TARGET'); this.setPreviousStatement(true); this.setNextStatement(true); this.setColour(C.MOTION); });
    def('s_set_x', function () { this.appendValueInput('X').setCheck('Number').appendField('set x to'); this.setInputsInline(true); this.setPreviousStatement(true); this.setNextStatement(true); this.setColour(C.MOTION); });
    def('s_set_y', function () { this.appendValueInput('Y').setCheck('Number').appendField('set y to'); this.setInputsInline(true); this.setPreviousStatement(true); this.setNextStatement(true); this.setColour(C.MOTION); });
    def('s_change_x', function () { this.appendValueInput('X').setCheck('Number').appendField('change x by'); this.setInputsInline(true); this.setPreviousStatement(true); this.setNextStatement(true); this.setColour(C.MOTION); });
    def('s_change_y', function () { this.appendValueInput('Y').setCheck('Number').appendField('change y by'); this.setInputsInline(true); this.setPreviousStatement(true); this.setNextStatement(true); this.setColour(C.MOTION); });
    def('s_bounce', function () { this.appendDummyInput().appendField('if on edge, bounce'); this.setPreviousStatement(true); this.setNextStatement(true); this.setColour(C.MOTION); });
    def('s_rot_style', function () { this.appendDummyInput().appendField('set rotation style').appendField(new Blockly.FieldDropdown([['left-right', 'lr'], ['all around', 'all'], ["don't rotate", 'none']]), 'STYLE'); this.setPreviousStatement(true); this.setNextStatement(true); this.setColour(C.MOTION); });
    // Reporters
    def('s_x_pos', function () { this.setOutput(true, 'Number'); this.appendDummyInput().appendField('x position'); this.setColour(C.MOTION); });
    def('s_y_pos', function () { this.setOutput(true, 'Number'); this.appendDummyInput().appendField('y position'); this.setColour(C.MOTION); });
    def('s_dir', function () { this.setOutput(true, 'Number'); this.appendDummyInput().appendField('direction'); this.setColour(C.MOTION); });

    // ══════════════════════════════════════════════════════════
    //  LOOKS  (all 21 Scratch blocks)
    // ══════════════════════════════════════════════════════════
    def('s_say_timed', function () { this.appendValueInput('MSG').setCheck('String').appendField('💬 say'); this.appendValueInput('SECS').setCheck('Number').appendField('for'); this.appendDummyInput().appendField('seconds'); this.setInputsInline(true); this.setPreviousStatement(true); this.setNextStatement(true); this.setColour(C.LOOKS); });
    def('s_say', function () { this.appendValueInput('MSG').setCheck('String').appendField('💬 say'); this.setInputsInline(true); this.setPreviousStatement(true); this.setNextStatement(true); this.setColour(C.LOOKS); });
    def('s_think_timed', function () { this.appendValueInput('MSG').setCheck('String').appendField('💭 think'); this.appendValueInput('SECS').setCheck('Number').appendField('for'); this.appendDummyInput().appendField('seconds'); this.setInputsInline(true); this.setPreviousStatement(true); this.setNextStatement(true); this.setColour(C.LOOKS); });
    def('s_think', function () { this.appendValueInput('MSG').setCheck('String').appendField('💭 think'); this.setInputsInline(true); this.setPreviousStatement(true); this.setNextStatement(true); this.setColour(C.LOOKS); });
    def('s_next_costume', function () { this.appendDummyInput().appendField('next costume'); this.setPreviousStatement(true); this.setNextStatement(true); this.setColour(C.LOOKS); });
    def('s_next_backdrop', function () { this.appendDummyInput().appendField('next backdrop'); this.setPreviousStatement(true); this.setNextStatement(true); this.setColour(C.LOOKS); });
    def('s_backdrop', function () {
        this.appendDummyInput()
            .appendField('switch backdrop to')
            .appendField(new Blockly.FieldDropdown([
                ['White Stage', 'White Stage'], ['Bedroom 1', 'Bedroom 1'],
                ['Jungle', 'Jungle'], ['Safari', 'Safari'],
                ['Space', 'Space'], ['Ocean', 'Ocean'],
                ['City', 'City'], ['Forest', 'Forest'],
                ['Desert', 'Desert'], ['Snow', 'Snow'],
                ['Volcano', 'Volcano'], ['Castle', 'Castle'],
                ['Stadium', 'Stadium'], ['Stage', 'Stage']
            ]), 'BACKDROP');
        this.setPreviousStatement(true);
        this.setNextStatement(true);
        this.setColour(C.LOOKS);
    });
    def('s_set_size', function () { this.appendValueInput('SIZE').setCheck('Number').appendField('set size to'); this.appendDummyInput().appendField('%'); this.setInputsInline(true); this.setPreviousStatement(true); this.setNextStatement(true); this.setColour(C.LOOKS); });
    def('s_change_size', function () { this.appendValueInput('AMT').setCheck('Number').appendField('change size by'); this.setInputsInline(true); this.setPreviousStatement(true); this.setNextStatement(true); this.setColour(C.LOOKS); });
    def('s_change_effect', function () { this.appendValueInput('VAL').setCheck('Number').appendField('change').appendField(new Blockly.FieldDropdown([['color', 'color'], ['fisheye', 'fisheye'], ['whirl', 'whirl'], ['pixelate', 'pixelate'], ['mosaic', 'mosaic'], ['brightness', 'brightness'], ['ghost', 'ghost']]), 'EFFECT').appendField('effect by'); this.setInputsInline(true); this.setPreviousStatement(true); this.setNextStatement(true); this.setColour(C.LOOKS); });
    def('s_set_effect', function () { this.appendValueInput('VAL').setCheck('Number').appendField('set').appendField(new Blockly.FieldDropdown([['color', 'color'], ['fisheye', 'fisheye'], ['whirl', 'whirl'], ['pixelate', 'pixelate'], ['mosaic', 'mosaic'], ['brightness', 'brightness'], ['ghost', 'ghost']]), 'EFFECT').appendField('effect to'); this.setInputsInline(true); this.setPreviousStatement(true); this.setNextStatement(true); this.setColour(C.LOOKS); });
    def('s_clear_fx', function () { this.appendDummyInput().appendField('✨ clear graphic effects'); this.setPreviousStatement(true); this.setNextStatement(true); this.setColour(C.LOOKS); });
    def('s_show', function () { this.appendDummyInput().appendField('👁️ show'); this.setPreviousStatement(true); this.setNextStatement(true); this.setColour(C.LOOKS); });
    def('s_hide', function () { this.appendDummyInput().appendField('🙈 hide'); this.setPreviousStatement(true); this.setNextStatement(true); this.setColour(C.LOOKS); });
    def('s_go_front', function () { this.appendDummyInput().appendField('go to').appendField(new Blockly.FieldDropdown([['front', 'front'], ['back', 'back']]), 'LAYER').appendField('layer'); this.setPreviousStatement(true); this.setNextStatement(true); this.setColour(C.LOOKS); });
    def('s_go_layer', function () { this.appendDummyInput().appendField('go').appendField(new Blockly.FieldDropdown([['forward', 'forward'], ['backward', 'backward']]), 'DIR').appendField('1 layer'); this.setPreviousStatement(true); this.setNextStatement(true); this.setColour(C.LOOKS); });
    // Reporters
    def('s_size_r', function () { this.setOutput(true, 'Number'); this.appendDummyInput().appendField('size'); this.setColour(C.LOOKS); });
    def('s_costume_r', function () { this.setOutput(true, 'Number'); this.appendDummyInput().appendField('costume').appendField(new Blockly.FieldDropdown([['number', 'number'], ['name', 'name']]), 'PROP'); this.setColour(C.LOOKS); });

    // ══════════════════════════════════════════════════════════
    //  SOUND
    // ══════════════════════════════════════════════════════════
    def('s_play_sound', function () { this.appendDummyInput().appendField('🔊 play').appendField(new Blockly.FieldDropdown([
        ['Meow (Cat)', 'meow'], ['Bark (Dog)', 'bark'], ['Croak (Frog)', 'croak'],
        ['Chomp', 'chomp'], ['Pop', 'pop'], ['Laser', 'laser'], ['Coin', 'coin'],
        ['Dance Music', 'dance'], ['Jungle', 'jungle'], ['Drum', 'drum'],
    ]), 'SOUND').appendField('until done'); this.setPreviousStatement(true); this.setNextStatement(true); this.setColour(C.SOUND); });
    def('s_start_sound', function () { this.appendDummyInput().appendField('▶ start').appendField(new Blockly.FieldDropdown([
        ['Meow (Cat)', 'meow'], ['Bark (Dog)', 'bark'], ['Croak (Frog)', 'croak'],
        ['Chomp', 'chomp'], ['Pop', 'pop'], ['Laser', 'laser'], ['Coin', 'coin'],
        ['Dance Music', 'dance'], ['Jungle', 'jungle'], ['Drum', 'drum'],
    ]), 'SOUND').appendField('sound'); this.setPreviousStatement(true); this.setNextStatement(true); this.setColour(C.SOUND); });
    def('s_stop_sounds', function () { this.appendDummyInput().appendField('⏹ stop all sounds'); this.setPreviousStatement(true); this.setNextStatement(true); this.setColour(C.SOUND); });
    def('s_play_note', function () { this.appendValueInput('NOTE').setCheck('Number').appendField('play note'); this.appendValueInput('BEATS').setCheck('Number').appendField('for'); this.appendDummyInput().appendField('beats'); this.setInputsInline(true); this.setPreviousStatement(true); this.setNextStatement(true); this.setColour(C.SOUND); });
    def('s_rest', function () { this.appendValueInput('BEATS').setCheck('Number').appendField('rest for'); this.appendDummyInput().appendField('beats'); this.setInputsInline(true); this.setPreviousStatement(true); this.setNextStatement(true); this.setColour(C.SOUND); });
    def('s_set_tempo', function () { this.appendValueInput('BPM').setCheck('Number').appendField('set tempo to'); this.appendDummyInput().appendField('bpm'); this.setInputsInline(true); this.setPreviousStatement(true); this.setNextStatement(true); this.setColour(C.SOUND); });
    def('s_change_tempo', function () { this.appendValueInput('AMT').setCheck('Number').appendField('change tempo by'); this.setInputsInline(true); this.setPreviousStatement(true); this.setNextStatement(true); this.setColour(C.SOUND); });
    def('s_tempo_r', function () { this.setOutput(true, 'Number'); this.appendDummyInput().appendField('tempo'); this.setColour(C.SOUND); });
    def('s_set_vol', function () { this.appendValueInput('VOL').setCheck('Number').appendField('set volume to'); this.appendDummyInput().appendField('%'); this.setInputsInline(true); this.setPreviousStatement(true); this.setNextStatement(true); this.setColour(C.SOUND); });
    def('s_change_vol', function () { this.appendValueInput('AMT').setCheck('Number').appendField('change volume by'); this.setInputsInline(true); this.setPreviousStatement(true); this.setNextStatement(true); this.setColour(C.SOUND); });
    def('s_vol_r', function () { this.setOutput(true, 'Number'); this.appendDummyInput().appendField('volume'); this.setColour(C.SOUND); });

    // ══════════════════════════════════════════════════════════
    //  CONTROL
    // ══════════════════════════════════════════════════════════
    def('s_wait', function () { this.appendValueInput('SECS').setCheck('Number').appendField('⏱️ wait'); this.appendDummyInput().appendField('seconds'); this.setInputsInline(true); this.setPreviousStatement(true); this.setNextStatement(true); this.setColour(C.CONTROL); });
    def('s_repeat', function () { this.appendValueInput('N').setCheck('Number').appendField('🔁 repeat'); this.appendStatementInput('DO').setCheck(null); this.setInputsInline(true); this.setPreviousStatement(true); this.setNextStatement(true); this.setColour(C.CONTROL); });
    def('s_forever', function () { this.appendStatementInput('DO').setCheck(null).appendField('♾️ forever'); this.setPreviousStatement(true); this.setColour(C.CONTROL); });
    def('s_if', function () { this.appendValueInput('COND').setCheck('Boolean').appendField('❓ if'); this.appendStatementInput('DO').setCheck(null).appendField('then'); this.setPreviousStatement(true); this.setNextStatement(true); this.setColour(C.CONTROL); });
    def('s_if_else', function () { this.appendValueInput('COND').setCheck('Boolean').appendField('❓ if'); this.appendStatementInput('DO').setCheck(null).appendField('then'); this.appendStatementInput('ELSE').setCheck(null).appendField('else'); this.setPreviousStatement(true); this.setNextStatement(true); this.setColour(C.CONTROL); });
    def('s_wait_until', function () { this.appendValueInput('COND').setCheck('Boolean').appendField('⏳ wait until'); this.setInputsInline(true); this.setPreviousStatement(true); this.setNextStatement(true); this.setColour(C.CONTROL); });
    def('s_repeat_until', function () { this.appendValueInput('COND').setCheck('Boolean').appendField('🔁 repeat until'); this.appendStatementInput('DO').setCheck(null); this.setInputsInline(true); this.setPreviousStatement(true); this.setNextStatement(true); this.setColour(C.CONTROL); });
    def('s_stop', function () { this.appendDummyInput().appendField('🛑 stop').appendField(new Blockly.FieldDropdown([['all', 'all'], ['this script', 'script'], ['other scripts', 'others']]), 'WHICH'); this.setPreviousStatement(true); this.setColour(C.CONTROL); });
    def('s_create_clone', function () { this.appendDummyInput().appendField('🐱 create clone of').appendField(new Blockly.FieldDropdown([['myself', 'myself']]), 'TARGET'); this.setPreviousStatement(true); this.setNextStatement(true); this.setColour(C.CONTROL); });
    def('s_when_clone', function () { this.appendDummyInput().appendField('🐱 when I start as a clone'); this.setNextStatement(true); this.setColour(C.CONTROL); });
    def('s_del_clone', function () { this.appendDummyInput().appendField('🗑️ delete this clone'); this.setPreviousStatement(true); this.setColour(C.CONTROL); });

    // ══════════════════════════════════════════════════════════
    //  SENSING
    // ══════════════════════════════════════════════════════════
    def('s_touching_mouse', function () { this.setOutput(true, 'Boolean'); this.appendDummyInput().appendField('touching mouse-pointer?'); this.setColour(C.SENSING); });
    def('s_touching_edge', function () { this.setOutput(true, 'Boolean'); this.appendDummyInput().appendField('touching edge?'); this.setColour(C.SENSING); });
    def('s_key_pressed', function () { this.setOutput(true, 'Boolean'); this.appendDummyInput().appendField('key').appendField(new Blockly.FieldDropdown([['space', 'space'], ['up arrow', 'up'], ['down arrow', 'down'], ['right arrow', 'right'], ['left arrow', 'left'], ['any', 'any']]), 'KEY').appendField('pressed?'); this.setColour(C.SENSING); });
    def('s_mouse_down', function () { this.setOutput(true, 'Boolean'); this.appendDummyInput().appendField('mouse down?'); this.setColour(C.SENSING); });
    def('s_mouse_x', function () { this.setOutput(true, 'Number'); this.appendDummyInput().appendField('mouse x'); this.setColour(C.SENSING); });
    def('s_mouse_y', function () { this.setOutput(true, 'Number'); this.appendDummyInput().appendField('mouse y'); this.setColour(C.SENSING); });
    def('s_dist_to', function () { this.setOutput(true, 'Number'); this.appendDummyInput().appendField('distance to').appendField(new Blockly.FieldDropdown([['mouse-pointer', 'mouse']]), 'TARGET'); this.setColour(C.SENSING); });
    def('s_ask', function () { this.appendValueInput('Q').setCheck('String').appendField('🔷 ask'); this.appendDummyInput().appendField('and wait'); this.setInputsInline(true); this.setPreviousStatement(true); this.setNextStatement(true); this.setColour(C.SENSING); });
    def('s_answer', function () { this.setOutput(true, 'String'); this.appendDummyInput().appendField('answer'); this.setColour(C.SENSING); });
    def('s_timer', function () { this.setOutput(true, 'Number'); this.appendDummyInput().appendField('timer'); this.setColour(C.SENSING); });
    def('s_reset_timer', function () { this.appendDummyInput().appendField('reset timer'); this.setPreviousStatement(true); this.setNextStatement(true); this.setColour(C.SENSING); });
    def('s_current_time', function () { this.setOutput(true, 'Number'); this.appendDummyInput().appendField('current').appendField(new Blockly.FieldDropdown([['year', 'year'], ['month', 'month'], ['date', 'date'], ['day of week', 'dayofweek'], ['hour', 'hour'], ['minute', 'minute'], ['second', 'second']]), 'WHICH'); this.setColour(C.SENSING); });
    def('s_loudness', function () { this.setOutput(true, 'Number'); this.appendDummyInput().appendField('loudness'); this.setColour(C.SENSING); });

    // ══════════════════════════════════════════════════════════
    //  OPERATORS
    // ══════════════════════════════════════════════════════════
    def('s_add', function () { this.setOutput(true, 'Number'); this.appendValueInput('A').setCheck('Number'); this.appendDummyInput().appendField('+'); this.appendValueInput('B').setCheck('Number'); this.setInputsInline(true); this.setColour(C.OPERATORS); });
    def('s_sub', function () { this.setOutput(true, 'Number'); this.appendValueInput('A').setCheck('Number'); this.appendDummyInput().appendField('-'); this.appendValueInput('B').setCheck('Number'); this.setInputsInline(true); this.setColour(C.OPERATORS); });
    def('s_mul', function () { this.setOutput(true, 'Number'); this.appendValueInput('A').setCheck('Number'); this.appendDummyInput().appendField('×'); this.appendValueInput('B').setCheck('Number'); this.setInputsInline(true); this.setColour(C.OPERATORS); });
    def('s_div', function () { this.setOutput(true, 'Number'); this.appendValueInput('A').setCheck('Number'); this.appendDummyInput().appendField('÷'); this.appendValueInput('B').setCheck('Number'); this.setInputsInline(true); this.setColour(C.OPERATORS); });
    def('s_mod', function () { this.setOutput(true, 'Number'); this.appendValueInput('A').setCheck('Number'); this.appendDummyInput().appendField('mod'); this.appendValueInput('B').setCheck('Number'); this.setInputsInline(true); this.setColour(C.OPERATORS); });
    def('s_round', function () { this.setOutput(true, 'Number'); this.appendValueInput('A').setCheck('Number').appendField('round'); this.setInputsInline(true); this.setColour(C.OPERATORS); });
    def('s_random', function () { this.setOutput(true, 'Number'); this.appendValueInput('FROM').setCheck('Number').appendField('pick random'); this.appendValueInput('TO').setCheck('Number').appendField('to'); this.setInputsInline(true); this.setColour(C.OPERATORS); });
    def('s_gt', function () { this.setOutput(true, 'Boolean'); this.appendValueInput('A'); this.appendDummyInput().appendField('>'); this.appendValueInput('B'); this.setInputsInline(true); this.setColour(C.OPERATORS); });
    def('s_lt', function () { this.setOutput(true, 'Boolean'); this.appendValueInput('A'); this.appendDummyInput().appendField('<'); this.appendValueInput('B'); this.setInputsInline(true); this.setColour(C.OPERATORS); });
    def('s_eq', function () { this.setOutput(true, 'Boolean'); this.appendValueInput('A'); this.appendDummyInput().appendField('='); this.appendValueInput('B'); this.setInputsInline(true); this.setColour(C.OPERATORS); });
    def('s_and', function () { this.setOutput(true, 'Boolean'); this.appendValueInput('A').setCheck('Boolean'); this.appendDummyInput().appendField('and'); this.appendValueInput('B').setCheck('Boolean'); this.setInputsInline(true); this.setColour(C.OPERATORS); });
    def('s_or', function () { this.setOutput(true, 'Boolean'); this.appendValueInput('A').setCheck('Boolean'); this.appendDummyInput().appendField('or'); this.appendValueInput('B').setCheck('Boolean'); this.setInputsInline(true); this.setColour(C.OPERATORS); });
    def('s_not', function () { this.setOutput(true, 'Boolean'); this.appendValueInput('A').setCheck('Boolean').appendField('not'); this.setInputsInline(true); this.setColour(C.OPERATORS); });
    def('s_join', function () { this.setOutput(true, 'String'); this.appendValueInput('A').appendField('join'); this.appendValueInput('B'); this.setInputsInline(true); this.setColour(C.OPERATORS); });
    def('s_length', function () { this.setOutput(true, 'Number'); this.appendValueInput('STR').appendField('length of'); this.setInputsInline(true); this.setColour(C.OPERATORS); });
    def('s_contains', function () { this.setOutput(true, 'Boolean'); this.appendValueInput('STR'); this.appendDummyInput().appendField('contains'); this.appendValueInput('Q'); this.setInputsInline(true); this.setColour(C.OPERATORS); });
    def('s_mathop', function () { this.setOutput(true, 'Number'); this.appendValueInput('NUM').setCheck('Number').appendField(new Blockly.FieldDropdown([['abs', 'abs'], ['floor', 'floor'], ['ceiling', 'ceiling'], ['sqrt', 'sqrt'], ['sin', 'sin'], ['cos', 'cos'], ['tan', 'tan'], ['asin', 'asin'], ['acos', 'acos'], ['atan', 'atan'], ['ln', 'ln'], ['log', 'log'], ['e^', 'e^'], ['10^', '10^']]), 'OP'); this.setInputsInline(true); this.setColour(C.OPERATORS); });

    // ══════════════════════════════════════════════════════════
    //  VARIABLES
    // ══════════════════════════════════════════════════════════
    def('s_set_var', function () { this.appendValueInput('VAL').setCheck(null).appendField('set').appendField(new Blockly.FieldDropdown([['score', 'score'], ['lives', 'lives'], ['x', 'x'], ['y', 'y'], ['speed', 'speed'], ['timer', 'timer'], ['level', 'level'], ['health', 'health']]), 'VAR').appendField('to'); this.setInputsInline(true); this.setPreviousStatement(true); this.setNextStatement(true); this.setColour(C.VARIABLES); });
    def('s_change_var', function () { this.appendValueInput('AMT').setCheck('Number').appendField('change').appendField(new Blockly.FieldDropdown([['score', 'score'], ['lives', 'lives'], ['x', 'x'], ['y', 'y'], ['speed', 'speed'], ['timer', 'timer'], ['level', 'level'], ['health', 'health']]), 'VAR').appendField('by'); this.setInputsInline(true); this.setPreviousStatement(true); this.setNextStatement(true); this.setColour(C.VARIABLES); });
    def('s_var_r', function () { this.setOutput(true, 'Number'); this.appendDummyInput().appendField(new Blockly.FieldDropdown([['score', 'score'], ['lives', 'lives'], ['x', 'x'], ['y', 'y'], ['speed', 'speed'], ['timer', 'timer'], ['level', 'level'], ['health', 'health']]), 'VAR'); this.setColour(C.VARIABLES); });
    def('s_show_var', function () { this.appendDummyInput().appendField('show variable').appendField(new Blockly.FieldDropdown([['score', 'score'], ['lives', 'lives'], ['speed', 'speed'], ['health', 'health']]), 'VAR'); this.setPreviousStatement(true); this.setNextStatement(true); this.setColour(C.VARIABLES); });
    def('s_hide_var', function () { this.appendDummyInput().appendField('hide variable').appendField(new Blockly.FieldDropdown([['score', 'score'], ['lives', 'lives'], ['speed', 'speed'], ['health', 'health']]), 'VAR'); this.setPreviousStatement(true); this.setNextStatement(true); this.setColour(C.VARIABLES); });

    // ══════════════════════════════════════════════════════════
    //  LISTS
    // ══════════════════════════════════════════════════════════
    const LISTS_DD = [['myList', 'myList'], ['highScores', 'highScores'], ['items', 'items']];
    def('s_list_add', function () { this.appendValueInput('ITEM').appendField('add'); this.appendDummyInput().appendField('to').appendField(new Blockly.FieldDropdown(LISTS_DD), 'LIST'); this.setInputsInline(true); this.setPreviousStatement(true); this.setNextStatement(true); this.setColour(C.LISTS); });
    def('s_list_del', function () { this.appendValueInput('IDX').setCheck('Number').appendField('delete item'); this.appendDummyInput().appendField('of').appendField(new Blockly.FieldDropdown(LISTS_DD), 'LIST'); this.setInputsInline(true); this.setPreviousStatement(true); this.setNextStatement(true); this.setColour(C.LISTS); });
    def('s_list_del_all', function () { this.appendDummyInput().appendField('delete all of').appendField(new Blockly.FieldDropdown(LISTS_DD), 'LIST'); this.setPreviousStatement(true); this.setNextStatement(true); this.setColour(C.LISTS); });
    def('s_list_insert', function () { this.appendValueInput('ITEM').appendField('insert'); this.appendDummyInput().appendField('at'); this.appendValueInput('IDX').setCheck('Number').appendField('of').appendField(new Blockly.FieldDropdown(LISTS_DD), 'LIST'); this.setInputsInline(true); this.setPreviousStatement(true); this.setNextStatement(true); this.setColour(C.LISTS); });
    def('s_list_replace', function () { this.appendDummyInput().appendField('replace item'); this.appendValueInput('IDX').setCheck('Number'); this.appendDummyInput().appendField('of').appendField(new Blockly.FieldDropdown(LISTS_DD), 'LIST').appendField('with'); this.appendValueInput('ITEM'); this.setInputsInline(true); this.setPreviousStatement(true); this.setNextStatement(true); this.setColour(C.LISTS); });
    def('s_list_item', function () { this.setOutput(true); this.appendDummyInput().appendField('item'); this.appendValueInput('IDX').setCheck('Number'); this.appendDummyInput().appendField('of').appendField(new Blockly.FieldDropdown(LISTS_DD), 'LIST'); this.setInputsInline(true); this.setColour(C.LISTS); });
    def('s_list_idx', function () { this.setOutput(true, 'Number'); this.appendValueInput('ITEM').appendField('item # of'); this.appendDummyInput().appendField(new Blockly.FieldDropdown(LISTS_DD), 'LIST'); this.setInputsInline(true); this.setColour(C.LISTS); });
    def('s_list_len', function () { this.setOutput(true, 'Number'); this.appendDummyInput().appendField('length of').appendField(new Blockly.FieldDropdown(LISTS_DD), 'LIST'); this.setColour(C.LISTS); });
    def('s_list_contains', function () { this.setOutput(true, 'Boolean'); this.appendDummyInput().appendField(new Blockly.FieldDropdown(LISTS_DD), 'LIST').appendField('contains'); this.appendValueInput('ITEM'); this.setInputsInline(true); this.setColour(C.LISTS); });
    def('s_list_show', function () { this.appendDummyInput().appendField('show list').appendField(new Blockly.FieldDropdown(LISTS_DD), 'LIST'); this.setPreviousStatement(true); this.setNextStatement(true); this.setColour(C.LISTS); });
    def('s_list_hide', function () { this.appendDummyInput().appendField('hide list').appendField(new Blockly.FieldDropdown(LISTS_DD), 'LIST'); this.setPreviousStatement(true); this.setNextStatement(true); this.setColour(C.LISTS); });

    // ══════════════════════════════════════════════════════════
    //  PEN EXTENSION
    // ══════════════════════════════════════════════════════════
    def('s_pen_down', function () { this.appendDummyInput().appendField('✏️ pen down'); this.setPreviousStatement(true); this.setNextStatement(true); this.setColour(C.PEN); });
    def('s_pen_up', function () { this.appendDummyInput().appendField('✏️ pen up'); this.setPreviousStatement(true); this.setNextStatement(true); this.setColour(C.PEN); });
    def('s_pen_clear', function () { this.appendDummyInput().appendField('🗑️ erase all'); this.setPreviousStatement(true); this.setNextStatement(true); this.setColour(C.PEN); });
    def('s_pen_stamp', function () { this.appendDummyInput().appendField('🖨️ stamp'); this.setPreviousStatement(true); this.setNextStatement(true); this.setColour(C.PEN); });
    def('s_pen_color', function () { this.appendValueInput('COLOR').appendField('set pen color to'); this.setInputsInline(true); this.setPreviousStatement(true); this.setNextStatement(true); this.setColour(C.PEN); });
    def('s_pen_color_eff', function () { this.appendValueInput('VAL').setCheck('Number').appendField('change pen').appendField(new Blockly.FieldDropdown([['color', 'color'], ['saturation', 'saturation'], ['brightness', 'brightness'], ['transparency', 'transparency']]), 'PROP').appendField('by'); this.setInputsInline(true); this.setPreviousStatement(true); this.setNextStatement(true); this.setColour(C.PEN); });
    def('s_pen_set_eff', function () { this.appendValueInput('VAL').setCheck('Number').appendField('set pen').appendField(new Blockly.FieldDropdown([['color', 'color'], ['saturation', 'saturation'], ['brightness', 'brightness'], ['transparency', 'transparency']]), 'PROP').appendField('to'); this.setInputsInline(true); this.setPreviousStatement(true); this.setNextStatement(true); this.setColour(C.PEN); });
    def('s_pen_size', function () { this.appendValueInput('SIZE').setCheck('Number').appendField('set pen size to'); this.setInputsInline(true); this.setPreviousStatement(true); this.setNextStatement(true); this.setColour(C.PEN); });
    def('s_pen_dsize', function () { this.appendValueInput('AMT').setCheck('Number').appendField('change pen size by'); this.setInputsInline(true); this.setPreviousStatement(true); this.setNextStatement(true); this.setColour(C.PEN); });

    // ══════════════════════════════════════════════════════════
    //  MY BLOCKS (Custom Procedures)
    // ══════════════════════════════════════════════════════════
    def('s_my_block_call', function () { this.appendDummyInput().appendField('🔧').appendField(new Blockly.FieldTextInput('my block'), 'NAME'); this.setPreviousStatement(true); this.setNextStatement(true); this.setColour(C.MYBLOCKS); });
    def('s_my_block_def', function () { this.appendDummyInput().appendField('define').appendField(new Blockly.FieldTextInput('my block'), 'NAME'); this.setNextStatement(true); this.setColour(C.MYBLOCKS); });
}

// ══════════════════════════════════════════════════════════════════════
//  TOOLBOX DEFINITION
// ══════════════════════════════════════════════════════════════════════
const N = (type, inputs = {}) => ({ kind: 'block', type, inputs });
const S = (v) => ({ shadow: { type: 'math_number', fields: { NUM: v } } });
const ST = (v) => ({ shadow: { type: 'text', fields: { TEXT: v } } });

export const SCRATCH_TOOLBOX = {
    kind: 'categoryToolbox',
    contents: [
        {
            kind: 'category', name: 'Motion', colour: C.MOTION,
            cssConfig: { icon: 'cat-icon-motion' },
            contents: [
                N('s_move', { STEPS: S(10) }),
                N('s_turn_r', { DEG: S(15) }),
                N('s_turn_l', { DEG: S(15) }),
                N('s_goto_xy', { X: S(0), Y: S(0) }),
                N('s_goto_pos'),
                N('s_glide_xy', { SECS: S(1), X: S(100), Y: S(0) }),
                N('s_glide_pos', { SECS: S(1) }),
                N('s_point_dir', { DIR: S(90) }),
                N('s_point_to'),
                N('s_set_x', { X: S(0) }),
                N('s_set_y', { Y: S(0) }),
                N('s_change_x', { X: S(10) }),
                N('s_change_y', { Y: S(10) }),
                N('s_bounce'),
                N('s_rot_style'),
                N('s_x_pos'), N('s_y_pos'), N('s_dir'),
            ]
        },
        {
            kind: 'category', name: 'Looks', colour: C.LOOKS,
            cssConfig: { icon: 'cat-icon-looks' },
            contents: [
                N('s_say_timed', { MSG: ST('Hello!'), SECS: S(2) }),
                N('s_say', { MSG: ST('Hello!') }),
                N('s_think_timed', { MSG: ST('Hmm...'), SECS: S(2) }),
                N('s_think', { MSG: ST('Hmm...') }),
                N('s_next_costume'), N('s_next_backdrop'), N('s_backdrop'),
                N('s_set_size', { SIZE: S(100) }),
                N('s_change_size', { AMT: S(10) }),
                N('s_change_effect', { VAL: S(25) }),
                N('s_set_effect', { VAL: S(0) }),
                N('s_clear_fx'),
                N('s_show'), N('s_hide'),
                N('s_go_front'), N('s_go_layer'),
                N('s_size_r'), N('s_costume_r'),
            ]
        },
        {
            kind: 'category', name: 'Sound', colour: C.SOUND,
            cssConfig: { icon: 'cat-icon-sound' },
            contents: [
                N('s_play_sound'), N('s_start_sound'), N('s_stop_sounds'),
                { kind: 'sep' },
                N('s_play_note', { NOTE: S(60), BEATS: S(0.25) }),
                N('s_rest', { BEATS: S(0.25) }),
                N('s_set_tempo', { BPM: S(120) }),
                N('s_change_tempo', { AMT: S(20) }),
                N('s_tempo_r'),
                { kind: 'sep' },
                N('s_set_vol', { VOL: S(100) }),
                N('s_change_vol', { AMT: S(-10) }),
                N('s_vol_r'),
            ]
        },
        {
            kind: 'category', name: 'Events', colour: C.EVENTS,
            cssConfig: { icon: 'cat-icon-events' },
            contents: [
                N('s_when_flag'),
                N('s_when_key'),
                N('s_when_clicked'),
                { kind: 'sep' },
                N('s_when_receive'),
                N('s_broadcast'),
                N('s_broadcast_wait'),
            ]
        },
        {
            kind: 'category', name: 'Control', colour: C.CONTROL,
            cssConfig: { icon: 'cat-icon-control' },
            contents: [
                N('s_wait', { SECS: S(1) }),
                N('s_repeat', { N: S(10) }),
                N('s_forever'),
                N('s_if'), N('s_if_else'),
                N('s_wait_until'), N('s_repeat_until'),
                N('s_stop'),
                N('s_create_clone'), N('s_when_clone'), N('s_del_clone'),
            ]
        },
        {
            kind: 'category', name: 'Sensing', colour: C.SENSING,
            cssConfig: { icon: 'cat-icon-sensing' },
            contents: [
                N('s_touching_mouse'), N('s_touching_edge'),
                N('s_key_pressed'), N('s_mouse_down'),
                N('s_mouse_x'), N('s_mouse_y'),
                N('s_dist_to'),
                N('s_ask', { Q: ST('What is your name?') }),
                N('s_answer'),
                N('s_timer'), N('s_reset_timer'),
                N('s_current_time'), N('s_loudness'),
            ]
        },
        {
            kind: 'category', name: 'Operators', colour: C.OPERATORS,
            cssConfig: { icon: 'cat-icon-operators' },
            contents: [
                N('s_add', { A: S(0), B: S(0) }),
                N('s_sub', { A: S(0), B: S(0) }),
                N('s_mul', { A: S(0), B: S(0) }),
                N('s_div', { A: S(0), B: S(0) }),
                N('s_mod', { A: S(0), B: S(0) }),
                N('s_round', { A: S(0) }),
                N('s_random', { FROM: S(1), TO: S(10) }),
                { kind: 'sep' },
                N('s_gt', { A: S(50), B: S(50) }),
                N('s_lt', { A: S(50), B: S(50) }),
                N('s_eq', { A: S(50), B: S(50) }),
                N('s_and'), N('s_or'), N('s_not'),
                { kind: 'sep' },
                N('s_join', { A: ST('hello '), B: ST('world') }),
                N('s_length', { STR: ST('world') }),
                N('s_contains', { STR: ST('apple'), Q: ST('a') }),
                N('s_mathop', { NUM: S(9) }),
            ]
        },
        {
            kind: 'category', name: 'Variables', colour: C.VARIABLES,
            cssConfig: { icon: 'cat-icon-variables' },
            contents: [
                N('s_var_r'),
                { kind: 'sep' },
                N('s_set_var', { VAL: S(0) }),
                N('s_change_var', { AMT: S(1) }),
                N('s_show_var'), N('s_hide_var'),
            ]
        },
        {
            kind: 'category', name: 'Lists', colour: C.LISTS,
            cssConfig: { icon: 'cat-icon-lists' },
            contents: [
                N('s_list_add', { ITEM: ST('thing') }),
                N('s_list_del', { IDX: S(1) }),
                N('s_list_del_all'),
                N('s_list_insert', { ITEM: ST('thing'), IDX: S(1) }),
                N('s_list_replace', { IDX: S(1), ITEM: ST('thing') }),
                { kind: 'sep' },
                N('s_list_item', { IDX: S(1) }),
                N('s_list_idx', { ITEM: ST('thing') }),
                N('s_list_len'),
                N('s_list_contains', { ITEM: ST('thing') }),
                { kind: 'sep' },
                N('s_list_show'), N('s_list_hide'),
            ]
        },
        {
            kind: 'category', name: 'Pen', colour: C.PEN,
            cssConfig: { icon: 'cat-icon-pen' },
            contents: [
                N('s_pen_down'), N('s_pen_up'), N('s_pen_clear'), N('s_pen_stamp'),
                { kind: 'sep' },
                N('s_pen_color', { COLOR: ST('#ff0000') }),
                N('s_pen_color_eff', { VAL: S(10) }),
                N('s_pen_set_eff', { VAL: S(50) }),
                { kind: 'sep' },
                N('s_pen_size', { SIZE: S(3) }),
                N('s_pen_dsize', { AMT: S(1) }),
            ]
        },
        {
            kind: 'category', name: 'My Blocks', colour: C.MYBLOCKS,
            cssConfig: { icon: 'cat-icon-myblocks' },
            contents: [
                N('s_my_block_def'),
                N('s_my_block_call'),
            ]
        }
    ]
};

// ══════════════════════════════════════════════════════════════════════
//  COMPILER v2 — AST with runtime expression evaluation
// ══════════════════════════════════════════════════════════════════════

/** Compile a reporter/boolean block into an expression AST node */
export function compileExpr(block) {
    if (!block) return null;
    switch (block.type) {
        case 'math_number': return { t: 'lit', v: parseFloat(block.getFieldValue('NUM')) || 0 };
        case 'text': return { t: 'litS', v: block.getFieldValue('TEXT') || '' };
        // Operators
        case 's_add': return { t: 'op', op: '+', a: compileExpr(block.getInputTargetBlock('A')), b: compileExpr(block.getInputTargetBlock('B')) };
        case 's_sub': return { t: 'op', op: '-', a: compileExpr(block.getInputTargetBlock('A')), b: compileExpr(block.getInputTargetBlock('B')) };
        case 's_mul': return { t: 'op', op: '*', a: compileExpr(block.getInputTargetBlock('A')), b: compileExpr(block.getInputTargetBlock('B')) };
        case 's_div': return { t: 'op', op: '/', a: compileExpr(block.getInputTargetBlock('A')), b: compileExpr(block.getInputTargetBlock('B')) };
        case 's_mod': return { t: 'op', op: '%', a: compileExpr(block.getInputTargetBlock('A')), b: compileExpr(block.getInputTargetBlock('B')) };
        case 's_round': return { t: 'round', a: compileExpr(block.getInputTargetBlock('A')) };
        case 's_random': return { t: 'random', from: compileExpr(block.getInputTargetBlock('FROM')), to: compileExpr(block.getInputTargetBlock('TO')) };
        case 's_gt': return { t: 'cmp', op: '>', a: compileExpr(block.getInputTargetBlock('A')), b: compileExpr(block.getInputTargetBlock('B')) };
        case 's_lt': return { t: 'cmp', op: '<', a: compileExpr(block.getInputTargetBlock('A')), b: compileExpr(block.getInputTargetBlock('B')) };
        case 's_eq': return { t: 'cmp', op: '==', a: compileExpr(block.getInputTargetBlock('A')), b: compileExpr(block.getInputTargetBlock('B')) };
        case 's_and': return { t: 'logic', op: '&&', a: compileExpr(block.getInputTargetBlock('A')), b: compileExpr(block.getInputTargetBlock('B')) };
        case 's_or': return { t: 'logic', op: '||', a: compileExpr(block.getInputTargetBlock('A')), b: compileExpr(block.getInputTargetBlock('B')) };
        case 's_not': return { t: 'not', a: compileExpr(block.getInputTargetBlock('A')) };
        case 's_join': return { t: 'join', a: compileExpr(block.getInputTargetBlock('A')), b: compileExpr(block.getInputTargetBlock('B')) };
        case 's_length': return { t: 'length', a: compileExpr(block.getInputTargetBlock('STR')) };
        case 's_contains': return { t: 'contains', str: compileExpr(block.getInputTargetBlock('STR')), q: compileExpr(block.getInputTargetBlock('Q')) };
        case 's_mathop': return { t: 'mathop', op: block.getFieldValue('OP'), a: compileExpr(block.getInputTargetBlock('NUM')) };
        // Sensing
        case 's_touching_mouse': return { t: 'touchingMouse' };
        case 's_touching_edge': return { t: 'touchingEdge' };
        case 's_key_pressed': return { t: 'keyPressed', key: block.getFieldValue('KEY') };
        case 's_mouse_down': return { t: 'mouseDown' };
        case 's_mouse_x': return { t: 'mouseX' };
        case 's_mouse_y': return { t: 'mouseY' };
        case 's_dist_to': return { t: 'distTo', target: block.getFieldValue('TARGET') };
        case 's_answer': return { t: 'answer' };
        case 's_timer': return { t: 'timer' };
        case 's_current_time': return { t: 'currentTime', which: block.getFieldValue('WHICH') };
        case 's_loudness': return { t: 'lit', v: 0 };
        // Motion reporters
        case 's_x_pos': return { t: 'xPos' };
        case 's_y_pos': return { t: 'yPos' };
        case 's_dir': return { t: 'direction' };
        // Looks reporters
        case 's_size_r': return { t: 'sizeR' };
        case 's_costume_r': return { t: 'costumeR', prop: block.getFieldValue('PROP') };
        // Sound reporters
        case 's_tempo_r': return { t: 'tempoR' };
        case 's_vol_r': return { t: 'volR' };
        // Variable
        case 's_var_r': return { t: 'var', name: block.getFieldValue('VAR') };
        // List reporters
        case 's_list_item': return { t: 'listItem', list: block.getFieldValue('LIST'), idx: compileExpr(block.getInputTargetBlock('IDX')) };
        case 's_list_idx': return { t: 'listIdx', list: block.getFieldValue('LIST'), item: compileExpr(block.getInputTargetBlock('ITEM')) };
        case 's_list_len': return { t: 'listLen', list: block.getFieldValue('LIST') };
        case 's_list_contains': return { t: 'listContains', list: block.getFieldValue('LIST'), item: compileExpr(block.getInputTargetBlock('ITEM')) };
        default: return { t: 'lit', v: 0 };
    }
}

/** Compile value input to expression node with numeric default */
function exprN(block, name, def = 0) {
    const ib = block.getInputTargetBlock(name);
    return ib ? compileExpr(ib) : { t: 'lit', v: def };
}

/** Compile value input to expression node with string default */
function exprS(block, name, def = '') {
    const ib = block.getInputTargetBlock(name);
    return ib ? compileExpr(ib) : { t: 'litS', v: def };
}

/** Compile a chain of connected blocks into an array of statement nodes */
function compileChain(block) {
    const out = [];
    let cur = block;
    while (cur) {
        const node = compileStmt(cur);
        if (node) out.push(node);
        cur = cur.getNextBlock();
    }
    return out;
}

/** Compile inner body of a C-shaped block */
function compileBody(block, slot) {
    const first = block.getInputTargetBlock(slot);
    return first ? compileChain(first) : [];
}

/** Compile a single statement block to an AST node */
function compileStmt(block) {
    if (!block) return null;
    switch (block.type) {
        // Hat blocks — skipped here, handled by compileAllScripts
        case 's_when_flag': case 's_when_key': case 's_when_clicked':
        case 's_when_clone': case 's_when_receive': case 's_my_block_def': return null;
        // Motion
        case 's_move': return { t: 'move', steps: exprN(block, 'STEPS', 10) };
        case 's_turn_r': return { t: 'turn', deg: exprN(block, 'DEG', 15) };
        case 's_turn_l': return { t: 'turnL', deg: exprN(block, 'DEG', 15) };
        case 's_goto_xy': return { t: 'goto', x: exprN(block, 'X'), y: exprN(block, 'Y') };
        case 's_goto_pos': return { t: 'gotoPos', pos: block.getFieldValue('POS') };
        case 's_glide_xy': return { t: 'glide', secs: exprN(block, 'SECS', 1), x: exprN(block, 'X'), y: exprN(block, 'Y') };
        case 's_glide_pos': return { t: 'glidePos', secs: exprN(block, 'SECS', 1), pos: block.getFieldValue('POS') };
        case 's_point_dir': return { t: 'pointDir', dir: exprN(block, 'DIR', 90) };
        case 's_point_to': return { t: 'pointMouse' };
        case 's_set_x': return { t: 'setX', x: exprN(block, 'X') };
        case 's_set_y': return { t: 'setY', y: exprN(block, 'Y') };
        case 's_change_x': return { t: 'dx', v: exprN(block, 'X', 10) };
        case 's_change_y': return { t: 'dy', v: exprN(block, 'Y', 10) };
        case 's_bounce': return { t: 'bounce' };
        case 's_rot_style': return { t: 'rotStyle', v: block.getFieldValue('STYLE') };
        // Looks
        case 's_say_timed': return { t: 'say', msg: exprS(block, 'MSG', 'Hello!'), secs: exprN(block, 'SECS', 2), bubble: 'say', timed: true };
        case 's_say': return { t: 'say', msg: exprS(block, 'MSG', 'Hello!'), secs: { t: 'lit', v: 0 }, bubble: 'say', timed: false };
        case 's_think_timed': return { t: 'say', msg: exprS(block, 'MSG', 'Hmm...'), secs: exprN(block, 'SECS', 2), bubble: 'think', timed: true };
        case 's_think': return { t: 'say', msg: exprS(block, 'MSG', 'Hmm...'), secs: { t: 'lit', v: 0 }, bubble: 'think', timed: false };
        case 's_next_costume': return { t: 'nextCostume' };
        case 's_next_backdrop': return { t: 'nextBackdrop' };
        case 's_backdrop': return { t: 'switchBackdrop', backdrop: { t: 'litS', v: block.getFieldValue('BACKDROP') } };
        case 's_set_size': return { t: 'size', v: exprN(block, 'SIZE', 100) };
        case 's_change_size': return { t: 'dsize', v: exprN(block, 'AMT', 10) };
        case 's_change_effect': return { t: 'deffect', eff: block.getFieldValue('EFFECT'), v: exprN(block, 'VAL', 25) };
        case 's_set_effect': return { t: 'setEffect', eff: block.getFieldValue('EFFECT'), v: exprN(block, 'VAL', 0) };
        case 's_clear_fx': return { t: 'clearFx' };
        case 's_show': return { t: 'vis', v: true };
        case 's_hide': return { t: 'vis', v: false };
        case 's_go_front': return { t: 'goLayer', layer: block.getFieldValue('LAYER') };
        case 's_go_layer': return { t: 'goLayerDir', dir: block.getFieldValue('DIR') };
        // Sound
        case 's_play_sound': return { t: 'sound', snd: block.getFieldValue('SOUND'), wait: true };
        case 's_start_sound': return { t: 'sound', snd: block.getFieldValue('SOUND'), wait: false };
        case 's_stop_sounds': return { t: 'stopSounds' };
        case 's_play_note': return { t: 'playNote', note: exprN(block, 'NOTE', 60), beats: exprN(block, 'BEATS', 0.25) };
        case 's_rest': return { t: 'rest', beats: exprN(block, 'BEATS', 0.25) };
        case 's_set_tempo': return { t: 'tempo', v: exprN(block, 'BPM', 120) };
        case 's_change_tempo': return { t: 'dtempo', v: exprN(block, 'AMT', 20) };
        case 's_set_vol': return { t: 'vol', v: exprN(block, 'VOL', 100) };
        case 's_change_vol': return { t: 'dvol', v: exprN(block, 'AMT', -10) };
        // Control — now produces TREE nodes, not flat unrolled lists
        case 's_wait': return { t: 'wait', secs: exprN(block, 'SECS', 1) };
        case 's_repeat': return { t: 'repeat', count: exprN(block, 'N', 10), body: compileBody(block, 'DO') };
        case 's_forever': return { t: 'forever', body: compileBody(block, 'DO') };
        case 's_if': return { t: 'if', cond: compileExpr(block.getInputTargetBlock('COND')), body: compileBody(block, 'DO') };
        case 's_if_else': return { t: 'ifElse', cond: compileExpr(block.getInputTargetBlock('COND')), body: compileBody(block, 'DO'), else: compileBody(block, 'ELSE') };
        case 's_wait_until': return { t: 'waitUntil', cond: compileExpr(block.getInputTargetBlock('COND')) };
        case 's_repeat_until': return { t: 'repeatUntil', cond: compileExpr(block.getInputTargetBlock('COND')), body: compileBody(block, 'DO') };
        case 's_stop': return { t: 'stop', w: block.getFieldValue('WHICH') };
        case 's_create_clone': return { t: 'clone', target: block.getFieldValue('TARGET') };
        case 's_when_clone': return null;
        case 's_del_clone': return { t: 'delClone' };
        // Sensing
        case 's_ask': return { t: 'ask', q: exprS(block, 'Q', 'What is your name?') };
        case 's_reset_timer': return { t: 'resetTimer' };
        // Variables
        case 's_set_var': return { t: 'setVar', name: block.getFieldValue('VAR'), v: exprN(block, 'VAL', 0) };
        case 's_change_var': return { t: 'dVar', name: block.getFieldValue('VAR'), v: exprN(block, 'AMT', 1) };
        case 's_show_var': return { t: 'showVar', name: block.getFieldValue('VAR') };
        case 's_hide_var': return { t: 'hideVar', name: block.getFieldValue('VAR') };
        // Broadcast
        case 's_broadcast': return { t: 'broadcast', msg: { t: 'litS', v: block.getFieldValue('MSG') || 'message1' }, wait: false };
        case 's_broadcast_wait': return { t: 'broadcast', msg: { t: 'litS', v: block.getFieldValue('MSG') || 'message1' }, wait: true };
        // Pen
        case 's_pen_down': return { t: 'penDown' };
        case 's_pen_up': return { t: 'penUp' };
        case 's_pen_clear': return { t: 'penClear' };
        case 's_pen_stamp': return { t: 'penStamp' };
        case 's_pen_color': return { t: 'penColor', color: exprS(block, 'COLOR', '#ff0000') };
        case 's_pen_color_eff': return { t: 'penDProp', prop: block.getFieldValue('PROP'), v: exprN(block, 'VAL', 10) };
        case 's_pen_set_eff': return { t: 'penSetProp', prop: block.getFieldValue('PROP'), v: exprN(block, 'VAL', 50) };
        case 's_pen_size': return { t: 'penSize', v: exprN(block, 'SIZE', 3) };
        case 's_pen_dsize': return { t: 'penDSize', v: exprN(block, 'AMT', 1) };
        // Lists
        case 's_list_add': return { t: 'listAdd', list: block.getFieldValue('LIST'), item: exprS(block, 'ITEM', '') };
        case 's_list_del': return { t: 'listDel', list: block.getFieldValue('LIST'), idx: exprN(block, 'IDX', 1) };
        case 's_list_del_all': return { t: 'listClear', list: block.getFieldValue('LIST') };
        case 's_list_insert': return { t: 'listInsert', list: block.getFieldValue('LIST'), idx: exprN(block, 'IDX', 1), item: exprS(block, 'ITEM', '') };
        case 's_list_replace': return { t: 'listReplace', list: block.getFieldValue('LIST'), idx: exprN(block, 'IDX', 1), item: exprS(block, 'ITEM', '') };
        // My Blocks
        case 's_my_block_call': return { t: 'myBlockCall', name: block.getFieldValue('NAME') };
        default: return null;
    }
}

/**
 * Compile ALL scripts from workspace, grouped by event hat type.
 * Returns { scripts: { flag, key, clicked, clone, receive }, myBlockDefs }
 */
export function compileAllScripts(workspace) {
    const tops = workspace.getTopBlocks(true);
    const scripts = { flag: [], key: [], clicked: [], clone: [], receive: [] };
    const myBlockDefs = {};
    for (const top of tops) {
        if (top.type === 's_my_block_def') {
            const name = top.getFieldValue('NAME');
            const next = top.getNextBlock();
            myBlockDefs[name] = next ? compileChain(next) : [];
            continue;
        }
        const next = top.getNextBlock();
        const body = next ? compileChain(next) : [];
        switch (top.type) {
            case 's_when_flag': scripts.flag.push(body); break;
            case 's_when_key': scripts.key.push({ key: top.getFieldValue('KEY'), body }); break;
            case 's_when_clicked': scripts.clicked.push(body); break;
            case 's_when_clone': scripts.clone.push(body); break;
            case 's_when_receive': {
                // MSG is now a FieldDropdown, not a connected block
                const msg = top.getFieldValue('MSG') || 'message1';
                scripts.receive.push({ msg, body });
                break;
            }
        }
    }
    return { scripts, myBlockDefs };
}

/** Legacy compat — flat compile for grading (kept for backward compat) */
export function compileWorkspace(workspace) {
    const { scripts } = compileAllScripts(workspace);
    return scripts.flag.flat();
}
export function compileForClone(workspace) { return compileWorkspace(workspace); }
