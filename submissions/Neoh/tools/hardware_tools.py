# -*- coding: utf-8 -*-
"""硬件研发工具集（路径 B：让「磐石」的硬件 claims 真正站得住）。

提供基于本地 LLM（vLLM + ROCm）的轻量生成工具：
- generate_verilog : 根据功能描述生成可综合的 Verilog / SystemVerilog 模块
- generate_testbench: 为指定 DUT 生成测试平台（testbench）

设计要点：
- 工具本身是无状态的纯函数（符合 registry 调用契约），通过 set_engine()
  注入全局推理引擎，由 RadeonAgent.__init__ 在构造时统一注入。
- 生成采用「轻量方案」：LLM 直接产出代码文本；生成的代码可被 simulate_verilog
  工具经本地 iverilog/vvp 仿真器真正编译并运行验证（工具链已随系统安装）。
  模型被要求只输出裸代码、不带 ``` 标记，以避免
  InferenceEngine.generate 的 stop 列表（含 ```) 提前截断。
"""

import logging
import os
import re
from typing import Any, Dict, Optional

from .registry import ToolDefinition, registry

logger = logging.getLogger(__name__)

# 模块级引擎引用，由 RadeonAgent.__init__ 注入，避免破坏工具调用契约
_ENGINE = None


def set_engine(engine) -> None:
    """注入推理引擎（InferenceEngine 实例）。"""
    global _ENGINE
    _ENGINE = engine
    logger.info("硬件工具集已接入推理引擎")


def _get_engine():
    return _ENGINE


# ---------------------------------------------------------------------------
# Prompt 模板
# ---------------------------------------------------------------------------
_VERILOG_PROMPT = """你是一名资深数字电路设计工程师。请根据功能描述生成可综合的 {lang} 代码。

硬性要求：
- 只输出 {lang} 代码本身，不要任何解释文字，不要使用 ``` 代码块标记
- 模块名、端口（含方向/位宽）必须完整且可综合
- 命名规范：时钟 clk、低有效复位 rst_n、信号用小写下划线
- 关键端口用 // 单行注释说明用途
- 不要使用 initial 块做主要功能（可综合性问题）

功能描述：
{spec}
"""

_TESTBENCH_PROMPT = """你是一名资深数字电路验证工程师。请为下面的 DUT 生成 {lang} 测试平台（testbench）。

硬性要求：
- 只输出 {lang} 代码本身，不要任何解释文字，不要使用 ``` 代码块标记
- 包含时钟与复位生成（forever + #延时）、信号激励、必要的 $display / $finish
- 必须以 $finish 结束（无头环境 vvp 不会进交互式暂停，仿真才能自动收尾）
- 至少覆盖基本功能与 1~2 个边界情况
- DUT 实例化名用 dut

DUT 模块名：{dut}
DUT 接口描述：{iface}
"""


def _strip_fences(text: str) -> str:
    """防御性去除可能出现的三引号代码块标记。"""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9_]*\n", "", text)
        text = re.sub(r"\n```\s*$", "", text)
    return text.strip()


def _slug(spec: str, max_len: int = 32) -> str:
    """从描述生成简短文件名。"""
    s = re.sub(r"[^\w一-鿿]+", "_", spec.strip())[:max_len].strip("_")
    return s or "module"


def _lang_ext(language: str) -> str:
    lang = (language or "verilog").lower()
    return ".sv" if "system" in lang else ".v"


def _write_generated(code: str, output_path: Optional[str], default_name: str, ext: str):
    os.makedirs("./generated", exist_ok=True)
    if not output_path:
        output_path = os.path.join("./generated", f"{default_name}{ext}")
    # 规范化相对路径
    if output_path.startswith("./") or output_path.startswith("../"):
        output_path = os.path.abspath(output_path)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(code + "\n")
    return output_path


