"""
Executor de alta performance usando HIP Graphs.

Grava o fluxo de kernels uma vez e executa com overhead mínimo de Python (~5µs).
O padrão de Staging Buffers separa a transferência de dados da execução do grafo,
garantindo conformidade com a API de Stream Capture da AMD/HIP.

Segurança de recursos da GPU: o grafo de decode é capturado UMA ÚNICA VEZ para
toda a geração (o kv_cache_offset é lido de um ponteiro na VRAM, atualizado a
cada passo, em vez de gravado como escalar fixo na captura). Grafos de prefill
(um por tamanho de prompt distinto) são cacheados com um teto — o mais antigo é
destruído (hipGraphExecDestroy) antes de capturar um novo além do limite, para
não acumular recursos de GPU indefinidamente.
"""

import numpy as np
import ctypes
import shutil
from collections import OrderedDict
from typing import Dict, Optional, List
from vte.bridge.hip_runtime import HIPRuntime
from vte.bridge.memory import SlabAllocator, MemoryRegion
from vte.compiler.ir import IRGraph, IRNode, NodeType
from vte.compiler.codegen import CodegenEngine
from vte.core.kernel_arg_builder import KernelArgBuilder
from vte.bridge.logger import get_logger

logger = get_logger(__name__)

class GraphCaptureError(Exception):
    pass

