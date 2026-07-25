"""
MiniMax Speech-2.8-HD TTS — 生成 InventoryDoc Agent 中文演示语音

使用方法:
  1. 获取 API Key: 访问 https://platform.minimaxi.com → 账户管理 → 接口密钥 → 创建
  2. 设置环境变量: set MINIMAX_API_KEY=your_key_here
  3. 运行: python scripts/generate_audio.py

输出: scripts/demo_audio.mp3
"""

import os
import sys
import requests

# ── 配置 ──────────────────────────────────────────────

API_URL = "https://api.minimaxi.com/v1/t2a_v2"
MODEL = "speech-2.8-hd"
VOICE_ID = "male-qn-qingse"  # 专业男声
OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "demo_audio.mp3")

NARRATION = """
每次盘点结束，仓储经理都要面对这样的困境：十份数据、五百多个SKU、几千行记录，分散在CSV、Excel和文本文件里，编码格式还不统一。人工分析至少需要两到三天，而且很容易算错——基准选错了，成本用了售价，数字前后对不上。等管理层开会的时候，差异原因说不清楚，追责更无从下手。

我们做了InventoryDoc Agent，一个完全本地部署的AI智能体。你只需要上传十份盘点数据，它就能在十分钟内自动生成可以直接上会的调账材料。所有数据在本地处理，零云端依赖。

它有三个核心能力。

第一，智能噪音识别。Agent能自动识别并排除六十八条扫码环境噪音记录，还有两份不适用的文件——一份是品类月报，粒度太粗；另一份是历史库存，里面有两百多条异常数据。这一步人工做需要逐行检查，Agent三秒搞定。

第二，基准智能选择。系统里有两份库存快照，编码体系不一样。Agent自动从编码一致性、数据粒度和时间窗口三个维度进行对比，选出了正确的基准——和盘点表编码一致的那一份。选错基准，整个分析就白做了。

第三，日志关联三分类。这是我们的独特创新。Agent不简单地说"有没有操作"，而是按实际出入库变动量进行精准比对，把一百五十九个差异SKU分成三类：十四个完全可解释，有对应的出入库记录；二十一个部分可解释，有操作但数量不够；还有一百二十四个完全没有日志关联——这些才是需要去仓库现场实物复核的重点。这个能力，目前市面上没有第二个Agent能做到。

最终，Agent输出一份Excel差异明细表和一份分析报告，管理层直接拿去开会。整个流程从两到三天缩短到十分钟。基于AMDRadeonGPU和ROCm本地部署，数据全程不出设备。谢谢。
""".strip()


def get_api_key():
    key = os.environ.get("MINIMAX_API_KEY")
    if not key:
        print("错误: 未设置 MINIMAX_API_KEY 环境变量")
        print()
        print("获取步骤:")
        print("  1. 访问 https://platform.minimaxi.com 注册/登录")
        print("  2. 进入「账户管理 > 接口密钥」")
        print("  3. 创建 API Key")
        print("  4. 设置环境变量:")
        print('     Windows:  set MINIMAX_API_KEY=your_key_here')
        print('     Linux/Mac: export MINIMAX_API_KEY=your_key_here')
        sys.exit(1)
    return key


def generate_speech(text, api_key):
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": MODEL,
        "text": text,
        "stream": False,
        "voice_setting": {
            "voice_id": VOICE_ID,
            "speed": 0.95,
            "vol": 1,
            "pitch": 0,
            "emotion": "calm",
        },
        "audio_setting": {
            "sample_rate": 32000,
            "bitrate": 128000,
            "format": "mp3",
            "channel": 1,
        },
        "output_format": "url",
    }

    print(f"调用 MiniMax {MODEL} API ...")
    print(f"音色: {VOICE_ID} | 语速: 0.95 | 情绪: calm")
    print(f"文本长度: {len(text)} 字符")
    print()

    resp = requests.post(API_URL, headers=headers, json=payload, timeout=120)
    resp.raise_for_status()
    data = resp.json()

    base_resp = data.get("base_resp", {})
    status_code = base_resp.get("status_code", -1)
    status_msg = base_resp.get("status_msg", "")

    if status_code != 0:
        print(f"API 错误 [{status_code}]: {status_msg}")
        sys.exit(1)

    extra = data.get("extra_info", {})
    audio_url = data.get("data", {}).get("audio", "")
    duration_ms = extra.get("audio_length", 0)
    file_size = extra.get("audio_size", 0)
    chars = extra.get("usage_characters", 0)

    print(f"生成成功:")
    print(f"  时长: {duration_ms / 1000:.1f} 秒")
    print(f"  大小: {file_size / 1024:.0f} KB")
    print(f"  计费字符: {chars}")
    print()

    return audio_url


def download_audio(url, output_path):
    print(f"下载音频到 {output_path} ...")
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    with open(output_path, "wb") as f:
        f.write(resp.content)
    size_kb = os.path.getsize(output_path) / 1024
    print(f"下载完成: {size_kb:.0f} KB")
    return output_path


def main():
    print("=" * 50)
    print("InventoryDoc Agent — 中文演示语音生成")
    print("=" * 50)
    print()

    api_key = get_api_key()
    audio_url = generate_speech(NARRATION, api_key)

    if audio_url:
        download_audio(audio_url, OUTPUT_FILE)
        print()
        print(f"完成! 音频文件: {OUTPUT_FILE}")
    else:
        print("错误: 未获取到音频 URL")
        sys.exit(1)


if __name__ == "__main__":
    main()
