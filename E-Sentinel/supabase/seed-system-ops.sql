-- ============================================================================
-- 系统运维面板综合种子数据
-- 覆盖: 审计日志 · 坐席绩效 · 合规审核 · 工单管理 · 智能催付 · 效果对比
-- 安全重复运行 (ON CONFLICT DO NOTHING / NOT EXISTS guards)
-- ============================================================================

-- ============================================================================
-- PART 1: 确保坐席 Profiles 存在 (AgentPerformancePanel 数据源)
-- ============================================================================
INSERT INTO profiles (id, name, role, team_id) VALUES
  ('a0000000-0000-0000-0000-000000000003', '王芳', 'agent', 'team_beauty'),
  ('a0000000-0000-0000-0000-000000000004', '赵强', 'agent', 'team_beauty'),
  ('00000000-0000-0000-0000-000000000101', '周敏', 'agent', 'team_beauty'),
  ('00000000-0000-0000-0000-000000000102', '刘洋', 'agent', 'team_beauty'),
  ('00000000-0000-0000-0000-000000000103', '陈丽华', 'agent', 'team_beauty'),
  ('00000000-0000-0000-0000-000000000104', '黄伟', 'agent', 'team_beauty'),
  ('00000000-0000-0000-0000-000000000105', '林小红', 'agent', 'team_beauty'),
  ('00000000-0000-0000-0000-000000000106', '吴建国', 'agent', 'team_beauty')
ON CONFLICT (id) DO NOTHING;

-- Ensure agents have user_roles entries
INSERT INTO user_roles (profile_id, role, assigned_by)
SELECT id, 'agent', 'a0000000-0000-0000-0000-000000000001'
FROM profiles
WHERE role = 'agent'
ON CONFLICT (profile_id) DO NOTHING;

-- ============================================================================
-- PART 2: 坐席质检报告 (AgentPerformancePanel 排行数据)
-- 为每个坐席生成近 30 天、不同分数和风险等级的质检记录
-- ============================================================================
DO $$
DECLARE
    agent_list UUID[] := ARRAY[
        'a0000000-0000-0000-0000-000000000003'::UUID,
        'a0000000-0000-0000-0000-000000000004'::UUID,
        '00000000-0000-0000-0000-000000000101'::UUID,
        '00000000-0000-0000-0000-000000000102'::UUID,
        '00000000-0000-0000-0000-000000000103'::UUID,
        '00000000-0000-0000-0000-000000000104'::UUID,
        '00000000-0000-0000-0000-000000000105'::UUID,
        '00000000-0000-0000-0000-000000000106'::UUID
    ];
    ag_name TEXT[] := ARRAY['王芳','赵强','周敏','刘洋','陈丽华','黄伟','林小红','吴建国'];
    ag_profile JSONB[] := ARRAY[
        '{"scores":[92,88,95,78,91,85,97,89,83,90,94,87,91,86,93,79,88,92,85,90,96,84,89,91],"violations":[{"category":"语气不当","desc":"连续使用感叹号"},{"category":"流程遗漏","desc":"未确认客户身份"}]}'::JSONB,
        '{"scores":[75,82,79,88,71,84,76,83,80,77,85,73,81,79,86,74,82,78,80,76,83,75,79,82],"violations":[{"category":"虚假承诺","desc":"声称产品保证效果"},{"category":"竞品提及","desc":"与其他品牌比较"},{"category":"敏感词","desc":"涉及医疗术语"}]}'::JSONB,
        '{"scores":[96,93,98,91,95,97,92,94,99,90,96,93,97,95,91,98,94,92,96,93,99,95,91,97],"violations":[{"category":"语气不当","desc":"回复过于简短"}]}'::JSONB,
        '{"scores":[88,85,91,84,87,90,83,86,89,82,85,88,84,91,86,83,90,87,85,89,82,86,88,84],"violations":[{"category":"流程遗漏","desc":"未发送满意度调查"}]}'::JSONB,
        '{"scores":[70,68,73,65,71,76,62,69,74,67,72,64,70,75,66,71,63,69,73,68,65,72,70,67],"violations":[{"category":"态度问题","desc":"语气生硬不耐烦"},{"category":"知识错误","desc":"产品成分描述有误"},{"category":"虚假承诺","desc":"声称适合所有肤质"},{"category":"敏感词","desc":"使用禁用营销词"}]}'::JSONB,
        '{"scores":[85,82,88,90,83,86,89,81,87,84,90,83,86,88,82,85,89,84,87,90,83,86,88,85],"violations":[{"category":"竞品提及","desc":"主动推荐其他平台"},{"category":"流程遗漏","desc":"未记录客户诉求"}]}'::JSONB,
        '{"scores":[78,81,75,83,79,76,82,80,77,84,81,78,75,82,79,76,83,80,77,84,81,78,75,82],"violations":[{"category":"语气不当","desc":"使用连续感叹号"},{"category":"知识错误","desc":"会员权益描述有误"}]}'::JSONB,
        '{"scores":[91,94,88,92,95,89,93,90,96,87,92,94,91,88,95,89,93,90,96,87,92,94,91,88],"violations":[{"category":"语气不当","desc":"回复格式不规范"}]}'::JSONB
    ];
    ag_reviewer UUID := 'a0000000-0000-0000-0000-000000000001'::UUID;
    i INT;
    d INT;
    score_val INT;
    risk TEXT;
    base_time TIMESTAMPTZ := now();
