-- E-Sentinel cross-panel demo data
-- Run after all migrations and the existing seed-data.sql files.
-- Safe to re-run: demo rows use stable IDs and conflict guards.
-- The same session/report/correlation IDs intentionally appear in multiple tables
-- so the dashboard can be checked across panels.

BEGIN;

-- Local projects may not have the optional observability migration applied yet.
-- Keep the demo script self-contained without changing the production schema contract.
CREATE TABLE IF NOT EXISTS llm_call_logs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  endpoint TEXT NOT NULL,
  model TEXT NOT NULL,
  tokens_used INTEGER NOT NULL DEFAULT 0,
  cost_estimate NUMERIC(12, 6) NOT NULL DEFAULT 0,
  success BOOLEAN NOT NULL DEFAULT false,
  cached BOOLEAN NOT NULL DEFAULT false,
  response_time_ms INTEGER NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_demo_llm_call_logs_created_at ON llm_call_logs(created_at DESC);

-- Stable IDs used by the demo dataset.
DO $$
BEGIN
  INSERT INTO model_configs (id, name, provider, model_name, temperature, max_tokens, top_p, is_default, is_active, priority)
  VALUES
    ('d1000000-0000-0000-0000-000000000001', '演示-DeepSeek 主模型', 'deepseek', 'deepseek-chat', 0.70, 4096, 1.00, true, true, 1),
    ('d1000000-0000-0000-0000-000000000002', '演示-Kimi 兜底模型', 'kimi', 'moonshot-v1-8k', 0.60, 2048, 0.95, false, true, 2),
    ('d1000000-0000-0000-0000-000000000003', '演示-轻量分类模型', 'qwen', 'qwen-turbo', 0.20, 1024, 1.00, false, true, 3)
  ON CONFLICT (id) DO NOTHING;

  INSERT INTO prompts (id, name, scene, system_prompt, variables, temperature, max_tokens, version, status, is_active)
  VALUES
    ('d2000000-0000-0000-0000-000000000001', '演示-售前转化助手', 'pre_sale', '你是美妆品牌售前顾问。先识别肤质和需求，再给出可验证的产品建议，不承诺绝对效果。', '[{"name":"shop_name","required":true},{"name":"customer_question","required":true}]'::jsonb, 0.65, 2048, 3, 'published', true),
    ('d2000000-0000-0000-0000-000000000002', '演示-售后安抚助手', 'after_sale', '你是售后服务专员。先确认订单和问题，再说明处理时效与升级路径，涉及过敏和医疗问题必须转人工。', '[{"name":"order_id","required":true},{"name":"issue","required":true}]'::jsonb, 0.45, 2048, 2, 'published', true),
    ('d2000000-0000-0000-0000-000000000003', '演示-物流查询助手', 'logistics', '你是物流查询客服。只引用已查到的物流状态，无法确认时明确说明并提供人工跟进方式。', '[{"name":"order_id","required":true}]'::jsonb, 0.35, 1024, 2, 'published', true),
    ('d2000000-0000-0000-0000-000000000004', '演示-合规回复审校', 'general', '审查客服回复中的绝对化用语、虚假承诺、平台比较和敏感表达，并给出可直接替换的合规版本。', '[{"name":"draft_reply","required":true}]'::jsonb, 0.15, 1536, 4, 'draft', false)
  ON CONFLICT (id) DO NOTHING;

  INSERT INTO prompt_versions (id, prompt_id, version, system_prompt, variables, temperature, max_tokens, created_by)
  VALUES
    ('d2100000-0000-0000-0000-000000000001', 'd2000000-0000-0000-0000-000000000001', 1, '你是美妆品牌售前顾问。根据客户需求推荐商品。', '[]'::jsonb, 0.70, 1536, 'demo-seed'),
    ('d2100000-0000-0000-0000-000000000002', 'd2000000-0000-0000-0000-000000000001', 2, '你是美妆品牌售前顾问。先识别肤质和需求，再给出可验证的产品建议。', '[]'::jsonb, 0.65, 2048, 'demo-seed'),
    ('d2100000-0000-0000-0000-000000000003', 'd2000000-0000-0000-0000-000000000001', 3, '你是美妆品牌售前顾问。先识别肤质和需求，再给出可验证的产品建议，不承诺绝对效果。', '[{"name":"shop_name","required":true}]'::jsonb, 0.65, 2048, 'demo-seed'),
    ('d2100000-0000-0000-0000-000000000004', 'd2000000-0000-0000-0000-000000000002', 1, '你是售后服务专员。先安抚，再核实订单，最后给出处理路径。', '[]'::jsonb, 0.50, 1536, 'demo-seed'),
    ('d2100000-0000-0000-0000-000000000005', 'd2000000-0000-0000-0000-000000000002', 2, '你是售后服务专员。涉及过敏和医疗问题必须转人工。', '[]'::jsonb, 0.45, 2048, 'demo-seed')
  ON CONFLICT (id) DO NOTHING;

  INSERT INTO bots (id, name, welcome_message, prompt_id, model_config_id, platform, working_hours, transfer_keywords, is_active)
  VALUES
    ('d3000000-0000-0000-0000-000000000001', '演示-天猫美妆客服', '您好，欢迎来到品牌旗舰店，我可以帮您查询商品、活动和订单。', 'd2000000-0000-0000-0000-000000000001', 'd1000000-0000-0000-0000-000000000001', 'tmall', '{"start":"09:00","end":"23:00","timezone":"Asia/Shanghai"}'::jsonb, '["人工","投诉","过敏","医疗"]'::jsonb, true),
    ('d3000000-0000-0000-0000-000000000002', '演示-抖音售后助手', '您好，我来帮您跟进订单和售后问题，请提供订单号。', 'd2000000-0000-0000-0000-000000000002', 'd1000000-0000-0000-0000-000000000002', 'douyin', '{"start":"10:00","end":"22:00","timezone":"Asia/Shanghai"}'::jsonb, '["人工","退款","投诉","过敏"]'::jsonb, true),
    ('d3000000-0000-0000-0000-000000000003', '演示-京东物流助手', '您好，我可以帮您查询物流进度和预计送达时间。', 'd2000000-0000-0000-0000-000000000003', 'd1000000-0000-0000-0000-000000000003', 'jd', '{"start":"08:00","end":"22:00","timezone":"Asia/Shanghai"}'::jsonb, '["人工","延误","投诉"]'::jsonb, true)
  ON CONFLICT (id) DO NOTHING;
