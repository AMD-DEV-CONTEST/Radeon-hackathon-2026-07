export { RECIPES } from './definitions';
export type {
  Recipe,
  RecipeStep,
  RecipeInput,
  RecipeExecution,
  RecipeStepResult,
  StepStatus,
} from './types';

import { RECIPES } from './definitions';
import type { Recipe } from './types';

/** Get a recipe by ID. */
export function getRecipe(id: string): Recipe | undefined {
  return RECIPES.find((r) => r.id === id);
}

/** Get all recipes, optionally filtered by category. */
export function getRecipes(category?: string): Recipe[] {
  if (!category || category === 'all') return RECIPES;
  return RECIPES.filter((r) => r.category === category);
}
