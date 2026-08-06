# -*- coding: utf-8 -*-
"""
bench.py — M6 推理后端性能压测（AMD ROCm + llama.cpp llama-server）

对接入的 OpenAI 兼容端点做基准测试，量化迁移到 AMD Radeon (gfx1100, ROCm) 后的
推理表现，为「迁移与优化」里程碑提供可复核的数据支撑。指标：
  - TTFT（首 token 延迟）：流式下从发出请求到收到第一个内容 token 的时间；
  - 端到端延迟：单次请求总耗时；
  - 解码吞吐：生成 token 数 / 解码耗时（tokens/s）；
  - 并发压测：多线程并发下的成功率与平均延迟。

运行：
  $env:PYTHONIOENCODING="utf-8"; $env:PYTHONUTF8="1"
  python bench.py                 # 默认：文本单请求 x3 + 并发 x4
  python bench.py --n 5 --concurrency 8
  python bench.py --vision fapiao2.jpg   # 附带一次多模态 OCR 延迟

依赖端点经 SSH 隧道可用（localhost:8000）。
"""

import argparse
import base64
import statistics
import threading
import time

import requests

import config as cfg

TEXT_PROMPT = "用一句话解释什么是医保甲类药品。/no_think"


def _post(messages, max_tokens, stream):
    payload = {
        "model": cfg.MODEL_ID,
        "messages": messages,
        "temperature": cfg.LLM_TEMPERATURE,
        "max_tokens": max_tokens,
        "stream": stream,
    }
    return requests.post(cfg.MODEL_URL, json=payload, stream=stream, timeout=cfg.LLM_TIMEOUT)


def bench_stream_once(prompt=TEXT_PROMPT, max_tokens=128):
    """单次流式请求，返回 (ttft, total, n_tokens)。失败返回 None。"""
    messages = [{"role": "user", "content": prompt}]
    t0 = time.perf_counter()
    ttft = None
    n_tokens = 0
    try:
        resp = _post(messages, max_tokens, stream=True)
        for line in resp.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data: "):
                continue
            data = line[6:].strip()
            if data == "[DONE]":
                break
            try:
                import json
                chunk = json.loads(data)
                delta = chunk["choices"][0].get("delta", {})
                content = delta.get("content") or delta.get("reasoning_content") or ""
                if content:
                    if ttft is None:
                        ttft = time.perf_counter() - t0
                    n_tokens += 1
            except (ValueError, KeyError, IndexError):
                continue
    except requests.RequestException as e:
        print(f"[ERR] 请求异常：{e}")
        return None
    total = time.perf_counter() - t0
    if ttft is None:
        ttft = total
    return ttft, total, n_tokens


def run_serial(n, max_tokens):
    print(f"\n===== 串行文本基准（n={n}, max_tokens={max_tokens}）=====")
    ttfts, totals, tps = [], [], []
    for i in range(n):
        r = bench_stream_once(max_tokens=max_tokens)
        if not r:
            continue
        ttft, total, ntok = r
        decode = max(total - ttft, 1e-6)
        rate = ntok / decode if ntok else 0.0
        ttfts.append(ttft); totals.append(total); tps.append(rate)
        print(f"  #{i+1}: TTFT={ttft:.2f}s  总耗时={total:.2f}s  "
              f"生成 {ntok} tok  解码 {rate:.1f} tok/s")
    if totals:
        print(f"  -- 平均 TTFT={statistics.mean(ttfts):.2f}s  "
              f"平均总耗时={statistics.mean(totals):.2f}s  "
              f"平均吞吐={statistics.mean(tps):.1f} tok/s")


def run_concurrent(concurrency, max_tokens):
    print(f"\n===== 并发压测（concurrency={concurrency}, max_tokens={max_tokens}）=====")
    results = [None] * concurrency
    lock = threading.Lock()

    def worker(idx):
        r = bench_stream_once(max_tokens=max_tokens)
        with lock:
            results[idx] = r

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(concurrency)]
    t0 = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    wall = time.perf_counter() - t0

    ok = [r for r in results if r]
    fail = concurrency - len(ok)
    print(f"  完成 {len(ok)}/{concurrency}（失败 {fail}），墙钟耗时 {wall:.2f}s")
    if ok:
        totals = [r[1] for r in ok]
        total_tok = sum(r[2] for r in ok)
        print(f"  平均单请求耗时={statistics.mean(totals):.2f}s  "
              f"聚合吞吐={total_tok / wall:.1f} tok/s（{total_tok} tok / {wall:.2f}s）")


def run_vision(image_path):
    print(f"\n===== 多模态 OCR 延迟（{image_path}）=====")
    from tools.ocr_tool import encode_image
    b64 = encode_image(image_path)
    messages = [{
        "role": "user",
        "content": [
            {"type": "text", "text": "识别这张发票的价税合计金额，只回答数字。/no_think"},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
        ],
    }]
    t0 = time.perf_counter()
    try:
        resp = _post(messages, max_tokens=64, stream=False)
        data = resp.json()
        content = data["choices"][0]["message"].get("content", "")
    except (requests.RequestException, ValueError, KeyError) as e:
        print(f"[ERR] 多模态请求异常：{e}")
        return
    print(f"  端到端耗时={time.perf_counter() - t0:.2f}s  返回：{content.strip()[:80]}")


def check_endpoint():
    try:
        r = requests.get(f"{cfg.MODEL_BASE_URL}/models", timeout=10)
        print(f"[OK] 端点可用：{cfg.MODEL_BASE_URL}（HTTP {r.status_code}）")
        return r.status_code == 200
    except requests.RequestException as e:
        print(f"[ERR] 端点不可用：{cfg.MODEL_BASE_URL} → {e}")
        return False


def main():
    ap = argparse.ArgumentParser(description="AMD ROCm 推理后端性能压测")
    ap.add_argument("--n", type=int, default=3, help="串行文本请求次数")
    ap.add_argument("--concurrency", type=int, default=4, help="并发请求数")
    ap.add_argument("--max-tokens", type=int, default=128, help="每次生成的 max_tokens")
    ap.add_argument("--vision", type=str, default="", help="附带一次多模态 OCR 延迟（图片路径）")
    args = ap.parse_args()

    print("==== M6 推理后端性能压测 ====")
    print(f"模型：{cfg.MODEL_ID}")
    if not check_endpoint():
        print("请先确认 SSH 隧道已建立（localhost:8000 -> 远程 8080）。")
        return

    run_serial(args.n, args.max_tokens)
    run_concurrent(args.concurrency, args.max_tokens)
    if args.vision:
        run_vision(args.vision)
    print("\n==== 压测结束 ====")


if __name__ == "__main__":
    main()
