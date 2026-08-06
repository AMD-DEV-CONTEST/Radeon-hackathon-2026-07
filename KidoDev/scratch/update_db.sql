-- Update curriculum intelligence
INSERT INTO tutor_solutions (lesson_id, xml, message, tip)
VALUES ('L1P1', '<xml xmlns=''https://developers.google.com/blockly/xml''><block type=''s_when_flag'' id=''1''><next><block type=''s_move''><value name=''STEPS''><shadow type=''math_number''><field name=''NUM''>10</field></shadow></value></block></next></block></xml>', 'Yay, you made the cat walk! ≡ƒÄë', 'Use the s_move block to make the cat walk a certain number of steps')
ON CONFLICT (lesson_id) DO UPDATE SET xml = EXCLUDED.xml, message = EXCLUDED.message, tip = EXCLUDED.tip;

UPDATE lessons SET steps = '[{"message":"≡ƒÉê Make the cat walk 10 steps when flag clicked ≡ƒÜÇ","check_xml_contains":"s_move"}]' WHERE id = 'L1P1';

DELETE FROM tutorial_steps WHERE lesson_id = 'L1P1';
INSERT INTO tutorial_steps (lesson_id, step_index, message, check_xml_contains)
VALUES ('L1P1', 0, '≡ƒÉê Make the cat walk 10 steps when flag clicked ≡ƒÜÇ', 's_move');

INSERT INTO tutor_solutions (lesson_id, xml, message, tip)
VALUES ('L1P2', '<xml xmlns=''https://developers.google.com/blockly/xml''><block type=''s_move'' id=''move'' x=''10'' y=''20''><value name=''STEPS''><shadow type=''math_number''><field name=''NUM''>10</field></shadow></value><next><block type=''s_say_timed'' id=''say''><value name=''MSG''><shadow type=''text''><field name=''TEXT''>Hello Kido!</field></shadow></value><value name=''SECS''><shadow type=''math_number''><field name=''NUM''>2</field></shadow></value></block></next></block></xml>', 'Yay! You made it talk! ≡ƒÄë', 'Use the ''s_move'' block to move the sprite and the ''s_say_timed'' block to make it talk')
ON CONFLICT (lesson_id) DO UPDATE SET xml = EXCLUDED.xml, message = EXCLUDED.message, tip = EXCLUDED.tip;

UPDATE lessons SET steps = '[{"message":"≡ƒÜ╢ Move the sprite 10 steps forward ≡ƒÜ╢","check_xml_contains":"s_move"},{"message":"≡ƒÆ¼ Make the sprite say ''Hello Kido!'' for 2 seconds ≡ƒÆ¼","check_xml_contains":"s_say_timed"}]' WHERE id = 'L1P2';

DELETE FROM tutorial_steps WHERE lesson_id = 'L1P2';
INSERT INTO tutorial_steps (lesson_id, step_index, message, check_xml_contains)
VALUES ('L1P2', 0, '≡ƒÜ╢ Move the sprite 10 steps forward ≡ƒÜ╢', 's_move');
INSERT INTO tutorial_steps (lesson_id, step_index, message, check_xml_contains)
VALUES ('L1P2', 1, '≡ƒÆ¼ Make the sprite say ''Hello Kido!'' for 2 seconds ≡ƒÆ¼', 's_say_timed');

INSERT INTO tutor_solutions (lesson_id, xml, message, tip)
VALUES ('L1P3', '<xml xmlns="https://developers.google.com/blockly/xml"><block type="s_when_flag"><next><block type="s_move"><value name="STEPS"><shadow type="math_number"><field name="NUM">10</field></shadow></value></block><next><block type="s_play_sound"><value name="SOUND"><shadow type="text"><field name="TEXT">meow</field></shadow></value></block><next><block type="s_say"><value name="MSG"><shadow type="text"><field name="TEXT">I am walking!</field></shadow></value></block></next></next></next></block></xml>', 'Yay, you did it! ≡ƒÄë', 'Remember to use the ''s_when_flag'' block to start your program')
ON CONFLICT (lesson_id) DO UPDATE SET xml = EXCLUDED.xml, message = EXCLUDED.message, tip = EXCLUDED.tip;