class HIPGraphExecutor:
    """
    Executor de altíssima performance usando HIP Graphs.
    Grava operações e as executa com < 5µs de overhead em Python.
    """

    DYNAMIC_INPUT_TENSORS = frozenset([
        "input_ids", "input_embeddings", "hidden_states"
    ])

    MAX_CACHED_PREFILL_GRAPHS = 2

    def __init__(self, hip: HIPRuntime, allocator: SlabAllocator, graph: IRGraph, tensor_mapping: dict, metadata: dict = None, lm_head_info: dict = None, context_length: int = None, topk_info: dict = None):
        self.hip = hip
        self.allocator = allocator
        self.ir_graph = graph
        self.tensor_mapping = tensor_mapping
        self.metadata = metadata or {}
        # `metadata['context_length']` é o valor NATIVO do GGUF (32768 no
        # Qwen2.5), não o `context_length` runtime usado para dimensionar o
        # KV cache de verdade (default 2048) -- por isso é um parâmetro
        # próprio, usado só para dimensionar o scratchpad do Split-KV.
        self.context_length = context_length or 4096

        # Fase 2 (41->100 tok/s): se resolvido em model.py ANTES deste
        # executor existir (peso/tied embeddings, logits_buffer, kernel já
        # compilado -- todos endereços fixos), o LM Head é gravado DENTRO do
        # grafo de decode em vez de rodar como lançamento eager separado a
        # cada token (eliminava ~3.19ms/tok de overhead de despacho). Só se
        # aplica ao grafo de decode (seq_len sempre 1) -- ver _capture_graph.
        self.lm_head_info = lm_head_info

        # Opt-in (VTE_TOPK_LOGITS_READBACK=1): redução de logits pro caminho
        # greedy, gravada DENTRO do grafo logo após o LM Head -- mesma
        # motivação da linha acima (uma versão eager, fora do grafo, media
        # perda líquida de tok/s: o despacho de um kernel novo custava mais
        # que a leitura reduzida economizava). Ver TopKLogitsReducer e
        # _capture_topk_reduce. Só o dict de ponteiros/kernel_fn (endereços
        # fixos); model.py mantém a instância de TopKLogitsReducer para
        # upload_exclude()/read_candidates() a cada passo de generate().
        self.topk_info = topk_info

        self.num_layers = self.metadata.get('block_count', 28)
        self.max_seq_len = 4096

        self.decode_graph: Optional[ctypes.c_void_p] = None
        self.prefill_graphs: "OrderedDict[int, ctypes.c_void_p]" = OrderedDict()

        self._kernel_cache: Dict[str, tuple] = {}
        self.arg_builder = KernelArgBuilder()

        # `codegen.compile_kernel()` semeia binários AOT empacotados antes de
        # sequer checar hipcc (ver codegen.py "Semeadura AOT"), então a
        # ausência de hipcc no PATH não implica ausência de kernels reais --
        # só bloqueava a recompilação sob demanda quando NENHUM AOT bate.
        # Gatear a captura inteira aqui nesse caso fazia o grafo virar
        # vazio (logits sempre zero) em qualquer máquina sem hipcc, mesmo
        # com o AOT certo pra GPU local já no pacote -- achado real rodando
        # sem hipcc numa RX 7600 com kernels AOT gfx1102 presentes.
        if shutil.which("hipcc") is None:
            logger.info("hipcc não encontrado no PATH; kernels virão do cache AOT empacotado (recompilação sob demanda indisponível).")

        self.codegen = CodegenEngine()

        self.staging_input = self.allocator.allocate(
            size=self.max_seq_len * 4,
            tag='staging_input',
            region=MemoryRegion.SCRATCH
        )

        # Buffer de 1 int reutilizado por TODAS as capturas: o kernel lê o
        # offset por ponteiro, então o mesmo grafo capturado uma vez continua
        # correto em qualquer posição do KV cache — só este valor muda entre
        # replays, nunca o grafo em si.
        self.staging_kv_offset = self.allocator.allocate(
            size=4,
            tag='staging_kv_offset',
            region=MemoryRegion.SCRATCH
        )

        self.staging_buffers = {
            'input_ids': self.staging_input,
            'input_embeddings': self.staging_input,
        }

        # Fusão Profunda: substitui os 5 kernels separados (attn_norm, q_proj,
        # k_proj, v_proj, rope) por 3 lançamentos do kernel fundido, e os 4
        # kernels do FFN (ffn_norm, gate_proj, up_proj, swiglu) por 1 — todos
        # gravados no grafo com launch_kernel_recorded (mesma lógica do
        # FallbackExecutor).
        from vte.core.fused_qkv_dispatch import FusedQKVDispatcher, FusedFFNDispatcher, layer_input_tensor_name
        self._fused_qkv = FusedQKVDispatcher(self.hip, self.codegen, self.metadata, allocator=self.allocator)
        self._fused_ffn = FusedFFNDispatcher(self.hip, self.codegen, self.metadata)
        self._layer_input_tensor_name = layer_input_tensor_name

        # Split-KV (Flash-Decoding): opt-in via VTE_ENABLE_ATTN_SPLITKV, ver
        # split_kv_attention.py para a motivação medida e o design completo.
        from vte.core.split_kv_attention import SplitKVAttentionDispatcher
        self._split_kv = SplitKVAttentionDispatcher(
            self.hip, self.codegen, self.metadata, allocator=self.allocator,
            context_length=self.context_length
        )

    def _get_or_compile_kernel(self, node: IRNode) -> Optional[ctypes.c_void_p]:
        """
        Compila e carrega o kernel para um nó, com cache para evitar recompilação.
        Sempre tenta `codegen.load_kernel_safe` (que semeia do AOT empacotado
        antes de precisar de hipcc); só devolve None se essa tentativa falhar
        de verdade (nem AOT bate nem há hipcc pra compilar sob demanda).
        """
        arch = self.hip.get_gpu_architecture()

        op_to_template = {
            NodeType.RMSNORM: "rmsnorm",
            NodeType.MATMUL: "matmul",
            NodeType.ROPE: "rope",
            NodeType.ATTENTION: "flash_attention",
            NodeType.SWIGLU: "swiglu",
            NodeType.ADD: "add",
            "mega_kernel": "fused_rmsnorm_matmul_rope",
            # Gated DeltaNet (Qwen3.5 "linear_attention") -- isolado, não
            # afeta nenhuma entrada acima.
            NodeType.CAUSAL_CONV1D: "causal_conv1d",
            NodeType.LINEAR_ATTENTION: "gated_delta_recurrent",
            NodeType.RMSNORM_GATED: "rmsnorm_gated",
            # Qwen3.5 full_attention: q_norm/k_norm + gate sigmoide pré-o_proj.
            NodeType.PER_HEAD_RMSNORM: "per_head_rmsnorm",
            NodeType.SIGMOID_GATE_MUL: "sigmoid_gate_mul",
        }
        from vte.core.fallback_executor import _is_vectorized_matmul, _is_q4k_matmul, _is_q6k_matmul, _is_q8_0_matmul, _is_q5_0_matmul
        if _is_q4k_matmul(node):
            template = "gemv_q4k"
        elif _is_q6k_matmul(node):
            template = "gemv_q6k"
        elif _is_q8_0_matmul(node):
            template = "gemv_q8_0"
        elif _is_q5_0_matmul(node):
            template = "gemv_q5_0"
        elif _is_vectorized_matmul(node):
            template = "gemv_coalesced"
        else:
            template = op_to_template.get(node.op_type)
        if template is None:
            logger.warning(f"Sem template mapeado para op_type '{node.op_type}'. Nó ignorado na captura.")
            return None

        # A chave DEVE incluir o template: nós de MATMUL com a mesma shape mas
        # kernels diferentes (ex.: down_proj Q4_K -> gemv_q4k vs attn_output
        # FP16 -> gemv_coalesced, ambos shape (1,-1,1536)) colidiriam se a chave
        # fosse só op_type+shape, fazendo um herdar o kernel do outro e ler o
        # peso no formato errado (NaN). Este era o bug que só aparecia no grafo
        # (o executor eager já chaveava por nome).
        cache_key = f"{template}_{node.shape}"
        if cache_key in self._kernel_cache:
            return self._kernel_cache[cache_key][1]

        try:
            module, function = self.codegen.load_kernel_safe(
                self.hip, template, arch, f"{template}_kernel",
                hidden_size=node.shape[-1] if node.shape else 1536,
                is_mega_kernel=(node.op_type == "mega_kernel")
            )
            self._kernel_cache[cache_key] = (module, function)
            return function
        except Exception as e:
            logger.warning(f"Kernel {template} não compilado: {e}. Nó ignorado na captura.")
            return None

    def _build_fused_gdn_proj_launch(self, layer_idx: int):
        """Qwen3.5 Gated DeltaNet: monta o lançamento fundido de
        qkv_proj+z_proj+a_proj+b_proj (ver fused_gdn_proj.hip.template e a
        versão irmã em fallback_executor.py::_dispatch_fused_gdn_proj).
        Tensores de saída já vêm pré-alocados (endereço fixo) por
        model.py::_allocate_activation_buffers -- não precisa alocação
        preguiçosa aqui, ao contrário do FallbackExecutor."""
        arch = self.hip.get_gpu_architecture()
        cache_key = "fused_gdn_proj"
        if cache_key not in self._kernel_cache:
            module, function = self.codegen.load_kernel_safe(self.hip, cache_key, arch, f"{cache_key}_kernel")
            self._kernel_cache[cache_key] = (module, function)
        fn = self._kernel_cache[cache_key][1]

        input_ptr = self.arg_builder._resolve_tensor_ptr(
            f"blk.{layer_idx}.attn_norm.output", self.tensor_mapping, {}
        )
        weight_qkv_ptr = self.arg_builder._resolve_tensor_ptr(
            f"blk.{layer_idx}.attn_qkv.weight", self.tensor_mapping, {}
        )
        weight_z_ptr = self.arg_builder._resolve_tensor_ptr(
            f"blk.{layer_idx}.attn_gate.weight", self.tensor_mapping, {}
        )
        weight_a_ptr = self.arg_builder._resolve_tensor_ptr(
            f"blk.{layer_idx}.ssm_alpha.weight", self.tensor_mapping, {}
        )
        weight_b_ptr = self.arg_builder._resolve_tensor_ptr(
            f"blk.{layer_idx}.ssm_beta.weight", self.tensor_mapping, {}
        )
        output_qkv_ptr = self.arg_builder._resolve_tensor_ptr(f"blk.{layer_idx}.qkv_proj.output", self.tensor_mapping, {})
        output_z_ptr = self.arg_builder._resolve_tensor_ptr(f"blk.{layer_idx}.z_proj.output", self.tensor_mapping, {})
        output_a_ptr = self.arg_builder._resolve_tensor_ptr(f"blk.{layer_idx}.a_proj.output", self.tensor_mapping, {})
        output_b_ptr = self.arg_builder._resolve_tensor_ptr(f"blk.{layer_idx}.b_proj.output", self.tensor_mapping, {})

        num_heads = self.metadata.get('linear_attn.num_heads', 16)
        conv_dim = self.metadata.get('linear_attn.conv_dim', 6144)
        value_dim = self.metadata.get('linear_attn.value_dim', 2048)
        hidden_size = self.metadata.get('embedding_length', 2048)
        args = [
            ctypes.c_void_p(input_ptr),
            ctypes.c_void_p(weight_qkv_ptr),
            ctypes.c_void_p(weight_z_ptr),
            ctypes.c_void_p(weight_a_ptr),
            ctypes.c_void_p(weight_b_ptr),
            ctypes.c_void_p(output_qkv_ptr),
            ctypes.c_void_p(output_z_ptr),
            ctypes.c_void_p(output_a_ptr),
            ctypes.c_void_p(output_b_ptr),
            ctypes.c_int(hidden_size),
            ctypes.c_int(conv_dim),
            ctypes.c_int(value_dim),
            ctypes.c_int(num_heads),
        ]
        total_rows = conv_dim + value_dim + 2 * num_heads
        return fn, args, (total_rows, 1, 1), (64, 1, 1), 0

    def _capture_embedding_lookup(self, seq_len: int):
        """
        Grava o kernel de embedding lookup como a PRIMEIRA operação do grafo,
        lendo os token ids do staging_input (atualizado antes de cada replay)
        e escrevendo em 'input_embeddings' (endereço fixo lido por
        blk.0.attn_norm).

        Sem isso, o grafo nunca calcula embeddings de verdade: o compute
        graph (qwen_compute.py) só tem um nó INPUT marcador (sempre pulado no
        despacho), não um nó de embedding real — só o FallbackExecutor tinha
        um método manual para isso, nunca chamado pelo HIPGraphExecutor. O
        resultado era que 'input_embeddings' ficava com o mesmo conteúdo
        "congelado" em todo replay, ignorando o token realmente processado.
        """
        arch = self.hip.get_gpu_architecture()
        from vte.core.fallback_executor import RAW_Q4K_WEIGHTS, RAW_Q6K_WEIGHTS, RAW_Q8_0_WEIGHTS
        if 'token_embd.weight' in RAW_Q4K_WEIGHTS:
            template = "embedding_lookup_q4k"
        elif 'token_embd.weight' in RAW_Q6K_WEIGHTS:
            template = "embedding_lookup_q6k"
        elif 'token_embd.weight' in RAW_Q8_0_WEIGHTS:
            template = "embedding_lookup_q8_0"
        else:
            template = "embedding_lookup"
        cache_key = template
        if cache_key not in self._kernel_cache:
            module, function = self.codegen.load_kernel_safe(self.hip, template, arch, f"{template}_kernel")
            self._kernel_cache[cache_key] = (module, function)
        else:
            function = self._kernel_cache[cache_key][1]

        embed_weight_ptr = self.tensor_mapping.get('token_embd.weight')
        embed_ptr_val = embed_weight_ptr.ptr if hasattr(embed_weight_ptr, 'ptr') else embed_weight_ptr
        output_ptr = self.tensor_mapping.get('input_embeddings')
        out_ptr_val = output_ptr.ptr if hasattr(output_ptr, 'ptr') else output_ptr
        hidden_size = self.metadata.get('embedding_length', 1536)

        args = [
            ctypes.c_void_p(self.staging_input.ptr),
            ctypes.c_void_p(embed_ptr_val),
            ctypes.c_void_p(out_ptr_val),
            ctypes.c_int(seq_len),
            ctypes.c_int(hidden_size),
            ctypes.c_float(self.metadata.get('embedding_scale', 1.0)),
        ]
        total_elements = seq_len * hidden_size
        block_size = 256
        grid_size = max(1, (total_elements + block_size - 1) // block_size)
        self.hip.launch_kernel_recorded(function, args, (grid_size, 1, 1), (block_size, 1, 1), 0)

    def _build_kernel_args(self, node: IRNode, seq_len: int) -> list:
        """
        Monta os argumentos (ponteiros VRAM + escalares) na ABI exata esperada
        pelo kernel, usando o mesmo KernelArgBuilder do FallbackExecutor.
        Tensores de input dinâmico são redirecionados para o Staging Buffer.
        O kv_cache_offset é sempre passado como PONTEIRO (staging_kv_offset),
        nunca como escalar — é isso que permite reutilizar o grafo capturado.
        """
        args, _ = self.arg_builder.build_args(
            node=node,
            tensor_mapping=self.tensor_mapping,
            staging_buffers=self.staging_buffers,
            seq_len=seq_len,
            metadata=self.metadata,
            kv_offset_ptr=self.staging_kv_offset.ptr,
        )
        return args

    def _calculate_launch_dims(self, node: IRNode, seq_len: int, batch: int = 1) -> tuple:
        """
        Calcula Grid (x, y, z), Block (x, y, z) e Shared Memory por tipo de nó,
        replicando exatamente o indexing (blockIdx.x/y, threadIdx.x) esperado por
        cada kernel .hip — usar uma fórmula genérica aqui desalinha blockIdx.y de
        MATMUL/ATTENTION com o que o kernel espera (só a "linha 0" seria
        computada corretamente) e gera lançamentos muito maiores que o
        necessário, sobrecarregando a GPU sem necessidade.

        `batch` default=1 preserva o comportamento de produção existente; a
        Fase I (Batched Decode) passa o batch_size real.
        """
        block_size = 256

        if node.op_type == NodeType.MATMUL:
            from vte.core.fallback_executor import _is_vectorized_matmul, _is_q4k_matmul, _is_q6k_matmul, _is_q8_0_matmul, _is_q5_0_matmul, _coalesced_gemv_dims
            if _is_q4k_matmul(node) or _is_q6k_matmul(node) or _is_q8_0_matmul(node) or _is_q5_0_matmul(node) or _is_vectorized_matmul(node):
                return _coalesced_gemv_dims(node, seq_len, batch)
            out_features = node.shape[-1]
            m = batch * seq_len
            grid_x = (out_features + block_size - 1) // block_size
            return (grid_x, m, 1), (block_size, 1, 1), 0

        if node.op_type == NodeType.RMSNORM:
            return (batch * seq_len, 1, 1), (block_size, 1, 1), 0

        if node.op_type == NodeType.ATTENTION:
            # FlashDecoding: 1 bloco por (batch, q_head), head_dim threads/bloco
            # (uma dimensão de saída por thread). LDS = q_sh + red = 2*head_dim.
            num_q_heads = self.metadata.get('attention.head_count', 12)
            head_dim = self.metadata.get('attention.key_length', 128)
            shared = 2 * head_dim * 4
            return (batch, num_q_heads, 1), (head_dim, 1, 1), shared

        if node.op_type == NodeType.ROPE:
            # blockIdx.y = batch_idx explícito (rope.hip.template, Fase I).
            total_elements = seq_len
            if node.shape:
                for dim in node.shape:
                    if dim > 0:
                        total_elements *= dim
            grid_x = max(1, (total_elements + block_size - 1) // block_size)
            return (grid_x, batch, 1), (block_size, 1, 1), 0

        if node.op_type in [NodeType.SWIGLU, NodeType.ADD]:
            total_elements = batch * seq_len
            if node.shape:
                for dim in node.shape:
                    if dim > 0:
                        total_elements *= dim
            grid_x = max(1, (total_elements + block_size - 1) // block_size)
            return (grid_x, 1, 1), (block_size, 1, 1), 0

        if node.op_type == NodeType.CAUSAL_CONV1D:
            # 1 thread por canal, sem __syncthreads/LDS -- block=64 (1
            # wavefront RDNA exato, zero lane mascarado) em vez do
            # block_size genérico de 256, o que quadruplica o número de
            # blocos (24->96) sem mudar o total de threads/trabalho. Já é
            # hardware-agnóstico por natureza: grid_x deriva de conv_dim
            # (largura do MODELO, não da GPU), então já escala sozinho para
            # QUALQUER contagem de CUs -- 96 blocos ocupa bem tanto uma GPU
            # de 32 CUs (RX 7600, 3 blocos/CU) quanto uma maior (ver
            # docs/PERFORMANCE.md, cópia irmã em
            # fallback_executor.py::_calculate_launch_dims).
            conv_dim = self.metadata.get('linear_attn.conv_dim', 6144)
            conv1d_block = 64
            grid_x = max(1, (conv_dim + conv1d_block - 1) // conv1d_block)
            return (grid_x, 1, 1), (conv1d_block, 1, 1), 0

        if node.op_type == NodeType.LINEAR_ATTENTION:
            # 1 bloco por head, head_v_dim threads/bloco -- thread l é dona
            # da coluna l do estado (ver gated_delta_recurrent.hip.template).
            num_heads = self.metadata.get('linear_attn.num_heads', 16)
            head_v_dim = self.metadata.get('linear_attn.head_v_dim', 128)
            return (num_heads, batch, 1), (head_v_dim, 1, 1), 0

        if node.op_type == NodeType.RMSNORM_GATED:
            # 1 linha (blockIdx.x) por HEAD, não por token -- confirmado no
            # código real (core_attn_out/z são reshaped pra (-1, head_v_dim)
            # antes do norm). grid.x = num_heads * batch.
            num_heads = self.metadata.get('linear_attn.num_heads', 16)
            head_v_dim = self.metadata.get('linear_attn.head_v_dim', 128)
            return (num_heads * batch, 1, 1), (head_v_dim, 1, 1), 0

        if node.op_type == NodeType.PER_HEAD_RMSNORM:
            # 1 bloco por head, head_dim threads/bloco -- q_norm usa
            # num_q_heads, k_norm usa num_kv_heads (distinguidos pelo nome
            # do nó, ver kernel_arg_builder.py::_build_per_head_rmsnorm_args).
            head_dim = self.metadata.get('attention.key_length', 128)
            if node.name.endswith('.q_norm'):
                num_heads = self.metadata.get('attention.head_count', 12)
            else:
                num_heads = self.metadata.get('attention.head_count_kv', 2)
            return (num_heads, 1, 1), (head_dim, 1, 1), head_dim * 4

        if node.op_type == NodeType.SIGMOID_GATE_MUL:
            head_dim = self.metadata.get('attention.key_length', 128)
            num_heads = self.metadata.get('attention.head_count', 12)
            total = num_heads * head_dim
            grid_x = max(1, (total + block_size - 1) // block_size)
            return (grid_x, 1, 1), (block_size, 1, 1), 0

        return (1, 1, 1), (block_size, 1, 1), 0

    def _capture_lm_head(self):
        """
        Grava o lançamento do LM Head (GEMV final, vocab x hidden) DENTRO do
        grafo de decode, usando os ponteiros/kernel já resolvidos em
        model.py._resolve_lm_head_capture_info() antes deste executor
        existir. Mesma assinatura de 9 argumentos de gemv_coalesced/
        gemv_q4k/gemv_q6k (input, weight, output, batch, seq_len,
        in_features, out_features, bias_ptr, residual_ptr) -- batch e
        seq_len são sempre 1 aqui (grafo de decode), então entram como
        constantes, não como ponteiros: não mudam entre replays, ao
        contrário do kv_cache_offset (que por isso é lido por ponteiro).
        """
        info = self.lm_head_info
        last_hidden_ptr = self.tensor_mapping.get('output_norm.output')
        last_hidden_val = last_hidden_ptr.ptr if hasattr(last_hidden_ptr, 'ptr') else last_hidden_ptr

        # Reaproveita o slot de residual_scale do epílogo do GEMV para aplicar
        # o logit_scale do Granite: como o LM Head nunca tem residual_ptr
        # (sempre nullptr), `total = dot_product * residual_scale` é
        # exatamente `logits = hidden @ W * (1/logit_scale)` -- confirmado em
        # granite.cpp: ggml_scale(cur, 1.0f/hparams.f_logit_scale) DIVIDE os
        # logits (não multiplica por 10 -- verificado direto no código-fonte,
        # não em paráfrase). Default 1.0 (Qwen não tem logit_scale).
        logit_scale = self.metadata.get('logit_scale', 1.0) or 1.0
        c_logit_mul = ctypes.c_float(1.0 / logit_scale)

        args = [
            ctypes.c_void_p(last_hidden_val),
            ctypes.c_void_p(info['weight_ptr']),
            ctypes.c_void_p(info['logits_buffer_ptr']),
            ctypes.c_int(1),                     # batch
            ctypes.c_int(1),                     # seq_len (decode: sempre 1)
            ctypes.c_int(info['hidden_size']),
            ctypes.c_int(info['vocab_size']),
            ctypes.c_void_p(0),                  # bias (LM head não tem)
            ctypes.c_void_p(0),                  # residual (sem epilogue aqui)
            c_logit_mul,
        ]

        self.hip.launch_kernel_recorded(
            function=info['kernel_fn'],
            args=args,
            grid=(info['vocab_size'], 1, 1),
            block=(64, 1, 1),
            shared_mem=0,
        )

    def _capture_topk_reduce(self):
        """Grava topk_reduce_greedy_kernel DENTRO do grafo de decode, logo
        após o LM Head -- lê o MESMO logits_buffer que o LM Head acabou de
        escrever neste replay (endereço fixo, `self.lm_head_info[
        'logits_buffer_ptr']`), usando os ponteiros de exclusão/saída fixos
        de TopKLogitsReducer (`self.topk_info`, ver model.py e
        topk_logits_reducer.py). O CONTEÚDO do array de exclusão é
        atualizado pelo host (H2D pequeno) ANTES de cada hipGraphLaunch --
        só o endereço é fixo, exatamente como o kv_cache_offset acima."""
        info = self.topk_info
        lm_info = self.lm_head_info
        args = [
            ctypes.c_void_p(lm_info['logits_buffer_ptr']),
            info['exclude_ids_ptr'],
            info['exclude_count_ptr'],
            ctypes.c_int(lm_info['vocab_size']),
            info['values_ptr'],
            info['indices_ptr'],
            info['gathered_ptr'],
        ]
        self.hip.launch_kernel_recorded(
            function=info['kernel_fn'],
            args=args,
            grid=(1, 1, 1),
            block=(1024, 1, 1),
            shared_mem=0,
        )

    def _capture_graph(self, mode: str, seq_len: int) -> ctypes.c_void_p:
        """
        Captura o fluxo de kernels no stream da AMD, sempre a partir do AOT
        empacotado (ou de hipcc, se disponível, para recompilação sob
        demanda quando nenhum AOT bate).
        """
        logger.info(f"Iniciando captura de HIP Graph para mode='{mode}', seq_len={seq_len}")

        nodes_recorded = 0
        raw_graph = None

        try:
            self.hip.stream_begin_capture()

            self._capture_embedding_lookup(seq_len)
            nodes_recorded += 1

            # Fusão Profunda: quando encontramos o attn_norm de uma camada
            # (seq_len==1, único caso suportado pelo kernel fundido), gravamos
            # 3 lançamentos do kernel fundido em vez dos 5 nós separados
            # (attn_norm, q_proj, k_proj, v_proj, rope) e pulamos os outros 4
            # nós dessa camada no restante do loop.
            fused_skip_names: set = set()

            from vte.core.fallback_executor import SKIP_ADD_NODES
            for node in self.ir_graph.topological_sort():
                if node.op_type in [NodeType.INPUT, NodeType.OUTPUT]:
                    continue
                if getattr(node, 'is_fused', False):
                    continue
                # Epilogue Fusion: o Add do residual foi fundido no GEMV anterior,
                # então não gravamos esse nó no grafo (mata 56 launches/tok).
                if node.name in SKIP_ADD_NODES:
                    continue
                if seq_len == 1 and node.name in fused_skip_names:
                    continue

                # A fusão QKV+RoPE assume pesos Q/K/V separados
                # (attn_q/attn_k/attn_v.weight) -- verdade pro Qwen2.5/
                # Granite e pras camadas full_attention do Qwen3.5, mas
                # FALSO pras camadas linear_attention (Gated DeltaNet), que
                # também têm um nó "attn_norm" só que seguido de
                # attn_qkv.weight fundido (formato diferente). Sem esta
                # checagem, a fusão disparava por nome em toda camada,
                # resolvia os pesos inexistentes pra ponteiro nulo
                # (_resolve_ptr silencioso) e pulava o RMSNorm real da
                # camada -- causa raiz do "!!!!!!!!" repetido na geração.
                #
                # rope_type==2 identifica as camadas full_attention do
                # Qwen3.5, que têm q_norm/k_norm + gate sigmoide (ver
                # qwen3_5_compute.py) que o kernel fundido não sabe
                # calcular -- desativado especificamente pra elas.
                #
                # attn_q.weight em RAW_Q4K/Q6K/Q8_0_WEIGHTS: o kernel fundido
                # lê os pesos como `__half*` puro, sem dequant embutido --
                # roteá-los crus (Granite/Qwen2.5, decisão desta sessão pra
                # reduzir VRAM) produziria valores errados/NaN se a fusão
                # tentasse usá-los.
                from vte.core.fallback_executor import (
                    RAW_Q4K_WEIGHTS as _RAW_Q4K_WEIGHTS,
                    RAW_Q6K_WEIGHTS as _RAW_Q6K_WEIGHTS,
                    RAW_Q8_0_WEIGHTS as _RAW_Q8_0_WEIGHTS,
                    RAW_Q5_0_WEIGHTS as _RAW_Q5_0_WEIGHTS,
                )
                # Checa as 4 matrizes (Q/K/V/O), não só Q -- ver comentário
                # completo na cópia irmã em fallback_executor.py (bug real
                # achado com o Qwen2.5 0.5B: dtype mistura por camada, attn_v
                # cru em Q8_0 enquanto attn_q segue FP16 na mesma camada).
                _layer_idx_str = node.name.split('.')[1] if (node.op_type == NodeType.RMSNORM and node.name.endswith('.attn_norm')) else None
                _attn_q_name = f"blk.{_layer_idx_str}.attn_q.weight" if _layer_idx_str is not None else None
                _raw_sets = (_RAW_Q4K_WEIGHTS, _RAW_Q6K_WEIGHTS, _RAW_Q8_0_WEIGHTS, _RAW_Q5_0_WEIGHTS)
                _any_qkvo_raw = _attn_q_name is not None and any(
                    f"blk.{_layer_idx_str}.{suffix}" in s
                    for suffix in ("attn_q.weight", "attn_k.weight", "attn_v.weight", "attn_output.weight")
                    for s in _raw_sets
                )
                if (seq_len == 1 and _attn_q_name is not None
                        and _attn_q_name in self.tensor_mapping
                        and not _any_qkvo_raw
                        and self.metadata.get('rope_type') != 2):
                    layer_idx = int(node.name.split('.')[1])
                    try:
                        launches = self._fused_qkv.build_launches(
                            layer_idx, self.tensor_mapping, self.staging_kv_offset.ptr
                        )
                        for fn, args, grid, block, shared_mem in launches:
                            self.hip.launch_kernel_recorded(fn, args, grid, block, shared_mem)
                            nodes_recorded += 1
                        fused_skip_names.update({
                            f"blk.{layer_idx}.attn_norm", f"blk.{layer_idx}.q_proj",
                            f"blk.{layer_idx}.k_proj", f"blk.{layer_idx}.v_proj",
                            f"blk.{layer_idx}.rope",
                        })
                        continue
                    except Exception as e:
                        logger.warning(
                            f"Fusão QKV falhou na captura (camada {layer_idx}): {e}. "
                            f"Usando kernels separados para esta camada."
                        )

                # Fusão qkv_proj+z_proj+a_proj+b_proj (Qwen3.5 Gated
                # DeltaNet): as 4 partem da MESMA entrada (attn_norm.
                # output) -- funde num único lançamento em vez de 4 (ver
                # fused_gdn_proj.hip.template). 3 kernels a menos POR
                # CAMADA (18 camadas = 54 nós a menos no grafo, ~15% do
                # total) -- fusões de 1 kernel não mudavam o tok/s de
                # forma mensurável nesta sessão; esta é grande o bastante
                # pra ter chance real de aparecer na medição.
                if seq_len == 1 and node.op_type == NodeType.MATMUL and node.name.endswith('.qkv_proj'):
                    layer_idx = int(node.name.split('.')[1])
                    if f"blk.{layer_idx}.ssm_beta.weight" in self.tensor_mapping:
                        try:
                            fn, args, grid, block, shared = self._build_fused_gdn_proj_launch(layer_idx)
                            self.hip.launch_kernel_recorded(fn, args, grid, block, shared)
                            nodes_recorded += 1
                            fused_skip_names.update({
                                f"blk.{layer_idx}.z_proj", f"blk.{layer_idx}.a_proj",
                                f"blk.{layer_idx}.b_proj",
                            })
                            continue
                        except Exception as e:
                            logger.warning(
                                f"Fusão GDN falhou na captura (camada {layer_idx}): {e}. "
                                f"Usando kernels separados para esta camada."
                            )

                # Split-KV (Flash-Decoding): opt-in via VTE_ENABLE_ATTN_SPLITKV
                # -- substitui o único flash_attention_kernel (12 blocos, laço
                # serial sobre o KV cache) por 3 lançamentos (append + partial
                # dividido em chunks + reduce), usando muito mais CUs. Ver
                # split_kv_attention.py para a motivação medida.
                if seq_len == 1 and self._split_kv.enabled and node.op_type == NodeType.ATTENTION:
                    layer_idx = int(node.name.split('.')[1])
                    try:
                        # node.input_tensors = [q, k, v] com os nomes REAIS
                        # que o RoPE modificou in-place -- q_proj.output/
                        # k_proj.output pro Qwen2.5/Granite, mas q_norm.output/
                        # k_norm.output pro Qwen3.5 (tem passo de RMSNorm
                        # por-head entre a projeção e o RoPE). Passar explícito
                        # em vez de deixar o dispatcher reconstruir por
                        # convenção fixa -- ver docstring de build_launches.
                        launches = self._split_kv.build_launches(
                            layer_idx, self.tensor_mapping, self.staging_kv_offset.ptr,
                            q_name=node.input_tensors[0], k_name=node.input_tensors[1],
                            v_name=node.input_tensors[2],
                        )
                        for fn, args, grid, block, shared_mem in launches:
                            self.hip.launch_kernel_recorded(fn, args, grid, block, shared_mem)
                            nodes_recorded += 1
                        continue
                    except Exception as e:
                        logger.warning(
                            f"Split-KV falhou na captura (camada {layer_idx}): {e}. "
                            f"Usando o flash_attention_kernel original para esta camada."
                        )

                # Fusão do FFN DESATIVADA por padrão: medida empiricamente, tanto
                # a versão totalmente fundida (RMSNorm+Gate+Up+SiLU em 1 kernel)
                # quanto a versão com RMSNorm separado (2 kernels) ficaram MAIS
                # LENTAS que os 4 kernels originais (ffn_norm+gate_proj+up_proj+
                # swiglu, cada um com cache em LDS) — 12.7-13.5 tok/s fundido vs
                # 18.8 tok/s separado, no mesmo hardware/prompt. Provável causa:
                # o loop de 2 acumuladores (gate_sum/up_sum) no mesmo laço
                # aumenta a pressão de registradores por thread, reduzindo a
                # ocupância o suficiente para superar o ganho de menos round-
                # trips de VRAM. Ao contrário da fusão QKV (16 blocos, ganho
                # real), aqui o grid tem ~35 blocos e o trade-off não compensa.
                # Mantido como opt-in via VTE_ENABLE_FFN_FUSION para experimentos.
                import os as _os
                if seq_len == 1 and _os.environ.get('VTE_ENABLE_FFN_FUSION') and node.op_type == NodeType.RMSNORM and node.name.endswith('.ffn_norm'):
                    layer_idx = int(node.name.split('.')[1])
                    try:
                        launches = self._fused_ffn.build_launches(
                            layer_idx, self.tensor_mapping
                        )
                        for fn, args, grid, block, shared_mem in launches:
                            self.hip.launch_kernel_recorded(fn, args, grid, block, shared_mem)
                            nodes_recorded += 1
                        fused_skip_names.update({
                            f"blk.{layer_idx}.ffn_norm", f"blk.{layer_idx}.gate_proj",
                            f"blk.{layer_idx}.up_proj", f"blk.{layer_idx}.swiglu",
                        })
                        continue
                    except Exception as e:
                        logger.warning(
                            f"Fusão FFN falhou na captura (camada {layer_idx}): {e}. "
                            f"Usando kernels separados para esta camada."
                        )

                kernel_func = self._get_or_compile_kernel(node)

                if kernel_func is None:
                    continue

                args = self._build_kernel_args(node, seq_len)
                grid, block, shared_mem = self._calculate_launch_dims(node, seq_len)

                self.hip.launch_kernel_recorded(kernel_func, args, grid, block, shared_mem)
                nodes_recorded += 1

            # Fase 2: grava o LM Head DENTRO do mesmo grafo, só no modo
            # decode (seq_len sempre 1 aqui). O grafo de prefill não recebe
            # isso -- shapes dinâmicas de prompt não combinam com um nó de
            # LM Head fixo, e hoje o prefill em HIP Graph reaproveita o
            # próprio grafo de decode token a token (ver VTEModel.generate),
            # então este é o único ponto que precisa do LM Head capturado.
            if mode == 'decode' and self.lm_head_info is not None:
                self._capture_lm_head()
                nodes_recorded += 1

                if self.topk_info is not None:
                    self._capture_topk_reduce()
                    nodes_recorded += 1

            raw_graph = self.hip.stream_end_capture()
            graph_exec = self.hip.graph_instantiate(raw_graph)

            # O hipGraph_t "molde" não é mais necessário depois de instanciado
            # (só o hipGraphExec_t é usado nos replays); liberamos na hora para
            # não acumular recursos de GPU a cada captura.
            try:
                self.hip.graph_destroy(raw_graph)
            except Exception as cleanup_err:
                logger.warning(f"Falha ao destruir hipGraph_t intermediário de '{mode}': {cleanup_err}")

            logger.info(f"HIP Graph instanciado para '{mode}': {nodes_recorded} kernels gravados")
            return graph_exec

        except Exception as e:
            logger.error(f"Falha na captura do grafo {mode}: {e}")
            try:
                self.hip.stream_end_capture()
            except Exception:
                pass
            raise GraphCaptureError(f"Erro ao compilar HIP Graph: {e}")

    def build_decode_graph(self):
        """
        Constrói o grafo de decode (1 token por passo auto-regressivo) — capturado
        uma ÚNICA VEZ para toda a geração. Como o kv_cache_offset é lido por
        ponteiro (não escalar), o mesmo grafo é válido para qualquer posição do
        KV cache; apenas o valor em staging_kv_offset muda entre replays.
        """
        if self.decode_graph is None:
            self.decode_graph = self._capture_graph(mode='decode', seq_len=1)

    def build_prefill_graph(self, seq_len: int):
        """
        Constrói (ou reaproveita do cache) o grafo para o tamanho exato do prompt.
        Mantém no máximo MAX_CACHED_PREFILL_GRAPHS grafos simultâneos na GPU,
        destruindo o mais antigo (hipGraphExecDestroy) antes de capturar um novo,
        para não acumular recursos indefinidamente entre gerações com prompts de
        tamanhos diferentes.
        """
        if seq_len in self.prefill_graphs:
            self.prefill_graphs.move_to_end(seq_len)
            return

        while len(self.prefill_graphs) >= self.MAX_CACHED_PREFILL_GRAPHS:
            oldest_seq_len, oldest_graph = self.prefill_graphs.popitem(last=False)
            try:
                self.hip.graph_exec_destroy(oldest_graph)
                logger.info(f"HIP Graph de prefill descartado (seq_len={oldest_seq_len}) para liberar recursos da GPU.")
            except Exception as cleanup_err:
                logger.warning(f"Falha ao destruir HIP Graph de prefill (seq_len={oldest_seq_len}): {cleanup_err}")

        self.prefill_graphs[seq_len] = self._capture_graph(mode=f'prefill_{seq_len}', seq_len=seq_len)

    def _update_staging_buffers(self, token_id: int, kv_offset: int):
        """
        Copia dados novos da RAM para VRAM nos Staging Buffers (~1-2µs).
        Ocorre FORA da captura do grafo, respeitando a regra de ouro da API HIP.
        """
        tok_arr = np.array([token_id], dtype=np.int32)
        kv_arr = np.array([kv_offset], dtype=np.int32)

        self.hip.safe_memcpy_host_to_device(
            ctypes.c_void_p(self.staging_input.ptr),
            tok_arr.tobytes(),
            tag="update_input_token"
        )
        self.hip.safe_memcpy_host_to_device(
            ctypes.c_void_p(self.staging_kv_offset.ptr),
            kv_arr.tobytes(),
            tag="update_kv_offset"
        )

    def execute_prefill(self, tokens: List[int]):
        """Executa a primeira passada no modelo (processa o prompt)."""
        seq_len = len(tokens)

        self.build_prefill_graph(seq_len)

        tok_arr = np.array(tokens, dtype=np.int32)
        self.hip.safe_memcpy_host_to_device(
            ctypes.c_void_p(self.staging_input.ptr),
            tok_arr.tobytes(),
            tag="prefill_input"
        )
        self.hip.safe_memcpy_host_to_device(
            ctypes.c_void_p(self.staging_kv_offset.ptr),
            np.array([0], dtype=np.int32).tobytes(),
            tag="update_kv_offset"
        )

        self.hip.graph_launch(self.prefill_graphs[seq_len])
        self.hip.synchronize()

    def execute_decode(self, token_id: int, kv_offset: int):
        """Executa um passo auto-regressivo no grafo único de decode (replay puro)."""
        self.build_decode_graph()

        self._update_staging_buffers(token_id, kv_offset)

        self.hip.graph_launch(self.decode_graph)
        self.hip.synchronize()
