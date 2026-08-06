import { matchesKey } from "@earendil-works/pi-tui";
import type { OrchestrationMode } from "../../domain/orchestration-mode.ts";

export type ModeSwitchDirection = -1 | 0 | 1;

export function modeSwitchDirection(data: string): ModeSwitchDirection {
	if (matchesKey(data, "shift+tab")) return 1;
	return 0;
}

export function adjacentModeId(
	modes: readonly OrchestrationMode[],
	selectedModeId: string,
	direction: Exclude<ModeSwitchDirection, 0>,
): string {
	if (modes.length === 0) throw new Error("至少需要一个模式才能切换");
	const currentIndex = modes.findIndex((mode) => mode.id === selectedModeId);
	if (currentIndex < 0) throw new Error(`当前模式不存在：${selectedModeId}`);
	const nextIndex = (currentIndex + direction + modes.length) % modes.length;
	return modes[nextIndex]!.id;
}
