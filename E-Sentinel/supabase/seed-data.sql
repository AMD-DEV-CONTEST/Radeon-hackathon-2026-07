-- ============================================================
-- E-Sentinel Seed Data — 50+ realistic records
-- Beauty/Skincare brand on multi-platform e-commerce
-- Uses subqueries for platform FK lookups (no hardcoded UUIDs)
-- ============================================================

-- ── Profiles (users) ────────────────────────────────────────
INSERT INTO profiles (id, name, role, team_id) VALUES
  ('a0000000-0000-0000-0000-000000000001', '张明', 'admin', 'team_beauty'),
  ('a0000000-0000-0000-0000-000000000002', '李婷', 'team_lead', 'team_beauty'),
  ('a0000000-0000-0000-0000-000000000003', '王芳', 'agent', 'team_beauty'),
  ('a0000000-0000-0000-0000-000000000004', '赵强', 'agent', 'team_beauty'),
  ('a0000000-0000-0000-0000-000000000005', '陈雪', 'team_lead', 'team_beauty')
ON CONFLICT (id) DO NOTHING;

-- ── User Roles ──────────────────────────────────────────────
INSERT INTO user_roles (profile_id, role, assigned_by) VALUES
  ('a0000000-0000-0000-0000-000000000001', 'admin', NULL),
  ('a0000000-0000-0000-0000-000000000002', 'operator', 'a0000000-0000-0000-0000-000000000001'),
  ('a0000000-0000-0000-0000-000000000003', 'agent', 'a0000000-0000-0000-0000-000000000001'),
  ('a0000000-0000-0000-0000-000000000004', 'agent', 'a0000000-0000-0000-0000-000000000001'),
  ('a0000000-0000-0000-0000-000000000005', 'operator', 'a0000000-0000-0000-0000-000000000001')
ON CONFLICT (profile_id) DO NOTHING;

-- ── Bot Chat Sessions (30 sessions across 5 platforms) ──────
-- Session 1: tmall pre-sale — converted
INSERT INTO bot_chat_sessions (id, platform_id, session_type, external_session_id, customer_id, bot_handled, is_inquiry, inquiry_result, sentiment_score, satisfaction, total_messages, first_response_ms, resolution_ms, tags, conversation, correlation_id, created_at)
SELECT 'b0000000-0000-0000-0000-000000000001', p.id, 'pre_sale', 'tmall-sess-001', 'cust_zhang', true, true, 'converted', 4, 'good', 8, 1200, 180000, ARRAY['美白','精华液'],
  '顾客: 你好，我想了解一下你们新出的美白精华液
机器人: 您好！感谢咨询～我们的焕白精华液含有烟酰胺+传明酸双重美白成分，适合所有肤质
顾客: 我是敏感肌，能用吗？
机器人: 完全可以用哦！我们产品通过了敏感肌测试，不含酒精、香精，pH值温和。建议第一次使用先在耳后测试
顾客: 价格呢？现在有活动吗
机器人: 618活动价179元/30ml，买2件享8折，还赠同款小样3支。现在是预售期最划算的时候
顾客: 好，那我买两瓶试试
机器人: 已为您生成订单链接，请点击查看～祝您肌肤越来越亮白✨',
  'corr-sess-001', NOW() - INTERVAL '28 days'
FROM platforms p WHERE p.code = 'tmall'
ON CONFLICT (id) DO NOTHING;

-- Session 2: tmall post-sale — allergy complaint (bad)
INSERT INTO bot_chat_sessions (id, platform_id, session_type, external_session_id, customer_id, bot_handled, is_inquiry, inquiry_result, sentiment_score, satisfaction, total_messages, first_response_ms, resolution_ms, tags, conversation, correlation_id, created_at)
SELECT 'b0000000-0000-0000-0000-000000000002', p.id, 'post_sale', 'tmall-sess-002', 'cust_li', true, false, NULL, 2, 'bad', 12, 1500, 360000, ARRAY['退货','过敏'],
  '顾客: 我用了你们的美白精华之后脸上发红发痒
机器人: 非常抱歉给您带来不好的体验！请问您使用前有做过敏测试吗？
顾客: 没有，你们说敏感肌可以用我就直接用了
机器人: 理解您的心情。我们的产品确实经过敏感肌测试，但每个人的肤质不同。建议您先停止使用，我们会为您办理退货退款
顾客: 我要退货，而且你们要承担运费
机器人: 退货是支持的，但运费需要您承担哦。我们的退换货政策是不影响二次销售的情况下支持7天无理由退货
顾客: 但是是你们的产品导致我过敏的！这不公平
机器人: 我理解您的诉求，但运费问题我这边确实无法处理，需要您联系人工客服
顾客: 真麻烦，算了退货吧',
  'corr-sess-002', NOW() - INTERVAL '27 days'
FROM platforms p WHERE p.code = 'tmall'
ON CONFLICT (id) DO NOTHING;

-- Session 3: jd pre-sale — converted
INSERT INTO bot_chat_sessions (id, platform_id, session_type, external_session_id, customer_id, bot_handled, is_inquiry, inquiry_result, sentiment_score, satisfaction, total_messages, first_response_ms, resolution_ms, tags, conversation, correlation_id, created_at)
SELECT 'b0000000-0000-0000-0000-000000000003', p.id, 'pre_sale', 'jd-sess-001', 'cust_wang', true, true, 'converted', 5, 'good', 6, 800, 120000, ARRAY['面霜','保湿'],
  '顾客: 推荐一款适合干皮的面霜
机器人: 推荐我们的玻尿酸保湿面霜！含有三重玻尿酸+神经酰胺，深层补水锁水，干皮救星
顾客: 和某蔻比怎么样？
机器人: 我们的面霜保湿时长实测达到48小时，成分表更干净，价格只要某蔻的三分之一哦
顾客: 油皮能用吗
机器人: 这款是针对干皮和混干的，油皮建议选择我们的清爽乳液系列～需要我推荐吗？
顾客: 行，那就先买这个面霜',
  'corr-sess-003', NOW() - INTERVAL '26 days'
FROM platforms p WHERE p.code = 'jd'
ON CONFLICT (id) DO NOTHING;

-- Session 4: douyin pre-sale — lost
INSERT INTO bot_chat_sessions (id, platform_id, session_type, external_session_id, customer_id, bot_handled, is_inquiry, inquiry_result, sentiment_score, satisfaction, total_messages, first_response_ms, resolution_ms, tags, conversation, correlation_id, created_at)
SELECT 'b0000000-0000-0000-0000-000000000004', p.id, 'pre_sale', 'douyin-sess-001', 'cust_zhao', true, true, 'lost', 3, 'neutral', 10, 2000, NULL, ARRAY['口红','试色'],
  '顾客: 你们那个豆沙色口红还有货吗
机器人: 有的呢～我们的丝绒哑光唇釉#301豆沙色现货充足。需要看试色图吗？
顾客: 发来看看
机器人: [图片]这是我们模特上唇效果，黄皮也显白哦
顾客: 有没有更偏粉的
机器人: 那推荐#302蜜桃豆沙，比#301更粉嫩一点
顾客: 我不敢盲买，有没有试用装
机器人: 抱歉目前没有试用装活动呢。不过我们支持7天无理由退货
顾客: 那算了我再看看吧',
  'corr-sess-004', NOW() - INTERVAL '25 days'
FROM platforms p WHERE p.code = 'douyin'
ON CONFLICT (id) DO NOTHING;

-- Session 5: tmall post-sale — wrong item complaint (bad)
INSERT INTO bot_chat_sessions (id, platform_id, session_type, external_session_id, customer_id, bot_handled, is_inquiry, inquiry_result, sentiment_score, satisfaction, total_messages, first_response_ms, resolution_ms, tags, conversation, correlation_id, created_at)
SELECT 'b0000000-0000-0000-0000-000000000005', p.id, 'post_sale', 'tmall-sess-003', 'cust_chen', true, false, NULL, 1, 'bad', 9, 1000, 600000, ARRAY['投诉','发错货'],
  '顾客: 我买的面霜你们给我发成乳液了！
机器人: 非常抱歉！请提供您的订单号，我帮您核实
顾客: TM202405061234
机器人: 已查到您的订单。确实是我们仓库发错了，非常抱歉！我们马上为您补发正确的面霜，乳液无需退回
顾客: 那我要等多久？
机器人: 补发预计3-5个工作日送达。作为补偿，我们会为您发放30元优惠券
顾客: 30块？耽误我这么久就给30？
机器人: 这个...我这边只能给到30元优惠券的权限，更多补偿需要联系人工客服
顾客: 你们就是这么对待老客户的？',
  'corr-sess-005', NOW() - INTERVAL '24 days'
FROM platforms p WHERE p.code = 'tmall'
ON CONFLICT (id) DO NOTHING;

-- Session 6: pdd pre-sale — converted
INSERT INTO bot_chat_sessions (id, platform_id, session_type, external_session_id, customer_id, bot_handled, is_inquiry, inquiry_result, sentiment_score, satisfaction, total_messages, first_response_ms, resolution_ms, tags, conversation, correlation_id, created_at)
SELECT 'b0000000-0000-0000-0000-000000000006', p.id, 'pre_sale', 'pdd-sess-001', 'cust_sun', true, true, 'converted', 4, 'good', 5, 600, 90000, ARRAY['防晒','夏天'],
  '顾客: 有清爽不油腻的防晒吗
机器人: 推荐我们的水感防晒乳！SPF50+ PA+++，轻薄乳液质地，上脸不油腻不泛白
顾客: 多少钱
机器人: 日常价89元/50ml，现在拼团价只要59元！
顾客: 买！',
  'corr-sess-006', NOW() - INTERVAL '23 days'
FROM platforms p WHERE p.code = 'pdd'
ON CONFLICT (id) DO NOTHING;

-- Session 7: jd post-sale — logistics delay (neutral)
INSERT INTO bot_chat_sessions (id, platform_id, session_type, external_session_id, customer_id, bot_handled, is_inquiry, inquiry_result, sentiment_score, satisfaction, total_messages, first_response_ms, resolution_ms, tags, conversation, correlation_id, created_at)
SELECT 'b0000000-0000-0000-0000-000000000007', p.id, 'post_sale', 'jd-sess-002', 'cust_zhou', true, false, NULL, 3, 'neutral', 7, 1300, 240000, ARRAY['物流','催单'],
  '顾客: 我的订单三天了还没发货
机器人: 您好，我帮您查询一下。您的订单JD202405078901，目前显示正在仓库配货中
顾客: 为什么这么慢？
机器人: 近期618大促订单量较大，仓库处理时间有所延长，请您谅解
顾客: 什么时候能发？
机器人: 预计明天内会更新物流信息。我们会为您标注加急处理
顾客: 行吧，希望别让我失望',
  'corr-sess-007', NOW() - INTERVAL '22 days'
FROM platforms p WHERE p.code = 'jd'
ON CONFLICT (id) DO NOTHING;

-- Session 8: douyin pre-sale — sensitive skin kit (good, transferred to human for complex query)
INSERT INTO bot_chat_sessions (id, platform_id, session_type, external_session_id, customer_id, bot_handled, transfer_reason, is_inquiry, inquiry_result, sentiment_score, satisfaction, total_messages, first_response_ms, resolution_ms, tags, conversation, correlation_id, created_at)
SELECT 'b0000000-0000-0000-0000-000000000008', p.id, 'pre_sale', 'douyin-sess-002', 'cust_wu', false, 'complex_product_query', true, 'converted', 4, 'good', 14, 1800, 420000, ARRAY['套装','敏感肌','成分'],
  '顾客: 我是敏感肌，想找一套完整的护肤流程
机器人: 了解！我们为敏感肌专门研发了舒缓修护系列，包括氨基酸洁面+舒缓水+修护精华+屏障面霜
顾客: 成分安全吗？有没有致痘成分
机器人: 全系列不含酒精、香精、色素、矿物油，通过皮肤科测试。这是完整的成分表 [链接]
顾客: 我是学生党，预算有限
机器人: 可以试试我们的入门套装，洁面+水+面霜三件套，学生价199元
顾客: 会闷痘吗
机器人: 不会的呢，全线无致痘成分。修护精华含有积雪草提取物，反而有助于痘肌修护
顾客: 好吧我下单试试',
  'corr-sess-008', NOW() - INTERVAL '21 days'
FROM platforms p WHERE p.code = 'douyin'
ON CONFLICT (id) DO NOTHING;

-- Session 9: tmall pre-sale — eye cream (good)
INSERT INTO bot_chat_sessions (id, platform_id, session_type, external_session_id, customer_id, bot_handled, is_inquiry, inquiry_result, sentiment_score, satisfaction, total_messages, first_response_ms, resolution_ms, tags, conversation, correlation_id, created_at)
SELECT 'b0000000-0000-0000-0000-000000000009', p.id, 'pre_sale', 'tmall-sess-004', 'cust_huang', true, true, 'converted', 5, 'good', 4, 700, 60000, ARRAY['眼霜','抗老'],
  '顾客: 25岁开始用眼霜早不早
