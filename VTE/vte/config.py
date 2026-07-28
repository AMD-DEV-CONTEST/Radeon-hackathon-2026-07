from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
MODEL_DIR = PROJECT_ROOT / "Model"
MODEL_PATH = MODEL_DIR / "Qwen2.5-1.5B-Instruct-Q4_K_M.gguf"
LOG_DIR = PROJECT_ROOT / "logs"
CACHE_DIR = PROJECT_ROOT / "cache"
KERNELS_DIR = PROJECT_ROOT / "kernels"

VRAM_SAFETY_MARGIN = 0.95
MIN_VRAM_REQUIRED = 4 * 1024 * 1024 * 1024
TDR_TIMEOUT_MS = 2000
# Teto de tempo (ms) para uma sincronização de GPU (hipDeviceSynchronize) antes
# do KernelWatchdog considerar a GPU travada e entrar em PANIC MODE, bloqueando
# novos lançamentos. 8s cobre um forward pass completo de 28 camadas mesmo sem
# cache de kernel "quente", mas ainda protege contra loops/kernels realmente
# travados (limite de "processador" da GPU, complementar ao VRAM_SAFETY_MARGIN).
SAFE_DISPATCH_TIMEOUT = 8000
CACHE_LINE_SIZE = 64
VRAM_PADDING_BYTES = 128 * 1024 * 1024

ALLOWED_MODEL_HASH = "sha256:PLACEHOLDER"
QWEN2_5_EXPECTED_HASH = "sha256:PLACEHOLDER"
GRANITE_4_1_3B_EXPECTED_HASH = "sha256:PLACEHOLDER"
GRANITE_4_1_30B_EXPECTED_HASH = "2f772a60949ab40144bca249a5a38f7fa530d6b6649c14b8b6395c4cd64ef396"
QWEN35_2B_EXPECTED_HASH = "sha256:PLACEHOLDER"
ALLOWED_MODEL_SIZE_MIN = 800 * 1024 * 1024
ALLOWED_MODEL_SIZE_MAX = 1200 * 1024 * 1024
GRANITE_4_1_3B_SIZE_MIN = 3 * 1024 * 1024 * 1024
GRANITE_4_1_3B_SIZE_MAX = 4 * 1024 * 1024 * 1024
# Arquivo real medido no benchmark do hackathon (instância cloud W7900,
# 2026-07-19): 30674969824 bytes (~28.57GiB) -- margem em torno disso, mesmo
# padrão de banda usado pros outros checkpoints curados.
GRANITE_4_1_30B_SIZE_MIN = 27 * 1024 * 1024 * 1024
GRANITE_4_1_30B_SIZE_MAX = 30 * 1024 * 1024 * 1024
# Arquivo real medido nesta sessão: 1574961408 bytes (~1.47GB) -- margem
# generosa em torno disso, mesmo padrão de banda usado pros outros dois
# modelos (não um cheque em branco, mas não colado no byte exato).
QWEN35_2B_SIZE_MIN = 1 * 1024 * 1024 * 1024
QWEN35_2B_SIZE_MAX = 2 * 1024 * 1024 * 1024
# Arquivo real medido nesta sessão: 4683074208 bytes (~4.36GB).
QWEN2_5_7B_EXPECTED_HASH = "sha256:PLACEHOLDER"
QWEN2_5_7B_SIZE_MIN = 4 * 1024 * 1024 * 1024
QWEN2_5_7B_SIZE_MAX = 5 * 1024 * 1024 * 1024
# Draft model do speculative decoding (Fase 5). Arquivo real medido nesta
# sessão: 397808192 bytes (~0.37GB).
QWEN2_5_0_5B_EXPECTED_HASH = "sha256:PLACEHOLDER"
QWEN2_5_0_5B_SIZE_MIN = 300 * 1024 * 1024
QWEN2_5_0_5B_SIZE_MAX = 500 * 1024 * 1024
# Benchmark do hackathon AMD (W7900 na nuvem, 2026-07-19). Arquivo real
# medido via HEAD request antes do download completar: 19851336576 bytes
# (~18.49GiB, bartowski/Qwen2.5-32B-Instruct-GGUF, Q4_K_M).
QWEN2_5_32B_EXPECTED_HASH = "2e5f6daea180dbc59f65a40641e94d3973b5dbaa32b3c0acf54647fa874e519e"
QWEN2_5_32B_SIZE_MIN = 17 * 1024 * 1024 * 1024
QWEN2_5_32B_SIZE_MAX = 20 * 1024 * 1024 * 1024
# Arquivo real medido nesta sessão (bartowski/Meta-Llama-3.1-8B-Instruct-GGUF,
# Q4_K_M): 4920739232 bytes (~4.58GB). Hash calculado e confirmado nesta
# sessão (mesmo arquivo usado para depurar e corrigir o bug de rope_type).
LLAMA3_1_8B_EXPECTED_HASH = "7b064f5842bf9532c91456deda288a1b672397a54fa729aa665952863033557c"
LLAMA3_1_8B_SIZE_MIN = int(4.5 * 1024 * 1024 * 1024)
LLAMA3_1_8B_SIZE_MAX = 5 * 1024 * 1024 * 1024

DEFAULT_GPU_ARCH = "gfx1100"
GPU_ARCH_MAP = {
    "rx 7600": "gfx1102", "rx 7600 xt": "gfx1101", "rx 7700": "gfx1101",
    "rx 7700 xt": "gfx1101", "rx 7800 xt": "gfx1101", "rx 7900": "gfx1100",
    "rx 7900 xt": "gfx1100", "rx 7900 xtx": "gfx1100",
    "w7900": "gfx1100", "w7800": "gfx1100", "w7700": "gfx1101", "w7600": "gfx1102",
    "rx 6600": "gfx1032", "rx 6600 xt": "gfx1032", "rx 6650 xt": "gfx1032",
    "rx 6700": "gfx1031", "rx 6700 xt": "gfx1031", "rx 6750 xt": "gfx1031",
    "rx 6800": "gfx1030", "rx 6800 xt": "gfx1030",
    "rx 6900": "gfx1030", "rx 6900 xt": "gfx1030", "rx 6950 xt": "gfx1030",
    "rx 6500 xt": "gfx1034", "rx 6400": "gfx1034",
}

VRAM_USAGE_LIMIT = VRAM_SAFETY_MARGIN
MAX_SHARED_MEM_PER_BLOCK = 64 * 1024
MAX_GRID_DIMENSIONS = (2**31) - 1
