import sqlite3, json

conn = sqlite3.connect('novel_world_zh.db')
conn.row_factory = sqlite3.Row
c = conn.cursor()

# ===================== DATA POPULATION =====================
# Entities from Chapter 30 text
entities = [
    # Characters
    ('CHR_0010', 'character', '雪', 9, '十四岁银牌杀手，忠诚派任务执行者。出身不明，非此界大陆之人，具有特殊战斗体系。', ['主角', '杀手']),
    ('CHR_0011', 'character', '老乞丐', 8, '忠诚派重要人物，曾是军中人。身着旧军袍，平日伪装为乞丐。', ['忠诚派', '军旅']),
    ('CHR_0012', 'character', '皇子', 8, '忠诚派主事者，约十五岁。少年老成，气质安静。非老狐狸型领袖。', ['忠诚派', '皇室']),
    ('CHR_0013', 'character', '青衣', 9, '曙光号导航AI，管理纳米机器人与工业体系。当前流落异星，以空投方式支援地面。', ['AI', '联邦']),
    ('CHR_0014', 'character', '老铁匠', 7, '青石村铁匠，知晓雪的来历。实力深不可测。', ['青石村', '隐者']),
    
    # Factions
    ('FAC_0003', 'faction', '忠诚派', 8, '反对叛军的抵抗势力，由旧皇族、旧部、忠于旧制度的修士组成。当前以旧山城为临时据点。', ['反抗军', '复国']),
    ('FAC_0004', 'faction', '叛军', 7, '当前控制大部分地区的反叛势力。正在调查镇令被杀事件。', ['叛军', '敌对']),
    
    # Locations
    ('LOC_0001', 'location', '旧山城', 6, '忠诚派临时议事处设在的一处旧山城。城墙多处破损，内有暗道通往地下议事厅。', ['忠诚派据点', '要塞']),
    ('LOC_0002', 'location', '青石村', 7, '雪当前居住的村庄。老铁匠所在之地。忠诚派承诺不监视此地。', ['村庄', '庇护所']),
    ('LOC_0003', 'location', '旧矿带', 7, '雪与青衣建立的纳米工业基地。位于废弃矿带，正在建立第一条生产线。', ['矿区', '工业基地']),
    
    # Items
    ('ITM_0001', 'item', '玉简', 5, '记载叛军运输路线、税粮分配、军械转运、押运人手等情报的信息载体。', ['情报', '证据']),
    ('ITM_0002', 'item', '守望者', 8, '曙光号配备的作战机甲，具备长距离飞行、光学迷彩、裂解射线枪等能力。', ['机甲', '联邦装备']),
    
    # Events
    ('EVT_0001', 'event', '镇令刺杀', 8, '雪执行忠诚派任务，刺杀叛军控制区镇令。行动干净利落，使用纯粹灵气爆发而非法术。', ['刺杀', '忠诚派行动']),
    ('EVT_0002', 'event', '第三空投', 8, '青衣从曙光号投放第三批物资，包括微型矿机、纳米机器人补充包和旧反应堆堆芯。', ['空投', '补给']),
    
    # Concepts
    ('CON_0020', 'concept', '纳米机器人', 9, '联邦微型工业机器人，可执行精密制造、物质分离、结构加固等任务。当前数量有限。', ['联邦科技', '工业']),
    ('CON_0021', 'concept', '星型多点约束反应堆', 9, '青衣基于联邦数据库设计的新型反应堆。多个局部反应区维持可控反应。首枚结构环已成形。', ['科技', '能源']),
]

for eid, etype, title, imp, content, tags in entities:
    c.execute('INSERT OR IGNORE INTO entities (entity_id, entity_type, title, content, importance, tags) VALUES (?,?,?,?,?,?)',
              (eid, etype, title, content, imp, json.dumps(tags, ensure_ascii=False)))

# Relations
relations = [
    ('CHR_0010', 'FAC_0003', '合作于', '雪与忠诚派以任务体系合作，非上下级关系'),
    ('CHR_0011', 'FAC_0003', '属于', '老乞丐是忠诚派核心成员'),
    ('CHR_0012', 'FAC_0003', '领导', '皇子是忠诚派主事者'),
    ('CHR_0013', 'LOC_0003', '控制', '青衣通过纳米机器人控制旧矿带生产基地'),
    ('CHR_0010', 'LOC_0002', '居住于', '雪当前居住在青石村'),
    ('CHR_0014', 'LOC_0002', '居住于', '老铁匠居住在青石村'),
    ('FAC_0003', 'LOC_0001', '占据', '忠诚派以旧山城为临时议事处'),
    ('LOC_0003', 'LOC_0002', '位于', '旧矿带位于青石村东南三十七里'),
    ('EVT_0001', 'CHR_0010', '执行者', '雪执行了镇令刺杀任务'),
    ('EVT_0002', 'CHR_0013', '操作者', '青衣操作了第三空投'),
    ('EVT_0002', 'LOC_0003', '目标', '第三空投降落在旧矿带'),
    ('CHR_0010', 'FAC_0004', '敌对', '雪与叛军敌对'),
    ('ITM_0001', 'CHR_0010', '获取者', '雪从镇令府获取了玉简和账簿'),
    ('ITM_0002', 'CHR_0013', '操控者', '青衣操控守望者'),
    ('CON_0020', 'LOC_0003', '部署于', '纳米机器人部署在旧矿带'),
    ('CON_0021', 'LOC_0003', '建造于', '星型多点约束反应堆在旧矿带建造'),
]

for src, tgt, rtype, desc in relations:
    c.execute('INSERT OR IGNORE INTO relations (source_id, target_id, relation_type, description) VALUES (?,?,?,?)',
              (src, tgt, rtype, desc))

conn.commit()
print('Data populated')

# ===================== VERIFICATION =====================
print()
print('=== ENTITIES (Chapter 30) ===')
for r in c.execute('SELECT entity_id, title, entity_type, importance FROM entities WHERE entity_id LIKE \"CHR_001%\" OR entity_id LIKE \"FAC_000%\" OR entity_id IN (\"LOC_0001\",\"LOC_0002\",\"LOC_0003\",\"ITM_0001\",\"ITM_0002\",\"EVT_0001\",\"EVT_0002\",\"CON_0020\",\"CON_0021\") ORDER BY entity_id').fetchall():
    print('  ' + r['entity_id'] + ': [' + r['entity_type'] + '] ' + r['title'])

print()
print('=== CHAPTER 30 RELATIONS ===')
for r in c.execute('SELECT r.source_id, r.target_id, r.relation_type, e1.title as s_title, e2.title as t_title FROM relations r JOIN entities e1 ON r.source_id=e1.entity_id JOIN entities e2 ON r.target_id=e2.entity_id WHERE r.id > 26 ORDER BY r.id').fetchall():
    print('  ' + r['s_title'] + ' --[' + r['relation_type'] + ']--> ' + r['t_title'])

print()
e = c.execute('SELECT COUNT(*) FROM entities').fetchone()[0]
r = c.execute('SELECT COUNT(*) FROM relations').fetchone()[0]
t = c.execute('SELECT COUNT(*) FROM tag_index').fetchone()[0]
print('DATABASE: ' + str(e) + ' entities, ' + str(r) + ' relations, ' + str(t) + ' tags')

conn.close()