机器人: 不早哦！眼部是最先显老的部位，25岁是开始抗初老的最佳时机
顾客: 推荐一下
机器人: 我们的多肽紧致眼霜，含六胜肽+咖啡因，淡化细纹、消浮肿，一涂化水不厚重
顾客: 下单了',
  'corr-sess-009', NOW() - INTERVAL '20 days'
FROM platforms p WHERE p.code = 'tmall'
ON CONFLICT (id) DO NOTHING;

-- Session 10: pdd post-sale — authenticity doubt (bad)
INSERT INTO bot_chat_sessions (id, platform_id, session_type, external_session_id, customer_id, bot_handled, is_inquiry, inquiry_result, sentiment_score, satisfaction, total_messages, first_response_ms, resolution_ms, tags, conversation, correlation_id, created_at)
SELECT 'b0000000-0000-0000-0000-000000000010', p.id, 'post_sale', 'pdd-sess-002', 'cust_liu', true, false, NULL, 2, 'bad', 8, 1400, 480000, ARRAY['质量问题','假货质疑'],
  '顾客: 你们这个洗面奶和我之前在专柜买的味道不一样
机器人: 您好，我们是品牌官方旗舰店，所有产品均为正品，请您放心
顾客: 但是闻起来就是不一样，而且泡沫也少
机器人: 不同批次的产品在气味上可能有轻微差异，这是因为我们使用的是天然植物提取成分。泡沫多少也与水质和用量有关
顾客: 你们是不是真假混卖？
机器人: 绝对没有这种情况！我们是品牌直营店，有品牌授权书。如果您不满意，可以申请退货
顾客: 退货多麻烦，我就想知道是不是正品
机器人: 我们可以提供该批次的质检报告，需要的话请留邮箱
顾客: 算了你们也证明不了什么',
  'corr-sess-010', NOW() - INTERVAL '19 days'
FROM platforms p WHERE p.code = 'pdd'
ON CONFLICT (id) DO NOTHING;

-- Session 11: jd pre-sale — mask (good)
INSERT INTO bot_chat_sessions (id, platform_id, session_type, external_session_id, customer_id, bot_handled, is_inquiry, inquiry_result, sentiment_score, satisfaction, total_messages, first_response_ms, resolution_ms, tags, conversation, correlation_id, created_at)
SELECT 'b0000000-0000-0000-0000-000000000011', p.id, 'pre_sale', 'jd-sess-003', 'cust_yang', true, true, 'converted', 5, 'good', 7, 900, 150000, ARRAY['面膜','补水'],
  '顾客: 补水面膜有推荐吗
机器人: 推荐我们的玻尿酸补水面膜！每片含25ml精华液，超薄天丝膜布，敷完水润一整天
顾客: 天天敷可以吗
机器人: 建议每周2-3次即可，过度水合反而不好哦
顾客: 好的，买两盒',
  'corr-sess-011', NOW() - INTERVAL '18 days'
FROM platforms p WHERE p.code = 'jd'
ON CONFLICT (id) DO NOTHING;

-- Session 12: douyin post-sale — timeout escalation (bad, critical complaint)
INSERT INTO bot_chat_sessions (id, platform_id, session_type, external_session_id, customer_id, bot_handled, transfer_reason, is_inquiry, inquiry_result, sentiment_score, satisfaction, total_messages, first_response_ms, resolution_ms, tags, conversation, correlation_id, created_at)
SELECT 'b0000000-0000-0000-0000-000000000012', p.id, 'post_sale', 'douyin-sess-003', 'cust_gao', false, 'escalation_timeout', false, NULL, 1, 'bad', 15, 3000, 720000, ARRAY['投诉','客服态度'],
  '顾客: 我昨天问的问题你们还没回复
机器人: 您好，请问是什么问题呢？
顾客: 我说了我的爽肤水漏液了！你们说会处理，然后就没下文了
机器人: 非常抱歉！我没有查到之前的记录。能否重新描述一下问题？
顾客: 你们内部不沟通的吗？？每次都要我重新说一遍
机器人: 实在抱歉给您带来不便。请提供订单号和漏液照片，我马上处理
顾客: 已经发过了！DY202405102345，照片昨天就发了
机器人: 感谢您的耐心，我查到记录了一个破损补发申请，目前状态是审核中
顾客: 审核要多久？
机器人: 一般1-3个工作日
顾客: 三天了还在审核，你们效率太低了
机器人: 我帮您催促进度，预计今天内会有结果',
  'corr-sess-012', NOW() - INTERVAL '17 days'
FROM platforms p WHERE p.code = 'douyin'
ON CONFLICT (id) DO NOTHING;

-- Session 13: tmall pre-sale — price comparison (lost)
INSERT INTO bot_chat_sessions (id, platform_id, session_type, external_session_id, customer_id, bot_handled, is_inquiry, inquiry_result, sentiment_score, satisfaction, total_messages, first_response_ms, resolution_ms, tags, conversation, correlation_id, created_at)
SELECT 'b0000000-0000-0000-0000-000000000013', p.id, 'pre_sale', 'tmall-sess-005', 'cust_ma', true, true, 'lost', 3, 'neutral', 9, 1100, NULL, ARRAY['价格','比价'],
  '顾客: 你们这个和某品牌比哪个好
机器人: 我们的产品采用的是进口原料，配方经过3年研发，效果有临床数据支撑
顾客: 但是某品牌便宜很多啊
机器人: 我们的性价比其实更高，因为有效成分浓度是同类产品的2倍
顾客: 有没有优惠券
机器人: 目前店铺券满300减30，还可叠加平台跨店满减
顾客: 还是有点贵，我再看看',
  'corr-sess-013', NOW() - INTERVAL '16 days'
FROM platforms p WHERE p.code = 'tmall'
ON CONFLICT (id) DO NOTHING;

-- Session 14: pdd pre-sale — oil control cleanser (good)
INSERT INTO bot_chat_sessions (id, platform_id, session_type, external_session_id, customer_id, bot_handled, is_inquiry, inquiry_result, sentiment_score, satisfaction, total_messages, first_response_ms, resolution_ms, tags, conversation, correlation_id, created_at)
SELECT 'b0000000-0000-0000-0000-000000000014', p.id, 'pre_sale', 'pdd-sess-003', 'cust_hu', true, true, 'converted', 4, 'good', 5, 500, 80000, ARRAY['洁面','油皮'],
  '顾客: 油皮用什么洁面好
机器人: 推荐我们的水杨酸控油洁面！含水杨酸+茶树精油，深层清洁毛孔，控油不紧绷
顾客: 会不会太刺激
机器人: 水杨酸浓度0.5%，温和去角质，日常使用完全OK
顾客: 好，买一支试试',
  'corr-sess-014', NOW() - INTERVAL '15 days'
FROM platforms p WHERE p.code = 'pdd'
ON CONFLICT (id) DO NOTHING;

-- Session 15: jd post-sale — shade exchange (neutral)
INSERT INTO bot_chat_sessions (id, platform_id, session_type, external_session_id, customer_id, bot_handled, is_inquiry, inquiry_result, sentiment_score, satisfaction, total_messages, first_response_ms, resolution_ms, tags, conversation, correlation_id, created_at)
SELECT 'b0000000-0000-0000-0000-000000000015', p.id, 'post_sale', 'jd-sess-004', 'cust_lin', true, false, NULL, 3, 'neutral', 8, 1200, 300000, ARRAY['换货','色号'],
  '顾客: 买的粉底液颜色太白了
机器人: 好的，请问您购买的是哪个色号？
顾客: 自然色，但是我涂上像刷墙
机器人: 理解！自然色可能对您来说偏白了。我们可以为您更换为健康色，这个色号更适合亚洲肤色
顾客: 怎么换？
机器人: 您申请换货即可，不需退货，我们直接为您寄出健康色
顾客: 运费呢
机器人: 换货运费由我们承担，您无需支付任何费用
顾客: 行',
  'corr-sess-015', NOW() - INTERVAL '14 days'
FROM platforms p WHERE p.code = 'jd'
ON CONFLICT (id) DO NOTHING;

-- Session 16: douyin pre-sale — cleansing oil (good)
INSERT INTO bot_chat_sessions (id, platform_id, session_type, external_session_id, customer_id, bot_handled, is_inquiry, inquiry_result, sentiment_score, satisfaction, total_messages, first_response_ms, resolution_ms, tags, conversation, correlation_id, created_at)
SELECT 'b0000000-0000-0000-0000-000000000016', p.id, 'pre_sale', 'douyin-sess-004', 'cust_xu', true, false, NULL, 4, 'good', 6, 900, 100000, ARRAY['卸妆','敏感肌'],
  '顾客: 有没有敏感肌能用的卸妆油
机器人: 推荐我们的氨基酸卸妆油！以氨基酸表活为基底，温和不刺激，眼唇都可以用
顾客: 能卸防水睫毛膏吗
机器人: 可以哦，湿手湿脸也能用，乳化速度快，不会糊眼睛
顾客: 那我买一瓶',
  'corr-sess-016', NOW() - INTERVAL '13 days'
FROM platforms p WHERE p.code = 'douyin'
ON CONFLICT (id) DO NOTHING;

-- Session 17: tmall post-sale — medical complaint (bad, severe)
INSERT INTO bot_chat_sessions (id, platform_id, session_type, external_session_id, customer_id, bot_handled, transfer_reason, is_inquiry, inquiry_result, sentiment_score, satisfaction, total_messages, first_response_ms, resolution_ms, tags, conversation, correlation_id, created_at)
SELECT 'b0000000-0000-0000-0000-000000000017', p.id, 'post_sale', 'tmall-sess-006', 'cust_he', false, 'sensitive_issue', false, NULL, 1, 'bad', 12, 2000, 840000, ARRAY['严重过敏','医疗纠纷','投诉'],
  '顾客: 用完你们产品我脸上起了大片红疹！已经去医院了
机器人: 非常非常抱歉！您的情况我们已经记录。请问方便提供医生的诊断证明吗？
顾客: 医生说是接触性皮炎，开了药膏。你们要负责
机器人: 我们一定会负责到底。请您保存好医疗记录和费用凭证，我们会安排专人跟进
顾客: 谁来跟进？不要又是机器人回复
机器人: 这个case会转接给我们的客诉专员，48小时内会给您电话沟通。同时我们会承担合理的医疗费用
顾客: 希望你们说到做到',
  'corr-sess-017', NOW() - INTERVAL '12 days'
FROM platforms p WHERE p.code = 'tmall'
ON CONFLICT (id) DO NOTHING;

-- Session 18: pdd pre-sale — lip balm (good)
INSERT INTO bot_chat_sessions (id, platform_id, session_type, external_session_id, customer_id, bot_handled, is_inquiry, inquiry_result, sentiment_score, satisfaction, total_messages, first_response_ms, resolution_ms, tags, conversation, correlation_id, created_at)
SELECT 'b0000000-0000-0000-0000-000000000018', p.id, 'pre_sale', 'pdd-sess-004', 'cust_deng', true, true, 'converted', 5, 'good', 4, 400, 45000, ARRAY['唇膏','秋冬'],
  '顾客: 嘴唇干裂用什么
机器人: 推荐我们的蜂蜜修护唇膏！含蜂蜡+维生素E，深层滋润，一抹化水不粘腻
顾客: 多少钱
机器人: 29元/支，买2送1
顾客: 下单2支',
  'corr-sess-018', NOW() - INTERVAL '11 days'
FROM platforms p WHERE p.code = 'pdd'
ON CONFLICT (id) DO NOTHING;

-- Session 19: xiaohongshu pre-sale — social referral (good)
INSERT INTO bot_chat_sessions (id, platform_id, session_type, external_session_id, customer_id, bot_handled, is_inquiry, inquiry_result, sentiment_score, satisfaction, total_messages, first_response_ms, resolution_ms, tags, conversation, correlation_id, created_at)
SELECT 'b0000000-0000-0000-0000-000000000019', p.id, 'pre_sale', 'xiaohongshu-sess-001', 'cust_feng', true, true, 'converted', 5, 'good', 7, 1000, 180000, ARRAY['种草','推荐'],
  '顾客: 小红书种草了你们家的精华，适合混油皮吗
机器人: 适合的！我们的焕白精华是清爽水润质地，混油皮用不会觉得油腻。小红书上的好评可以参考我们官方账号
顾客: 和博主说的一样好用吗
机器人: 保证正品！而且我们有30天无忧退换服务，不满意随时退
顾客: 好，那我也跟风入一瓶',
  'corr-sess-019', NOW() - INTERVAL '10 days'
FROM platforms p WHERE p.code = 'xiaohongshu'
ON CONFLICT (id) DO NOTHING;

-- Session 20: jd post-sale — refund progress (neutral)
INSERT INTO bot_chat_sessions (id, platform_id, session_type, external_session_id, customer_id, bot_handled, is_inquiry, inquiry_result, sentiment_score, satisfaction, total_messages, first_response_ms, resolution_ms, tags, conversation, correlation_id, created_at)
SELECT 'b0000000-0000-0000-0000-000000000020', p.id, 'post_sale', 'jd-sess-005', 'cust_cao', true, false, NULL, 3, 'neutral', 6, 1100, 200000, ARRAY['退款进度'],
  '顾客: 我的退款什么时候到账