END $$;

-- Make the existing knowledge base useful for effect and hit-rate panels.
UPDATE knowledge_entries
SET hit_count = CASE category
  WHEN 'product' THEN 96
  WHEN 'faq' THEN 72
  WHEN 'after_sales_policy' THEN 58
  WHEN 'campaign' THEN 44
  ELSE 31
END,
  last_hit_at = now() - interval '12 hours',
effect_metrics = jsonb_build_object(
  'pre_update_hit_rate', 0.68,
  'post_update_hit_rate', 0.89,
  'gap_reduction_pct', 0.37,
  'sample_count', 128,
  'snapshot_date', current_date::text
)
WHERE status = 'published';

-- Additional knowledge entries used by the current sessions and work orders.
INSERT INTO knowledge_entries (id, category, platform_id, title, content, keywords, tags, priority, status, source, updated_by, version, tone, hit_count, gap_source_count, last_hit_at, effect_metrics)
SELECT v.id, v.category, p.id, v.title, v.content, v.keywords, v.tags, v.priority, v.status, 'demo-cross-panel', 'a0000000-0000-0000-0000-000000000002'::uuid, v.version, v.tone, v.hit_count, v.gap_source_count, now() - (v.hours_ago * interval '1 hour'), v.effect_metrics::jsonb
FROM (VALUES
  ('d4000000-0000-0000-0000-000000000001'::uuid, 'product', 'tmall', '神经酰胺屏障修护面霜', '含神经酰胺和泛醇，适合干燥及敏感肌日常修护。首次使用建议先做局部测试。', ARRAY['神经酰胺','屏障','敏感肌'], ARRAY['产品','敏感肌'], 8, 'published', 3, 'friendly', 84, 2, 6, '{"pre_update_hit_rate":0.63,"post_update_hit_rate":0.91,"gap_reduction_pct":0.45}'),
  ('d4000000-0000-0000-0000-000000000002'::uuid, 'faq', 'jd', 'SPF 与 PA 如何选择', '通勤可选择 SPF30 以上且 PA+++ 的产品；户外长时间活动需要按说明补涂。', ARRAY['SPF','PA','防晒'], ARRAY['FAQ','防晒'], 7, 'published', 2, 'concise', 67, 4, 12, '{"pre_update_hit_rate":0.59,"post_update_hit_rate":0.86,"gap_reduction_pct":0.38}'),
  ('d4000000-0000-0000-0000-000000000003'::uuid, 'after_sales_policy', 'douyin', '破损和漏液售后处理', '请保留外包装、订单号和商品照片。核实后可按平台规则安排补发、退款或其他处理。', ARRAY['破损','漏液','补发','退款'], ARRAY['售后','高频'], 10, 'published', 1, 'professional', 73, 5, 4, '{"pre_update_hit_rate":0.55,"post_update_hit_rate":0.88,"gap_reduction_pct":0.52}'),
  ('d4000000-0000-0000-0000-000000000004'::uuid, 'campaign', 'tmall', '夏季满减活动规则', '单笔满399元可享赠品，优惠以结算页实际展示为准，不同平台活动可能不同。', ARRAY['满减','赠品','夏季活动'], ARRAY['活动','需实时更新'], 9, 'draft', 1, 'friendly', 0, 12, 96, '{"pre_update_hit_rate":0.42,"post_update_hit_rate":0.74,"gap_reduction_pct":0.29}'),
  ('d4000000-0000-0000-0000-000000000005'::uuid, 'faq', 'pdd', '孕期护肤咨询边界', '客服只能提供产品成分和使用信息，孕期、疾病或过敏相关问题建议咨询医生，并转人工服务。', ARRAY['孕期','成分','过敏','医生'], ARRAY['FAQ','敏感问题'], 10, 'published', 0, 'professional', 52, 9, 18, '{"pre_update_hit_rate":0.48,"post_update_hit_rate":0.82,"gap_reduction_pct":0.61}')
) AS v(id, category, platform_code, title, content, keywords, tags, priority, status, version, tone, hit_count, gap_source_count, hours_ago, effect_metrics)
JOIN platforms p ON p.code = v.platform_code
ON CONFLICT (id) DO NOTHING;

