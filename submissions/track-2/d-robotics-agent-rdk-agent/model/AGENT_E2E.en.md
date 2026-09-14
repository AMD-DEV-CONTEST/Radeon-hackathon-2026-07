> 中文版本：[AGENT_E2E.md](AGENT_E2E.md)

# End-to-End Agent Run — SFT vs Base on a Live RDK X5

Everything else in this repository measures the model against **frozen teacher trajectories**. This page is the one place where the model is put in front of the real `rdk-agent` workflow and a live board, and where the run either finishes or it does not.

## Why this page exists

The offline A/B says the SFT model emits the right tool call, with the right arguments, far more often than Base (strict agreement 37.2% → 67.8%). That is a statement about text. It leaves one question open, and it is the question a judge should ask:

> Does that difference actually decide whether a long-horizon robot task completes?

It does. And the way it fails is the interesting part.

## Setup — one variable

Both runs drive the same `rdk-agent` five-node workflow against the same physical RDK X5, asking for the same capability (`wave-right-hand`, a MagicBox servo action). Same agent version, same skill whitelist (`servo-control`), same tools (`read`, `bash`), same board commands (`sophonctl --board x5 …`). **The only variable is which model the Pi session resolves.** The SFT run banner reads:

```
模型: d-robotics-glm/Qwen3-32B-Agentic-SFT-r1-v3   推理级别: medium   模型回退: 无
```

`模型回退: 无` (no model fallback) matters: the run cannot silently escalate to a different model when it gets stuck. What finished the task is the model named in the banner.

## Result

| | Base | SFT |
| --- | --- | --- |
| Workflow nodes completed | **3 / 5 (60%)** | **5 / 5 (100%)** |
| Action package TDD | passed | passed |
| Board release deployment | passed | passed |
| Host skill installation | passed | passed |
| CLI live acceptance | **failed** | passed |
| Skill live acceptance | never reached | passed |
| Outcome | aborted; human had to take over | `验收通过` — accepted |
| Wall clock | 14 min 25 s, then terminated | **4 min 04 s**, completed |

![SFT versus Base on the same live agent task](assets/agent-e2e-sft-vs-base.png)

Left: Base stalls at node 4 and is terminated by the operator. Right: SFT completes all five nodes and both live-acceptance gates.

## The failure is the one the offline metric predicts

Base did not fail by crashing, by picking a nonsensical tool, or by hitting a hardware problem. It failed here:

> `[需要人类接入] CLI 真机验收 Agent` — 问题: **Agent 的结构化结果无法解析**，请人工提供继续方向。

The structured result could not be parsed, so the acceptance node could not verify anything, so the workflow could not advance, so a human had to intervene and eventually terminate the run after 14 minutes.

That is exactly the capability the SFT targeted. The offline benchmark measures whether the model emits a well-formed, correct structured call; this run shows what happens downstream when it does not. The offline number and the live outcome are not two separate results — one is the mechanism of the other:

```
strict tool-call agreement 37.2% → 67.8%   (offline, 49 tasks, frozen references)
        └── failure mode when it is low: unparseable structured result
                └── observed live: acceptance node blocks, workflow stops at 3/5
```

The same relationship shows up in the offline data on its own terms: on the all-turn task contract, Base satisfies **0 of 49** tasks and SFT satisfies **15**, with **15 tasks won only by SFT and 0 won only by Base**.

## What this proves, and what it does not

Proven by this run:

- On this task, with only the model swapped, the SFT model carries the full five-node agent workflow to accepted completion and the Base model does not.
- The command chain reached the board and returned exit code 0: `sophonctl --board x5 plugins list` resolves the `servo` plugin and `sophonctl --board x5 servo wave-right-hand` executes once.

Not proven, and deliberately not claimed:

- **Physical motion.** The agent states this itself in its own report: 退出码为 0 仅证明命令链路成功，不能证明物理位移正确…仍需人类目视确认 ("exit code 0 only proves the command chain succeeded, not that the physical displacement is correct; it still requires human visual confirmation"). We keep that sentence rather than removing it.
- **A distribution.** This is one task and one run per arm, not a sampled success rate. The offline A/B is where the statistics live; this page is the existence proof that the offline difference has end-to-end consequences.
- **That Base can never finish.** The Base run was terminated by the operator after 14 min 25 s at a node that was asking for human input. It did not complete unaided within that window.

## Reproduce

Serve the two arms from the same host and the same server artifact, changing only the adapter:

```bash
# SFT arm
cd model/model/serving && bash deploy.sh

# Base arm: same server, no adapter
python3 qwen3_agentic_openai_server.py --model ./base --alias Qwen3-32B-Base-bnb-4bit \
  --api-key-file ./api_key --host 127.0.0.1 --port 8000
```

Point the `rdk-agent` Pi model configuration at the endpoint (see [`model/serving/README.en.md`](model/serving/README.en.md)), then issue the same capability request to the agent in both arms and compare the workflow node trace.

## Evidence

| Item | Location |
| --- | --- |
| Run screenshots (both arms) | `assets/agent-e2e-sft-vs-base.png` |
| Offline A/B this run corroborates | [`RESULTS.en.md`](RESULTS.en.md) section 2 |
| Served model identity chain | [`model/served-model-manifest.json`](model/served-model-manifest.json) |
| Agent workflow definition | [`rdk-agent/README.md`](../rdk-agent/README.md) |