机器人: 您好，退款一般在我们收到退货后3-5个工作日到账
顾客: 快递显示你们已经签收3天了
机器人: 我帮您查一下。您的退款单号RF202405123456，目前状态是仓库已签收、质检中
顾客: 那还要多久
机器人: 质检通过后会立即发起退款，预计1-2个工作日内到账
顾客: 好吧',
  'corr-sess-020', NOW() - INTERVAL '9 days'
FROM platforms p WHERE p.code = 'jd'
ON CONFLICT (id) DO NOTHING;

-- Session 21: douyin pre-sale — gift for mom (pending)
INSERT INTO bot_chat_sessions (id, platform_id, session_type, external_session_id, customer_id, bot_handled, is_inquiry, inquiry_result, sentiment_score, satisfaction, total_messages, first_response_ms, resolution_ms, tags, conversation, correlation_id, created_at)
SELECT 'b0000000-0000-0000-0000-000000000021', p.id, 'pre_sale', 'douyin-sess-005', 'cust_wei', true, true, 'pending', 4, 'good', 8, 1200, NULL, ARRAY['礼物','送人'],
  '顾客: 想给妈妈买一套护肤品，推荐一下
机器人: 孝顺！推荐我们的逆龄紧致套装，含精华水+精华液+面霜，适合40+熟龄肌，提拉紧致效果很好
顾客: 包装好看吗？是送人的
机器人: 是的呢，我们的礼盒包装非常精致，还附带贺卡，送礼体面大方
顾客: 妈妈皮肤比较干，够滋润吗
机器人: 够的！面霜是丰润质地，特别适合干燥熟龄肌，很多顾客反馈妈妈用了很喜欢
顾客: 好的，我先看看，晚点下单',
  'corr-sess-021', NOW() - INTERVAL '8 days'
FROM platforms p WHERE p.code = 'douyin'
ON CONFLICT (id) DO NOTHING;

-- Session 22: tmall pre-sale — 618 promotion (good)
INSERT INTO bot_chat_sessions (id, platform_id, session_type, external_session_id, customer_id, bot_handled, is_inquiry, inquiry_result, sentiment_score, satisfaction, total_messages, first_response_ms, resolution_ms, tags, conversation, correlation_id, created_at)
SELECT 'b0000000-0000-0000-0000-000000000022', p.id, 'pre_sale', 'tmall-sess-007', 'cust_qin', true, true, 'converted', 5, 'good', 5, 700, 70000, ARRAY['618','大促'],
  '顾客: 618有什么活动
机器人: 618年中大促即将开始！买1件享9折，买2件享8折，买3件享7折。满399还赠价值199元的大礼包！
顾客: 礼包有什么
机器人: 礼包含焕白精华7ml+保湿面霜15g+面膜2片，价值199元
顾客: 这个划算，我凑个399的单',
  'corr-sess-022', NOW() - INTERVAL '7 days'
FROM platforms p WHERE p.code = 'tmall'
ON CONFLICT (id) DO NOTHING;

-- Session 23: pdd post-sale — damaged packaging (bad)
INSERT INTO bot_chat_sessions (id, platform_id, session_type, external_session_id, customer_id, bot_handled, is_inquiry, inquiry_result, sentiment_score, satisfaction, total_messages, first_response_ms, resolution_ms, tags, conversation, correlation_id, created_at)
SELECT 'b0000000-0000-0000-0000-000000000023', p.id, 'post_sale', 'pdd-sess-005', 'cust_jin', true, false, NULL, 2, 'bad', 7, 1600, 360000, ARRAY['包装破损'],
  '顾客: 收到货了，但是包装盒都压扁了
机器人: 抱歉给您带来不好的体验！是快递运输的问题。产品本身有损坏吗？
顾客: 产品看起来没事，但是盒子烂了
机器人: 非常抱歉！我们可以为您补偿10元优惠券，下次购物可用
顾客: 才10块？我是要送人的，这盒子怎么送
机器人: 如果您需要，我们可以单独为您寄一个新的包装盒
顾客: 那太麻烦了，算了。以后包装能不能好一点？
机器人: 您的建议我们已经记录，会反馈给仓库改进包装',
  'corr-sess-023', NOW() - INTERVAL '6 days'
FROM platforms p WHERE p.code = 'pdd'
ON CONFLICT (id) DO NOTHING;

-- Session 24: jd pre-sale — ingredient inquiry (lost)
INSERT INTO bot_chat_sessions (id, platform_id, session_type, external_session_id, customer_id, bot_handled, is_inquiry, inquiry_result, sentiment_score, satisfaction, total_messages, first_response_ms, resolution_ms, tags, conversation, correlation_id, created_at)
SELECT 'b0000000-0000-0000-0000-000000000024', p.id, 'pre_sale', 'jd-sess-006', 'cust_tian', true, true, 'lost', 3, 'neutral', 11, 1400, NULL, ARRAY['成分党','配方'],
  '顾客: 你们精华的成分表能发给我吗
机器人: 当然可以！主成分：烟酰胺4%+传明酸2%+透明质酸钠。完整成分表请查看商品详情页
顾客: 有酒精吗
机器人: 不含酒精
顾客: 香精呢
机器人: 也不含香精，我们的调香来自天然植物精油
顾客: 防腐剂用的什么体系
机器人: 这个问题比较专业，我需要帮您确认一下，请稍等
顾客: 好的
机器人: 抱歉让您久等！我们使用的是多元醇防腐体系（戊二醇+己二醇），不含传统防腐剂
顾客: 嗯，不错。我再研究一下',
  'corr-sess-024', NOW() - INTERVAL '5 days'
FROM platforms p WHERE p.code = 'jd'
ON CONFLICT (id) DO NOTHING;

-- Session 25: douyin post-sale — repurchase (good)
INSERT INTO bot_chat_sessions (id, platform_id, session_type, external_session_id, customer_id, bot_handled, is_inquiry, inquiry_result, sentiment_score, satisfaction, total_messages, first_response_ms, resolution_ms, tags, conversation, correlation_id, created_at)
SELECT 'b0000000-0000-0000-0000-000000000025', p.id, 'post_sale', 'douyin-sess-006', 'cust_xia', true, false, NULL, 4, 'good', 5, 800, 120000, ARRAY['好评','回购'],
  '顾客: 用了一个月效果很好，想再买一瓶
机器人: 感谢您的认可！回购客户我们有专属优惠，输入码「老客回购」享9折
顾客: 太好了，我拉我闺蜜也来买
机器人: 太感谢了！推荐好友下单双方都可获得50积分，积分可兑换正装产品哦
顾客: 好的好的',
  'corr-sess-025', NOW() - INTERVAL '4 days'
FROM platforms p WHERE p.code = 'douyin'
ON CONFLICT (id) DO NOTHING;

-- Session 26: tmall pre-sale — pregnancy safety (good)
INSERT INTO bot_chat_sessions (id, platform_id, session_type, external_session_id, customer_id, bot_handled, is_inquiry, inquiry_result, sentiment_score, satisfaction, total_messages, first_response_ms, resolution_ms, tags, conversation, correlation_id, created_at)
SELECT 'b0000000-0000-0000-0000-000000000026', p.id, 'pre_sale', 'tmall-sess-008', 'cust_han', true, true, 'converted', 4, 'good', 7, 900, 160000, ARRAY['孕妇','安全'],
  '顾客: 怀孕了能用你们的产品吗
机器人: 恭喜准妈妈！我们的产品成分安全温和，但孕期建议避开含维A醇、水杨酸的产品。推荐我们的基础保湿系列
顾客: 哪个系列？
机器人: 推荐氨基酸洁面+玻尿酸水+保湿乳的基础保湿三件套，不含孕妇慎用成分
顾客: 你确定安全吗
机器人: 是的，这三款产品无维A、无水杨酸、无酒精。但孕期体质特殊，建议使用前咨询您的产科医生
顾客: 好，那我先买这三件',
  'corr-sess-026', NOW() - INTERVAL '3 days'
FROM platforms p WHERE p.code = 'tmall'
ON CONFLICT (id) DO NOTHING;

-- Session 27: pdd pre-sale — coupon issue (lost, bad)
INSERT INTO bot_chat_sessions (id, platform_id, session_type, external_session_id, customer_id, bot_handled, transfer_reason, is_inquiry, inquiry_result, sentiment_score, satisfaction, total_messages, first_response_ms, resolution_ms, tags, conversation, correlation_id, created_at)
SELECT 'b0000000-0000-0000-0000-000000000027', p.id, 'pre_sale', 'pdd-sess-006', 'cust_tao', false, 'payment_issue', true, 'lost', 2, 'bad', 8, 1500, NULL, ARRAY['支付','优惠券'],
  '顾客: 为什么我领的优惠券用不了
机器人: 请问是哪个优惠券呢
顾客: 新人满200减50的
机器人: 这个券需要您的订单金额满200元才能使用，目前您的购物车金额是178元
顾客: 那我还差22块
机器人: 是的，您可以再选购一件小商品凑单哦
顾客: 我不想多买，你们就不能通融一下吗
机器人: 抱歉优惠券有使用门槛，这个我这边无法调整
顾客: 那算了不要了',
  'corr-sess-027', NOW() - INTERVAL '2 days'
FROM platforms p WHERE p.code = 'pdd'
ON CONFLICT (id) DO NOTHING;

-- Session 28: jd post-sale — positive feedback (good)
INSERT INTO bot_chat_sessions (id, platform_id, session_type, external_session_id, customer_id, bot_handled, is_inquiry, inquiry_result, sentiment_score, satisfaction, total_messages, first_response_ms, resolution_ms, tags, conversation, correlation_id, created_at)
SELECT 'b0000000-0000-0000-0000-000000000028', p.id, 'post_sale', 'jd-sess-007', 'cust_meng', true, false, NULL, 4, 'good', 5, 700, 100000, ARRAY['好评','效果'],
  '顾客: 用了一周皮肤真的有变好
机器人: 感谢反馈！很高兴我们的产品帮到了您。坚持使用效果会更好哦
顾客: 想问下这个精华早上用还是晚上用
机器人: 美白精华建议晚上使用，白天一定要做好防晒，否则会事倍功半
顾客: 好的谢谢',
  'corr-sess-028', NOW() - INTERVAL '1 day'
FROM platforms p WHERE p.code = 'jd'
ON CONFLICT (id) DO NOTHING;

-- Session 29: douyin pre-sale — newbie starter kit (good)
INSERT INTO bot_chat_sessions (id, platform_id, session_type, external_session_id, customer_id, bot_handled, is_inquiry, inquiry_result, sentiment_score, satisfaction, total_messages, first_response_ms, resolution_ms, tags, conversation, correlation_id, created_at)
SELECT 'b0000000-0000-0000-0000-000000000029', p.id, 'pre_sale', 'douyin-sess-007', 'cust_pan', true, true, 'converted', 5, 'good', 6, 800, 110000, ARRAY['新手','入门'],
  '顾客: 完全不懂护肤，该从什么开始
机器人: 欢迎入门！基础护肤四步走：清洁→补水→保湿→防晒。推荐我们的新手入门套组
顾客: 套组包含什么
机器人: 氨基酸洁面120ml+玻尿酸爽肤水150ml+保湿乳液100ml+防晒乳50ml，一套搞定基础护肤
顾客: 加起来多少钱
机器人: 单品总价356元，套组价只要269元，相当于75折！非常划算
顾客: 好，就这个了',
  'corr-sess-029', NOW() - INTERVAL '12 hours'
FROM platforms p WHERE p.code = 'douyin'
ON CONFLICT (id) DO NOTHING;

-- Session 30: tmall post-sale — usage question (good)
INSERT INTO bot_chat_sessions (id, platform_id, session_type, external_session_id, customer_id, bot_handled, is_inquiry, inquiry_result, sentiment_score, satisfaction, total_messages, first_response_ms, resolution_ms, tags, conversation, correlation_id, created_at)
SELECT 'b0000000-0000-0000-0000-000000000030', p.id, 'post_sale', 'tmall-sess-009', 'cust_shi', true, false, NULL, 4, 'good', 4, 600, 80000, ARRAY['使用方法'],
  '顾客: 这个精华用在哪一步
机器人: 精华在爽肤水之后、乳液/面霜之前使用。取2-3滴按压在面部，轻轻按摩至吸收
顾客: 早晚都用吗
机器人: 美白精华建议晚上用，保湿精华早晚都可以
顾客: 好的明白了',
  'corr-sess-030', NOW() - INTERVAL '6 hours'
FROM platforms p WHERE p.code = 'tmall'
ON CONFLICT (id) DO NOTHING;

-- Session 31: xiaohongshu pre-sale — eye mask (good)
INSERT INTO bot_chat_sessions (id, platform_id, session_type, external_session_id, customer_id, bot_handled, is_inquiry, inquiry_result, sentiment_score, satisfaction, total_messages, first_response_ms, resolution_ms, tags, conversation, correlation_id, created_at)
SELECT 'b0000000-0000-0000-0000-000000000031', p.id, 'pre_sale', 'xiaohongshu-sess-002', 'cust_duan', true, true, 'converted', 5, 'good', 4, 500, 60000, ARRAY['眼膜','黑眼圈'],
  '顾客: 有什么去黑眼圈的产品