UPDATE lessons SET steps = '[{"message":"≡ƒîƒ Click on the flag to start the sound walk","check_xml_contains":"s_when_flag"},{"message":"≡ƒÜ╢ΓÇìΓÖÇ∩╕Å Move the sprite 10 steps","check_xml_contains":"s_move"},{"message":"≡ƒÉ▒ Play the meow sound","check_xml_contains":"s_play_sound"},{"message":"≡ƒÆ¼ Say ''I am walking!''","check_xml_contains":"s_say"}]' WHERE id = 'L1P3';

DELETE FROM tutorial_steps WHERE lesson_id = 'L1P3';
INSERT INTO tutorial_steps (lesson_id, step_index, message, check_xml_contains)
VALUES ('L1P3', 0, '≡ƒîƒ Click on the flag to start the sound walk', 's_when_flag');
INSERT INTO tutorial_steps (lesson_id, step_index, message, check_xml_contains)
VALUES ('L1P3', 1, '≡ƒÜ╢ΓÇìΓÖÇ∩╕Å Move the sprite 10 steps', 's_move');
INSERT INTO tutorial_steps (lesson_id, step_index, message, check_xml_contains)
VALUES ('L1P3', 2, '≡ƒÉ▒ Play the meow sound', 's_play_sound');
INSERT INTO tutorial_steps (lesson_id, step_index, message, check_xml_contains)
VALUES ('L1P3', 3, '≡ƒÆ¼ Say ''I am walking!''', 's_say');

INSERT INTO tutor_solutions (lesson_id, xml, message, tip)
VALUES ('L1P4', '<xml xmlns=''https://developers.google.com/blockly/xml''><block type=''s_when_flag''><next><block type=''s_repeat''><value name=''N''><shadow type=''math_number''><field name=''NUM''>10</field></shadow></value><next><block type=''s_next_costume''/><next><block type=''s_wait''><value name=''SECS''><shadow type=''math_number''><field name=''NUM''>0.5</field></shadow></value></block><next><block type=''s_play_sound''><value name=''SOUND''><shadow type=''text''><field name=''TEXT''>dance</field></shadow></value></block></next></next></next></block></next></block></xml>', 'You did it! The dancer is ready to perform ≡ƒÄë', 'Try changing the repeat value or the wait time to create different dance effects')
ON CONFLICT (lesson_id) DO UPDATE SET xml = EXCLUDED.xml, message = EXCLUDED.message, tip = EXCLUDED.tip;

UPDATE lessons SET steps = '[{"message":"≡ƒîƒ Click on the ''Events'' category and drag the ''when flag clicked'' block to the workspace","check_xml_contains":"s_when_flag"},{"message":"≡ƒöü Click on the ''Control'' category, drag the ''repeat'' block, and attach it to the ''when flag clicked'' block","check_xml_contains":"s_repeat"},{"message":"≡ƒô¥ Set the repeat value to 10 by clicking on the math number field and typing 10","check_xml_contains":"10"},{"message":"≡ƒæù Click on the ''Looks'' category, drag the ''next costume'' block, and attach it to the repeat block","check_xml_contains":"s_next_costume"},{"message":"ΓÅ▒∩╕Å Click on the ''Control'' category, drag the ''wait'' block, and attach it to the ''next costume'' block","check_xml_contains":"s_wait"},{"message":"ΓÅ▒∩╕Å Set the wait value to 0.5 by clicking on the math number field and typing 0.5","check_xml_contains":"0.5"},{"message":"≡ƒÄ╡ Click on the ''Sound'' category, drag the ''play sound'' block, and attach it to the ''wait'' block","check_xml_contains":"s_play_sound"},{"message":"≡ƒÄ╡ Set the sound to ''dance'' by clicking on the text field and typing dance","check_xml_contains":"dance"}]' WHERE id = 'L1P4';

