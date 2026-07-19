"""
Executor de fallback com despacho real de kernels HIP.

Itera o Compute Graph em ordem topológica, compila (ou usa cache) os kernels
via hipcc para gfx1102 e os lança na GPU usando hipModuleLaunchKernel.
"""

import ctypes
import numpy as np
from typing import List, Dict, Set, Tuple
from vte.bridge.hip_runtime import HIPRuntime
from vte.bridge.memory import SlabAllocator, MemoryRegion
from vte.compiler.ir import IRGraph, IRNode, NodeType
from vte.compiler.qwen_mapper import ActivationArena
from vte.compiler.codegen import CodegenEngine
from vte.bridge.logger import get_logger
from vte.bridge.errors import HIPSafetyError

logger = get_logger(__name__)


# Bloco do GEMV coalescido: 1 bloco = 1 neurônio de saída, threads dividindo K.
GEMV_COALESCED_BLOCK = 64

# Registro (fonte única em runtime) dos pesos que ficam CRUS em Q4_K na VRAM e
# são roteados ao gemv_q4k. Preenchido pelo model no load, a partir do MESMO
# is_raw_q4k_weight() usado pelo weight_loader e pelo qwen_mapper — garantindo
# que "peso cru" e "kernel de desquant" nunca fiquem dessincronizados.
RAW_Q4K_WEIGHTS: set = set()
RAW_Q6K_WEIGHTS: set = set()
RAW_Q8_0_WEIGHTS: set = set()
RAW_Q5_0_WEIGHTS: set = set()

# Epilogue Fusion do residual: {gemv_node_name: (out_tensor, residual_tensor)}.
# O GEMV escreve direto na saída do Add e soma residual[row] no epílogo; o nó
# Add correspondente (em SKIP_ADD_NODES) é pulado no despacho.
RESIDUAL_FUSION: dict = {}
SKIP_ADD_NODES: set = set()


def build_residual_fusion(nodes) -> None:
    """
    Detecta o padrão GEMV -> Add(residual, gemv_out) e popula RESIDUAL_FUSION /
    SKIP_ADD_NODES. Convenção do grafo Qwen: Add.input[0]=residual, input[1]=
    saída do MATMUL (attn_output/down_proj). Gated por VTE_DISABLE_RESIDUAL_FUSION.
    """
    import os as _os
    RESIDUAL_FUSION.clear()
    SKIP_ADD_NODES.clear()
    if _os.environ.get('VTE_DISABLE_RESIDUAL_FUSION'):
        return
    out_producer = {}
    for n in nodes:
        if getattr(n, 'output_tensor', None):
            out_producer[n.output_tensor] = n
    for n in nodes:
        if n.op_type != NodeType.ADD:
            continue
        inputs = getattr(n, 'input_tensors', None) or []
        if len(inputs) < 2:
            continue
        residual_tensor, gemv_out = inputs[0], inputs[1]
        producer = out_producer.get(gemv_out)
        if producer is not None and producer.op_type == NodeType.MATMUL:
            RESIDUAL_FUSION[producer.name] = (n.output_tensor, residual_tensor)
            SKIP_ADD_NODES.add(n.name)


def register_raw_q4k_weights(names) -> None:
    RAW_Q4K_WEIGHTS.clear()
    RAW_Q4K_WEIGHTS.update(names)


def register_raw_q6k_weights(names) -> None:
    RAW_Q6K_WEIGHTS.clear()
    RAW_Q6K_WEIGHTS.update(names)


def register_raw_q8_0_weights(names) -> None:
    RAW_Q8_0_WEIGHTS.clear()
    RAW_Q8_0_WEIGHTS.update(names)


def register_raw_q5_0_weights(names) -> None:
    RAW_Q5_0_WEIGHTS.clear()
    RAW_Q5_0_WEIGHTS.update(names)


def _is_q4k_matmul(node: IRNode) -> bool:
    """True se o peso do MATMUL está cru em Q4_K (roteia para gemv_q4k)."""
    if node.op_type != NodeType.MATMUL:
        return False
    inputs = getattr(node, 'input_tensors', None) or []
    return len(inputs) >= 2 and inputs[1] in RAW_Q4K_WEIGHTS


def _is_q6k_matmul(node: IRNode) -> bool:
    """True se o peso do MATMUL está cru em Q6_K (roteia para gemv_q6k)."""
    if node.op_type != NodeType.MATMUL:
        return False
    inputs = getattr(node, 'input_tensors', None) or []
    return len(inputs) >= 2 and inputs[1] in RAW_Q6K_WEIGHTS


def _is_q8_0_matmul(node: IRNode) -> bool:
    """True se o peso do MATMUL está cru em Q8_0 (roteia para gemv_q8_0)."""
    if node.op_type != NodeType.MATMUL:
        return False
    inputs = getattr(node, 'input_tensors', None) or []
    return len(inputs) >= 2 and inputs[1] in RAW_Q8_0_WEIGHTS


def _is_q5_0_matmul(node: IRNode) -> bool:
    """True se o peso do MATMUL está cru em Q5_0 (roteia para gemv_q5_0)."""
    if node.op_type != NodeType.MATMUL:
        return False
    inputs = getattr(node, 'input_tensors', None) or []
    return len(inputs) >= 2 and inputs[1] in RAW_Q5_0_WEIGHTS

# Nós MATMUL roteados para o kernel GEMV coalescido (Split-K, 1 bloco/neurônio,
# leitura de peso coalescida entre lanes + redução via __shfl_down).
# Etapa B: gate/up (34.3%), depois down_proj (10%) e attn_output (5.5%) — todos
# GEMVs "puros" (sem fusão), drop-in direto de mesma ABI. O QKV fica de fora
# aqui pois vive dentro do fused_norm_matmul_rope (exige reescrever o loop
# interno com Split-K, tratado por último). O lm_head é coalescido à parte
# (roda no LMHead, fora do grafo de nós).
def _is_vectorized_matmul(node: IRNode) -> bool:
    if node.op_type != NodeType.MATMUL:
        return False
    return any(k in node.name for k in ("gate_proj", "up_proj", "down_proj", "attn_output"))


