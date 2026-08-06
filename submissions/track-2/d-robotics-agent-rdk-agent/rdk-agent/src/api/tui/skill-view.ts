import type { AgentProfile } from "../../domain/agent-profile.ts";
import type { AgentSkillInfo } from "../../shared/agent-runner.ts";
import { defaultLocale, localeText, type Locale } from "../../shared/locale.ts";

export function profileSkillStatus(
	profile: AgentProfile,
	loadedSkills?: readonly AgentSkillInfo[],
	selectedSkills?: readonly AgentSkillInfo[],
	locale: Locale = defaultLocale,
): string | undefined {
	if (profile.skills.length === 0) return undefined;
	const loaded = loadedSkills?.map((skill) => skill.name).join(", ")
		?? localeText(locale, "尚未创建会话", "session not created");
	const selected = selectedSkills?.map((skill) => skill.name).join(", ")
		|| localeText(locale, "尚未选择", "not selected");
	return locale === "en"
		? `Skills: configured ${profile.skills.join(", ")} · loaded ${loaded} · selected ${selected}`
		: `Skills：配置 ${profile.skills.join(", ")} · 已加载 ${loaded} · 本次选择 ${selected}`;
}

export function skillReport(
	profiles: readonly AgentProfile[],
	loadedByAgent: ReadonlyMap<string, readonly AgentSkillInfo[]>,
	selectedByAgent: ReadonlyMap<string, readonly AgentSkillInfo[]>,
	locale: Locale = defaultLocale,
): string {
	return profiles.map((profile) => {
		const configured = profile.skills.join(", ") || localeText(locale, "无", "None");
		const loaded = loadedByAgent.get(profile.id)?.map((skill) => `${skill.name} (${skill.filePath})`).join(", ")
			?? localeText(locale, "尚未创建会话", "session not created");
		const selected = selectedByAgent.get(profile.id)?.map((skill) => skill.name).join(", ")
			|| localeText(locale, "尚未选择", "not selected");
		return locale === "en"
			? `[${profile.name}]\nConfigured: ${configured}\nLoaded: ${loaded}\nSelected: ${selected}`
			: `[${profile.name}]\n配置：${configured}\n实际加载：${loaded}\n本次选择：${selected}`;
	}).join("\n\n");
}
