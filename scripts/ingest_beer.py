"""Ingest the beer story (zhihu/beer.md) into the story graph."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from memory.story_graph import StoryGraphBuilder, reconstruct_narrative


def ingest_beer_story():
    builder = StoryGraphBuilder("啤酒故事")

    # ─── Entities ───────────────────────────────────────────
    # People
    builder.add_entity("父亲", "person", "工地工人，膝盖有伤，只在工地喝啤酒")
    builder.add_entity("儿子", "person", "父亲的孩子，高考后跟父亲去了工地")
    builder.add_entity("我", "person", "儿子的朋友，故事叙述者，同样去了工地")
    builder.add_entity("工友", "person", "工地上的其他工人")
    builder.add_entity("亲戚", "person", "春节时搬来两箱啤酒的亲戚")

    # Objects
    builder.add_entity("啤酒", "object", "特定品牌，父亲只在工地喝，在家从不碰")
    builder.add_entity("盒饭", "object", "工地十五块钱的盒饭，米饭压得很实，土豆豆芽和肥肉")
    builder.add_entity("安全帽", "object", "工人的防护装备")
    builder.add_entity("膏药", "object", "父亲膝盖上贴的膏药，边缘被汗泡得发白")
    builder.add_entity("瓦刀", "object", "父亲的工作工具")
    builder.add_entity("帆布包", "object", "父亲装工具的包")
    builder.add_entity("手套", "object", "搬砖用的手套，虎口磨开后汗流进去像针扎")

    # Places
    builder.add_entity("工地", "place", "刚封顶的大楼，没有窗户，水泥地面烫得鞋底发软")
    builder.add_entity("毛坯房", "place", "工人中午吃饭休息的背阴房间")
    builder.add_entity("家", "place", "父亲的家，在那里的啤酒从来不碰")
    builder.add_entity("宿舍", "place", "父亲在工地的宿舍")
    builder.add_entity("邻居家", "place", "需要翻修院墙的邻居")

    # Body parts / sensations
    builder.add_entity("膝盖", "body_part", "父亲的膝盖，贴着膏药，退休原因")
    builder.add_entity("虎口", "body_part", "搬砖磨开的虎口")
    builder.add_entity("汗", "feeling", "劳动中的汗水")

    # Concepts
    builder.add_entity("劳动身份", "concept", "通过劳动定义的自我身份认同")
    builder.add_entity("仪式", "concept", "工地中午喝啤酒是一种日常仪式而非享受")
    builder.add_entity("父子关系", "concept", "父亲和儿子之间含蓄而深沉的关系")
    builder.add_entity("阶层", "concept", "体力劳动者的生活状态和困境")
    builder.add_entity("生活必需品", "concept", "啤酒是让饭能咽下去的工具，不是享受")

    # ─── Events (in temporal order) ─────────────────────────
    builder.add_event(
        "日常劳作", "父亲在工地干活，每天中午吃饭时喝一瓶啤酒", order=1, time_period="多年"
    )
    builder.add_event(
        "春节拒酒", "春节亲戚搬来两箱啤酒，父亲让人原样搬回去", order=2, time_period="某年春节"
    )
    builder.add_event(
        "高考后打工",
        "我和儿子高考结束后跟着父亲去工地做了十一天小工",
        order=3,
        time_period="高考后",
    )
    builder.add_event(
        "第一次工地午餐", "中午在毛坯房吃盒饭，父亲用瓶盖开啤酒", order=4, time_period="第一天"
    )
    builder.add_event(
        "对话啤酒的意义",
        "儿子问啤酒真能解乏吗，父亲说不能，饭太干",
        order=5,
        time_period="第一天午餐",
    )
    builder.add_event(
        "中年的午休", "工人吃完饭靠着墙就躺下，一共休息四十分钟", order=6, time_period="每天中午"
    )
    builder.add_event(
        "下午继续劳作", "下午开工，父亲先扶着墙活动了两下膝盖", order=7, time_period="每天下午"
    )
    builder.add_event(
        "体力不支",
        "第十一天我的手肿得握不住筷子，儿子腰也直不起来",
        order=8,
        time_period="第十一天",
    )
    builder.add_event(
        "离开工地",
        "父亲让我们回去，说再干下去挣的钱还不够看手",
        order=9,
        time_period="第十二天早上",
    )
    builder.add_event(
        "儿子买酒", "儿子买了一箱啤酒搬到父亲宿舍床底下，父亲说会丢", order=10, time_period="离开前"
    )
    builder.add_event(
        "酒被带回",
        "一个月后父亲回家，那箱啤酒被带回来，只少了五瓶",
        order=11,
        time_period="一个月后",
    )
    builder.add_event(
        "因伤退休", "父亲膝盖越来越差，不再出去干活，在家种菜修水管", order=12, time_period="后来"
    )
    builder.add_event(
        "在家不喝酒", "儿子专门买了那个牌子，父亲喝了一口皱着眉放下", order=13, time_period="在家时"
    )
    builder.add_event(
        "啤酒过期", "剩下的十一瓶在冰箱里全部过期，只开了一瓶", order=14, time_period="后来"
    )
    builder.add_event(
        "最后一瓶酒",
        "邻居家翻修院墙，父亲换上旧衣服装好工具，从冰箱拿出一瓶啤酒塞进工具中间",
        order=15,
        time_period="某天",
    )

    # ─── Relationships ──────────────────────────────────────
    builder.relate("父亲", "儿子", "parent_of", "父亲和儿子的关系")
    builder.relate("儿子", "我", "friend_of", "儿子和我是朋友，一起去工地")
    builder.relate("父亲", "工友", "colleague_of", "父亲和工友的关系")
    builder.relate("父亲", "啤酒", "daily_ritual_with", "每天中午在工地喝一瓶啤酒")
    builder.relate("父亲", "盒饭", "eats", "中午吃工地盒饭")
    builder.relate("父亲", "膏药", "wears", "膝盖贴着膏药继续干活")
    builder.relate("啤酒", "工地", "consumed_at", "啤酒只在工地喝")
    builder.relate("啤酒", "家", "refused_at", "在家从不喝酒")
    builder.relate("父亲", "工地", "works_at", "在工地干活")
    builder.relate("父亲", "家", "lives_at", "住在家里")
    builder.relate("父亲", "膝盖", "has_injury", "膝盖有伤病")

    # ─── Event participation ────────────────────────────────
    builder.participate("父亲", "日常劳作", "主体")
    builder.participate("啤酒", "日常劳作", "伴随物")
    builder.participate("工地", "日常劳作", "地点")
    builder.participate("父亲", "春节拒酒", "主体")
    builder.participate("啤酒", "春节拒酒", "涉及物")
    builder.participate("亲戚", "春节拒酒", "参与者")
    builder.participate("父亲", "高考后打工", "主体")
    builder.participate("儿子", "高考后打工", "参与者")
    builder.participate("我", "高考后打工", "参与者")
    builder.participate("父亲", "第一次工地午餐", "主体")
    builder.participate("儿子", "第一次工地午餐", "参与者")
    builder.participate("我", "第一次工地午餐", "参与者")
    builder.participate("啤酒", "第一次工地午餐", "伴随物")
    builder.participate("盒饭", "第一次工地午餐", "伴随物")
    builder.participate("毛坯房", "第一次工地午餐", "地点")
    builder.participate("父亲", "对话啤酒的意义", "主体")
    builder.participate("儿子", "对话啤酒的意义", "参与者")
    builder.participate("啤酒", "对话啤酒的意义", "话题")
    builder.participate("父亲", "中年的午休", "主体")
    builder.participate("工友", "中年的午休", "参与者")
    builder.participate("毛坯房", "中年的午休", "地点")
    builder.participate("父亲", "下午继续劳作", "主体")
    builder.participate("膝盖", "下午继续劳作", "影响部位")
    builder.participate("膏药", "下午继续劳作", "伴随物")
    builder.participate("儿子", "体力不支", "主体")
    builder.participate("我", "体力不支", "主体")
    builder.participate("父亲", "离开工地", "主体")
    builder.participate("儿子", "离开工地", "参与者")
    builder.participate("我", "离开工地", "参与者")
    builder.participate("儿子", "儿子买酒", "主体")
    builder.participate("啤酒", "儿子买酒", "涉及物")
    builder.participate("父亲", "酒被带回", "主体")
    builder.participate("啤酒", "酒被带回", "涉及物")
    builder.participate("父亲", "因伤退休", "主体")
    builder.participate("膝盖", "因伤退休", "原因")
    builder.participate("父亲", "在家不喝酒", "主体")
    builder.participate("啤酒", "在家不喝酒", "涉及物")
    builder.participate("家", "在家不喝酒", "地点")
    builder.participate("啤酒", "最后一瓶酒", "核心物")
    builder.participate("父亲", "最后一瓶酒", "主体")
    builder.participate("瓦刀", "最后一瓶酒", "伴随物")
    builder.participate("帆布包", "最后一瓶酒", "伴随物")

    # ─── Symbolic relationships ─────────────────────────────
    builder.symbol("啤酒", "劳动身份", "啤酒只属于工地，是劳动身份的标志")
    builder.symbol("啤酒", "仪式", "每天中午一瓶啤酒是一种重复的日常仪式")
    builder.symbol("啤酒", "生活必需品", "饭太干，啤酒是用来把饭咽下去的工具")
    builder.symbol("膏药", "劳动身份", "膝盖上的膏药是体力劳动的代价")

    # ─── Build ──────────────────────────────────────────────
    print("Building beer story graph...")
    builder.build()
    print("Done!")

    # ─── Test reconstruction ────────────────────────────────
    print("\n=== 故事回顾 (啤酒) ===")
    narrative = reconstruct_narrative("啤酒")
    print(narrative)


if __name__ == "__main__":
    ingest_beer_story()