DELETE FROM tutorial_steps WHERE lesson_id = 'L1P4';
INSERT INTO tutorial_steps (lesson_id, step_index, message, check_xml_contains)
VALUES ('L1P4', 0, '≡ƒîƒ Click on the ''Events'' category and drag the ''when flag clicked'' block to the workspace', 's_when_flag');
INSERT INTO tutorial_steps (lesson_id, step_index, message, check_xml_contains)
VALUES ('L1P4', 1, '≡ƒöü Click on the ''Control'' category, drag the ''repeat'' block, and attach it to the ''when flag clicked'' block', 's_repeat');
INSERT INTO tutorial_steps (lesson_id, step_index, message, check_xml_contains)
VALUES ('L1P4', 2, '≡ƒô¥ Set the repeat value to 10 by clicking on the math number field and typing 10', '10');
INSERT INTO tutorial_steps (lesson_id, step_index, message, check_xml_contains)
VALUES ('L1P4', 3, '≡ƒæù Click on the ''Looks'' category, drag the ''next costume'' block, and attach it to the repeat block', 's_next_costume');
INSERT INTO tutorial_steps (lesson_id, step_index, message, check_xml_contains)
VALUES ('L1P4', 4, 'ΓÅ▒∩╕Å Click on the ''Control'' category, drag the ''wait'' block, and attach it to the ''next costume'' block', 's_wait');
INSERT INTO tutorial_steps (lesson_id, step_index, message, check_xml_contains)
VALUES ('L1P4', 5, 'ΓÅ▒∩╕Å Set the wait value to 0.5 by clicking on the math number field and typing 0.5', '0.5');
INSERT INTO tutorial_steps (lesson_id, step_index, message, check_xml_contains)
VALUES ('L1P4', 6, '≡ƒÄ╡ Click on the ''Sound'' category, drag the ''play sound'' block, and attach it to the ''wait'' block', 's_play_sound');
INSERT INTO tutorial_steps (lesson_id, step_index, message, check_xml_contains)
VALUES ('L1P4', 7, '≡ƒÄ╡ Set the sound to ''dance'' by clicking on the text field and typing dance', 'dance');

INSERT INTO tutor_solutions (lesson_id, xml, message, tip)
VALUES ('L1P5', '<xml xmlns=''https://developers.google.com/blockly/xml''><block type=''s_when_flag'' id=''1''><next><block type=''s_move'' id=''2''><value name=''STEPS''><shadow type=''math_number''><field name=''NUM''>50</field></shadow></value></block></next><next><block type=''s_wait'' id=''3''><value name=''SECS''><shadow type=''math_number''><field name=''NUM''>1</field></shadow></value></block></next><next><block type=''s_next_backdrop'' id=''4''></block></next></block></xml>', 'Yay! You successfully changed the scene ≡ƒÄë', 'Try adding more backdrops and sprites to create a story ≡ƒôÜ')
ON CONFLICT (lesson_id) DO UPDATE SET xml = EXCLUDED.xml, message = EXCLUDED.message, tip = EXCLUDED.tip;

UPDATE lessons SET steps = '[{"message":"≡ƒîƒ Click on the flag to start the scene change","check_xml_contains":"s_when_flag"},{"message":"≡ƒÜ╢ΓÇìΓÖé∩╕Å Move the sprite 50 steps forward","check_xml_contains":"s_move"},{"message":"ΓÅ▒∩╕Å Wait for 1 second","check_xml_contains":"s_wait"},{"message":"≡ƒîä Switch to the next backdrop","check_xml_contains":"s_next_backdrop"}]' WHERE id = 'L1P5';

DELETE FROM tutorial_steps WHERE lesson_id = 'L1P5';
INSERT INTO tutorial_steps (lesson_id, step_index, message, check_xml_contains)
VALUES ('L1P5', 0, '≡ƒîƒ Click on the flag to start the scene change', 's_when_flag');
INSERT INTO tutorial_steps (lesson_id, step_index, message, check_xml_contains)
VALUES ('L1P5', 1, '≡ƒÜ╢ΓÇìΓÖé∩╕Å Move the sprite 50 steps forward', 's_move');
INSERT INTO tutorial_steps (lesson_id, step_index, message, check_xml_contains)
VALUES ('L1P5', 2, 'ΓÅ▒∩╕Å Wait for 1 second', 's_wait');
INSERT INTO tutorial_steps (lesson_id, step_index, message, check_xml_contains)
VALUES ('L1P5', 3, '≡ƒîä Switch to the next backdrop', 's_next_backdrop');