BEGIN
    FOR i IN 1..8 LOOP
        FOR d IN 0..23 LOOP
            score_val := (ag_profile[i]->'scores'->d)::INT;
            IF score_val >= 90 THEN risk := 'low';
            ELSIF score_val >= 75 THEN risk := 'medium';
            ELSIF score_val >= 60 THEN risk := 'high';
            ELSE risk := 'critical';
            END IF;

            INSERT INTO quality_reports (
                id, ticket_id, agent_id, reviewer_id, conversation,
                intent, sentiment_score, total_score, violations, risk_level,
                status, correlation_id, review_mode, created_at
            ) VALUES (
                gen_random_uuid(),
                'TKT-' || to_char(base_time - (d || ' days')::INTERVAL, 'YYMMDD') || '-' || lpad(i::TEXT, 3, '0'),
                agent_list[i],
                ag_reviewer,
                '顾客: ' || ag_name[i] || '处理的客服对话记录 #' || d,
                'consultation',
                round((score_val::NUMERIC / 100 * 4 + 1)::NUMERIC, 1),
                score_val,
                CASE WHEN score_val < 85 THEN ag_profile[i]->'violations' ELSE '[]'::JSONB END,
                risk,
                'confirmed',
                'corr-agent-' || i::TEXT || '-' || d::TEXT,
                'active',
                base_time - (d || ' days')::INTERVAL
            )
            ON CONFLICT DO NOTHING;
        END LOOP;
    END LOOP;
END $$;

-- ============================================================================
-- PART 3: 全链路审计日志 (AuditPanel 数据源)
-- 覆盖全部 19 种审计事件类型，时间分散于近 30 天
-- ============================================================================
DO $$
DECLARE
    admin_id UUID := 'a0000000-0000-0000-0000-000000000001'::UUID;
    agent_ids UUID[] := ARRAY['a0000000-0000-0000-0000-000000000003','a0000000-0000-0000-0000-000000000004','00000000-0000-0000-0000-000000000101']::UUID[];
    trace_id TEXT;
    idx INT;
    action_list TEXT[] := ARRAY[
        'login','logout','llm_call','evaluate','overturn',
        'dispatch_feishu','feishu_event_receive','report_generate',
        'knowledge_create','knowledge_update','knowledge_delete','knowledge_publish','knowledge_reject',
        'bot_config_create','bot_config_activate','bot_config_archive','bot_config_publish','bot_config_reject',
        'optimization_task_create','optimization_task_update',
        'campaign_import','rule_create','rule_delete',
        'auto_evaluate_failed','compliance_warn'
    ];
    detail_json JSONB;
    action_now TEXT;
    time_offset INTERVAL;
