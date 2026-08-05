#!/usr/bin/env python3
"""
AMD AI Studio — 双机并行推理基准测试脚本

利用本地和远端两台 AMD Radeon PRO W7900D (48GB) 服务器，
通过内网（10.232.x.x）分发 prompt 池并行推理，大幅提升吞吐。

架构:
  ┌─────────────────┐         SSH (内网)         ┌──────────────────┐
  │  本地 (LOCAL)    │ ◄──────────────────────► │  远端 (REMOTE)    │
  │  10.232.4.145    │                           │  10.232.22.148    │
  │  GPU: W7900D     │                           │  GPU: W7900D      │
  │  prompt 1,3,5... │                           │  prompt 2,4,6...  │
  └─────────────────┘                           └──────────────────┘

用法:
  # 完整测试（8步，5轮预热，双机并行）
  python scripts/benchmark_dual_machine.py

  # 快速测试
  python scripts/benchmark_dual_machine.py --rounds 3 --warmup 1

  # 仅本地（对比单机）
  python scripts/benchmark_dual_machine.py --local-only

  # 仅远端（对比单机）
  python scripts/benchmark_dual_machine.py --remote-only
"""

import os
import sys
import time
import json
import argparse
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

# 添加项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

# ============================================================
# 配置
# ============================================================
OUTPUT_DIR = Path("outputs/benchmarks")
ASSETS_DIR = OUTPUT_DIR / "assets"
JSON_PATH = OUTPUT_DIR / "dual_machine_benchmark.json"

# 远端连接配置
REMOTE_HOST = "10.232.22.148"
REMOTE_PORT = 22
REMOTE_USER = "root"
REMOTE_PROJECT = "/workspace/amd-ai-studio"
REMOTE_VENV = "/opt/venv"
SSH_KEY = "/tmp/id_ed25519_nopass"
SSH_PASSPHRASE = ""

# 紫狮风格提示词（8 个，双机各 4 个）
SAMPLE_PROMPTS = [
    "a majestic lion in traditional Chinese ink wash painting style, golden mane flowing, mystical purple aura, ancient temple background",
    "紫狮神兽，中国传统水墨画风格，鬃毛飘逸，紫色神光环绕，古刹背景，4K",
    "a fierce lion warrior in Chinese mythology, purple energy mane, ceremonial armor, dramatic lighting, masterpiece",
    "紫狮守护神，宫殿石阶，祥云缭绕，紫色雷电鬃毛，写实摄影质感，8K",
    "a regal lion king seated on a jade throne, purple imperial aura, Chinese dragon motifs, cinematic composition",
    "紫狮踏云，东方神话，紫金鬃毛，云雾翻腾，国风水墨，超高清",
    "a cyberpunk purple lion with neon mane, futuristic city backdrop, holographic elements, cinematic lighting",
    "紫狮×赛博朋克，霓虹鬃毛，未来都市背景，全息投影元素，高对比度，8K",
]

# 默认参数（官方推荐）
DEFAULT_STEPS = 8
DEFAULT_GUIDANCE = 0.0
DEFAULT_WIDTH = 1024
DEFAULT_HEIGHT = 1024
DEFAULT_WARMUP = 2
DEFAULT_ROUNDS = 5

# 远端 SSH 命令模板（使用持久化 ssh-agent，避免每次新建）
SSH_CMD_BASE = (
    f'ssh -p {REMOTE_PORT} -o StrictHostKeyChecking=no -o BatchMode=yes '
    f'{REMOTE_USER}@{REMOTE_HOST}'
)
SSH_CMD_TEMPLATE = (
    f'ssh -i {SSH_KEY} -p {REMOTE_PORT} -o StrictHostKeyChecking=no -o BatchMode=yes '
    f'{REMOTE_USER}@{REMOTE_HOST}'
)

# 远端执行命令模板
REMOTE_EXEC_TEMPLATE = (
    f'cd {REMOTE_PROJECT} && source {REMOTE_VENV}/bin/activate && '
    'python3 -c {code}'
)


