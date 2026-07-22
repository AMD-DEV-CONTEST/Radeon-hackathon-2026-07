"""
API principal do VTE - Estilo PyTorch/Ollama
"""

from pathlib import Path
from typing import Optional
from ..bridge.hip_runtime import HIPRuntime
from ..compiler.sanitizer import GGUFSanitizer
from .lifecycle import ModelLifecycleManager
from ..bridge.logger import get_logger
from ..compiler.tokenizer import QwenTokenizer
from ..core.sampler import Sampler
from ..core.hip_graph_executor import HIPGraphExecutor
from ..core.fallback_executor import FallbackExecutor
from ..compiler.qwen_mapper import QwenTensorMapper, ActivationArena
from ..bridge.memory import MemoryBlock, SlabAllocator, MemoryRegion
from ..bridge.errors import HIPSafetyError
from vte.core.vram_profiler import VRAMProfiler
from vte.bridge.kernel_profiler import PROFILER as _KERNEL_PROFILER
from ..compiler.gguf_parser import GGUFParser
from ..compiler.weight_loader import GGUFWeightLoader
from ..core.lm_head import LMHead
from ..core.incremental_decoder import IncrementalUTF8Decoder
from ..core.constrained_decoding import ChoiceConstraint
import os
import time
import threading
import ctypes
import numpy as np

logger = get_logger("VTE.Model")

# Batched/chunked prefill (VTE_BATCHED_PREFILL, default ON again since
# 2026-07-22). Was briefly reverted to off the same day after a deep
# investigation found the generated first token genuinely diverged from
# the sequential path for Qwen2.5 1.5B (Q4_K), with every individual
# kernel (embedding lookup, RMSNorm, gemm_q4k_wmma, the attention pair)
# independently validated correct against real weights and real
# activations -- the investigation's own control data even contradicted
# its leading hypothesis (Split-KV/RoPE). Root cause found shortly
# after, on a re-read of the same evidence with fresh eyes: Qwen2.5 uses
# attention_bias=True (real blk.N.attn_{q,k,v}.bias tensors in the
# GGUF), unlike Llama 3.1 8B, the only model this kernel had ever been
# validated against -- gemm_q4k_wmma's kernel signature simply had no
# bias parameter at all, so q/k/v_proj silently dropped it for any
# model that has one. Confirmed by direct arithmetic before touching any
# code: an isolated gemv_q4k call (no bias) plus the real attn_k.bias,
# summed in NumPy, matched the sequential path's real k_cache element-
# for-element. Fixed by adding a bias_ptr parameter to the kernel
# (resolved via the same KernelArgBuilder._resolve_matmul_bias gemv_q4k
# already used, nullptr for weights with no bias) -- re-verified
# byte-identical to sequential on Qwen2.5 1.5B, 60 generated tokens,
# real prompt, greedy. See docs/LIMITATIONS.md#batching-and-prefill for
# the full investigation and fix.
#
# The rest of this comment describes the chunk-size defaults chosen
# back when the feature was on; those still apply if VTE_BATCHED_PREFILL=1
# is set explicitly. See _ensure_batched_prefill_executor for the
# runtime free-VRAM check. Chunk size is deliberately small and fixed
# rather than scaling to the prompt, for two independent reasons. (1) The
# fallback seq_len=N attention kernel used if the primary tree-reduction
# path (PrefillAttentionDispatcher) ever fails to build its launch args
# (gqa_attention.hip.template) keeps a per-thread `float scores[2048]`
# local array -- total cached+new positions per chunk must stay
# comfortably under 2048, see _BATCHED_PREFILL_MAX_CONTEXT below. (2) Extra
# VRAM for the chunk's own activation buffers scales with chunk_size (see
# _estimate_chunk_activation_bytes) -- kept small enough to stay safe on
# an 8GB card (RX 7600), not just the 48GB W7900 this was measured on;
# _ensure_batched_prefill_executor also checks free VRAM explicitly before
# committing, so this is a sane default, not the only thing standing
# between this feature and an OOM on a smaller card. Default chunk_size=64
# (not 128): measured as the fastest on the W7900 (1.96x vs sequential
# TTFT, median of 3, vs 1.64x at chunk=128) -- also happens to exactly
# match the WMMA GEMM kernel's M_TILE=64, so no wasted tile padding.
_BATCHED_PREFILL_CHUNK_SIZE = int(os.environ.get("VTE_BATCHED_PREFILL_CHUNK_SIZE", "64"))
_BATCHED_PREFILL_MAX_CONTEXT = 2048

# vte/core/model.py -> raiz do repo é dois níveis acima. Resolvido a partir
# de __file__ (não do cwd) porque `vte-ui`/`vte` são instalados como pacote
# e podem ser invocados de qualquer diretório -- procurar "Model/" relativo
# ao cwd atual falhava silenciosamente sempre que o processo não era
# lançado a partir da raiz do projeto (ex.: atalho, outro terminal),
# mesmo com o arquivo do modelo presente e no lugar certo.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent

