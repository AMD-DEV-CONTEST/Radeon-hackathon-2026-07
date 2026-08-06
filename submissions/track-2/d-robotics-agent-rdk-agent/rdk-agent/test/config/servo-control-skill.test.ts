import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";

const skillDirectory = join(import.meta.dirname, "../../config/skills/servo-control");
const skill = readFileSync(join(skillDirectory, "SKILL.md"), "utf8");
const acceptance = readFileSync(join(skillDirectory, "acceptance.md"), "utf8");
const templateSkill = readFileSync(
	join(import.meta.dirname, "../../config/templates/magicbox-servo/skills/servo-control/SKILL.md"),
	"utf8",
);

test("servo Skill exposes only supported motion commands", () => {
	assert.equal(templateSkill, skill);
	assert.match(skill, /^---\nname: servo-control\n/);
	assert.match(skill, /^- `shake-ears`$/m);
	assert.match(skill, /`sophonctl servo shake-ears`/);
	assert.doesNotMatch(skill, /wave-hands|wave-left-hand|wave-right-hand/);
});

test("servo Skill acceptance separates static checks from physical confirmation", () => {
	assert.match(acceptance, /test_plugin_manifest_valid/);
	assert.match(acceptance, /test_start_left_does_not_touch_right_pwm/);
	assert.match(acceptance, /实际物理效果仍需最终真机阶段由人类目视确认/);
	assert.doesNotMatch(acceptance, /wave-hands|wave-left-hand|\[x\]|Verification Status/);
});

test("servo Skill executes imperative application requests without a second confirmation", () => {
	assert.match(skill, /动作式自然语言就是对映射动作的一次执行授权/);
	assert.match(skill, /直接执行唯一映射命令一次/);
	assert.match(skill, /不得停在列表或帮助检查/);
	assert.match(acceptance, /动作式输入不需要二次确认/);
});
