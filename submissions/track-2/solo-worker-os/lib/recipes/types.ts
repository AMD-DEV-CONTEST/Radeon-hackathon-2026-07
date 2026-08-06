/**
 * Recipe system — standardized delivery packages.
 *
 * A Recipe chains multiple tool calls into a single executable workflow.
 * Instead of asking the user to trigger each step individually (create project →
 * generate contract → generate invoice → record payment), a recipe bundles the
 * entire sequence with pre-filled parameters derived from a single user input.
 *
 * This is the "delivery not tooling" strategy: sell the finished result, not the tool.
 */

/** A single step in a recipe, mapping to one tool call. */
export interface RecipeStep {
  /** Tool name to execute (must match a registered ToolConfig.name) */
  tool: string;
  /** Human-readable label for UI display */
  label: string;
  /**
   * Template for the tool input. Values can be:
   * - Literal strings/numbers
   * - `${variableName}` references to recipe-level inputs
   * - `${prev.xxx}` references to the previous step's result fields
   */
  inputTemplate: Record<string, unknown>;
  /** Skip this step if the condition evaluates to false (uses same template syntax) */
  skipIf?: string;
}

/** A recipe-level input parameter that the user must provide. */
export interface RecipeInput {
  name: string;
  label: string;
  type: 'string' | 'number' | 'date' | 'select';
  required: boolean;
  placeholder?: string;
  options?: string[]; // for select type
  default?: unknown;
}

/** A complete recipe definition. */
export interface Recipe {
  id: string;
  /** Display name (short, action-oriented) */
  name: string;
  /** One-line description of what this recipe delivers */
  description: string;
  /** Icon identifier (maps to SVG in UI) */
  icon: string;
  /** Category for grouping in UI */
  category: 'sales' | 'delivery' | 'finance' | 'management';
  /** Input parameters the user provides once */
  inputs: RecipeInput[];
  /** Ordered steps to execute */
  steps: RecipeStep[];
  /** What this recipe produces (for the "delivery" framing) */
  deliverables: string[];
  /** Estimated time saved vs manual execution (minutes) */
  estimatedTimeSaved: number;
}

/** Runtime execution state of a recipe step. */
export type StepStatus = 'pending' | 'running' | 'done' | 'skipped' | 'error';

export interface RecipeStepResult {
  stepIndex: number;
  tool: string;
  status: StepStatus;
  result?: { toolResult: string; clientSummary: string; displayText?: string };
  error?: string;
  startedAt?: number;
  completedAt?: number;
}

export interface RecipeExecution {
  id: string;
  recipeId: string;
  inputs: Record<string, unknown>;
  steps: RecipeStepResult[];
  currentStep: number;
  status: 'running' | 'completed' | 'failed';
  startedAt: number;
  completedAt?: number;
}