INSERT INTO tutor_solutions (lesson_id, xml, message, tip)
VALUES ('L1P6', '<xml xmlns=''https://developers.google.com/blockly/xml''><block type=''s_when_flag''><next><block type=''s_show''></block><next><block type=''s_wait''><value name=''SECS''><shadow type=''math_number''><field name=''NUM''>2</field></shadow></value></block><next><block type=''s_hide''></block></next></next></next></block></xml>', 'Great job! You made the sprite appear and disappear ≡ƒÄë', 'Use the flag click event to trigger the sequence of actions')
ON CONFLICT (lesson_id) DO UPDATE SET xml = EXCLUDED.xml, message = EXCLUDED.message, tip = EXCLUDED.tip;

UPDATE lessons SET steps = '[{"message":"≡ƒîƒ Click on the flag to start the project","check_xml_contains":"s_when_flag"},{"message":"≡ƒæÇ Show the sprite","check_xml_contains":"s_show"},{"message":"ΓÅ▒∩╕Å Wait for 2 seconds","check_xml_contains":"s_wait"},{"message":"≡ƒö« Hide the sprite","check_xml_contains":"s_hide"}]' WHERE id = 'L1P6';

DELETE FROM tutorial_steps WHERE lesson_id = 'L1P6';
INSERT INTO tutorial_steps (lesson_id, step_index, message, check_xml_contains)
VALUES ('L1P6', 0, '≡ƒîƒ Click on the flag to start the project', 's_when_flag');
INSERT INTO tutorial_steps (lesson_id, step_index, message, check_xml_contains)
VALUES ('L1P6', 1, '≡ƒæÇ Show the sprite', 's_show');
INSERT INTO tutorial_steps (lesson_id, step_index, message, check_xml_contains)
VALUES ('L1P6', 2, 'ΓÅ▒∩╕Å Wait for 2 seconds', 's_wait');
INSERT INTO tutorial_steps (lesson_id, step_index, message, check_xml_contains)
VALUES ('L1P6', 3, '≡ƒö« Hide the sprite', 's_hide');

INSERT INTO tutor_solutions (lesson_id, xml, message, tip)
VALUES ('L1P7', '<xml xmlns=''https://developers.google.com/blockly/xml''><block type=''s_when_clicked''><next><block type=''s_change_effect''><title name=''EFFECT''>color</title><value name=''VALUE''><shadow type=''math_number''><field name=''NUM''>25</field></shadow></value></block><next><block type=''s_play_sound''><title name=''SOUND''>pop</title></block></next></next></block></xml>', 'You did it! ≡ƒÄë The sprite now changes color and plays a sound when clicked', 'Try changing the sound or effect to create different magic touch effects')
ON CONFLICT (lesson_id) DO UPDATE SET xml = EXCLUDED.xml, message = EXCLUDED.message, tip = EXCLUDED.tip;

UPDATE lessons SET steps = '[{"message":"≡ƒû▒∩╕Å Click on the sprite to trigger the magic touch","check_xml_contains":"s_when_clicked"},{"message":"≡ƒÆ½ Change the color effect by 25","check_xml_contains":"s_change_effect"},{"message":"≡ƒÄ╡ Play the ''pop'' sound","check_xml_contains":"s_play_sound"}]' WHERE id = 'L1P7';

DELETE FROM tutorial_steps WHERE lesson_id = 'L1P7';
INSERT INTO tutorial_steps (lesson_id, step_index, message, check_xml_contains)
VALUES ('L1P7', 0, '≡ƒû▒∩╕Å Click on the sprite to trigger the magic touch', 's_when_clicked');
INSERT INTO tutorial_steps (lesson_id, step_index, message, check_xml_contains)
VALUES ('L1P7', 1, '≡ƒÆ½ Change the color effect by 25', 's_change_effect');
INSERT INTO tutorial_steps (lesson_id, step_index, message, check_xml_contains)
VALUES ('L1P7', 2, '≡ƒÄ╡ Play the ''pop'' sound', 's_play_sound');

