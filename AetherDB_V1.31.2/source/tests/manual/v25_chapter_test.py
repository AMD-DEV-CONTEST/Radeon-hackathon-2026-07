import sqlite3, json

conn = sqlite3.connect('novel_world_zh.db')
conn.row_factory = sqlite3.Row
c = conn.cursor()

print('=== PRE-INSERTION STATE ===')
e = c.execute('SELECT COUNT(*) FROM entities').fetchone()[0]
r = c.execute('SELECT COUNT(*) FROM relations').fetchone()[0]
t = c.execute('SELECT COUNT(*) FROM tag_index').fetchone()[0]
print(f'  Entities: {e}, Relations: {r}, Tags: {t}')

# Chapter 25 new entities
entities = [
    ('CHR_0015', 'character', '村长', 6, '青石村村长，关心村民，不过问雪的任务。', ['青石村', '平民']),
    ('CHR_0016', 'character', '金丹护卫', 5, '新兴家族金丹护卫，忠诚派夜袭中未全力死战以保全家族。', ['护卫', '家族']),
    ('CHR_0017', 'character', '断臂修士', 5, '被叛军俘虏的忠诚派残部，囚营中被救出。', ['忠诚派', '残部']),
    ('CHR_0018', 'character', '镇丞', 4, '镇令死后幸存的地方官员，被叛军看管。', ['地方官', '幸存者']),
    ('CHR_0019', 'character', '叛军筑基军官', 5, '负责押运的叛军军官，连夜写了三份不同版本的上报文书。', ['叛军', '军官']),
    ('EVT_0003', 'event', '南仓之战', 8, '忠诚派对南仓发动正面攻击，摧毁粮草军械，切断运输石桥。', ['军事行动', '忠诚派']),
    ('EVT_0004', 'event', '囚营解救', 7, '忠诚派救出被俘残部，使用红烧肉暗号确认身份。', ['营救', '忠诚派']),
    ('EVT_0005', 'event', '雪回归青石村', 5, '雪完成任务后绕远路返回，村民以平常心接纳。', ['回归', '日常']),
    ('ITM_0003', 'item', '灵石袋', 4, '忠诚派支付给雪的任务报酬。老铁匠让雪收下。', ['报酬', '灵石']),
]

for eid, etype, title, imp, content, tags in entities:
    tags_json = json.dumps(tags, ensure_ascii=False)
    c.execute('INSERT OR IGNORE INTO entities (entity_id,entity_type,title,content,importance,tags) VALUES (?,?,?,?,?,?)',
              (eid, etype, title, content, imp, tags_json))

# Chapter 25 relations
relations = [
    ('EVT_0003', 'LOC_0002', '发生于附近', '南仓之战发生在青石村附近的镇子'),
    ('EVT_0003', 'FAC_0003', '执行者', '忠诚派执行了南仓之战'),
    ('EVT_0004', 'FAC_0003', '执行者', '忠诚派执行了囚营解救'),
    ('EVT_0004', 'CHR_0017', '救出', '断臂修士等被俘忠诚派被救出'),
    ('EVT_0005', 'CHR_0010', '主角', '雪回归青石村'),
    ('EVT_0005', 'LOC_0002', '发生于', '回归发生在青石村'),
    ('CHR_0010', 'CHR_0015', '被接应', '村长接应雪回村'),
    ('CHR_0015', 'LOC_0002', '管辖', '村长管辖青石村'),
    ('CHR_0016', 'FAC_0004', '服务', '金丹护卫为叛军区域势力服务'),
    ('CHR_0019', 'FAC_0004', '属于', '叛军筑基军官属于叛军'),
    ('CHR_0018', 'FAC_0004', '被看管', '镇丞被叛军看管'),
    ('ITM_0003', 'CHR_0010', '报酬于', '灵石袋是忠诚派给雪的报酬'),
    ('ITM_0003', 'CHR_0014', '转交', '老铁匠代收并转交灵石袋'),
    ('EVT_0003', 'EVT_0001', '后续', '南仓之战是镇令刺杀的后续行动'),
]

for src, tgt, rtype, desc in relations:
    c.execute('INSERT OR IGNORE INTO relations (source_id,target_id,relation_type,description) VALUES (?,?,?,?)',
              (src, tgt, rtype, desc))

conn.commit()

print()
print('=== POST-INSERTION STATE ===')
e = c.execute('SELECT COUNT(*) FROM entities').fetchone()[0]
r = c.execute('SELECT COUNT(*) FROM relations').fetchone()[0]
t = c.execute('SELECT COUNT(*) FROM tag_index').fetchone()[0]
print(f'  Entities: {e}, Relations: {r}, Tags: {t}')

print()
print('=== CHAPTER 25 NEW ENTITIES ===')
rows = c.execute('SELECT entity_id, title, entity_type, importance FROM entities WHERE entity_id LIKE ? OR entity_id IN (?,?,?,?) ORDER BY entity_id',
                 ('CHR_001%', 'EVT_0003', 'EVT_0004', 'EVT_0005', 'ITM_0003')).fetchall()
for row in rows:
    print(f'  {row[0]}: [{row[2]}] imp={row[3]} {row[1]}')

print()
print('=== CHAPTER 25 RELATIONS ===')
rows = c.execute('''SELECT e1.title as s, r.relation_type as rt, e2.title as t
    FROM relations r
    JOIN entities e1 ON r.source_id=e1.entity_id
    JOIN entities e2 ON r.target_id=e2.entity_id
    WHERE r.id > 42 ORDER BY r.id''').fetchall()
for row in rows:
    print(f'  {row[0]} --[{row[1]}]--> {row[2]}')

print()
print('=== CROSS-CHAPTER VERIFICATION ===')
e = c.execute('SELECT COUNT(*) FROM entities').fetchone()[0]
r = c.execute('SELECT COUNT(*) FROM relations').fetchone()[0]
t = c.execute('SELECT COUNT(*) FROM tag_index').fetchone()[0]
et = c.execute('SELECT COUNT(DISTINCT entity_type) FROM entities').fetchone()[0]
rt = c.execute('SELECT COUNT(DISTINCT relation_type) FROM relations').fetchone()[0]
print(f'  Total: {e} entities, {r} relations, {t} tags')
print(f'  Entity types: {et}, Relation types: {rt}')

conn.close()