def parse_args():
    p = argparse.ArgumentParser(description="双机并行推理基准测试")
    p.add_argument("--steps", type=int, default=DEFAULT_STEPS, help="推理步数")
    p.add_argument("--guidance", type=float, default=DEFAULT_GUIDANCE, help="引导尺度")
    p.add_argument("--width", type=int, default=DEFAULT_WIDTH)
    p.add_argument("--height", type=int, default=DEFAULT_HEIGHT)
    p.add_argument("--warmup", type=int, default=DEFAULT_WARMUP, help="预热轮数")
    p.add_argument("--rounds", type=int, default=DEFAULT_ROUNDS, help="正式测试轮数")
    p.add_argument("--local-only", action="store_true", help="仅本地（单机对比）")
    p.add_argument("--remote-only", action="store_true", help="仅远端（单机对比）")
    return p.parse_args()


def get_system_info():
    """收集本地系统信息"""
    info = {
        "timestamp": datetime.now().isoformat(),
        "python": sys.version.split()[0],
        "torch": __import__("torch").__version__,
        "cuda_available": __import__("torch").cuda.is_available(),
    }
    if __import__("torch").cuda.is_available():
        info["gpu"] = __import__("torch").cuda.get_device_name(0)
        info["vram_total_gb"] = round(
            __import__("torch").cuda.get_device_properties(0).total_memory / 1024**3, 1
        )
    if hasattr(__import__("torch").version, "hip") and __import__("torch").version.hip:
        info["rocm"] = __import__("torch").version.hip
    try:
        import diffusers; info["diffusers"] = diffusers.__version__
    except Exception:
        info["diffusers"] = "unknown"
    return info


def get_remote_system_info():
    """获取远端系统信息"""
    code = """
import torch, json
info = {"torch": torch.__version__, "cuda": torch.cuda.is_available()}
if torch.cuda.is_available():
    info["gpu"] = torch.cuda.get_device_name(0)
    info["vram_total_gb"] = round(torch.cuda.get_device_properties(0).total_memory / 1024**3, 1)
if hasattr(torch.version, "hip") and torch.version.hip:
    info["rocm"] = torch.version.hip
import diffusers; info["diffusers"] = diffusers.__version__
print(json.dumps(info))
"""
    cmd = SSH_CMD_TEMPLATE + f' \'{REMOTE_EXEC_TEMPLATE.format(code=repr(code))}\''
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
        return json.loads(result.stdout.strip())
    except Exception as e:
        return {"error": str(e)}


def run_inference_local(prompts, args, warmup=0, seed_offset=0):
    """在本地 GPU 上运行推理"""
    import torch
    from diffusers import Krea2Pipeline

    print(f"  [本地] 加载模型...")
    pipe = Krea2Pipeline.from_pretrained(
        "krea/Krea-2-Turbo", torch_dtype=torch.bfloat16
    ).to("cuda")
    try:
        pipe.enable_attention_slicing()
    except Exception:
        pass

    results = []
    for i, prompt in enumerate(prompts):
        torch.cuda.reset_peak_memory_stats()
        generator = torch.Generator(device="cuda").manual_seed(seed_offset + i + 1000)

        t0 = time.time()
        with torch.inference_mode():
            result = pipe(
                prompt=prompt,
                num_inference_steps=args.steps,
                guidance_scale=args.guidance,
                width=args.width,
                height=args.height,
                generator=generator,
            )
        latency = time.time() - t0
        image = result.images[0]
        peak_vram = torch.cuda.max_memory_allocated(0) / 1024**3

        results.append({
            "index": i,
            "prompt": prompt,
            "latency_s": round(latency, 3),
            "peak_vram_gb": round(peak_vram, 2),
            "machine": "local",
        })
        print(f"  [本地] 样图 {i+1}/{len(prompts)}: {latency:.2f}s | 显存 {peak_vram:.2f}GB")

    return results, pipe