机器人: 推荐我们的咖啡因焕亮眼膜！含咖啡因+烟酰胺，针对性淡化黑眼圈，敷15分钟眼下明显提亮
顾客: 每天都能用吗
机器人: 建议每周3-4次，搭配规律作息效果最好
顾客: 下单试试',
  'corr-sess-031', NOW() - INTERVAL '3 hours'
FROM platforms p WHERE p.code = 'xiaohongshu'
ON CONFLICT (id) DO NOTHING;

-- ── Quality Reports (25 reports) ───────────────────────────
-- Report 1: tmall pre-sale — clean (low risk)
INSERT INTO quality_reports (id, ticket_id, agent_id, reviewer_id, conversation, intent, sentiment_score, total_score, violations, risk_level, status, correlation_id, review_mode, is_bot_session, bot_session_id, platform_id, created_at)
SELECT 'c0000000-0000-0000-0000-000000000001', 'tmall-sess-001', 'a0000000-0000-0000-0000-000000000003', 'a0000000-0000-0000-0000-000000000002',
  '顾客: 你好，我想了解一下你们新出的美白精华液...', 'pre_sale_product_inquiry',
  4, 92, '[]', 'low', 'confirmed', 'corr-eval-001', 'active', true,
  'b0000000-0000-0000-0000-000000000001', p.id, NOW() - INTERVAL '27 days'
FROM platforms p WHERE p.code = 'tmall'
ON CONFLICT (id) DO NOTHING;

-- Report 2: tmall post-sale — allergy complaint (high risk, 3 violations)
INSERT INTO quality_reports (id, ticket_id, agent_id, reviewer_id, conversation, intent, sentiment_score, total_score, violations, risk_level, status, correlation_id, review_mode, is_bot_session, bot_session_id, platform_id, created_at)
SELECT 'c0000000-0000-0000-0000-000000000002', 'tmall-sess-002', 'a0000000-0000-0000-0000-000000000004', 'a0000000-0000-0000-0000-000000000002',
  '顾客: 我用了你们的美白精华之后脸上发红发痒...', 'post_sale_complaint',
  2, 45, '[{"rule":"未主动安抚客户情绪","deduction":15,"source_quote":"我理解您的诉求，但运费问题我这边确实无法处理","severity":"critical"},{"rule":"退换货政策说明不清晰","deduction":10,"source_quote":"退货是支持的，但运费需要您承担哦","severity":"major"},{"rule":"未提供升级路径","deduction":5,"source_quote":"需要您联系人工客服","severity":"minor"}]',
  'high', 'pending_review', 'corr-eval-002', 'active', true,
  'b0000000-0000-0000-0000-000000000002', p.id, NOW() - INTERVAL '27 days'
FROM platforms p WHERE p.code = 'tmall'
ON CONFLICT (id) DO NOTHING;

-- Report 3: jd pre-sale — clean (low risk)
INSERT INTO quality_reports (id, ticket_id, agent_id, reviewer_id, conversation, intent, sentiment_score, total_score, violations, risk_level, status, correlation_id, review_mode, is_bot_session, bot_session_id, platform_id, created_at)
SELECT 'c0000000-0000-0000-0000-000000000003', 'jd-sess-001', 'a0000000-0000-0000-0000-000000000003', 'a0000000-0000-0000-0000-000000000005',
  '顾客: 推荐一款适合干皮的面霜...', 'pre_sale_product_inquiry',
  5, 96, '[]', 'low', 'confirmed', 'corr-eval-003', 'active', true,
  'b0000000-0000-0000-0000-000000000003', p.id, NOW() - INTERVAL '26 days'
FROM platforms p WHERE p.code = 'jd'
ON CONFLICT (id) DO NOTHING;

-- Report 4: douyin pre-sale — lost sale (medium risk, 2 violations)
INSERT INTO quality_reports (id, ticket_id, agent_id, reviewer_id, conversation, intent, sentiment_score, total_score, violations, risk_level, status, correlation_id, review_mode, is_bot_session, bot_session_id, platform_id, created_at)
SELECT 'c0000000-0000-0000-0000-000000000004', 'douyin-sess-001', 'a0000000-0000-0000-0000-000000000004', 'a0000000-0000-0000-0000-000000000002',
  '顾客: 你们那个豆沙色口红还有货吗...', 'pre_sale_product_inquiry',
  3, 78, '[{"rule":"未主动挽留流失客户","deduction":10,"source_quote":"抱歉目前没有试用装活动呢","severity":"major"},{"rule":"缺少主动转化引导","deduction":8,"source_quote":"那算了我再看看吧","severity":"major"}]',
  'medium', 'confirmed', 'corr-eval-004', 'active', true,
  'b0000000-0000-0000-0000-000000000004', p.id, NOW() - INTERVAL '25 days'
FROM platforms p WHERE p.code = 'douyin'
ON CONFLICT (id) DO NOTHING;

-- Report 5: tmall post-sale — critical complaint (critical, 3 violations)
INSERT INTO quality_reports (id, ticket_id, agent_id, reviewer_id, conversation, intent, sentiment_score, total_score, violations, risk_level, status, correlation_id, review_mode, is_bot_session, bot_session_id, platform_id, created_at)
SELECT 'c0000000-0000-0000-0000-000000000005', 'tmall-sess-003', 'a0000000-0000-0000-0000-000000000003', 'a0000000-0000-0000-0000-000000000005',
  '顾客: 我买的面霜你们给我发成乳液了！...', 'post_sale_complaint',
  1, 35, '[{"rule":"补偿方案不足","deduction":15,"source_quote":"更多补偿需要联系人工客服","severity":"critical"},{"rule":"未主动道歉安抚","deduction":10,"source_quote":"确实是我们仓库发错了","severity":"major"},{"rule":"未提供升级路径","deduction":5,"source_quote":"需要联系人工客服","severity":"minor"}]',
  'critical', 'confirmed', 'corr-eval-005', 'active', true,
  'b0000000-0000-0000-0000-000000000005', p.id, NOW() - INTERVAL '24 days'
FROM platforms p WHERE p.code = 'tmall'
ON CONFLICT (id) DO NOTHING;

-- Report 6: pdd pre-sale — minor issue (low risk)
INSERT INTO quality_reports (id, ticket_id, agent_id, reviewer_id, conversation, intent, sentiment_score, total_score, violations, risk_level, status, correlation_id, review_mode, is_bot_session, bot_session_id, platform_id, created_at)
SELECT 'c0000000-0000-0000-0000-000000000006', 'pdd-sess-001', 'a0000000-0000-0000-0000-000000000003', 'a0000000-0000-0000-0000-000000000002',
  '顾客: 有清爽不油腻的防晒吗...', 'pre_sale_product_inquiry',
  4, 90, '[{"rule":"产品介绍过于简短","deduction":5,"severity":"minor"}]',
  'low', 'confirmed', 'corr-eval-006', 'active', true,
  'b0000000-0000-0000-0000-000000000006', p.id, NOW() - INTERVAL '23 days'
FROM platforms p WHERE p.code = 'pdd'
ON CONFLICT (id) DO NOTHING;

-- Report 7: jd post-sale — logistics (medium risk, 2 violations)
INSERT INTO quality_reports (id, ticket_id, agent_id, reviewer_id, conversation, intent, sentiment_score, total_score, violations, risk_level, status, correlation_id, review_mode, is_bot_session, bot_session_id, platform_id, created_at)
SELECT 'c0000000-0000-0000-0000-000000000007', 'jd-sess-002', 'a0000000-0000-0000-0000-000000000004', 'a0000000-0000-0000-0000-000000000002',
  '顾客: 我的订单三天了还没发货...', 'post_sale_logistics',
  3, 82, '[{"rule":"缺少主动补偿","deduction":10,"source_quote":"我们会为您标注加急处理","severity":"major"},{"rule":"话术过于模板化","deduction":8,"source_quote":"近期618大促订单量较大","severity":"major"}]',
  'medium', 'confirmed', 'corr-eval-007', 'active', true,
  'b0000000-0000-0000-0000-000000000007', p.id, NOW() - INTERVAL '22 days'
FROM platforms p WHERE p.code = 'jd'
ON CONFLICT (id) DO NOTHING;

-- Report 8: douyin pre-sale — human transfer (medium risk)
INSERT INTO quality_reports (id, ticket_id, agent_id, reviewer_id, conversation, intent, sentiment_score, total_score, violations, risk_level, status, correlation_id, review_mode, is_bot_session, bot_session_id, platform_id, created_at)
SELECT 'c0000000-0000-0000-0000-000000000008', 'douyin-sess-002', 'a0000000-0000-0000-0000-000000000003', 'a0000000-0000-0000-0000-000000000005',
  '顾客: 我是敏感肌，想找一套完整的护肤流程...', 'pre_sale_recommend',
  4, 88, '[{"rule":"转人工后响应时间长","deduction":12,"severity":"major"}]',
  'medium', 'confirmed', 'corr-eval-008', 'active', true,
  'b0000000-0000-0000-0000-000000000008', p.id, NOW() - INTERVAL '21 days'
FROM platforms p WHERE p.code = 'douyin'
ON CONFLICT (id) DO NOTHING;

-- Report 9: tmall pre-sale — clean (low risk)
INSERT INTO quality_reports (id, ticket_id, agent_id, reviewer_id, conversation, intent, sentiment_score, total_score, violations, risk_level, status, correlation_id, review_mode, is_bot_session, bot_session_id, platform_id, created_at)
SELECT 'c0000000-0000-0000-0000-000000000009', 'tmall-sess-004', 'a0000000-0000-0000-0000-000000000004', 'a0000000-0000-0000-0000-000000000002',
  '顾客: 25岁开始用眼霜早不早...', 'pre_sale_product_inquiry',
  5, 94, '[]', 'low', 'confirmed', 'corr-eval-009', 'active', true,
  'b0000000-0000-0000-0000-000000000009', p.id, NOW() - INTERVAL '20 days'
FROM platforms p WHERE p.code = 'tmall'
ON CONFLICT (id) DO NOTHING;

-- Report 10: pdd post-sale — authenticity doubt (high risk, 3 violations)
INSERT INTO quality_reports (id, ticket_id, agent_id, reviewer_id, conversation, intent, sentiment_score, total_score, violations, risk_level, status, correlation_id, review_mode, is_bot_session, bot_session_id, platform_id, created_at)
SELECT 'c0000000-0000-0000-0000-000000000010', 'pdd-sess-002', 'a0000000-0000-0000-0000-000000000003', 'a0000000-0000-0000-0000-000000000005',
  '顾客: 你们这个洗面奶和我之前在专柜买的味道不一样...', 'post_sale_quality_doubt',
  2, 52, '[{"rule":"未有效消除客户疑虑","deduction":15,"source_quote":"不同批次的产品在气味上可能有轻微差异","severity":"critical"},{"rule":"语气过于被动防御","deduction":10,"source_quote":"绝对没有这种情况","severity":"major"},{"rule":"未主动提供解决方案","deduction":8,"source_quote":"如果您不满意，可以申请退货","severity":"major"}]',
  'high', 'pending_review', 'corr-eval-010', 'active', true,
  'b0000000-0000-0000-0000-000000000010', p.id, NOW() - INTERVAL '19 days'
FROM platforms p WHERE p.code = 'pdd'
ON CONFLICT (id) DO NOTHING;

-- Report 11: jd pre-sale — clean (low risk)
INSERT INTO quality_reports (id, ticket_id, agent_id, reviewer_id, conversation, intent, sentiment_score, total_score, violations, risk_level, status, correlation_id, review_mode, is_bot_session, bot_session_id, platform_id, created_at)
SELECT 'c0000000-0000-0000-0000-000000000011', 'jd-sess-003', 'a0000000-0000-0000-0000-000000000004', 'a0000000-0000-0000-0000-000000000002',
  '顾客: 补水面膜有推荐吗...', 'pre_sale_product_inquiry',
  5, 95, '[]', 'low', 'confirmed', 'corr-eval-011', 'active', true,
  'b0000000-0000-0000-0000-000000000011', p.id, NOW() - INTERVAL '18 days'
FROM platforms p WHERE p.code = 'jd'
ON CONFLICT (id) DO NOTHING;

-- Report 12: douyin post-sale — critical complaint (critical, 3 violations)
INSERT INTO quality_reports (id, ticket_id, agent_id, reviewer_id, conversation, intent, sentiment_score, total_score, violations, risk_level, status, correlation_id, review_mode, is_bot_session, bot_session_id, platform_id, created_at)
SELECT 'c0000000-0000-0000-0000-000000000012', 'douyin-sess-003', 'a0000000-0000-0000-0000-000000000003', 'a0000000-0000-0000-0000-000000000002',
  '顾客: 我昨天问的问题你们还没回复...', 'post_sale_complaint',
  1, 28, '[{"rule":"多客服信息不共享","deduction":15,"source_quote":"我没有查到之前的记录","severity":"critical"},{"rule":"响应时间过长","deduction":10,"source_quote":"审核中","severity":"major"},{"rule":"反复要求客户重复信息","deduction":8,"source_quote":"请提供订单号和漏液照片","severity":"major"}]',
  'critical', 'confirmed', 'corr-eval-012', 'active', true,
  'b0000000-0000-0000-0000-000000000012', p.id, NOW() - INTERVAL '17 days'
