import { NextResponse } from 'next/server';
import { getRecipes, getRecipe } from '@/lib/recipes';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/**
 * GET /api/recipes
 * Returns all recipes, optionally filtered by ?category=
 */
export async function GET(req: Request) {
  const { searchParams } = new URL(req.url);
  const category = searchParams.get('category') ?? undefined;

  if (searchParams.get('id')) {
    const recipe = getRecipe(searchParams.get('id')!);
    if (!recipe) {
      return NextResponse.json({ error: 'Recipe not found' }, { status: 404 });
    }
    return NextResponse.json({ recipe });
  }

  const recipes = getRecipes(category);
  return NextResponse.json({ recipes, count: recipes.length });
}
