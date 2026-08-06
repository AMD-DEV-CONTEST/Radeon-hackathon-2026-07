"""Ingest major policies with societal impact — events people remember.

Covers: education, healthcare, housing, land, economy, social welfare,
labor, legal reform, family policy, environment. China main focus + key global.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from memory.story_graph import StoryGraphBuilder

POLICIES = [
    # ===== Education =====
    ("[CN] 九年义务教育法颁布", 1986, "1980s"),
    ("[CN] 义务教育学杂费免除开始试点", 2005, "2000s"),
    ("[CN] 农村义务教育全面免收学杂费", 2006, "2000s"),
    ("[CN] 城市义务教育免收学杂费", 2008, "2000s"),
    ("[CN] 两免一补政策全面实施", 2006, "2000s"),
    ("[CN] 高考恢复", 1977, "1970s"),
    ("[CN] 高校扩招政策开始", 1999, "1990s"),
    ("[CN] 希望工程启动", 1989, "1980s"),
    ("[CN] 大学毕业生不再包分配", 1996, "1990s"),
    ("[CN] 211工程启动", 1995, "1990s"),
    ("[CN] 985工程启动", 1998, "1990s"),
    ("[CN] 双一流大学建设启动", 2017, "2010s"),
    ("[CN] 双减政策实施", 2021, "2020s"),
    ("[CN] 扫盲运动大规模开展", 1950, "1950s"),
    ("[CN] 简化汉字方案公布", 1956, "1950s"),
    ("[CN] 汉语拼音方案公布", 1958, "1950s"),
    # ===== Healthcare =====
    ("[CN] 赤脚医生制度建立", 1965, "1960s"),
    ("[CN] 农村合作医疗制度建立", 1960, "1960s"),
    ("[CN] 新型农村合作医疗启动", 2003, "2000s"),
    ("[CN] 城镇居民基本医疗保险启动", 2007, "2000s"),
    ("[CN] 医药分开改革试点", 2009, "2000s"),
    ("[CN] 全面二孩政策实施", 2016, "2010s"),
    ("[CN] 三孩政策实施", 2021, "2020s"),
    ("[CN] SARS公共卫生应急体系建立", 2003, "2000s"),
    ("[CN] 爱国卫生运动大规模开展", 1952, "1950s"),
    ("[CN] 疫苗接种计划免疫系统建立", 1978, "1970s"),
    ("[GL] WHO eradication of smallpox declared", 1980, "1980s"),
    ("[GL] Affordable Care Act USA", 2010, "2010s"),
    # ===== Housing & Land =====
    ("[CN] 土地改革完成", 1952, "1950s"),
    ("[CN] 人民公社化运动", 1958, "1950s"),
    ("[CN] 家庭联产承包责任制开始", 1978, "1970s"),
    ("[CN] 住房商品化改革启动", 1988, "1980s"),
    ("[CN] 住房公积金制度建立", 1991, "1990s"),
    ("[CN] 经济适用房政策启动", 1998, "1990s"),
    ("[CN] 棚户区改造大规模实施", 2008, "2000s"),
    ("[CN] 房地产调控国十条出台", 2010, "2010s"),
    ("[CN] 城镇保障性住房大规模建设", 2011, "2010s"),
    # ===== Economy =====
    ("[CN] 改革开放政策启动", 1978, "1970s"),
    ("[CN] 深圳等经济特区设立", 1980, "1980s"),
    ("[CN] 十四沿海城市对外开放", 1984, "1980s"),
    ("[CN] 浦东开发开放", 1990, "1990s"),
    ("[CN] 社会主义市场经济体制确立", 1992, "1990s"),
    ("[CN] 分税制改革实施", 1994, "1990s"),
    ("[CN] 国有企业下岗分流改革", 1998, "1990s"),
    ("[CN] 中国加入世界贸易组织WTO", 2001, "2000s"),
    ("[CN] 所得税法统一内外资企业", 2008, "2000s"),
    ("[CN] 四万亿经济刺激计划", 2008, "2000s"),
    ("[CN] 营改增全面推开", 2016, "2010s"),
    ("[CN] 共同富裕政策提出", 2021, "2020s"),
    ("[GL] Bretton Woods system established", 1944, "1940s"),
    ("[GL] US abandons gold standard", 1971, "1970s"),
    ("[GL] Euro currency launched", 1999, "1990s"),
    ("[GL] Global Financial Crisis bailouts", 2008, "2000s"),
    # ===== Family & Social =====
    ("[CN] 婚姻法颁布", 1950, "1950s"),
    ("[CN] 计划生育政策开始推行", 1979, "1970s"),
    ("[CN] 独生子女政策全面实施", 1980, "1980s"),
    ("[CN] 单独二孩政策实施", 2014, "2010s"),
    ("[CN] 户籍制度改革试点", 2014, "2010s"),
    ("[CN] 居住证制度全面推开", 2016, "2010s"),
    ("[CN] 劳动法颁布实施", 1995, "1990s"),
    ("[CN] 劳动合同法实施", 2008, "2000s"),
    ("[CN] 全面取消农业税", 2006, "2000s"),
    ("[CN] 新农保制度建立", 2009, "2000s"),
    ("[CN] 城镇居民养老保险建立", 2011, "2010s"),
    ("[CN] 脱贫攻坚战全面胜利", 2020, "2020s"),
    ("[GL] US Social Security Act", 1935, "1930s"),
    ("[GL] UK National Health Service founded", 1948, "1940s"),
    ("[GL] Universal Declaration of Human Rights", 1948, "1940s"),
    ("[GL] US Civil Rights Act", 1964, "1960s"),
    # ===== Environment =====
    ("[CN] 退耕还林工程启动", 1999, "1990s"),
    ("[CN] 南水北调工程正式开工", 2002, "2000s"),
    ("[CN] 大气污染防治行动计划实施", 2013, "2010s"),
    ("[CN] 垃圾分类强制实施", 2019, "2010s"),
    ("[CN] 碳达峰碳中和承诺", 2020, "2020s"),
    ("[CN] 长江十年禁渔计划实施", 2021, "2020s"),
    ("[GL] Kyoto Protocol adopted", 1997, "1990s"),
    ("[GL] Paris Climate Agreement signed", 2015, "2010s"),
    ("[GL] Montreal Protocol ozone protection", 1987, "1980s"),
    # ===== Technology & Infrastructure =====
    ("[CN] 京九铁路全线通车", 1996, "1990s"),
    ("[CN] 青藏铁路全线通车", 2006, "2000s"),
    ("[CN] 中国高铁网络大规模建设", 2008, "2000s"),
    ("[CN] 北斗卫星导航系统建成", 2020, "2020s"),
    ("[CN] 天宫空间站建成", 2022, "2020s"),
    ("[GL] Apollo program Moon landing", 1969, "1960s"),
    ("[GL] International Space Station launched", 1998, "1990s"),
    ("[GL] Human Genome Project completed", 2003, "2000s"),
    ("[GL] Large Hadron Collider operational", 2008, "2000s"),
    # ===== Legal & Constitutional =====
    ("[CN] 中华人民共和国宪法颁布", 1954, "1950s"),
    ("[CN] 刑法和刑事诉讼法颁布", 1979, "1970s"),
    ("[CN] 民法通则颁布", 1986, "1980s"),
    ("[CN] 物权法颁布实施", 2007, "2000s"),
    ("[CN] 民法典颁布实施", 2021, "2020s"),
    ("[CN] 反垄断法实施", 2008, "2000s"),
    ("[CN] 网络安全法实施", 2017, "2010s"),
    ("[CN] 个人信息保护法实施", 2021, "2020s"),
]


def main():
    builder = StoryGraphBuilder("World Facts 1924-2024")
    for y in range(1920, 2030, 10):
        builder.add_phase(f"{y}s", f"{y}s")

    for label, year, decade in POLICIES:
        builder.add_event(label, "", year, str(year))
        builder.in_phase(label, decade)

    builder.build()

    cn = sum(1 for l, _, _ in POLICIES if "[CN]" in l)
    gl = sum(1 for l, _, _ in POLICIES if "[GL]" in l)
    cat = {}
    for l, _, _ in POLICIES:
        # Simple category inference from keywords
        for kw in ["教育", "高考", "大学", "学校", "双减", "扫盲", "汉字", "汉语"]:
            if kw in l:
                cat["教育"] = cat.get("教育", 0) + 1
                break
        else:
            for kw in ["医疗", "卫生", "疫苗", "医", "SARS", "医保", "生育", "健康"]:
                if kw in l:
                    cat["医疗"] = cat.get("医疗", 0) + 1
                    break
            else:
                for kw in ["住房", "土地", "房地产", "棚户", "保障", "房"]:
                    if kw in l:
                        cat["住房"] = cat.get("住房", 0) + 1
                        break
                else:
                    cat["综合"] = cat.get("综合", 0) + 1

    print(f"Added {len(POLICIES)} major policy events")
    print(f"  China: {cn} | Global: {gl}")
    print(f"  Categories: {dict(cat)}")


if __name__ == "__main__":
    main()
