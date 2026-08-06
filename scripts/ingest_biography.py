"""Ingest a biography (陈明远) into the story graph to test v2 schema."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from memory.story_graph import StoryGraphBuilder, clear_story_data, reconstruct_narrative


def main():
    clear_story_data()
    builder = StoryGraphBuilder("陈明远传")

    # ─── Phases ────────────────────────────────────────────
    builder.add_phase("童年渔村", "浙江渔村，看潮汐长大，父亲是修船的木匠", order=1)
    builder.add_phase("求学之路", "上海水产学院海洋系，村里第一个大学生", order=2)
    builder.add_phase("深海岁月", "青岛海洋研究所，从废潜艇上拆零件建实验室", order=3)
    builder.add_phase("医院长廊", "妻子林小华肝癌晚期，在病房走廊里改论文", order=4)
    builder.add_phase("孤峰突破", "妻子去世后，一个人完成了6000米深海传感器", order=5)
    builder.add_phase("渔村归途", "退休回村，教孩子们机械制图", order=6)

    # ─── Entities ──────────────────────────────────────────
    # People
    builder.add_entity("陈明远", "person", "1957-2023，海洋科学家")
    builder.add_entity("林小华", "person", "陈明远的妻子，肝癌去世")
    builder.add_entity("陈雨", "person", "陈明远的女儿，在美国做硅片工程师")
    builder.add_entity("小海", "person", "渔村十二岁男孩，陈明远最后的徒弟")

    # Traits
    builder.add_entity("专注", "trait", "可以在一堆破烂里坐一整个冬天")
    builder.add_entity("倔强", "trait", "不走下海路，不碰二手设备")
    builder.add_entity("沉默的骄傲", "trait", "水压测试成功时一个人去海边坐到天黑")

    # Objects
    builder.add_entity("水压测试台", "object", "从退役潜艇上拆下的舱壁做的")
    builder.add_entity("三本手写册子", "object", "临终前给小海的机械制图和深海笔记")
    builder.add_entity("小潜艇模型", "object", "小海用木头和铁丝做的")

    # Places
    builder.add_entity("浙江渔村", "place", "陈明远的家乡")
    builder.add_entity("上海水产学院", "place", "陈明远的大学")
    builder.add_entity("青岛研究所", "place", "陈明远工作的地方")
    builder.add_entity("南海", "place", "深海传感器6000米测试点")

    # Skills
    builder.add_entity("机械制图", "skill", "退休后教给渔村孩子的技能")
    builder.add_entity("深海传感器设计", "skill", "6000米深水压传感器")

    # Concepts
    builder.add_entity("传承", "concept", "三本册子传给小海")
    builder.add_entity("孤独", "concept", "妻子去世后的独处")
    builder.add_entity("草根的科研精神", "concept", "不从建制获取资源，自己动手")

    # ─── Events ────────────────────────────────────────────
    builder.add_event("出生", "1957年生于浙江渔村，父亲是修船的木匠", order=1, time_period="1957")
    builder.add_event(
        "童年看潮汐", "在码头边看潮来潮去，在沙滩上画潮汐表", order=2, time_period="1960年代"
    )
    builder.add_event(
        "村里第一个大学生",
        "考进上海水产学院海洋系，全村凑钱送他去上海",
        order=3,
        time_period="1975",
    )
    builder.add_event("毕业分配", "分配到青岛海洋研究所，从洗仪器开始", order=4, time_period="1979")
    builder.add_event(
        "遇见林小华", "在研究所食堂认识，她是会计，说话声音很轻", order=5, time_period="1981"
    )
    builder.add_event("结婚", "没有办婚礼，周末骑自行车去海边就算蜜月", order=6, time_period="1983")
    builder.add_event(
        "从废潜艇拆零件",
        "经费太少，从退役潜艇上拆舱壁做水压测试台",
        order=7,
        time_period="1985-1990",
    )
    builder.add_event(
        "女儿出生", "女儿陈雨出生，林小华休完产假就回来上班", order=8, time_period="1988"
    )
    builder.add_event(
        "妻子确诊肝癌", "林小华体检发现肝癌晚期，只剩六个月", order=9, time_period="1992"
    )
    builder.add_event(
        "病房走廊改论文", "陪床期间在走廊长椅上改深海传感器论文", order=10, time_period="1992-1993"
    )
    builder.add_event(
        "妻子去世", "林小华走了，陈明远连夜赶回研究所，把论文发了出去", order=11, time_period="1993"
    )
    builder.add_event(
        "一个人待了三年",
        "不出差，不社交，每天在实验室待十六个小时",
        order=12,
        time_period="1993-1996",
    )
    builder.add_event(
        "深海传感器突破",
        "6000米水压测试一次性成功，精度超过了日本同期设备",
        order=13,
        time_period="1996",
    )
    builder.add_event(
        "功成时看海", "测试成功那天一个人去海边坐到天黑，没喝庆功酒", order=14, time_period="1996"
    )
    builder.add_event(
        "退休回乡", "退休回到渔村，村里没人知道他做过什么", order=15, time_period="2017"
    )
    builder.add_event(
        "教小海画图", "免费教村里十二岁的男孩小海机械制图", order=16, time_period="2020"
    )
    builder.add_event(
        "小海做潜艇模型", "小海用木头和铁丝做了一个潜艇模型送给陈明远", order=17, time_period="2021"
    )
    builder.add_event(
        "肺癌确诊", "肺癌晚期，医生说和年轻时接触潜艇内壁的涂料有关", order=18, time_period="2022"
    )
    builder.add_event(
        "把册子交给小海",
        "临终前把三本手写册子交给小海，一笔一画写了十来年",
        order=19,
        time_period="2023",
    )
    builder.add_event(
        "去世", "2023年去世，享年66岁。骨灰一半撒在南海6000米测试点", order=20, time_period="2023"
    )

    # ─── Phase assignments ────────────────────────────────
    builder.in_phase("出生", "童年渔村")
    builder.in_phase("童年看潮汐", "童年渔村")
    builder.in_phase("村里第一个大学生", "求学之路")
    builder.in_phase("毕业分配", "求学之路")
    builder.in_phase("遇见林小华", "深海岁月")
    builder.in_phase("结婚", "深海岁月")
    builder.in_phase("从废潜艇拆零件", "深海岁月")
    builder.in_phase("女儿出生", "深海岁月")
    builder.in_phase("妻子确诊肝癌", "医院长廊")
    builder.in_phase("病房走廊改论文", "医院长廊")
    builder.in_phase("妻子去世", "医院长廊")
    builder.in_phase("一个人待了三年", "孤峰突破")
    builder.in_phase("深海传感器突破", "孤峰突破")
    builder.in_phase("功成时看海", "孤峰突破")
    builder.in_phase("退休回乡", "渔村归途")
    builder.in_phase("教小海画图", "渔村归途")
    builder.in_phase("小海做潜艇模型", "渔村归途")
    builder.in_phase("肺癌确诊", "渔村归途")
    builder.in_phase("把册子交给小海", "渔村归途")
    builder.in_phase("去世", "渔村归途")

    # ─── Relationships ─────────────────────────────────────
    builder.relate("陈明远", "林小华", "married", "1983年结婚，1993年妻子去世")
    builder.relate("陈明远", "陈雨", "parent_of", "女儿在美国")
    builder.relate("陈明远", "小海", "mentor_of", "退休后在渔村收的最后一个徒弟")
    builder.relate("陈明远", "专注", "has_trait", "")
    builder.relate("陈明远", "倔强", "has_trait", "不碰二手设备，宁可自己从废潜艇上拆")
    builder.relate("陈明远", "沉默的骄傲", "has_trait", "水压测试成功时不喝庆功酒，一个人看海")
    builder.relate("陈明远", "机械制图", "masters", "")
    builder.relate("陈明远", "深海传感器设计", "creates", "6000米深海压传感器")
    builder.relate("陈明远", "水压测试台", "built", "从退役潜艇上拆零件建造")
    builder.relate("陈明远", "三本手写册子", "writes", "临终前交给小海")
    builder.relate("小海", "小潜艇模型", "makes", "用木头和铁丝做的")
    builder.relate("浙江渔村", "陈明远", "birthplace_of", "")
    builder.relate("上海水产学院", "陈明远", "educated_at", "海洋系")

    # ─── Causal links ──────────────────────────────────────
    builder.causes(
        "从废潜艇拆零件", "深海传感器突破", "从退役潜艇拆下的舱壁成为水压测试台的核心材料"
    )
    builder.causes("妻子去世", "一个人待了三年", "妻子走后，他把所有精力投入实验室")
    builder.causes("一个人待了三年", "深海传感器突破", "三年孤独的积累最终突破了6000米")
    builder.causes("深海传感器突破", "功成时看海", "完成了毕生最大的成就，一个人坐到天黑")
    builder.causes("退休回乡", "教小海画图", "回到渔村后开始免费教孩子们机械制图")
    builder.causes("教小海画图", "小海做潜艇模型", "小海学了三个月后用木头和铁丝做了潜艇模型")
    builder.causes("从废潜艇拆零件", "肺癌确诊", "年轻时长期接触潜艇内壁涂料导致了三十年后肺癌")

    # ─── Event participants ────────────────────────────────
    builder.participate("陈明远", "出生", "主体")
    builder.participate("陈明远", "童年看潮汐", "主体")
    builder.participate("浙江渔村", "童年看潮汐", "地点")
    builder.participate("陈明远", "村里第一个大学生", "主体")
    builder.participate("上海水产学院", "村里第一个大学生", "地点")
    builder.participate("陈明远", "毕业分配", "主体")
    builder.participate("青岛研究所", "毕业分配", "地点")
    builder.participate("陈明远", "遇见林小华", "主体")
    builder.participate("林小华", "遇见林小华", "参与者")
    builder.participate("陈明远", "结婚", "主体")
    builder.participate("林小华", "结婚", "参与者")
    builder.participate("陈明远", "从废潜艇拆零件", "主体")
    builder.participate("青岛研究所", "从废潜艇拆零件", "地点")
    builder.participate("陈明远", "女儿出生", "主体")
    builder.participate("陈雨", "女儿出生", "参与者")
    builder.participate("林小华", "妻子确诊肝癌", "主体")
    builder.participate("陈明远", "妻子确诊肝癌", "参与者")
    builder.participate("陈明远", "病房走廊改论文", "主体")
    builder.participate("林小华", "病房走廊改论文", "关联者")
    builder.participate("陈明远", "妻子去世", "主体")
    builder.participate("林小华", "妻子去世", "主体")
    builder.participate("陈明远", "一个人待了三年", "主体")
    builder.participate("陈明远", "深海传感器突破", "主体")
    builder.participate("水压测试台", "深海传感器突破", "关键设备")
    builder.participate("深海传感器设计", "深海传感器突破", "成果")
    builder.participate("陈明远", "功成时看海", "主体")
    builder.participate("陈明远", "退休回乡", "主体")
    builder.participate("浙江渔村", "退休回乡", "地点")
    builder.participate("陈明远", "教小海画图", "主体")
    builder.participate("小海", "教小海画图", "对象")
    builder.participate("机械制图", "教小海画图", "内容")
    builder.participate("小海", "小海做潜艇模型", "主体")
    builder.participate("小潜艇模型", "小海做潜艇模型", "成果")
    builder.participate("陈明远", "肺癌确诊", "主体")
    builder.participate("陈明远", "把册子交给小海", "主体")
    builder.participate("小海", "把册子交给小海", "对象")
    builder.participate("三本手写册子", "把册子交给小海", "核心物")
    builder.participate("陈明远", "去世", "主体")

    # ─── Symbolic relationships ────────────────────────────
    builder.symbol("小潜艇模型", "传承", "一个孩子用木头和铁丝连接了两代人的海洋梦想")
    builder.symbol("三本手写册子", "传承", "一笔一画写了十来年，是知识也是生命")
    builder.symbol("水压测试台", "草根的科研精神", "从废铁中提炼出来的一流研究")
    builder.symbol("功成时看海", "孤独", "完成了毕生最大的成就，一个人坐到天黑")

    # ─── Build ─────────────────────────────────────────────
    print("Building biography graph...")
    builder.build()
    print("Done!")

    print("\n" + "=" * 60)
    print(reconstruct_narrative("陈明远"))


if __name__ == "__main__":
    main()