-- More bot configurations with effect snapshots, linked to the same platforms.
INSERT INTO bot_configs (id, platform_id, config_type, config_key, config_value, version, status, updated_by, change_summary, source_type, source_session_ids, effect_metrics, created_at, updated_at)
SELECT v.id, p.id, v.config_type, v.config_key, v.config_value::jsonb, v.version, v.status, 'a0000000-0000-0000-0000-000000000002'::uuid, v.change_summary, v.source_type, ARRAY['b1000000-0000-0000-0000-' || lpad(v.session_no::text, 12, '0')]::uuid[], v.effect_metrics::jsonb, now() - (v.days_ago * interval '1 day'), now() - (v.days_ago * interval '1 day')
FROM (VALUES
  ('d5000000-0000-0000-0000-000000000001'::uuid, 'tmall', 'pre_sale', 'demo_product_recommend', '{"greeting":"您好，我可以根据肤质和预算推荐产品。","max_rounds":6}', 3, 'active', '基于售前询单样本优化推荐顺序', 'inspect_script', 1, '{"pre_publish_satisfaction":0.81,"post_publish_satisfaction":0.91,"post_publish_handled_rate":0.88}', 2),
  ('d5000000-0000-0000-0000-000000000002'::uuid, 'tmall', 'post_sale', 'demo_allergy_escalation', '{"trigger_keywords":["过敏","红疹","就医"],"action":"transfer_human"}', 2, 'active', '增加敏感问题人工升级', 'knowledge_loop', 2, '{"pre_publish_satisfaction":0.63,"post_publish_satisfaction":0.86,"post_publish_handled_rate":0.72}', 3),
  ('d5000000-0000-0000-0000-000000000003'::uuid, 'jd', 'pre_sale', 'demo_sunscreen_faq', '{"knowledge_title":"SPF 与 PA 如何选择","fallback":"转人工"}', 2, 'active', '补充防晒高频问答', 'inspect_script', 3, '{"pre_publish_satisfaction":0.78,"post_publish_satisfaction":0.89,"post_publish_handled_rate":0.84}', 4),
  ('d5000000-0000-0000-0000-000000000004'::uuid, 'douyin', 'post_sale', 'demo_damage_claim', '{"required_fields":["订单号","照片"],"sla_hours":24}', 2, 'draft', '等待合规复核后发布', 'llm_suggest', 4, '{"pre_publish_satisfaction":0.71,"post_publish_satisfaction":0.79,"post_publish_handled_rate":0.67}', 1),
  ('d5000000-0000-0000-0000-000000000005'::uuid, 'pdd', 'pre_sale', 'demo_coupon_explain', '{"coupon_rules":["满199减20","不可与部分券叠加"],"avoid_claims":["全网最低"]}', 2, 'active', '修正优惠券解释和合规措辞', 'manual', 5, '{"pre_publish_satisfaction":0.74,"post_publish_satisfaction":0.84,"post_publish_handled_rate":0.79}', 5),
  ('d5000000-0000-0000-0000-000000000006'::uuid, 'xiaohongshu', 'pre_sale', 'demo_content_referral', '{"source":"官方笔记","disclaimer":"以商品详情页为准"}', 1, 'active', '增加内容种草来源说明', 'manual', 6, '{"pre_publish_satisfaction":0.80,"post_publish_satisfaction":0.88,"post_publish_handled_rate":0.82}', 6)
) AS v(id, platform_code, config_type, config_key, config_value, version, status, change_summary, source_type, session_no, effect_metrics, days_ago)
JOIN platforms p ON p.code = v.platform_code
ON CONFLICT (id) DO NOTHING;

-- 60 recent sessions across five platforms. The corresponding fixed report IDs,
-- shadow replies, unresolved questions, and correlation IDs are derived from n.
DO $$
DECLARE
  n integer;
  platform_code text;
  session_type text;
  inquiry_result text;
  satisfaction text;
  bot_handled boolean;
  bot_id uuid;
  session_id uuid;
  agent_id uuid;
  created_at_value timestamptz;
BEGIN
  FOR n IN 1..60 LOOP
    platform_code := (ARRAY['tmall','jd','douyin','pdd','xiaohongshu'])[((n - 1) % 5) + 1];
    session_type := CASE WHEN n % 3 = 0 THEN 'post_sale' ELSE 'pre_sale' END;
    inquiry_result := CASE WHEN session_type = 'post_sale' THEN NULL WHEN n % 7 = 0 THEN 'lost' WHEN n % 11 = 0 THEN 'pending' ELSE 'converted' END;
    satisfaction := CASE WHEN n % 9 = 0 THEN 'bad' WHEN n % 4 = 0 THEN 'neutral' ELSE 'good' END;
    bot_handled := n % 8 <> 0;
    bot_id := CASE platform_code WHEN 'tmall' THEN 'd3000000-0000-0000-0000-000000000001'::uuid WHEN 'douyin' THEN 'd3000000-0000-0000-0000-000000000002'::uuid ELSE 'd3000000-0000-0000-0000-000000000003'::uuid END;
    session_id := ('b1000000-0000-0000-0000-' || lpad(n::text, 12, '0'))::uuid;
    agent_id := CASE (n % 5) WHEN 0 THEN 'a0000000-0000-0000-0000-000000000003'::uuid WHEN 1 THEN 'a0000000-0000-0000-0000-000000000004'::uuid WHEN 2 THEN '00000000-0000-0000-0000-000000000101'::uuid WHEN 3 THEN '00000000-0000-0000-0000-000000000102'::uuid ELSE '00000000-0000-0000-0000-000000000103'::uuid END;
    created_at_value := CASE WHEN n <= 12 THEN now() - (n * interval '2 hours') ELSE now() - ((n % 30 + 1) * interval '1 day') END;

    INSERT INTO bot_chat_sessions (id, platform_id, session_type, external_session_id, customer_id, bot_handled, transfer_reason, is_inquiry, inquiry_result, sentiment_score, satisfaction, total_messages, first_response_ms, resolution_ms, tags, conversation, correlation_id, bot_id, tenant_id, created_at)
    SELECT session_id, p.id, session_type, 'demo-' || platform_code || '-' || lpad(n::text, 3, '0'), 'demo-customer-' || lpad(n::text, 3, '0'), bot_handled,
      CASE WHEN bot_handled THEN NULL WHEN n % 3 = 0 THEN 'sensitive_issue' ELSE 'complex_product_query' END,
      session_type = 'pre_sale', inquiry_result, CASE WHEN satisfaction = 'bad' THEN 1 WHEN satisfaction = 'neutral' THEN 3 ELSE 5 END, satisfaction,
      4 + (n % 12), 450 + (n % 8) * 180, CASE WHEN satisfaction = 'bad' THEN 480000 ELSE 60000 + (n % 8) * 30000 END,
      CASE WHEN n % 5 = 0 THEN ARRAY['敏感肌','成分'] ELSE ARRAY['产品咨询','demo'] END,
      CASE WHEN session_type = 'pre_sale' THEN '顾客: 这款产品适合敏感肌吗？\n机器人: 建议先查看成分并做局部测试，我可以继续帮您匹配。\n顾客: 还有优惠活动吗？\n机器人: 当前活动以结算页展示为准。' ELSE '顾客: 我的订单需要查询售后进度。\n机器人: 请提供订单号和问题照片，我会先核实状态。\n顾客: 已经提交过了，什么时候能处理？' END,
      'corr-demo-' || lpad(n::text, 3, '0'), bot_id, 'default', created_at_value
    FROM platforms p WHERE p.code = platform_code
    ON CONFLICT (id) DO NOTHING;

    INSERT INTO quality_reports (id, ticket_id, agent_id, reviewer_id, conversation, intent, sentiment_score, total_score, violations, risk_level, status, correlation_id, review_mode, is_bot_session, bot_session_id, platform_id, tenant_id, created_at)
    SELECT ('c1000000-0000-0000-0000-' || lpad(n::text, 12, '0'))::uuid, 'demo-' || platform_code || '-' || lpad(n::text, 3, '0'), agent_id,
      'a0000000-0000-0000-0000-000000000002'::uuid, '顾客咨询与客服回复的演示质检记录', CASE WHEN session_type = 'pre_sale' THEN '产品咨询' ELSE '售后进度' END,
      CASE WHEN satisfaction = 'bad' THEN 1 WHEN satisfaction = 'neutral' THEN 3 ELSE 5 END,
      CASE WHEN satisfaction = 'bad' THEN 48 + (n % 12) WHEN satisfaction = 'neutral' THEN 72 + (n % 10) ELSE 88 + (n % 10) END,
      CASE WHEN satisfaction = 'bad' THEN '[{"rule":"未明确说明升级路径","category":"服务质量","deduction":15,"severity":"major"},{"rule":"未确认客户已提交材料","category":"响应效率","deduction":10,"severity":"medium"}]'::jsonb WHEN n % 6 = 0 THEN '[{"rule":"活动规则引用不完整","category":"准确性","deduction":8,"severity":"minor"}]'::jsonb ELSE '[]'::jsonb END,
      CASE WHEN satisfaction = 'bad' THEN 'high' WHEN n % 10 = 0 THEN 'medium' ELSE 'low' END,
      CASE WHEN n % 10 = 0 THEN 'pending_review' WHEN n % 13 = 0 THEN 'overturned' ELSE 'confirmed' END,
      'corr-demo-' || lpad(n::text, 3, '0'), CASE WHEN n % 4 = 0 THEN 'shadow' ELSE 'active' END, true, session_id, p.id, 'default', created_at_value + interval '5 minutes'
    FROM platforms p WHERE p.code = platform_code
    ON CONFLICT (id) DO NOTHING;
  END LOOP;
