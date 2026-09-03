"""
hardware.py — the agent's self-awareness layer.

Gives the local optimizer-agent three things it can call on its own:
  1. detect_hardware()   — what GPU am I actually running on? (rocminfo / rocm-smi, live)
  2. hardware_map(arch)  — the optimization-relevant facts + ISA sources for that arch (or any RDNA/CDNA)
  3. list_gpu_targets()  — enumerate ALL known RDNA/CDNA targets, so it can reason across hardware

The agent is NOT told its answer; it is told how to find its hardware and what each arch can do, then
it tailors the optimization to whatever target it detects. Everything here works offline (rocminfo +
built-in map + local llvm disassembly); ISA_SOURCES also lists where to fetch the authoritative docs.
"""
import subprocess, re

# --- the RDNA/CDNA hardware map (optimization-relevant facts we mined) --------------------------
# keyed by gfx target. 'matrix' = matrix engine; 'fp8' = native fp8 datapath; 'levers' = the knobs
# that actually move llama.cpp inference on this arch; 'known' = validated results from our work.
MAP = {
    # ---- RDNA4 ----
    "gfx1201": {"arch": "RDNA4", "name": "Radeon AI PRO R9700 / RX 9070 XT", "wave": 32,
                "matrix": "WMMA (f16/bf16/iu8/iu4 16x16x16 + iu4 16x16x32 + native fp8)",
                "fp8": True, "dp4a": True,
                "levers": ["spec-decode (DFlash depth)", "fp8 E4M3/E5M2 weights+KV", "MXFP8",
                           "rpb/nwarps MMVQ dispatch", "quant choice (Q2_0/Q1_0 ternary)"],
                "known": "DFlash depth-4 = 2.34x decode; native fp8 kernels; iu4 W4A4 does NOT beat "
                         "dp4a/MMQ for ternary (weight-memory-bound); rpb=3 +3.7%."},
    "gfx1200": {"arch": "RDNA4", "name": "RX 9070 / 9060", "wave": 32,
                "matrix": "WMMA + native fp8", "fp8": True, "dp4a": True,
                "levers": ["spec-decode", "fp8", "MXFP8", "rpb/nwarps"], "known": "same family as gfx1201."},
    # ---- RDNA next-gen ----
    "gfx1250": {"arch": "RDNA-next", "name": "next-gen RDNA (gfx1250)", "wave": 32,
                "matrix": "WMMA + SWMMAC + NATIVE MX-WMMA (MXFP4/6/8 w/ hw scale) + scale-convert units",
                "fp8": True, "dp4a": True, "mx_native": True,
                "levers": ["native MXFP4/6/8 (hw scale, NOT software-convert)",
                           "v_cvt_scalef32_* scale-convert (pk_fp8/pk32_fp6/2xpk16_fp6)",
                           "fp4/fp6 scale-cvt", "+ all gfx1201 levers (SWMMAC 2:4, dot8, fp8)"],
                "known": "The instructions GATED/ABSENT on gfx1201 (v_cvt_scalef32_*, MX-WMMA via "
                         "scale_gfx125.hpp, fp4-cvt-scale) are NATIVE here. On gfx1201 MX is convert-only "
                         "(software); on gfx1250 it is a real matrix+scale lever. The arch check must FLIP: "
                         "USE MX-scale on gfx1250, SKIP it (gated) on gfx1201."},
    # ---- RDNA3 / 3.5 ----
    "gfx1100": {"arch": "RDNA3", "name": "RX 7900 XTX/XT, PRO W7900/W7800", "wave": 32,
                "matrix": "WMMA (f16/bf16/iu8/iu4 16x16x16)", "fp8": False, "dp4a": True,
                "levers": ["spec-decode", "WMMA prefill tiling", "quant choice", "nwarps"],
                "known": "no native fp8 (emulate); WMMA present; bandwidth-bound decode."},
    "gfx1151": {"arch": "RDNA3.5", "name": "Strix Halo iGPU (Radeon 8060S, Ryzen AI Max)", "wave": 32,
                "matrix": "WMMA", "fp8": False, "dp4a": True,
                "levers": ["spec-decode", "unified-memory-aware batching", "quant choice"],
                "known": "UNIFIED memory (CPU+GPU share DDR5-LPDDR) -> bandwidth-STARVED; favor small "
                         "quant + spec-decode; WMMA tiling less useful than on dGPU."},
    "gfx1030": {"arch": "RDNA2", "name": "RX 6900/6800 XT", "wave": 32, "matrix": "none (v_dot dp4a)",
                "fp8": False, "dp4a": True, "levers": ["spec-decode", "quant choice", "dp4a decode"],
                "known": "NO matrix engine; dp4a only; prefill is vector-bound."},
    # ---- CDNA (Instinct) ----
    "gfx942": {"arch": "CDNA3", "name": "Instinct MI300X/MI300A", "wave": 64,
               "matrix": "MFMA (fp16/bf16/fp8)", "fp8": True, "dp4a": True,
               "levers": ["MFMA tiling (wave64)", "fp8", "large-batch throughput", "vLLM runtime params"],
               "known": "wave64 + MFMA; throughput/batch-oriented, NOT batch-1 latency; huge HBM bandwidth."},
    "gfx950": {"arch": "CDNA4", "name": "Instinct MI350X / MI355X", "wave": 64, "mx_native": True,
               "matrix": "MFMA + NATIVE MX (MXFP4/6/8 w/ hw scale) + fp8/fp4 scale-convert",
               "fp8": True, "dp4a": True,
               "levers": ["native MXFP4/6/8 MFMA (hw scale)", "fp8/fp4 scale-convert",
                          "wave64 MFMA tiling", "massive HBM bandwidth", "large-batch throughput",
                          "vLLM/SGLang runtime", "QuickReduce compressed all-reduce"],
               "known": "CDNA4; like gfx1250 the MX scale-convert + fp4 are NATIVE (gated on gfx1201). "
                        "Throughput/batch-oriented; the GPU MODE / distributed-inference contests run here."},
    "gfx90a": {"arch": "CDNA2", "name": "Instinct MI250/MI210", "wave": 64, "matrix": "MFMA (fp16/bf16)",
               "fp8": False, "dp4a": True, "levers": ["MFMA tiling", "batch throughput"],
               "known": "wave64 MFMA, no fp8; HBM2e."},
    "gfx908": {"arch": "CDNA1", "name": "Instinct MI100", "wave": 64, "matrix": "MFMA (fp16/bf16)",
               "fp8": False, "dp4a": True, "levers": ["MFMA tiling", "batch throughput"], "known": "first MFMA gen."},
    # ---- AMD CPU (EPYC / Ryzen) — inference via AVX-512-VNNI + zentorch / vLLM-CPU ----
    "znver5": {"arch": "Zen5 CPU", "name": "EPYC 9005 Turin / Threadripper 9000(WX) & PRO / Ryzen 9000",
               "wave": None, "cpu": True,
               "matrix": "AVX-512 SIMD (VNNI int8, BF16) — no tensor engine", "fp8": False, "dp4a": True,
               "levers": ["AVX-512-VNNI int8 GEMM", "AVX-512-BF16", "zentorch (AMD torch backend)",
                          "vLLM-CPU", "pin to ONE socket + its NUMA memory", "int8/int4 weight quant",
                          "large system-RAM KV", "many-core parallelism (Threadripper/EPYC)"],
               "known": "CPU inference is bandwidth+SIMD-bound; AVX-512-VNNI does the int8 matmul. TIER: "
                        "Ryzen (desktop, dual-channel) < Threadripper/TR-PRO (HEDT/workstation, up to 96c + "
                        "quad/octa-channel = much higher throughput, single-socket so NO cross-socket penalty) "
                        "< EPYC (server, dual-socket -> pin to ONE socket, vLLM scales poorly across sockets). "
                        "See amd/skills serving-llms-on-epyc."},
    "znver4": {"arch": "Zen4 CPU", "name": "EPYC 9004 Genoa / Threadripper 7000(WX) & PRO / Ryzen 7000",
               "wave": None, "cpu": True,
               "matrix": "AVX-512 (VNNI int8, BF16)", "fp8": False, "dp4a": True,
               "levers": ["AVX-512-VNNI int8", "AVX-512-BF16", "zentorch", "vLLM-CPU", "NUMA pinning", "int8/int4 quant"],
               "known": "first AMD AVX-512 gen; same CPU-inference levers as Zen5, lower throughput."},
    "znver3": {"arch": "Zen3 CPU", "name": "EPYC 7003 Milan / Ryzen 5000", "wave": None, "cpu": True,
               "matrix": "AVX2 (no AVX-512)", "fp8": False, "dp4a": True,
               "levers": ["AVX2 int8/fp32 GEMM", "vLLM-CPU", "NUMA pinning", "int8/int4 quant"],
               "known": "no AVX-512; AVX2 only -> lower int8 throughput; still viable for small models."},
    # ---- AMD NPU (Ryzen AI / XDNA) ----
    "xdna2": {"arch": "XDNA2 NPU", "name": "Ryzen AI 300 NPU (Strix / Strix Halo)", "wave": None, "npu": True,
              "matrix": "AIE tiled array — int8/int4/bf16, ~50 TOPS", "fp8": False, "dp4a": True,
              "levers": ["int8/int4 quantized models on the AIE", "Ryzen AI SW / ONNX-RT / Lemonade",
                         "power-efficient decode offload", "hybrid NPU + gfx1151 iGPU"],
              "known": "Ryzen AI NPU: power-efficient int8/int4 inference; quantize to the NPU's supported "
                       "types; served via Lemonade / ONNX Runtime. Pairs with the Strix Halo iGPU (gfx1151)."},
    "xdna1": {"arch": "XDNA1 NPU", "name": "Ryzen AI 7040/8040 NPU (Phoenix / Hawk Point)", "wave": None, "npu": True,
              "matrix": "AIE array — int8, ~10-16 TOPS", "fp8": False, "dp4a": True,
              "levers": ["int8 quantized models on the AIE", "Ryzen AI SW / Lemonade", "power-efficient offload"],
              "known": "first-gen Ryzen AI NPU; int8-focused; lower TOPS than XDNA2."},
    # ---- AMD APU (unified CPU + iGPU + NPU on ONE chip, shared memory) ----
    "strix-halo": {"arch": "APU (Ryzen AI Max)", "name": "Ryzen AI Max 300 — Strix Halo", "apu": True,
                   "engines": {"cpu": "znver5", "igpu": "gfx1151 (RDNA3.5)", "npu": "xdna2 (~50 TOPS)"},
                   "matrix": "iGPU WMMA + NPU AIE + CPU AVX-512-VNNI — pick per phase", "fp8": False, "dp4a": True,
                   "levers": ["UNIFIED LPDDR5X (up to 128GB, NO CPU<->GPU copy) — big models fit, zero-copy hand-off",
                              "HYBRID partition: NPU=power-efficient decode, iGPU=parallel prefill, CPU=orchestration/overflow",
                              "bandwidth-STARVED (shared LPDDR) -> byte-width is everything: aggressive int4/mxfp quant + spec-decode",
                              "Lemonade auto-routes across NPU/iGPU/CPU"],
                   "known": "The whole substrate on ONE chip. Unified memory = fit big models + zero-copy between "
                            "engines; shared LPDDR bandwidth is the wall -> small quant. THE premier whole-substrate "
                            "optimizer target: partition the model across NPU+iGPU+CPU. Drill into engines[] for per-engine levers."},
    "strix-point": {"arch": "APU (Ryzen AI 300)", "name": "Ryzen AI 300 — Strix Point", "apu": True,
                    "engines": {"cpu": "znver5", "igpu": "RDNA3.5 iGPU", "npu": "xdna2 (~50 TOPS)"},
                    "matrix": "iGPU WMMA + NPU AIE + CPU AVX-512-VNNI", "fp8": False, "dp4a": True,
                    "levers": ["unified DDR5/LPDDR5", "hybrid NPU+iGPU+CPU", "aggressive quant", "Lemonade routing"],
                    "known": "mainstream Ryzen AI APU; same hybrid levers as Strix Halo, smaller iGPU + less bandwidth."},
    "phoenix": {"arch": "APU (Ryzen 7040/8040)", "name": "Ryzen AI 7040/8040 — Phoenix / Hawk Point", "apu": True,
                "engines": {"cpu": "znver4", "igpu": "RDNA3 iGPU", "npu": "xdna1 (~10-16 TOPS)"},
                "matrix": "iGPU WMMA + NPU AIE + CPU AVX-512-VNNI", "fp8": False, "dp4a": True,
                "levers": ["unified DDR5", "hybrid NPU(XDNA1)+iGPU(RDNA3)+CPU", "int8 quant", "Lemonade routing"],
                "known": "first Ryzen AI APU gen; XDNA1 (int8, lower TOPS) + RDNA3 iGPU + Zen4."},
}