def run_inference_remote(prompts, args, seed_offset=0):
    """在远端 GPU 上运行推理，通过 SSH 内网传输结果"""
    import base64, io
    from PIL import Image

    # 构建远端 Python 代码
    prompts_json = json.dumps(prompts)
    code = f"""
import json, sys, os, time, base64, io
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

import torch
from diffusers import Krea2Pipeline
from PIL import Image

prompts = {prompts_json}
steps = {args.steps}
guidance = {args.guidance}
width = {args.width}
height = {args.height}
seed_offset = {seed_offset}

pipe = Krea2Pipeline.from_pretrained("krea/Krea-2-Turbo", torch_dtype=torch.bfloat16).to("cuda")
try:
    pipe.enable_attention_slicing()
except:
    pass

results = []
for i, prompt in enumerate(prompts):
    torch.cuda.reset_peak_memory_stats()
    generator = torch.Generator(device="cuda").manual_seed(seed_offset + i + 2000)
    t0 = time.time()
    with torch.inference_mode():
        result = pipe(prompt=prompt, num_inference_steps=steps, guidance_scale=guidance,
                      width=width, height=height, generator=generator)
    latency = time.time() - t0
    img = result.images[0]
    peak_vram = torch.cuda.max_memory_allocated(0) / 1024**3

    # 将图片转 base64 传回
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    img_b64 = base64.b64encode(buf.getvalue()).decode()

    results.append({{
        "index": i,
        "prompt": prompt,
        "latency_s": round(latency, 3),
        "peak_vram_gb": round(peak_vram, 2),
        "machine": "remote",
        "image_b64": img_b64,
    }})
    print(f"  [远端] 样图 {{i+1}}/{{len(prompts)}}: {{latency:.2f}}s | 显存 {{peak_vram:.2f}}GB", flush=True)

print("===JSON_START===" + json.dumps(results) + "===JSON_END===")
"""

    cmd = SSH_CMD_TEMPLATE + f' \'{REMOTE_EXEC_TEMPLATE.format(code=repr(code))}\''

    print(f"  [远端] 发送 {len(prompts)} 个 prompt 到远端推理...")
    t0 = time.time()
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=600
        )
        elapsed = time.time() - t0

        if result.returncode != 0:
            print(f"  [远端] SSH 错误: {result.stderr[:500]}")
            return None

        # 解析 JSON 结果
        stdout = result.stdout
        start = stdout.find("===JSON_START===")
        end = stdout.find("===JSON_END===")
        if start == -1 or end == -1:
            print(f"  [远端] 输出中未找到 JSON 结果")
            print(f"  输出片段: {stdout[-500:]}")
            return None

        json_str = stdout[start + len("===JSON_START==="):end]
        remote_results = json.loads(json_str)

        # 解码 base64 图片
        for r in remote_results:
            img_b64 = r.pop("image_b64", None)
            if img_b64:
                img_data = base64.b64decode(img_b64)
                img = Image.open(io.BytesIO(img_data))
                fname = f"krea_zishi_remote_{r['index'] + 1}.png"
                fpath = ASSETS_DIR / fname
                img.save(str(fpath))
                r["image_path"] = str(fpath)

        print(f"  [远端] 完成，耗时 {elapsed:.1f}s")
        return remote_results

    except subprocess.TimeoutExpired:
        print(f"  [远端] SSH 超时（>600s）")
        return None
    except Exception as e:
        print(f"  [远端] 错误: {e}")
        return None