END $$;

-- Recent shadow and actual replies feed quality monitoring and shadow approval.
DO $$
DECLARE
  n integer;
  code text;
BEGIN
  FOR n IN 1..72 LOOP
    code := (ARRAY['tmall','jd','douyin','pdd','xiaohongshu'])[((n - 1) % 5) + 1];
    INSERT INTO shadow_replies (id, platform_id, session_id, message_id, customer_id, original_text, generated_reply, reply_mode, llm_latency_ms, was_fallback, cached, gate_reason, gate_tier, quality_score, metadata, created_at)
    VALUES (
      ('d6000000-0000-0000-0000-' || lpad(n::text, 12, '0'))::uuid, code, 'demo-session-' || code || '-' || lpad(((n - 1) % 60 + 1)::text, 3, '0'), 'demo-msg-shadow-' || n, 'demo-customer-' || lpad(((n - 1) % 60 + 1)::text, 3, '0'),
      CASE WHEN n % 3 = 0 THEN '我的订单什么时候发货？' WHEN n % 3 = 1 THEN '敏感肌可以用吗？' ELSE '现在有什么优惠？' END,
      CASE WHEN n % 3 = 0 THEN '我先帮您查询物流状态，确认后给出预计发货时间。' WHEN n % 3 = 1 THEN '建议先查看完整成分表并做局部测试，涉及过敏问题可转人工。' ELSE '活动和优惠以当前商品结算页展示为准。' END,
      CASE WHEN n % 4 = 0 THEN 'gradual' ELSE 'shadow' END, 380 + (n % 9) * 210, n % 17 = 0, n % 5 = 0,
      CASE WHEN n % 4 = 0 THEN 'simple_question_match' ELSE 'whitelist_match' END, CASE WHEN n % 4 = 0 THEN 'simple_questions' ELSE 'whitelist' END,
      CASE WHEN n % 17 = 0 THEN 0.62 ELSE 0.86 + (n % 10) / 100.0 END,
      jsonb_build_object('store_nick', code || '_demo_store', 'correlation_id', 'corr-demo-' || lpad(((n - 1) % 60 + 1)::text, 3, '0')), now() - (n * interval '18 minutes')
    ) ON CONFLICT (id) DO NOTHING;

    IF n <= 36 THEN
      INSERT INTO actual_replies (id, platform_id, session_id, message_id, customer_id, original_text, generated_reply, sanitized_reply, reply_mode, llm_latency_ms, was_fallback, compliance_safe, compliance_block_reason, sent_success, sent_at, platform_msg_id, quality_score, metadata, created_at)
      VALUES (
        ('d6100000-0000-0000-0000-' || lpad(n::text, 12, '0'))::uuid, code, 'demo-session-' || code || '-' || lpad(((n - 1) % 60 + 1)::text, 3, '0'), 'demo-msg-actual-' || n, 'demo-customer-' || lpad(((n - 1) % 60 + 1)::text, 3, '0'),
        '我想确认一下这个订单和产品信息。', '您好，我来帮您核实订单和商品信息。', '您好，我来帮您核实订单和商品信息。', CASE WHEN n % 3 = 0 THEN 'full' ELSE 'gradual' END, 420 + (n % 7) * 240, n % 19 = 0,
        n % 11 <> 0, CASE WHEN n % 11 = 0 THEN '命中敏感问题，需要人工复核' ELSE NULL END, n % 4 <> 0, CASE WHEN n % 4 <> 0 THEN now() - (n * interval '25 minutes') ELSE NULL END,
        CASE WHEN n % 4 <> 0 THEN 'platform-msg-' || n ELSE NULL END, CASE WHEN n % 11 = 0 THEN 0.58 ELSE 0.82 + (n % 12) / 100.0 END,
        jsonb_build_object('approved', n % 4 <> 0, 'reviewed_by', CASE WHEN n % 4 <> 0 THEN 'demo-operator' ELSE NULL END, 'correlation_id', 'corr-demo-' || lpad(((n - 1) % 60 + 1)::text, 3, '0')), now() - (n * interval '25 minutes')
      ) ON CONFLICT (id) DO NOTHING;
    END IF;
  END LOOP;
END $$;

