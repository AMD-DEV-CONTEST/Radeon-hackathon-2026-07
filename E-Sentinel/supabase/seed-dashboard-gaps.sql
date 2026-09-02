-- E-Sentinel seed data for previously-empty dashboard panels.
-- Fills: Release-evidence panel (release_evidences) + Lost-deal diagnosis panel
--        (diagnosis_sessions / diagnosis_findings / diagnosis_reviews).
-- Safe to rerun: stable IDs with ON CONFLICT DO NOTHING.
BEGIN;

-- ── Release evidence (release-evidence panel) ────────────────
INSERT INTO release_evidences (
  id, tenant_id, commit_sha, build_id, schema_version, rule_version, prompt_version,
  model_version, issue_ids, pr_ids, adr_refs, required_checks, checks_passed,
  checks_failed, status, feature_flags, target_cohort, target_percentage,
  correlation_id, approver_id, approver_name, approval_reason, approved_at,
  canary_current_stage, observation_metrics, rollback_triggered, rollback_reason,
  rollback_method, rollback_executed_at, rollback_executed_by, final_conclusion,
  created_at, updated_at
) VALUES
  -- 1) Pending: quality rule v2.1 awaiting approval
  ('f2000000-0000-0000-0000-000000000001', 'default',
   '9f2c4b7a1e8d3f6a5b2c9d0e1f8a7b6c5d4e3f2a',
   'build-20260805-01', 'schema-1.0', 'rules-v2.1', 'prompt-qa-v3', 'qwen3-8b-fp16',
   '["QA-113"]'::jsonb, '["PR-42"]'::jsonb, '["ADR-0004"]'::jsonb,
   '{"goldset-105": true, "stability-3x": true}'::jsonb, true,
   '[]'::jsonb, 'pending', '["agent_qa_new"]'::jsonb, NULL, 0,
   'rel_corr_001', NULL, NULL, NULL, NULL, NULL, '{}'::jsonb,
   false, NULL, NULL, NULL, NULL, NULL,
   NOW() - INTERVAL '2 hours', NOW() - INTERVAL '2 hours'),
  -- 2) Approved + canary in observation
  ('f2000000-0000-0000-0000-000000000002', 'default',
   '1a2b3c4d5e6f708192a3b4c5d6e7f8091a2b3c4d',
   'build-20260803-02', 'schema-1.0', 'rules-v2.0', 'prompt-tone-v4', 'qwen3-8b-fp16',
   '["QA-089"]'::jsonb, '["PR-38"]'::jsonb, '[]'::jsonb,
   '{"human-gold-105": true}'::jsonb, true,
   '[]'::jsonb, 'approved', '["tone_policy"]'::jsonb, '5%', 5,
   'rel_corr_002',
   'a0000000-0000-0000-0000-000000000001', '张明', '话术模板更新，黄金集回放通过', NOW() - INTERVAL '2 days',
   'started', '{"conversation_count": 320, "compliance_violations": 1}'::jsonb,
   false, NULL, NULL, NULL, NULL, '观察中',
   NOW() - INTERVAL '2 days', NOW() - INTERVAL '1 day'),
  -- 3) Rolled back
  ('f2000000-0000-0000-0000-000000000003', 'default',
   '7d8e9f0a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e',
   'build-20260728-09', 'schema-0.9', 'rules-v1.9', 'prompt-qa-v2', 'qwen3-8b-fp16',
   '["QA-061"]'::jsonb, '["PR-30"]'::jsonb, '["ADR-0003"]'::jsonb,
   '{"leak-test": true}'::jsonb, false,
   '["stable-v2-regression"]'::jsonb, 'rolled_back', '["old_rule_engine"]'::jsonb,
   '100%', 100, 'rel_corr_003',
   'a0000000-0000-0000-0000-000000000001', '张明', '发布 6h 后 FPR 上升 12%',
   NOW() - INTERVAL '8 days', NULL, '{}'::jsonb,
   true, 'FPR 上升 12%，触发回滚阈值', 'feature_flag',
   NOW() - INTERVAL '7 days', 'a0000000-0000-0000-0000-000000000001', '已回滚并冻结旧规则',
   NOW() - INTERVAL '8 days', NOW() - INTERVAL '7 days')
ON CONFLICT (id) DO NOTHING;

-- ── Lost-deal diagnosis (diagnosis panel) ───────────────────
INSERT INTO diagnosis_sessions (
  id, tenant_id, trigger_type, status, conversation_ids, campaign_id, product_id,
  time_window_start, time_window_end, engine_version, summary,
  created_by, started_at, finished_at, created_at
) VALUES (
  'e2000000-0000-0000-0000-000000000001', 'default', 'auto_batch', 'completed',
  ARRAY['sess-006', 'pdd-sess-008']::TEXT[], '618_promotion', 'Gemini-335',
  NOW() - INTERVAL '3 days', NOW() - INTERVAL '1 day', 'diagnosis-engine-v1.0',
  '{"loss_count": 14, "top_category": "price_objection", "revenue_impact": 8600}'::jsonb,
  'a0000000-0000-0000-0000-000000000001', NOW() - INTERVAL '2 days', NOW() - INTERVAL '2 days', NOW() - INTERVAL '2 days'
) ON CONFLICT (id) DO NOTHING;

INSERT INTO diagnosis_findings (
  id, session_id, tenant_id, reason_category, fact_statement, inference_statement,
  confidence, confidence_score, counter_evidence, suggestion, suggestion_actionable,
  evidence_refs, funnel_stage, conversation_id, product_id, campaign_id, created_at
) VALUES
  ('e2000000-0000-0000-0000-000000000011', 'e2000000-0000-0000-0000-000000000001', 'default',
   'price_objection',
   '会话 pdd-sess-006 中客户因优惠券使用门槛明确表示放弃下单（原文："抱歉优惠券有使用门槛"）。',
   '618 大促优惠券设置过高的门槛，直接拦截了价格敏感客户。',
   'high', 0.82, '部分客户仍正常下单', '将优惠券门槛从满 999 降至满 299，覆盖价格敏感人群。', true,
   '[{"type": "quote", "ref": "pdd-sess-006", "text": "抱歉优惠券有使用门槛"}]'::jsonb,
   'cart', 'pdd-sess-006', 'Gemini-335', '618_promotion', NOW() - INTERVAL '2 days'),
  ('e2000000-0000-0000-0000-000000000012', 'e2000000-0000-0000-0000-000000000001', 'default',
   'service_failure',
   '会话 sess-008 中客服在客户询问物流时效时仅回复"请您耐心等待"且未给出预计到达时间。',
   '客服未提供确定性信息，削弱客户信任导致流失。',
   'medium', 0.61, '该客服整体满意度仍高于团队均值', '为物流查询配置确定性时效话术并加入质检规则。', true,
   '[{"type": "quote", "ref": "sess-008", "text": "请您耐心等待"}]'::jsonb,
   'conversation', 'sess-008', 'Gemini-335', '618_promotion', NOW() - INTERVAL '2 days')
ON CONFLICT (id) DO NOTHING;

INSERT INTO diagnosis_reviews (
  id, finding_id, tenant_id, reviewer_id, decision, modified_reason, feedback_note,
  feedback_target, created_at
) VALUES (
  'e2000000-0000-0000-0000-000000000021', 'e2000000-0000-0000-0000-000000000011',
  'default', 'a0000000-0000-0000-0000-000000000001', 'accepted', NULL,
  '价格敏感客户占比确认，门槛调整建议合理。', 'rule', NOW() - INTERVAL '1 day'
) ON CONFLICT (id) DO NOTHING;

COMMIT;
