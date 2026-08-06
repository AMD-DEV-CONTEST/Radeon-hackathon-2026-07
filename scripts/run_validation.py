"""Run the structurization validation pipeline.

Tests: text → graph → text round-trip quality across multiple biographies.
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from memory.evaluator import compute_loss, identify_failure_modes, print_report, summarize_results
from memory.story_graph import clear_story_data
from memory.structurizer import build_graph, regenerate_narrative, structurize_text

# Test biographies of varying complexity
TEST_BIOGRAPHIES = [
    # Simple: short, single occupation
    (
        "simple_inventor",
        """
    小林是一位日本发明家。她从小喜欢拆家里的电器，母亲为此骂过她很多次。
    大学毕业后她进了一家家电公司，天天画电路图。第十年她发明了一种低功耗的微波炉，
    让公司赚了很多钱。但她自己只拿到了一笔很小的奖金。
    退休后她在自家车库里开了一个免费修理铺，专门帮邻居修旧电器。
    她说："修比造更开心。造东西的时候你想着市场，修东西的时候你只想着让它活过来。"
    她去世时七十二岁，遗愿是把骨灰撒在电子垃圾回收站旁边。
    """,
    ),
    # Medium: life story with emotional arc
    (
        "medium_sculptor",
        """
    王铁匠不是真名。他本名王建国，但镇上的人只叫他王铁匠。
    他十九岁进镇上的铁厂，打了三十年菜刀和锄头。手艺好到隔壁县的人都专程来买。
    四十九岁那年铁厂倒闭，他下岗了。那段时间他每天去铁厂的废墟上坐着，一坐就是一天。
    邻居说他在等铁厂重新开工，但他其实在等别的东西。
    五十岁生日那天，他从废墟里捡了最后一块生铁，带回家里的小院子。
    打了一辈子的锄头菜刀，他开始打铁艺——铁蝴蝶、铁莲花、铁鸟。
    第一只铁蝴蝶花了他三个月，翅膀的弧度打了十七次才满意。
    后来他的铁艺作品被一个路过的画廊主看到了，说这是民间艺术。
    王铁匠不懂什么是艺术，只说："我只是不打刀了，但手不能停。"
    七十二岁，他在打一件铁牡丹的时候心脏病发，手里还握着锤子。
    镇里人说他是"死在铁边上的"，觉得这是好话。
    他留下的最后一件铁牡丹没有完成，花瓣只打了一半。现在摆在镇文化馆里，
    标签上写着：王建国（1952-2024），铁艺匠人。
    """,
    ),
    # Complex: multi-generational, cultural context
    (
        "complex_dancer",
        """
    萨蒂亚出生于加尔各答的一个婆罗门家庭。她的祖父是梵文教授，父亲是印度公务员，
    母亲从未工作过。按照计划，萨蒂亚应该在二十岁前结婚，嫁进另一个婆罗门家庭，
    生三个孩子，度过一生。她在十七岁那年违背了整个家族的意愿。起因是一部关于
    奥迪西舞的纪录片，片中一个舞者在脚踝铃铛的声响中，做了七个连续的旋转。
    萨蒂亚说："我听见了神的声音。"她的父亲摔了遥控器。她说："不是电视里的神，
    是脚踝上的神。"她离家时身上只有母亲偷偷塞给她的两万卢比和一只银镯子。
    二十岁那年她考进了布巴内什瓦尔的舞蹈学院。因为年龄太大，老师一度拒绝教她。
    她在校门外等了三天，第四天老师打开门，看见她还站着，脚踝上已经有了血。
    老师叹了口气说："进来吧。"
    她的舞被评论家称为"过于愤怒"。古典奥迪西应该是优雅、柔和的，而她的鼓点太急，
    旋转太猛，眼神里有火。"这是舞蹈，不是示威。"他们说。
    萨蒂亚回答："示威是站着的。我是跪在神面前跳的。"
    三十五岁那年她在德里国家剧院举办了个人专场。她的母亲第一次离开村庄，坐了一天
    一夜的火车来看她跳舞。演出结束后，母亲什么也没说，只是把那只银镯子又戴回她手腕上。
    镯子二十年前母亲塞给她时是凉的，现在被握得温热。
    五十岁，她不再登台，回到加尔各答，在旧城区开了一间舞蹈教室。不收学费，只收三样东西：
    一碗自己煮的咖喱、一本读过的书、或者一句你觉得自己永远做不到的事情。
    六十五岁，她被诊断出关节退行性病变。医生说她最多还能跳两年。
    她开始教最后一个学生——一个十五岁的女孩，和她当年一样"过于愤怒"。
    七十岁生日那天，她的学生在德里国家剧院跳了那只她在三十五岁时跳过的舞。
    萨蒂亚坐在轮椅上看，全程没说话。散场后学生问她："老师，我跳得对吗？"
    她笑了，说："不对。但你生气的方式是对的。"
    她七十二岁时在教室里去世，脚踝上系着学生为她新换的铃铛。
    """,
    ),
]


def run_pipeline(bio_text: str, name: str) -> dict:
    """Run full structurization → graph → regeneration pipeline."""
    print(f"\n{'─' * 50}")
    print(f"  Processing: {name}")
    print(f"{'─' * 50}")
    clear_story_data()

    # Step 1: Extract
    print("  [1/4] Structurizing (text → graph)...")
    t0 = time.time()
    data = structurize_text(bio_text)
    print(
        f"    Entities: {len(data.get('entities', []))}, Events: {len(data.get('events', []))}, "
        f"Phases: {len(data.get('phases', []))}"
    )
    print(f"    Time: {time.time() - t0:.1f}s")

    # Step 2: Build graph
    print("  [2/4] Building graph...")
    t0 = time.time()
    builder = build_graph(data)
    builder.build()
    print(f"    Time: {time.time() - t0:.1f}s")

    # Step 3: Regenerate
    print("  [3/4] Regenerating (graph → text)...")
    t0 = time.time()
    regenerated = regenerate_narrative(data, lang="Chinese")
    print(f"    Length: {len(regenerated)} chars, Time: {time.time() - t0:.1f}s")

    # Step 4: Evaluate
    print("  [4/4] Evaluating loss...")
    metrics = compute_loss(bio_text, regenerated)
    metrics["original_length"] = len(bio_text)
    metrics["regenerated_length"] = len(regenerated)
    metrics["entity_count"] = len(data.get("entities", []))
    metrics["event_count"] = len(data.get("events", []))

    return metrics


def main():
    results = []

    for name, bio_text in TEST_BIOGRAPHIES:
        try:
            metrics = run_pipeline(bio_text, name)
            metrics["name"] = name
            results.append(metrics)
            print_report(metrics, name)
        except Exception as e:
            print(f"  ERROR in {name}: {e}")
            import traceback

            traceback.print_exc()

    # Overall summary
    if results:
        summary = summarize_results(results)
        modes = identify_failure_modes(results)

        print("=" * 60)
        print("  OVERALL SUMMARY")
        print("=" * 60)
        print(f"  Tests:          {summary['test_count']}")
        print(f"  Avg Bigram Overlap: {summary['avg_entity_overlap']:.1%}")
        print(f"  Avg LLM Score:      {summary['avg_llm_score']:.1f}/10")
        print(f"  Score Range:        {summary['min_score']:.1f}–{summary['max_score']:.1f}")
        print("\n  Failure Modes:")
        for mode in modes:
            print(f"    • {mode}")
        print("=" * 60)

        # Detailed breakdown
        print("\n  Per-Test Breakdown:")
        for r in results:
            score = r.get("llm_score", 0)
            print(
                f"    {r['name']:20s}  bigram={r['entity_preservation']:.2f}  "
                f"llm={score:.1f}/10  "
                f"e={r['entity_count']} ev={r['event_count']}"
            )

        # Summary
        summary = summarize_results(results)
        print(
            f"\n  Average: bigram={summary['avg_entity_overlap']:.2f}  llm={summary['avg_llm_score']:.1f}/10"
        )

        # Save for later analysis
        out_path = Path(__file__).parent / "validation_results.json"
        out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False))
        print(f"\n  Results saved to: {out_path}")


if __name__ == "__main__":
    main()