INSERT INTO tutor_solutions (lesson_id, xml, message, tip)
VALUES ('L1P8', '<xml xmlns=''https://developers.google.com/blockly/xml''><block type=''s_when_key'' id=''1''><field name=''KEY''>up</field><statement name=''STACK''><block type=''s_change_y''><value name=''Y''><shadow type=''math_number''><field name=''NUM''>10</field></shadow></value></block></statement></block><block type=''s_when_key'' id=''2''><field name=''KEY''>down</field><statement name=''STACK''><block type=''s_change_y''><value name=''Y''><shadow type=''math_number''><field name=''NUM''>-10</field></shadow></value></block></statement></block><block type=''s_when_key'' id=''3''><field name=''KEY''>left</field><statement name=''STACK''><block type=''s_change_x''><value name=''X''><shadow type=''math_number''><field name=''NUM''>-10</field></shadow></value></block></statement></block><block type=''s_when_key'' id=''4''><field name=''KEY''>right</field><statement name=''STACK''><block type=''s_change_x''><value name=''X''><shadow type=''math_number''><field name=''NUM''>10</field></shadow></value></block></statement></block></xml>', 'Great job! You''re now controlling your sprite with the keyboard!', 'Remember to use the correct arrow keys to move your sprite in the desired direction.')
ON CONFLICT (lesson_id) DO UPDATE SET xml = EXCLUDED.xml, message = EXCLUDED.message, tip = EXCLUDED.tip;

UPDATE lessons SET steps = '[{"message":"≡ƒö¥ Step 1: Move up with up arrow key","check_xml_contains":"s_when_key"},{"message":"Γ¼ç∩╕Å Step 2: Move down with down arrow key","check_xml_contains":"s_when_key"},{"message":"Γ¼à∩╕Å Step 3: Move left with left arrow key","check_xml_contains":"s_when_key"},{"message":"Γ₧í∩╕Å Step 4: Move right with right arrow key","check_xml_contains":"s_when_key"}]' WHERE id = 'L1P8';

DELETE FROM tutorial_steps WHERE lesson_id = 'L1P8';
INSERT INTO tutorial_steps (lesson_id, step_index, message, check_xml_contains)
VALUES ('L1P8', 0, '≡ƒö¥ Step 1: Move up with up arrow key', 's_when_key');
INSERT INTO tutorial_steps (lesson_id, step_index, message, check_xml_contains)
VALUES ('L1P8', 1, 'Γ¼ç∩╕Å Step 2: Move down with down arrow key', 's_when_key');
INSERT INTO tutorial_steps (lesson_id, step_index, message, check_xml_contains)
VALUES ('L1P8', 2, 'Γ¼à∩╕Å Step 3: Move left with left arrow key', 's_when_key');
INSERT INTO tutorial_steps (lesson_id, step_index, message, check_xml_contains)
VALUES ('L1P8', 3, 'Γ₧í∩╕Å Step 4: Move right with right arrow key', 's_when_key');

INSERT INTO tutor_solutions (lesson_id, xml, message, tip)
VALUES ('L1P9', '<xml xmlns=''https://developers.google.com/blockly/xml''><block type=''s_when_flag'' id=''1''><next><block type=''s_glide_xy'' id=''2''><value name=''SECS''><shadow type=''math_number''><field name=''NUM''>2</field></shadow></value><value name=''X''><shadow type=''math_number''><field name=''NUM''>200</field></shadow></value><value name=''Y''><shadow type=''math_number''><field name=''NUM''>0</field></shadow></value></block></next></block></xml>', 'Great job! You made the sprite glide and slide', 'Use the s_glide_xy block to move the sprite smoothly')
ON CONFLICT (lesson_id) DO UPDATE SET xml = EXCLUDED.xml, message = EXCLUDED.message, tip = EXCLUDED.tip;