# --- where to get the ISA / arch details on its own -------------------------------------------
ISA_SOURCES = {
    "RDNA4": {"isa_pdf": "https://gpuopen.com/download/RDNA4_Instruction_Set_Architecture.pdf",
              "llvm": "https://llvm.org/docs/AMDGPU/AMDGPUAsmGFX1200.html",
              "matrix_calc": "https://github.com/ROCm/amd_matrix_instruction_calculator"},
    "RDNA3": {"isa_pdf": "https://gpuopen.com/download/RDNA3_Instruction_Set_Architecture.pdf",
              "llvm": "https://llvm.org/docs/AMDGPU/AMDGPUAsmGFX11.html",
              "matrix_calc": "https://github.com/ROCm/amd_matrix_instruction_calculator"},
    "RDNA3.5": {"isa_pdf": "https://gpuopen.com/download/RDNA3_Instruction_Set_Architecture.pdf",
                "llvm": "https://llvm.org/docs/AMDGPU/AMDGPUAsmGFX1150.html"},
    "RDNA2": {"isa_pdf": "https://gpuopen.com/download/RDNA2_Shader_ISA_November2020.pdf",
              "llvm": "https://llvm.org/docs/AMDGPU/AMDGPUAsmGFX1030.html"},
    "CDNA3": {"isa_pdf": "https://www.amd.com/content/dam/amd/en/documents/instinct-tech-docs/instruction-set-architectures/amd-instinct-mi300-cdna3-instruction-set-architecture.pdf",
              "matrix_calc": "https://github.com/ROCm/amd_matrix_instruction_calculator"},
    "_local": "llvm-mc -triple=amdgcn -mcpu=<gfx> -show-encoding  |  llvm-objdump --arch=amdgcn --mcpu=<gfx> -d <obj>  |  rocminfo  |  rocm-smi --showhw",
}


