-- ============================================================================
-- Migration 014: Production Deploy — Combined Phase 1/2 Schema
-- Run this in Supabase SQL Editor to create all missing tables at once.
-- All tables use IF NOT EXISTS — safe to re-run.
-- ============================================================================

-- ============================================================================
-- PART 1: Compliance Engine (from migration-009)
-- ============================================================================

CREATE TABLE IF NOT EXISTS compliance_rules (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    rule_text       TEXT NOT NULL,
    pattern         TEXT NOT NULL,
    risk_level      INT NOT NULL CHECK (risk_level BETWEEN 1 AND 4),
    category        TEXT NOT NULL CHECK (category IN (
        'advertising_law', 'absolute_claim', 'false_promise',
        'platform_rule', 'competitor_mention', 'tone_violation', 'sensitive_word'
    )),
    action_type     TEXT NOT NULL DEFAULT 'block' CHECK (action_type IN ('block', 'warn', 'flag')),
    description     TEXT,
    exemption_tags  TEXT[] DEFAULT '{}',
    is_active       BOOLEAN NOT NULL DEFAULT true,
    match_count     INT NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_compliance_risk ON compliance_rules(risk_level, is_active);
CREATE INDEX IF NOT EXISTS idx_compliance_category ON compliance_rules(category);

CREATE TABLE IF NOT EXISTS compliance_audit_logs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_type     TEXT NOT NULL CHECK (source_type IN ('knowledge_entry', 'bot_config', 'chat_message')),
    source_id       UUID,
    content_snippet TEXT NOT NULL,
    risk_level      INT,
    matched_rules   JSONB DEFAULT '[]',
    decision        TEXT NOT NULL CHECK (decision IN ('blocked', 'flagged', 'passed')),
    reviewed_by     UUID,
    review_notes    TEXT,
    correlation_id  TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_compliance_logs_source ON compliance_audit_logs(source_type, source_id);
CREATE INDEX IF NOT EXISTS idx_compliance_logs_decision ON compliance_audit_logs(decision, created_at DESC);

-- Seed compliance rules (Advertising Law 34 prohibitions + platform terms)
INSERT INTO compliance_rules (rule_text, pattern, risk_level, category, action_type, description) VALUES
    ('禁止使用国家级/最高级/最佳等绝对化用语', '国家级|最高级|最佳|最优|第一品牌|独一无二|顶级|极品|全网第一|全球第一|全国第一|万能|全能', 1, 'absolute_claim', 'block', '广告法第9条'),
    ('禁止使用国家标志或暗示国家背书', '国宴|国宾|人民大会堂|国务院|中南海|中央军委|国家免检|国家推荐', 1, 'advertising_law', 'block', '广告法第9条'),
    ('禁止声称治愈率或有效率', '治愈率|有效率|根治|药到病除|永不复发|彻底治愈|无任何副作用|100%有效|纯天然无添加', 1, 'advertising_law', 'block', '广告法第16条'),
    ('禁止声称疾病预防/治疗功能（非药品）', '治疗|预防疾病|抗癌|防癌|抑制肿瘤|降血压|降血糖|降血脂|排毒|消炎|抗菌|抑菌', 1, 'advertising_law', 'block', '广告法第17条'),
    ('禁止虚假或引人误解的宣传', '假一赔万|假一赔命|假一赔十亿|绝不|永不|永久有效|终身保修|终身免费|万无一失', 1, 'false_promise', 'block', '广告法第28条'),
    ('禁止损害国家尊严或社会公共利益', '台独|港独|藏独|疆独|法轮功|邪教|分裂', 1, 'advertising_law', 'block', '广告法第9条'),
    ('禁止使用"最"字类极限用语', '(?<![不没无])最[高低大小好坏多少强弱快慢新老远近长短轻重](?!于|的|程度|范围|限度)', 1, 'absolute_claim', 'block', '广告法第9条'),
    ('禁止使用"第一"类排他性用语', '行业第一|销量第一|口碑第一|服务第一|品质第一|市场第一|中国第一|世界第一|全球首发|全国首发|独家首发', 1, 'absolute_claim', 'block', '广告法第9条'),
    ('禁止虚假承诺美容/减肥效果', '立刻见效|瞬间|立即变|马上白|秒变|一喷即白|一抹即白|永不反弹|绝不反弹|躺着瘦|不运动也能瘦', 2, 'false_promise', 'block', '禁止美容/减肥虚假承诺'),
    ('禁止虚假承诺投资理财收益', '稳赚不赔|保本保息|零风险|高收益|年化率|日息|月息|本金保障|收益翻倍|一夜暴富', 2, 'false_promise', 'block', '禁止金融产品收益承诺'),
    ('禁止虚假承诺教育培训效果', '包过|保过|包拿证|包录取|包就业|包分配|一次通过|100%通过|签证必过|政审必过', 2, 'false_promise', 'block', '禁止教育/培训效果承诺'),
    ('禁止贬低其他生产经营者', '比.*好[得多百倍千倍万倍]|远超|秒杀|吊打|完胜|碾压|甩.*几条街|别人.*不行|其他.*不如|只有我们', 2, 'competitor_mention', 'block', '广告法第13条'),
    ('禁止违规比较广告', '比.*便宜|比.*优惠|价格最低|全网最低价|历史最低|跌破底价|亏本|血亏|赔本', 2, 'platform_rule', 'warn', '禁止未经证实的比较广告'),
    ('禁止诱导点击/虚假诱导文案', '点击领取|免费领取|点击抽奖|点击有惊喜|不点就亏了|点开有惊喜|马上抢|疯狂抢购', 3, 'platform_rule', 'warn', '禁止虚假诱导点击'),
    ('禁止在非授权情况下使用平台名义', '天猫认证|京东认证|官方授权(?!书|牌|证|文件)|平台推荐(?!商品|好物)', 3, 'platform_rule', 'warn', '禁止未经授权使用平台名义'),
    ('禁止使用禁用营销词', '最后一天|仅此一天|限时抢购|秒杀(?!活动|专区|价)|清仓|倒闭|破产|跑路|老板哭了|老板疯了|挥泪|跳楼价', 3, 'platform_rule', 'flag', '平台禁用营销用语'),
    ('竞品平台提及检测', '天猫(?!店|店铺|旗舰|官方|客服|平台|商城|超市|国际|优品|会员|积分|优惠|活动|双1|6|年货)|京东(?!店|店铺|旗舰|官方|客服|平台|商城|超市|国际|自营|会员|PLUS|物流|快递|优品|优惠|活动|618|年货)|拼多多(?!店|店铺|官方|客服|平台)|抖音(?!店|店铺|官方|客服|平台|商城|直播)|小红书(?!店|店铺|官方|客服|平台|商城)', 3, 'competitor_mention', 'flag', '提及竞品平台需审核'),
    ('敏感话题检测', '政治|宗教|种族|性别歧视|地域歧视|色情|暴力|赌博|毒品|枪支|弹药', 3, 'sensitive_word', 'block', '禁止敏感话题'),
    ('多处感叹号可能令客户感到压迫', '[！!]{2,}', 4, 'tone_violation', 'flag', '连续感叹号'),
    ('连续问号可能显得不耐烦', '[？?]{3,}', 4, 'tone_violation', 'flag', '连续问号'),
    ('全大写英文可能被视为咆哮', '\b[A-Z]{8,}\b', 4, 'tone_violation', 'flag', '全大写英文'),
    ('建议避免使用粗俗/不文明用语', '傻逼|脑残|废物|笨蛋|蠢|垃圾(?!分类|桶|短信|邮件|文件|清理|广告|信息|数据|内容)', 4, 'tone_violation', 'warn', '粗俗用语')
ON CONFLICT DO NOTHING;

ALTER TABLE compliance_rules ENABLE ROW LEVEL SECURITY;
ALTER TABLE compliance_audit_logs ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN
    CREATE POLICY "Compliance rules readable by all authenticated" ON compliance_rules FOR SELECT USING (true);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
DO $$ BEGIN
    CREATE POLICY "Compliance audit logs readable by all authenticated" ON compliance_audit_logs FOR SELECT USING (true);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ============================================================================
-- PART 2: System Runtime Configuration (from migration-010)
-- ============================================================================

CREATE TABLE IF NOT EXISTS system_configs (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    config_key  TEXT NOT NULL UNIQUE,
    config_value TEXT NOT NULL,
    value_type  TEXT NOT NULL DEFAULT 'string' CHECK (value_type IN ('string', 'number', 'boolean', 'json')),
    description TEXT,
    category    TEXT NOT NULL DEFAULT 'general' CHECK (category IN ('general', 'auto_publish', 'feishu', 'llm', 'compliance', 'qa')),
    updated_by  UUID,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_system_configs_category ON system_configs(category);

INSERT INTO system_configs (config_key, config_value, value_type, description, category) VALUES
    ('auto_publish_threshold', '0.95', 'number', 'Minimum LLM confidence for auto-publish', 'auto_publish'),
    ('auto_publish_max_change_length', '50', 'number', 'Max change description length for auto-publish', 'auto_publish'),
    ('feishu_timeout_ms', '10000', 'number', 'Feishu API timeout (ms)', 'feishu'),
    ('feishu_retry_count', '3', 'number', 'Feishu dispatch retry count', 'feishu'),
    ('feishu_night_window_start', '22', 'number', 'Night window start hour', 'feishu'),
    ('feishu_night_window_end', '8', 'number', 'Night window end hour', 'feishu'),
    ('llm_rate_limit_per_minute', '30', 'number', 'LLM API rate limit', 'llm'),
    ('llm_cache_ttl_hours', '24', 'number', 'LLM cache TTL', 'llm'),
    ('llm_max_retries', '3', 'number', 'LLM retry count', 'llm'),
    ('knowledge_gap_similarity_threshold', '0.15', 'number', 'Knowledge match similarity threshold', 'qa'),
    ('qa_kappa_alert_threshold', '0.4', 'number', 'Cohen Kappa alert threshold', 'qa'),
    ('compliance_auto_block_threshold', '2', 'number', 'Auto-block risk level threshold', 'compliance'),
    ('dedup_window_days', '7', 'number', 'Dedup window in days', 'general'),
    ('payment_reminder_max_rounds', '3', 'number', 'Max reminder rounds per order', 'general'),
    ('payment_reminder_interval_hours', '24', 'number', 'Hours between reminder rounds', 'general'),
    ('payment_reminder_first_delay_minutes', '30', 'number', 'Minutes before first reminder', 'general')
ON CONFLICT (config_key) DO NOTHING;

ALTER TABLE system_configs ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN
    CREATE POLICY "System configs readable by all authenticated" ON system_configs FOR SELECT USING (true);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ============================================================================
-- PART 3: Intent Accuracy Tracking (from migration-011)
-- ============================================================================

DO $$ BEGIN
    CREATE TABLE IF NOT EXISTS intent_accuracy_logs (
        id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        platform_id     UUID,
        period_date     DATE NOT NULL,
        total_recognitions  INT NOT NULL DEFAULT 0,
        correct_recognitions INT NOT NULL DEFAULT 0,
        incorrect_recognitions INT NOT NULL DEFAULT 0,
        accuracy        NUMERIC(5,4) NOT NULL DEFAULT 0,
        coverage_rate   NUMERIC(5,4),
        target_met      BOOLEAN NOT NULL DEFAULT false,
        bad_case_ids    UUID[] DEFAULT '{}',
        notes           TEXT,
        created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
        UNIQUE(platform_id, period_date)
    );
EXCEPTION WHEN duplicate_table THEN NULL;
END $$;

CREATE INDEX IF NOT EXISTS idx_intent_accuracy_date ON intent_accuracy_logs(period_date DESC);
CREATE INDEX IF NOT EXISTS idx_intent_accuracy_target ON intent_accuracy_logs(target_met, period_date DESC);

ALTER TABLE intent_accuracy_logs ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN
    CREATE POLICY "Intent accuracy readable by all authenticated" ON intent_accuracy_logs FOR SELECT USING (true);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ============================================================================
-- PART 4: Work Orders (from migration-012)
-- ============================================================================

CREATE TABLE IF NOT EXISTS work_orders (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title           TEXT NOT NULL,
    description     TEXT NOT NULL,
    source          TEXT NOT NULL CHECK (source IN ('qa_evaluate', 'compliance_block', 'inspection', 'manual', 'cron')),
    source_id       UUID,
    priority        TEXT NOT NULL DEFAULT 'medium' CHECK (priority IN ('low', 'medium', 'high', 'critical')),
    status          TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'in_progress', 'resolved', 'closed')),
    category        TEXT NOT NULL DEFAULT 'general' CHECK (category IN ('general', 'compliance', 'script_fix', 'knowledge_gap', 'customer_complaint', 'system_issue')),
    platform_id     UUID,
    assigned_to     UUID,
    resolved_by     UUID,
    resolution      TEXT,
    feishu_message_id TEXT,
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at     TIMESTAMPTZ,
    closed_at       TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_work_orders_status ON work_orders(status, priority);
CREATE INDEX IF NOT EXISTS idx_work_orders_source ON work_orders(source, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_work_orders_assigned ON work_orders(assigned_to) WHERE status NOT IN ('resolved', 'closed');

CREATE TABLE IF NOT EXISTS work_order_actions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    work_order_id   UUID NOT NULL REFERENCES work_orders(id) ON DELETE CASCADE,
    action          TEXT NOT NULL CHECK (action IN ('created', 'assigned', 'in_progress', 'resolved', 'closed', 'reopened', 'commented')),
    comment         TEXT,
    performed_by    UUID,
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_wo_actions_order ON work_order_actions(work_order_id, created_at DESC);

ALTER TABLE work_orders ENABLE ROW LEVEL SECURITY;
ALTER TABLE work_order_actions ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN
    CREATE POLICY "Work orders readable by all authenticated" ON work_orders FOR SELECT USING (true);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
DO $$ BEGIN
    CREATE POLICY "Work order actions readable by all authenticated" ON work_order_actions FOR SELECT USING (true);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ============================================================================
-- PART 5: Payment Reminders (from migration-013)
-- ============================================================================

CREATE TABLE IF NOT EXISTS pending_orders (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    external_order_id TEXT NOT NULL,
    platform_id     UUID,
    customer_id     TEXT,
    customer_name   TEXT,
    product_name    TEXT,
    order_amount    NUMERIC(10,2),
    order_status    TEXT NOT NULL DEFAULT 'pending_payment' CHECK (order_status IN ('pending_payment', 'reminded', 'paid', 'cancelled', 'expired')),
    created_at_order TIMESTAMPTZ NOT NULL DEFAULT now(),
    expire_at       TIMESTAMPTZ,
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_pending_orders_external ON pending_orders(external_order_id, platform_id);
CREATE INDEX IF NOT EXISTS idx_pending_orders_status ON pending_orders(order_status, expire_at);

CREATE TABLE IF NOT EXISTS payment_reminders (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id        UUID NOT NULL REFERENCES pending_orders(id) ON DELETE CASCADE,
    round           INT NOT NULL DEFAULT 1,
    script          TEXT NOT NULL,
    channel         TEXT NOT NULL DEFAULT 'bot' CHECK (channel IN ('bot', 'sms', 'feishu', 'app_push')),
    status          TEXT NOT NULL DEFAULT 'sent' CHECK (status IN ('pending', 'sent', 'delivered', 'failed', 'converted')),
    sent_at         TIMESTAMPTZ,
    converted_at    TIMESTAMPTZ,
    response        TEXT,
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_reminders_order ON payment_reminders(order_id, round);
CREATE INDEX IF NOT EXISTS idx_reminders_status ON payment_reminders(status, sent_at DESC);

ALTER TABLE pending_orders ENABLE ROW LEVEL SECURITY;
ALTER TABLE payment_reminders ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN
    CREATE POLICY "Pending orders readable by all authenticated" ON pending_orders FOR SELECT USING (true);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
DO $$ BEGIN
    CREATE POLICY "Payment reminders readable by all authenticated" ON payment_reminders FOR SELECT USING (true);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ============================================================================
-- Verify: List all newly created tables
-- ============================================================================
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name IN (
    'compliance_rules', 'compliance_audit_logs',
    'system_configs',
    'intent_accuracy_logs',
    'work_orders', 'work_order_actions',
    'pending_orders', 'payment_reminders'
  )
ORDER BY table_name;
