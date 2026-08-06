-- Review and clean stale test members from team_members.
-- Run this in Supabase SQL Editor.

-- 1. Preview stale/test members before deleting (safe: SELECT only)
SELECT id, name, role, created_at
FROM team_members
WHERE name IN ('测试员', '张三', '李四', '王五')
   OR role ILIKE '%test%'
   OR created_at < '2024-01-01'
ORDER BY created_at;

-- 2. Uncomment to delete after confirming the preview is correct:
-- DELETE FROM team_members
-- WHERE name IN ('测试员', '张三', '李四', '王五')
--    OR role ILIKE '%test%'
--    OR created_at < '2024-01-01';