BEGIN
    FOR idx IN 1..80 LOOP
        action_now := action_list[1 + (idx % array_length(action_list, 1))];
        time_offset := (idx * 180 + (random() * 360)::INT) * '1 minute'::INTERVAL;

        -- Build realistic detail per action type
        CASE action_now
            WHEN 'login' THEN
                detail_json := jsonb_build_object('ip', '192.168.' || (1 + random() * 254)::INT || '.' || (1 + random() * 254)::INT, 'user_agent', 'Mozilla/5.0');
            WHEN 'logout' THEN
                detail_json := jsonb_build_object('session_duration_min', (5 + random() * 480)::INT);
            WHEN 'llm_call' THEN
                detail_json := jsonb_build_object(
                    'model', (CASE WHEN random() > 0.5 THEN 'moonshot-v1-8k' ELSE 'kimi-latest' END),
                    'prompt_type', (CASE WHEN random() > 0.6 THEN 'evaluate' WHEN random() > 0.3 THEN 'generate_knowledge' ELSE 'compliance_check' END),
                    'latency_ms', (800 + random() * 15000)::INT,
                    'cached', random() > 0.7,
                    'tokens', (200 + random() * 3000)::INT,
                    'was_fallback', random() > 0.9
                );
            WHEN 'evaluate' THEN
                detail_json := jsonb_build_object(
                    'score', (60 + random() * 40)::INT,
                    'risk_level', (CASE WHEN random() > 0.8 THEN 'critical' WHEN random() > 0.5 THEN 'high' ELSE 'medium' END),
                    'violations_count', (0 + random() * 8)::INT,
                    'review_mode', (CASE WHEN random() > 0.5 THEN 'auto' ELSE 'manual' END)
                );
            WHEN 'dispatch_feishu' THEN
                detail_json := jsonb_build_object(
                    'route', (CASE WHEN random() > 0.6 THEN 'direct_message' WHEN random() > 0.3 THEN 'group_webhook' ELSE 'global_webhook' END),
                    'target', (CASE WHEN random() > 0.5 THEN 'team_beauty' ELSE 'agent_wangfang' END),
                    'priority', (CASE WHEN random() > 0.8 THEN 'critical' ELSE 'normal' END)
                );
            WHEN 'feishu_event_receive' THEN
                detail_json := jsonb_build_object(
                    'event_type', (CASE WHEN random() > 0.5 THEN 'im.message.receive_v1' ELSE 'im.message.reaction.created_v1' END),
                    'chat_id', 'oc_' || md5(random()::TEXT),
                    'sender_open_id', 'ou_' || md5(random()::TEXT)
                );
            WHEN 'report_generate' THEN
                detail_json := jsonb_build_object('report_type', (CASE WHEN random() > 0.5 THEN 'daily' WHEN random() > 0.3 THEN 'weekly' ELSE 'agent_performance' END));
            WHEN 'knowledge_create','knowledge_update' THEN
                detail_json := jsonb_build_object('title', (CASE
                    WHEN random() > 0.8 THEN '美白精华液成分说明'
                    WHEN random() > 0.6 THEN '防晒霜SPF值科普'
                    WHEN random() > 0.4 THEN '退换货政策FAQ'
                    WHEN random() > 0.2 THEN '敏感肌护肤指南'
                    ELSE '618活动规则解读'
                END));
            WHEN 'knowledge_delete' THEN
                detail_json := jsonb_build_object('title', '过期话术模板-2024版', 'reason', '内容已过时');
            WHEN 'bot_config_create','bot_config_activate' THEN
                detail_json := jsonb_build_object('config_key', (CASE
                    WHEN random() > 0.7 THEN 'skincare_consult'
                    WHEN random() > 0.4 THEN 'order_inquiry_reply'
                    ELSE 'after_sale_return'
                END));
            WHEN 'bot_config_archive' THEN
                detail_json := jsonb_build_object('config_key', 'old_promo_script_Q1', 'reason', '促销活动已结束');
            WHEN 'campaign_import' THEN
                detail_json := jsonb_build_object('count', (10 + random() * 200)::INT, 'source', 'tmall_campaign_api');
            WHEN 'rule_create' THEN
                detail_json := jsonb_build_object('rule_text', '绝对化用语检测增强', 'risk_level', 1);
            WHEN 'rule_delete' THEN
                detail_json := jsonb_build_object('rule_text', '旧版营销词检测', 'reason', '已合并至新规则');
            WHEN 'overturn' THEN
                detail_json := jsonb_build_object('original_score', (60 + random() * 30)::INT, 'new_risk', 'medium', 'reason', '该对话属于正常产品咨询，不构成违规');
            WHEN 'auto_evaluate_failed' THEN
                detail_json := jsonb_build_object('error', (CASE WHEN random() > 0.5 THEN 'LLM timeout after 30s' ELSE 'JSON parse error in evaluation result' END), 'conversation_preview', '顾客: 你好，请问这款产品适合油性皮肤吗...');
            WHEN 'compliance_warn' THEN
                detail_json := jsonb_build_object('resource_type', 'knowledge_entries', 'action', (CASE WHEN random() > 0.5 THEN 'blocked' ELSE 'flagged' END), 'risk_level', (1 + random() * 3)::INT);
            ELSE
                detail_json := jsonb_build_object('note', '系统自动操作');
        END CASE;

        trace_id := 'trace-' || to_char(now() - time_offset, 'YYMMDD') || '-' || lpad(idx::TEXT, 4, '0');

        INSERT INTO audit_logs (
            id, action, user_id, user_name, resource_type, resource_id,
            detail, correlation_id, created_at
        ) VALUES (
            gen_random_uuid(),
            action_now,
            CASE WHEN action_now IN ('login','logout','llm_call','evaluate','rule_create','rule_delete')
                 THEN agent_ids[1 + (idx % 3)]
                 WHEN action_now IN ('knowledge_create','knowledge_update','knowledge_delete','knowledge_publish','knowledge_reject',
                                     'bot_config_create','bot_config_activate','bot_config_archive','bot_config_publish','bot_config_reject',
                                     'report_generate','campaign_import','overturn','compliance_warn')
                 THEN admin_id
                 ELSE NULL
            END,
            CASE WHEN action_now IN ('login','logout','llm_call','evaluate','rule_create','rule_delete')
                 THEN (SELECT name FROM profiles WHERE id = agent_ids[1 + (idx % 3)])
                 WHEN action_now IN ('knowledge_create','knowledge_update','knowledge_delete','knowledge_publish','knowledge_reject',
                                     'bot_config_create','bot_config_activate','bot_config_archive','bot_config_publish','bot_config_reject',
                                     'report_generate','campaign_import','overturn','compliance_warn')
                 THEN (SELECT name FROM profiles WHERE id = admin_id)
                 ELSE NULL
            END,
            CASE
                WHEN action_now LIKE 'knowledge_%' THEN 'knowledge_entries'
                WHEN action_now LIKE 'bot_config_%' THEN 'bot_configs'
                WHEN action_now IN ('evaluate','auto_evaluate_failed') THEN 'quality_reports'
                WHEN action_now = 'llm_call' THEN 'llm'
                WHEN action_now = 'dispatch_feishu' THEN 'feishu_dispatch'
                WHEN action_now = 'feishu_event_receive' THEN 'feishu_event'
                WHEN action_now = 'report_generate' THEN 'quality_reports'
                WHEN action_now IN ('rule_create','rule_delete') THEN 'compliance_rules'
                WHEN action_now IN ('login','logout') THEN 'auth'
                WHEN action_now = 'overturn' THEN 'quality_reports'
                WHEN action_now = 'campaign_import' THEN 'campaigns'
                WHEN action_now = 'compliance_warn' THEN 'compliance_rules'
                ELSE 'system'
            END,
            gen_random_uuid(),
            detail_json,
            trace_id,
            now() - time_offset
        );
    END LOOP;
