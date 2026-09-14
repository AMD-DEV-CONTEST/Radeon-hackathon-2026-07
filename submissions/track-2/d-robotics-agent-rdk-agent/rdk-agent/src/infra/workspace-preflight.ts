import { existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";

export interface WorkspaceProblem {
	root: string;
	missingPaths: readonly string[];
	suggestedRoot?: string;
}

function satisfies(root: string, requiredPaths: readonly string[]): boolean {
	return requiredPaths.every((path) => existsSync(join(root, path)));
}

export function inspectDevelopmentWorkspace(root: string, requiredPaths: readonly string[]): WorkspaceProblem | undefined {
	const absoluteRoot = resolve(root);
	const missingPaths = requiredPaths.filter((path) => !existsSync(join(absoluteRoot, path)));
	if (missingPaths.length === 0) return undefined;
	const candidates = [join(absoluteRoot, "rdk-sophon"), join(dirname(absoluteRoot), "rdk-sophon"), dirname(absoluteRoot)];
	const suggestedRoot = [...new Set(candidates.map((candidate) => resolve(candidate)))]
		.find((candidate) => candidate !== absoluteRoot && satisfies(candidate, requiredPaths));
	return { root: absoluteRoot, missingPaths, suggestedRoot };
}
