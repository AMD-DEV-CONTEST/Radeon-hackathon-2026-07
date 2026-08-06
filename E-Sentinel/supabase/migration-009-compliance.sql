-- ============================================================================
-- Migration 009: Compliance Engine — 4-level risk prevention system
-- Covers: Advertising Law 34 prohibitions + e-commerce platform banned terms
-- Risk levels: fatal (1) / high (2) / medium (3) / low (4)
-- ============================================================================

-- 1. Compliance rules table
CREATE TABLE IF NOT EXISTS compliance_rules (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    rule_text       TEXT NOT NULL,
    pattern         TEXT NOT NULL,              -- regex pattern for matching
    risk_level      INT NOT NULL CHECK (risk_level BETWEEN 1 AND 4),
    category        TEXT NOT NULL CHECK (category IN (
        'advertising_law',     -- 广告法禁令
        'absolute_claim',      -- 绝对化用语
        'false_promise',       -- 虚假承诺
        'platform_rule',       -- 平台规则
        'competitor_mention',  -- 竞品提及
        'tone_violation',      -- 语气不当
        'sensitive_word'       -- 通用敏感词
    )),
    action_type     TEXT NOT NULL DEFAULT 'block' CHECK (action_type IN ('block', 'warn', 'flag')),
    description     TEXT,
    exemption_tags  TEXT[] DEFAULT '{}',        -- 豁免场景标签
    is_active       BOOLEAN NOT NULL DEFAULT true,
    match_count     INT NOT NULL DEFAULT 0,     -- times this rule matched
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_compliance_risk ON compliance_rules(risk_level, is_active);
CREATE INDEX IF NOT EXISTS idx_compliance_category ON compliance_rules(category);

-- 2. Compliance audit log
CREATE TABLE IF NOT EXISTS compliance_audit_logs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_type     TEXT NOT NULL CHECK (source_type IN ('knowledge_entry', 'bot_config', 'chat_message')),
    source_id       UUID,
    content_snippet TEXT NOT NULL,              -- first 200 chars of checked content
    risk_level      INT,                       -- highest risk level found
    matched_rules   JSONB DEFAULT '[]',         -- [{rule_id, rule_text, category, action}]
    decision        TEXT NOT NULL CHECK (decision IN ('blocked', 'flagged', 'passed')),
    reviewed_by     UUID REFERENCES profiles(id),
    review_notes    TEXT,
    correlation_id  TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_compliance_logs_source ON compliance_audit_logs(source_type, source_id);
CREATE INDEX IF NOT EXISTS idx_compliance_logs_decision ON compliance_audit_logs(decision, created_at DESC);

-- 3. Seed data: Advertising Law + e-commerce forbidden terms

-- === FATAL (risk_level=1): Advertising Law absolute prohibitions ===
INSERT INTO compliance_rules (rule_text, pattern, risk_level, category, action_type, description) VALUES
    -- Art.9: 使用或变相使用国旗、国徽等
    ('禁止使用国家级/最高级/最佳等绝对化用语', '国家级|最高级|最佳|最优|第一品牌|独一无二|顶级|极品|全网第一|全球第一|全国第一|万能|全能', 1, 'absolute_claim', 'block', '广告法第9条：禁止使用绝对化用语'),
    ('禁止使用国家标志或暗示国家背书', '国宴|国宾|人民大会堂|国务院|中南海|中央军委|国家免检|国家推荐', 1, 'advertising_law', 'block', '广告法第9条：禁止使用或变相使用国家机关名义'),
    ('禁止声称治愈率或有效率', '治愈率|有效率|根治|药到病除|永不复发|彻底治愈|无任何副作用|100%有效|纯天然无添加', 1, 'advertising_law', 'block', '广告法第16条：禁止含有表示功效的安全性的断言或保证'),
    ('禁止声称疾病预防/治疗功能（非药品）', '治疗|预防疾病|抗癌|防癌|抑制肿瘤|降血压|降血糖|降血脂|排毒|消炎|抗菌|抑菌', 1, 'advertising_law', 'block', '广告法第17条：除药品/医疗器械外禁止声称疾病治疗功能'),
    ('禁止虚假或引人误解的宣传', '假一赔万|假一赔命|假一赔十亿|绝不|永不|永久有效|终身保修|终身免费|万无一失', 1, 'false_promise', 'block', '广告法第28条：禁止虚假或引人误解的宣传'),
    ('禁止损害国家尊严或社会公共利益', '台独|港独|藏独|疆独|法轮功|邪教|分裂', 1, 'advertising_law', 'block', '广告法第9条：禁止危害国家统一和社会稳定'),
    ('禁止使用"最"字类极限用语', '(?<![不没无])最[高低大小好坏多少强弱快慢新老远近长短轻重](?!于|的|程度|范围|限度)', 1, 'absolute_claim', 'block', '广告法第9条：禁止使用极限用语（含"最X"结构）'),
    ('禁止使用"第一"类排他性用语', '行业第一|销量第一|口碑第一|服务第一|品质第一|市场第一|中国第一|世界第一|全球首发|全国首发|独家首发', 1, 'absolute_claim', 'block', '广告法第9条：禁止排他性绝对化表述')
ON CONFLICT DO NOTHING;

-- === HIGH (risk_level=2): False promises & misleading claims ===
INSERT INTO compliance_rules (rule_text, pattern, risk_level, category, action_type, description) VALUES
    ('禁止虚假承诺美容/减肥效果', '立刻见效|瞬间|立即变|马上白|秒变|一喷即白|一抹即白|永不反弹|绝不反弹|躺着瘦|不运动也能瘦', 2, 'false_promise', 'block', '禁止对美容/减肥等效果进行虚假承诺'),
    ('禁止虚假承诺投资理财收益', '稳赚不赔|保本保息|零风险|高收益|年化率|日息|月息|本金保障|收益翻倍|一夜暴富', 2, 'false_promise', 'block', '禁止对金融产品收益进行承诺性宣传'),
    ('禁止虚假承诺教育培训效果', '包过|保过|包拿证|包录取|包就业|包分配|一次通过|100%通过|签证必过|政审必过', 2, 'false_promise', 'block', '禁止对教育/培训效果做出明示或暗示的保证性承诺'),
    ('禁止贬低其他生产经营者', '比.*好[得多百倍千倍万倍]|远超|秒杀|吊打|完胜|碾压|甩.*几条街|别人.*不行|其他.*不如|只有我们', 2, 'competitor_mention', 'block', '广告法第13条：禁止贬低其他生产经营者的商品或服务'),
    ('禁止违规比较广告', '比.*便宜|比.*优惠|价格最低|全网最低价|历史最低|跌破底价|亏本|血亏|赔本', 2, 'platform_rule', 'warn', '各平台禁止未经证实的比较广告和最低价宣称')
ON CONFLICT DO NOTHING;

-- === MEDIUM (risk_level=3): Platform-specific & sensitive content ===
INSERT INTO compliance_rules (rule_text, pattern, risk_level, category, action_type, description) VALUES
    ('禁止诱导点击/虚假诱导文案', '点击领取|免费领取|点击抽奖|点击有惊喜|不点就亏了|点开有惊喜|马上抢|疯狂抢购', 3, 'platform_rule', 'warn', '各平台禁止虚假诱导点击行为'),
    ('禁止在非授权情况下使用平台名义', '天猫认证|京东认证|官方授权(?!书|牌|证|文件)|平台推荐(?!商品|好物)', 3, 'platform_rule', 'warn', '禁止未经授权使用平台名义进行宣传'),
    ('禁止使用禁用营销词', '最后一天|仅此一天|限时抢购|秒杀(?!活动|专区|价)|清仓|倒闭|破产|跑路|老板哭了|老板疯了|挥泪|跳楼价', 3, 'platform_rule', 'flag', '平台管控禁用营销用语'),
    ('竞品平台提及检测', '天猫(?!店|店铺|旗舰|官方|客服|平台|商城|超市|国际|优品|会员|积分|优惠|活动|双1|6|年货)|京东(?!店|店铺|旗舰|官方|客服|平台|商城|超市|国际|自营|会员|PLUS|物流|快递|优品|优惠|活动|618|年货)|拼多多(?!店|店铺|官方|客服|平台)|抖音(?!店|店铺|官方|客服|平台|商城|直播)|小红书(?!店|店铺|官方|客服|平台|商城)', 3, 'competitor_mention', 'flag', '提及竞品平台需上下文审核'),
    ('敏感话题检测', '政治|宗教|种族|性别歧视|地域歧视|色情|暴力|赌博|毒品|枪支|弹药', 3, 'sensitive_word', 'block', '禁止涉及敏感话题和政治相关内容')
ON CONFLICT DO NOTHING;

-- === LOW (risk_level=4): Tone & style suggestions ===
INSERT INTO compliance_rules (rule_text, pattern, risk_level, category, action_type, description) VALUES
    ('多处感叹号可能令客户感到压迫', '[！!]{2,}', 4, 'tone_violation', 'flag', '多个感叹号连续使用会让客户感到压迫感'),
    ('连续问号可能显得不耐烦', '[？?]{3,}', 4, 'tone_violation', 'flag', '连续问号可能传达不耐烦的情绪'),
    ('全大写英文可能被视为咆哮', '\\b[A-Z]{8,}\\b', 4, 'tone_violation', 'flag', '全大写英文在客服沟通中可能被视为不友好'),
    ('建议避免使用粗俗/不文明用语', '傻逼|脑残|废物|笨蛋|蠢|垃圾(?!分类|桶|短信|邮件|文件|清理|广告|信息|数据|内容)', 4, 'tone_violation', 'warn', '客服沟通中应避免粗俗用语')
ON CONFLICT DO NOTHING;

-- 4. RLS
ALTER TABLE compliance_rules ENABLE ROW LEVEL SECURITY;
ALTER TABLE compliance_audit_logs ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Compliance rules readable by all authenticated" ON compliance_rules FOR SELECT USING (true);
CREATE POLICY "Compliance audit logs readable by all authenticated" ON compliance_audit_logs FOR SELECT USING (true);