END $$;

-- ============================================================================
-- PART 4: 合规审计日志 (CompliancePanel 历史记录)
-- 模拟 30 次合规扫描事件
-- ============================================================================
INSERT INTO compliance_audit_logs (source_type, source_id, content_snippet, risk_level, matched_rules, decision, correlation_id, created_at)
SELECT
    (CASE WHEN n % 3 = 0 THEN 'knowledge_entry' WHEN n % 3 = 1 THEN 'bot_config' ELSE 'chat_message' END),
    gen_random_uuid(),
    (CASE
        WHEN n % 8 = 0 THEN '我们产品是最顶级的，效果秒杀市面所有其他品牌'
        WHEN n % 8 = 1 THEN '这款面霜含有天然植物精华，有效改善肌肤'
        WHEN n % 8 = 2 THEN '国家免检产品，100%有效，永不复发'
        WHEN n % 8 = 3 THEN '天猫认证正品，比其他平台便宜很多'
        WHEN n % 8 = 4 THEN '本产品由国家级实验室研发，品质有保障'
        WHEN n % 8 = 5 THEN '亲爱的顾客您好，感谢您的咨询，请问有什么可以帮您？'
        WHEN n % 8 = 6 THEN '活动最后一天！！不买就亏了！！赶紧下单！！'
        WHEN n % 8 = 7 THEN '建议您搭配我们的精华液一起使用效果更好哦'
    END),
    (CASE
        WHEN n % 8 = 0 THEN 1 WHEN n % 8 = 1 THEN 4
        WHEN n % 8 = 2 THEN 1 WHEN n % 8 = 3 THEN 2
        WHEN n % 8 = 4 THEN 1 WHEN n % 8 = 5 THEN NULL
        WHEN n % 8 = 6 THEN 3 WHEN n % 8 = 7 THEN NULL
    END),
    (CASE
        WHEN n % 8 = 0 THEN '[{"rule":"绝对化用语","risk":1}]'::JSONB
        WHEN n % 8 = 1 THEN '[]'::JSONB
        WHEN n % 8 = 2 THEN '[{"rule":"禁止承诺有效率","risk":1},{"rule":"禁止使用国家标志","risk":1}]'::JSONB
        WHEN n % 8 = 3 THEN '[{"rule":"禁止未经授权使用平台名义","risk":3},{"rule":"禁止违规比较广告","risk":2}]'::JSONB
        WHEN n % 8 = 4 THEN '[{"rule":"禁止使用国家标志","risk":1}]'::JSONB
        WHEN n % 8 = 5 THEN '[]'::JSONB
        WHEN n % 8 = 6 THEN '[{"rule":"连续感叹号","risk":4},{"rule":"禁止使用禁用营销词","risk":3}]'::JSONB
        WHEN n % 8 = 7 THEN '[]'::JSONB
    END),
    (CASE
        WHEN n % 8 = 0 THEN 'blocked' WHEN n % 8 = 1 THEN 'passed'
        WHEN n % 8 = 2 THEN 'blocked' WHEN n % 8 = 3 THEN 'flagged'
        WHEN n % 8 = 4 THEN 'blocked' WHEN n % 8 = 5 THEN 'passed'
        WHEN n % 8 = 6 THEN 'flagged' WHEN n % 8 = 7 THEN 'passed'
    END),
    'compliance-' || lpad(n::TEXT, 3, '0'),
    now() - (n * 12 || ' hours')::INTERVAL
