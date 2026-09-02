-- ============================================================================
-- Seed Data for Phase 1/2 Panels
-- Run AFTER migration-014 in Supabase SQL Editor.
-- ============================================================================

-- 1. Seed Work Orders (for 工单管理)
INSERT INTO work_orders (title, description, source, priority, status, category, metadata) VALUES
    ('客服态度恶劣需整改 — 质检红灯', '质检报告发现客服在对话中使用粗俗用语，客户情绪升至5级。对话内容涉及退货纠纷。需立即约谈并整改。', 'qa_evaluate', 'critical', 'open', 'customer_complaint', '{"report_id": "seed-001", "score": 45}'),
    ('退款政策话术疑似违规', '自动话术"不满意全额退"被合规引擎标记为虚假承诺嫌疑（风险等级2）。需人工审核修改措辞。', 'compliance_block', 'high', 'open', 'compliance', '{"rule_id": "false_promise", "risk": 2}'),
    ('物流查询流程缺少快递100+平台适配', '质检发现抖音和拼多多平台的物流查询话术未做平台适配，导致客户在正确输入订单号后仍转人工。', 'inspection', 'medium', 'in_progress', 'script_fix', '{"platforms": ["pdd", "douyin"]}'),
    ('孕妇可用护肤品知识条目缺失', '连续3天出现"孕妇可以用吗"类问题未命中知识库。需要审核并创建相关条目。', 'cron', 'medium', 'open', 'knowledge_gap', '{"gap_count": 12, "cluster": "孕产护肤"}'),
    ('系统自动催付功能未按预期触发', 'payment_reminders cron 任务报错：pending_orders 关联查询超时。需优化查询或增加索引。', 'manual', 'high', 'in_progress', 'system_issue', '{"error": "timeout", "endpoint": "/api/qa/payment-reminders"}'),
    ('批量导入商品材质说明更新', '运营团队需要一次性更新50个商品的材质说明话术。需要批量导入接口支持。', 'manual', 'low', 'resolved', 'general', '{"batch_size": 50, "status": "done"}'),
    ('化妆品备案号缺失导致合规拦截', '某护肤品牌在话术中声称"医学级"但未提供备案号，合规引擎拦截。需补充备案号或修改措辞。', 'compliance_block', 'critical', 'open', 'compliance', '{"brand": "sample-brand", "term": "医学级"}')
ON CONFLICT DO NOTHING;

-- Add some work order actions for the in_progress orders
INSERT INTO work_order_actions (work_order_id, action, comment, metadata)
SELECT id, 'created', '系统自动生成', '{"auto_generated": true}'::jsonb
FROM work_orders
WHERE NOT EXISTS (SELECT 1 FROM work_order_actions WHERE work_order_actions.work_order_id = work_orders.id);

-- 2. Seed Pending Orders (for 智能催付)
INSERT INTO pending_orders (external_order_id, customer_name, product_name, order_amount, order_status, created_at_order, expire_at) VALUES
    ('ORD-20260501-001', '张*丽', '兰蔻持妆粉底液 PO-01 30ml', 459.00, 'pending_payment', '2026-05-15 14:30:00+08', '2026-05-16 14:30:00+08'),
    ('ORD-20260502-002', '王*明', 'Apple AirPods Pro 2 无线耳机', 1388.00, 'pending_payment', '2026-05-16 09:15:00+08', '2026-05-17 09:15:00+08'),
    ('ORD-20260502-003', '李*芳', '三只松鼠坚果大礼包 1888g', 128.00, 'reminded', '2026-05-15 20:00:00+08', '2026-05-16 20:00:00+08'),
    ('ORD-20260503-004', '赵*', '海尔冰箱 BCD-500 智能变频', 3299.00, 'pending_payment', '2026-05-16 11:00:00+08', '2026-05-18 11:00:00+08'),
    ('ORD-20260503-005', '刘*婷', 'SK-II 神仙水 230ml 限量版', 1590.00, 'reminded', '2026-05-16 15:45:00+08', '2026-05-17 15:45:00+08'),
    ('ORD-20260501-006', '陈*', '小米13 Ultra 12+256G 黑色', 4999.00, 'paid', '2026-05-15 10:00:00+08', '2026-05-16 10:00:00+08'),
    ('ORD-20260501-007', '孙*华', '耐克 Air Max 270 男款跑步鞋 42码', 739.00, 'paid', '2026-05-15 12:30:00+08', '2026-05-16 12:30:00+08'),
    ('ORD-20260430-008', '周*杰', '戴森 V15 无线吸尘器 2024款', 4399.00, 'expired', '2026-04-30 16:00:00+08', '2026-05-01 16:00:00+08'),
    ('ORD-20260428-009', '吴*', '海底捞火锅底料 麻辣 200g*5', 49.90, 'cancelled', '2026-04-28 10:00:00+08', '2026-04-29 10:00:00+08'),
    ('ORD-20260503-010', '黄*强', 'PS5 主机 光驱版 国行', 3499.00, 'pending_payment', '2026-05-16 18:30:00+08', '2026-05-17 18:30:00+08')
ON CONFLICT DO NOTHING;

-- Add sample reminders for reminded/paid orders
INSERT INTO payment_reminders (order_id, round, script, channel, status, sent_at)
SELECT id, 1, '亲爱的顾客，您的订单已生成，请及时完成支付哦～', 'bot', 'sent', created_at_order + interval '30 minutes'
FROM pending_orders WHERE order_status IN ('reminded', 'paid')
ON CONFLICT DO NOTHING;

INSERT INTO payment_reminders (order_id, round, script, channel, status, sent_at, converted_at)
SELECT id, 1, '亲爱的顾客，您的订单已生成，请及时完成支付哦～', 'bot', 'converted', created_at_order + interval '30 minutes', created_at_order + interval '2 hours'
FROM pending_orders WHERE order_status = 'paid'
ON CONFLICT DO NOTHING;

-- 3. Seed Intent Accuracy Logs (for 意图准确率)
-- Generates 30 days of trending data
INSERT INTO intent_accuracy_logs (period_date, total_recognitions, correct_recognitions, incorrect_recognitions, accuracy, target_met)
SELECT
    today::date - (n || ' days')::interval,
    150 + floor(random() * 200)::int,
    (150 + floor(random() * 200)::int) - floor(random() * 5)::int,
    floor(random() * 5)::int,
    CASE
        WHEN n <= 5 THEN 0.996 + random() * 0.003  -- recent: high accuracy
        WHEN n <= 15 THEN 0.993 + random() * 0.005 -- mid: around alert line
        ELSE 0.988 + random() * 0.010              -- older: some dips
    END,
    CASE WHEN n <= 5 THEN true ELSE random() > 0.3 END
FROM generate_series(0, 29) AS n,
     (SELECT current_date AS today) AS d
WHERE NOT EXISTS (SELECT 1 FROM intent_accuracy_logs WHERE period_date = today::date - (n || ' days')::interval);

-- 4. Verify seed data
SELECT 'work_orders' AS table_name, count(*) AS rows FROM work_orders
UNION ALL SELECT 'work_order_actions', count(*) FROM work_order_actions
UNION ALL SELECT 'pending_orders', count(*) FROM pending_orders
UNION ALL SELECT 'payment_reminders', count(*) FROM payment_reminders
UNION ALL SELECT 'intent_accuracy_logs', count(*) FROM intent_accuracy_logs
UNION ALL SELECT 'system_configs', count(*) FROM system_configs
UNION ALL SELECT 'compliance_rules', count(*) FROM compliance_rules
ORDER BY table_name;
