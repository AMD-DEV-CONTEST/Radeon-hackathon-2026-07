export type Locale = "zh-CN" | "en";

export const defaultLocale: Locale = "zh-CN";

/** Accept short CLI-friendly aliases while keeping one canonical runtime value. */
export function parseLocale(value?: string): Locale {
	if (value === undefined || value.trim() === "") return defaultLocale;
	const normalized = value.trim().toLowerCase();
	if (normalized === "zh" || normalized === "zh-cn" || normalized === "cn") return "zh-CN";
	if (normalized === "en" || normalized === "en-us" || normalized === "en-gb") return "en";
	throw new Error(`不支持的语言 / Unsupported language: ${value}. Supported values: zh-CN, en`);
}

export function localeText(locale: Locale, chinese: string, english: string): string {
	return locale === "en" ? english : chinese;
}

export function outputLanguageInstruction(locale: Locale): string {
	return locale === "en"
		? "All user-facing prose, including summaries, feedback, and questions, must be in English. Preserve commands, paths, identifiers, raw tool output, user-provided quotations, and required machine-readable result markers exactly."
		: "所有面向用户的说明、摘要、反馈和问题必须使用简洁中文。命令、路径、标识符、原始工具输出、用户原文引用和规定的机器可读结果标记保持原样。";
}
