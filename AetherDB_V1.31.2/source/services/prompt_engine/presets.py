"""Built-in profiles."""
BUILTIN_PROFILES = [
    {"profile_id":"default_general","name":"通用默认","content":"从文本提取实体和关系。只输出JSON。"},
    {"profile_id":"cultivation_xuanhuan","name":"修仙玄幻","content":"额外识别境界、功法、丹药。"},
    {"profile_id":"sci_fi","name":"科幻星际","content":"额外识别科技、组织、星舰。"},
    {"profile_id":"creative_author","name":"创作者模式","content":"保留原文情感和叙事结构。"},
    {"profile_id":"reader_import","name":"读者导入","content":"快速提取核心实体，重要性>=3的保留。"},
]
def get_builtin_profiles(): return list(BUILTIN_PROFILES)