-- LLM ledger rows are persisted so the observability panel is populated after a restart.
INSERT INTO llm_call_logs (id, endpoint, model, tokens_used, cost_estimate, success, cached, response_time_ms, created_at)
SELECT ('d6200000-0000-0000-0000-' || lpad(n::text, 12, '0'))::uuid,
  CASE n % 5 WHEN 0 THEN '/api/qa/evaluate' WHEN 1 THEN '/api/qa/satisfaction/analyze' WHEN 2 THEN '/api/qa/knowledge/search' WHEN 3 THEN '/api/qa/payment-reminders' ELSE '/api/qa/prompts/generate' END,
  CASE n % 3 WHEN 0 THEN 'deepseek-chat' WHEN 1 THEN 'moonshot-v1-8k' ELSE 'qwen-turbo' END,
  320 + (n % 15) * 47, round((0.002 + (n % 8) * 0.0007)::numeric, 6), n % 13 <> 0, n % 5 = 0, 620 + (n % 18) * 310,
  now() - (n * interval '4 minutes')
FROM generate_series(1, 120) AS n
ON CONFLICT (id) DO NOTHING;

-- Unresolved questions mirror the transferred or low-satisfaction sessions.
INSERT INTO unresolved_questions (id, session_id, platform_id, platform_code, user_question, ai_reply, transfer_reason, satisfaction, conversation, category, tags, status, priority, assigned_to, note, resolved_by, resolved_at, correlation_id, created_at, updated_at)
SELECT ('d6300000-0000-0000-0000-' || lpad(n::text, 12, '0'))::uuid,
  'demo-session-' || p.code || '-' || lpad(((n - 1) % 60 + 1)::text, 3, '0'), p.id, p.code,
  CASE n % 5 WHEN 0 THEN '孕期可以使用这款产品吗？' WHEN 1 THEN '商品漏液了，已经提交照片，什么时候处理？' WHEN 2 THEN '这个成分和我正在使用的药会冲突吗？' WHEN 3 THEN '订单一直没有物流更新怎么办？' ELSE '活动优惠和直播间券可以一起使用吗？' END,
  '这个问题需要进一步核实，我先为您转接人工客服。', CASE n % 3 WHEN 0 THEN 'sensitive_issue' WHEN 1 THEN 'policy_unclear' ELSE 'complex_product_query' END,
  CASE n % 4 WHEN 0 THEN 'bad' WHEN 1 THEN 'neutral' ELSE 'good' END,
  '顾客: 需要确认一个复杂问题。\n机器人: 已记录问题，但当前需要人工核实。\n顾客: 请尽快给我明确答复。',
  CASE n % 4 WHEN 0 THEN '敏感问题' WHEN 1 THEN '售后政策' WHEN 2 THEN '物流查询' ELSE '活动规则' END,
  ARRAY['demo','需人工核实'], CASE n % 5 WHEN 0 THEN 'resolved' WHEN 1 THEN 'processing' WHEN 2 THEN 'exported' ELSE 'pending' END,
  CASE WHEN n % 5 = 0 THEN 2 WHEN n % 3 = 0 THEN 1 ELSE 0 END, CASE WHEN n % 5 = 0 THEN 'ou_demo_001' ELSE NULL END,
  CASE WHEN n % 5 = 0 THEN '已补充知识库条目并回访客户' ELSE NULL END, CASE WHEN n % 5 = 0 THEN 'demo-operator' ELSE NULL END,
  CASE WHEN n % 5 = 0 THEN now() - ((n % 16 + 1) * interval '1 hour') ELSE NULL END,
  'corr-demo-' || lpad(((n - 1) % 60 + 1)::text, 3, '0'), now() - ((n % 7 + 1) * interval '1 day'), now()
FROM generate_series(1, 24) AS n
JOIN platforms p ON p.code = (ARRAY['tmall','jd','douyin','pdd','xiaohongshu'])[((n - 1) % 5) + 1]
ON CONFLICT (id) DO NOTHING;

INSERT INTO unresolved_question_logs (id, unresolved_id, action, operator, detail, created_at)
SELECT ('d6400000-0000-0000-0000-' || lpad(n::text, 12, '0'))::uuid, ('d6300000-0000-0000-0000-' || lpad(n::text, 12, '0'))::uuid,
  CASE WHEN n % 3 = 0 THEN 'resolve' WHEN n % 3 = 1 THEN 'assign' ELSE 'create' END, 'demo-operator', jsonb_build_object('source','cross-panel-demo','step',n), now() - (n * interval '20 hours')
FROM generate_series(1, 24) AS n
ON CONFLICT (id) DO NOTHING;

-- Intent accuracy: one row per platform/day for a 30-day trend with a few alert days.
INSERT INTO intent_accuracy_logs (id, platform_id, period_date, total_recognitions, correct_recognitions, incorrect_recognitions, accuracy, coverage_rate, target_met, bad_case_ids, notes, created_at)
SELECT ('d6500000-0000-0000-0000-' || lpad(n::text, 12, '0'))::uuid, p.id, current_date - ((n - 1) % 30),
  420 + (n % 9) * 23, 420 + (n % 9) * 23 - CASE WHEN n % 17 = 0 THEN 7 ELSE (n % 3) END, CASE WHEN n % 17 = 0 THEN 7 ELSE (n % 3) END,
  round(((420 + (n % 9) * 23 - CASE WHEN n % 17 = 0 THEN 7 ELSE (n % 3) END)::numeric / (420 + (n % 9) * 23))::numeric, 4),
  round((0.95 + (n % 5) * 0.01)::numeric, 4), n % 17 <> 0 AND n % 11 <> 0, ARRAY[]::uuid[], CASE WHEN n % 17 = 0 THEN '演示告警日：需复核低置信度意图' ELSE '每日抽样复核' END, now() - (n * interval '10 hours')
FROM generate_series(1, 150) AS n
JOIN platforms p ON p.code = (ARRAY['tmall','jd','douyin','pdd','xiaohongshu','vip','kuaishou','weibo'])[((n - 1) % 8) + 1]
ON CONFLICT (platform_id, period_date) DO NOTHING;

