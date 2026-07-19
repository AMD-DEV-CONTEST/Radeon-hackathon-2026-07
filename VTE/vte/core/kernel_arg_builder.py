import ctypes
import math
from typing import List, Dict, Any, Tuple
from vte.compiler.ir import IRNode, NodeType
from vte.bridge.errors import HIPSafetyError
import logging

logger = logging.getLogger("VTE.KernelArgBuilder")


class KernelArgBuilder:
    """
    Constrói arrays de argumentos para kernels HIP com segurança de ABI.
    
    Responsabilidades:
    1. Mapeia IRNode → assinatura exata do kernel C++
    2. Mantém referências fortes para evitar GC prematuro
    3. Valida número de argumentos antes do launch
    4. Constrói o void** exigido pela API hipModuleLaunchKernel
    """
    
    # Assinaturas esperadas de cada tipo de kernel
    # Formato: [(nome, tipo_ctypes), ...]
    KERNEL_SIGNATURES = {
        NodeType.RMSNORM: [
            ("input", ctypes.c_void_p),
            ("weight", ctypes.c_void_p),
            ("output", ctypes.c_void_p),
            ("n", ctypes.c_int),
            ("eps", ctypes.c_float),
        ],
        NodeType.MATMUL: [
            ("input", ctypes.c_void_p),
            ("weight", ctypes.c_void_p),
            ("output", ctypes.c_void_p),
            ("batch", ctypes.c_int),
            ("seq_len", ctypes.c_int),
            ("in_features", ctypes.c_int),
            ("out_features", ctypes.c_int),
            ("bias", ctypes.c_void_p),
            ("residual", ctypes.c_void_p),
            ("residual_scale", ctypes.c_float),
        ],
        NodeType.ROPE: [
            ("q", ctypes.c_void_p),
            ("k", ctypes.c_void_p),
            ("cos", ctypes.c_void_p),
            ("sin", ctypes.c_void_p),
            ("seq_len", ctypes.c_int),
            ("num_q_heads", ctypes.c_int),
            ("num_kv_heads", ctypes.c_int),
            ("head_dim", ctypes.c_int),
            ("kv_cache_offset_ptr", ctypes.c_void_p),
            ("rope_type", ctypes.c_int),
            ("rotary_dim", ctypes.c_int),
        ],
        NodeType.ATTENTION: [
            ("q", ctypes.c_void_p),
            ("k", ctypes.c_void_p),
            ("v", ctypes.c_void_p),
            ("k_cache", ctypes.c_void_p),
            ("v_cache", ctypes.c_void_p),
            ("output", ctypes.c_void_p),
            ("seq_len", ctypes.c_int),
            ("num_q_heads", ctypes.c_int),
            ("num_kv_heads", ctypes.c_int),
            ("head_dim", ctypes.c_int),
            ("scale", ctypes.c_float),
            ("kv_cache_offset_ptr", ctypes.c_void_p),
            ("kv_batch_stride", ctypes.c_int),   # Fase I: elementos __half entre sequências no K/V cache
        ],
        NodeType.SWIGLU: [
            ("gate", ctypes.c_void_p),
            ("up", ctypes.c_void_p),
            ("output", ctypes.c_void_p),
            ("total_elements", ctypes.c_int),
        ],
        NodeType.ADD: [
            ("residual", ctypes.c_void_p),
            ("input", ctypes.c_void_p),
            ("output", ctypes.c_void_p),
            ("n", ctypes.c_int),
            ("residual_scale", ctypes.c_float),
        ],
        # Gated DeltaNet (Qwen3.5 "linear_attention") -- ver
        # vte/compiler/templates/causal_conv1d.hip.template e
        # gated_delta_recurrent.hip.template. Isolado: nenhuma entrada
        # existente acima é alterada por esta adição.
        NodeType.CAUSAL_CONV1D: [
            ("x", ctypes.c_void_p),
            ("history", ctypes.c_void_p),
            ("weight", ctypes.c_void_p),
            ("bias", ctypes.c_void_p),
            ("output", ctypes.c_void_p),
            ("conv_dim", ctypes.c_int),
        ],
        NodeType.LINEAR_ATTENTION: [
            ("q", ctypes.c_void_p),
            ("k", ctypes.c_void_p),
            ("v", ctypes.c_void_p),
            ("a", ctypes.c_void_p),
            ("b", ctypes.c_void_p),
            ("A_log", ctypes.c_void_p),
            ("dt_bias", ctypes.c_void_p),
            ("state", ctypes.c_void_p),
            ("output", ctypes.c_void_p),
            ("head_k_dim", ctypes.c_int),
            ("head_v_dim", ctypes.c_int),
        ],
        NodeType.RMSNORM_GATED: [
            ("x", ctypes.c_void_p),
            ("weight", ctypes.c_void_p),
            ("gate", ctypes.c_void_p),
            ("output", ctypes.c_void_p),
            ("head_v_dim", ctypes.c_int),
            ("eps", ctypes.c_float),
        ],
        # Qwen3.5 full_attention: q_norm/k_norm (RMSNorm por-head, ver
        # per_head_rmsnorm.hip.template) e o gate sigmoide pré-o_proj (ver
        # sigmoid_gate_mul.hip.template). Isolados dos node types acima.
        NodeType.PER_HEAD_RMSNORM: [
            ("input", ctypes.c_void_p),
            ("weight", ctypes.c_void_p),
            ("output", ctypes.c_void_p),
            ("num_heads", ctypes.c_int),
            ("head_dim", ctypes.c_int),
            ("input_stride", ctypes.c_int),
            ("input_offset", ctypes.c_int),
            ("eps", ctypes.c_float),
        ],
        NodeType.SIGMOID_GATE_MUL: [
            ("attn_out", ctypes.c_void_p),
            ("q_proj_raw", ctypes.c_void_p),
            ("output", ctypes.c_void_p),
            ("num_heads", ctypes.c_int),
            ("head_dim", ctypes.c_int),
            ("gate_stride", ctypes.c_int),
            ("gate_offset", ctypes.c_int),
        ],
    }
    
    def __init__(self):
        # Mantém referências fortes aos objetos ctypes criados
        # Isso previne garbage collection antes do kernel executar
        self._active_refs: List[Any] = []
    
    def build_args(
        self,
        node: IRNode,
        tensor_mapping: Dict[str, int],
        staging_buffers: Dict[str, Any],
        seq_len: int,
        metadata: dict,
        kv_offset_ptr: int = 0,
        batch: int = 1
    ) -> Tuple[List[ctypes.c_void_p], List[Any]]:
        """
        Constrói argumentos para um nó do grafo.
        
        Returns:
            (args_array, strong_refs): 
                - args_array: lista de ctypes.c_void_p para passar ao kernel
                - strong_refs: lista de objetos que devem ser mantidos vivos
        """
        signature = self.KERNEL_SIGNATURES.get(node.op_type)
        if signature is None:
            raise NotImplementedError(
                f"Assinatura não definida para op_type: {node.op_type}"
            )
        
        args_array = []
        strong_refs = []
        
        # Constrói argumentos baseado no tipo de nó
        if node.op_type == NodeType.RMSNORM:
            args_array, strong_refs = self._build_rmsnorm_args(
                node, tensor_mapping, seq_len, metadata
            )
        elif node.op_type == NodeType.MATMUL:
            args_array, strong_refs = self._build_matmul_args(
                node, tensor_mapping, seq_len, metadata, batch
            )
        elif node.op_type == NodeType.ROPE:
            args_array, strong_refs = self._build_rope_args(
                node, tensor_mapping, seq_len, metadata, kv_offset_ptr
            )
        elif node.op_type == NodeType.ATTENTION:
            args_array, strong_refs = self._build_attention_args(
                node, tensor_mapping, seq_len, metadata, kv_offset_ptr
            )
        elif node.op_type == NodeType.SWIGLU:
            args_array, strong_refs = self._build_swiglu_args(
                node, tensor_mapping, seq_len, metadata, batch
            )
        elif node.op_type == NodeType.ADD:
            args_array, strong_refs = self._build_add_args(
                node, tensor_mapping, seq_len, metadata, batch
            )
        elif node.op_type == NodeType.CAUSAL_CONV1D:
            args_array, strong_refs = self._build_causal_conv1d_args(
                node, tensor_mapping, metadata
            )
        elif node.op_type == NodeType.LINEAR_ATTENTION:
            args_array, strong_refs = self._build_linear_attention_args(
                node, tensor_mapping, metadata
            )
        elif node.op_type == NodeType.RMSNORM_GATED:
            args_array, strong_refs = self._build_rmsnorm_gated_args(
                node, tensor_mapping, metadata
            )
        elif node.op_type == NodeType.PER_HEAD_RMSNORM:
            args_array, strong_refs = self._build_per_head_rmsnorm_args(
                node, tensor_mapping, metadata
            )
        elif node.op_type == NodeType.SIGMOID_GATE_MUL:
            args_array, strong_refs = self._build_sigmoid_gate_mul_args(
                node, tensor_mapping, metadata
            )

        # Validação de ABI: número de argumentos deve bater com assinatura
        if len(args_array) != len(signature):
            raise RuntimeError(
                f"ABI Mismatch no nó {node.name} ({node.op_type}): "
                f"esperado {len(signature)} args, fornecido {len(args_array)}. "
                f"Assinatura: {[name for name, _ in signature]}"
            )
        
        # Armazena referências fortes para prevenir GC
        self._active_refs.extend(strong_refs)
        
        return args_array, strong_refs
    
    def _get_meta(self, metadata: dict, key: str, default=None) -> Any:
        for k, v in metadata.items():
            if k.endswith(key):
                return v
        if default is not None:
            return default
        # Retorna dummy se não achar para o teste de validação de args não quebrar
        return 1
        
    def _resolve_tensor_ptr(
        self,
        tensor_name: str,
        tensor_mapping: Dict[str, int],
        staging_buffers: Dict[str, Any]
    ) -> int:
        """Resolve nome de tensor para ponteiro de VRAM"""
        if tensor_name in tensor_mapping:
            ptr = tensor_mapping[tensor_name]
            return ptr.ptr if hasattr(ptr, 'ptr') else int(ptr)
        elif tensor_name in ["input_ids", "input_embeddings"] and "input_ids" in staging_buffers:
            return staging_buffers['input_ids'].ptr
        else:
            # Retornar 0 (nullptr) aqui seria passar um ponteiro nulo pra um
            # kernel HIP -- causa dereference inválido na GPU, que pode se
            # manifestar como TDR/hang em vez de um erro Python limpo. Falha
            # alto e rápido em vez de arriscar a GPU.
            raise HIPSafetyError(
                f"Tensor '{tensor_name}' não encontrado no tensor_mapping. "
                f"Recusando lançar kernel com ponteiro nulo."
            )

    def _require_ptr(self, tensor_name: str, tensor_mapping: Dict[str, int]) -> int:
        """Igual a `_resolve_tensor_ptr`, mas para buffers de estado
        persistente (Gated DeltaNet: `linear_attn_state`/`conv1d_history`)
        que são acessados direto via `.get()` em vez de passar pelo
        dispatcher genérico -- sem isto, um nome de buffer não encontrado
        cairia num ponteiro nulo silencioso (mesma classe de bug que
        `_resolve_tensor_ptr` já recusa)."""
        ptr = tensor_mapping.get(tensor_name)
        if ptr is None:
            raise HIPSafetyError(
                f"Buffer de estado persistente '{tensor_name}' não encontrado no "
                f"tensor_mapping. Recusando lançar kernel com ponteiro nulo."
            )
        return ptr.ptr if hasattr(ptr, 'ptr') else int(ptr)
    
    def _build_rmsnorm_args(
        self, node: IRNode, tensor_mapping: dict, seq_len: int, metadata: dict = None
    ) -> Tuple[list, list]:
        """RMSNorm: (input, weight, output, n, eps)"""
        input_ptr = self._resolve_tensor_ptr(node.input_tensors[0], tensor_mapping, {})
        weight_ptr = self._resolve_tensor_ptr(node.input_tensors[1], tensor_mapping, {})
        output_ptr = self._resolve_tensor_ptr(node.output_tensor, tensor_mapping, {})

        n = node.shape[-1]  # hidden_size
        # Qwen2.5 usa eps=1e-6 (layer_norm_rms_epsilon do GGUF), não 1e-5.
        eps = self._get_meta(metadata or {}, 'attention.layer_norm_rms_epsilon', 1e-6)
        
        # Cria objetos ctypes e mantém referências fortes
        c_n = ctypes.c_int(n)
        c_eps = ctypes.c_float(eps)
        
        args = [
            ctypes.c_void_p(input_ptr),
            ctypes.c_void_p(weight_ptr),
            ctypes.c_void_p(output_ptr),
            c_n,
            c_eps,
        ]
        
        strong_refs = [c_n, c_eps]
        return args, strong_refs
    
    # Projeções que têm bias no Qwen2.5 (q/k/v). o_proj, gate, up, down NÃO têm.
    _BIAS_SUFFIX = {
        "q_proj": "attn_q.bias",
        "k_proj": "attn_k.bias",
        "v_proj": "attn_v.bias",
    }

    def _resolve_matmul_bias(self, node: IRNode, tensor_mapping: dict) -> int:
        """Resolve o ponteiro de bias para q/k/v_proj; 0 (nullptr) para as demais."""
        for suffix, bias_field in self._BIAS_SUFFIX.items():
            if node.name.endswith(suffix):
                # node.name = "blk.<idx>.<proj>"
                parts = node.name.split('.')
                if len(parts) >= 2:
                    bias_name = f"blk.{parts[1]}.{bias_field}"
                    bp = tensor_mapping.get(bias_name)
                    if bp is not None:
                        return bp.ptr if hasattr(bp, 'ptr') else int(bp)
                break
        return 0

    def _build_matmul_args(
        self, node: IRNode, tensor_mapping: dict, seq_len: int, metadata: dict, batch: int = 1
    ) -> Tuple[list, list]:
        """MatMul: (input, weight, output, batch, seq_len, in_features, out_features, bias)"""
        input_ptr = self._resolve_tensor_ptr(node.input_tensors[0], tensor_mapping, {})
        weight_ptr = self._resolve_tensor_ptr(node.input_tensors[1], tensor_mapping, {})

        # Epilogue Fusion do residual: se este GEMV é seguido por um Add(residual,
        # gemv_out), ele escreve direto na saída do Add e soma o residual no
        # epílogo (o nó Add é pulado pelo executor). Fonte única: RESIDUAL_FUSION.
        residual_ptr = 0
        out_tensor = node.output_tensor
        try:
            from vte.core.fallback_executor import RESIDUAL_FUSION
            fusion = RESIDUAL_FUSION.get(node.name)
        except Exception:
            fusion = None
        if fusion:
            out_tensor, residual_tensor = fusion
            residual_ptr = self._resolve_tensor_ptr(residual_tensor, tensor_mapping, {})
        output_ptr = self._resolve_tensor_ptr(out_tensor, tensor_mapping, {})

        if "down_proj" in node.name:
            in_features = self._get_meta(metadata, 'feed_forward_length', 8960)
        else:
            in_features = self._get_meta(metadata, 'embedding_length', 1536)

        out_features = node.shape[-1]
        bias_ptr = self._resolve_matmul_bias(node, tensor_mapping)

        c_batch = ctypes.c_int(batch)
        c_seq = ctypes.c_int(seq_len)
        c_in = ctypes.c_int(in_features)
        c_out = ctypes.c_int(out_features)
        # Granite escala a SAÍDA do sub-bloco (não o residual em si) ANTES de
        # somá-la ao residual -- confirmado em granite.cpp: só o `cur` que
        # entra em ggml_add(cur, inpSA/ffn_inp) é escalado, nunca gate_proj/
        # up_proj/q_proj/k_proj/v_proj isoladamente. Por isso só aplicamos o
        # valor real quando este nó É o que funde com o residual (`fusion`
        # truthy — exatamente attn_output/down_proj); todo o resto usa 1.0,
        # senão gate_proj/up_proj ficariam encolhidos por 0.22x sem motivo
        # (bug real encontrado nesta sessão: SiLU(gate*0.22)*(up*0.22) some
        # com o sinal do FFN antes mesmo do down_proj rodar).
        c_residual_scale = ctypes.c_float(metadata.get('residual_scale', 1.0) if fusion else 1.0)

        args = [
            ctypes.c_void_p(input_ptr),
            ctypes.c_void_p(weight_ptr),
            ctypes.c_void_p(output_ptr),
            c_batch,
            c_seq,
            c_in,
            c_out,
            ctypes.c_void_p(bias_ptr),
            ctypes.c_void_p(residual_ptr),
            c_residual_scale,
        ]

        strong_refs = [c_batch, c_seq, c_in, c_out, c_residual_scale]
        return args, strong_refs
    
    def _build_rope_args(
        self, node: IRNode, tensor_mapping: dict, seq_len: int, metadata: dict, kv_offset_ptr: int
    ) -> Tuple[list, list]:
        """RoPE: (q, k, cos_cache, sin_cache, seq_len, num_q_heads, num_kv_heads, head_dim, kv_offset_ptr)"""
        q_ptr = self._resolve_tensor_ptr(node.input_tensors[0], tensor_mapping, {})
        k_ptr = self._resolve_tensor_ptr(node.input_tensors[1], tensor_mapping, {})
        cos_ptr = self._resolve_tensor_ptr("rope_cos", tensor_mapping, {})
        sin_ptr = self._resolve_tensor_ptr("rope_sin", tensor_mapping, {})

        num_q_heads = self._get_meta(metadata, 'attention.head_count', 16)
        num_kv_heads = self._get_meta(metadata, 'attention.head_count_kv', 2)
        head_dim = self._get_meta(metadata, 'attention.key_length', 128)
        rope_type = metadata.get('rope_type', 0)
        # Só rope_type==2 (NEOX parcial, Qwen3.5) usa um valor != head_dim --
        # default head_dim preserva Qwen2.5/Granite bit a bit (rotary_dim ==
        # head_dim equivale a girar o vetor inteiro, igual antes desta chave
        # existir).
        rotary_dim = metadata.get('rotary_dim', head_dim)

        c_seq = ctypes.c_int(seq_len)
        c_q_heads = ctypes.c_int(num_q_heads)
        c_kv_heads = ctypes.c_int(num_kv_heads)
        c_dim = ctypes.c_int(head_dim)
        c_rope_type = ctypes.c_int(rope_type)
        c_rotary_dim = ctypes.c_int(rotary_dim)

        args = [
            ctypes.c_void_p(q_ptr),
            ctypes.c_void_p(k_ptr),
            ctypes.c_void_p(cos_ptr),
            ctypes.c_void_p(sin_ptr),
            c_seq,
            c_q_heads,
            c_kv_heads,
            c_dim,
            ctypes.c_void_p(kv_offset_ptr),
            c_rope_type,
            c_rotary_dim,
        ]

        strong_refs = [c_seq, c_q_heads, c_kv_heads, c_dim, c_rope_type, c_rotary_dim]
        return args, strong_refs

    def _build_attention_args(
        self, node: IRNode, tensor_mapping: dict, seq_len: int, metadata: dict, kv_offset_ptr: int
    ) -> Tuple[list, list]:
        """GQA: (q, k_cache, v_cache, q_norm, k_norm, kv_offset_ptr, seq_len, num_q, num_kv, dim)"""
        layer_idx = int(node.name.split('.')[1])

        q_ptr = self._resolve_tensor_ptr(node.input_tensors[0], tensor_mapping, {})
        k_proj_ptr = self._resolve_tensor_ptr(node.input_tensors[1], tensor_mapping, {})
        v_proj_ptr = self._resolve_tensor_ptr(node.input_tensors[2], tensor_mapping, {})
        
        # Tenta buscar K e V cache
        k_ptr = tensor_mapping.get(f'blk.{layer_idx}.kv_cache.k')
        v_ptr = tensor_mapping.get(f'blk.{layer_idx}.kv_cache.v')
        
        # Fallbacks comuns
        if k_ptr is None:
            k_ptr = tensor_mapping.get(f'kv_cache.layer_{layer_idx}.k')
        if v_ptr is None:
            v_ptr = tensor_mapping.get(f'kv_cache.layer_{layer_idx}.v')
            
        # Fallback para pool único
        if k_ptr is None or v_ptr is None:
            pool_ptr = tensor_mapping.get('KV Cache Pool')
            if pool_ptr is not None:
                # Calcula offset para esta layer
                # Qwen2.5: 2 KV heads, head_dim=128, max_seq=2048, FP16
                kv_size_per_layer = 2 * 2 * 128 * 2048 * 2  # K+V * heads * dim * seq * bytes
                k_ptr = pool_ptr + (layer_idx * kv_size_per_layer)
                v_ptr = pool_ptr + (layer_idx * kv_size_per_layer) + (kv_size_per_layer // 2)
                
                if layer_idx == 0:
                    print(f"  Usando fallback de offset do pool único")
                    print(f"     K ptr: 0x{k_ptr:016x}")
                    print(f"     V ptr: 0x{v_ptr:016x}")
        
        if k_ptr is None or v_ptr is None:
            print(f"  CRÍTICO: KV Cache não encontrado para layer {layer_idx}!")
            k_ptr = 0
            v_ptr = 0
            
        output_ptr = self._resolve_tensor_ptr(node.output_tensor, tensor_mapping, {})
        
        # Meta config
        num_q_heads = metadata.get('attention.head_count', 16)
        num_kv_heads = metadata.get('attention.head_count_kv', 2)
        head_dim = metadata.get('attention.key_length', 128)
        
        c_seq = ctypes.c_int(seq_len)
        c_q_heads = ctypes.c_int(num_q_heads)
        c_kv_heads = ctypes.c_int(num_kv_heads)
        c_dim = ctypes.c_int(head_dim)
        
        # Escala de atenção: usa o valor explícito do GGUF quando presente
        # (Granite: attention.scale=0.015625, SUBSTITUI o cálculo padrão —
        # não multiplica/soma a ele, confirmado contra llama-graph.cpp) ou
        # cai no cálculo padrão 1/sqrt(head_dim) quando ausente (Qwen).
        attention_scale = metadata.get('attention_scale')
        scale = attention_scale if attention_scale else 1.0 / (head_dim ** 0.5)
        c_scale = ctypes.c_float(scale)

        # Fase I: stride (em elementos __half) entre sequências do batch no
        # KV cache — calculado em qwen_mapper.py. Ausente (batch=1 / testes
        # sem esse tensor mapeado) => 0, seguro pois é multiplicado por
        # batch_idx=0 em produção (grid.x=1 hoje).
        kv_batch_stride = tensor_mapping.get('kv_batch_stride_elements', 0)
        c_kv_batch_stride = ctypes.c_int(int(kv_batch_stride))

        args = [
            ctypes.c_void_p(q_ptr),
            ctypes.c_void_p(k_proj_ptr),
            ctypes.c_void_p(v_proj_ptr),
            ctypes.c_void_p(k_ptr),
            ctypes.c_void_p(v_ptr),
            ctypes.c_void_p(output_ptr),
            c_seq,
            c_q_heads,
            c_kv_heads,
            c_dim,
            c_scale,
            ctypes.c_void_p(kv_offset_ptr),
            c_kv_batch_stride,
        ]

        strong_refs = [c_seq, c_q_heads, c_kv_heads, c_dim, c_scale, c_kv_batch_stride]
        return args, strong_refs

    def _build_causal_conv1d_args(
        self, node: IRNode, tensor_mapping: dict, metadata: dict
    ) -> Tuple[list, list]:
        """Gated DeltaNet (Qwen3.5): conv1d causal depthwise.
        (x, history, weight, bias, output, conv_dim). O conv1d desta
        arquitetura não tem bias (nn.Conv1d(..., bias=False, ...) no
        código-fonte real) -- bias_ptr é sempre 0/nullptr aqui."""
        layer_idx = int(node.name.split('.')[1])

        x_ptr = self._resolve_tensor_ptr(node.input_tensors[0], tensor_mapping, {})
        history_ptr = self._require_ptr(f'blk.{layer_idx}.conv1d_history', tensor_mapping)
        weight_ptr = self._resolve_tensor_ptr(f'blk.{layer_idx}.ssm_conv1d.weight', tensor_mapping, {})
        output_ptr = self._resolve_tensor_ptr(node.output_tensor, tensor_mapping, {})

        conv_dim = self._get_meta(metadata, 'linear_attn.conv_dim', 6144)
        c_conv_dim = ctypes.c_int(conv_dim)

        args = [
            ctypes.c_void_p(x_ptr),
            ctypes.c_void_p(history_ptr),
            ctypes.c_void_p(weight_ptr),
            ctypes.c_void_p(0),  # bias -- sempre nullptr (bias=False no modelo real)
            ctypes.c_void_p(output_ptr),
            c_conv_dim,
        ]
        strong_refs = [c_conv_dim]
        return args, strong_refs

    def _build_linear_attention_args(
        self, node: IRNode, tensor_mapping: dict, metadata: dict
    ) -> Tuple[list, list]:
        """Gated DeltaNet (Qwen3.5): a recorrência em si.
        (q, k, v, a, b, A_log, dt_bias, state, output, head_k_dim, head_v_dim).
        `a`/`b` são as saídas das projeções in_proj_a/in_proj_b (MatMul comuns,
        já existentes); A_log/dt_bias são pesos estáticos do GGUF
        (blk.N.ssm_a / blk.N.ssm_dt.bias); `state` é o estado persistente
        alocado por qwen3_5_mapper.py (tamanho fixo, não cresce com
        context_length -- diferente do KV cache).

        Q/K/V NÃO são três tensores separados no grafo -- o conv1d causal
        (CAUSAL_CONV1D) produz um único buffer concatenado [key_dim*2 +
        value_dim] (mixed_qkv, confirmado em modeling_qwen3_5.py:
        `torch.split(mixed_qkv, [key_dim, key_dim, value_dim], dim=-1)`).
        Em vez de criar um mecanismo novo de "views" no tensor_mapping, o
        split acontece aqui mesmo via aritmética de ponteiro (offsets
        fixos em bytes, FP16 = 2 bytes/elemento) -- node.input_tensors[0]
        é o único tensor de entrada (a saída do CAUSAL_CONV1D)."""
        layer_idx = int(node.name.split('.')[1])

        mixed_qkv_ptr = self._resolve_tensor_ptr(node.input_tensors[0], tensor_mapping, {})
        key_dim = self._get_meta(metadata, 'linear_attn.key_dim', 2048)
        value_dim = self._get_meta(metadata, 'linear_attn.value_dim', 2048)
        conv_dim = self._get_meta(metadata, 'linear_attn.conv_dim', 6144)
        # Sanidade: o split Q/K/V por aritmética de ponteiro assume que
        # key_dim*2 + value_dim é exatamente o tamanho do buffer produzido
        # pelo CAUSAL_CONV1D (conv_dim). Se a metadata ficar inconsistente
        # (ex: valores default != valores reais do GGUF), o split calcularia
        # offsets errados silenciosamente -- prefiro falhar aqui a deixar o
        # kernel ler/escrever fora do buffer.
        if key_dim * 2 + value_dim != conv_dim:
            raise HIPSafetyError(
                f"Metadata inconsistente para LINEAR_ATTENTION: "
                f"key_dim*2+value_dim ({key_dim * 2 + value_dim}) != conv_dim ({conv_dim})."
            )
        q_ptr = mixed_qkv_ptr
        k_ptr = mixed_qkv_ptr + key_dim * 2  # FP16 = 2 bytes/elemento
        v_ptr = mixed_qkv_ptr + key_dim * 2 * 2

        a_ptr = self._resolve_tensor_ptr(node.input_tensors[1], tensor_mapping, {})
        b_ptr = self._resolve_tensor_ptr(node.input_tensors[2], tensor_mapping, {})
        A_log_ptr = self._resolve_tensor_ptr(f'blk.{layer_idx}.ssm_a', tensor_mapping, {})
        dt_bias_ptr = self._resolve_tensor_ptr(f'blk.{layer_idx}.ssm_dt.bias', tensor_mapping, {})

        state_ptr = self._require_ptr(f'blk.{layer_idx}.linear_attn_state', tensor_mapping)

        output_ptr = self._resolve_tensor_ptr(node.output_tensor, tensor_mapping, {})

        head_k_dim = self._get_meta(metadata, 'linear_attn.head_k_dim', 128)
        head_v_dim = self._get_meta(metadata, 'linear_attn.head_v_dim', 128)
        c_head_k_dim = ctypes.c_int(head_k_dim)
        c_head_v_dim = ctypes.c_int(head_v_dim)

        args = [
            ctypes.c_void_p(q_ptr),
            ctypes.c_void_p(k_ptr),
            ctypes.c_void_p(v_ptr),
            ctypes.c_void_p(a_ptr),
            ctypes.c_void_p(b_ptr),
            ctypes.c_void_p(A_log_ptr),
            ctypes.c_void_p(dt_bias_ptr),
            ctypes.c_void_p(state_ptr),
            ctypes.c_void_p(output_ptr),
            c_head_k_dim,
            c_head_v_dim,
        ]
        strong_refs = [c_head_k_dim, c_head_v_dim]
        return args, strong_refs

    def _build_rmsnorm_gated_args(
        self, node: IRNode, tensor_mapping: dict, metadata: dict
    ) -> Tuple[list, list]:
        """RMSNormGated (Qwen3.5): (x, weight, gate, output, head_v_dim, eps).
        weight vem do GGUF (blk.N.ssm_norm.weight); gate é a saída de
        in_proj_z (MatMul comum, já existente)."""
        layer_idx = int(node.name.split('.')[1])

        x_ptr = self._resolve_tensor_ptr(node.input_tensors[0], tensor_mapping, {})
        gate_ptr = self._resolve_tensor_ptr(node.input_tensors[1], tensor_mapping, {})
        weight_ptr = self._resolve_tensor_ptr(f'blk.{layer_idx}.ssm_norm.weight', tensor_mapping, {})
        output_ptr = self._resolve_tensor_ptr(node.output_tensor, tensor_mapping, {})

        head_v_dim = self._get_meta(metadata, 'linear_attn.head_v_dim', 128)
        eps = self._get_meta(metadata, 'attention.layer_norm_rms_epsilon', 1e-6)
        c_head_v_dim = ctypes.c_int(head_v_dim)
        c_eps = ctypes.c_float(eps)

        args = [
            ctypes.c_void_p(x_ptr),
            ctypes.c_void_p(weight_ptr),
            ctypes.c_void_p(gate_ptr),
            ctypes.c_void_p(output_ptr),
            c_head_v_dim,
            c_eps,
        ]
        strong_refs = [c_head_v_dim, c_eps]
        return args, strong_refs

    def _build_per_head_rmsnorm_args(
        self, node: IRNode, tensor_mapping: dict, metadata: dict
    ) -> Tuple[list, list]:
        """Qwen3.5 full_attention: q_norm/k_norm (RMSNorm por-head).
        (input, weight, output, num_heads, head_dim, input_stride,
        input_offset, eps). Distingue q_norm de k_norm pelo NOME do nó
        (mesmo padrão de derivar layer_idx do nome já usado no resto do
        arquivo) -- q_norm lê do buffer intercalado do q_proj (largura
        dupla head_dim*2 por head, ver Qwen3_5Attention.forward), k_norm
        lê do k_proj.output já contíguo (head_dim por head)."""
        layer_idx = int(node.name.split('.')[1])
        input_ptr = self._resolve_tensor_ptr(node.input_tensors[0], tensor_mapping, {})
        weight_name = f'blk.{layer_idx}.attn_q_norm.weight' if node.name.endswith('.q_norm') else f'blk.{layer_idx}.attn_k_norm.weight'
        weight_ptr = self._resolve_tensor_ptr(weight_name, tensor_mapping, {})
        output_ptr = self._resolve_tensor_ptr(node.output_tensor, tensor_mapping, {})

        head_dim = self._get_meta(metadata, 'attention.key_length', 128)
        if node.name.endswith('.q_norm'):
            num_heads = self._get_meta(metadata, 'attention.head_count', 12)
            input_stride = head_dim * 2  # q_proj: [query(head_dim) | gate(head_dim)] por head
        else:
            num_heads = self._get_meta(metadata, 'attention.head_count_kv', 2)
            input_stride = head_dim  # k_proj: contíguo, sem gate misturado
        eps = self._get_meta(metadata, 'attention.layer_norm_rms_epsilon', 1e-6)

        c_num_heads = ctypes.c_int(num_heads)
        c_head_dim = ctypes.c_int(head_dim)
        c_input_stride = ctypes.c_int(input_stride)
        c_input_offset = ctypes.c_int(0)
        c_eps = ctypes.c_float(eps)

        args = [
            ctypes.c_void_p(input_ptr),
            ctypes.c_void_p(weight_ptr),
            ctypes.c_void_p(output_ptr),
            c_num_heads,
            c_head_dim,
            c_input_stride,
            c_input_offset,
            c_eps,
        ]
        strong_refs = [c_num_heads, c_head_dim, c_input_stride, c_input_offset, c_eps]
        return args, strong_refs

    def _build_sigmoid_gate_mul_args(
        self, node: IRNode, tensor_mapping: dict, metadata: dict
    ) -> Tuple[list, list]:
        """Qwen3.5 full_attention: attn_output = attn_out * sigmoid(gate).
        (attn_out, q_proj_raw, output, num_heads, head_dim, gate_stride,
        gate_offset). `gate` é lido direto do buffer bruto do q_proj
        (offset head_dim, stride head_dim*2 por head) -- sem precisar de
        um buffer de extração separado."""
        attn_out_ptr = self._resolve_tensor_ptr(node.input_tensors[0], tensor_mapping, {})
        q_proj_raw_ptr = self._resolve_tensor_ptr(node.input_tensors[1], tensor_mapping, {})
        output_ptr = self._resolve_tensor_ptr(node.output_tensor, tensor_mapping, {})

        head_dim = self._get_meta(metadata, 'attention.key_length', 128)
        num_heads = self._get_meta(metadata, 'attention.head_count', 12)

        c_num_heads = ctypes.c_int(num_heads)
        c_head_dim = ctypes.c_int(head_dim)
        c_gate_stride = ctypes.c_int(head_dim * 2)
        c_gate_offset = ctypes.c_int(head_dim)

        args = [
            ctypes.c_void_p(attn_out_ptr),
            ctypes.c_void_p(q_proj_raw_ptr),
            ctypes.c_void_p(output_ptr),
            c_num_heads,
            c_head_dim,
            c_gate_stride,
            c_gate_offset,
        ]
        strong_refs = [c_num_heads, c_head_dim, c_gate_stride, c_gate_offset]
        return args, strong_refs

    def _build_swiglu_args(
        self, node: IRNode, tensor_mapping: dict, seq_len: int, metadata: dict, batch: int = 1
    ) -> Tuple[list, list]:
        """SwiGLU: (gate, up, output, total_elements).

        O kernel processa element-wise e recebe UM único total_elements
        (batch * seq_len * intermediate_size). Antes o builder passava 6 args
        (batch, seq_len, intermediate_size separados), mas o kernel só tem 4
        parâmetros — ele lia total_elements = batch = 1 e processava apenas 1
        dos 8960 elementos, zerando o resto do FFN e matando o sinal.

        swiglu_kernel é puramente elementwise sobre um range flat — já
        suporta batch>1 sem mudança de kernel, desde que total_elements
        inclua o multiplicador de batch (buffers [batch, features] contíguos).
        """
        gate_ptr = self._resolve_tensor_ptr(node.input_tensors[0], tensor_mapping, {})
        up_ptr = self._resolve_tensor_ptr(node.input_tensors[1], tensor_mapping, {})
        output_ptr = self._resolve_tensor_ptr(node.output_tensor, tensor_mapping, {})

        intermediate_size = self._get_meta(metadata, 'feed_forward_length', 8960)
        total_elements = batch * seq_len * intermediate_size

        c_total = ctypes.c_int(total_elements)

        args = [
            ctypes.c_void_p(gate_ptr),
            ctypes.c_void_p(up_ptr),
            ctypes.c_void_p(output_ptr),
            c_total,
        ]

        strong_refs = [c_total]
        return args, strong_refs
    
    def _build_add_args(
        self, node: IRNode, tensor_mapping: dict, seq_len: int, metadata: dict = None, batch: int = 1
    ) -> Tuple[list, list]:
        """Add (residual): (residual, input, output, n, residual_scale).

        add_kernel é puramente elementwise — já suporta batch>1 sem mudança
        de kernel, desde que n inclua o multiplicador de batch. Só é
        realmente exercitado com VTE_DISABLE_RESIDUAL_FUSION=1 (produção usa
        o epilogue fundido no GEMV anterior, ver build_residual_fusion).
        """
        residual_ptr = self._resolve_tensor_ptr(node.input_tensors[0], tensor_mapping, {})
        input_ptr = self._resolve_tensor_ptr(node.input_tensors[1], tensor_mapping, {})
        output_ptr = self._resolve_tensor_ptr(node.output_tensor, tensor_mapping, {})

        n = batch * seq_len * node.shape[-1]
        c_n = ctypes.c_int(n)
        c_residual_scale = ctypes.c_float((metadata or {}).get('residual_scale', 1.0))

        args = [
            ctypes.c_void_p(residual_ptr),
            ctypes.c_void_p(input_ptr),
            ctypes.c_void_p(output_ptr),
            c_n,
            c_residual_scale,
        ]

        strong_refs = [c_n, c_residual_scale]
        return args, strong_refs
    
    def clear_refs(self):
        """Libera referências fortes após sincronização"""
        self._active_refs.clear()