def generate_verilog(module_spec: str, language: str = "verilog",
                    output_path: Optional[str] = None) -> Dict[str, Any]:
    """根据功能描述生成 Verilog / SystemVerilog 模块。

    Args:
        module_spec: 模块功能描述（如 "一个带同步复位的 8 位向上计数器"）
        language: verilog 或 systemverilog
        output_path: 可选，生成文件保存路径；缺省写入 ./generated/
    """
    engine = _get_engine()
    if engine is None:
        return {"success": False, "error": "推理引擎未初始化，无法生成（RadeonAgent 构造时会注入）"}
    if not module_spec or not module_spec.strip():
        return {"success": False, "error": "module_spec 不能为空"}

    try:
        prompt = _VERILOG_PROMPT.format(lang=language, spec=module_spec.strip())
        raw = engine.generate(prompt, max_tokens=2048, temperature=0.2)
        code = _strip_fences(raw)
        if not code:
            return {"success": False, "error": "模型未返回有效代码"}

        path = _write_generated(code, output_path, _slug(module_spec), _lang_ext(language))
        logger.info(f"已生成 {language} 模块 -> {path}")
        return {
            "success": True,
            "code": code,
            "file_path": path,
            "language": language,
        }
    except Exception as e:
        logger.error(f"Verilog 生成失败: {e}")
        return {"success": False, "error": str(e)}


def generate_testbench(dut_name: str, interface_description: str,
                       language: str = "verilog",
                       output_path: Optional[str] = None) -> Dict[str, Any]:
    """为指定 DUT 生成测试平台（testbench）。

    Args:
        dut_name: 被测模块名
        interface_description: DUT 端口 / 接口描述
        language: verilog 或 systemverilog
        output_path: 可选，生成文件保存路径；缺省写入 ./generated/
    """
    engine = _get_engine()
    if engine is None:
        return {"success": False, "error": "推理引擎未初始化，无法生成（RadeonAgent 构造时会注入）"}
    if not dut_name or not dut_name.strip():
        return {"success": False, "error": "dut_name 不能为空"}

    try:
        prompt = _TESTBENCH_PROMPT.format(
            lang=language,
            dut=dut_name.strip(),
            iface=(interface_description or "（请模型根据常见接口合理假设）").strip(),
        )
        raw = engine.generate(prompt, max_tokens=2048, temperature=0.2)
        code = _strip_fences(raw)
        if not code:
            return {"success": False, "error": "模型未返回有效代码"}

        path = _write_generated(
            code, output_path, f"{dut_name.strip()}_tb", _lang_ext(language)
        )
        logger.info(f"已生成 {language} 测试平台 -> {path}")
        return {
            "success": True,
            "code": code,
            "file_path": path,
            "language": language,
            "dut": dut_name.strip(),
        }
    except Exception as e:
        logger.error(f"Testbench 生成失败: {e}")
        return {"success": False, "error": str(e)}


import subprocess  # noqa: E402  (放在文件中部以便 simulate_verilog 使用)