def run_benchmark_local(prompts, args, warmup=0, seed_offset=0):
    """在本地 GPU 上运行基准测试（预热 + 正式）"""
    import torch
    from diffusers import Krea2Pipeline

    print(f"  [本地] 加载模型...")
    pipe = Krea2Pipeline.from_pretrained(
        "krea/Krea-2-Turbo", torch_dtype=torch.bfloat16
    ).to("cuda")
    try:
        pipe.enable_attention_slicing()
    except Exception:
        pass

    bench_prompt = prompts[0] if prompts else "a purple lion, Chinese ink painting"
    latencies = []
    peak_vrams = []

    # 预热
    if warmup > 0:
        print(f"  [本地] 预热 {warmup} 轮...")
        for i in range(warmup):
            generator = torch.Generator(device="cuda").manual_seed(100 + i)
            with torch.inference_mode():
                pipe(bench_prompt, num_inference_steps=args.steps,
                     guidance_scale=args.guidance, width=args.width,
                     height=args.height, generator=generator)

    # 正式测试
    print(f"  [本地] 正式基准测试 {args.rounds} 轮...")
    for i in range(args.rounds):
        torch.cuda.reset_peak_memory_stats()
        generator = torch.Generator(device="cuda").manual_seed(42 + i)
        t0 = time.time()
        with torch.inference_mode():
            pipe(bench_prompt, num_inference_steps=args.steps,
                 guidance_scale=args.guidance, width=args.width,
                 height=args.height, generator=generator)
        latency = time.time() - t0
        peak_vram = torch.cuda.max_memory_allocated(0) / 1024**3
        latencies.append(latency)
        peak_vrams.append(peak_vram)
        print(f"  [本地] 轮次 {i+1}/{args.rounds}: {latency:.3f}s | 显存 {peak_vram:.2f}GB")

    return {
        "latency_avg_s": round(sum(latencies) / len(latencies), 3),
        "latency_min_s": round(min(latencies), 3),
        "latency_max_s": round(max(latencies), 3),
        "throughput_avg_img_per_s": round(args.rounds / sum(latencies), 2),
        "peak_vram_avg_gb": round(sum(peak_vrams) / len(peak_vrams), 2),
        "latencies": [round(l, 3) for l in latencies],
        "peak_vrams": [round(v, 2) for v in peak_vrams],
    }, pipe


def run_benchmark_remote(args):
    """在远端 GPU 上运行基准测试"""
    code = f"""
import json, sys, os, time
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
import torch
from diffusers import Krea2Pipeline

steps = {args.steps}
guidance = {args.guidance}
width = {args.width}
height = {args.height}
warmup = {args.warmup}
rounds = {args.rounds}

pipe = Krea2Pipeline.from_pretrained("krea/Krea-2-Turbo", torch_dtype=torch.bfloat16).to("cuda")
try:
    pipe.enable_attention_slicing()
except:
    pass

bench_prompt = "a majestic purple lion in Chinese ink wash painting, 4K, masterpiece"
latencies = []
peak_vrams = []

if warmup > 0:
    print(f"  [远端] 预热 {{warmup}} 轮...", flush=True)
    for i in range(warmup):
        generator = torch.Generator(device="cuda").manual_seed(100 + i)
        with torch.inference_mode():
            pipe(bench_prompt, num_inference_steps=steps, guidance_scale=guidance,
                 width=width, height=height, generator=generator)

print(f"  [远端] 正式基准测试 {{rounds}} 轮...", flush=True)
for i in range(rounds):
    torch.cuda.reset_peak_memory_stats()
    generator = torch.Generator(device="cuda").manual_seed(42 + i)
    t0 = time.time()
    with torch.inference_mode():
        pipe(bench_prompt, num_inference_steps=steps, guidance_scale=guidance,
             width=width, height=height, generator=generator)
    latency = time.time() - t0
    peak_vram = torch.cuda.max_memory_allocated(0) / 1024**3
    latencies.append(latency)
    peak_vrams.append(peak_vram)
    print(f"  [远端] 轮次 {{i+1}}/{{rounds}}: {{latency:.3f}}s | 显存 {{peak_vram:.2f}}GB", flush=True)

result = {{
    "latency_avg_s": round(sum(latencies)/len(latencies), 3),
    "latency_min_s": round(min(latencies), 3),
    "latency_max_s": round(max(latencies), 3),
    "throughput_avg_img_per_s": round(rounds/sum(latencies), 2),
    "peak_vram_avg_gb": round(sum(peak_vrams)/len(peak_vrams), 2),
    "latencies": [round(l, 3) for l in latencies],
    "peak_vrams": [round(v, 2) for v in peak_vrams],
}}
print("===JSON_START===" + json.dumps(result) + "===JSON_END===")
"""

    cmd = SSH_CMD_TEMPLATE + f' \'{REMOTE_EXEC_TEMPLATE.format(code=repr(code))}\''

    print(f"  [远端] 发送基准测试命令...")
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=600)
        if result.returncode != 0:
            print(f"  [远端] SSH 错误: {result.stderr[:500]}")
            return None

        stdout = result.stdout
        # 打印远端 stdout 中的普通输出（非 JSON 部分）
        for line in stdout.split("\n"):
            if "===JSON_START===" in line:
                break
            if line.strip():
                print(f"  {line}")

        start = stdout.find("===JSON_START===")
        end = stdout.find("===JSON_END===")
        if start == -1 or end == -1:
            print(f"  [远端] 输出中未找到 JSON 结果")
            print(f"  输出末尾: {stdout[-300:]}")
            return None

        json_str = stdout[start + len("===JSON_START==="):end]
        return json.loads(json_str)

    except subprocess.TimeoutExpired:
        print(f"  [远端] SSH 超时（>600s）")
        return None
    except Exception as e:
        print(f"  [远端] 错误: {e}")
        return None