FROM platforms p WHERE p.code = 'douyin'
ON CONFLICT (id) DO NOTHING;

-- Report 13: tmall pre-sale — price compare lost (medium risk)
INSERT INTO quality_reports (id, ticket_id, agent_id, reviewer_id, conversation, intent, sentiment_score, total_score, violations, risk_level, status, correlation_id, review_mode, is_bot_session, bot_session_id, platform_id, created_at)
SELECT 'c0000000-0000-0000-0000-000000000013', 'tmall-sess-005', 'a0000000-0000-0000-0000-000000000004', 'a0000000-0000-0000-0000-000000000005',
  '顾客: 你们这个和某品牌比哪个好...', 'pre_sale_price_compare',
  3, 80, '[{"rule":"比价场景缺乏说服力","deduction":10,"source_quote":"我们的产品采用的是进口原料","severity":"major"},{"rule":"未转化价格敏感客户","deduction":8,"source_quote":"还是有点贵，我再看看","severity":"major"}]',
  'medium', 'confirmed', 'corr-eval-013', 'active', true,
  'b0000000-0000-0000-0000-000000000013', p.id, NOW() - INTERVAL '16 days'
FROM platforms p WHERE p.code = 'tmall'
ON CONFLICT (id) DO NOTHING;

-- Report 14: pdd pre-sale — clean (low risk)
INSERT INTO quality_reports (id, ticket_id, agent_id, reviewer_id, conversation, intent, sentiment_score, total_score, violations, risk_level, status, correlation_id, review_mode, is_bot_session, bot_session_id, platform_id, created_at)
SELECT 'c0000000-0000-0000-0000-000000000014', 'pdd-sess-003', 'a0000000-0000-0000-0000-000000000003', 'a0000000-0000-0000-0000-000000000002',
  '顾客: 油皮用什么洁面好...', 'pre_sale_product_inquiry',
  4, 92, '[]', 'low', 'confirmed', 'corr-eval-014', 'active', true,
  'b0000000-0000-0000-0000-000000000014', p.id, NOW() - INTERVAL '15 days'
FROM platforms p WHERE p.code = 'pdd'
ON CONFLICT (id) DO NOTHING;

-- Report 15: jd post-sale — shade exchange (low risk)
INSERT INTO quality_reports (id, ticket_id, agent_id, reviewer_id, conversation, intent, sentiment_score, total_score, violations, risk_level, status, correlation_id, review_mode, is_bot_session, bot_session_id, platform_id, created_at)
SELECT 'c0000000-0000-0000-0000-000000000015', 'jd-sess-004', 'a0000000-0000-0000-0000-000000000004', 'a0000000-0000-0000-0000-000000000005',
  '顾客: 买的粉底液颜色太白了...', 'post_sale_exchange',
  3, 88, '[]', 'low', 'confirmed', 'corr-eval-015', 'active', true,
  'b0000000-0000-0000-0000-000000000015', p.id, NOW() - INTERVAL '14 days'
FROM platforms p WHERE p.code = 'jd'
ON CONFLICT (id) DO NOTHING;

-- Report 16: douyin pre-sale — clean (low risk)
INSERT INTO quality_reports (id, ticket_id, agent_id, reviewer_id, conversation, intent, sentiment_score, total_score, violations, risk_level, status, correlation_id, review_mode, is_bot_session, bot_session_id, platform_id, created_at)
SELECT 'c0000000-0000-0000-0000-000000000016', 'douyin-sess-004', 'a0000000-0000-0000-0000-000000000003', 'a0000000-0000-0000-0000-000000000002',
  '顾客: 有没有敏感肌能用的卸妆油...', 'pre_sale_product_inquiry',
  4, 91, '[]', 'low', 'confirmed', 'corr-eval-016', 'active', true,
  'b0000000-0000-0000-0000-000000000016', p.id, NOW() - INTERVAL '13 days'
FROM platforms p WHERE p.code = 'douyin'
ON CONFLICT (id) DO NOTHING;

-- Report 17: tmall post-sale — medical complaint (critical)
INSERT INTO quality_reports (id, ticket_id, agent_id, reviewer_id, conversation, intent, sentiment_score, total_score, violations, risk_level, status, correlation_id, review_mode, is_bot_session, bot_session_id, platform_id, created_at)
SELECT 'c0000000-0000-0000-0000-000000000017', 'tmall-sess-006', 'a0000000-0000-0000-0000-000000000004', 'a0000000-0000-0000-0000-000000000002',
  '顾客: 用完你们产品我脸上起了大片红疹...', 'post_sale_medical_complaint',
  1, 40, '[{"rule":"医疗投诉处理流程需完善","deduction":20,"source_quote":"这个case会转接给我们的客诉专员","severity":"critical"},{"rule":"首次响应缺少同理心","deduction":10,"source_quote":"请问方便提供医生的诊断证明吗","severity":"major"}]',
  'critical', 'pending_review', 'corr-eval-017', 'active', true,
  'b0000000-0000-0000-0000-000000000017', p.id, NOW() - INTERVAL '12 days'
FROM platforms p WHERE p.code = 'tmall'
ON CONFLICT (id) DO NOTHING;

-- Report 18: pdd pre-sale — clean (low risk)
INSERT INTO quality_reports (id, ticket_id, agent_id, reviewer_id, conversation, intent, sentiment_score, total_score, violations, risk_level, status, correlation_id, review_mode, is_bot_session, bot_session_id, platform_id, created_at)
SELECT 'c0000000-0000-0000-0000-000000000018', 'pdd-sess-004', 'a0000000-0000-0000-0000-000000000003', 'a0000000-0000-0000-0000-000000000005',
  '顾客: 嘴唇干裂用什么...', 'pre_sale_product_inquiry',
  5, 96, '[]', 'low', 'confirmed', 'corr-eval-018', 'active', true,
  'b0000000-0000-0000-0000-000000000018', p.id, NOW() - INTERVAL '11 days'
FROM platforms p WHERE p.code = 'pdd'
ON CONFLICT (id) DO NOTHING;

-- Report 19: xiaohongshu pre-sale — clean (low risk)
INSERT INTO quality_reports (id, ticket_id, agent_id, reviewer_id, conversation, intent, sentiment_score, total_score, violations, risk_level, status, correlation_id, review_mode, is_bot_session, bot_session_id, platform_id, created_at)
SELECT 'c0000000-0000-0000-0000-000000000019', 'xiaohongshu-sess-001', 'a0000000-0000-0000-0000-000000000004', 'a0000000-0000-0000-0000-000000000002',
  '顾客: 小红书种草了你们家的精华...', 'pre_sale_social_referral',
  5, 93, '[]', 'low', 'confirmed', 'corr-eval-019', 'active', true,
  'b0000000-0000-0000-0000-000000000019', p.id, NOW() - INTERVAL '10 days'
FROM platforms p WHERE p.code = 'xiaohongshu'
ON CONFLICT (id) DO NOTHING;

-- Report 20: jd post-sale — refund progress (medium risk)
INSERT INTO quality_reports (id, ticket_id, agent_id, reviewer_id, conversation, intent, sentiment_score, total_score, violations, risk_level, status, correlation_id, review_mode, is_bot_session, bot_session_id, platform_id, created_at)
SELECT 'c0000000-0000-0000-0000-000000000020', 'jd-sess-005', 'a0000000-0000-0000-0000-000000000003', 'a0000000-0000-0000-0000-000000000005',
  '顾客: 我的退款什么时候到账...', 'post_sale_refund',
  3, 86, '[{"rule":"退款进度话术可优化","deduction":8,"source_quote":"质检通过后会立即发起退款","severity":"major"}]',
  'medium', 'confirmed', 'corr-eval-020', 'active', true,
  'b0000000-0000-0000-0000-000000000020', p.id, NOW() - INTERVAL '9 days'
FROM platforms p WHERE p.code = 'jd'
ON CONFLICT (id) DO NOTHING;

-- Report 21: pdd post-sale — packaging (high risk, 2 violations)
INSERT INTO quality_reports (id, ticket_id, agent_id, reviewer_id, conversation, intent, sentiment_score, total_score, violations, risk_level, status, correlation_id, review_mode, is_bot_session, bot_session_id, platform_id, created_at)
SELECT 'c0000000-0000-0000-0000-000000000021', 'pdd-sess-005', 'a0000000-0000-0000-0000-000000000004', 'a0000000-0000-0000-0000-000000000002',
  '顾客: 收到货了，但是包装盒都压扁了...', 'post_sale_packaging',
  2, 68, '[{"rule":"补偿力度不足","deduction":15,"source_quote":"我们可以为您补偿10元优惠券","severity":"critical"},{"rule":"未考虑送礼场景","deduction":10,"source_quote":"如果您需要，我们可以单独为您寄一个新的包装盒","severity":"major"}]',
  'high', 'confirmed', 'corr-eval-021', 'active', true,
  'b0000000-0000-0000-0000-000000000023', p.id, NOW() - INTERVAL '6 days'
FROM platforms p WHERE p.code = 'pdd'
ON CONFLICT (id) DO NOTHING;

-- Report 22: jd pre-sale — ingredient inquiry (medium risk)
INSERT INTO quality_reports (id, ticket_id, agent_id, reviewer_id, conversation, intent, sentiment_score, total_score, violations, risk_level, status, correlation_id, review_mode, is_bot_session, bot_session_id, platform_id, created_at)
SELECT 'c0000000-0000-0000-0000-000000000022', 'jd-sess-006', 'a0000000-0000-0000-0000-000000000003', 'a0000000-0000-0000-0000-000000000005',
  '顾客: 你们精华的成分表能发给我吗...', 'pre_sale_ingredient_inquiry',
  3, 85, '[{"rule":"成分查询响应慢","deduction":10,"source_quote":"这个问题比较专业，我需要帮您确认一下","severity":"major"},{"rule":"未转化专业型客户","deduction":5,"source_quote":"我再研究一下","severity":"minor"}]',
  'medium', 'confirmed', 'corr-eval-022', 'active', true,
  'b0000000-0000-0000-0000-000000000024', p.id, NOW() - INTERVAL '5 days'
FROM platforms p WHERE p.code = 'jd'
ON CONFLICT (id) DO NOTHING;

-- Report 23: pdd pre-sale — coupon issue (high risk, 2 violations)
INSERT INTO quality_reports (id, ticket_id, agent_id, reviewer_id, conversation, intent, sentiment_score, total_score, violations, risk_level, status, correlation_id, review_mode, is_bot_session, bot_session_id, platform_id, created_at)
SELECT 'c0000000-0000-0000-0000-000000000023', 'pdd-sess-006', 'a0000000-0000-0000-0000-000000000004', 'a0000000-0000-0000-0000-000000000002',
  '顾客: 为什么我领的优惠券用不了...', 'pre_sale_coupon_issue',
  2, 72, '[{"rule":"未挽留因券流失客户","deduction":12,"source_quote":"抱歉优惠券有使用门槛","severity":"critical"},{"rule":"缺少灵活应对方案","deduction":10,"source_quote":"这个我这边无法调整","severity":"major"}]',
  'high', 'pending_review', 'corr-eval-023', 'active', true,
  'b0000000-0000-0000-0000-000000000027', p.id, NOW() - INTERVAL '2 days'
FROM platforms p WHERE p.code = 'pdd'
ON CONFLICT (id) DO NOTHING;

-- Report 24: douyin pre-sale — newbie guide (low risk)
INSERT INTO quality_reports (id, ticket_id, agent_id, reviewer_id, conversation, intent, sentiment_score, total_score, violations, risk_level, status, correlation_id, review_mode, is_bot_session, bot_session_id, platform_id, created_at)
SELECT 'c0000000-0000-0000-0000-000000000024', 'douyin-sess-007', 'a0000000-0000-0000-0000-000000000003', 'a0000000-0000-0000-0000-000000000005',
  '顾客: 完全不懂护肤，该从什么开始...', 'pre_sale_newbie_guide',
  5, 94, '[]', 'low', 'confirmed', 'corr-eval-024', 'active', true,
  'b0000000-0000-0000-0000-000000000029', p.id, NOW() - INTERVAL '12 hours'
FROM platforms p WHERE p.code = 'douyin'
ON CONFLICT (id) DO NOTHING;

-- Report 25: tmall pre-sale — 618 promotion (low risk)
INSERT INTO quality_reports (id, ticket_id, agent_id, reviewer_id, conversation, intent, sentiment_score, total_score, violations, risk_level, status, correlation_id, review_mode, is_bot_session, bot_session_id, platform_id, created_at)
SELECT 'c0000000-0000-0000-0000-000000000025', 'tmall-sess-007', 'a0000000-0000-0000-0000-000000000004', 'a0000000-0000-0000-0000-000000000002',
  '顾客: 618有什么活动...', 'pre_sale_promotion_inquiry',
  5, 92, '[]', 'low', 'confirmed', 'corr-eval-025', 'active', true,
  'b0000000-0000-0000-0000-000000000022', p.id, NOW() - INTERVAL '7 days'
FROM platforms p WHERE p.code = 'tmall'
ON CONFLICT (id) DO NOTHING;