-- Work orders and action history cover every status and priority branch.
INSERT INTO work_orders (id, title, description, source, source_id, priority, status, category, platform_id, assigned_to, metadata, created_at, resolved_at, closed_at)
SELECT ('d6600000-0000-0000-0000-' || lpad(n::text, 12, '0'))::uuid,
  CASE n % 5 WHEN 0 THEN '敏感问题升级路径需要补充' WHEN 1 THEN '物流延迟话术需要平台适配' WHEN 2 THEN '活动优惠规则需要重新发布' WHEN 3 THEN '漏液售后知识条目需要复核' ELSE '机器人回复质量抽样复盘' END,
  '演示工单：由质检、合规、知识库或监控面板产生，关联同一批演示会话。',
  CASE n % 5 WHEN 0 THEN 'compliance_block' WHEN 1 THEN 'qa_evaluate' WHEN 2 THEN 'cron' WHEN 3 THEN 'inspection' ELSE 'manual' END,
  ('c1000000-0000-0000-0000-' || lpad((n % 60 + 1)::text, 12, '0'))::uuid,
  CASE n % 4 WHEN 0 THEN 'critical' WHEN 1 THEN 'high' WHEN 2 THEN 'medium' ELSE 'low' END,
  CASE n % 4 WHEN 0 THEN 'open' WHEN 1 THEN 'in_progress' WHEN 2 THEN 'resolved' ELSE 'closed' END,
  CASE n % 5 WHEN 0 THEN 'compliance' WHEN 1 THEN 'script_fix' WHEN 2 THEN 'knowledge_gap' WHEN 3 THEN 'customer_complaint' ELSE 'system_issue' END,
  p.id, CASE n % 3 WHEN 0 THEN 'a0000000-0000-0000-0000-000000000003'::uuid WHEN 1 THEN 'a0000000-0000-0000-0000-000000000004'::uuid ELSE '00000000-0000-0000-0000-000000000101'::uuid END,
  jsonb_build_object('source_panel', CASE n % 4 WHEN 0 THEN '合规审核' WHEN 1 THEN '质检中枢' WHEN 2 THEN '知识库' ELSE '回复质量监控' END, 'demo', true),
  now() - (n * interval '9 hours'), CASE WHEN n % 4 >= 2 THEN now() - (n * interval '4 hours') ELSE NULL END, CASE WHEN n % 4 = 3 THEN now() - (n * interval '3 hours') ELSE NULL END
FROM generate_series(1, 24) AS n
JOIN platforms p ON p.code = (ARRAY['tmall','jd','douyin','pdd','xiaohongshu'])[((n - 1) % 5) + 1]
ON CONFLICT (id) DO NOTHING;

INSERT INTO work_order_actions (id, work_order_id, action, comment, performed_by, metadata, created_at)
SELECT ('d6700000-0000-0000-0000-' || lpad(n::text, 12, '0'))::uuid, ('d6600000-0000-0000-0000-' || lpad(n::text, 12, '0'))::uuid,
  CASE n % 4 WHEN 0 THEN 'created' WHEN 1 THEN 'assigned' WHEN 2 THEN 'in_progress' ELSE 'commented' END,
  CASE n % 4 WHEN 0 THEN '系统自动创建' WHEN 1 THEN '已分配给坐席' WHEN 2 THEN '负责人开始处理' ELSE '补充了关联会话和证据' END,
  'a0000000-0000-0000-0000-000000000002'::uuid, jsonb_build_object('demo', true, 'correlation_id', 'corr-demo-' || lpad(n::text, 3, '0')), now() - (n * interval '7 hours')
FROM generate_series(1, 24) AS n
ON CONFLICT (id) DO NOTHING;

-- Payment reminders include pending, reminded, paid, expired and cancelled orders.
INSERT INTO pending_orders (id, external_order_id, platform_id, customer_id, customer_name, product_name, order_amount, order_status, created_at_order, expire_at, metadata, created_at, updated_at)
SELECT ('d6800000-0000-0000-0000-' || lpad(n::text, 12, '0'))::uuid, 'DEMO-ORDER-' || lpad(n::text, 4, '0'), p.id, 'demo-customer-' || n, '演示客户' || n,
  CASE n % 4 WHEN 0 THEN '舒缓修护套装' WHEN 1 THEN '神经酰胺面霜' WHEN 2 THEN '玻尿酸补水面膜' ELSE '防晒乳 SPF50+' END,
  (129 + n * 17.5)::numeric(10,2), CASE n % 5 WHEN 0 THEN 'pending_payment' WHEN 1 THEN 'reminded' WHEN 2 THEN 'paid' WHEN 3 THEN 'expired' ELSE 'cancelled' END,
  now() - (n * interval '5 hours'), now() + ((24 - n) * interval '1 hour'), jsonb_build_object('source','demo-cross-panel','session_id','demo-session-' || p.code || '-' || lpad(((n - 1) % 60 + 1)::text, 3, '0')),
  now() - (n * interval '4 hours'), now() - (n * interval '2 hours')
FROM generate_series(1, 20) AS n
JOIN platforms p ON p.code = (ARRAY['tmall','jd','douyin','pdd','xiaohongshu'])[((n - 1) % 5) + 1]
ON CONFLICT (id) DO NOTHING;

INSERT INTO payment_reminders (id, order_id, round, script, channel, status, sent_at, converted_at, response, metadata, created_at)
SELECT ('d6900000-0000-0000-0000-' || lpad(n::text, 12, '0'))::uuid, ('d6800000-0000-0000-0000-' || lpad(n::text, 12, '0'))::uuid,
  CASE WHEN n % 6 = 0 THEN 2 ELSE 1 END, '温馨提醒：您的订单还未支付，活动库存会随时变化，请及时完成支付。', CASE n % 3 WHEN 0 THEN 'bot' WHEN 1 THEN 'app_push' ELSE 'feishu' END,
  CASE n % 5 WHEN 0 THEN 'pending' WHEN 1 THEN 'sent' WHEN 2 THEN 'converted' WHEN 3 THEN 'delivered' ELSE 'failed' END,
  now() - (n * interval '2 hours'), CASE WHEN n % 5 = 2 THEN now() - (n * interval '1 hour') ELSE NULL END,
  CASE WHEN n % 5 = 2 THEN '已完成支付，谢谢提醒' ELSE NULL END, jsonb_build_object('demo', true, 'round_label', '第' || CASE WHEN n % 6 = 0 THEN 2 ELSE 1 END || '轮'), now() - (n * interval '2 hours')