FROM generate_series(1, 30) AS n
WHERE NOT EXISTS (SELECT 1 FROM compliance_audit_logs LIMIT 1);

-- ============================================================================
-- PART 5: 工单 (WorkOrderPanel)
-- 补充更多真实工单场景
-- ============================================================================
INSERT INTO work_orders (title, description, source, priority, status, category, metadata, created_at)
VALUES
  ('抖音直播间话术违规 — 质检红灯',
   '直播中主播使用了"全网最低价""最有效美白"等声称，合规引擎标记致命级违规。需审核话术脚本并修改。',
   'compliance_block', 'critical', 'open', 'compliance',
   '{"platform":"douyin","rule_ids":["absolute_claim_001","false_promise_005"]}',
   now() - '2 hours'::INTERVAL),

  ('客户投诉退货流程超过72小时未处理',
   '客户购买护肤套装后因过敏申请退货，系统流程卡在审核环节超过3天，客户在微博公开投诉。',
   'manual', 'critical', 'open', 'customer_complaint',
   '{"order_id":"ORD-20260515-889","platform":"tmall","escalated":true}',
   now() - '5 hours'::INTERVAL),

  ('小红书平台回复话术缺少产品备案号',
   '质检发现小红书平台的自动回复中提及"美白""祛斑"等特殊功效但未引用备案号/批准文号格式，不符合药监局要求。',
   'inspection', 'high', 'open', 'compliance',
   '{"platform":"xiaohongshu","config_key":"whitening_faq"}',
   now() - '1 day'::INTERVAL),

  ('拼多多店铺话术模板批量过期',
   'Q1促销活动已结束，但拼多多平台的欢迎语和催付话术仍包含"女神节特惠"等过期内容，需要批量归档并生成新话术。',
   'cron', 'high', 'in_progress', 'script_fix',
   '{"platform":"pdd","expired_configs":4,"campaign":"Q1_womens_day"}',
   now() - '1 day'::INTERVAL),

  ('坐席王芳客户满意度连续下降',
   '绩效系统检测到坐席王芳近两周的好评率从92%降至78%，可能存在工作状态问题，需团队负责人约谈。',
   'qa_evaluate', 'medium', 'in_progress', 'general',
   '{"agent_id":"a0000000-0000-0000-0000-000000000003","trend":"declining","period":"14d"}',
   now() - '2 days'::INTERVAL),

  ('知识库"防晒"类目覆盖不足',
   '连续5天检测到高频率未命中问题："物理防晒和化学防晒区别""孕妇可用防晒霜吗""SPF值怎么选"。建议创建知识条目。',
   'cron', 'medium', 'open', 'knowledge_gap',
   '{"cluster":"sun_protection","gap_count":23,"priority_score":0.87}',
   now() - '2 days'::INTERVAL),

  ('618大促活动话术上线审批',
   '运营团队提交了618活动话术模板，包括限时折扣、满减优惠、赠品策略等内容，需要合规扫描后发布到全部8个平台。',
   'manual', 'medium', 'in_progress', 'script_fix',
   '{"campaign":"618","platforms":["tmall","jd","pdd","douyin"],"config_count":12}',
   now() - '3 days'::INTERVAL),

  ('飞书告警通道降级测试',
   '凌晨3点检测到飞书个人Webhook超时，系统按四级降级路由切换至群聊Webhook成功。需确认夜间告警策略是否正常。',
   'manual', 'low', 'resolved', 'system_issue',
   '{"route":"direct->group","downgrade_time_ms":3200,"night_window":true}',
   now() - '4 days'::INTERVAL),

  ('自动质检模型对美妆类对话误判率高',
   '运营反馈美妆行业的专业术语（如烟酰胺、A醇、刷酸等）经常被误判为敏感词或违规内容，需要添加行业豁免词表。',
   'manual', 'medium', 'open', 'system_issue',
   '{"industry":"beauty","false_positive_rate":0.12,"affected_terms":["烟酰胺","刷酸","A醇","果酸"]}',
   now() - '5 days'::INTERVAL),

  ('批量导入竞品分析话术',
   '市场部完成竞品调研，需要批量导入50+条竞品对比话术，内容涵盖产品成分、价格、功效等多维度对比。',
   'manual', 'low', 'resolved', 'general',
   '{"batch_size":52,"imported_by":"a0000000-0000-0000-0000-000000000002"}',
   now() - '7 days'::INTERVAL)