-- ── Bot Configs (10 configs) ─────────────────────────────────
INSERT INTO bot_configs (id, platform_id, config_type, config_key, config_value, version, status, updated_by, change_summary, created_at, updated_at)
SELECT 'd0000000-0000-0000-0000-000000000001', p.id, 'pre_sale', 'greeting_template', '{"greeting":"您好！欢迎光临{{brand}}官方旗舰店～请问有什么可以帮您的？","time_greeting":{"morning":"早上好☀️","afternoon":"下午好🌤","evening":"晚上好🌙"}}', 1, 'active', 'a0000000-0000-0000-0000-000000000002', '初始版本', NOW() - INTERVAL '30 days', NOW() - INTERVAL '30 days'
FROM platforms p WHERE p.code = 'tmall'
ON CONFLICT (id) DO NOTHING;

INSERT INTO bot_configs (id, platform_id, config_type, config_key, config_value, version, status, updated_by, change_summary, created_at, updated_at)
SELECT 'd0000000-0000-0000-0000-000000000002', p.id, 'pre_sale', 'product_recommend', '{"strategy":"肤质优先","flow":["询问肤质→确认需求→推荐产品→提供链接"],"upsell":"推荐搭配使用效果更好"}', 1, 'active', 'a0000000-0000-0000-0000-000000000002', '初始版本', NOW() - INTERVAL '30 days', NOW() - INTERVAL '30 days'
FROM platforms p WHERE p.code = 'tmall'
ON CONFLICT (id) DO NOTHING;

INSERT INTO bot_configs (id, platform_id, config_type, config_key, config_value, version, status, updated_by, change_summary, created_at, updated_at)
SELECT 'd0000000-0000-0000-0000-000000000003', p.id, 'post_sale', 'return_policy', '{"policy_text":"支持7天无理由退换货，不影响二次销售即可。过敏包退，需提供照片。退货地址：广东省广州市...","auto_approve":true,"auto_approve_amount":200}', 1, 'active', 'a0000000-0000-0000-0000-000000000002', '初始版本', NOW() - INTERVAL '30 days', NOW() - INTERVAL '30 days'
FROM platforms p WHERE p.code = 'tmall'
ON CONFLICT (id) DO NOTHING;

INSERT INTO bot_configs (id, platform_id, config_type, config_key, config_value, version, status, updated_by, change_summary, created_at, updated_at)
SELECT 'd0000000-0000-0000-0000-000000000004', p.id, 'post_sale', 'compensation_tiers', '{"tier_1":{"condition":"发货延迟1-3天","compensation":"5元优惠券"},"tier_2":{"condition":"发错货/少发货","compensation":"30元优惠券+补发"},"tier_3":{"condition":"过敏/质量问题","compensation":"全额退款+医疗费(需凭证)"}}', 1, 'active', 'a0000000-0000-0000-0000-000000000002', '初始版本', NOW() - INTERVAL '28 days', NOW() - INTERVAL '28 days'
FROM platforms p WHERE p.code = 'tmall'
ON CONFLICT (id) DO NOTHING;

INSERT INTO bot_configs (id, platform_id, config_type, config_key, config_value, version, status, updated_by, change_summary, created_at, updated_at)
SELECT 'd0000000-0000-0000-0000-000000000005', p.id, 'pre_sale', 'live_stream_script', '{"hook":"直播间专属福利来啦！","pain_point":"是不是总觉得自己皮肤暗沉？","solution":"今天给大家带来的是我们的明星产品...","urgency":"库存不多，先到先得！"}', 1, 'draft', 'a0000000-0000-0000-0000-000000000005', '初始版本', NOW() - INTERVAL '20 days', NOW() - INTERVAL '20 days'
FROM platforms p WHERE p.code = 'douyin'
ON CONFLICT (id) DO NOTHING;

INSERT INTO bot_configs (id, platform_id, config_type, config_key, config_value, version, status, updated_by, change_summary, created_at, updated_at)
SELECT 'd0000000-0000-0000-0000-000000000006', p.id, 'post_sale', 'douyin_after_sales', '{"support_hours":"09:00-22:00","response_sla_minutes":5,"escalation":"3次无解→转人工","satisfaction_survey":true}', 1, 'active', 'a0000000-0000-0000-0000-000000000005', '初始版本', NOW() - INTERVAL '20 days', NOW() - INTERVAL '20 days'
FROM platforms p WHERE p.code = 'douyin'
ON CONFLICT (id) DO NOTHING;

INSERT INTO bot_configs (id, platform_id, config_type, config_key, config_value, version, status, updated_by, change_summary, created_at, updated_at)
SELECT 'd0000000-0000-0000-0000-000000000007', p.id, 'pre_sale', 'jd_price_match', '{"enable":false,"reason":"品牌控价策略，不参与比价","redirect_msg":"我们的产品品质和效果值得这个价格哦"}', 1, 'active', 'a0000000-0000-0000-0000-000000000002', '初始版本', NOW() - INTERVAL '15 days', NOW() - INTERVAL '15 days'
FROM platforms p WHERE p.code = 'jd'
ON CONFLICT (id) DO NOTHING;

INSERT INTO bot_configs (id, platform_id, config_type, config_key, config_value, version, status, updated_by, change_summary, created_at, updated_at)
SELECT 'd0000000-0000-0000-0000-000000000008', p.id, 'pre_sale', 'pdd_low_price_strategy', '{"low_price_tactics":["拼团价","限时秒杀","新人专享"],"upsell_threshold":99,"free_shipping_threshold":29}', 1, 'active', 'a0000000-0000-0000-0000-000000000005', '初始版本', NOW() - INTERVAL '12 days', NOW() - INTERVAL '12 days'
FROM platforms p WHERE p.code = 'pdd'
ON CONFLICT (id) DO NOTHING;

INSERT INTO bot_configs (id, platform_id, config_type, config_key, config_value, version, status, updated_by, change_summary, created_at, updated_at)
SELECT 'd0000000-0000-0000-0000-000000000009', p.id, 'pre_sale', 'objection_handling', '{"common_objections":[{"obj":"太贵了","reply":"我们的性价比其实更高，因为有效成分浓度是同类产品的2倍"},{"obj":"会过敏吗","reply":"产品通过敏感肌测试，但建议首次使用先做耳后测试"},{"obj":"和XX比怎么样","reply":"我们的配方更安全，不添加酒精香精，您可以对比成分表"}]}', 1, 'active', 'a0000000-0000-0000-0000-000000000002', '初始版本', NOW() - INTERVAL '10 days', NOW() - INTERVAL '10 days'
FROM platforms p WHERE p.code = 'tmall'
ON CONFLICT (id) DO NOTHING;

INSERT INTO bot_configs (id, platform_id, config_type, config_key, config_value, version, status, updated_by, change_summary, created_at, updated_at)
SELECT 'd0000000-0000-0000-0000-000000000010', p.id, 'post_sale', 'complaint_escalation', '{"levels":["初级客服→安抚+记录","中台→48h电话回访","客诉专员→处理医疗投诉"],"sensitive_keywords":["过敏","毁容","医院","12315","投诉","律师","媒体"]}', 1, 'active', 'a0000000-0000-0000-0000-000000000002', '初始版本', NOW() - INTERVAL '8 days', NOW() - INTERVAL '8 days'
FROM platforms p WHERE p.code = 'tmall'
ON CONFLICT (id) DO NOTHING;

-- ── Knowledge Entries (15 entries) ──────────────────────────
INSERT INTO knowledge_entries (id, category, platform_id, title, content, keywords, tags, priority, status, version, updated_by, created_at, updated_at)
SELECT 'e0000000-0000-0000-0000-000000000001', 'product', p.id, '焕白精华液产品说明',
  '产品名称：焕白精华液 规格：30ml 主要成分：烟酰胺4%+传明酸2%+透明质酸钠 功效：美白淡斑、提亮肤色 适用肤质：所有肤质（含敏感肌） 使用建议：每晚使用，取2-3滴按压吸收 注意事项：白天使用需搭配防晒',
  ARRAY['美白','精华','烟酰胺','淡斑'], ARRAY['明星产品','核心单品'], 10, 'published', 1, 'a0000000-0000-0000-0000-000000000002', NOW() - INTERVAL '30 days', NOW() - INTERVAL '30 days'
FROM platforms p WHERE p.code = 'tmall'
ON CONFLICT (id) DO NOTHING;

INSERT INTO knowledge_entries (id, category, platform_id, title, content, keywords, tags, priority, status, version, updated_by, created_at, updated_at)
SELECT 'e0000000-0000-0000-0000-000000000002', 'product', p.id, '玻尿酸保湿面霜产品说明',
  '产品名称：玻尿酸保湿面霜 规格：50g 主要成分：三重玻尿酸+神经酰胺+角鲨烷 功效：深层补水、锁水保湿、修护屏障 适用肤质：干皮、混干 使用建议：早晚使用，取适量均匀涂抹',
  ARRAY['面霜','保湿','玻尿酸','干皮'], ARRAY['明星产品'], 9, 'published', 1, 'a0000000-0000-0000-0000-000000000002', NOW() - INTERVAL '30 days', NOW() - INTERVAL '30 days'
FROM platforms p WHERE p.code = 'tmall'
ON CONFLICT (id) DO NOTHING;

INSERT INTO knowledge_entries (id, category, platform_id, title, content, keywords, tags, priority, status, version, updated_by, created_at, updated_at)
SELECT 'e0000000-0000-0000-0000-000000000003', 'faq', p.id, '常见问题：敏感肌能用吗',
  '我们的产品全线经过敏感肌测试，不含酒精、香精、色素、矿物油。但每个人的过敏原不同，建议首次使用前在耳后或手腕内侧做24小时过敏测试。如果出现不适，请立即停用并联系我们。',
  ARRAY['敏感肌','过敏','安全','测试'], ARRAY['FAQ','高频问题'], 8, 'published', 1, 'a0000000-0000-0000-0000-000000000002', NOW() - INTERVAL '28 days', NOW() - INTERVAL '28 days'
FROM platforms p WHERE p.code = 'tmall'
ON CONFLICT (id) DO NOTHING;

INSERT INTO knowledge_entries (id, category, platform_id, title, content, keywords, tags, priority, status, version, updated_by, created_at, updated_at)
SELECT 'e0000000-0000-0000-0000-000000000004', 'faq', p.id, '常见问题：孕妇能用吗',
  '孕期建议避开含维A醇（视黄醇）、水杨酸、果酸的产品。我们推荐的基础保湿三件套（氨基酸洁面+玻尿酸水+保湿乳）不含上述成分，适合孕期使用。但因孕期体质特殊，建议使用前咨询产科医生。',
  ARRAY['孕妇','怀孕','安全','成分'], ARRAY['FAQ','安全类'], 8, 'published', 1, 'a0000000-0000-0000-0000-000000000005', NOW() - INTERVAL '28 days', NOW() - INTERVAL '28 days'
FROM platforms p WHERE p.code = 'tmall'
ON CONFLICT (id) DO NOTHING;

INSERT INTO knowledge_entries (id, category, platform_id, title, content, keywords, tags, priority, status, version, updated_by, created_at, updated_at)
SELECT 'e0000000-0000-0000-0000-000000000005', 'after_sales_policy', p.id, '退换货政策',
  '1. 7天无理由退货：不影响二次销售即可（未拆封、未使用） 2. 过敏退货：提供过敏照片+停止使用，全额退款 3. 发错货：免费补发正确商品，错误商品无需退回 4. 质量问题：提供照片/视频证明，全额退款或换货 5. 退货地址：广东省广州市白云区XX产业园XX栋 6. 退款时效：收到退货后3-5个工作日内到账',
  ARRAY['退货','退款','换货','政策','售后'], ARRAY['售后政策','重要'], 9, 'published', 2, 'a0000000-0000-0000-0000-000000000002', NOW() - INTERVAL '25 days', NOW() - INTERVAL '10 days'
FROM platforms p WHERE p.code = 'tmall'
ON CONFLICT (id) DO NOTHING;

INSERT INTO knowledge_entries (id, category, platform_id, title, content, keywords, tags, priority, status, version, updated_by, created_at, updated_at)
SELECT 'e0000000-0000-0000-0000-000000000006', 'product', p.id, '水感防晒乳产品说明',
  '产品名称：水感防晒乳 规格：50ml SPF值：SPF50+ PA+++ 主要成分：物理+化学双重防晒 功效：防晒、清爽不油腻 适用肤质：所有肤质 使用建议：出门前20分钟涂抹，每2-3小时补涂',
  ARRAY['防晒','清爽','SPF50','夏天'], ARRAY['夏季热销'], 7, 'published', 1, 'a0000000-0000-0000-0000-000000000005', NOW() - INTERVAL '22 days', NOW() - INTERVAL '22 days'
FROM platforms p WHERE p.code = 'tmall'
ON CONFLICT (id) DO NOTHING;

