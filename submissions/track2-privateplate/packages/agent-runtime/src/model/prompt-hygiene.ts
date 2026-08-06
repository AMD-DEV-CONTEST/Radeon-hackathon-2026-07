/**
 * Prompt hygiene: keep system prompt + tool descriptions free of fixture
 * food/template ids and eval-seed user utterance strings.
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { PRIVATEPLATE_SYSTEM_PROMPT } from "./provider.js";
import { PRIVATEPLATE_MODEL_TOOLS } from "./tool-definitions.js";
import { PRIVATEPLATE_CONTROL_TOOLS } from "./control-decisions.js";

const HERE = fileURLToPath(new URL(".", import.meta.url));
const REPO_ROOT = join(HERE, "../../../..");
const FIXTURES_ROOT = join(REPO_ROOT, "fixtures");

export type PromptHygieneFinding = {
  source: string;
  banned: string;
  kind: "food_id" | "template_id" | "eval_utterance";
};

function walkJsonFiles(dir: string): string[] {
  const out: string[] = [];
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    const st = statSync(full);
    if (st.isDirectory()) out.push(...walkJsonFiles(full));
    else if (name.endsWith(".json")) out.push(full);
  }
  return out;
}

function collectIdsFromFixtures(): {
  foodIds: Set<string>;
  templateIds: Set<string>;
} {
  const foodIds = new Set<string>();
  const templateIds = new Set<string>();
  for (const file of walkJsonFiles(FIXTURES_ROOT)) {
    let raw: string;
    try {
      raw = readFileSync(file, "utf8");
    } catch {
      continue;
    }
    let data: unknown;
    try {
      data = JSON.parse(raw);
    } catch {
      continue;
    }
    visit(data, (key, value) => {
      if (typeof value !== "string") return;
      if (
        (key === "id" || key === "foodId") &&
        /^food-[a-z0-9-]+$/i.test(value)
      ) {
        foodIds.add(value);
      }
      if (
        (key === "id" || key === "templateId") &&
        /^tpl-[a-z0-9-]+$/i.test(value)
      ) {
        templateIds.add(value);
      }
    });
  }
  return { foodIds, templateIds };
}

function visit(
  node: unknown,
  onEntry: (key: string, value: unknown) => void
): void {
  if (Array.isArray(node)) {
    for (const item of node) visit(item, onEntry);
    return;
  }
  if (!node || typeof node !== "object") return;
  for (const [key, value] of Object.entries(node as Record<string, unknown>)) {
    onEntry(key, value);
    visit(value, onEntry);
  }
}

function collectEvalUtterances(): Set<string> {
  const utterances = new Set<string>();
  const evalRoots = [
    join(FIXTURES_ROOT, "evals"),
    join(FIXTURES_ROOT, "scenarios")
  ];
  for (const root of evalRoots) {
    let files: string[] = [];
    try {
      files = walkJsonFiles(root);
    } catch {
      continue;
    }
    for (const file of files) {
      let data: unknown;
      try {
        data = JSON.parse(readFileSync(file, "utf8"));
      } catch {
        continue;
      }
      visit(data, (key, value) => {
        if (
          (key === "text" || key === "userText" || key === "utterance") &&
          typeof value === "string"
        ) {
          const trimmed = value.trim();
          // Only ban substantial seed utterances to avoid flagging generic words.
          if (trimmed.length >= 8) utterances.add(trimmed);
        }
      });
    }
  }
  return utterances;
}

function collectPromptSurfaces(): Array<{ source: string; text: string }> {
  const surfaces: Array<{ source: string; text: string }> = [
    { source: "system_prompt", text: PRIVATEPLATE_SYSTEM_PROMPT }
  ];
  for (const tool of PRIVATEPLATE_MODEL_TOOLS) {
    surfaces.push({
      source: `tool:${tool.function.name}.description`,
      text: tool.function.description
    });
    const props = tool.function.parameters?.properties ?? {};
    for (const [field, schema] of Object.entries(props)) {
      const description =
        schema && typeof schema === "object" && "description" in schema
          ? String((schema as { description?: unknown }).description ?? "")
          : "";
      if (description) {
        surfaces.push({
          source: `tool:${tool.function.name}.${field}.description`,
          text: description
        });
      }
    }
  }
  for (const tool of PRIVATEPLATE_CONTROL_TOOLS) {
    surfaces.push({
      source: `control:${tool.function.name}.description`,
      text: tool.function.description
    });
  }
  return surfaces;
}

function containsToken(haystack: string, needle: string): boolean {
  if (!needle) return false;
  if (/^[a-z0-9_-]+$/i.test(needle)) {
    const re = new RegExp(
      `(^|[^A-Za-z0-9_-])${needle.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}([^A-Za-z0-9_-]|$)`
    );
    return re.test(haystack);
  }
  return haystack.includes(needle);
}

export function scanPromptHygiene(): PromptHygieneFinding[] {
  const { foodIds, templateIds } = collectIdsFromFixtures();
  const utterances = collectEvalUtterances();
  const findings: PromptHygieneFinding[] = [];
  for (const surface of collectPromptSurfaces()) {
    for (const id of foodIds) {
      if (containsToken(surface.text, id)) {
        findings.push({ source: surface.source, banned: id, kind: "food_id" });
      }
    }
    for (const id of templateIds) {
      if (containsToken(surface.text, id)) {
        findings.push({
          source: surface.source,
          banned: id,
          kind: "template_id"
        });
      }
    }
    for (const utterance of utterances) {
      if (surface.text.includes(utterance)) {
        findings.push({
          source: surface.source,
          banned: utterance,
          kind: "eval_utterance"
        });
      }
    }
  }
  return findings;
}

export function formatPromptHygieneReport(
  findings: PromptHygieneFinding[]
): string {
  if (findings.length === 0) return "prompt hygiene: clean";
  const lines = findings.map(
    (f) => `- [${f.kind}] ${f.source}: ${JSON.stringify(f.banned)}`
  );
  return `prompt hygiene violations (${findings.length}):\n${lines.join("\n")}\nfixtures root: ${relative(REPO_ROOT, FIXTURES_ROOT)}`;
}