def simulate_verilog(testbench_path: str, dut_path: Optional[str] = None,
                    timeout: int = 60) -> Dict[str, Any]:
    """用本地 iverilog/vvp 仿真器编译并运行 Verilog/SystemVerilog，验证生成代码。

    这是把「未经验证的 HDL」短板补上的关键步骤：generate_verilog /
    generate_testbench 产出的代码经此真正编译并跑通，确认可综合、可仿真。

    Args:
        testbench_path: 测试平台文件路径（.v / .sv），其 `module` 含 $finish 收尾
        dut_path: 可选，被测设计文件路径；缺省时自动收集 testbench 同目录的
            *.v / *.sv 一并编译（iverilog 需拿到 DUT 源）
        timeout: 仿真超时秒数，防止 $finish 缺失导致 vvp 挂死
    """
    import glob
    import tempfile

    if not testbench_path or not os.path.exists(testbench_path):
        return {"success": False, "passed": False,
                "error": f"测试平台不存在: {testbench_path}"}

    # 收集待编译源文件：testbench + 显式 DUT + 同目录其他 .v/.sv
    sources = [os.path.abspath(testbench_path)]
    if dut_path:
        if not os.path.exists(dut_path):
            return {"success": False, "passed": False,
                    "error": f"DUT 文件不存在: {dut_path}"}
        sources.append(os.path.abspath(dut_path))
    else:
        tb_dir = os.path.dirname(os.path.abspath(testbench_path))
        for ext in ("*.v", "*.sv"):
            for f in sorted(glob.glob(os.path.join(tb_dir, ext))):
                af = os.path.abspath(f)
                if af not in sources:
                    sources.append(af)

    # 用 mkstemp 生成唯一临时文件，避免并发调用路径冲突
    fd, out_file = tempfile.mkstemp(prefix="sim_", suffix=".out")
    os.close(fd)  # 只需路径，关闭文件描述符
    cmd_compile = ["iverilog", "-g2012", "-o", out_file] + sources
    try:
        comp = subprocess.run(cmd_compile, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"success": False, "passed": False,
                "error": f"编译超时（>{timeout}s）"}
    except FileNotFoundError:
        return {"success": False, "passed": False,
                "error": "iverilog 未安装，无法仿真验证（请 apt-get install iverilog）"}

    if comp.returncode != 0:
        return {
            "success": False,
            "passed": False,
            "error": "编译失败（iverilog 报错）",
            "stdout": comp.stdout,
            "stderr": comp.stderr,
        }

    # 编译通过 -> 运行 vvp
    try:
        run = subprocess.run(["vvp", out_file], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        # 仿真超时视为执行失败（与编译超时一致），保留部分输出便于调试
        return {"success": False, "passed": False,
                "error": f"仿真超时（>{timeout}s，可能缺 $finish）",
                "stdout": e.stdout or "", "stderr": e.stderr or ""}
    finally:
        try:
            os.remove(out_file)
        except OSError:
            pass

    # vvp 退出码非 0 视为仿真异常；0 视为通过
    passed = run.returncode == 0
    return {
        "success": True,
        "passed": passed,
        "stdout": run.stdout,
        "stderr": run.stderr,
        "return_code": run.returncode,
    }


registry.register_tool(ToolDefinition(
    name="generate_verilog",
    description="根据功能描述，用本地 LLM 生成可综合的 Verilog/SystemVerilog 模块并写入文件",
    parameters={
        "module_spec": {"type": "string", "description": "模块功能描述，如 '带同步复位的8位向上计数器'"},
        "language": {"type": "string", "description": "verilog 或 systemverilog，默认 verilog"},
        "output_path": {"type": "string", "description": "可选，生成文件保存路径"},
    },
    function=generate_verilog,
    requires_approval=False,
))

registry.register_tool(ToolDefinition(
    name="generate_testbench",
    description="为指定 DUT 生成 Verilog/SystemVerilog 测试平台（testbench）并写入文件",
    parameters={
        "dut_name": {"type": "string", "description": "被测模块名"},
        "interface_description": {"type": "string", "description": "DUT 端口/接口描述"},
        "language": {"type": "string", "description": "verilog 或 systemverilog，默认 verilog"},
        "output_path": {"type": "string", "description": "可选，生成文件保存路径"},
    },
    function=generate_testbench,
    requires_approval=False,
))

registry.register_tool(ToolDefinition(
    name="simulate_verilog",
    description="用本地 iverilog/vvp 仿真器编译并运行 Verilog/SystemVerilog（DUT + 测试平台），"
                "验证生成代码可编译、可仿真，返回编译/运行日志与是否通过（passed）。"
                "用于把生成的 HDL 真正跑通、补上「未经验证」短板。",
    parameters={
        "testbench_path": {"type": "string", "description": "测试平台文件路径（.v/.sv），需含 $finish 收尾"},
        "dut_path": {"type": "string", "description": "可选，被测设计文件路径；缺省自动收集同目录 *.v/*.sv"},
        "timeout": {"type": "integer", "description": "编译/仿真超时秒数，默认 60"},
    },
    function=simulate_verilog,
    requires_approval=False,
))