ON CONFLICT DO NOTHING;

-- ============================================================================
-- PART 6: 智能催付订单补充 (PaymentReminderPanel)
-- ============================================================================
INSERT INTO pending_orders (external_order_id, customer_name, product_name, order_amount, order_status, created_at_order, expire_at) VALUES
  ('ORD-20260517-101', '郑*怡', '雅诗兰黛小棕瓶精华 50ml', 890.00, 'pending_payment', '2026-05-17 10:15:00+08', '2026-05-18 10:15:00+08'),
  ('ORD-20260517-102', '林*豪', '戴森吹风机 Supersonic HD15', 3190.00, 'pending_payment', '2026-05-17 14:30:00+08', '2026-05-18 14:30:00+08'),
  ('ORD-20260517-103', '杨*婷', '兰芝睡眠面膜 70ml*2', 185.00, 'reminded', '2026-05-17 09:00:00+08', '2026-05-19 09:00:00+08'),
  ('ORD-20260518-104', '马*军', '华为Mate 70 Pro 12+512G', 6499.00, 'pending_payment', '2026-05-18 08:45:00+08', '2026-05-19 08:45:00+08'),
  ('ORD-20260518-105', '胡*', '完美日记小细跟口红礼盒 6支', 299.00, 'pending_payment', '2026-05-18 11:20:00+08', '2026-05-19 11:20:00+08'),
  ('ORD-20260516-106', '何*雯', '科沃斯扫拖机器人 X5 PRO', 4599.00, 'paid', '2026-05-16 15:00:00+08', '2026-05-17 15:00:00+08'),
  ('ORD-20260516-107', '高*', '花西子空气蜜粉 01号色', 159.00, 'paid', '2026-05-16 20:30:00+08', '2026-05-17 20:30:00+08'),
  ('ORD-20260515-108', '罗*华', '飞利浦电动牙刷 HX9352', 699.00, 'reminded', '2026-05-15 13:00:00+08', '2026-05-17 13:00:00+08'),
  ('ORD-20260514-109', '梁*欣', 'OLAY 抗糖小白瓶 30ml', 239.00, 'expired', '2026-05-14 16:00:00+08', '2026-05-15 16:00:00+08'),
  ('ORD-20260513-110', '谢*锋', '北面冲锋衣 1996经典款', 1899.00, 'cancelled', '2026-05-13 10:00:00+08', '2026-05-14 10:00:00+08'),
  ('ORD-20260518-111', '潘*玲', '芙丽芳丝净润洗面奶 100g*3', 297.00, 'pending_payment', '2026-05-18 13:10:00+08', '2026-05-19 13:10:00+08'),
  ('ORD-20260518-112', '范*伟', '联想ThinkPad X1 Carbon i7', 9999.00, 'pending_payment', '2026-05-18 14:55:00+08', '2026-05-19 14:55:00+08')