def _run(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=30).stdout
    except Exception:
        return ""

def detect():
    """Live-probe the GPU(s) this agent is running on. Offline, always available.
    gfx targets come from rocminfo (GPU agent blocks only); card count / names / VRAM from rocm-smi."""
    # gfx targets — take Name: gfx* only from agent blocks that are GPUs (skip the CPU agent)
    rinfo, gfx_list = _run(["rocminfo"]), []
    cur_is_gpu, cur_gfx = False, None
    for line in rinfo.splitlines():
        if re.search(r"Device Type:\s*CPU", line): cur_is_gpu = False
        if re.search(r"Device Type:\s*GPU", line): cur_is_gpu = True
        m = re.search(r"Name:\s*(gfx\d+\w*)", line)
        if m and cur_is_gpu: gfx_list.append(m.group(1))
    # card count + marketing names + VRAM from rocm-smi (authoritative for per-card info)
    smi = _run(["rocm-smi", "--showproductname"])
    names = re.findall(r"GPU\[(\d+)\][^\n]*Card Series:\s*(.+)", smi) or \
            re.findall(r"GPU\[(\d+)\][^\n]*(?:Card Model|Device Name|Marketing Name):\s*(.+)", smi)
    vram = _run(["rocm-smi", "--showmeminfo", "vram"])
    vgb = [round(int(x)/1e9, 1) for x in re.findall(r"VRAM Total Memory \(B\):\s*(\d+)", vram)]
    n_cards = len(vgb) or len(set(i for i, _ in names)) or len(gfx_list)
    primary = gfx_list[0] if gfx_list else None
    cards = [{"gpu": i, "name": n.strip()} for i, n in names]
    for k, g in enumerate(cards):
        if k < len(vgb): g["vram_gb"] = vgb[k]
    prof = {"detected_gfx": primary, "n_cards": n_cards, "distinct_gfx": sorted(set(gfx_list)),
            "vram_gb_per_card": vgb, "cards": cards}
    if primary in MAP:
        prof["profile"] = {**MAP[primary], "gfx": primary}
        prof["isa_sources"] = ISA_SOURCES.get(MAP[primary]["arch"], {})
    return prof


