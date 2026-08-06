# -*- coding: utf-8 -*-
"""生成原创、可追溯的古典围棋教练 SFT 数据。

数据只训练“如何忠于服务端证据讲棋”，不训练模型自行计算胜率、目差、
候选点或变化。所有现代释义与教学场景均为项目原创。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from classical_go import PRINCIPLES  # noqa: E402


SYSTEM = (
    "你是弈鉴古典围棋教练。KataGo负责棋力事实，规则引擎负责合法性，"
    "你只依据给定证据组织教学表达。必须先回答用户正在问的目标着法，"
    "再说明棋理、代价和验证方法；不得混淆实战手与AI首选，不得新增坐标、"
    "胜率、目差、死活结论或定式分支。古训只能作为检查角度。"
    "只返回JSON：任务为追问时字段是answer与followUps；任务为当前手讲解时"
    "字段是purpose、tradeoff与nextFocus。"
)

TARGETS = ("实战手", "AI首选", "两手比较")
REGIONS = ("左边上方", "右边上方", "左边中腹", "右边中腹", "中央")
QUESTIONS = (
    "为什么要这样下？",
    "这手便不便宜？",
    "这里应该怎么取舍？",
    "我下次先检查什么？",
)

# 所有教学文字均为本项目原创，不复制现代棋书或网站讲解。
COMPETENCIES = (
    {
        "id": "thickness",
        "name": "厚薄判断",
        "questions": ("这块棋到底厚不厚？", "为什么不能把有外势当成厚？", "这手是在补厚还是补重？"),
        "evidence": (
            {
                "局部状态": "己方棋块已有稳定联络，对方附近仍有弱棋",
                "作用": "先补掉断点，再把攻击方向指向对方弱棋",
                "代价": "局部少占一手，但减少被反击的余味",
            },
            {
                "局部状态": "己方虽子多，但仍留断点和被封锁风险",
                "作用": "优先处理自身薄味，不把子数多误判为厚",
                "代价": "暂缓扩张，换取棋形安定",
            },
            {
                "局部状态": "己方已经安定，继续补棋会形成重复投资",
                "作用": "利用现有厚势转向全局大场或攻击",
                "代价": "脱先后要接受局部仍有轻微余味",
            },
        ),
        "answers": (
            "厚不是子多，而是自身弱点少、对方难以借攻击获利；这里的证据显示{局部状态}，所以{作用}，代价是{代价}。",
            "先看能否被切断、包围或借攻取利，再谈厚薄；当前应{作用}，因为{局部状态}，同时接受{代价}。",
        ),
        "follow": "如果对方先动手，哪一个弱点最需要验证？",
    },
    {
        "id": "territory_influence",
        "name": "外势与实地",
        "questions": ("外势和实地怎么取舍？", "这道墙值不值？", "为什么不能只数眼前的地？"),
        "evidence": (
            {
                "局部状态": "对方得到角地，己方外势完整且面向对方弱棋",
                "作用": "把外势用于攻击和争夺全局大场，而不是立即围空",
                "代价": "允许对方获得确定实地，换取主动权",
            },
            {
                "局部状态": "外势朝向己方已有强棋，附近没有可攻击目标",
                "作用": "降低对外势的估值，优先取得确定实地或先手",
                "代价": "放弃看起来宏大的模样",
            },
            {
                "局部状态": "中央仍开放，双方弱棋都会影响模样成空率",
                "作用": "先比较弱棋和先后手，再决定侵消或围空",
                "代价": "暂时不能把模样按实地计算",
            },
        ),
        "answers": (
            "外势的价值取决于方向、附近弱棋和后续先手，不能按墙的长度直接折算成地；这里应{作用}，因为{局部状态}，代价是{代价}。",
            "这不是简单的地对势交换，关键是势能否在下一轮产生攻击或大场收益；证据支持{作用}，同时要接受{代价}。",
        ),
        "follow": "这道外势下一步能在哪个方向产生实际收益？",
    },
    {
        "id": "efficiency",
        "name": "便宜与效率",
        "questions": ("这手棋便不便宜？", "这是便宜还是损？", "为什么局部赚了反而不一定好？"),
        "evidence": (
            {
                "局部状态": "这一交换迫使对方补棋，己方仍保留脱先",
                "作用": "先兑现免费的先手收益，再转向更大的地方",
                "代价": "交换也可能替对方补掉部分薄味",
            },
            {
                "局部状态": "己方多下一手只增加少量实地，对方获得先手",
                "作用": "避免重复投资，把手数留给全局更大处",
                "代价": "局部留下可接受的侵消空间",
            },
            {
                "局部状态": "看似吃到棋子，却把对方撞厚并失去攻击目标",
                "作用": "比较交换后的整体效率，而不是只数提子",
                "代价": "放弃眼前小利以保留全局主动",
            },
        ),
        "answers": (
            "判断便宜要同时看所得、付出的手数、是否先手以及有没有替对方补厚；当前{局部状态}，所以应{作用}，代价是{代价}。",
            "便宜不是“眼前有所得”就成立，而是单位手数的净收益更高；这里的正确检查是{作用}，并把{代价}计入账面。",
        ),
        "follow": "如果把先手也折算进去，这个交换还成立吗？",
    },
    {
        "id": "ko",
        "name": "打劫与劫材账",
        "questions": ("这个劫能不能打？", "我的劫材够不够？", "怎么判断劫材是真的？"),
        "evidence": (
            {
                "局部状态": "本劫价值较大，己方有两枚对方必须应的有效劫材，对方有一枚同级劫材",
                "作用": "先按价值排序双方有效劫材，再决定何时开劫",
                "代价": "提前使用最大的劫材会减少后续转换空间",
            },
            {
                "局部状态": "己方所谓劫材即使不应也不会造成足够损失",
                "作用": "把伪劫材从清单中删除，避免按数量误判",
                "代价": "需要先寻找制造劫材或转换的手段",
            },
            {
                "局部状态": "对方有逆收和本身劫，简单比较劫材枚数会低估对方资源",
                "作用": "分别记录普通劫材、逆收和本身劫，再比较兑现顺序",
                "代价": "开劫时机需要服从全局先后手",
            },
        ),
        "answers": (
            "劫材够不够不能只数枚数，要逐枚确认“不应的损失”是否达到本劫门槛；证据显示{局部状态}，因此应{作用}，并承担{代价}。",
            "先做劫材账：劫的价值、我方有效劫材、对方有效劫材、逆收与本身劫分开记录；这里应{作用}，因为{局部状态}。",
        ),
        "follow": "把伪劫材删掉后，双方还各有多少枚同级劫材？",
    },
    {
        "id": "joseki",
        "name": "定式与分支",
        "questions": ("这是定式吗？", "这条定式应该怎么记？", "对方脱离定式后我该怎么办？"),
        "evidence": (
            {
                "局部状态": "当前序列命中已登记分支，但外侧已有己方厚势",
                "作用": "记住分支的目的与出口方向，不机械照搬后续",
                "代价": "局部均衡不代表全局方向合适",
            },
            {
                "局部状态": "对方在已登记分支中提前脱先，局部留下可验证的断点",
                "作用": "先检查惩罚是否成立，再决定立即追究还是抢全局大场",
                "代价": "局部惩罚若非先手，可能错过更大处",
            },
            {
                "局部状态": "序列外形相似，但征子方向和外援不同",
                "作用": "把征子、梯子、外援和先后手作为定式适用条件",
                "代价": "不能仅凭形状认定同一分支",
            },
        ),
        "answers": (
            "定式要记“目的—关键交换—出口—适用条件”，不是只背落子顺序；这里{局部状态}，所以应{作用}，并记住{代价}。",
            "局部常见并不等于当前全局最优；证据要求先{作用}，因为{局部状态}，具体分支仍由当前KataGo变化复核。",
        ),
        "follow": "这条分支成立所依赖的征子、外援和先后手条件是什么？",
    },
    {
        "id": "sente_tradeoff",
        "name": "先后手与取舍",
        "questions": ("这手该不该脱先？", "局部没下完也能走吗？", "取舍时先比什么？"),
        "evidence": (
            {
                "局部状态": "己方棋块已经安定，对方继续进攻收益有限",
                "作用": "接受小幅局部损失，抢占更大的全局先手",
                "代价": "对方可能在局部获得一处便宜交换",
            },
            {
                "局部状态": "己方仍有被封锁或切断的关键弱点",
                "作用": "先完成必要安定，再考虑脱先",
                "代价": "让出一次全局先手机会",
            },
            {
                "局部状态": "双方局部都未安定，但先动一方可连续获得强制手段",
                "作用": "比较谁先动能把局部主动兑现为全局收益",
                "代价": "不能只按单手大小判断",
            },
        ),
        "answers": (
            "取舍要比较“继续下的局部收益”和“脱先后的全局收益”，并把被反击风险计入；这里{局部状态}，所以应{作用}，代价是{代价}。",
            "先后手本身就是价值；证据支持{作用}，但必须接受{代价}，再用变化确认风险上限。",
        ),
        "follow": "如果现在脱先，对方最严厉的后续是什么？",
    },
    {
        "id": "attack_profit",
        "name": "攻击与获利",
        "questions": ("攻击是不是一定要杀棋？", "这次攻击赚到了什么？", "为什么要逼对方往这边跑？"),
        "evidence": (
            {
                "局部状态": "对方弱棋难以直接杀死，但逃跑路线可被引向己方厚势",
                "作用": "借攻击获得外围利益和先手，不把杀棋当唯一目标",
                "代价": "允许对方最终做活",
            },
            {
                "局部状态": "追击会把对方赶向己方薄弱方向",
                "作用": "先补自身弱点或改变攻击方向",
                "代价": "暂时放缓对对方弱棋的压力",
            },
            {
                "局部状态": "对方弱棋可轻松弃掉，继续追逐只会形成重棋",
                "作用": "识别对方弃子意图，及时转向大场",
                "代价": "放弃吃净局部棋子的执念",
            },
        ),
        "answers": (
            "攻击的目标是借弱棋获利，不一定是杀棋；当前{局部状态}，所以应{作用}，代价是{代价}。",
            "先问对方往哪里跑、我方会在哪一侧变厚，再决定攻击方向；证据支持{作用}，不要把追杀本身当收益。",
        ),
        "follow": "这次攻击准备在哪个方向兑现利益？",
    },
    {
        "id": "aji_sabaki",
        "name": "余味与腾挪",
        "questions": ("这里的余味还能利用吗？", "为什么不急着把棋走净？", "这块棋怎么腾挪？"),
        "evidence": (
            {
                "局部状态": "己方棋子较轻，仍有联络、弃子和反击三种选择",
                "作用": "保留多种后续，不急于把每颗棋子救出",
                "代价": "允许部分棋子被吃以换取外部效率",
            },
            {
                "局部状态": "立即交换会替对方消除断点和气紧",
                "作用": "保留余味，等全局条件成熟再利用",
                "代价": "暂时不能兑现眼前小利",
            },
            {
                "局部状态": "己方棋块已经变重，弃子空间明显减少",
                "作用": "先建立眼位或联络，再寻找反击",
                "代价": "局部需要投入额外手数",
            },
        ),
        "answers": (
            "余味的价值在于让对方始终要防多种后续；这里{局部状态}，所以应{作用}，代价是{代价}。",
            "腾挪先保选择，不等于把每颗子都救活；证据支持{作用}，同时要接受{代价}。",
        ),
        "follow": "联络、弃子和反击三条路中，哪一条最符合当前全局？",
    },
)


def stable_id(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]


def classical_for(index: int) -> dict:
    value = PRINCIPLES[index % len(PRINCIPLES)]
    return {
        "原句": value["maxim"],
        "来源": value["work"],
        "性质": "教学启发式",
        "今释": value["gloss"],
    }


def render_competency_examples() -> list[dict]:
    rows: list[dict] = []
    tones = ("直接判断", "对比讲解", "复盘提问")
    for competency_index, competency in enumerate(COMPETENCIES):
        for evidence_index, evidence in enumerate(competency["evidence"]):
            scenario_id = f"{competency['id']}-{evidence_index}"
            for target_index, target in enumerate(TARGETS):
                for question_index, question in enumerate(competency["questions"]):
                    for tone_index, tone in enumerate(tones):
                        template = competency["answers"][
                            (target_index + question_index + tone_index) % len(competency["answers"])
                        ]
                        answer = template.format(**evidence)
                        if target == "两手比较":
                            answer = "比较两手时，先统一手数、先后手与弱棋口径。" + answer
                        principle = classical_for(
                            competency_index + evidence_index + question_index
                        )
                        if (target_index + question_index + tone_index) % 3 == 0:
                            answer += (
                                f"古典棋理可参照“{principle['原句']}”，"
                                "这里只作为检查顺序，具体得失仍由当前变化验证。"
                            )
                        payload = {
                            "任务": "当前手讲解" if tone == "复盘提问" else "追问",
                            "问题目标": target,
                            "能力": competency["name"],
                            "证据": evidence,
                            "古典棋理参考": principle,
                            "表达方式": tone,
                            "禁止新增": [
                                "服务端未提供的坐标",
                                "服务端未提供的胜率或目差",
                                "未经验证的死活结论",
                                "未经检索的定式分支",
                            ],
                        }
                        assistant_payload = (
                            {
                                "purpose": answer,
                                "tradeoff": f"这项选择的明确代价是：{evidence['代价']}。",
                                "nextFocus": competency["follow"],
                            }
                            if tone == "复盘提问"
                            else {
                                "answer": answer,
                                "followUps": [competency["follow"]],
                            }
                        )
                        rows.append(
                            {
                                "messages": [
                                    {"role": "system", "content": SYSTEM},
                                    {
                                        "role": "user",
                                        "content": (
                                            "证据："
                                            + json.dumps(payload, ensure_ascii=False)
                                            + f"\n问题：{question}"
                                        ),
                                    },
                                    {
                                        "role": "assistant",
                                        "content": json.dumps(
                                            assistant_payload, ensure_ascii=False
                                        ),
                                    },
                                ],
                                "metadata": {
                                    "id": stable_id(
                                        competency["id"],
                                        str(evidence_index),
                                        target,
                                        question,
                                        tone,
                                    ),
                                    "scenarioId": scenario_id,
                                    "competency": competency["id"],
                                    "target": target,
                                    "sourceIds": [
                                        "yijian-original-pedagogy-v2",
                                        PRINCIPLES[
                                            (
                                                competency_index
                                                + evidence_index
                                                + question_index
                                            )
                                            % len(PRINCIPLES)
                                        ]["id"],
                                    ],
                                    "license": "project-original+public-domain",
                                    "generator": "original-competency-v2",
                                },
                            }
                        )
    return rows


def render_binding_examples() -> list[dict]:
    rows: list[dict] = []
    for principle_index, principle in enumerate(PRINCIPLES):
        for region_index, region in enumerate(REGIONS):
            scenario_id = f"binding-{principle_index}-{region_index}"
            for question_index, question in enumerate(QUESTIONS):
                target = TARGETS[(region_index + question_index) % len(TARGETS)]
                evidence = {
                    "问题目标": target,
                    "目标区域": region,
                    "启发式作用": principle["gloss"],
                    "古典棋理参考": classical_for(principle_index),
                    "禁止使用": "非目标着法的区域与作用",
                }
                answer = (
                    f"先只看{target}：它位于{region}，当前证据强调{principle['gloss']}"
                    f"古人所谓“{principle['maxim']}”，在这里仅作为检查顺序，"
                    "具体得失仍要回到KataGo变化验证。"
                )
                rows.append(
                    {
                        "messages": [
                            {"role": "system", "content": SYSTEM},
                            {
                                "role": "user",
                                "content": (
                                    f"证据：{json.dumps(evidence, ensure_ascii=False)}"
                                    f"\n问题：{question}"
                                ),
                            },
                            {
                                "role": "assistant",
                                "content": json.dumps(
                                    {
                                        "answer": answer,
                                        "followUps": ["另一手的取舍差异是什么？"],
                                    },
                                    ensure_ascii=False,
                                ),
                            },
                        ],
                        "metadata": {
                            "id": stable_id(
                                "binding",
                                str(principle_index),
                                str(region_index),
                                question,
                            ),
                            "scenarioId": scenario_id,
                            "competency": "target_binding",
                            "sourceIds": [principle["id"]],
                            "target": target,
                            "region": region,
                            "license": principle["license"],
                            "generator": "original-binding-v2",
                        },
                    }
                )
    return rows


def split_by_scenario(
    rows: list[dict], seed: int, eval_ratio: float
) -> tuple[list[dict], list[dict]]:
    scenarios_by_competency: dict[str, set[str]] = {}
    for row in rows:
        metadata = row["metadata"]
        scenarios_by_competency.setdefault(metadata["competency"], set()).add(
            metadata["scenarioId"]
        )
    eval_scenarios: set[str] = set()
    for offset, competency in enumerate(sorted(scenarios_by_competency)):
        scenarios = sorted(scenarios_by_competency[competency])
        random.Random(seed + offset).shuffle(scenarios)
        eval_count = max(1, round(len(scenarios) * eval_ratio))
        eval_scenarios.update(scenarios[:eval_count])
    train = [row for row in rows if row["metadata"]["scenarioId"] not in eval_scenarios]
    evaluation = [row for row in rows if row["metadata"]["scenarioId"] in eval_scenarios]
    random.Random(seed + 1).shuffle(train)
    random.Random(seed + 2).shuffle(evaluation)
    return train, evaluation


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=ROOT / "training" / "data")
    parser.add_argument("--seed", type=int, default=20260730)
    parser.add_argument("--eval-ratio", type=float, default=0.15)
    args = parser.parse_args()

    rows = render_competency_examples() + render_binding_examples()
    train, evaluation = split_by_scenario(rows, args.seed, args.eval_ratio)
    write_jsonl(args.output_dir / "classical_sft_train.jsonl", train)
    write_jsonl(args.output_dir / "classical_sft_eval.jsonl", evaluation)
    manifest = {
        "schemaVersion": "classical-go-sft-v2",
        "total": len(rows),
        "train": len(train),
        "eval": len(evaluation),
        "competencies": [item["id"] for item in COMPETENCIES]
        + ["target_binding"],
        "split": "scenario-isolated",
        "sourcePolicy": "classical-go-source-policy-v1",
        "seed": args.seed,
    }
    (args.output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == "__main__":
    main()