FROM generate_series(1, 20) AS n
ON CONFLICT (id) DO NOTHING;

-- Compliance history provides passed, flagged and blocked examples.
INSERT INTO compliance_audit_logs (id, source_type, source_id, content_snippet, risk_level, matched_rules, decision, reviewed_by, review_notes, correlation_id, created_at)
SELECT ('d7000000-0000-0000-0000-' || lpad(n::text, 12, '0'))::uuid,
  CASE n % 3 WHEN 0 THEN 'knowledge_entry' WHEN 1 THEN 'bot_config' ELSE 'chat_message' END,
  ('d4000000-0000-0000-0000-' || lpad((n % 5 + 1)::text, 12, '0'))::uuid,
  CASE n % 4 WHEN 0 THEN '本产品全网第一，马上见效' WHEN 1 THEN '您好，建议先查看成分表并做局部测试' WHEN 2 THEN '活动最后一天，点击领取优惠' ELSE '您的订单已进入仓库配货流程' END,
  CASE n % 4 WHEN 0 THEN 1 WHEN 1 THEN NULL WHEN 2 THEN 3 ELSE NULL END,
  CASE n % 4 WHEN 0 THEN '[{"rule_text":"绝对化用语","category":"absolute_claim","action":"blocked"}]'::jsonb WHEN 2 THEN '[{"rule_text":"诱导点击","category":"platform_rule","action":"flagged"}]'::jsonb ELSE '[]'::jsonb END,
  CASE n % 4 WHEN 0 THEN 'blocked' WHEN 2 THEN 'flagged' ELSE 'passed' END,
  CASE WHEN n % 4 = 1 THEN NULL ELSE 'a0000000-0000-0000-0000-000000000002'::uuid END,
  CASE WHEN n % 4 = 0 THEN '已拦截并生成工单' WHEN n % 4 = 2 THEN '待运营确认活动上下文' ELSE NULL END,
  'corr-demo-compliance-' || lpad(n::text, 3, '0'), now() - (n * interval '6 hours')
FROM generate_series(1, 48) AS n
ON CONFLICT (id) DO NOTHING;

-- Audit rows tie panel operations back to the same reports/configs/knowledge.
INSERT INTO audit_logs (id, action, user_id, user_name, resource_type, resource_id, detail, correlation_id, created_at)
SELECT ('d7100000-0000-0000-0000-' || lpad(n::text, 12, '0'))::uuid,
  CASE n % 8 WHEN 0 THEN 'evaluate' WHEN 1 THEN 'knowledge_update' WHEN 2 THEN 'bot_config_activate' WHEN 3 THEN 'compliance_warn' WHEN 4 THEN 'work_order_create' WHEN 5 THEN 'llm_call' WHEN 6 THEN 'report_generate' ELSE 'unresolved_questions_create' END,
  CASE WHEN n % 4 = 0 THEN NULL ELSE 'a0000000-0000-0000-0000-000000000002'::uuid END, CASE WHEN n % 4 = 0 THEN 'system' ELSE '李婷' END,
  CASE n % 8 WHEN 0 THEN 'quality_report' WHEN 1 THEN 'knowledge_entry' WHEN 2 THEN 'bot_config' WHEN 3 THEN 'compliance_rules' WHEN 4 THEN 'work_orders' WHEN 5 THEN 'llm' WHEN 6 THEN 'robot_report' ELSE 'unresolved_questions' END,
  CASE n % 8 WHEN 0 THEN 'c1000000-0000-0000-0000-' || lpad((n % 60 + 1)::text, 12, '0') WHEN 1 THEN 'd4000000-0000-0000-0000-' || lpad((n % 5 + 1)::text, 12, '0') WHEN 2 THEN 'd5000000-0000-0000-0000-' || lpad((n % 6 + 1)::text, 12, '0') WHEN 4 THEN 'd6600000-0000-0000-0000-' || lpad((n % 24 + 1)::text, 12, '0') ELSE NULL END,
  jsonb_build_object('demo', true, 'panel', CASE n % 8 WHEN 0 THEN 'qa' WHEN 1 THEN 'knowledge-base' WHEN 2 THEN 'bot-config' WHEN 3 THEN 'compliance' WHEN 4 THEN 'work-orders' WHEN 5 THEN 'llm-metrics' WHEN 6 THEN 'reports' ELSE 'unresolved' END),
  CASE WHEN n % 8 IN (0, 4) THEN 'corr-demo-' || lpad((n % 60 + 1)::text, 3, '0') ELSE 'corr-demo-audit-' || lpad(n::text, 3, '0') END, now() - (n * interval '5 hours')
FROM generate_series(1, 80) AS n
ON CONFLICT (id) DO NOTHING;

-- Daily/weekly/monthly reports cover the data center's three report types.
INSERT INTO robot_reports (id, report_type, period_start, period_end, platform_id, summary_md, metrics, optimization_plan, industry_compare, generated_by, created_at)
SELECT ('d7200000-0000-0000-0000-' || lpad(n::text, 12, '0'))::uuid,
  CASE WHEN n % 3 = 0 THEN 'daily' WHEN n % 3 = 1 THEN 'weekly' ELSE 'monthly' END,
  current_date - CASE WHEN n % 3 = 0 THEN (n / 3) ELSE CASE WHEN n % 3 = 1 THEN (n / 3 + 1) * 7 ELSE (n / 3 + 1) * 30 END END,
  current_date - CASE WHEN n % 3 = 0 THEN (n / 3) ELSE CASE WHEN n % 3 = 1 THEN (n / 3 + 1) * 7 - 6 ELSE (n / 3 + 1) * 30 - 29 END END,
  p.id,
  '# 演示运营报告\n\n本报告关联客服会话、质检报告、知识命中和合规扫描数据。\n\n- 建议优先处理高风险售后与活动规则话术。',
  jsonb_build_object('sessions', 36 + n * 2, 'qa_reports', 28 + n, 'satisfaction_rate', 0.82 + (n % 6) / 100.0, 'conversion_rate', 0.18 + (n % 5) / 100.0, 'critical_count', n % 4),
  '1. 补齐敏感问题知识库；\n2. 对高风险回复启用人工审批；\n3. 每日复核流失原因。',
  jsonb_build_object('industry_avg_conversion', 0.12, 'industry_top_conversion', 0.22, 'sample_period', '2026'), 'demo-seed', now() - (n * interval '1 day')
