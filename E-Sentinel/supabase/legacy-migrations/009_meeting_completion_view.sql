-- Meeting completion stats view
-- Aggregates task completion per meeting; used by /api/meetings/stats
CREATE OR REPLACE VIEW meeting_completion_stats AS
SELECT
  m.id                                                          AS meeting_id,
  m.title,
  m.created_at,
  m.user_id,
  COUNT(t.id) FILTER (WHERE t.status <> 'cancelled' AND t.deleted_at IS NULL)           AS task_total,
  COUNT(t.id) FILTER (WHERE t.status = 'completed'  AND t.deleted_at IS NULL)           AS task_completed,
  COUNT(t.id) FILTER (WHERE t.status NOT IN ('completed','cancelled') AND t.deleted_at IS NULL) AS task_pending,
  CASE
    WHEN COUNT(t.id) FILTER (WHERE t.status <> 'cancelled' AND t.deleted_at IS NULL) = 0 THEN NULL
    ELSE ROUND(
      COUNT(t.id) FILTER (WHERE t.status = 'completed' AND t.deleted_at IS NULL)::numeric
      / COUNT(t.id) FILTER (WHERE t.status <> 'cancelled' AND t.deleted_at IS NULL)::numeric
      * 100, 1
    )
  END                                                           AS completion_rate
FROM meetings m
LEFT JOIN tasks t ON t.meeting_id = m.id
GROUP BY m.id, m.title, m.created_at, m.user_id;