class VTEModel:
    """
    Interface de alto nível para carregar e usar modelos de linguagem.
    
    Exemplo:
        >>> model = VTEModel.from_pretrained("qwen2.5:1.5b-q4_k_m")
        >>> response = model.generate("Olá", max_tokens=100)
    """
    
    MODEL_REGISTRY = {
        "qwen2.5:1.5b-q4_k_m": "Qwen2.5-1.5B-Instruct-Q4_K_M.gguf",
        "granite-4.1:3b-q8_0": "granite-4.1-3b-Q8_0.gguf",
        "granite-4.1:30b-q8_0": "granite-4.1-30b-Q8_0.gguf",
        "qwen3.5:2b-q6_k": "Qwen3.5-2B-Q6_K.gguf",
        # Mesma arquitetura "qwen2" (_load_qwen2_metadata já lê hidden_size/
        # n_layers/n_heads do metadata do GGUF, nada hardcoded pro 1.5B) --
        # registrar o 7B é literalmente só esta linha. VRAM: ~4.3GB de pesos
        # Q4_K_M cru + KV/arena, cabe nos 8GB da RX 7600 (ver
        # docs/PERFORMANCE.md). O checkpoint OOM preventivo em
        # qwen_mapper.py::map_and_allocate_tensors já usa a VRAM REAL da
        # GPU (hip_runtime.py::initialize, hipGetDeviceProperties) -- numa
        # GPU maior (ex. RX 7900 XTX, 24GB) a mesma checagem aceita
        # naturalmente, sem código novo.
        "qwen2.5:7b-q4_k_m": "Qwen2.5-7B-Instruct.Q4_K_M.gguf",
        # Qwen2.5 0.5B -- fica em Model/Classifier/ (subpasta dedicada), não
        # em Model/ raiz. `from_pretrained` resolve isso sem mudança:
        # Path("Model") / "Classifier/Qwen2.5-...gguf" já produz o caminho
        # relativo certo, e o whitelist de nome no sanitizer usa Path.name
        # (só o basename), então a subpasta não interfere na validação.
        "qwen2.5:0.5b-q4_k_m-draft": "Classifier/Qwen2.5-0.5B-Instruct-Q4_K_M.gguf",
        "llama3.1:8b-instruct-q4_k_m": "Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf",
        "qwen2.5:32b-q4_k_m": "Qwen2.5-32B-Instruct-Q4_K_M.gguf",
    }

    # Modelos cujo tokenizer emite <think>/</think> como texto literal (ver
    # Qwen3_5Tokenizer._LITERAL_SPECIAL_TOKENS em compiler/tokenizer.py) --
    # única fonte de verdade sobre "thinking mode" para quem consome
    # VTEModel (hoje só a UI Flet), evita duplicar essa lista em app.py.
    SUPPORTS_THINKING = frozenset({"qwen3.5:2b-q6_k"})

    DEFAULT_CONTEXT_LENGTH = 2048

    def __init__(self, gguf_path: str, use_hip_graph: bool = True, enable_fusion: bool = True, context_length: int = None, idle_timeout: int = 5, auto_unload: bool = True, max_batch_size: int = 1):
        self._path = gguf_path
        self._use_hip_graph = use_hip_graph
        self._enable_fusion = enable_fusion
        self._hip = None
        self._allocator = None
        self._graph = None
        self.compute_graph = None
        self._is_loaded = False
        self._context_length = context_length if context_length is not None else self.DEFAULT_CONTEXT_LENGTH
        # Fase II (prep): reserva headroom de VRAM no pool para permitir
        # generate_batch() alocar KV cache/arena de até `max_batch_size` sob
        # demanda, sem re-hipMalloc do pool inteiro. Pesos não escalam com
        # batch — só o KV cache/arena do maior batch pretendido precisa de
        # espaço reservado de antemão.
        self._max_batch_size = max(1, max_batch_size)
        
        self.idle_timeout = idle_timeout
        self.auto_unload = auto_unload
        self._last_access_time = 0
        self._watchdog_thread = None
        self._stop_watchdog = threading.Event()
        self.profiler = None
        
        self._lifecycle = ModelLifecycleManager(
            self,
            idle_timeout_seconds=idle_timeout,
            enable_auto_unload=auto_unload
        )
    
    @classmethod
    def discover_models(cls) -> dict:
        """Escaneia Model/ (recursivo, cobre subpastas como Model/Classifier/)
        por qualquer `.gguf` e mapeia nome amigável (stem do arquivo) -> Path
        resolvido. Descoberta dinâmica: basta copiar um arquivo pra Model/
        pra ele ficar carregável por `from_pretrained(stem)`, sem editar
        MODEL_REGISTRY nem nenhum código -- a arquitetura (qwen2/granite/
        qwen35) e o tamanho continuam validados pelo sanitizer no load (ver
        sanitizer.py::SUPPORTED_ARCHITECTURES), não aqui. Arquivos com o
        mesmo stem em raízes diferentes: o primeiro encontrado vence."""
        roots = [p for p in (Path("Model"), _REPO_ROOT / "Model") if p.is_dir()]
        discovered: dict[str, Path] = {}
        for root in roots:
            for gguf_path in sorted(root.rglob("*.gguf")):
                discovered.setdefault(gguf_path.stem, gguf_path)
        return discovered

    @classmethod
    def from_pretrained(
        cls,
        model_name: str,
        use_hip_graph: bool = True,
        enable_fusion: bool = True,
        idle_timeout_seconds: int = 300,
        enable_auto_unload: bool = True,
        max_batch_size: int = 1,
        context_length: int = None
    ) -> "VTEModel":
        if model_name in cls.MODEL_REGISTRY:
            filename = cls.MODEL_REGISTRY[model_name]
            # Tenta primeiro relativo ao diretório de trabalho atual (permite
            # uma pasta Model/ própria fora do repo, se o usuário quiser rodar
            # assim), e só depois relativo à raiz do projeto -- que é o que
            # realmente resolve o caso comum de `vte-ui` ser instalado como
            # comando e invocado de qualquer lugar.
            candidates = [Path("Model") / filename, _REPO_ROOT / "Model" / filename]
            model_path = next((p for p in candidates if p.exists()), None)
            if model_path is None:
                checked = "\n".join(f"  - {p.resolve()}" for p in candidates)
                raise FileNotFoundError(
                    f"Arquivo do modelo não encontrado. Caminhos checados:\n{checked}\n"
                    f"Baixe o modelo e coloque-o na pasta 'Model/' na raiz do projeto "
                    f"({_REPO_ROOT / 'Model'})."
                )
        else:
            # Não é um nome registrado -- procura por descoberta dinâmica
            # (qualquer .gguf já presente em Model/, pelo stem do arquivo).
            discovered = cls.discover_models()
            model_path = discovered.get(model_name)
            if model_path is None:
                available = ", ".join(cls.MODEL_REGISTRY.keys()) or "(nenhum)"
                found = ", ".join(sorted(discovered.keys())) or "(nenhum .gguf em Model/)"
                raise ValueError(
                    f"Modelo '{model_name}' não encontrado.\n"
                    f"Nomes registrados: {available}\n"
                    f"Arquivos .gguf encontrados em Model/: {found}"
                )

        instance = cls(
            str(model_path),
            use_hip_graph=use_hip_graph,
            enable_fusion=enable_fusion,
            context_length=context_length,
            idle_timeout=idle_timeout_seconds,
            auto_unload=enable_auto_unload,
            max_batch_size=max_batch_size
        )
        instance._load()
        instance._lifecycle.start_monitoring()
        return instance

    @classmethod
    def from_path(
        cls,
        gguf_path: str,
        use_hip_graph: bool = True,
        enable_fusion: bool = True,
        idle_timeout_seconds: int = 300,
        enable_auto_unload: bool = True,
        max_batch_size: int = 1,
        context_length: int = None
    ) -> "VTEModel":
        """Mesma lógica final de `from_pretrained`, mas para um path absoluto
        já resolvido pelo chamador -- pula inteiramente MODEL_REGISTRY/
        discover_models(). Existe para hosts externos (ex.: vte-server, que
        recebe o path já resolvido por um model manager de terceiros) que não
        querem/precisam da convenção de pasta Model/ deste projeto."""
        p = Path(gguf_path)
        if not p.is_file():
            raise FileNotFoundError(f"Arquivo GGUF não encontrado: {gguf_path}")

        instance = cls(
            str(p),
            use_hip_graph=use_hip_graph,
            enable_fusion=enable_fusion,
            context_length=context_length,
            idle_timeout=idle_timeout_seconds,
            auto_unload=enable_auto_unload,
            max_batch_size=max_batch_size
        )
        instance._load()
        instance._lifecycle.start_monitoring()
        return instance

    def _load_qwen2_metadata(self, sanitizer) -> dict:
        """Lê os hiperparâmetros REAIS do GGUF em vez de depender de defaults
        espalhados pelo código. Vários defaults estavam ERRADOS para o
        Qwen2.5-1.5B (head_count=12 não 16, rope.freq_base=1e6 não 1e4,
        eps=1e-6 não 1e-5), quebrando GQA, RoPE e lançando blocos de cabeça
        fora dos limites. As chaves aqui são as (sem prefixo 'qwen2.') que
        kernel_arg_builder/qwen_compute/qwen_mapper consultam. Comportamento
        INTOCADO em relação à versão anterior (pré-Granite) desta função."""
        from ..compiler.gguf_metadata import read_gguf_metadata
        raw = read_gguf_metadata(self._path, wanted_keys={
            "qwen2.embedding_length", "qwen2.block_count", "qwen2.context_length",
            "qwen2.attention.head_count", "qwen2.attention.head_count_kv",
            "qwen2.attention.key_length", "qwen2.feed_forward_length",
            "qwen2.rope.freq_base", "qwen2.attention.layer_norm_rms_epsilon",
        })

        embedding_length = raw.get("qwen2.embedding_length", sanitizer.header.embedding_length)
        head_count = raw.get("qwen2.attention.head_count", 12)
        # Qwen2.5 não armazena key_length separado no GGUF; head_dim = hidden / n_heads.
        head_dim = raw.get("qwen2.attention.key_length", embedding_length // head_count)

        metadata = {
            "embedding_length": embedding_length,
            "block_count": raw.get("qwen2.block_count", sanitizer.header.block_count),
            "context_length": raw.get("qwen2.context_length", sanitizer.header.context_length),
            "attention.head_count": head_count,
            "attention.head_count_kv": raw.get("qwen2.attention.head_count_kv", 2),
            "attention.key_length": head_dim,
            "feed_forward_length": raw.get("qwen2.feed_forward_length", 8960),
            "rope.freq_base": raw.get("qwen2.rope.freq_base", 1000000.0),
            "attention.layer_norm_rms_epsilon": raw.get("qwen2.attention.layer_norm_rms_epsilon", 1e-6),
        }
        logger.info(
            f"Hiperparâmetros GGUF (Qwen2.5): hidden={embedding_length}, heads={head_count}, "
            f"kv_heads={metadata['attention.head_count_kv']}, head_dim={head_dim}, "
            f"ffn={metadata['feed_forward_length']}, rope_theta={metadata['rope.freq_base']}, "
            f"eps={metadata['attention.layer_norm_rms_epsilon']:.2e}"
        )
        return metadata

    def _load_granite_metadata(self, sanitizer) -> dict:
        """Mesma ideia de `_load_qwen2_metadata`, mas para o Granite 4.1:
        lê hiperparâmetros reais do namespace 'granite.*' do GGUF, incluindo
        os 4 multiplicadores de escala (embedding_scale/attention_scale/
        residual_scale/logit_scale) que o Qwen2.5 não tem -- ausentes aqui
        eles ficam com o valor neutro (1.0, ou None para deixar o cálculo
        padrão de 1/sqrt(head_dim) assumir, no caso do attention_scale),
        que é como o resto do pipeline compartilhado (kernel_arg_builder,
        fallback_executor, etc.) já trata a ausência dessas chaves para o
        Qwen. Valores confirmados contra os bytes reais do GGUF, não
        adivinhados: attention.scale=0.015625, embedding_scale=12.0,
        residual_scale=0.22, logit_scale=10.0."""
        from ..compiler.gguf_metadata import read_gguf_metadata
        raw = read_gguf_metadata(self._path, wanted_keys={
            "granite.embedding_length", "granite.block_count", "granite.context_length",
            "granite.attention.head_count", "granite.attention.head_count_kv",
            "granite.rope.dimension_count", "granite.feed_forward_length",
            "granite.rope.freq_base", "granite.attention.layer_norm_rms_epsilon",
            "granite.attention.scale", "granite.embedding_scale",
            "granite.residual_scale", "granite.logit_scale",
        })

        embedding_length = raw.get("granite.embedding_length", sanitizer.header.embedding_length)
        head_count = raw.get("granite.attention.head_count", 40)
        head_dim = raw.get("granite.rope.dimension_count", embedding_length // head_count)

        metadata = {
            "embedding_length": embedding_length,
            "block_count": raw.get("granite.block_count", sanitizer.header.block_count),
            "context_length": raw.get("granite.context_length", sanitizer.header.context_length),
            "attention.head_count": head_count,
            "attention.head_count_kv": raw.get("granite.attention.head_count_kv", 8),
            "attention.key_length": head_dim,
            "feed_forward_length": raw.get("granite.feed_forward_length", 8192),
            "rope.freq_base": raw.get("granite.rope.freq_base", 1.0e7),
            "attention.layer_norm_rms_epsilon": raw.get("granite.attention.layer_norm_rms_epsilon", 1e-5),
            "attention_scale": raw.get("granite.attention.scale"),
            "embedding_scale": raw.get("granite.embedding_scale", 1.0),
            "residual_scale": raw.get("granite.residual_scale", 1.0),
            "logit_scale": raw.get("granite.logit_scale", 1.0),
            # 1 = NORM/intercalado (llama-model.cpp::llama_model_rope_type ->
            # LLAMA_ROPE_TYPE_NORM para LLM_ARCH_GRANITE) -- NÃO é o mesmo
            # NEOX/split-half do Qwen2.5 (que fica com o default 0). Não vem
            # do GGUF: é uma propriedade fixa da arquitetura, hardcoded pelo
            # próprio llama.cpp por arch, não por chave de metadado.
            "rope_type": 1,
        }
        logger.info(
            f"Hiperparâmetros GGUF (Granite): hidden={embedding_length}, heads={head_count}, "
            f"kv_heads={metadata['attention.head_count_kv']}, head_dim={head_dim}, "
            f"ffn={metadata['feed_forward_length']}, rope_theta={metadata['rope.freq_base']}, "
            f"eps={metadata['attention.layer_norm_rms_epsilon']:.2e}, "
            f"attention_scale={metadata['attention_scale']}, embedding_scale={metadata['embedding_scale']}, "
            f"residual_scale={metadata['residual_scale']}, logit_scale={metadata['logit_scale']}"
        )
        return metadata

    def _load_qwen3_5_metadata(self, sanitizer) -> dict:
        """Mesma ideia de `_load_qwen2_metadata`/`_load_granite_metadata`,
        pro Qwen 3.5 2B. Duas chaves NÃO vêm do GGUF (mesma situação do
        `rope_type=1` do Granite -- são propriedades fixas da arquitetura,
        confirmadas em config.json/modeling_qwen3_5.py reais, não em
        metadata do GGUF):
        - `rope_type=2` (NEOX parcial) e `rotary_dim=64`
          (partial_rotary_factor=0.25 * head_dim=256), só usados nas 6
          camadas `full_attention`.
        - As dimensões do Gated DeltaNet (`linear_attn.*`) também são fixas
          da arquitetura, não do GGUF -- vêm de `qwen3_5_mapper.py`."""
        from ..compiler.gguf_metadata import read_gguf_metadata
        from ..compiler.qwen3_5_mapper import (
            QWEN35_DEFAULT_HEAD_COUNT, QWEN35_DEFAULT_HEAD_COUNT_KV,
            QWEN35_DEFAULT_HEAD_DIM, QWEN35_DEFAULT_ROTARY_DIM, QWEN35_DEFAULT_FFN,
            QWEN35_DEFAULT_ROPE_THETA, QWEN35_LINEAR_NUM_HEADS,
            QWEN35_LINEAR_HEAD_K_DIM, QWEN35_LINEAR_HEAD_V_DIM,
            QWEN35_LINEAR_KEY_DIM, QWEN35_LINEAR_VALUE_DIM, QWEN35_CONV_DIM,
        )
        raw = read_gguf_metadata(self._path, wanted_keys={
            "qwen35.embedding_length", "qwen35.block_count", "qwen35.context_length",
            "qwen35.attention.head_count", "qwen35.attention.head_count_kv",
            "qwen35.attention.key_length", "qwen35.feed_forward_length",
            "qwen35.rope.freq_base", "qwen35.attention.layer_norm_rms_epsilon",
            "qwen35.rope.dimension_count",
        })

        embedding_length = raw.get("qwen35.embedding_length", sanitizer.header.embedding_length)
        head_count = raw.get("qwen35.attention.head_count", QWEN35_DEFAULT_HEAD_COUNT)
        head_dim = raw.get("qwen35.attention.key_length", QWEN35_DEFAULT_HEAD_DIM)
        rotary_dim = raw.get("qwen35.rope.dimension_count", QWEN35_DEFAULT_ROTARY_DIM)

        metadata = {
            "embedding_length": embedding_length,
            "block_count": raw.get("qwen35.block_count", sanitizer.header.block_count),
            "context_length": raw.get("qwen35.context_length", sanitizer.header.context_length),
            "attention.head_count": head_count,
            "attention.head_count_kv": raw.get("qwen35.attention.head_count_kv", QWEN35_DEFAULT_HEAD_COUNT_KV),
            "attention.key_length": head_dim,
            "feed_forward_length": raw.get("qwen35.feed_forward_length", QWEN35_DEFAULT_FFN),
            "rope.freq_base": raw.get("qwen35.rope.freq_base", QWEN35_DEFAULT_ROPE_THETA),
            "attention.layer_norm_rms_epsilon": raw.get("qwen35.attention.layer_norm_rms_epsilon", 1e-6),
            # RoPE parcial (Fase 1 do plano) -- fixo pela arquitetura, não
            # lido do GGUF (mesma natureza do rope_type=1 do Granite).
            "rope_type": 2,
            "rotary_dim": rotary_dim,
            # Gated DeltaNet (Fase 2/3) -- dimensões fixas da arquitetura.
            "linear_attn.num_heads": QWEN35_LINEAR_NUM_HEADS,
            "linear_attn.head_k_dim": QWEN35_LINEAR_HEAD_K_DIM,
            "linear_attn.head_v_dim": QWEN35_LINEAR_HEAD_V_DIM,
            "linear_attn.key_dim": QWEN35_LINEAR_KEY_DIM,
            "linear_attn.value_dim": QWEN35_LINEAR_VALUE_DIM,
            "linear_attn.conv_dim": QWEN35_CONV_DIM,
        }
        logger.info(
            f"Hiperparâmetros GGUF (Qwen3.5): hidden={embedding_length}, heads={head_count}, "
            f"kv_heads={metadata['attention.head_count_kv']}, head_dim={head_dim}, "
            f"rotary_dim={rotary_dim}, ffn={metadata['feed_forward_length']}, "
            f"rope_theta={metadata['rope.freq_base']}, "
            f"eps={metadata['attention.layer_norm_rms_epsilon']:.2e}"
        )
        return metadata

    def _load_llama_metadata(self, sanitizer) -> dict:
        """Mesma ideia de `_load_qwen2_metadata`: lê os hiperparâmetros reais
        do namespace 'llama.*' do GGUF em vez de assumir defaults do Qwen.
        Confirmados contra Model/Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf via
        gguf.GGUFReader real: hidden=4096, heads=32, kv_heads=8, head_dim=128
        (lido de rope.dimension_count -- Llama, ao contrário do Qwen2.5,
        armazena isso separado em vez de hidden/n_heads), ffn=14336,
        rope_theta=500000.0, eps=1e-5.

        `rope_type=1` (NORM/intercalado), IGUAL ao Granite e DIFERENTE do
        Qwen2.5: llama.cpp usa LLAMA_ROPE_TYPE_NORM para LLM_ARCH_LLAMA (o
        mesmo case do Granite em llama-model.cpp::llama_model_rope_type),
        não LLAMA_ROPE_TYPE_NEOX. O convert_hf_to_gguf.py permuta as linhas
        de attn_q/attn_k do Llama justamente para casar com essa rotação
        intercalada de pares adjacentes -- aplicar o split-half (rope_type=0,
        do Qwen) sobre pesos permutados para intercalado embaralha a
        informação posicional e produz geração incoerente/em loop (bug real
        encontrado nesta sessão: o default 0 herdado por engano do caminho
        do Qwen era a causa; Granite, que já setava rope_type=1, sempre
        funcionou). NÃO vem do GGUF -- é propriedade fixa da arquitetura."""
        from ..compiler.gguf_metadata import read_gguf_metadata
        raw = read_gguf_metadata(self._path, wanted_keys={
            "llama.embedding_length", "llama.block_count", "llama.context_length",
            "llama.attention.head_count", "llama.attention.head_count_kv",
            "llama.rope.dimension_count", "llama.feed_forward_length",
            "llama.rope.freq_base", "llama.attention.layer_norm_rms_epsilon",
        })

        embedding_length = raw.get("llama.embedding_length", sanitizer.header.embedding_length)
        head_count = raw.get("llama.attention.head_count", 32)
        head_dim = raw.get("llama.rope.dimension_count", embedding_length // head_count)

        metadata = {
            "embedding_length": embedding_length,
            "block_count": raw.get("llama.block_count", sanitizer.header.block_count),
            "context_length": raw.get("llama.context_length", sanitizer.header.context_length),
            "attention.head_count": head_count,
            "attention.head_count_kv": raw.get("llama.attention.head_count_kv", 8),
            "attention.key_length": head_dim,
            "feed_forward_length": raw.get("llama.feed_forward_length", 14336),
            "rope.freq_base": raw.get("llama.rope.freq_base", 500000.0),
            "attention.layer_norm_rms_epsilon": raw.get("llama.attention.layer_norm_rms_epsilon", 1e-5),
            # NORM/intercalado (ver docstring) -- NÃO o default 0 do Qwen.
            "rope_type": 1,
        }
        logger.info(
            f"Hiperparâmetros GGUF (Llama 3.1): hidden={embedding_length}, heads={head_count}, "
            f"kv_heads={metadata['attention.head_count_kv']}, head_dim={head_dim}, "
            f"ffn={metadata['feed_forward_length']}, rope_theta={metadata['rope.freq_base']}, "
            f"eps={metadata['attention.layer_norm_rms_epsilon']:.2e}"
        )
        return metadata

    def _load(self):
        sanitizer = GGUFSanitizer(Path(self._path))
        sanitizer.validate()

        # Arquitetura já foi validada pelo sanitizer (SUPPORTED_ARCHITECTURES)
        # -- aqui só escolhemos QUAL leitor de metadados/mapper/tokenizer usar,
        # nunca um terceiro caminho "desconhecido" (isso já teria sido
        # rejeitado por sanitizer.validate() antes de chegarmos aqui).
        architecture = sanitizer.header.architecture
        if architecture == "granite":
            metadata = self._load_granite_metadata(sanitizer)
        elif architecture == "qwen35":
            metadata = self._load_qwen3_5_metadata(sanitizer)
        elif architecture == "llama":
            metadata = self._load_llama_metadata(sanitizer)
        else:
            metadata = self._load_qwen2_metadata(sanitizer)
        self.metadata = metadata
        self._architecture = architecture

        if self._hip is None:
            self._hip = HIPRuntime()
            self._hip.initialize()
        
        if self._allocator is None:
            vram_total = self._hip.get_device_properties()['total_global_mem']
            
            self.parser = GGUFParser(Path(self._path))
            self.parser.parse_tensors(sanitizer.header)

            # Etapa C: registra os pesos que ficam CRUS em Q4_K/Q6_K/Q8_0 a
            # partir da MESMA função usada pelo loader/mapper, para o executor
            # rotear esses nós ao gemv_* correto. Fonte única de verdade.
            from vte.compiler.qwen_mapper import is_raw_q4k_weight, is_raw_q6k_weight, is_raw_q5_0_weight
            from vte.compiler.granite_mapper import is_raw_q8_0_weight
            from vte.core.fallback_executor import register_raw_q4k_weights, register_raw_q6k_weights, register_raw_q8_0_weights, register_raw_q5_0_weights
            raw_q4k = {n for n, t in self.parser.tensors.items() if is_raw_q4k_weight(n, t)}
            raw_q6k = {n for n, t in self.parser.tensors.items() if is_raw_q6k_weight(n, t)}
            raw_q8_0 = {n for n, t in self.parser.tensors.items() if is_raw_q8_0_weight(n, t)}
            raw_q5_0 = {n for n, t in self.parser.tensors.items() if is_raw_q5_0_weight(n, t)}
            if architecture == "qwen35":
                # qwen_mapper.is_raw_q6k_weight (linha acima) é restrito por
                # NOME (ffn_down/token_embd) -- pensado pro GGUF misto
                # Q4_K/Q6_K do Qwen2.5. O GGUF do Qwen3.5 não mistura: TODA
                # matriz grande é Q6_K (attn_qkv, attn_gate, ffn_*,
                # token_embd), confirmado via gguf.GGUFReader real. Sem esta
                # união, attn_qkv/attn_gate/ffn_gate/ffn_up ficariam alocados
                # CRUS (qwen3_5_mapper.py) mas roteados como se fossem FP16
                # pelo executor -- corrupção silenciosa de dados. Aditivo:
                # não muda nada pro Qwen2.5/Granite (só roda quando
                # architecture=="qwen35").
                from vte.compiler.qwen3_5_mapper import is_raw_q6k_weight as qwen35_is_raw_q6k_weight
                raw_q6k |= {n for n, t in self.parser.tensors.items() if qwen35_is_raw_q6k_weight(n, t)}
            # Guardados na instância (não só nos sets globais) porque
            # RAW_Q4K_WEIGHTS/RAW_Q6K_WEIGHTS/RAW_Q8_0_WEIGHTS/RAW_Q5_0_WEIGHTS
            # em fallback_executor.py são estado GLOBAL de módulo, não por
            # modelo -- carregar um SEGUNDO VTEModel no mesmo processo
            # sobrescreve esses sets com os do modelo mais recentemente
            # carregado, fazendo o guard de fusão QKV de um modelo já
            # carregado consultar o registro ERRADO (bug real encontrado e
            # documentado em docs/BUGS.md: um peso cru sendo lido como FP16
            # puro pelo kernel fundido, colapso para "!!!!!!!!"). Se dois
            # modelos precisarem coexistir no mesmo processo de novo no
            # futuro, chame `_activate_raw_registries()` antes de decodificar
            # em cada um.
            self._raw_q4k = raw_q4k
            self._raw_q6k = raw_q6k
            self._raw_q8_0 = raw_q8_0
            self._raw_q5_0 = raw_q5_0
            register_raw_q4k_weights(raw_q4k)
            register_raw_q6k_weights(raw_q6k)
            register_raw_q8_0_weights(raw_q8_0)
            register_raw_q5_0_weights(raw_q5_0)
            logger.info(f"Pesos crus in-kernel: Q4_K={len(raw_q4k)} (gemv_q4k), Q6_K={len(raw_q6k)} (gemv_q6k), Q8_0={len(raw_q8_0)} (gemv_q8_0), Q5_0={len(raw_q5_0)} (gemv_q5_0)")

            if architecture == "granite":
                from vte.compiler.granite_mapper import GraniteTensorMapper
                mapper = GraniteTensorMapper(self.parser, metadata)
            elif architecture == "qwen35":
                from vte.compiler.qwen3_5_mapper import Qwen3_5TensorMapper
                mapper = Qwen3_5TensorMapper(self.parser, metadata)
            elif architecture == "llama":
                # Estrutura de camada idêntica ao Qwen2.5 (RMSNorm->QKV->RoPE->
                # GQA->O-proj->SwiGLU) -- reaproveita QwenTensorMapper sem
                # subclasse, só troca o rótulo usado na mensagem de OOM.
                mapper = QwenTensorMapper(self.parser, metadata, model_label=Path(self._path).stem)
            else:
                mapper = QwenTensorMapper(self.parser, metadata)
            self._mapper = mapper  # Fase II (prep): reaproveitado por generate_batch()

            # Dimensiona o pool para o MAIOR batch_size pretendido (padrão 1 —
            # sem custo extra para quem só usa generate() de sequência única).
            # Pesos não escalam com batch; só o KV cache/arena do batch máximo
            # entram no cálculo de margem.
            reqs = mapper.calculate_memory_requirements(self._context_length, self._max_batch_size)
            requested_pool_size = reqs['with_margin']

            # Batched prefill (VTE_BATCHED_PREFILL=1) allocates a SECOND,
            # chunk-sized activation-buffer set on top of everything above
            # (see _build_chunk_tensor_mapping) -- but SlabAllocator is a
            # bump allocator with a FIXED pool sized here, at load time,
            # long before _ensure_batched_prefill_executor ever runs. Real
            # GPU VRAM having room free (checked separately in
            # _ensure_batched_prefill_executor) doesn't help if THIS pool
            # itself has no headroom left -- confirmed directly: without
            # this, every batched-prefill attempt failed with "OOM no
            # Slab: Não há N bytes contíguos" even on a 49GB card with
            # >40GB genuinely free, because the pool itself was sized to
            # fit exactly weights+KV+seq_len=1 buffers, nothing more.
            # reqs['arena'] is the seq_len=1 activation cost (one unit of
            # it is already inside requested_pool_size above); the chunk
            # buffers need chunk_size-1 MORE of that same unit, additive.
            self._batched_prefill_pool_reserved = False
            if os.environ.get("VTE_BATCHED_PREFILL", "1") == "1":
                chunk_size = int(os.environ.get("VTE_BATCHED_PREFILL_CHUNK_SIZE", "64"))
                extra_headroom = reqs['arena'] * max(chunk_size - 1, 0)
                # Real-VRAM check BEFORE committing this reservation, same
                # conservative 50%-of-free threshold _ensure_batched_prefill_executor
                # already uses for its own (later, runtime) decision -- keeping
                # both checks identical means they can never disagree. This used
                # to be an unconditional addition: confirmed directly on the RX
                # 7600 (8GB) that Llama 3.1 8B/Qwen2.5 7B's chunk=64 buffer
                # (+4.23GB/+5.59GB) blows past what's actually free on this
                # card, and SlabAllocator.initialize() hard-crashed on it
                # instead of falling back to sequential prefill like the design
                # always intended (see docs/LIMITATIONS.md#batching-and-prefill).
                free_bytes, total_bytes = self._hip.get_real_mem_info()
                if extra_headroom > free_bytes * 0.5:
                    logger.warning(
                        "VTE_BATCHED_PREFILL=1: chunk_size=%d precisaria de +%.0fMB extras, "
                        "só %.0fMB livres (VRAM total %.0fMB) -- prefill em lote fica "
                        "indisponível para este carregamento, caminho sequencial "
                        "(sempre correto) será usado.",
                        chunk_size, extra_headroom / 1024**2, free_bytes / 1024**2, total_bytes / 1024**2,
                    )
                else:
                    requested_pool_size += extra_headroom
                    self._batched_prefill_pool_reserved = True
                    logger.info(
                        "VTE_BATCHED_PREFILL=1: reservando +%.0fMB no pool pra buffers de chunk_size=%d.",
                        extra_headroom / 1024**2, chunk_size,
                    )

            self._allocator = SlabAllocator(self._hip, vram_total, requested_pool_size=requested_pool_size)
            self._allocator.initialize()
            
            self.profiler = VRAMProfiler(self._allocator)
            
            self.tensor_mapping = mapper.map_and_allocate_tensors(self._allocator, self._hip, profiler=self.profiler, context_length=self._context_length)

            weight_loader = GGUFWeightLoader(
                self._path, self.parser, self.tensor_mapping,
                raw_q4k=raw_q4k, raw_q6k=raw_q6k, raw_q8_0=raw_q8_0, raw_q5_0=raw_q5_0,
            )
            loaded, total_bytes = weight_loader.load_all(self._hip)
            logger.info(f"Pesos injetados na VRAM: {loaded} tensores ({total_bytes / (1024*1024):.1f} MB)")

            logger.info("Construindo grafo de operações...")
            if architecture == "qwen35":
                # Grafo próprio (não QwenComputeGraphBuilder): as camadas do
                # Qwen3.5 NÃO têm todas a mesma sequência de nós (6
                # full_attention vs 18 linear_attention/Gated DeltaNet) --
                # diferente de Qwen2.5/Granite, que são estruturalmente
                # idênticos camada a camada (só os números mudam).
                from vte.compiler.qwen3_5_compute import Qwen3_5ComputeGraphBuilder
                compute_builder = Qwen3_5ComputeGraphBuilder(metadata)
            else:
                from vte.compiler.qwen_compute import QwenComputeGraphBuilder
                compute_builder = QwenComputeGraphBuilder(metadata)
            self.compute_graph = compute_builder.build_compute_graph()
            self._graph = self.compute_graph  # Alias para compatibilidade
            
            if self._enable_fusion:
                logger.info("Aplicando fusão de kernels...")
                from vte.compiler.fusion_analyzer import FusionAnalyzer
                from vte.compiler.fusion_applier import FusionApplier
                
                analyzer = FusionAnalyzer()
                candidates = analyzer.analyze(self.compute_graph)
                
                if candidates:
                    applier = FusionApplier()
                    self.compute_graph = applier.apply(self.compute_graph, candidates)
                    self._graph = self.compute_graph
                    logger.info(f"Fusão aplicada: {len(candidates)} mega-kernels criados")
                else:
                    logger.info("Nenhuma fusão possível encontrada")

            # Epilogue Fusion do residual: detecta GEMV -> Add(residual) e funde
            # o Add no epílogo do GEMV (mata ~56 launches/tok). Deve rodar após
            # o grafo final estar montado.
            from vte.core.fallback_executor import build_residual_fusion, RESIDUAL_FUSION
            build_residual_fusion(list(self._graph.nodes.values()))
            logger.info(f"Fusão de residual (epilogue): {len(RESIDUAL_FUSION)} GEMVs fundidos")

        if architecture == "granite":
            from vte.compiler.tokenizer import GraniteTokenizer
            self.tokenizer = GraniteTokenizer(gguf_path=self._path)
        elif architecture == "qwen35":
            from vte.compiler.tokenizer import Qwen3_5Tokenizer
            self.tokenizer = Qwen3_5Tokenizer(gguf_path=self._path)
        elif architecture == "llama":
            from vte.compiler.tokenizer import LlamaTokenizer
            self.tokenizer = LlamaTokenizer(gguf_path=self._path)
        else:
            self.tokenizer = QwenTokenizer(gguf_path=self._path)
        self.sampler = Sampler()

        # Recupera o bloco de arena pré-alocado pelo mapper (Evita sobreposicao)
        arena_block = next((b for b in self._allocator.blocks if b.tag == "ACTIVATION_ARENA"), None)
        if not arena_block:
            raise RuntimeError("Bloco ACTIVATION_ARENA não encontrado no SlabAllocator após mapeamento.")
            
        # 2MB reservado para input_embeddings e input_ids no início da arena
        self.arena = ActivationArena(arena_block, start_offset=2097152)
        
        # Aloca buffers de ativação persistentes para o HIP Graph
        self._allocate_activation_buffers()

        lm_head_capture_info = None
        if self._use_hip_graph:
            # Resolve os dados do LM Head (peso/tied embeddings, buffer de
            # logits, kernel compilado) ANTES de construir o HIPGraphExecutor,
            # para poder gravá-lo DENTRO do mesmo grafo de decode (elimina o
            # lançamento eager separado a cada token, ~3.19ms/tok medidos).
            # Não dá para simplesmente criar o LMHead primeiro: LMHead.
            # compute_logits() reaproveita self.model.executor.codegen, que
            # ainda não existiria — usamos aqui uma instância própria de
            # CodegenEngine (o cache de kernel compilado é em disco, por hash
            # de conteúdo, não fica preso à instância).
            try:
                lm_head_capture_info = self._resolve_lm_head_capture_info()
            except Exception as e:
                logger.warning(f"Não foi possível pré-resolver o LM Head para captura no grafo: {e}. "
                                f"LM Head continuará rodando eager, fora do grafo.")
                lm_head_capture_info = None

        # Opt-in (padrão desligado): redução de logits na GPU pro caminho
        # greedy (temperature<=0). Resolvido ANTES do HIPGraphExecutor pelo
        # MESMO motivo do LM Head acima: o kernel precisa ser gravado DENTRO
        # do grafo (ver HIPGraphExecutor._capture_topk_reduce), então seus
        # ponteiros/kernel_fn (endereços fixos) precisam existir antes da
        # captura. Uma primeira versão rodava isto eager (fora do grafo) e
        # media uma perda líquida de tok/s -- o despacho de um kernel novo
        # custava mais que a economia da leitura reduzida (ver
        # docs/PERFORMANCE.md "Follow-up: GPU duty-cycle investigation").
        # Só faz sentido com o LM Head também resolvido (usa o mesmo
        # logits_buffer/vocab_size dele).
        self._topk_reducer = None
        topk_capture_info = None
        if (self._use_hip_graph and lm_head_capture_info is not None
                and os.environ.get("VTE_TOPK_LOGITS_READBACK", "0") == "1"):
            try:
                from vte.compiler.codegen import CodegenEngine
                from vte.core.topk_logits_reducer import TopKLogitsReducer
                self._topk_reducer = TopKLogitsReducer(self._hip, self._allocator, CodegenEngine())
                topk_capture_info = {
                    'kernel_fn': self._topk_reducer.kernel,
                    'exclude_ids_ptr': self._topk_reducer.exclude_ids_ptr,
                    'exclude_count_ptr': self._topk_reducer.exclude_count_ptr,
                    'values_ptr': self._topk_reducer.values_ptr,
                    'indices_ptr': self._topk_reducer.indices_ptr,
                    'gathered_ptr': self._topk_reducer.gathered_ptr,
                }
                logger.info("TopKLogitsReducer ativado (VTE_TOPK_LOGITS_READBACK=1): redução de logits "
                             "capturada dentro do HIP Graph de decode para o caminho greedy.")
            except Exception as e:
                logger.warning(f"Falha ao inicializar TopKLogitsReducer (VTE_TOPK_LOGITS_READBACK=1): {e}. "
                                f"Caminho de leitura de logits completo será usado normalmente.")
                self._topk_reducer = None
                topk_capture_info = None

        # Análogo ao bloco acima, pro caminho ESTOCÁSTICO (temperature>0 --
        # o padrão real do projeto, ao contrário do greedy acima). Ver
        # topk_reduce_stochastic.hip.template e Sampler.sample_from_gpu_
        # candidates: medido (2026-07) que 92.6% do custo de Sampler.
        # sample() é um único np.argpartition sobre o vocabulário inteiro,
        # não o RNG/top-p/repetition penalty -- eliminar esse argpartition
        # (e a leitura D2H de todo o vocabulário que o alimenta) mediu
        # +6.96% de tok/s real (Llama 3.1 8B, W7900, warmup separado,
        # mediana de 3, 74.36 -> 79.54 tok/s). Default ON desde 2026-07
        # (opt out via VTE_STOCHASTIC_TOPK_READBACK=0): validado
        # estatisticamente (KL-divergence 0.0001 contra o caminho antigo
        # numa distribuição real de alta entropia) e greedy confirmado
        # byte-idêntico com a flag ligada ou desligada -- ver
        # docs/LIMITATIONS.md ("Kernel efficiency and rejected
        # optimizations") pro bug de clustering encontrado e corrigido
        # antes disto ser ligado por padrão.
        self._stochastic_topk_reducer = None
        stochastic_topk_capture_info = None
        if (self._use_hip_graph and lm_head_capture_info is not None
                and os.environ.get("VTE_STOCHASTIC_TOPK_READBACK", "1") == "1"):
            try:
                from vte.compiler.codegen import CodegenEngine
                from vte.core.topk_logits_reducer import StochasticTopKReducer
                self._stochastic_topk_reducer = StochasticTopKReducer(self._hip, self._allocator, CodegenEngine())
                stochastic_topk_capture_info = {
                    'kernel_fn': self._stochastic_topk_reducer.kernel,
                    'exclude_ids_ptr': self._stochastic_topk_reducer.exclude_ids_ptr,
                    'exclude_count_ptr': self._stochastic_topk_reducer.exclude_count_ptr,
                    'values_ptr': self._stochastic_topk_reducer.values_ptr,
                    'indices_ptr': self._stochastic_topk_reducer.indices_ptr,
                    'gathered_ptr': self._stochastic_topk_reducer.gathered_ptr,
                }
                logger.info("StochasticTopKReducer ativado (VTE_STOCHASTIC_TOPK_READBACK=1): redução de logits "
                             "capturada dentro do HIP Graph de decode para o caminho estocástico.")
            except Exception as e:
                logger.warning(f"Falha ao inicializar StochasticTopKReducer (VTE_STOCHASTIC_TOPK_READBACK=1): {e}. "
                                f"Caminho de leitura de logits completo será usado normalmente.")
                self._stochastic_topk_reducer = None
                stochastic_topk_capture_info = None

        if self._use_hip_graph:
            try:
                self.executor = HIPGraphExecutor(self._hip, self._allocator, self._graph, self.tensor_mapping,
                                                  metadata=self.metadata, lm_head_info=lm_head_capture_info,
                                                  context_length=self._context_length, topk_info=topk_capture_info,
                                                  stochastic_topk_info=stochastic_topk_capture_info)
                self.executor.build_decode_graph()
                logger.info(f"HIP Graph executor inicializado com sucesso (Nós: {len(self._graph.nodes)})")
            except Exception as e:
                logger.warning(f"HIP Graph falhou: {e}. Fazendo fallback para executor legado.")
                self.executor = FallbackExecutor(self._hip, self._allocator, self.arena, self._graph, self.tensor_mapping, metadata=self.metadata)
                self._use_hip_graph = False
                lm_head_capture_info = None
                # O grafo não foi capturado (nem o LM Head nem o topk foram
                # gravados nele) -- a instância existe mas não está ligada a
                # nada real, usá-la seria incorreto.
                self._topk_reducer = None
                self._stochastic_topk_reducer = None
        else:
            logger.info("HIP Graphs desabilitado via flag. Usando FallbackExecutor.")
            self.executor = FallbackExecutor(self._hip, self._allocator, self.arena, self._graph, self.tensor_mapping, metadata=self.metadata)

        if lm_head_capture_info is not None:
            # HIP Graph capturou o LM Head: o LMHead reaproveita o MESMO
            # buffer/kernel já resolvidos, em vez de alocar/compilar de novo
            # (um segundo buffer não seria o que o grafo escreve).
            self.lm_head = LMHead(self, self._hip, self._allocator, tokenizer=self.tokenizer,
                                   logits_buffer=lm_head_capture_info['logits_buffer_ptr'],
                                   kernel_info={'kernel': lm_head_capture_info['kernel_fn'],
                                                'template': lm_head_capture_info['template']})
        else:
            self.lm_head = LMHead(self, self._hip, self._allocator, tokenizer=self.tokenizer)

        from vte.core.gpu_keepalive import GPUKeepAlive
        self._keepalive = GPUKeepAlive(self._hip, self._allocator)
        # Válvula de escape: o pulso fixo de 2ms foi medido como obsoleto (e
        # em 1.0ms, ativamente prejudicial -- picos de até 35ms, pior caso de
        # todos os testados) depois que o Split-KV encurtou o tick de decode
        # para ~9-10ms -- rápido o bastante para o DPM do WDDM nunca ter
        # tempo de derrubar o clock entre tokens. Ver README ("Bugs found
        # during development") para a medição completa (rajada contínua de
        # 200 tokens + gaps reais de 3s entre turnos, sem TDR em nenhum
        # caso). Mantido configurável via env var para reverter sem deploy
        # de código, caso um driver futuro ou hardware diferente reintroduza
        # o cenário que o pulso existia para prevenir.
        self._keepalive_pulse_s = float(os.environ.get("VTE_KEEPALIVE_PULSE_MS", "0.0")) / 1000.0

        # Registra este modelo no monitor de pressão de VRAM (singleton de
        # processo) -- se a VRAM REAL da GPU (hipMemGetInfo, inclui qualquer
        # outro programa usando a GPU) passar de 95% de forma sustentada, o
        # guard descarrega automaticamente o modelo menos usado no momento
        # (ver vte/bridge/vram_pressure_guard.py) em vez de deixar a próxima
        # alocação falhar sem aviso.
        from vte.bridge.vram_pressure_guard import get_vram_pressure_guard
        get_vram_pressure_guard().register_model(self)

        self._is_loaded = True
    
    def _allocate_activation_buffers(self):
        """
        Aloca buffers persistentes na VRAM para as saídas intermediárias de cada nó.
        Necessário para o HIP Graph (grafo estático = endereços fixos).
        """
        from vte.compiler.ir import NodeType
        
        if not hasattr(self, 'compute_graph') or self.compute_graph is None:
            return
        
        allocated = 0
        for node in self.compute_graph.topological_sort():
            if node.op_type in [NodeType.INPUT, NodeType.OUTPUT]:
                continue
            
            out_name = node.output_tensor
            if not out_name or out_name in self.tensor_mapping:
                continue

            # Aloca PERSISTENTEMENTE a saída de todo nó de computação (não só as
            # saídas finais de camada). O HIP Graph exige endereços fixos para
            # TODOS os tensores intermediários referenciados durante a captura,
            # já que não há alocação dinâmica possível dentro de um grafo estático.
            #
            # Dimensionamos a dimensão dinâmica (-1, seq_len) como 1: esses buffers
            # persistentes são compartilhados por TODAS as capturas de grafo, e o
            # caso dominante (decode autoregressivo, um token por passo) sempre usa
            # seq_len=1. Dimensionar para context_length cheio custaria ~4.5GB só
            # nesses buffers (28 camadas x tensores intermediários), inviável na
            # VRAM disponível. Limitação conhecida: um prefill multi-token via
            # HIPGraphExecutor pode gravar além do buffer se seq_len > 1 nesses
            # tensores intermediários (não nas saídas finais persistentes, que já
            # existiam antes e continuam corretas) — acompanhar em trabalho futuro
            # de particionamento de buffers por "classe de shape" do grafo.
            size = 1
            for dim in node.shape:
                if dim > 0:
                    size *= dim
                elif dim == -1:
                    size *= 1
            size = size * 2  # fp16
            size = max(size, 512)
            
            block = self._allocator.allocate(size, f"act_{out_name}", MemoryRegion.ACTIVATIONS)
            self.tensor_mapping[out_name] = block.ptr
            allocated += 1

        logger.info(f"Buffers persistentes alocados: {allocated} tensores")

    def _estimate_chunk_activation_bytes(self, chunk_size: int) -> int:
        """Same sizing walk as _allocate_activation_buffers, but only
        totals the byte count -- doesn't allocate anything. Used to check
        against free VRAM BEFORE committing to a chunk size, so a tight
        card (e.g. RX 7600, 8GB) fails safe (falls back to the existing
        per-token path) instead of racing an allocator exception."""
        from vte.compiler.ir import NodeType

        if not hasattr(self, 'compute_graph') or self.compute_graph is None:
            return 0
        total = 0
        for node in self.compute_graph.topological_sort():
            if node.op_type in [NodeType.INPUT, NodeType.OUTPUT]:
                continue
            if not node.output_tensor:
                continue
            size = 1
            for dim in node.shape:
                if dim > 0:
                    size *= dim
                elif dim == -1:
                    size *= chunk_size
            size = size * 2  # fp16
            total += max(size, 512)
        return total

    def _build_chunk_tensor_mapping(self, chunk_size: int) -> dict:
        """Activation-buffer set sized for `chunk_size` rows, layered on
        top of a COPY of self.tensor_mapping (never mutates the original)
        -- weights, KV cache pointers (`blk.{l}.kv_cache.k`/`.v`), RoPE
        cache, and anything else not produced by a compute-graph node stay
        exactly as they are, genuinely SHARED with decode's own executor
        (the whole point: batched prefill must write into the SAME KV
        cache decode reads from afterward, not a second disconnected one).
        Only the per-node intermediate/activation OUTPUTS get fresh,
        chunk-sized allocations, overriding the inherited seq_len=1
        entries -- those are the ones HIPGraphExecutor would otherwise
        overrun writing chunk_size rows into a 1-row buffer (silent VRAM
        corruption, not just a perf issue -- see the known-limitation
        comment on _allocate_activation_buffers this generalizes from).
        Tagged act_prefill_* (distinct from _allocate_activation_buffers'
        act_* tags) so the new allocations are identifiable in VRAM
        profiling logs."""
        from vte.compiler.ir import NodeType

        mapping: dict = dict(self.tensor_mapping)
        if not hasattr(self, 'compute_graph') or self.compute_graph is None:
            return mapping
        # NOTE: deliberately does NOT skip when out_name is already in
        # `mapping` -- it always IS, inherited from the self.tensor_mapping
        # copy above (every node's seq_len=1 buffer was already allocated
        # by _allocate_activation_buffers at load time). This loop's whole
        # job is to OVERRIDE those specific entries with fresh chunk-sized
        # ones; only KV cache/weights/RoPE-cache entries (never produced by
        # a compute-graph node, so never visited here) stay as inherited.
        seen: set = set()
        for node in self.compute_graph.topological_sort():
            if node.op_type in [NodeType.INPUT, NodeType.OUTPUT]:
                continue
            out_name = node.output_tensor
            if not out_name or out_name in seen:
                continue
            seen.add(out_name)
            size = 1
            for dim in node.shape:
                if dim > 0:
                    size *= dim
                elif dim == -1:
                    size *= chunk_size
            size = size * 2  # fp16
            size = max(size, 512)
            block = self._allocator.allocate(size, f"act_prefill_{out_name}", MemoryRegion.ACTIVATIONS)
            mapping[out_name] = block.ptr
        return mapping

    def _ensure_batched_prefill_executor(self, chunk_size: int):
        """Lazily builds (once) a second HIPGraphExecutor dedicated to
        batched/chunked prefill, with its own chunk-sized tensor_mapping
        (see _build_chunk_tensor_mapping). Entirely additive: the existing
        self.executor/self.tensor_mapping/decode graph are never touched,
        so this can only ever add a new capability, never regress decode.

        Returns None (and logs why) if batched prefill isn't applicable or
        safe right now -- caller falls back to the existing per-token
        prefill loop in that case, same as if this method didn't exist:
          - VTE_BATCHED_PREFILL explicitly set to something other than "1"
            (default ON since 2026-07-22 -- see the module-level comment
            near _BATCHED_PREFILL_CHUNK_SIZE for the missing-bias
            correctness bug found and fixed the same day, and
            docs/LIMITATIONS.md#batching-and-prefill for the full
            investigation. The 1.96x TTFT measurement and byte-identical-
            output claim below were originally validated on the
            W7900/Llama-3.1-8B combination and, after the bias fix,
            re-verified byte-identical on Qwen2.5 1.5B/RX 7600 as well
            -- opt OUT via VTE_BATCHED_PREFILL=0 if ever needed, same
            escape-hatch pattern as VTE_DISABLE_ATTN_SPLITKV).
          - Not running the HIP Graph executor (FallbackExecutor has no
            graph-capture concept to batch).
          - Gated DeltaNet (qwen35): its recurrent state can't resume
            mid-sequence the way transformer KV cache can (see the
            skip_prefix docstring in generate()) -- no batched-prefill
            story for it yet, always falls through to the sequential path.
          - Estimated extra VRAM for `chunk_size` doesn't fit comfortably
            under the free budget -- checked explicitly (not just left to
            an allocator exception) specifically so a tight card (RX 7600,
            8GB) degrades to the always-correct sequential path instead of
            a failed allocation banking on being caught cleanly everywhere
            downstream.
        """
        if os.environ.get("VTE_BATCHED_PREFILL", "1") != "1":
            return None
        if not getattr(self, "_batched_prefill_pool_reserved", False):
            # _load() already checked real free VRAM before reserving this
            # feature's extra chunk buffers in the pool and found it didn't
            # fit (logged a warning there) -- the pool itself has no room
            # for these buffers regardless of what's free on the GPU right
            # now, so building the chunk tensor mapping here would just hit
            # "OOM no Slab: Não há N bytes contíguos" instead of failing
            # cleanly. Nothing new to log here, _load() already explained why.
            return None
        if not self._use_hip_graph:
            return None
        if self._architecture == "qwen35":
            logger.info("Prefill em lote desativado para Gated DeltaNet (qwen35) -- caminho sequencial mantido.")
            return None
        if getattr(self, "_batched_prefill_executor", None) is not None:
            if getattr(self, "_batched_prefill_chunk_size", None) == chunk_size:
                return self._batched_prefill_executor
            # Chunk size changed (shouldn't normally happen mid-process) --
            # rebuild rather than silently reuse a mismatched mapping.
            self._batched_prefill_executor = None

        estimated_bytes = self._estimate_chunk_activation_bytes(chunk_size)
        free_bytes, total_bytes = self._hip.get_real_mem_info()
        # Deliberately conservative beyond the allocator's own
        # VRAM_SAFETY_MARGIN check (vte/bridge/memory.py) -- this is an
        # OPTIONAL extra buffer set on top of an already-loaded model, so
        # it should only ever be taken when there's clearly comfortable
        # headroom, not just whatever's technically left.
        if estimated_bytes > free_bytes * 0.5:
            logger.info(
                "Prefill em lote pulado: chunk_size=%d precisaria de ~%.0fMB extras, "
                "só %.0fMB livres (VRAM total %.0fMB) -- mantendo caminho sequencial.",
                chunk_size, estimated_bytes / 1024**2, free_bytes / 1024**2, total_bytes / 1024**2,
            )
            return None

        try:
            chunk_mapping = self._build_chunk_tensor_mapping(chunk_size)
            executor = HIPGraphExecutor(
                self._hip, self._allocator, self.compute_graph, chunk_mapping,
                metadata=self.metadata, lm_head_info=None, context_length=self._context_length,
                topk_info=None,
            )
            executor.build_prefill_graph(chunk_size)
        except Exception as e:
            logger.warning("Prefill em lote falhou ao inicializar (chunk_size=%d): %s -- caminho sequencial mantido.", chunk_size, e)
            return None

        self._batched_prefill_executor = executor
        self._batched_prefill_chunk_size = chunk_size
        logger.info(
            "Prefill em lote ativado: chunk_size=%d (~%.0fMB de buffers extras).",
            chunk_size, estimated_bytes / 1024**2,
        )
        return executor

    def _resolve_lm_head_capture_info(self, batch_size: int = 1, tensor_mapping: dict = None) -> dict:
        """
        Resolve peso (com tied embeddings), aloca o buffer de logits e
        compila o kernel do LM Head — tudo ANTES do HIPGraphExecutor/
        BatchedHIPGraphExecutor existir, para que a captura do grafo de
        decode possa gravar o LM Head como mais um nó (mesmos requisitos de
        endereço fixo dos demais tensores). `batch_size` dimensiona o
        buffer de logits ([batch_size, vocab_size]) e o grid da captura
        (grid.y = batch_size); o peso e o kernel são os mesmos em qualquer
        batch_size, já que gemv_coalesced/gemv_q4k/gemv_q6k já suportam
        batch nativamente via blockIdx.y.

        Réplica deliberada da lógica de resolução em LMHead (nome do peso
        tied, critério gemv_q6k vs gemv_coalesced) — não dá para reaproveitar
        LMHead diretamente aqui porque LMHead.compute_logits() depende de
        self.model.executor.codegen, e o executor ainda não existe neste
        ponto. Usamos uma instância própria de CodegenEngine: o cache de
        kernel compilado é em disco, por hash do template renderizado, então
        não importa qual instância compila — o binário final é o mesmo.
        """
        from vte.compiler.codegen import CodegenEngine
        from vte.compiler.qwen_mapper import is_raw_q6k_weight
        from vte.compiler.granite_mapper import is_raw_q8_0_weight

        tensor_mapping = tensor_mapping if tensor_mapping is not None else self.tensor_mapping
        hidden_size = self.metadata.get('embedding_length', 1536)

        lm_head_name = 'output.weight'
        lm_head_ptr = tensor_mapping.get(lm_head_name)
        if lm_head_ptr is None:
            lm_head_name = 'token_embd.weight'
            lm_head_ptr = tensor_mapping.get(lm_head_name)
        if lm_head_ptr is None:
            raise ValueError("Peso do LM Head não encontrado em tensor_mapping (nem output.weight, nem token_embd.weight).")
        weight_ptr = lm_head_ptr.ptr if hasattr(lm_head_ptr, 'ptr') else lm_head_ptr

        tensor_info = self.parser.tensors.get(lm_head_name, {})
        weight_shape = tensor_info.get('shape')
        if not weight_shape:
            raise ValueError(f"Shape do peso do LM Head não encontrado ({lm_head_name}).")
        vocab_size = weight_shape[0]

        logits_block = self._allocator.allocate(
            size=batch_size * vocab_size * 2,  # FP16, [batch_size, vocab_size] -- tamanho fixo, nunca muda
            tag="logits_output" if batch_size == 1 else "logits_output_batch",
            region=MemoryRegion.SCRATCH
        )

        if is_raw_q6k_weight(lm_head_name, tensor_info):
            template = "gemv_q6k"
        elif is_raw_q8_0_weight(lm_head_name, tensor_info):
            template = "gemv_q8_0"
        else:
            template = "gemv_coalesced"
        codegen = CodegenEngine()
        _, kernel_fn = codegen.load_kernel_safe(
            self._hip, template, self._hip.get_gpu_architecture(), f"{template}_kernel",
            hidden_size=hidden_size,
            tile_size=256
        )

        return {
            'weight_ptr': weight_ptr,
            'logits_buffer_ptr': logits_block.ptr,
            'kernel_fn': kernel_fn,
            'batch_size': batch_size,
            'template': template,
            'vocab_size': vocab_size,
            'hidden_size': hidden_size,
        }

    def _reset_gdn_state_if_needed(self):
        """Zera o estado persistente do Gated DeltaNet (Qwen3.5) + histórico
        do conv1d causal ANTES de cada nova chamada de generate().

        Bug real encontrado nesta sessão: `hipMemset` só era chamado UMA VEZ,
        em `map_and_allocate_tensors()` (carregamento do modelo) -- nunca de
        novo entre chamadas de generate(). Igual o KV cache (que reinicia
        implicitamente em kv_offset=0 a cada generate(), tratando cada
        chamada como uma sequência nova e independente), o estado do Gated
        DeltaNet também precisa reiniciar do zero a cada nova sequência --
        sem isto, uma segunda mensagem/geração na mesma instância do modelo
        carregado herdava o estado (contaminado) da geração ANTERIOR,
        explicando degradação que só aparece em conversas com mais de uma
        mensagem/chamada."""
        if getattr(self, '_architecture', None) != "qwen35":
            return
        from vte.compiler.qwen3_5_mapper import (
            QWEN35_FULL_ATTENTION_LAYERS, QWEN35_DEFAULT_LAYERS,
            QWEN35_LINEAR_NUM_HEADS, QWEN35_LINEAR_HEAD_K_DIM, QWEN35_LINEAR_HEAD_V_DIM,
            QWEN35_CONV_DIM, QWEN35_CONV_KERNEL_SIZE,
        )
        num_layers = self.metadata.get('block_count', QWEN35_DEFAULT_LAYERS)
        linear_attn_layers = sorted(set(range(num_layers)) - QWEN35_FULL_ATTENTION_LAYERS)
        state_size = QWEN35_LINEAR_NUM_HEADS * QWEN35_LINEAR_HEAD_K_DIM * QWEN35_LINEAR_HEAD_V_DIM * 4
        conv_hist_size = QWEN35_CONV_DIM * (QWEN35_CONV_KERNEL_SIZE - 1) * 4
        for l in linear_attn_layers:
            for key, size in ((f'blk.{l}.linear_attn_state', state_size),
                               (f'blk.{l}.conv1d_history', conv_hist_size)):
                ptr = self.tensor_mapping.get(key)
                if ptr is None:
                    continue
                pv = ptr.ptr if hasattr(ptr, 'ptr') else ptr
                self._hip.safe_memset(ctypes.c_void_p(pv), size, tag=key)

    def _default_repetition_penalty(self) -> float:
        if getattr(self, '_architecture', None) == "qwen35":
            return 1.3
        return 1.1

    def _default_temperature(self) -> float:
        if getattr(self, '_architecture', None) == "qwen35":
            return 0.0
        return 0.7

    def _activate_raw_registries(self):
        """Restaura os sets globais RAW_Q4K/Q6K/Q8_0/Q5_0_WEIGHTS
        (fallback_executor.py) para refletir ESTE modelo. Esses sets são
        estado de MÓDULO (não por instância) -- se mais de um VTEModel for
        carregado no mesmo processo, o registro do último a carregar
        sobrescreve o dos demais, fazendo o guard de fusão QKV de outros
        modelos já carregados consultar o registro errado (bug real
        encontrado e documentado em docs/BUGS.md). Chame isto antes de
        decodificar sempre que mais de uma instância de VTEModel puder estar
        coexistindo no processo."""
        from vte.core.fallback_executor import register_raw_q4k_weights, register_raw_q6k_weights, register_raw_q8_0_weights, register_raw_q5_0_weights
        register_raw_q4k_weights(self._raw_q4k)
        register_raw_q6k_weights(self._raw_q6k)
        register_raw_q8_0_weights(self._raw_q8_0)
        register_raw_q5_0_weights(self._raw_q5_0)

    def generate(
        self,
        prompt: str,
        max_tokens: int = 100,
        temperature: float = None,
        top_p: float = 0.9,
        top_k: int = 50,
        repetition_penalty: float = None,
        stats: dict = None,
        choice_constraint: Optional[ChoiceConstraint] = None,
    ):
        """Gera texto como um Generator, permitindo interrupção caller-side.

        `choice_constraint` (opcional): um vte.core.constrained_decoding.
        ChoiceConstraint já construído para este mesmo tokenizer -- quando
        passado, mascara os logits em cada passo de decode assim que o
        gatilho da constraint aparece no texto decodificado, restringindo
        a geração a completar exatamente uma das strings permitidas
        (equivalente a outlines.generate.choice(), ver o docstring do
        módulo). Builder do constraint fica por conta do chamador (ex.:
        vte-server, a partir de um campo da requisição) -- este método só
        aplica o mask a cada passo e avança o estado, sem saber nada sobre
        o que as escolhas representam.

        `stats` (opcional): se um dict for passado, ao fim da geração normal
        recebe `completion_tokens` = número de tokens REALMENTE gerados
        (len(input_tokens) - prompt_len, exato -- vem da contabilidade interna,
        não de uma re-tokenização aproximada do texto) e `finish_reason`
        ("stop" se um stop token foi amostrado, "length" se parou por
        context_length/max_tokens -- convenção OpenAI). Também recebe
        `prefill_duration_ttft` (segundos, tokenização+prefill até o primeiro
        logit) e `decoding_speed_tps` (tokens/s do loop de decode, excluindo
        prefill), nomeados como a convenção usage.{prefill_duration_ttft,
        decoding_speed_tps} do FastFlowLM que a telemetria do Lemonade já
        sabe ler. Usado pelo vte-server pra preencher os campos
        `usage`/`finish_reason` da resposta OpenAI. Não é preenchido se a
        geração for cancelada no meio (gen.close()), já que o caller nesse
        caso descarta a resposta."""
        self._lifecycle.ensure_loaded()
        self._lifecycle.touch()

        t_start = time.perf_counter()

        if temperature is None:
            temperature = self._default_temperature()
        if repetition_penalty is None:
            repetition_penalty = self._default_repetition_penalty()

        self._reset_gdn_state_if_needed()

        input_tokens = self.tokenizer.encode(prompt)
        current_seq_len = len(input_tokens)

        # Guarda que faltava: o loop de decode (mais abaixo) já para sozinho
        # em current_seq_len >= self._context_length antes de processar
        # qualquer token GERADO, mas o PREFILL nunca teve a mesma checagem --
        # um prompt cujo tamanho já tokenizado excede o KV cache/RoPE cache
        # alocados (dimensionados para self._context_length em
        # calculate_memory_requirements) escreveria em kv_offset além do
        # buffer, corrompendo a Activation Arena silenciosamente. Falha
        # cedo e com mensagem clara em vez de deixar o kernel escrever fora
        # dos limites.
        if current_seq_len >= self._context_length:
            raise HIPSafetyError(
                f"Prompt tem {current_seq_len} tokens, mas o contexto está "
                f"configurado para {self._context_length}. Reduza o prompt ou "
                f"aumente o context_length antes de gerar."
            )

        # Prefill processa o prompt (posições 0..N-1). Ao final, output_norm.output
        # contém o hidden state da ÚLTIMA posição do prompt — é dele que sai a
        # predição do PRIMEIRO token gerado. Não reprocessamos o último token.
        #
        # No modo HIP Graph, processamos o prompt token a token reutilizando o
        # MESMO grafo de decode (seq_len=1, kv_offset variável) em vez do
        # antigo execute_prefill em lote (grafo seq_len=N): os buffers de
        # ativação persistentes são dimensionados para 1 posição, e um grafo
        # de N posições sofreria o mesmo overflow/corrupção que foi corrigido
        # no FallbackExecutor.prefill(). Como o grafo de decode já é
        # capturado uma única vez e reaproveitado (replay puro), processar o
        # prompt assim continua rápido — sem overhead de lançar 392 kernels
        # em Python por token do prompt.
        # use_topk decidido ANTES do prefill: quando ativo, o kernel de
        # redução já roda dentro de TODO replay do grafo (inclusive
        # prefill, capturado uma vez para toda a vida do modelo -- ver
        # HIPGraphExecutor._capture_topk_reduce), então o buffer de
        # exclusão precisa estar num estado válido (vazio, já que nenhum
        # token foi gerado ainda) antes do PRIMEIRO replay.
        use_topk = self._topk_reducer is not None and temperature <= 0.0
        if use_topk:
            self._topk_reducer.upload_exclude(np.empty(0, dtype=np.int64))
        # Mesma lógica de use_topk acima, pro caminho estocástico
        # (temperature>0) -- mutuamente exclusivo com use_topk por
        # construção (nunca os dois True ao mesmo tempo, já que um exige
        # temperature<=0 e o outro temperature>0).
        use_stochastic_topk = self._stochastic_topk_reducer is not None and temperature > 0.0
        if use_stochastic_topk:
            self._stochastic_topk_reducer.upload_exclude(np.empty(0, dtype=np.int64))

        # Prefix reuse: the KV cache is one persistent VRAM buffer that
        # nothing actually clears between generate() calls -- the loop below
        # just always used to start writing at kv_offset=0, silently
        # re-doing work for whatever leading tokens are IDENTICAL to last
        # call (the system prompt + conversation-so-far, unchanged in every
        # round of an agent turn). Skipping the decode-graph replay for that
        # shared prefix and resuming kv_offset from where it ends reuses
        # those already-correct KV entries as-is, no copy/save/restore
        # needed, since it's the same physical buffer. Split-KV attention
        # takes an explicit kv_offset and only attends up to it, so stale
        # trailing entries beyond the new prompt's own length are never
        # read. Scoped to standard-attention architectures only -- Qwen3.5's
        # Gated DeltaNet has separate recurrent state that _reset_gdn_state_
        # if_needed() unconditionally clears every call specifically because
        # it can't resume mid-sequence like transformer KV cache can, so
        # qwen35 always falls through to a full prefill here (skip_prefix
        # stays 0), same as before this change.
        skip_prefix = 0
        if self._use_hip_graph and getattr(self, "_architecture", None) != "qwen35":
            last_seq = getattr(self, "_last_kv_sequence", None) or []
            # Always leave at least one new position to process: with
            # skip_prefix == len(input_tokens), output_norm.output would
            # still hold the previous call's leftover state instead of a
            # hidden state for THIS prompt's last position.
            max_common = min(len(last_seq), len(input_tokens) - 1)
            while skip_prefix < max_common and last_seq[skip_prefix] == input_tokens[skip_prefix]:
                skip_prefix += 1

        if self._use_hip_graph:
            # VTE_BATCHED_PREFILL, default ON since 2026-07 (opt out via
            # VTE_BATCHED_PREFILL=0): process all but a TAIL of the
            # remaining prompt in fixed-size chunks
            # through a second, chunk-sized HIP Graph (see
            # _ensure_batched_prefill_executor) instead of one seq_len=1
            # decode-graph replay per position -- the real fix for prefill
            # being O(N) sequential graph replays instead of a handful of
            # batched ones. The tail (>=1 token, up to a full chunk) always
            # still runs through the EXACT existing per-token loop below,
            # unchanged -- that's deliberate, not a missed optimization:
            # it's what leaves self.lm_head.logits_buffer correctly
            # populated for the first generated token exactly as before,
            # with zero new code needed for that part. Batched chunks only
            # need to populate the KV cache, never read logits themselves.
            batched_executor = None
            n_remaining = len(input_tokens) - skip_prefix
            chunk_size = _BATCHED_PREFILL_CHUNK_SIZE
            # gqa_attention.hip.template's per-thread `scores[2048]` local
            # array bounds total (cached + new) positions any single
            # batched-prefill chunk can attend over -- checked against the
            # WORST case (the very last position of the whole prompt) up
            # front, not just the first chunk, so a long prompt falls back
            # to the always-correct sequential path instead of risking an
            # overrun partway through.
            if n_remaining > chunk_size and len(input_tokens) <= _BATCHED_PREFILL_MAX_CONTEXT:
                batched_executor = self._ensure_batched_prefill_executor(chunk_size)
            if batched_executor is not None:
                num_full_chunks = n_remaining // chunk_size
                if n_remaining % chunk_size == 0:
                    num_full_chunks -= 1  # keep >=1 token for the decode-graph tail below
                for chunk_idx in range(num_full_chunks):
                    chunk_start = skip_prefix + chunk_idx * chunk_size
                    chunk_tokens = input_tokens[chunk_start:chunk_start + chunk_size]
                    batched_executor.execute_prefill(chunk_tokens, kv_offset=chunk_start)
                skip_prefix += num_full_chunks * chunk_size

            for pos in range(skip_prefix, len(input_tokens)):
                self.executor.execute_decode(input_tokens[pos], kv_offset=pos)
        else:
            self.executor.prefill(input_tokens)

        # Fase 2 (LM Head no HIP Graph): quando o executor capturou o LM Head
        # dentro do próprio grafo de decode, o replay de execute_decode() já
        # escreveu os logits em lm_head.logits_buffer -- chamar
        # compute_logits() de novo aqui recalcularia a mesma GEMV eager,
        # duplicando o trabalho e anulando o ganho (~3.19ms/tok medidos).
        # Nesse caso, _read_logits só lê o que já está pronto na VRAM.
        lm_head_captured_in_graph = (
            self._use_hip_graph and getattr(self.executor, 'lm_head_info', None) is not None
        )

        def _get_logits_ptr():
            if lm_head_captured_in_graph:
                return self.lm_head.logits_buffer
            hidden_ptr = self.tensor_mapping.get('output_norm.output')
            hidden_val = hidden_ptr.ptr if hasattr(hidden_ptr, 'ptr') else hidden_ptr
            return self.lm_head.compute_logits(hidden_val, seq_len=1)

        def _read_logits():
            logits_buffer = bytearray(self.lm_head.vocab_size * 2)
            logits_ptr = _get_logits_ptr()
            # O LM head grava logits em FP16 (mesmo tipo do matmul_kernel).
            self._hip.safe_memcpy_device_to_host(
                logits_buffer, ctypes.c_void_p(logits_ptr), tag="logits_d2h"
            )
            return np.frombuffer(logits_buffer, dtype=np.float16).astype(np.float32)

        # Caminho opcional (VTE_TOPK_LOGITS_READBACK=1, só greedy) que troca
        # a leitura do vocabulário inteiro (151936 fp16, ~304KB, limitada por
        # LATÊNCIA de PCIe/driver, não banda -- ver docs/PERFORMANCE.md,
        # "Follow-up: GPU duty-cycle investigation") por uma redução feita
        # na própria GPU (topk_reduce_greedy_kernel), lendo de volta só um
        # punhado de candidatos. Corretude (não é uma aproximação -- ver
        # Sampler.pick_greedy_from_gpu_candidates e o comentário do kernel):
        # a penalidade de repetição só DIMINUI logits, nunca aumenta, então
        # o vencedor pós-penalidade é sempre um token da janela recente
        # (valor exato via gather) ou o melhor token NÃO-janela de cada
        # grupo de thread (cujo valor não muda com a penalidade).
        ignore_token_set = set(self.tokenizer.special_tokens.values())
        vocab_size = self.lm_head.vocab_size
        prompt_len = len(input_tokens)
        # How many leading positions of input_tokens are actually resident
        # in the KV cache right now -- starts at prompt_len (prefill above
        # always leaves the whole prompt validly written, skipped or not),
        # advances by one per decode iteration ONLY past the point where
        # execute_decode/decode_step actually ran (see the context_length
        # break below: a token can be appended to input_tokens and then the
        # loop exits before writing its KV entry, so len(input_tokens)
        # alone isn't a safe stand-in for this).
        kv_valid_len = prompt_len

        if use_topk:
            # O kernel já rodou como parte do ÚLTIMO replay do prefill (com
            # exclusão vazia, uploadada acima antes do loop de prefill) --
            # só falta ler de volta os candidatos, nenhum lançamento aqui.
            unique_ids, counts = np.empty(0, dtype=np.int64), np.empty(0, dtype=np.float64)
            group_values, group_indices, gathered_values = self._topk_reducer.read_candidates()
        elif use_stochastic_topk:
            unique_ids, counts = np.empty(0, dtype=np.int64), np.empty(0, dtype=np.float64)
            candidate_values, candidate_indices, stoch_gathered_values = self._stochastic_topk_reducer.read_candidates()
        else:
            logits = _read_logits()
        t_prefill_end = time.perf_counter()

        stop_ids = self.tokenizer.stop_token_ids
        # Um token BPE byte-level pode carregar só METADE dos bytes de um
        # caractere multi-byte (emoji, acento) -- decodificar cada token
        # isoladamente cortava essas sequências no meio e produzia "�" (ver
        # vte/core/incremental_decoder.py). O decoder segura bytes
        # incompletos entre chamadas de feed() até a sequência completar.
        utf8_decoder = IncrementalUTF8Decoder()
        # OpenAI's finish_reason: "length" is the default (covers both the
        # context-length break below and natural max_tokens exhaustion, neither
        # of which is a real stop condition), overwritten to "stop" only when
        # a stop token is actually sampled.
        finish_reason = "length"

        constraint_state = choice_constraint.new_state() if choice_constraint is not None else None

        for i in range(max_tokens):
            t_tok_start = time.perf_counter() if _KERNEL_PROFILER.enabled else 0.0
            # A masked step needs the FULL logits array (the topk-candidate
            # GPU path never reads it back at all -- see _get_logits_ptr's
            # comment above), so an active constraint forces one extra
            # readback for just this token even on the greedy fast path.
            # lm_head.logits_buffer is populated by the graph replay either
            # way (use_topk only decides whether the topk-reduce kernel
            # ALSO ran in the same replay), so this doesn't require
            # recapturing the graph or touching use_topk's own bookkeeping.
            if choice_constraint is not None and constraint_state.active and (use_topk or use_stochastic_topk):
                logits = _read_logits()
            if choice_constraint is not None and constraint_state.active:
                logits = choice_constraint.apply_mask(logits, constraint_state)
                next_token = self.sampler.sample(
                    logits=logits,
                    temperature=temperature,
                    top_p=top_p,
                    top_k=top_k,
                    repetition_penalty=1.0,
                    generated_tokens=None,
                    ignore_tokens=None,
                )
            elif use_topk:
                next_token = Sampler.pick_greedy_from_gpu_candidates(
                    group_values, group_indices, gathered_values, unique_ids, counts, repetition_penalty
                )
            elif use_stochastic_topk:
                next_token = Sampler.sample_from_gpu_candidates(
                    candidate_values, candidate_indices, stoch_gathered_values, unique_ids, counts,
                    temperature, top_p, top_k, repetition_penalty,
                )
            else:
                next_token = self.sampler.sample(
                    logits=logits,
                    temperature=temperature,
                    top_p=top_p,
                    top_k=top_k,
                    repetition_penalty=repetition_penalty,
                    generated_tokens=input_tokens[prompt_len:],
                    ignore_tokens=ignore_token_set,
                )

            # Para no fim de turno (<|im_end|>) ou <|endoftext|>. Sem isto o
            # modelo continua gerando muito além da resposta, divergindo para
            # texto incoerente -- era o "texto quebrado no final". decode() já
            # retorna "" para esses tokens, mas o loop precisa PARAR, não só
            # emitir vazio.
            if next_token in stop_ids:
                finish_reason = "stop"
                break

            input_tokens.append(next_token)
            word = utf8_decoder.feed(self.tokenizer.decode_bytes([next_token]))
            if choice_constraint is not None:
                # observe_token BEFORE observe_text: advances an ALREADY-
                # active state using this token first, THEN checks for a
                # fresh trigger match -- calling them in the other order
                # would let the very token that just completed the
                # trigger get double-consumed as if it were also the
                # first token of the choice itself (confirmed by a real
                # failure while building this: reversing the order made
                # every choice immediately dead-end on its first token).
                constraint_state = choice_constraint.observe_token(constraint_state, next_token)
                constraint_state = choice_constraint.observe_text(constraint_state, word)
            if word:
                yield word

            current_seq_len += 1
            if current_seq_len >= self._context_length:
                break

            # Sobe o conteúdo do próximo conjunto de exclusão ANTES do
            # replay que vai usá-lo -- o kernel topk roda DENTRO do mesmo
            # replay que recalcula os logits (gravado no grafo logo após o
            # LM Head), então precisa ver a janela de repetição já
            # atualizada com o `next_token` recém-anexado a input_tokens.
            if use_topk:
                unique_ids, counts = Sampler.compute_repetition_ids(
                    input_tokens[prompt_len:], vocab_size, ignore_token_set
                )
                self._topk_reducer.upload_exclude(unique_ids)
            elif use_stochastic_topk:
                unique_ids, counts = Sampler.compute_repetition_ids(
                    input_tokens[prompt_len:], vocab_size, ignore_token_set
                )
                self._stochastic_topk_reducer.upload_exclude(unique_ids)

            # Processa o token recém-gerado na sua posição para prever o próximo.
            if self._use_hip_graph:
                self.executor.execute_decode(next_token, kv_offset=current_seq_len - 1)
            else:
                self.executor.decode_step(next_token, current_seq_len - 1)
            kv_valid_len = current_seq_len

            # Histórico: 15ms fixos -> virou teto artificial de velocidade
            # (~66 tok/s) quando HIP Graph + fusão baixaram o tempo real de
            # GPU bem abaixo disso -> 2ms de pulso de keep-alive (proteção
            # contra o DPM do WDDM derrubar o clock entre tokens) -> 0.0ms
            # (padrão atual): com o Split-KV, o tick caiu para ~9-10ms,
            # rápido o bastante para o DPM nunca ter uma janela ociosa longa
            # o suficiente para agir — medido sem TDR em rajada contínua e em
            # gaps reais de 3s entre turnos (ver README). Configurável via
            # VTE_KEEPALIVE_PULSE_MS para reverter sem deploy de código.
            self._keepalive.pulse(self._keepalive_pulse_s)
            if use_topk:
                # O replay acima já rodou o kernel topk (dentro do grafo)
                # com o exclude_ids/count subidos logo acima -- só falta ler
                # de volta os candidatos.
                group_values, group_indices, gathered_values = self._topk_reducer.read_candidates()
            elif use_stochastic_topk:
                candidate_values, candidate_indices, stoch_gathered_values = self._stochastic_topk_reducer.read_candidates()
            else:
                logits = _read_logits()
            if _KERNEL_PROFILER.enabled:
                _KERNEL_PROFILER.mark_token((time.perf_counter() - t_tok_start) * 1000.0)

        tail = utf8_decoder.flush()
        if tail:
            yield tail

        # Not reached on cancellation (gen.close() raises GeneratorExit at
        # whatever yield the loop above is suspended on), same as `stats`
        # below -- left at its previous value in that case, which is still
        # a true (if shorter-than-optimal) prefix of what's actually in the
        # KV cache now, so the next call's skip-prefix search below just
        # undershoots a little instead of ever assuming a stale position is
        # valid when it isn't.
        #
        # Measured caveat (not a bug): a later prompt that re-encodes THIS
        # reply as rendered chat-template text won't always retokenize back
        # to these exact sampled token ids -- BPE encode(decode(tokens)) can
        # legitimately merge differently than the greedy one-token-at-a-time
        # sampling that produced them. The skip-prefix search below still
        # handles this safely (a mismatch just ends the shared prefix
        # there, never assumes wrong data is valid), so the reply itself
        # commonly gets re-prefilled next round even though the system
        # prompt + prior user turns before it reliably don't -- confirmed
        # against the real Aetheris system prompt on Qwen2.5 7B: round 1
        # (cold) 32.4s TTFT, round 2 (same session) 2.6s, a ~12x drop even
        # with this caveat, since the system prompt is by far the larger
        # fixed cost.
        self._last_kv_sequence = input_tokens[:kv_valid_len]

        if stats is not None:
            completion_tokens = len(input_tokens) - prompt_len
            stats["completion_tokens"] = completion_tokens
            stats["finish_reason"] = finish_reason
            # Named to match FastFlowLM's usage.{prefill_duration_ttft,decoding_speed_tps}
            # convention, which Lemonade's telemetry (StreamingProxy::extract_telemetry_
            # from_chunk) already parses -- reusing it means Lemonade picks these up with
            # no adapter-side change needed.
            stats["prefill_duration_ttft"] = t_prefill_end - t_start
            decode_duration = time.perf_counter() - t_prefill_end
            stats["decoding_speed_tps"] = (
                completion_tokens / decode_duration if decode_duration > 0 and completion_tokens > 0 else 0.0
            )

    def generate_batch(
        self,
        prompts: list,
        max_tokens: int = 100,
        temperature: float = None,
        top_p: float = 0.9,
        top_k: int = 50,
        repetition_penalty: float = None,
    ):
        """
        Fase II (preparação para scheduler): gera para `len(prompts)`
        sequências SIMULTANEAMENTE via BatchedHIPGraphExecutor — mesmos
        pesos do modelo já carregado (compartilhados, sem duplicar VRAM),
        KV cache/arena/RoPE cache alocados sob demanda para este batch_size.

        Escopo desta etapa (deliberado, ver Fase I/plano): todos os prompts
        precisam ter o MESMO número de tokens (lockstep puro). Suportar
        prompts de tamanhos diferentes exige mascaramento de atenção para
        ignorar posições de padding — isso é trabalho de scheduler real
        (Fase II completa: fila de admissão, paginação de KV cache), não
        uma mudança trivial de tokenização. Levantamos um erro claro em vez
        de gerar silenciosamente resultados incorretos.

        Yields:
            list[str]: uma palavra por sequência do batch, a cada "tick".
        """
        self._lifecycle.ensure_loaded()
        self._lifecycle.touch()

        if temperature is None:
            temperature = self._default_temperature()
        if repetition_penalty is None:
            repetition_penalty = self._default_repetition_penalty()

        batch_size = len(prompts)
        tokenized = [self.tokenizer.encode(p) for p in prompts]
        lengths = {len(t) for t in tokenized}
        if len(lengths) != 1:
            raise ValueError(
                f"generate_batch requer prompts do MESMO comprimento em tokens (lockstep) "
                f"nesta etapa — recebido comprimentos {sorted(lengths)}. Padding com máscara de "
                f"atenção fica para a Fase II completa (scheduler com admissão heterogênea)."
            )
        prompt_len = lengths.pop()

        from vte.core.batched_hip_graph_executor import BatchedHIPGraphExecutor
        batch_tensor_mapping = self._mapper.allocate_batch_runtime_state(
            self.tensor_mapping, self._allocator, self._hip,
            self._context_length, batch_size, profiler=self.profiler
        )

        # Mesmo padrão da Fase 2 (batch=1): resolve peso/buffer/kernel do LM
        # Head ANTES do BatchedHIPGraphExecutor existir, para gravá-lo DENTRO
        # do grafo batched (elimina o lançamento eager de compute_logits_batch,
        # ~7.5ms/tick medidos). Regra de ouro: o grafo só ESCREVE os logits na
        # VRAM -- o hipMemcpy D2H e o Sampler continuam rodando DEPOIS do
        # graph_launch retornar, nunca dentro da captura.
        lm_head_batch_info = None
        try:
            lm_head_batch_info = self._resolve_lm_head_capture_info(
                batch_size=batch_size, tensor_mapping=batch_tensor_mapping
            )
        except Exception as e:
            logger.warning(f"Não foi possível pré-resolver o LM Head batched para captura no grafo: {e}. "
                            f"LM Head batched continuará rodando eager, fora do grafo.")

        batch_executor = BatchedHIPGraphExecutor(
            self._hip, self._allocator, self._graph, batch_tensor_mapping, self.metadata,
            batch_size=batch_size, lm_head_info=lm_head_batch_info
        )

        for pos in range(prompt_len):
            tokens_at_pos = [tokenized[b][pos] for b in range(batch_size)]
            batch_executor.execute_decode_batch(tokens_at_pos, [pos] * batch_size)

        def _read_logits_batch():
            buf = bytearray(batch_size * self.lm_head.vocab_size * 2)
            if lm_head_batch_info is not None:
                logits_ptr = lm_head_batch_info['logits_buffer_ptr']
            else:
                hidden_ptr = batch_tensor_mapping['output_norm.output']
                hidden_val = hidden_ptr.ptr if hasattr(hidden_ptr, 'ptr') else hidden_ptr
                logits_ptr = self.lm_head.compute_logits_batch(hidden_val, batch_size)
            self._hip.safe_memcpy_device_to_host(buf, ctypes.c_void_p(logits_ptr), tag="logits_d2h")
            return np.frombuffer(bytes(buf), dtype=np.float16).astype(np.float32).reshape(batch_size, self.lm_head.vocab_size)

        logits_batch = _read_logits_batch()
        current_seq_len = prompt_len
        # Um decoder incremental POR sequência do batch -- cada uma tem seu
        # próprio buffer de bytes pendentes, independente das outras (ver
        # vte/core/incremental_decoder.py e o mesmo tratamento em generate()).
        utf8_decoders = [IncrementalUTF8Decoder() for _ in range(batch_size)]

        for i in range(max_tokens):
            next_tokens = []
            words = []
            for b in range(batch_size):
                tok = self.sampler.sample(
                    logits=logits_batch[b], temperature=temperature, top_p=top_p,
                    top_k=top_k, repetition_penalty=repetition_penalty,
                    generated_tokens=tokenized[b][prompt_len:],
                    ignore_tokens=set(self.tokenizer.special_tokens.values()),
                )
                tokenized[b].append(tok)
                next_tokens.append(tok)
                words.append(utf8_decoders[b].feed(self.tokenizer.decode_bytes([tok])))
            yield words

            current_seq_len += 1
            if current_seq_len >= self._context_length:
                break

            batch_executor.execute_decode_batch(next_tokens, [current_seq_len - 1] * batch_size)
            self._keepalive.pulse(self._keepalive_pulse_s)
            logits_batch = _read_logits_batch()

        tails = [d.flush() for d in utf8_decoders]
        if any(tails):
            yield tails

    def unload(self):
        """Descarrega o modelo da VRAM (limpa slabs e libera HIP)."""
        logger.info("Iniciando unload seguro do modelo...")
        self._is_loaded = False
        try:
            from vte.bridge.vram_pressure_guard import get_vram_pressure_guard
            get_vram_pressure_guard().unregister_model(self)
        except Exception:
            pass
        self._lifecycle.unload()
        if self._allocator:
            self._allocator.cleanup()
            self._allocator = None
        if self._hip:
            self._hip.cleanup()
            self._hip = None
        logger.info("Modelo descarregado da VRAM com sucesso")

    def get_vram_usage(self) -> dict:
        """Retorna as estatísticas do VRAMProfiler"""
        if self.profiler:
            return self.profiler.get_summary_dict()
        return {'total_mb': 0, 'weights_mb': 0, 'kv_cache_mb': 0, 'arena_mb': 0, 'scratch_mb': 0}

    def get_model_status(self) -> dict:
        """Retorna status do modelo"""
        return self._lifecycle.get_status()
    
    def __del__(self):
        try:
            if hasattr(self, '_lifecycle') and self._lifecycle._is_loaded:
                logger.info("Cleanup automático: descarregando modelo...")
                self._lifecycle.unload()
        except Exception as e:
            logger.error(f"Erro no cleanup automático: {e}")
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.__del__()
        return False
