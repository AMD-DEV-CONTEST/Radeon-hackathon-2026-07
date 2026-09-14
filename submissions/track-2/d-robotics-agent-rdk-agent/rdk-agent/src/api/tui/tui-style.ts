import { styleText } from "node:util";
import type { StageStatus } from "../../domain/workflow.ts";
import { defaultLocale, localeText, type Locale } from "../../shared/locale.ts";

type StyleFormat = Parameters<typeof styleText>[0];

function renderStyle(format: StyleFormat, text: string, forceColor = false): string {
	return forceColor
		? styleText(format, text, { validateStream: false })
		: styleText(format, text);
}

export const tuiStyle = {
	title: (text: string): string => renderStyle("bold", text),
	accent: (text: string): string => renderStyle(["bold", "cyanBright"], text),
	running: (text: string): string => renderStyle(["bold", "cyanBright"], text),
	succeeded: (text: string): string => renderStyle(["bold", "greenBright"], text),
	failed: (text: string): string => renderStyle(["bold", "redBright"], text),
	warning: (text: string): string => renderStyle(["bold", "yellowBright"], text),
	pending: (text: string): string => renderStyle("gray", text),
};

export function stageMarker(status: StageStatus): string {
	if (status === "running") return tuiStyle.running("▶");
	if (status === "succeeded") return tuiStyle.succeeded("✓");
	if (status === "failed") return tuiStyle.failed("✗");
	return tuiStyle.pending("○");
}

export function agentStartBanner(
	agentName: string,
	startedAt: number,
	forceColor = false,
	locale: Locale = defaultLocale,
): string {
	const banner = locale === "en"
		? `▶▶ AGENT STARTED · ${agentName} · ${formatClock(startedAt, locale)}`
		: `▶▶ AGENT 开始 · ${agentName} · ${formatClock(startedAt, locale)}`;
	return renderStyle(["bold", "cyanBright"], banner, forceColor);
}

export function agentEndBanner(
	agentName: string,
	status: "succeeded" | "failed",
	finishedAt: number,
	startedAt?: number,
	forceColor = false,
	locale: Locale = defaultLocale,
): string {
	const elapsed = startedAt === undefined
		? ""
		: localeText(
			locale,
			` · 用时 ${formatDuration(finishedAt - startedAt, locale)}`,
			` · elapsed ${formatDuration(finishedAt - startedAt, locale)}`,
		);
	const marker = status === "succeeded" ? "✓✓" : "✗✗";
	const label = status === "succeeded"
		? localeText(locale, "完成", "COMPLETED")
		: localeText(locale, "失败", "FAILED");
	const banner = `${marker} AGENT ${label} · ${agentName} · ${formatClock(finishedAt, locale)}${elapsed}`;
	return renderStyle(["bold", status === "succeeded" ? "greenBright" : "redBright"], banner, forceColor);
}

/** Keeps lifecycle markers visually separate from both Agent output and adjacent tasks. */
export function agentLifecycleLogEntry(banner: string): string {
	return `\n\n${banner}\n\n`;
}

function formatClock(timestamp: number, locale: Locale): string {
	return new Date(timestamp).toLocaleTimeString(locale === "en" ? "en-GB" : "zh-CN", { hour12: false });
}

function formatDuration(milliseconds: number, locale: Locale): string {
	const seconds = Math.max(0, Math.round(milliseconds / 1_000));
	if (seconds < 60) return localeText(locale, `${seconds}秒`, `${seconds}s`);
	const minutes = Math.floor(seconds / 60);
	return localeText(locale, `${minutes}分${seconds % 60}秒`, `${minutes}m ${seconds % 60}s`);
}