FROM generate_series(1, 18) AS n
JOIN platforms p ON p.code = (ARRAY['tmall','jd','douyin','pdd','xiaohongshu','vip'])[((n - 1) % 6) + 1]
ON CONFLICT (id) DO NOTHING;

-- Optimization tasks connect inquiry loss, satisfaction, chats and knowledge gaps.
INSERT INTO optimization_tasks (id, source, category, title, description, priority, status, platform_id, related_chat_id, related_knowledge_id, assigned_to, resolution, impact_estimate, created_by, created_at, resolved_at)
SELECT ('d7300000-0000-0000-0000-' || lpad(n::text, 12, '0'))::uuid,
  CASE n % 5 WHEN 0 THEN 'inquiry_loss' WHEN 1 THEN 'satisfaction' WHEN 2 THEN 'chat_inspection' WHEN 3 THEN 'knowledge_gap' ELSE 'campaign' END,
  CASE n % 4 WHEN 0 THEN '转化' WHEN 1 THEN '服务质量' WHEN 2 THEN '物流' ELSE '知识库' END,
  CASE n % 4 WHEN 0 THEN '优化优惠券解释，减少询单流失' WHEN 1 THEN '补充敏感肌售后升级话术' WHEN 2 THEN '完善物流延迟预计时间回复' ELSE '建立防晒和孕期咨询知识条目' END,
  '演示优化任务，来源于面板中的会话、评分、知识命中和活动数据。', CASE n % 4 WHEN 0 THEN 'high' WHEN 1 THEN 'critical' WHEN 2 THEN 'medium' ELSE 'low' END,
  CASE n % 4 WHEN 0 THEN 'open' WHEN 1 THEN 'in_progress' WHEN 2 THEN 'resolved' ELSE 'wont_fix' END, p.id,
  ('b1000000-0000-0000-0000-' || lpad((n % 60 + 1)::text, 12, '0'))::uuid, ('d4000000-0000-0000-0000-' || lpad((n % 5 + 1)::text, 12, '0'))::uuid,
  CASE n % 2 WHEN 0 THEN 'a0000000-0000-0000-0000-000000000003'::uuid ELSE 'a0000000-0000-0000-0000-000000000004'::uuid END,
  CASE WHEN n % 4 >= 2 THEN '已更新对应话术并观察7天' ELSE NULL END, CASE n % 4 WHEN 0 THEN '预计询单转化率 +3%' WHEN 1 THEN '预计差评率 -5%' ELSE '预计命中率 +8%' END,
  'a0000000-0000-0000-0000-000000000002'::uuid, now() - (n * interval '11 hours'), CASE WHEN n % 4 >= 2 THEN now() - (n * interval '5 hours') ELSE NULL END
FROM generate_series(1, 20) AS n
JOIN platforms p ON p.code = (ARRAY['tmall','jd','douyin','pdd','xiaohongshu'])[((n - 1) % 5) + 1]
ON CONFLICT (id) DO NOTHING;

-- Runtime values keep monitoring and panels readable in the local demo.
INSERT INTO system_configs (config_key, config_value, value_type, description, category, updated_by)
VALUES
  ('tmall_auto_throttle_enabled', 'true', 'boolean', '演示：启用自动降级', 'qa', 'a0000000-0000-0000-0000-000000000001'::uuid),
  ('tmall_alert_auto_dispatch', 'false', 'boolean', '演示：告警只展示不外发', 'qa', 'a0000000-0000-0000-0000-000000000001'::uuid),
  ('tmall_shadow_daily_quota', '1000', 'number', '演示：影子回复每日配额', 'platform', 'a0000000-0000-0000-0000-000000000001'::uuid)
ON CONFLICT (config_key) DO UPDATE SET config_value = EXCLUDED.config_value, value_type = EXCLUDED.value_type, description = EXCLUDED.description, category = EXCLUDED.category, updated_by = EXCLUDED.updated_by, updated_at = now();

-- Cross-panel verification: all result sets should be non-zero and key links should be intact.
SELECT 'sessions' AS table_name, count(*) AS demo_rows FROM bot_chat_sessions WHERE correlation_id LIKE 'corr-demo-%'
UNION ALL SELECT 'quality_reports', count(*) FROM quality_reports WHERE correlation_id LIKE 'corr-demo-%'
UNION ALL SELECT 'shadow_replies', count(*) FROM shadow_replies WHERE metadata->>'correlation_id' LIKE 'corr-demo-%'
UNION ALL SELECT 'actual_replies', count(*) FROM actual_replies WHERE metadata->>'correlation_id' LIKE 'corr-demo-%'
UNION ALL SELECT 'unresolved_questions', count(*) FROM unresolved_questions WHERE correlation_id LIKE 'corr-demo-%'
UNION ALL SELECT 'work_orders', count(*) FROM work_orders WHERE metadata->>'demo' = 'true'
UNION ALL SELECT 'pending_orders', count(*) FROM pending_orders WHERE metadata->>'source' = 'demo-cross-panel'
UNION ALL SELECT 'llm_call_logs', count(*) FROM llm_call_logs WHERE id::text LIKE 'd6200000-%'
ORDER BY table_name;

SELECT 'orphan_quality_reports' AS check_name, count(*) AS failures
FROM quality_reports r
LEFT JOIN bot_chat_sessions s ON s.id = r.bot_session_id
WHERE r.correlation_id LIKE 'corr-demo-%' AND s.id IS NULL
UNION ALL
SELECT 'orphan_optimization_tasks', count(*)
FROM optimization_tasks t
LEFT JOIN bot_chat_sessions s ON s.id = t.related_chat_id
WHERE t.id::text LIKE 'd7300000-%' AND s.id IS NULL;

COMMIT;