def _matmul_in_features(node: IRNode, metadata: dict) -> int:
    """in_features de um MATMUL (mesma regra do KernelArgBuilder)."""
    if "down_proj" in node.name:
        return int((metadata or {}).get('feed_forward_length', 8960))
    return int((metadata or {}).get('embedding_length', 1536))


def _coalesced_gemv_dims(node: IRNode, seq_len: int, batch: int = 1):
    """Grid/block do gemv_coalesced_kernel: grid=(out_features, m, 1), block=(64,1,1).

    m = batch*seq_len (Fase I: os kernels gemv_* já suportam essa dimensão
    linear estruturalmente — só precisam do batch real vindo do dispatcher).
    """
    out_features = node.shape[-1]
    m = batch * seq_len
    return (out_features, m, 1), (GEMV_COALESCED_BLOCK, 1, 1), 0


def _profile_category(node: IRNode) -> str:
    """Mapeia um nó para a categoria de profiling da Etapa A."""
    name = node.name
    op = node.op_type
    if op == NodeType.RMSNORM:
        return "RMSNorm"
    if op == NodeType.ROPE:
        return "RoPE"
    if op == NodeType.ATTENTION:
        return "FlashAttention"
    if op == NodeType.SWIGLU:
        return "SwiGLU"
    if op == NodeType.ADD:
        return "Residual"
    if op == NodeType.EMBEDDING:
        return "Embedding"
    if op == NodeType.MATMUL:
        if "down_proj" in name:
            return "FFN_Down"
        if "gate_proj" in name or "up_proj" in name:
            return "FFN_Gate_Up"
        if any(k in name for k in ("q_proj", "k_proj", "v_proj")):
            return "QKV_proj"
        if "attn_output" in name or "o_proj" in name:
            return "AttnOutput"
        if "lm_head" in name or "output" in name:
            return "LMHead"
        return "MatMul_other"
    if op == NodeType.CAUSAL_CONV1D:
        return "GDN_Conv1d"
    if op == NodeType.LINEAR_ATTENTION:
        return "GDN_Recurrent"
    if op == NodeType.RMSNORM_GATED:
        return "GDN_NormGated"
    if op == NodeType.PER_HEAD_RMSNORM:
        return "QK_Norm"
    if op == NodeType.SIGMOID_GATE_MUL:
        return "AttnGateMul"
    return "Other"

class ExecutionContext:
    """Mantém o estado da execução para permitir rollback seguro no caso de falhas"""
    def __init__(self):
        self.executed_nodes: Set[str] = set()
        self.intermediate_ptrs: Dict[str, int] = {}
        
    def rollback(self):
        self.intermediate_ptrs.clear()
        self.executed_nodes.clear()

from vte.core.kernel_arg_builder import KernelArgBuilder

