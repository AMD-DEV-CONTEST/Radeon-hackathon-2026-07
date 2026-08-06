-- Add summary_markdown column to meetings table
-- Run this in Supabase SQL Editor or via supabase migration
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS summary_markdown TEXT;