ON CONFLICT DO NOTHING;

-- Add payment reminders (only for orders that don't have them)
DO $$
BEGIN
    INSERT INTO payment_reminders (order_id, round, script, channel, status, sent_at)
    SELECT o.id, 1,
        '亲爱的' || COALESCE(o.customer_name, '顾客') || '，您选购的' || COALESCE(o.product_name, '商品') || '还未支付哦～库存有限，请尽快完成支付',
        'bot', 'sent', o.created_at_order + '30 minutes'::INTERVAL
    FROM pending_orders o
    WHERE o.order_status IN ('reminded', 'paid')
      AND NOT EXISTS (SELECT 1 FROM payment_reminders r WHERE r.order_id = o.id);

    INSERT INTO payment_reminders (order_id, round, script, channel, status, sent_at, converted_at)
    SELECT o.id, 1,
        '亲爱的' || COALESCE(o.customer_name, '顾客') || '，您的订单已为您保留，现在支付即享优先发货～',
        'bot', 'converted', o.created_at_order + '30 minutes'::INTERVAL, o.created_at_order + '2 hours'::INTERVAL
    FROM pending_orders o
    WHERE o.order_status = 'paid'
      AND NOT EXISTS (SELECT 1 FROM payment_reminders r WHERE r.order_id = o.id AND r.status = 'converted');
END $$;

-- ============================================================================
-- PART 7: Effect Metrics (EffectComparePanel — 发布前后对比)
-- 安全执行：仅在对应列存在时更新
-- ============================================================================
DO $$
BEGIN
    -- bot_configs.effect_metrics (from migration-007)
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'bot_configs' AND column_name = 'effect_metrics'
    ) THEN
        EXECUTE '
            UPDATE bot_configs
            SET effect_metrics = jsonb_build_object(
                ''pre_publish_satisfaction'', round((0.82 + random() * 0.1)::NUMERIC, 3),
                ''pre_publish_handled_rate'', round((0.75 + random() * 0.15)::NUMERIC, 3),
                ''pre_publish_avg_response_ms'', (1500 + random() * 3000)::INT,
                ''snapshot_date'', to_char(now() - ''14 days''::INTERVAL, ''YYYY-MM-DD'')
            )
            WHERE status = ''active''
              AND effect_metrics IS NULL
              AND effect_metrics = ''{}''::jsonb';
    END IF;

    -- knowledge_entries.effect_metrics (from migration-008)
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'knowledge_entries' AND column_name = 'effect_metrics'
    ) THEN
        EXECUTE '
            UPDATE knowledge_entries
            SET effect_metrics = jsonb_build_object(
                ''pre_update_hit_rate'', round((0.6 + random() * 0.25)::NUMERIC, 3),
                ''pre_update_avg_relevance'', round((0.7 + random() * 0.2)::NUMERIC, 3),
                ''gap_reduction_pct'', round((0.15 + random() * 0.4)::NUMERIC, 3),
                ''snapshot_date'', to_char(now() - ''14 days''::INTERVAL, ''YYYY-MM-DD'')
            )
            WHERE status = ''published''
              AND effect_metrics IS NULL
              AND effect_metrics = ''{}''::jsonb';
    END IF;