class FallbackExecutor:
    """
    Executor DAG especializado com suporte robusto à ABI via KernelArgBuilder.
    """
    
    def __init__(self, hip: HIPRuntime, allocator: SlabAllocator, arena: ActivationArena, graph: IRGraph, tensor_mapping: dict = None, metadata: dict = None):
        self.hip = hip
        self.allocator = allocator
        self.arena = arena
        self.graph = graph
        self.tensor_mapping = tensor_mapping or {}
        self.metadata = metadata or {}
        
        self.execution_order = self._build_topological_order()
        self.context = ExecutionContext()
        self.num_layers = self.metadata.get('block_count', 28)
        
        self._arch = self.hip.get_gpu_architecture()
        self.codegen = CodegenEngine()
        self._kernel_cache = {}
        self.arg_builder = KernelArgBuilder()

        # Buffer persistente de 1 int na VRAM para o kv_cache_offset. Kernels
        # (RoPE/Attention) leem o offset por ponteiro em vez de escalar fixo,
        # permitindo reutilizar o mesmo kernel compilado/gravado sem precisar
        # de um valor "capturado" por chamada.
        self._kv_offset_buf = self.allocator.allocate(4, "kv_offset_scalar", MemoryRegion.SCRATCH)

        # Fusão Profunda: substitui os 5 kernels separados (attn_norm, q_proj,
        # k_proj, v_proj, rope) por 3 lançamentos do kernel fundido
        # (RMSNorm+MatMul+RoPE em um só), evitando os round-trips de VRAM
        # entre essas etapas. O mesmo vale para o FFN (ffn_norm, gate_proj,
        # up_proj, swiglu) fundidos em 1 lançamento; o down_proj continua
        # separado.
        from vte.core.fused_qkv_dispatch import FusedQKVDispatcher, FusedFFNDispatcher
        self._fused_qkv = FusedQKVDispatcher(self.hip, self.codegen, self.metadata, allocator=self.allocator)
        self._fused_ffn = FusedFFNDispatcher(self.hip, self.codegen, self.metadata)
        
    def _build_topological_order(self) -> List[IRNode]:
        """Kahn's Algorithm para Topological Sort garantindo dependências de dados"""
        in_degree = {name: 0 for name in self.graph.nodes}
        for node in self.graph.nodes.values():
            for out_node in node.outputs:
                if out_node in in_degree:
                    in_degree[out_node] += 1
                    
        queue = [name for name, deg in in_degree.items() if deg == 0]
        order = []
        
        while queue:
            curr = queue.pop(0)
            order.append(self.graph.nodes[curr])
            for out_node in self.graph.nodes[curr].outputs:
                if out_node in in_degree:
                    in_degree[out_node] -= 1
                    if in_degree[out_node] == 0:
                        queue.append(out_node)
                        
        if len(order) != self.graph.node_count:
            raise HIPSafetyError("Falha no Topological Sort: O Grafo IR possui dependências circulares.")
            
        return order

    def _write_input_ids(self, tokens: list):
        """
        Copia os IDs de token reais para o buffer 'input_ids' na VRAM.

        Sem isso, _execute_embedding_lookup lê o que já estiver naquele
        endereço (lixo/valores obsoletos), fazendo o modelo processar sempre
        os mesmos dados independente do prompt real — era exatamente o bug
        que fazia a geração ignorar completamente a entrada.
        """
        ptr = self.tensor_mapping.get('input_ids')
        if ptr is None:
            return
        ptr_val = ptr.ptr if hasattr(ptr, 'ptr') else ptr
        tok_arr = np.array(tokens, dtype=np.int32)
        self.hip.safe_memcpy_host_to_device(
            ctypes.c_void_p(ptr_val), tok_arr.tobytes(), tag="input_ids_update"
        )

    def _execute_embedding_lookup(self, seq_len: int):
        """
        Executa embedding lookup manualmente, ja que nao esta no grafo principal.
        """
        import ctypes
        
        # O ptr dos tokens deve estar mapeado. Em testes pode estar mockado ou vazio.
        # Aqui, vamos ler o input_embeddings direto, ou se ele for pre-injetado,
        # pular o embedding.
        token_ids_ptr = self.tensor_mapping.get('input_ids')
        embed_weight_ptr = self.tensor_mapping.get('token_embd.weight')
        output_ptr = self.tensor_mapping.get('input_embeddings')
        hidden_size = self.metadata.get('embedding_length', 1536)

        # Se os pesos do embedding não estao carregados ou ids, não conseguimos fazer o lookup.
        # Mas para o teste, o user pediu para implementarmos!
        if not embed_weight_ptr or not output_ptr:
            return

        embed_ptr_val = embed_weight_ptr.ptr if hasattr(embed_weight_ptr, 'ptr') else embed_weight_ptr
        out_ptr_val = output_ptr.ptr if hasattr(output_ptr, 'ptr') else output_ptr
        token_ids_val = token_ids_ptr.ptr if hasattr(token_ids_ptr, 'ptr') else token_ids_ptr

        # token_embd.weight cru exige dequant no lookup, não leitura FP16
        # direta: Q6_K no Qwen 1.5B (Fase D.1, tied), Q8_0 no Granite (Fase
        # 1, tied), Q4_K no Qwen 7B (token_embd separado do lm_head, ~1GB de
        # VRAM economizado ficando cru -- ver embedding_lookup_q4k.template).
        # Casa com o formato em que o tensor ficou cru na VRAM.
        if 'token_embd.weight' in RAW_Q4K_WEIGHTS:
            template = "embedding_lookup_q4k"
        elif 'token_embd.weight' in RAW_Q6K_WEIGHTS:
            template = "embedding_lookup_q6k"
        elif 'token_embd.weight' in RAW_Q8_0_WEIGHTS:
            template = "embedding_lookup_q8_0"
        else:
            template = "embedding_lookup"

        # Cria ou pega kernel de embedding_lookup
        cache_key = f"{NodeType.EMBEDDING}_{template}"
        if cache_key not in self._kernel_cache:
            try:
                module, kernel = self.codegen.load_kernel_safe(self.hip, template, self._arch, f"{template}_kernel")
                self._kernel_cache[cache_key] = kernel
            except Exception as e:
                logger.error(f"Erro compilando {template}: {e}")
                return
        else:
            kernel = self._kernel_cache[cache_key]
            
        c_seq = ctypes.c_int(seq_len)
        c_hidden = ctypes.c_int(hidden_size)
        c_embedding_scale = ctypes.c_float(self.metadata.get('embedding_scale', 1.0))

        args = [
            ctypes.c_void_p(token_ids_val),
            ctypes.c_void_p(embed_ptr_val),
            ctypes.c_void_p(out_ptr_val),
            c_seq,
            c_hidden,
            c_embedding_scale,
        ]

        # Converte para array de ponteiros
        c_args = (ctypes.c_void_p * len(args))()
        for i, arg in enumerate(args):
            c_args[i] = ctypes.cast(ctypes.byref(arg), ctypes.c_void_p)

        total_elements = seq_len * hidden_size
        block_size = 256
        grid_size = max(1, (total_elements + block_size - 1) // block_size)

        self.hip.launch_kernel(
            function=kernel,
            args=args, # launch_kernel cuida do byref
            grid=(grid_size, 1, 1),
            block=(block_size, 1, 1),
            shared_mem=0,
            expected_args=6
        )

    def _dispatch_fused_gdn_proj(self, layer_idx: int, seq_len: int):
        """Qwen3.5 Gated DeltaNet: lança qkv_proj+z_proj+a_proj+b_proj num
        único kernel (ver fused_gdn_proj.hip.template) -- as 4 partem da
        MESMA entrada (attn_norm.output); qkv/z usam pesos Q6_K crus,
        a/b usam Q8_0 crus."""
        cache_key = "fused_gdn_proj"
        if cache_key not in self._kernel_cache:
            _, fn = self.codegen.load_kernel_safe(self.hip, cache_key, self._arch, f"{cache_key}_kernel")
            self._kernel_cache[cache_key] = fn
        kernel = self._kernel_cache[cache_key]

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

        num_heads = self.metadata.get('linear_attn.num_heads', 16)
        conv_dim = self.metadata.get('linear_attn.conv_dim', 6144)
        value_dim = self.metadata.get('linear_attn.value_dim', 2048)
        for out_name, n_elem in (
            (f"blk.{layer_idx}.qkv_proj.output", conv_dim),
            (f"blk.{layer_idx}.z_proj.output", value_dim),
            (f"blk.{layer_idx}.a_proj.output", num_heads),
            (f"blk.{layer_idx}.b_proj.output", num_heads),
        ):
            if out_name not in self.tensor_mapping:
                size = max(n_elem * 2, 512)
                self.tensor_mapping[out_name] = self.arena.allocate(size)[0]
                if not hasattr(self, '_dynamic_tensors'):
                    self._dynamic_tensors = []
                self._dynamic_tensors.append(out_name)
        output_qkv_ptr = self.arg_builder._resolve_tensor_ptr(f"blk.{layer_idx}.qkv_proj.output", self.tensor_mapping, {})
        output_z_ptr = self.arg_builder._resolve_tensor_ptr(f"blk.{layer_idx}.z_proj.output", self.tensor_mapping, {})
        output_a_ptr = self.arg_builder._resolve_tensor_ptr(f"blk.{layer_idx}.a_proj.output", self.tensor_mapping, {})
        output_b_ptr = self.arg_builder._resolve_tensor_ptr(f"blk.{layer_idx}.b_proj.output", self.tensor_mapping, {})

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
        self.hip.launch_kernel(
            function=kernel, args=args,
            grid=(total_rows, 1, 1), block=(64, 1, 1), shared_mem=0,
            expected_args=len(args),
        )
        self.hip.synchronize()

    def execute_layer(self, layer_idx: int, seq_len: int = 1, kv_cache_offset: int = 0):
        """Executa uma camada completa do transformer"""
        layer_prefix = f"blk.{layer_idx}."

        offset_arr = np.array([kv_cache_offset], dtype=np.int32)
        self.hip.safe_memcpy_host_to_device(
            ctypes.c_void_p(self._kv_offset_buf.ptr), offset_arr.tobytes(), tag="kv_offset_update"
        )

        if layer_idx == 0:
            self._execute_embedding_lookup(seq_len)

        # Fusão Profunda: os nós attn_norm/q_proj/k_proj/v_proj/rope são
        # despachados como 3 lançamentos do kernel fundido QKV+RoPE quando
        # encontramos attn_norm; ffn_norm/gate_proj/up_proj/swiglu como 1
        # lançamento do kernel fundido FFN quando encontramos ffn_norm — cada
        # fusão só é disparada no ponto certo da sequência (o FFN depende de
        # residual_1.output, que só existe depois da atenção já ter rodado).
        # Só válido para seq_len==1 (VTE processa prompt e decode token a
        # token). down_proj e os ADD de residual continuam despachados
        # normalmente pelo loop principal.
        # Só monta o conjunto de "nomes escondidos atrás da fusão" quando a
        # camada REALMENTE tem pesos Q/K/V separados -- caso contrário
        # (camadas linear_attention do Qwen3.5/Gated DeltaNet) esses nomes
        # nem existem no grafo, e incluí-los aqui incondicionalmente faria
        # o "blk.N.attn_norm" real ser pulado no loop principal mesmo com a
        # tentativa de fusão desativada acima -- mesmo bug, caminho diferente.
        # Bug real encontrado ao adicionar o Qwen2.5 0.5B (draft model): esta
        # checagem só olhava attn_q.weight, mas o GGUF do 0.5B mistura
        # dtypes POR CAMADA -- metade das camadas tem attn_v.weight em Q8_0
        # (roteado cru por is_raw_q8_0_weight, que não tem restrição de nome)
        # enquanto attn_q/k/output continuam FP16 na MESMA camada. A fusão
        # disparava mesmo assim (só via attn_q livre), e o kernel fundido lia
        # attn_v cru como `__half*` puro -- V corrompido, causa raiz do
        # "!!!!!!!!" repetido na geração do draft (mesmo sintoma documentado
        # pro bug de fusão do Qwen3.5 em docs/QWEN35.md, causa diferente).
        # Checar as 4 matrizes (Q/K/V/O), não só Q.
        _attn_q_name = f"blk.{layer_idx}.attn_q.weight"
        _attn_k_name = f"blk.{layer_idx}.attn_k.weight"
        _attn_v_name = f"blk.{layer_idx}.attn_v.weight"
        _attn_o_name = f"blk.{layer_idx}.attn_output.weight"
        _raw_sets = (RAW_Q4K_WEIGHTS, RAW_Q6K_WEIGHTS, RAW_Q8_0_WEIGHTS, RAW_Q5_0_WEIGHTS)
        _qkv_fusable = (_attn_q_name in self.tensor_mapping
                        and not any(n in s for n in (_attn_q_name, _attn_k_name, _attn_v_name, _attn_o_name) for s in _raw_sets)
                        and self.metadata.get('rope_type') != 2)
        qkv_fused_names = {
            f"blk.{layer_idx}.attn_norm", f"blk.{layer_idx}.q_proj",
            f"blk.{layer_idx}.k_proj", f"blk.{layer_idx}.v_proj",
            f"blk.{layer_idx}.rope",
        } if _qkv_fusable else set()
        ffn_fused_names = {
            f"blk.{layer_idx}.ffn_norm", f"blk.{layer_idx}.gate_proj",
            f"blk.{layer_idx}.up_proj", f"blk.{layer_idx}.swiglu",
        }
        # IMPORTANTE: só incluir os nós do FFN na lista de "pular no loop" se a
        # fusão do FFN estiver realmente ativa. Caso contrário, gate_proj/
        # up_proj/swiglu seriam pulados sem NUNCA serem despachados pelo path
        # fundido — o FFN inteiro sumiria (bug pego pelo profiler da Etapa A).
        import os as _os
        _ffn_fusion_on = bool(_os.environ.get('VTE_ENABLE_FFN_FUSION'))
        # Qwen3.5 Gated DeltaNet: qkv_proj+z_proj+a_proj+b_proj fundidos.
        # IMPORTANTE (bug real encontrado e corrigido nesta sessão): este
        # conjunto precisa ser recalculado do ZERO a cada chamada de
        # execute_layer (igual qkv_fused_names/ffn_fused_names acima), NUNCA
        # via `self.context.executed_nodes` -- esse set persiste e ACUMULA
        # por TODA a geração (só é limpo uma vez, no início de generate()),
        # então qualquer checagem baseada nele ("já rodou antes?") ficava
        # permanentemente verdadeira a partir da 2a posição em diante,
        # fazendo TODOS os nós da camada (não só z/a/b_proj) serem pulados
        # sem nunca serem recalculados -- collapse total da geração a partir
        # do 2o token. `fused_names` abaixo é local/stateless (recriado a
        # cada chamada), mesmo padrão já usado e validado pelo QKV/FFN.
        _gdn_fusable = (f"blk.{layer_idx}.ssm_beta.weight" in self.tensor_mapping
                        and not _os.environ.get('VTE_DISABLE_GDN_FUSION'))
        gdn_fused_names = {
            f"blk.{layer_idx}.qkv_proj", f"blk.{layer_idx}.z_proj",
            f"blk.{layer_idx}.a_proj", f"blk.{layer_idx}.b_proj",
        } if _gdn_fusable else set()
        fused_names = qkv_fused_names | gdn_fused_names | (ffn_fused_names if _ffn_fusion_on else set())

        for node in self.execution_order:
            is_layer_node = node.name.startswith(layer_prefix)
            if not is_layer_node:
                continue

            # Epilogue Fusion: o Add do residual foi fundido no GEMV anterior.
            if node.name in SKIP_ADD_NODES:
                self.context.executed_nodes.add(node.name)
                continue

            # A fusão QKV+RoPE assume pesos Q/K/V SEPARADOS (attn_q/attn_k/
            # attn_v.weight) -- verdade pro Qwen2.5/Granite e pras camadas
            # full_attention do Qwen3.5, mas FALSO pras camadas
            # linear_attention do Qwen3.5 (Gated DeltaNet): estas têm um
            # nó também chamado "attn_norm" só que seguido de attn_qkv.weight
            # fundido (formato completamente diferente). Sem esta checagem,
            # a fusão disparava por NOME em toda camada, resolvia os pesos
            # inexistentes pra ponteiro nulo (_resolve_ptr silencioso) e —
            # pior — PULAVA o RMSNorm real da camada, deixando
            # attn_norm.output zerado e propagando zero pro resto do modelo
            # inteiro (causa raiz do "!!!!!!!!" repetido na geração real).
            #
            # rope_type==2 identifica as camadas full_attention do Qwen3.5
            # (ver metadata['rope_type'] em _load_qwen3_5_metadata) -- essas
            # têm q_norm/k_norm (RMSNorm por-head) e um gate sigmoide entre
            # q_proj/k_proj e o RoPE/atenção (Qwen3_5Attention real, ver
            # qwen3_5_compute.py) que o kernel fundido de QKV+RoPE não sabe
            # calcular. Desativado especificamente pra essas camadas -- usa
            # o pipeline próprio (nós separados) em vez do fundido.
            #
            # Qualquer projeção Q/K/V/O em RAW_Q4K/Q6K/Q8_0/Q5_0_WEIGHTS: o
            # kernel fundido lê os pesos como `__half*` puro, sem dequant
            # embutido -- roteá-los crus produziria valores errados/NaN se a
            # fusão tentasse usá-los. Sem a fusão, o despacho genérico por-nó
            # já roteia pro gemv_q4k/q6k/q8_0/q5_0 (que sabem desquantizar)
            # automaticamente. Reusa `_qkv_fusable` (calculado acima, já
            # confere as 4 projeções + rope_type) em vez de reafirmar aqui só
            # com attn_q -- antes as duas checagens podiam divergir (esta só
            # olhava Q; `_qkv_fusable`/`qkv_fused_names" olhava as 4), o que
            # deixava margem pra disparar a fusão mesmo com K/V/O crus.
            if (seq_len == 1 and node.name == f"blk.{layer_idx}.attn_norm" and _qkv_fusable):
                try:
                    prof = getattr(self.hip, '_profiler', None)
                    if prof is not None and prof.enabled:
                        prof.set_category("FusedQKV")
                    launches = self._fused_qkv.build_launches(
                        layer_idx, self.tensor_mapping, self._kv_offset_buf.ptr
                    )
                    for fn, args, grid, block, shared_mem in launches:
                        self.hip.launch_kernel(
                            function=fn, args=args, grid=grid, block=block,
                            shared_mem=shared_mem, expected_args=len(args)
                        )
                        self.hip.synchronize()
                    self.context.executed_nodes.update(qkv_fused_names)
                except Exception as e:
                    logger.error(f"Kernel Panic na fusão QKV da camada {layer_idx}: {e}")
                    self.context.rollback()
                    raise
                continue

            # Fusão qkv_proj+z_proj+a_proj+b_proj (Qwen3.5 Gated DeltaNet):
            # as 4 projeções partem da MESMA entrada (attn_norm.output) --
            # funde num único lançamento em vez de 4 (ver
            # fused_gdn_proj.hip.template). O skip de z_proj/a_proj/b_proj
            # é feito pelo check ESTÁTICO `node.name in fused_names` mais
            # abaixo (gdn_fused_names, calculado no topo desta função) --
            # não aqui, ver comentário acima sobre o bug de usar
            # `executed_nodes` (que acumula por toda a geração).
            if (seq_len == 1 and node.name == f"blk.{layer_idx}.qkv_proj"
                    and _gdn_fusable):
                try:
                    self._dispatch_fused_gdn_proj(layer_idx, seq_len)
                except Exception as e:
                    logger.error(f"Kernel Panic na fusão GDN da camada {layer_idx}: {e}")
                    self.context.rollback()
                    raise
                continue

            # Fusão do FFN desativada por padrão (regressão medida: ver nota em
            # hip_graph_executor.py). Opt-in via VTE_ENABLE_FFN_FUSION.
            import os as _os
            if seq_len == 1 and _os.environ.get('VTE_ENABLE_FFN_FUSION') and node.name == f"blk.{layer_idx}.ffn_norm":
                try:
                    launches = self._fused_ffn.build_launches(
                        layer_idx, self.tensor_mapping
                    )
                    for fn, args, grid, block, shared_mem in launches:
                        self.hip.launch_kernel(
                            function=fn, args=args, grid=grid, block=block,
                            shared_mem=shared_mem, expected_args=len(args)
                        )
                        self.hip.synchronize()
                    self.context.executed_nodes.update(ffn_fused_names)
                except Exception as e:
                    logger.error(f"Kernel Panic na fusão FFN da camada {layer_idx}: {e}")
                    self.context.rollback()
                    raise
                continue

            if seq_len == 1 and node.name in fused_names:
                continue

            # Nós originais escondidos atrás de uma fusão (mega_kernel) não são
            # despachados individualmente — mesmo comportamento do
            # HIPGraphExecutor. Hoje nenhum padrão de fusão é aplicável ao
            # Qwen2.5 (ver FusionAnalyzer), então este caminho só é exercitado
            # por grafos sintéticos/testes.
            if getattr(node, 'is_fused', False):
                continue

            try:
                self._dispatch_node(node, seq_len, kv_cache_offset)
                self.context.executed_nodes.add(node.name)
            except Exception as e:
                logger.error(f"Kernel Panic no node {node.name}: {e}")
                self.context.rollback()
                raise
                
        # Executa output_norm se for a última camada
        if layer_idx == self.metadata.get('block_count', 28) - 1:
            for node in self.execution_order:
                if node.name == "output_norm":
                    try:
                        self._dispatch_node(node, seq_len, kv_cache_offset)
                        self.context.executed_nodes.add(node.name)
                    except Exception as e:
                        logger.error(f"Kernel Panic no node output_norm: {e}")
                        raise
        
        # Sincroniza APÓS a camada completa
        self.hip.synchronize()
        
        # Cleanup de memória dinâmica APENAS se não for persistente
        # PARA DEBUG: mantemos os tensores mapeados
        # for tensor_name in self._dynamic_tensors:
        #     if tensor_name not in self.model._persistent_buffers:
        #         # Aqui não chamamos self.allocator.free(tensor_name) 
        #         # porque a Activation Arena limpa tudo no reset().
        #         # Apenas removemos do mapping para evitar uso acidental.
        #         del self.tensor_mapping[tensor_name]
        
        # Limpa rastreamento
        # self.arg_builder.clear_refs()
        # self._dynamic_tensors.clear()
            
        if self.arena._synchronized:
            logger.warning("Arena não foi usada antes do reset. Possível overhead desnecessário!")
        self.arena.reset_after_sync()
        
    def _dispatch_node(self, node: IRNode, seq_len: int, kv_cache_offset: int = 0, batch: int = 1):
        """Despacha um nó para a GPU via KernelArgBuilder.

        `batch` default=1 preserva o comportamento de produção; a Fase I
        (BatchedFallbackExecutor) passa o batch_size real.
        """
        if node.op_type in [NodeType.INPUT, NodeType.OUTPUT]:
            return  # Nós lógicos, não executam

        prof = getattr(self.hip, '_profiler', None)
        if prof is not None and prof.enabled:
            prof.set_category(_profile_category(node))
            
        # Garante alocação na arena para tensores que não foram alocados persistentemente
        out_name = node.output_tensor
        if out_name and out_name not in self.tensor_mapping:
            size = 1
            for dim in node.shape:
                if dim > 0:
                    size *= dim
                elif dim == -1:
                    size *= seq_len
            size = max(size * 2, 512)
            self.tensor_mapping[out_name] = self.arena.allocate(size)[0]
            # Rastreamos as keys adicionadas temporariamente para removê-las ao fim do ciclo
            if not hasattr(self, '_dynamic_tensors'):
                self._dynamic_tensors = []
            self._dynamic_tensors.append(out_name)
        
        # Pega ou compila kernel
        kernel = self._get_or_compile_kernel(node)
        if kernel is None:
            if node.op_type == "mega_kernel":
                logger.warning(
                    f"Nó fundido '{node.name}' não pode ser despachado: kernel de mega-fusão "
                    f"ainda não implementado (sem template/ABI mapeados). Nó ignorado."
                )
            return
            
        # Constrói argumentos com ABI correto
        args_array, strong_refs = self.arg_builder.build_args(
            node=node,
            tensor_mapping=self.tensor_mapping,
            staging_buffers=getattr(self, 'staging_buffers', {}),
            seq_len=seq_len,
            metadata=self.metadata,
            kv_offset_ptr=self._kv_offset_buf.ptr,
            batch=batch
        )

        # Calcula dimensões de lançamento
        grid, block, shared_mem = self._calculate_launch_dims(node, seq_len, batch)
        
        # Lança kernel
        try:
            self.hip.launch_kernel(
                function=kernel,
                args=args_array,
                grid=grid,
                block=block,
                shared_mem=shared_mem,
                expected_args=len(args_array)
            )
            # Sincroniza a CADA kernel individual (não só uma vez por camada
            # inteira). É aqui que o limitador de duty cycle
            # (HIPRuntime._throttle_before_dispatch/_throttle_duty_cycle) tem
            # chance de agir: sem isso, uma camada inteira (~14 kernels)
            # poderia rodar como uma única rajada contínua longa o bastante
            # para a janela de amostragem do Windows enxergar 100% de uso,
            # mesmo com o limitador ativo (ele só consegue pausar ENTRE
            # rajadas, nunca no meio de uma já em curso).
            self.hip.synchronize()
            logger.debug(f"Kernel {node.name} ({node.op_type}) lançado com {len(args_array)} args")
        except Exception as e:
            logger.error(
                f"Kernel Panic no node {node.name}: {e}\n"
                f"   Args fornecidos: {len(args_array)}\n"
                f"   Grid: {grid}, Block: {block}"
            )
            raise

    def _get_or_compile_kernel(self, node: IRNode):
        """Cache de kernels compilados"""
        cache_key = f"{node.op_type}_{node.name}"
        
        if cache_key not in self._kernel_cache:
            # Em um cenário real, usaria templates correspondentes
            template_map = {
                NodeType.RMSNORM: "rmsnorm",
                NodeType.MATMUL: "matmul",
                NodeType.ROPE: "rope",
                NodeType.ATTENTION: "flash_attention",
                NodeType.SWIGLU: "swiglu",
                NodeType.ADD: "add",
                # Gated DeltaNet (Qwen3.5 "linear_attention") -- terceira
                # cópia deste mesmo dict de despacho (as outras duas são
                # kernel_arg_builder.py::KERNEL_SIGNATURES e
                # hip_graph_executor.py::op_to_template, ambas já
                # atualizadas). Faltando aqui, _get_or_compile_kernel
                # retornava None silenciosamente pra estes 3 tipos, e
                # _dispatch_node simplesmente não fazia nada -- causa raiz
                # do conv1d.output/linear_attention.output ficarem zerados
                # no caminho FallbackExecutor (use_hip_graph=False).
                NodeType.CAUSAL_CONV1D: "causal_conv1d",
                NodeType.LINEAR_ATTENTION: "gated_delta_recurrent",
                NodeType.RMSNORM_GATED: "rmsnorm_gated",
                # Qwen3.5 full_attention: q_norm/k_norm + gate sigmoide.
                NodeType.PER_HEAD_RMSNORM: "per_head_rmsnorm",
                NodeType.SIGMOID_GATE_MUL: "sigmoid_gate_mul",
            }
            if _is_q4k_matmul(node):
                template_name = "gemv_q4k"
            elif _is_q6k_matmul(node):
                template_name = "gemv_q6k"
            elif _is_q8_0_matmul(node):
                template_name = "gemv_q8_0"
            elif _is_q5_0_matmul(node):
                template_name = "gemv_q5_0"
            elif _is_vectorized_matmul(node):
                template_name = "gemv_coalesced"
            else:
                template_name = template_map.get(node.op_type)
            if not template_name:
                return None

            logger.info(f"Compilando kernel para {node.name} ({template_name})...")
            try:
                module, function = self.codegen.load_kernel_safe(
                    self.hip, template_name, self._arch, f"{template_name}_kernel",
                    hidden_size=node.shape[-1] if node.shape else 1536,
                    tile_size=256,
                    is_mega_kernel=False
                )
                self._kernel_cache[cache_key] = function
            except Exception as e:
                logger.error(f"Falha ao compilar {node.name}: {e}")
                self._kernel_cache[cache_key] = None
                
        return self._kernel_cache[cache_key]

    def _calculate_launch_dims(self, node: IRNode, seq_len: int, batch: int = 1) -> Tuple[tuple, tuple, int]:
        """Calcula Grid, Block e Shared Memory para cada tipo de nó.

        `batch` default=1 preserva o comportamento de produção existente;
        a Fase I (Batched Decode) passa o batch_size real via
        BatchedFallbackExecutor.
        """
        block_size = 256

        if node.op_type == NodeType.MATMUL:
            # gate/up (Q4_K -> gemv_q4k) e down/attn_output (FP16 -> gemv_coalesced)
            # usam a mesma geometria: 1 bloco/neurônio, 64 threads dividindo K.
            if _is_q4k_matmul(node) or _is_q6k_matmul(node) or _is_q8_0_matmul(node) or _is_q5_0_matmul(node) or _is_vectorized_matmul(node):
                return _coalesced_gemv_dims(node, seq_len, batch)
            out_features = node.shape[-1]
            m = batch * seq_len
            grid_x = (out_features + block_size - 1) // block_size
            grid_y = m
            return (grid_x, grid_y, 1), (block_size, 1, 1), 0

        elif node.op_type == NodeType.RMSNORM:
            # blockIdx.x = row
            return (batch * seq_len, 1, 1), (block_size, 1, 1), 0

        elif node.op_type == NodeType.ATTENTION:
            # FlashDecoding: 1 bloco por (batch, q_head), head_dim threads/bloco
            # (uma dimensão de saída por thread). LDS = q_sh + red = 2*head_dim.
            num_q_heads = self.metadata.get('attention.head_count', 12)
            head_dim = self.metadata.get('attention.key_length', 128)
            shared = 2 * head_dim * 4
            return (batch, num_q_heads, 1), (head_dim, 1, 1), shared
            
        elif node.op_type == NodeType.ROPE:
            # blockIdx.y = batch_idx explícito (rope.hip.template, Fase I);
            # grid_x cobre os elementos de UMA sequência (não multiplicar
            # por batch aqui — o kernel já desloca os ponteiros por
            # batch_idx internamente).
            total_elements = seq_len
            if node.shape:
                for dim in node.shape:
                    if dim > 0:
                        total_elements *= dim
            grid_x = (total_elements + block_size - 1) // block_size
            grid_x = max(1, grid_x)
            return (grid_x, batch, 1), (block_size, 1, 1), 0

        elif node.op_type in [NodeType.SWIGLU, NodeType.ADD]:
            # swiglu_kernel/add_kernel são puramente elementwise sobre um
            # range flat — já suportam batch>1 sem mudança de kernel, desde
            # que total_elements inclua o multiplicador de batch (buffers
            # [batch, features] contíguos).
            total_elements = batch * seq_len
            if node.shape:
                for dim in node.shape:
                    if dim > 0:
                        total_elements *= dim
            grid_x = (total_elements + block_size - 1) // block_size
            grid_x = max(1, grid_x)
            return (grid_x, 1, 1), (block_size, 1, 1), 0

        elif node.op_type == NodeType.CAUSAL_CONV1D:
            # 1 thread por canal, sem __syncthreads/LDS (cada thread é
            # 100% independente) -- caso ideal pra ocupação em RDNA
            # (wavefront=64): block=64 (exatamente 1 wavefront, zero thread
            # mascarado) em vez do block_size genérico de 256, o que
            # QUADRUPLICA o número de blocos (24->96) sem mudar o total de
            # threads/trabalho -- espalha por todos os 32 CUs da RX 7600 em
            # vez de deixar metade ociosa com só 24 blocos.
            conv_dim = self.metadata.get('linear_attn.conv_dim', 6144)
            conv1d_block = 64
            grid_x = max(1, (conv_dim + conv1d_block - 1) // conv1d_block)
            return (grid_x, 1, 1), (conv1d_block, 1, 1), 0

        elif node.op_type == NodeType.LINEAR_ATTENTION:
            # 1 bloco por head, head_v_dim threads/bloco -- ver
            # gated_delta_recurrent.hip.template (early-return antes de
            # __syncthreads() exige EXATAMENTE head_v_dim threads/bloco).
            num_heads = self.metadata.get('linear_attn.num_heads', 16)
            head_v_dim = self.metadata.get('linear_attn.head_v_dim', 128)
            return (num_heads, batch, 1), (head_v_dim, 1, 1), 0

        elif node.op_type == NodeType.RMSNORM_GATED:
            # 1 linha (blockIdx.x) por HEAD, não por token.
            num_heads = self.metadata.get('linear_attn.num_heads', 16)
            head_v_dim = self.metadata.get('linear_attn.head_v_dim', 128)
            return (num_heads * batch, 1, 1), (head_v_dim, 1, 1), 0

        elif node.op_type == NodeType.PER_HEAD_RMSNORM:
            head_dim = self.metadata.get('attention.key_length', 128)
            if node.name.endswith('.q_norm'):
                num_heads = self.metadata.get('attention.head_count', 12)
            else:
                num_heads = self.metadata.get('attention.head_count_kv', 2)
            return (num_heads, 1, 1), (head_dim, 1, 1), head_dim * 4

        elif node.op_type == NodeType.SIGMOID_GATE_MUL:
            head_dim = self.metadata.get('attention.key_length', 128)
            num_heads = self.metadata.get('attention.head_count', 12)
            total = num_heads * head_dim
            grid_x = max(1, (total + block_size - 1) // block_size)
            return (grid_x, 1, 1), (block_size, 1, 1), 0

        return (1, 1, 1), (block_size, 1, 1), 0

    def _execute_rope_test(
        self,
        x_ptr: int,
        cos_ptr: int,
        sin_ptr: int,
        x_rot_ptr: int,
        seq_len: int,
        num_heads: int,
        head_dim: int
    ):
        """Executa kernel RoPE isolado para validação"""
        import ctypes
        
        # O kernel matmul testou via CodegenEngine direto, mas aqui vamos compilar
        mod, kernel = self.codegen.load_kernel_safe(self.hip, "rope", self._arch, "rope_kernel")
        
        # Monta argumentos passados por valor como ints (similar a MatMul)
        c_seq = ctypes.c_int(seq_len)
        c_heads = ctypes.c_int(num_heads)
        c_dim = ctypes.c_int(head_dim)
        
        args = [
            ctypes.c_void_p(x_ptr),
            ctypes.c_void_p(cos_ptr),
            ctypes.c_void_p(sin_ptr),
            ctypes.c_void_p(x_rot_ptr),
            c_seq,
            c_heads,
            c_dim
        ]
        
        # Grid/Block: 1 thread por elemento
        total_elements = seq_len * num_heads * head_dim
        block_size = 256
        grid_size = (total_elements + block_size - 1) // block_size
        
        self.hip.launch_kernel(
            kernel,
            grid=(grid_size, 1, 1),
            block=(block_size, 1, 1),
            args=args,
            shared_mem=0,
            expected_args=7
        )
    def _execute_attention_test(
        self,
        Q_ptr: int,
        K_ptr: int,
        V_ptr: int,
        output_ptr: int,
        seq_len: int,
        num_q_heads: int,
        num_kv_heads: int,
        head_dim: int
    ):
        """Executa kernel GQA Attention isolado para validação"""
        import ctypes
        from vte.compiler.ir import NodeType
        
        mod, kernel = self.codegen.load_kernel_safe(self.hip, "gqa_attention", self._arch, "gqa_attention_kernel")
        
        c_seq = ctypes.c_int(seq_len)
        c_q_heads = ctypes.c_int(num_q_heads)
        c_kv_heads = ctypes.c_int(num_kv_heads)
        c_dim = ctypes.c_int(head_dim)
        c_scale = ctypes.c_float(1.0 / (head_dim ** 0.5))
        
        args = [
            ctypes.c_void_p(Q_ptr),
            ctypes.c_void_p(K_ptr),
            ctypes.c_void_p(V_ptr),
            ctypes.c_void_p(output_ptr),
            c_seq,
            c_q_heads,
            c_kv_heads,
            c_dim,
            c_scale
        ]
        
        # Grid 2D: (batch, num_q_heads, 1)
        grid_size = (1, num_q_heads, 1)
        # Block 1D: (seq_len, 1, 1)
        block_size = (seq_len, 1, 1)
        
        self.hip.launch_kernel(
            kernel,
            grid=grid_size,
            block=block_size,
            args=args,
            shared_mem=0,
            expected_args=9
        )
    def _execute_pure_swiglu_activation(
        self,
        gate_ptr: int,
        up_ptr: int,
        hidden_ptr: int,
        total_elements: int
    ):
        """Executa kernel SwiGLU Elementwise isolado para validação"""
        import ctypes
        
        module, function = self.codegen.load_kernel_safe(self.hip, "swiglu", self._arch, "swiglu_kernel")
        
        c_elements = ctypes.c_int(total_elements)
        
        args = [
            ctypes.c_void_p(gate_ptr),
            ctypes.c_void_p(up_ptr),
            ctypes.c_void_p(hidden_ptr),
            c_elements
        ]
        
        block_size = 256
        grid_size = (total_elements + block_size - 1) // block_size
        
        self.hip.launch_kernel(
            kernel,
            grid=(grid_size, 1, 1),
            block=(block_size, 1, 1),
            args=args,
            shared_mem=0,
            expected_args=4
        )

    def prefill(self, input_tokens: list):
        """
        Processa o prompt token a token (seq_len=1 por passo), preenchendo o
        KV cache nas posições 0..N-1.

        Não processamos o prompt inteiro de uma vez (seq_len=N) porque os
        buffers de ativação persistentes são dimensionados para 1 posição
        (para caber na VRAM — dimensioná-los para o context_length cheio
        custaria GBs). Um prefill com seq_len=N escreveria N posições nesses
        buffers de 1 posição, causando overflow que corrompe as ativações e
        os pesos adjacentes. Processar token a token é matematicamente
        equivalente (cada token atende ao histórico via KV cache), só mais
        lento — aceitável e correto.
        """
        self.context.rollback()
        for pos, tok in enumerate(input_tokens):
            self._write_input_ids([tok])
            for layer in range(self.num_layers):
                self.execute_layer(layer, seq_len=1, kv_cache_offset=pos)

    def decode_step(self, token_id: int, current_seq_len: int):
        """
        Decodificação Auto-regressiva para 1 token.

        `current_seq_len` é a posição atual no KV cache (kv_cache_offset),
        não o número de linhas a processar — o passo de decode sempre lê e
        gera exatamente 1 token novo (seq_len=1), lendo o histórico via o
        KV cache já preenchido nas posições anteriores.
        """
        self.context.rollback()
        self._write_input_ids([token_id])
        for layer in range(self.num_layers):
            self.execute_layer(layer, seq_len=1, kv_cache_offset=current_seq_len)

Qwen25Executor = FallbackExecutor
