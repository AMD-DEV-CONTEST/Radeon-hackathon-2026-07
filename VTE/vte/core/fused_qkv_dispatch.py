import ctypes
import os


def layer_input_tensor_name(layer_idx: int) -> str:
    """Nome do tensor de entrada da camada (saída da camada anterior, ou o embedding para a camada 0)."""
    if layer_idx == 0:
        return "input_embeddings"
    return f"blk.{layer_idx - 1}.output"


class FusedQKVDispatcher:
    """
    Monta os argumentos/launch-dims do QKV+RoPE.

    Dois designs disponíveis:
    1. (Fase E.1, PADRÃO) Two-Pass Split-K inter-bloco: RMSNorm uma vez
       (rmsnorm_kernel) + Pass1 (32 blocos/head, cada um computa um chunk de
       K) + Pass2 (reduz as 32 parciais + RoPE). Preenche as 32 CUs da GPU —
       medido: 37.9→41.0 tok/s (+8%), validado numérica e textualmente. O
       design anterior (1 bloco/head) só usava 2-12 blocos, deixando a
       maioria das CUs ociosas (occupancy-bound, não ALU/endereçamento).
    2. (legado, opt-in via VTE_DISABLE_QKV_SPLITK) fused_norm_matmul_rope_kernel:
       1 bloco por head, mantido para regressão/debug.
    """

    def __init__(self, hip, codegen, metadata: dict, allocator=None, batch_size: int = 1):
        self.hip = hip
        self.codegen = codegen
        self.metadata = metadata or {}
        self.allocator = allocator
        self.batch_size = batch_size
        self._kernel_cache = {}
        self._scratch = None
        self.use_split_k = not bool(os.environ.get('VTE_DISABLE_QKV_SPLITK')) and allocator is not None

    def _get_kernel(self):
        if 'fused_qkv' not in self._kernel_cache:
            arch = self.hip.get_gpu_architecture()
            _, fn = self.codegen.load_kernel_safe(self.hip, 'fused_norm_matmul_rope', arch, 'fused_norm_matmul_rope_kernel')
            self._kernel_cache['fused_qkv'] = fn
        return self._kernel_cache['fused_qkv']

    def _get_splitk_kernels(self):
        if 'rmsnorm' not in self._kernel_cache:
            arch = self.hip.get_gpu_architecture()
            from vte.bridge.memory import MemoryRegion
            _, fn = self.codegen.load_kernel_safe(self.hip, 'rmsnorm', arch, 'rmsnorm_kernel')
            self._kernel_cache['rmsnorm'] = fn

            _, fn = self.codegen.load_kernel_safe(self.hip, 'split_k_qkv_pass1', arch, 'split_k_qkv_pass1_kernel')
            self._kernel_cache['pass1'] = fn

            _, fn = self.codegen.load_kernel_safe(self.hip, 'split_k_qkv_pass2', arch, 'split_k_qkv_pass2_kernel')
            self._kernel_cache['pass2'] = fn

            hidden_size = self.metadata.get('embedding_length', 1536)
            head_dim = self.metadata.get('attention.key_length', 128)
            num_q_heads = self.metadata.get('attention.head_count', 12)
            # Fase I: x_norm e o scratchpad ganham uma dimensão de batch —
            # [batch, hidden_size] e [batch, num_heads, 32, head_dim].
            self._xnorm_buf = self.allocator.allocate(hidden_size * 2 * self.batch_size, "qkv_splitk_xnorm", MemoryRegion.SCRATCH)
            self._scratch_buf = self.allocator.allocate(32 * num_q_heads * head_dim * 4 * self.batch_size, "qkv_splitk_scratch", MemoryRegion.SCRATCH)
        return self._kernel_cache['rmsnorm'], self._kernel_cache['pass1'], self._kernel_cache['pass2']

    @staticmethod
    def _resolve_ptr(tensor_mapping: dict, name: str) -> int:
        p = tensor_mapping.get(name)
        if p is None:
            return 0
        return p.ptr if hasattr(p, 'ptr') else int(p)

    def build_launches(self, layer_idx: int, tensor_mapping: dict, kv_offset_ptr: int, batch: int = 1):
        if self.use_split_k:
            return self._build_launches_splitk(layer_idx, tensor_mapping, kv_offset_ptr, batch)
        return self._build_launches_fused(layer_idx, tensor_mapping, kv_offset_ptr)

    def _build_launches_splitk(self, layer_idx: int, tensor_mapping: dict, kv_offset_ptr: int, batch: int = 1):
        """Fase E.1: RMSNorm (1x) + [Pass1, Pass2] por projeção (Q, K, V).

        Fase I: `batch` (default=1) adiciona uma dimensão de grid (Pass1:
        blockIdx.z; Pass2: blockIdx.y) e stride correspondente no x_norm/
        scratchpad/output. kv_offset_ptr já é um array de `batch` ints
        (mesmo buffer usado pelos outros kernels batch-aware).
        """
        hidden_size = self.metadata.get('embedding_length', 1536)
        head_dim = self.metadata.get('attention.key_length', 128)
        num_q_heads = self.metadata.get('attention.head_count', 12)
        num_kv_heads = self.metadata.get('attention.head_count_kv', 2)
        eps = self.metadata.get('attention.layer_norm_rms_epsilon', 1e-6)
        # 0 = NEOX/split-half (Qwen2); 1 = NORM/intercalado (Granite) --
        # confirmado em llama-model.cpp::llama_model_rope_type. Default 0
        # preserva o Qwen (a única arquitetura que não seta esta chave).
        rope_type = self.metadata.get('rope_type', 0)
        # 2 = NEOX parcial (Qwen3.5); default head_dim preserva Qwen2.5/
        # Granite bit a bit -- ver kernel_arg_builder.py::_build_rope_args.
        rotary_dim = self.metadata.get('rotary_dim', head_dim)

        x_name = layer_input_tensor_name(layer_idx)
        x_ptr = self._resolve_ptr(tensor_mapping, x_name)
        norm_w_ptr = self._resolve_ptr(tensor_mapping, f'blk.{layer_idx}.attn_norm.weight')
        cos_ptr = self._resolve_ptr(tensor_mapping, 'rope_cos')
        sin_ptr = self._resolve_ptr(tensor_mapping, 'rope_sin')

        fn_rms, fn_p1, fn_p2 = self._get_splitk_kernels()
        chunk_size = hidden_size // 32

        launches = []

        # RMSNorm única, compartilhada entre Q/K/V (evita recomputar a
        # redução 3x como o design de 1-bloco-por-head fazia). Grid.x=batch
        # (rmsnorm_kernel: blockIdx.x = row, já suporta batch nativamente).
        rms_args = [
            ctypes.c_void_p(x_ptr), ctypes.c_void_p(norm_w_ptr), ctypes.c_void_p(self._xnorm_buf.ptr),
            ctypes.c_int(hidden_size), ctypes.c_float(eps),
        ]
        launches.append((fn_rms, rms_args, (batch, 1, 1), (256, 1, 1), 0))

        specs = [
            ('q', num_q_heads, True),
            ('k', num_kv_heads, True),
            ('v', num_kv_heads, False),
        ]
        for key, num_heads, apply_rope in specs:
            w_ptr = self._resolve_ptr(tensor_mapping, f'blk.{layer_idx}.attn_{key}.weight')
            b_ptr = self._resolve_ptr(tensor_mapping, f'blk.{layer_idx}.attn_{key}.bias')
            out_ptr = self._resolve_ptr(tensor_mapping, f'blk.{layer_idx}.{key}_proj.output')

            p1_args = [
                ctypes.c_void_p(self._xnorm_buf.ptr), ctypes.c_void_p(w_ptr), ctypes.c_void_p(self._scratch_buf.ptr),
                ctypes.c_int(hidden_size), ctypes.c_int(head_dim), ctypes.c_int(num_heads),
            ]
            shared1 = chunk_size * 2  # halfs (LDS do chunk de x_norm)
            launches.append((fn_p1, p1_args, (32, num_heads, batch), (head_dim, 1, 1), shared1))

            p2_args = [
                ctypes.c_void_p(self._scratch_buf.ptr), ctypes.c_void_p(b_ptr), ctypes.c_void_p(cos_ptr),
                ctypes.c_void_p(sin_ptr), ctypes.c_void_p(out_ptr), ctypes.c_int(head_dim),
                ctypes.c_void_p(kv_offset_ptr), ctypes.c_int(1 if apply_rope else 0), ctypes.c_int(num_heads),
                ctypes.c_int(rope_type), ctypes.c_int(rotary_dim),
            ]
            launches.append((fn_p2, p2_args, (num_heads, batch, 1), (head_dim, 1, 1), 0))

        return launches

    def _build_launches_fused(self, layer_idx: int, tensor_mapping: dict, kv_offset_ptr: int):
        """Retorna lista de (kernel_fn, args, grid, block, shared_mem) para Q, K, V."""
        hidden_size = self.metadata.get('embedding_length', 1536)
        head_dim = self.metadata.get('attention.key_length', 128)
        num_q_heads = self.metadata.get('attention.head_count', 12)
        num_kv_heads = self.metadata.get('attention.head_count_kv', 2)
        eps = self.metadata.get('attention.layer_norm_rms_epsilon', 1e-6)
        rope_type = self.metadata.get('rope_type', 0)
        rotary_dim = self.metadata.get('rotary_dim', head_dim)

        x_name = layer_input_tensor_name(layer_idx)
        x_ptr = self._resolve_ptr(tensor_mapping, x_name)
        norm_w_ptr = self._resolve_ptr(tensor_mapping, f'blk.{layer_idx}.attn_norm.weight')
        cos_ptr = self._resolve_ptr(tensor_mapping, 'rope_cos')
        sin_ptr = self._resolve_ptr(tensor_mapping, 'rope_sin')

        fn = self._get_kernel()
        launches = []
        specs = [
            ('q', num_q_heads * head_dim, True),
            ('k', num_kv_heads * head_dim, True),
            ('v', num_kv_heads * head_dim, False),
        ]
        for key, out_features, apply_rope in specs:
            w_ptr = self._resolve_ptr(tensor_mapping, f'blk.{layer_idx}.attn_{key}.weight')
            b_ptr = self._resolve_ptr(tensor_mapping, f'blk.{layer_idx}.attn_{key}.bias')
            out_ptr = self._resolve_ptr(tensor_mapping, f'blk.{layer_idx}.{key}_proj.output')

            args = [
                ctypes.c_void_p(x_ptr),
                ctypes.c_void_p(norm_w_ptr),
                ctypes.c_void_p(w_ptr),
                ctypes.c_void_p(b_ptr),
                ctypes.c_void_p(cos_ptr),
                ctypes.c_void_p(sin_ptr),
                ctypes.c_void_p(out_ptr),
                ctypes.c_int(hidden_size),
                ctypes.c_int(out_features),
                ctypes.c_int(head_dim),
                ctypes.c_float(eps),
                ctypes.c_void_p(kv_offset_ptr),
                ctypes.c_int(1 if apply_rope else 0),
                ctypes.c_int(rope_type),
                ctypes.c_int(rotary_dim),
            ]
            # 1 bloco por head; 256 threads = 8 wavefronts (gfx11 wave32) fazendo
            # Split-K coalescido (nwarps=8 divide head_dim=128 em 16 iterações).
            grid = (out_features // head_dim, 1, 1)
            block = (256, 1, 1)
            launches.append((fn, args, grid, block, 0))

        return launches


class FusedFFNDispatcher:
    """
    Monta os argumentos/launch-dims para a fusão do FFN.

    Diferente da fusão QKV, o RMSNorm do FFN NÃO é fundido junto: o grid do
    Gate/Up/SiLU tem ~35 blocos (intermediate_size=8960 / 256), e recalcular
    a redução do RMSNorm (com suas ~8 barreiras __syncthreads de árvore) 35x
    se mostrou mais caro do que os round-trips de VRAM que a fusão total
    economizava (medido empiricamente: regressão de 19.3 para 13.5 tok/s).

    Design final (2 lançamentos em vez de 4):
      1. rmsnorm_kernel (já existente, 1 bloco) -> escreve em ffn_norm.output
      2. fused_gate_up_silu_kernel -> lê ffn_norm.output, calcula Gate e Up
         no mesmo laço (reaproveitando X_norm da LDS) + SiLU em registrador.

    O down_proj continua como um MatMul separado (reaproveita o
    matmul_kernel já otimizado com LDS).
    """

    def __init__(self, hip, codegen, metadata: dict):
        self.hip = hip
        self.codegen = codegen
        self.metadata = metadata or {}
        self._kernel_cache = {}

    def _get_rmsnorm_kernel(self):
        if 'ffn_rmsnorm' not in self._kernel_cache:
            arch = self.hip.get_gpu_architecture()
            _, fn = self.codegen.load_kernel_safe(self.hip, 'rmsnorm', arch, 'rmsnorm_kernel')
            self._kernel_cache['ffn_rmsnorm'] = fn
        return self._kernel_cache['ffn_rmsnorm']

    def _get_gate_up_silu_kernel(self):
        if 'fused_ffn' not in self._kernel_cache:
            arch = self.hip.get_gpu_architecture()
            _, fn = self.codegen.load_kernel_safe(self.hip, 'fused_rmsnorm_gate_up_silu', arch, 'fused_gate_up_silu_kernel')
            self._kernel_cache['fused_ffn'] = fn
        return self._kernel_cache['fused_ffn']

    @staticmethod
    def _resolve_ptr(tensor_mapping: dict, name: str) -> int:
        p = tensor_mapping.get(name)
        if p is None:
            return 0
        return p.ptr if hasattr(p, 'ptr') else int(p)

    def build_launches(self, layer_idx: int, tensor_mapping: dict, batch: int = 1):
        """Retorna lista de (kernel_fn, args, grid, block, shared_mem): [rmsnorm, gate_up_silu].

        `batch` (experimento Fase M): rmsnorm_kernel já suporta batch
        nativamente (blockIdx.x = row, basta grid.x=batch); o kernel fundido
        gate_up_silu foi estendido com blockIdx.y = batch_idx (ver template)
        -- gate_weight/up_weight são compartilhados entre as sequências do
        batch, só x_norm/output são indexados por batch_idx. batch=1
        (default) reduz exatamente ao comportamento original.
        """
        hidden_size = self.metadata.get('embedding_length', 1536)
        intermediate_size = self.metadata.get('feed_forward_length', 8960)
        eps = self.metadata.get('attention.layer_norm_rms_epsilon', 1e-6)

        x_ptr = self._resolve_ptr(tensor_mapping, f'blk.{layer_idx}.residual_1.output')
        norm_w_ptr = self._resolve_ptr(tensor_mapping, f'blk.{layer_idx}.ffn_norm.weight')
        norm_out_ptr = self._resolve_ptr(tensor_mapping, f'blk.{layer_idx}.ffn_norm.output')
        gate_w_ptr = self._resolve_ptr(tensor_mapping, f'blk.{layer_idx}.ffn_gate.weight')
        up_w_ptr = self._resolve_ptr(tensor_mapping, f'blk.{layer_idx}.ffn_up.weight')
        out_ptr = self._resolve_ptr(tensor_mapping, f'blk.{layer_idx}.swiglu.output')

        norm_fn = self._get_rmsnorm_kernel()
        norm_args = [
            ctypes.c_void_p(x_ptr),
            ctypes.c_void_p(norm_w_ptr),
            ctypes.c_void_p(norm_out_ptr),
            ctypes.c_int(hidden_size),
            ctypes.c_float(eps),
        ]
        norm_launch = (norm_fn, norm_args, (batch, 1, 1), (256, 1, 1), 0)

        gu_fn = self._get_gate_up_silu_kernel()
        gu_args = [
            ctypes.c_void_p(norm_out_ptr),
            ctypes.c_void_p(gate_w_ptr),
            ctypes.c_void_p(up_w_ptr),
            ctypes.c_void_p(out_ptr),
            ctypes.c_int(hidden_size),
            ctypes.c_int(intermediate_size),
        ]
        block_size = 256
        grid = ((intermediate_size + block_size - 1) // block_size, batch, 1)
        gu_launch = (gu_fn, gu_args, grid, (block_size, 1, 1), 0)

        return [norm_launch, gu_launch]
