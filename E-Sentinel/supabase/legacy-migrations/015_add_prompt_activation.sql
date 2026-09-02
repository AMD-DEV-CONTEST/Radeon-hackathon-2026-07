-- Migration 015: Add is_active column to prompts table for scene-specific activation
ALTER TABLE prompts ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT false;
CREATE INDEX IF NOT EXISTS idx_prompts_is_active ON prompts(is_active);
CREATE INDEX IF NOT EXISTS idx_prompts_scene_active ON prompts(scene, is_active);