INSERT INTO knowledge_entries (id, category, platform_id, title, content, keywords, tags, priority, status, version, updated_by, created_at, updated_at)
SELECT 'e0000000-0000-0000-0000-000000000007', 'campaign', p.id, '618年中大促活动规则',
  '活动时间：6月1日-6月20日 优惠力度：买1件9折/买2件8折/买3件7折 满赠：满399元赠价值199元大礼包（精华7ml+面霜15g+面膜2片） 叠加：可叠加平台跨店满减 老客专属：输入暗号「老客回购」额外9折 积分翻倍：活动期间购买享双倍积分',
  ARRAY['618','大促','优惠','满减','折扣'], ARRAY['大促活动','促销'], 10, 'published', 1, 'a0000000-0000-0000-0000-000000000002', NOW() - INTERVAL '15 days', NOW() - INTERVAL '15 days'
FROM platforms p WHERE p.code = 'tmall'
ON CONFLICT (id) DO NOTHING;

INSERT INTO knowledge_entries (id, category, platform_id, title, content, keywords, tags, priority, status, version, updated_by, created_at, updated_at)
SELECT 'e0000000-0000-0000-0000-000000000008', 'product', p.id, '多肽紧致眼霜产品说明',
  '产品名称：多肽紧致眼霜 规格：15g 主要成分：六胜肽+咖啡因+透明质酸 功效：淡化细纹、消除浮肿、紧致眼周 适用肤质：所有肤质 使用建议：早晚使用，取米粒大小点涂在眼周，轻拍至吸收',
  ARRAY['眼霜','抗老','细纹','黑眼圈'], ARRAY['明星产品'], 7, 'published', 1, 'a0000000-0000-0000-0000-000000000002', NOW() - INTERVAL '20 days', NOW() - INTERVAL '20 days'
FROM platforms p WHERE p.code = 'tmall'
ON CONFLICT (id) DO NOTHING;

INSERT INTO knowledge_entries (id, category, platform_id, title, content, keywords, tags, priority, status, version, updated_by, created_at, updated_at)
SELECT 'e0000000-0000-0000-0000-000000000009', 'faq', p.id, '常见问题：使用顺序',
  '基础护肤使用顺序（日间）：洁面→爽肤水→精华→眼霜→乳液/面霜→防晒 基础护肤使用顺序（夜间）：卸妆→洁面→爽肤水→精华→眼霜→乳液/面霜 美白精华建议夜间使用，保湿精华早晚均可',
  ARRAY['使用顺序','步骤','护肤流程'], ARRAY['FAQ','使用指南'], 6, 'published', 1, 'a0000000-0000-0000-0000-000000000005', NOW() - INTERVAL '18 days', NOW() - INTERVAL '18 days'
FROM platforms p WHERE p.code = 'tmall'
ON CONFLICT (id) DO NOTHING;

INSERT INTO knowledge_entries (id, category, platform_id, title, content, keywords, tags, priority, status, version, updated_by, created_at, updated_at)
SELECT 'e0000000-0000-0000-0000-000000000010', 'product', p.id, '丝绒哑光唇釉产品说明',
  '产品名称：丝绒哑光唇釉 规格：4.5g 色号：#301豆沙色、#302蜜桃豆沙、#303复古红、#304珊瑚橘 质地：丝绒哑光，上嘴轻薄不拔干 特色：食品级安全配方，持色8小时',
  ARRAY['口红','唇釉','哑光','豆沙色'], ARRAY['彩妆','爆款'], 6, 'published', 1, 'a0000000-0000-0000-0000-000000000005', NOW() - INTERVAL '18 days', NOW() - INTERVAL '18 days'
FROM platforms p WHERE p.code = 'douyin'
ON CONFLICT (id) DO NOTHING;

INSERT INTO knowledge_entries (id, category, platform_id, title, content, keywords, tags, priority, status, version, updated_by, created_at, updated_at)
SELECT 'e0000000-0000-0000-0000-000000000011', 'greeting', p.id, '天猫旗舰店欢迎语',
  '{{time_greeting}}欢迎光临{{brand}}官方旗舰店～ 我们主营温和高效的护肤产品，全线通过敏感肌测试。618大促进行中，买3件享7折！ 有任何护肤问题都可以问我哦 💕',
  ARRAY['欢迎','问候','618'], ARRAY['欢迎语','天猫'], 5, 'published', 1, 'a0000000-0000-0000-0000-000000000002', NOW() - INTERVAL '10 days', NOW() - INTERVAL '10 days'
FROM platforms p WHERE p.code = 'tmall'
ON CONFLICT (id) DO NOTHING;

INSERT INTO knowledge_entries (id, category, platform_id, title, content, keywords, tags, priority, status, version, updated_by, created_at, updated_at)
SELECT 'e0000000-0000-0000-0000-000000000012', 'after_sales_policy', p.id, '物流与配送政策',
  '发货时效：正常订单48小时内发货，大促期间72小时内 快递合作：顺丰/中通（随机） 包邮政策：满99元包邮，不满99元运费8元 偏远地区：新疆、西藏、内蒙古加收15元 物流查询：提供订单号即可查询实时物流',
  ARRAY['物流','快递','发货','包邮'], ARRAY['售后政策'], 5, 'published', 1, 'a0000000-0000-0000-0000-000000000005', NOW() - INTERVAL '12 days', NOW() - INTERVAL '12 days'
FROM platforms p WHERE p.code = 'tmall'
ON CONFLICT (id) DO NOTHING;

INSERT INTO knowledge_entries (id, category, platform_id, title, content, keywords, tags, priority, status, version, updated_by, created_at, updated_at)
SELECT 'e0000000-0000-0000-0000-000000000013', 'campaign', p.id, '新客专享活动',
  '新客首单礼：注册即领满200减50新人券（有效期30天） 首单赠品：下单即赠焕白精华7ml试用装 邀请有礼：邀请好友下单双方各获50积分（积分可兑换正装） 会员体系：消费1元=1积分，积分商城定期上新',
  ARRAY['新人','首单','优惠券','积分'], ARRAY['拉新活动'], 8, 'published', 1, 'a0000000-0000-0000-0000-000000000002', NOW() - INTERVAL '14 days', NOW() - INTERVAL '14 days'
FROM platforms p WHERE p.code = 'tmall'
ON CONFLICT (id) DO NOTHING;

INSERT INTO knowledge_entries (id, category, platform_id, title, content, keywords, tags, priority, status, version, updated_by, created_at, updated_at)
SELECT 'e0000000-0000-0000-0000-000000000014', 'product', p.id, '氨基酸洁面产品说明',
  '产品名称：氨基酸洁面乳 规格：120ml 主要成分：氨基酸表活+甘油+积雪草提取物 功效：温和清洁、不紧绷、修护屏障 适用肤质：所有肤质，尤其推荐敏感肌 起泡方式：湿手揉搓或搭配起泡网',
  ARRAY['洁面','氨基酸','温和','敏感肌'], ARRAY['基础护肤'], 6, 'published', 1, 'a0000000-0000-0000-0000-000000000002', NOW() - INTERVAL '25 days', NOW() - INTERVAL '25 days'
FROM platforms p WHERE p.code = 'tmall'
ON CONFLICT (id) DO NOTHING;

INSERT INTO knowledge_entries (id, category, platform_id, title, content, keywords, tags, priority, status, version, updated_by, created_at, updated_at)
SELECT 'e0000000-0000-0000-0000-000000000015', 'faq', p.id, '常见问题：真假辨别',
  '辨别正品方法：1. 扫描包装二维码可跳转官网验证 2. 正品包装有激光防伪标签 3. 正品瓶身底部有生产批号（可通过官网查询） 4. 我们每个批次都有质检报告，可联系客服索取 温馨提示：请认准官方旗舰店和授权店，非授权渠道无法保证正品',
  ARRAY['正品','真假','辨别','防伪'], ARRAY['FAQ','信任类'], 9, 'published', 2, 'a0000000-0000-0000-0000-000000000005', NOW() - INTERVAL '20 days', NOW() - INTERVAL '5 days'
FROM platforms p WHERE p.code = 'tmall'
ON CONFLICT (id) DO NOTHING;

-- ── Optimization Tasks (10 tasks) ──────────────────────────
INSERT INTO optimization_tasks (id, source, category, title, description, priority, status, platform_id, related_chat_id, related_knowledge_id, assigned_to, impact_estimate, created_by, created_at) VALUES
('f0000000-0000-0000-0000-000000000001', 'chat_inspection', '话术优化', '过敏投诉场景增加主动安抚话术', '质检发现多起过敏投诉中机器人回复缺少同理心，直接进入退换货流程。需要在首次回应中增加情绪安抚模板', 'critical', 'open', (SELECT id FROM platforms WHERE code='tmall'), 'b0000000-0000-0000-0000-000000000002', NULL, 'a0000000-0000-0000-0000-000000000005', '预计减少差评30%', 'a0000000-0000-0000-0000-000000000002', NOW() - INTERVAL '26 days'),
('f0000000-0000-0000-0000-000000000002', 'chat_inspection', '流程优化', '客服信息同步机制建立', '多客服转接时信息不共享导致客户重复描述问题。需要建立会话上下文传递机制', 'critical', 'in_progress', (SELECT id FROM platforms WHERE code='douyin'), 'b0000000-0000-0000-0000-000000000012', NULL, 'a0000000-0000-0000-0000-000000000005', '预计减少客户重复沟通时间50%', 'a0000000-0000-0000-0000-000000000002', NOW() - INTERVAL '17 days'),
('f0000000-0000-0000-0000-000000000003', 'inquiry_loss', '话术优化', '比价场景增加价值证明话术', '用户因价格疑虑流失。需要在比价回复中补充成分浓度对比、临床数据、用户口碑等价值证明', 'high', 'open', (SELECT id FROM platforms WHERE code='jd'), 'b0000000-0000-0000-0000-000000000024', NULL, 'a0000000-0000-0000-0000-000000000003', '预计提升转化率5%', 'a0000000-0000-0000-0000-000000000005', NOW() - INTERVAL '5 days'),
('f0000000-0000-0000-0000-000000000004', 'chat_inspection', '知识库更新', '补充防腐剂体系专业知识', '成分党客户询问防腐剂体系时机器人无法即时回答。需将各产品线的防腐体系加入知识库', 'medium', 'resolved', (SELECT id FROM platforms WHERE code='jd'), 'b0000000-0000-0000-0000-000000000024', 'e0000000-0000-0000-0000-000000000001', 'a0000000-0000-0000-0000-000000000005', '预计减少转人工率3%', 'a0000000-0000-0000-0000-000000000002', NOW() - INTERVAL '4 days'),
('f0000000-0000-0000-0000-000000000005', 'satisfaction', '流程优化', '差评补偿体系优化', '包装破损和发错货的补偿力度不足导致差评。建议将发错货补偿从30元提升至50元优惠券+免邮', 'high', 'open', (SELECT id FROM platforms WHERE code='pdd'), 'b0000000-0000-0000-0000-000000000023', NULL, 'a0000000-0000-0000-0000-000000000002', '预计减少差评率10%', 'a0000000-0000-0000-0000-000000000005', NOW() - INTERVAL '6 days'),
('f0000000-0000-0000-0000-000000000006', 'chat_inspection', '话术优化', '试用装缺失场景增加替代方案', '因无试用装导致客户流失。建议增加"可购买旅行装体验"或"建议先购买30ml小规格"的替代转化话术', 'high', 'open', (SELECT id FROM platforms WHERE code='douyin'), 'b0000000-0000-0000-0000-000000000004', NULL, 'a0000000-0000-0000-0000-000000000003', '预计减少流失率8%', 'a0000000-0000-0000-0000-000000000002', NOW() - INTERVAL '24 days'),
('f0000000-0000-0000-0000-000000000007', 'knowledge_gap', '知识库更新', '增加各肤质推荐产品矩阵', '多个会话中客户同时询问多个肤质适用性。建议建立"肤质×产品"推荐矩阵知识条目', 'medium', 'open', (SELECT id FROM platforms WHERE code='tmall'), NULL, NULL, 'a0000000-0000-0000-0000-000000000005', '预计减少会话轮次2-3轮', 'a0000000-0000-0000-0000-000000000002', NOW() - INTERVAL '7 days'),
('f0000000-0000-0000-0000-000000000008', 'manual', '流程优化', '抖音直播话术脚本定稿', '抖音直播带货脚本目前仍是draft状态。需要运营团队审核定稿并在下次直播中AB测试', 'medium', 'open', (SELECT id FROM platforms WHERE code='douyin'), NULL, 'e0000000-0000-0000-0000-000000000010', 'a0000000-0000-0000-0000-000000000004', '提升抖音渠道转化率', 'a0000000-0000-0000-0000-000000000005', NOW() - INTERVAL '3 days'),
('f0000000-0000-0000-0000-000000000009', 'satisfaction', '流程优化', '真假质疑场景增加信任背书', '客户质疑正品时机器人回复过于被动防御。需要增加品牌授权书展示、质检报告链接、防伪查询指引', 'high', 'in_progress', (SELECT id FROM platforms WHERE code='pdd'), 'b0000000-0000-0000-0000-000000000010', 'e0000000-0000-0000-0000-000000000015', 'a0000000-0000-0000-0000-000000000003', '预计减少信任类流失20%', 'a0000000-0000-0000-0000-000000000002', NOW() - INTERVAL '18 days'),
('f0000000-0000-0000-0000-000000000010', 'chat_inspection', '话术优化', '逾期未回复客户增加进度通知', '客户等待3天未收到回复导致严重投诉。建议增加自动"处理进度通知"卡片', 'critical', 'open', (SELECT id FROM platforms WHERE code='douyin'), 'b0000000-0000-0000-0000-000000000012', NULL, 'a0000000-0000-0000-0000-000000000003', '预计减少投诉升级率40%', 'a0000000-0000-0000-0000-000000000002', NOW() - INTERVAL '17 days')
ON CONFLICT (id) DO NOTHING;

