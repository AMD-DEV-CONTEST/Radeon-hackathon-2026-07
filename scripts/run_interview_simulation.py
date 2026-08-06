"""Simulate an interview session: interviewer vs interviewee.

Runs N rounds of Q&A, builds the life graph incrementally,
then compares the resulting graph against a secret ground-truth persona.
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.interviewee import respond_with_delay
from agents.interviewer import GraphInterviewer
from memory.evaluator import compute_loss
from memory.story_graph import clear_story_data
from memory.structurizer import regenerate_narrative, structurize_text

# Secret ground-truth persona (NOT shown to interviewer)
GROUND_TRUTH = """
陈明远，1957年生于浙江渔村。父亲是修船的木匠。小时候在码头边看潮起潮落，沙滩上画潮汐表。
1975年考进上海水产学院海洋系，是村里第一个大学生。全村子凑钱送他去上海。
1979年分配到青岛海洋研究所，从洗仪器开始，一直做到了深海传感器项目的负责人。
1983年与研究所会计林小华结婚。没有办婚礼，周末骑自行车去海边就算蜜月。
1988年女儿陈雨出生。林小华休完产假就回来上班。
1992年林小华体检发现肝癌晚期，只剩六个月。陈明远在病房走廊里改深海传感器论文。
1993年林小华去世。她走的那个晚上，陈明远连夜赶回研究所，把论文发了出去。
从1993到1996年，他一个人待了三年。不出差，不社交，每天在实验室待十六个小时。
1996年，6000米水压测试一次性成功，精度超过了日本同期设备。
测试成功那天，他没喝庆功酒，一个人去海边坐到天黑。
2017年退休回到渔村。村里没人知道他做过什么。
2020年开始免费教村里十二岁的男孩小海机械制图。
小海用木头和铁丝做了一个潜艇模型送给陈明远。
2022年确诊肺癌晚期，医生说和年轻时接触潜艇内壁的涂料有关。
2023年临终前把三本手写册子交给小海，一笔一画写了十来年。
2023年去世，享年66岁。骨灰一半撒在南海6000米测试点。
"""


def run_interview(max_rounds: int = 8, verbose: bool = True) -> dict:
    """Run a complete interview simulation.

    Returns:
        dict with interview transcript, extracted graph, and metrics.
    """
    interviewer = GraphInterviewer("陈明远")
    transcript = []

    print(f"{'=' * 60}")
    print("  Interview Simulation: GraphVoice Interviewer")
    print(f"{'=' * 60}\n")

    for round_num in range(1, max_rounds + 1):
        # Interviewer asks a question
        print(f"\n[Round {round_num}] Strategy: {interviewer.state.current_strategy}")
        question = interviewer.ask()

        print(f"\n{'─' * 50}")
        print(f"Interviewer: {question}")

        # Interviewee responds (with thinking delay)
        print("  (thinking...)")
        answer = respond_with_delay(
            question,
            persona_text=GROUND_TRUTH,
            verbosity=1.0,
            tangent_rate=0.15,
            guard_topics=["林小华的病情", "妻子去世的那个晚上"],
        )
        print(f"User: {answer}")

        transcript.append({"round": round_num, "question": question, "answer": answer})

        # Interviewer processes the answer -> extracts graph data
        data = interviewer.process_answer(answer)
        if verbose:
            entities = data.get("entities", [])
            events = data.get("events", [])
            if entities or events:
                ent_names = ", ".join(e["name"] for e in entities[:5])
                print(
                    f"  [Extracted: {len(entities)} entities ({ent_names}...), {len(events)} events]"
                )

        # Show coverage progress
        if verbose:
            print(f"  Coverage: {interviewer.get_coverage_summary().replace(chr(10), ' | ')}")

        # Check if complete
        if interviewer.is_complete(min_coverage=0.4) and round_num >= 5:
            print(f"\n  [Interview complete after {round_num} rounds]")
            break

    # Build the graph from all collected data
    print(f"\n{'=' * 60}")
    print("  Building interview graph...")
    clear_story_data()

    # Collect all extracted data into one structurization
    all_text = "\n\n".join(f"Q: {t['question']}\nA: {t['answer']}" for t in transcript)
    try:
        full_data = structurize_text(all_text)
    except Exception:
        full_data = {
            "entities": [],
            "events": [],
            "phases": [],
            "relationships": [],
            "causal_links": [],
            "symbols": [],
        }

    print(
        f"  Graph: {len(full_data.get('entities', []))} entities, "
        f"{len(full_data.get('events', []))} events, "
        f"{len(full_data.get('phases', []))} phases"
    )

    # Regenerate narrative from graph
    regenerated = regenerate_narrative(full_data, lang="Chinese")

    # Compare against ground truth
    metrics = compute_loss(GROUND_TRUTH, regenerated)

    return {
        "transcript": transcript,
        "rounds": len(transcript),
        "graph_data": full_data,
        "regenerated": regenerated,
        "metrics": metrics,
    }


def main():
    # Suppress structurization warnings
    import logging

    logging.getLogger("memory.structurizer").setLevel(logging.WARNING)

    print("Running interview simulation...\n")
    start = time.time()
    result = run_interview(max_rounds=8, verbose=True)
    elapsed = time.time() - start

    print(f"\n{'=' * 60}")
    print("  RESULTS")
    print(f"{'=' * 60}")
    print(f"  Rounds:           {result['rounds']}")
    print(f"  Total time:       {elapsed:.0f}s")
    print(f"  Entities found:   {len(result['graph_data'].get('entities', []))}")
    print(f"  Events found:     {len(result['graph_data'].get('events', []))}")
    print(f"  Bigram overlap:   {result['metrics']['entity_preservation']:.1%}")
    print(f"  LLM Score:        {result['metrics']['llm_score']:.1f}/10")
    print("\n  Ground truth has: 24 entities (from earlier manual ingestion)")
    print(
        f"  Interview found:  {len(result['graph_data'].get('entities', []))} entities "
        f"({len(result['graph_data'].get('entities', [])) / 24 * 100:.0f}% recall)"
    )

    print(f"\n{'=' * 60}")
    print("  INTERVIEW TRANSCRIPT")
    print(f"{'=' * 60}")
    for t in result["transcript"]:
        print(f"\n[Round {t['round']}]")
        print(f"Q: {t['question']}")
        print(f"A: {t['answer']}")

    print(f"\n{'=' * 60}")
    print("  REGENERATED BIOGRAPHY")
    print(f"{'=' * 60}")
    print(result["regenerated"])

    # Save
    out = Path(__file__).parent / "interview_results.json"
    out.write_text(
        json.dumps(
            {
                "rounds": result["rounds"],
                "transcript": result["transcript"],
                "metrics": result["metrics"],
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    print(f"\n  Results saved: {out}")


if __name__ == "__main__":
    main()