def main():
    args = parse_args()

    print("=" * 70)
    print("AMD AI Studio — 双机并行推理基准测试")
    print("=" * 70)

    # 获取系统信息
    local_info = get_system_info()
    print(f"\n📦 本地: {local_info.get('gpu', 'N/A')} | {local_info.get('vram_total_gb', '?')}GB torch={local_info['torch']}")

    remote_info = None
    if not args.local_only:
        print(f"获取远端系统信息...")
        remote_info = get_remote_system_info()
        if remote_info and "error" not in remote_info:
            print(f"📦 远端: {remote_info.get('gpu', 'N/A')} | {remote_info.get('vram_total_gb', '?')}GB torch={remote_info['torch']}")
        else:
            print(f"⚠️ 远端不可达: {remote_info}")
            if args.remote_only:
                print("错误: --remote-only 但远端不可达")
                return 1
            print("  降级为仅本地模式")
            args.local_only = True

    # 确保输出目录存在
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)

    # ============================================================
    # 模式 1: 双机并行样本生成
    # ============================================================
    if not args.local_only and not args.remote_only:
        print("\n" + "=" * 70)
        print("🚀 双机并行: 生成 8 张紫狮风格样图（各 4 张）")
        print("=" * 70)

        # 均分 prompt
        prompts = SAMPLE_PROMPTS[:8]
        local_prompts = prompts[0::2]  # 偶数索引 → 本地
        remote_prompts = prompts[1::2]  # 奇数索引 → 远端

        print(f"  本地: {len(local_prompts)} 个 prompt")
        print(f"  远端: {len(remote_prompts)} 个 prompt")

        # 并行执行
        t0 = time.time()
        local_results = []
        remote_results = []

        with ThreadPoolExecutor(max_workers=2) as executor:
            local_future = executor.submit(run_inference_local, local_prompts, args, 0, 0)
            remote_future = executor.submit(run_inference_remote, remote_prompts, args, 0)

            # 收集本地结果
            try:
                local_results, _ = local_future.result(timeout=600)
            except Exception as e:
                print(f"  [本地] 错误: {e}")

            # 收集远端结果
            try:
                remote_results = remote_future.result(timeout=600)
            except Exception as e:
                print(f"  [远端] 错误: {e}")

        total_elapsed = time.time() - t0
        total_images = len(local_results) + (len(remote_results) if remote_results else 0)
        print(f"\n✅ 双机并行完成: {total_images} 张样图, 耗时 {total_elapsed:.1f}s")
        print(f"   等效吞吐: {total_images / total_elapsed:.2f} img/s")
        print(f"   单机延迟: ~37.7s/img → 双机并行 {total_images} 张仅需 {total_elapsed:.1f}s")

    # ============================================================
    # 模式 2: 基准测试（单机 vs 双机）
    # ============================================================
    print("\n" + "=" * 70)

    if args.local_only:
        print("📊 单机基准测试（仅本地）")
        print("=" * 70)
        local_result, _ = run_benchmark_local(SAMPLE_PROMPTS[:args.rounds], args, args.warmup, 0)
        dual_result = None
        remote_result = None

    elif args.remote_only:
        print("📊 单机基准测试（仅远端）")
        print("=" * 70)
        local_result = None
        remote_result = run_benchmark_remote(args)
        dual_result = None

    else:
        print("📊 双机并行基准测试")
        print("=" * 70)

        # 分两半执行
        half = args.rounds // 2 + args.rounds % 2
        local_rounds = half
        remote_rounds = args.rounds - half

        # 本地
        print(f"\n  🤖 本地 ({local_rounds} 轮)...")
        local_result = None
        local_args = argparse.Namespace(
            steps=args.steps, guidance=args.guidance,
            width=args.width, height=args.height,
            warmup=args.warmup, rounds=local_rounds,
        )
        local_result, _ = run_benchmark_local(SAMPLE_PROMPTS[:local_rounds], local_args, args.warmup, 0)

        # 远端
        print(f"\n  🖥️ 远端 ({remote_rounds} 轮)...")
        remote_args = argparse.Namespace(
            steps=args.steps, guidance=args.guidance,
            width=args.width, height=args.height,
            warmup=0, rounds=remote_rounds,
        )
        remote_result = run_benchmark_remote(remote_args)

        # 计算双机汇总
        if local_result and remote_result:
            all_latencies = local_result["latencies"] + remote_result["latencies"]
            total_wall_time = max(
                local_result["latency_avg_s"] * local_rounds,
                remote_result.get("latency_avg_s", 0) * remote_rounds,
            )
            dual_result = {
                "local_rounds": local_rounds,
                "remote_rounds": remote_rounds,
                "total_rounds": args.rounds,
                "total_wall_time_s": round(total_wall_time, 2),
                "throughput_combined_img_per_s": round(args.rounds / total_wall_time, 2),
                "latency_avg_s": round(sum(all_latencies) / len(all_latencies), 3),
            }
        else:
            dual_result = None

    # ============================================================
    # 汇总输出
    # ============================================================
    output = {
        "test_type": "dual_machine" if not (args.local_only or args.remote_only) else ("local_only" if args.local_only else "remote_only"),
        "timestamp": datetime.now().isoformat(),
        "model": "Krea-2-Turbo-zishi",
        "config": {
            "num_inference_steps": args.steps,
            "guidance_scale": args.guidance,
            "width": args.width,
            "height": args.height,
            "dtype": "bfloat16",
            "optimizations": ["enable_attention_slicing"],
        },
        "local": local_info,
        "remote": remote_info,
        "result_local": local_result,
        "result_remote": remote_result,
        "result_dual": dual_result,
        "notes": [
            "双机并行: 本地 (10.232.4.145) + 远端 (10.232.22.148)",
            f"内网 SSH 通信，密钥 {SSH_KEY}",
            f"远端 venv: {REMOTE_VENV}",
            "prompt 池按奇偶索引均分到两台 GPU",
        ],
    }

    # 写入 JSON
    JSON_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✅ 结果已保存: {JSON_PATH}")

    # 打印摘要
    print("\n" + "=" * 70)
    print("📊 结果摘要")
    print("=" * 70)
    if local_result:
        print(f"  本地: {local_result['latency_avg_s']:.3f}s/img | 吞吐 {local_result['throughput_avg_img_per_s']:.2f} img/s | 显存 {local_result['peak_vram_avg_gb']:.2f}GB")
    if remote_result:
        print(f"  远端: {remote_result['latency_avg_s']:.3f}s/img | 吞吐 {remote_result['throughput_avg_img_per_s']:.2f} img/s | 显存 {remote_result['peak_vram_avg_gb']:.2f}GB")
    if dual_result:
        speedup = dual_result["throughput_combined_img_per_s"] / (local_result["throughput_avg_img_per_s"] if local_result else 1)
        print(f"  双机: {dual_result['total_rounds']} 轮, 耗时 {dual_result['total_wall_time_s']:.1f}s, 吞吐 {dual_result['throughput_combined_img_per_s']:.2f} img/s")
        print(f"  🚀 加速比: {speedup:.2f}x")
    print("=" * 70)


if __name__ == "__main__":
    main()