# --- tools the agent can call (merged into every task) -----------------------------------------
HW_TOOLS = [
    {"type": "function", "function": {
        "name": "detect_hardware",
        "description": "Detect the GPU(s) this agent is running on (gfx target, arch, matrix engine, "
                       "native-fp8 support, VRAM). Call this FIRST to know your hardware before choosing an "
                       "optimization strategy.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "hardware_map",
        "description": "Get the optimization-relevant facts (matrix engine, fp8, the levers that work, "
                       "known results) and ISA-document sources for a given gfx target or arch. Omit 'target' "
                       "to get the map for the detected hardware.",
        "parameters": {"type": "object", "properties": {
            "target": {"type": "string", "description": "gfx id (e.g. gfx1201) or arch (e.g. RDNA3). optional."}}}}},
    {"type": "function", "function": {
        "name": "list_gpu_targets",
        "description": "Enumerate all RDNA/CDNA GPU targets the agent knows about, so it can reason across "
                       "hardware and pick strategy for a target other than the one it's on.",
        "parameters": {"type": "object", "properties": {}}}},
]

def hw_execute(fn, args):
    if fn == "detect_hardware":
        return detect()
    if fn == "list_gpu_targets":
        return {gfx: {"arch": m["arch"], "name": m["name"], "matrix": m["matrix"], "fp8": m["fp8"]}
                for gfx, m in MAP.items()}
    if fn == "hardware_map":
        tgt = (args or {}).get("target")
        if not tgt:
            tgt = detect().get("detected_gfx")
        if tgt in MAP:
            return {"target": tgt, **MAP[tgt], "isa_sources": ISA_SOURCES.get(MAP[tgt]["arch"], {})}
        for gfx, m in MAP.items():   # allow lookup by arch name
            if m["arch"].lower() == str(tgt).lower():
                return {"target": gfx, **m, "isa_sources": ISA_SOURCES.get(m["arch"], {})}
        return {"error": f"unknown target {tgt}", "known_targets": list(MAP.keys())}
    return {"error": f"unknown hw tool {fn}"}


HW_PREAMBLE = (
    "You are hardware-aware. BEFORE choosing any optimization, call detect_hardware() to learn your "
    "gfx target and its capabilities, then hardware_map() for the levers that actually work on that arch "
    "(and where to find its ISA). Do NOT apply an optimization the detected hardware can't do (e.g. native "
    "fp8 exists only on RDNA4/CDNA3; MFMA is CDNA/wave64; RDNA1/2 have no matrix engine). Tailor strategy to "
    "the silicon you are actually on.")


if __name__ == "__main__":
    import json
    print(json.dumps(detect(), indent=2))