UPDATE lessons SET steps = '[{"message":"≡ƒîƒ Click on the flag to start the animation","check_xml_contains":"s_when_flag"},{"message":"≡ƒÜÇ Sprite glides to the target position","check_xml_contains":"s_glide_xy"}]' WHERE id = 'L1P9';

DELETE FROM tutorial_steps WHERE lesson_id = 'L1P9';
INSERT INTO tutorial_steps (lesson_id, step_index, message, check_xml_contains)
VALUES ('L1P9', 0, '≡ƒîƒ Click on the flag to start the animation', 's_when_flag');
INSERT INTO tutorial_steps (lesson_id, step_index, message, check_xml_contains)
VALUES ('L1P9', 1, '≡ƒÜÇ Sprite glides to the target position', 's_glide_xy');

INSERT INTO tutor_solutions (lesson_id, xml, message, tip)
VALUES ('L1P10', '<xml xmlns=''https://developers.google.com/blockly/xml''><block type=''s_when_flag'' id=''1''><next><block type=''s_repeat'' id=''2''><value name=''N''><shadow type=''math_number''><field name=''NUM''>4</field></shadow></value><next><block type=''s_move'' id=''3''><value name=''STEPS''><shadow type=''math_number''><field name=''NUM''>100</field></shadow></value><next><block type=''s_turn_r'' id=''4''><value name=''DEG''><shadow type=''math_number''><field name=''NUM''>90</field></shadow></value></next></block></next></block></next></block><block type=''s_say'' id=''5'' x=''100'' y=''100''><value name=''MSG''><shadow type=''text''><field name=''TEXT''>Level 1 Complete!</field></shadow></value></block></xml>', 'Congratulations, you''ve completed The Grand Finale! ≡ƒÄë', 'Remember to use the ''repeat'' block to simplify your code and make it more efficient ≡ƒñö')
ON CONFLICT (lesson_id) DO UPDATE SET xml = EXCLUDED.xml, message = EXCLUDED.message, tip = EXCLUDED.tip;

UPDATE lessons SET steps = '[{"message":"≡ƒÄë Start by adding a ''when flag clicked'' block to begin the program","check_xml_contains":"s_when_flag"},{"message":"≡ƒöä Add a ''repeat'' block and set it to 4 times","check_xml_contains":"s_repeat"},{"message":"≡ƒÜ╢ΓÇìΓÖé∩╕Å Inside the repeat block, add a ''move'' block and set it to 100 steps","check_xml_contains":"s_move"},{"message":"≡ƒöä Add a ''turn right'' block and set it to 90 degrees","check_xml_contains":"s_turn_r"},{"message":"≡ƒôó Finally, add a ''say'' block and type ''Level 1 Complete!''","check_xml_contains":"s_say"}]' WHERE id = 'L1P10';

DELETE FROM tutorial_steps WHERE lesson_id = 'L1P10';
INSERT INTO tutorial_steps (lesson_id, step_index, message, check_xml_contains)
VALUES ('L1P10', 0, '≡ƒÄë Start by adding a ''when flag clicked'' block to begin the program', 's_when_flag');
INSERT INTO tutorial_steps (lesson_id, step_index, message, check_xml_contains)
VALUES ('L1P10', 1, '≡ƒöä Add a ''repeat'' block and set it to 4 times', 's_repeat');
INSERT INTO tutorial_steps (lesson_id, step_index, message, check_xml_contains)
VALUES ('L1P10', 2, '≡ƒÜ╢ΓÇìΓÖé∩╕Å Inside the repeat block, add a ''move'' block and set it to 100 steps', 's_move');
INSERT INTO tutorial_steps (lesson_id, step_index, message, check_xml_contains)
VALUES ('L1P10', 3, '≡ƒöä Add a ''turn right'' block and set it to 90 degrees', 's_turn_r');
INSERT INTO tutorial_steps (lesson_id, step_index, message, check_xml_contains)
VALUES ('L1P10', 4, '≡ƒôó Finally, add a ''say'' block and type ''Level 1 Complete!''', 's_say');

