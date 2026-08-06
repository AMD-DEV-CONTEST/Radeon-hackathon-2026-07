import type { SupabaseClient } from '@supabase/supabase-js';
import type { Project } from '@/lib/types';

/**
 * Resolve a project by project_id (UUID) or by client_name + optional project_type.
 *
 * Lookup order:
 * 1. By project_id (exact UUID match)
 * 2. By client_name (exact match)
 * 3. By client_name (fuzzy substring match — fetch all, filter in JS)
 * 4. If project_type is given and multiple candidates, filter further
 * 5. Sorts by created_at descending to return the most recent match
 *
 * Throws if no project is found.
 */
export async function resolveProject(
  supabase: SupabaseClient,
  input: { project_id?: string; client_name?: string; project_type?: string }
): Promise<Project> {
  // 1. Try by UUID first
  if (input.project_id) {
    const { data, error } = await supabase.from('projects').select('*').eq('id', input.project_id).single();
    if (!error && data) return data as Project;
  }

  // 2. Try by client name
  if (input.client_name) {
    // Exact match
    const { data: exact } = await supabase.from('projects').select('*').eq('client_name', input.client_name);
    let candidates = (exact as Project[]) ?? [];

    // Fuzzy substring match fallback
    if (candidates.length === 0) {
      const { data: all } = await supabase.from('projects').select('*');
      candidates = ((all as Project[]) ?? []).filter((p) =>
        p.client_name.includes(input.client_name!) || input.client_name!.includes(p.client_name)
      );
    }

    // If project_type also given, filter further
    if (input.project_type && candidates.length > 1) {
      const filtered = candidates.filter((p) =>
        p.project_type.includes(input.project_type!) || input.project_type!.includes(p.project_type)
      );
      if (filtered.length > 0) candidates = filtered;
    }

    // Sort by created_at descending to pick most recent project
    if (candidates.length > 0) {
      candidates.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
      return candidates[0];
    }
  }

  throw new Error(`Project not found. Tried project_id=${input.project_id ?? 'N/A'}, client_name=${input.client_name ?? 'N/A'}.`);
}