-- ── Robot Reports (5 reports) ──────────────────────────────
INSERT INTO robot_reports (id, report_type, period_start, period_end, platform_id, summary_md, metrics, optimization_plan, generated_by, created_at) VALUES
('77777777-0000-0000-0000-000000000001', 'daily', '2026-05-13', '2026-05-13', NULL,
  '# 每日机器人运营报告\n\n## 核心指标\n- 总会话数: 31\n- 机器人处理率: 87%\n- 平均首响时间: 1.2s\n- 客户满意度: 4.1/5',
  '{"total_sessions":31,"bot_handle_rate":0.87,"avg_first_response_ms":1200,"satisfaction_avg":4.1,"conversion_rate":0.65,"complaint_count":3}',
  '1. 本周完成过敏安抚话术A/B测试 2. 与仓库确认包装加固方案', 'auto', NOW() - INTERVAL '1 day'),
('77777777-0000-0000-0000-000000000002', 'daily', '2026-05-12', '2026-05-12', NULL,
  '# 每日机器人运营报告\n\n## 核心指标\n- 总会话数: 28\n- 机器人处理率: 85%\n- 客户满意度: 4.0/5\n\n## 预警\n- 抖音渠道2起投诉升级',
  '{"total_sessions":28,"bot_handle_rate":0.85,"avg_first_response_ms":1400,"satisfaction_avg":4.0,"conversion_rate":0.60,"complaint_count":5}',
  '1. 优化退款进度自动推送 2. 检查抖音售后SLA是否达标', 'auto', NOW() - INTERVAL '2 days'),
('77777777-0000-0000-0000-000000000003', 'daily', '2026-05-11', '2026-05-11', NULL,
  '# 每日机器人运营报告\n\n## 核心指标\n- 总会话数: 25\n- 机器人处理率: 88%\n- 客户满意度: 4.2/5\n\n## 亮点\n- 拼多多渠道转化率创新高达75%',
  '{"total_sessions":25,"bot_handle_rate":0.88,"avg_first_response_ms":1100,"satisfaction_avg":4.2,"conversion_rate":0.68,"complaint_count":2}',
  '继续推广老客专属优惠码', 'auto', NOW() - INTERVAL '3 days'),
('77777777-0000-0000-0000-000000000004', 'weekly', '2026-05-04', '2026-05-10', NULL,
  '# 周报 (W19)\n\n## 概览\n- 总会话数: 187\n- 机器人处理率: 86%\n- 客户满意度: 4.0/5\n- 转化率: 62%\n\n## 渠道对比\n| 渠道 | 满意度 | 转化率 |\n|------|--------|--------|\n| 天猫 | 4.1 | 65% |\n| 京东 | 4.2 | 60% |\n| 抖音 | 3.8 | 55% |\n| 拼多多 | 3.9 | 72% |\n| 小红书 | 4.5 | 70% |',
  '{"total_sessions":187,"bot_handle_rate":0.86,"satisfaction_avg":4.0,"conversion_rate":0.62}',
  '1. 过敏安抚话术A/B测试 2. 物流催款自动推送 3. 比价场景价值证明', 'auto', NOW() - INTERVAL '4 days'),
('77777777-0000-0000-0000-000000000005', 'monthly', '2026-04-01', '2026-04-30', NULL,
  '# 月报 (2026年4月)\n\n## 月度概览\n- 总会话数: 742\n- 机器人处理率: 85%\n- 客户满意度: 4.0/5\n- 转化率: 61%\n\n## 行业对标\n| 指标 | 我们 | 行业平均 | 行业Top |\n|------|------|----------|--------|\n| 满意度 | 4.0 | 3.8 | 4.5 |\n| 首响时间 | 1.2s | 3.0s | 1.0s |',
  '{"total_sessions":742,"bot_handle_rate":0.85,"satisfaction_avg":4.0,"conversion_rate":0.61,"transfer_rate":0.15}',
  '5月重点：过敏安抚话术+抖音售后SLA+跨客服信息同步', 'auto', NOW() - INTERVAL '14 days')
ON CONFLICT (id) DO NOTHING;

-- ── Knowledge Update Logs (8 logs) ─────────────────────────
INSERT INTO knowledge_update_logs (id, knowledge_id, update_type, field_changed, old_value, new_value, updated_by, correlation_id, created_at) VALUES
('99999999-0000-0000-0000-000000000001', 'e0000000-0000-0000-0000-000000000005', 'update', 'content', '退换货政策v1', '退换货政策v2（增加发错货和补偿细则）', 'a0000000-0000-0000-0000-000000000002', 'corr-update-001', NOW() - INTERVAL '10 days'),
('99999999-0000-0000-0000-000000000002', 'e0000000-0000-0000-0000-000000000015', 'update', 'content', '真假辨别v1', '真假辨别v2（增加激光防伪标签和质检报告说明）', 'a0000000-0000-0000-0000-000000000005', 'corr-update-002', NOW() - INTERVAL '5 days'),
('99999999-0000-0000-0000-000000000003', 'e0000000-0000-0000-0000-000000000007', 'create', NULL, NULL, NULL, 'a0000000-0000-0000-0000-000000000002', 'corr-create-003', NOW() - INTERVAL '15 days'),
('99999999-0000-0000-0000-000000000004', 'e0000000-0000-0000-0000-000000000011', 'publish', NULL, 'draft', 'published', 'a0000000-0000-0000-0000-000000000002', 'corr-publish-004', NOW() - INTERVAL '10 days'),
('99999999-0000-0000-0000-000000000005', 'e0000000-0000-0000-0000-000000000013', 'create', NULL, NULL, NULL, 'a0000000-0000-0000-0000-000000000002', 'corr-create-005', NOW() - INTERVAL '14 days'),
('99999999-0000-0000-0000-000000000006', 'e0000000-0000-0000-0000-000000000009', 'create', NULL, NULL, NULL, 'a0000000-0000-0000-0000-000000000005', 'corr-create-006', NOW() - INTERVAL '18 days'),
('99999999-0000-0000-0000-000000000007', 'e0000000-0000-0000-0000-000000000008', 'create', NULL, NULL, NULL, 'a0000000-0000-0000-0000-000000000002', 'corr-create-007', NOW() - INTERVAL '20 days'),
('99999999-0000-0000-0000-000000000008', 'e0000000-0000-0000-0000-000000000012', 'publish', NULL, 'draft', 'published', 'a0000000-0000-0000-0000-000000000005', 'corr-publish-008', NOW() - INTERVAL '12 days')
ON CONFLICT (id) DO NOTHING;

-- ── Audit Logs (12 logs) ──────────────────────────────────
INSERT INTO audit_logs (id, action, user_id, user_name, resource_type, resource_id, detail, correlation_id, created_at) VALUES
('88888888-0000-0000-0000-000000000001', 'evaluate', 'a0000000-0000-0000-0000-000000000003', '王芳', 'quality_report', 'c0000000-0000-0000-0000-000000000001', '{"score":92,"risk":"low","violations":0}', 'corr-audit-001', NOW() - INTERVAL '27 days'),
('88888888-0000-0000-0000-000000000002', 'evaluate', 'a0000000-0000-0000-0000-000000000004', '赵强', 'quality_report', 'c0000000-0000-0000-0000-000000000002', '{"score":45,"risk":"high","violations":3}', 'corr-audit-002', NOW() - INTERVAL '27 days'),
('88888888-0000-0000-0000-000000000003', 'knowledge_create', 'a0000000-0000-0000-0000-000000000002', '李婷', 'knowledge_entry', 'e0000000-0000-0000-0000-000000000007', '{"category":"campaign","title":"618年中大促活动规则"}', 'corr-audit-003', NOW() - INTERVAL '15 days'),
('88888888-0000-0000-0000-000000000004', 'knowledge_update', 'a0000000-0000-0000-0000-000000000005', '陈雪', 'knowledge_entry', 'e0000000-0000-0000-0000-000000000015', '{"field":"content","reason":"增加防伪信息"}', 'corr-audit-004', NOW() - INTERVAL '5 days'),
('88888888-0000-0000-0000-000000000005', 'optimization_task_create', 'a0000000-0000-0000-0000-000000000002', '李婷', 'optimization_task', 'f0000000-0000-0000-0000-000000000001', '{"source":"chat_inspection","priority":"critical"}', 'corr-audit-005', NOW() - INTERVAL '26 days'),
('88888888-0000-0000-0000-000000000006', 'optimization_task_create', 'a0000000-0000-0000-0000-000000000002', '李婷', 'optimization_task', 'f0000000-0000-0000-0000-000000000002', '{"source":"chat_inspection","priority":"critical"}', 'corr-audit-006', NOW() - INTERVAL '17 days'),
('88888888-0000-0000-0000-000000000007', 'bot_config_create', 'a0000000-0000-0000-0000-000000000002', '李婷', 'bot_config', 'd0000000-0000-0000-0000-000000000003', '{"config_type":"post_sale","key":"return_policy"}', 'corr-audit-007', NOW() - INTERVAL '30 days'),
('88888888-0000-0000-0000-000000000008', 'bot_config_activate', 'a0000000-0000-0000-0000-000000000002', '李婷', 'bot_config', 'd0000000-0000-0000-0000-000000000001', '{"config_type":"pre_sale","key":"greeting_template"}', 'corr-audit-008', NOW() - INTERVAL '30 days'),
('88888888-0000-0000-0000-000000000009', 'report_generate', NULL, 'system', 'robot_report', '77777777-0000-0000-0000-000000000001', '{"report_type":"daily","period":"2026-05-13"}', 'corr-audit-009', NOW() - INTERVAL '1 day'),
('88888888-0000-0000-0000-000000000010', 'report_generate', NULL, 'system', 'robot_report', '77777777-0000-0000-0000-000000000004', '{"report_type":"weekly","period":"2026-W19"}', 'corr-audit-010', NOW() - INTERVAL '4 days'),
('88888888-0000-0000-0000-000000000011', 'login', 'a0000000-0000-0000-0000-000000000001', '张明', NULL, NULL, NULL, 'corr-audit-011', NOW() - INTERVAL '1 day'),
('88888888-0000-0000-0000-000000000012', 'evaluate', 'a0000000-0000-0000-0000-000000000003', '王芳', 'quality_report', 'c0000000-0000-0000-0000-000000000017', '{"score":40,"risk":"critical","violations":2}', 'corr-audit-012', NOW() - INTERVAL '12 days')
ON CONFLICT (id) DO NOTHING;

-- ── Bad Cases (3 cases for overturned reports) ────────────
INSERT INTO bad_cases (id, quality_report_id, original_judgment, corrected_judgment, overturn_reason, corrected_by, created_at) VALUES
('55555555-0000-0000-0000-000000000001', 'c0000000-0000-0000-0000-000000000005',
  '{"score":35,"violations":[{"rule":"补偿方案不足","deduction":15},{"rule":"未主动道歉安抚","deduction":10},{"rule":"未提供升级路径","deduction":5}],"risk_level":"critical"}',
  '{"score":45,"violations":[{"rule":"补偿方案不足","deduction":15},{"rule":"未提供升级路径","deduction":5}],"risk_level":"high"}',
  '客户发错货场景中机器人已进行了道歉（"确实是我们仓库发错了，非常抱歉！"），"未主动道歉安抚"扣分不合理',
  'a0000000-0000-0000-0000-000000000002', NOW() - INTERVAL '23 days'),
('55555555-0000-0000-0000-000000000002', 'c0000000-0000-0000-0000-000000000010',
  '{"score":52,"violations":[{"rule":"未有效消除客户疑虑","deduction":15},{"rule":"语气过于被动防御","deduction":10},{"rule":"未主动提供解决方案","deduction":8}],"risk_level":"high"}',
  '{"score":62,"violations":[{"rule":"未有效消除客户疑虑","deduction":15},{"rule":"语气过于被动防御","deduction":10}],"risk_level":"medium"}',
  '机器人已提供退货方案和质检报告获取方式，"未主动提供解决方案"不成立',
  'a0000000-0000-0000-0000-000000000005', NOW() - INTERVAL '18 days'),
('55555555-0000-0000-0000-000000000003', 'c0000000-0000-0000-0000-000000000023',
  '{"score":72,"violations":[{"rule":"未挽留因券流失客户","deduction":12},{"rule":"缺少灵活应对方案","deduction":10}],"risk_level":"high"}',
  '{"score":82,"violations":[{"rule":"缺少灵活应对方案","deduction":10}],"risk_level":"medium"}',
  '新人券有固定使用门槛，机器人已清楚解释规则并给出凑单建议。在平台规则硬性约束下，"未挽留"不应视为机器人问题',
  'a0000000-0000-0000-0000-000000000002', NOW() - INTERVAL '1 day')
ON CONFLICT (id) DO NOTHING;