END $$;

-- ============================================================================
-- PART 8: 意图准确率日志补充 (IntentAccuracyPanel)
-- 确保近 30 天每天有数据
-- ============================================================================
INSERT INTO intent_accuracy_logs (period_date, total_recognitions, correct_recognitions, incorrect_recognitions, accuracy, target_met)
SELECT
    current_date - (n || ' days')::INTERVAL,
    200 + floor(random() * 300)::INT,
    (200 + floor(random() * 300)::INT) - (1 + floor(random() * 8))::INT,
    (1 + floor(random() * 8))::INT,
    CASE
        WHEN n <= 3 THEN 0.997 + random() * 0.002
        WHEN n <= 10 THEN 0.994 + random() * 0.004
        WHEN n <= 20 THEN 0.992 + random() * 0.005
        ELSE 0.989 + random() * 0.008
    END,
    CASE WHEN n <= 8 THEN true ELSE random() > 0.25 END
FROM generate_series(0, 29) AS n
WHERE NOT EXISTS (
    SELECT 1 FROM intent_accuracy_logs WHERE period_date = current_date - (n || ' days')::INTERVAL
);

-- ============================================================================
-- 验证：输出所有表行数
-- ============================================================================
SELECT 'profiles (agents)' AS tbl, count(*) AS rows FROM profiles WHERE role = 'agent'
UNION ALL SELECT 'quality_reports', count(*) FROM quality_reports
UNION ALL SELECT 'audit_logs', count(*) FROM audit_logs
UNION ALL SELECT 'compliance_rules', count(*) FROM compliance_rules
UNION ALL SELECT 'compliance_audit_logs', count(*) FROM compliance_audit_logs
UNION ALL SELECT 'work_orders', count(*) FROM work_orders
UNION ALL SELECT 'pending_orders', count(*) FROM pending_orders
UNION ALL SELECT 'payment_reminders', count(*) FROM payment_reminders
UNION ALL SELECT 'intent_accuracy_logs', count(*) FROM intent_accuracy_logs
UNION ALL SELECT 'system_configs', count(*) FROM system_configs
ORDER BY tbl;
