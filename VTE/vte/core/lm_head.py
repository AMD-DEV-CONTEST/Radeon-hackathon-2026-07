# vte/core/lm_head.py

import ctypes
from vte.compiler.ir import NodeType
from vte.compiler.qwen_mapper import MemoryRegion
from vte.core.model_config import ModelConfig

class LMHead:
    """
    Projeção final: (batch, seq, hidden_size) @ (hidden_size, vocab_size) → logits
    """
    
    def __init__(self, model, hip, allocator, tokenizer=None, logits_buffer=None, kernel_info=None):
        self.model = model
        self.hip = hip
        self.allocator = allocator
        self.tokenizer = tokenizer

        self.config = ModelConfig(model)
        self.hidden_size = self.config.hidden_size

        self.vocab_size = self._resolve_vocab_size(self.config._metadata)

        self._validate_weight_shape()

        if logits_buffer is not None:
            # Fase 2 (LM Head no HIP Graph): reaproveita o MESMO buffer já
            # alocado e usado por model.py ao capturar o LM Head dentro do
            # grafo de decode -- é o endereço que o replay realmente escreve,
            # não pode ser um segundo buffer independente.
            self.logits_buffer = logits_buffer
        else:
            # O matmul_kernel escreve a saída em FP16 (__float2half), então o
            # buffer de logits DEVE ser FP16 (2 bytes/elemento). Antes era
            # alocado/lido como FP32 (4 bytes): o host reinterpretava pares de
            # valores FP16 adjacentes como um único FP32, produzindo logits
            # completamente corrompidos (magnitude ~1e7) mesmo com o hidden state
            # correto. Logits reais (~±40) cabem folgado na faixa do FP16.
            self.logits_buffer = allocator.allocate(
                size=self.vocab_size * 2,  # FP16 (2 bytes por elemento)
                tag="logits_output",
                region=MemoryRegion.SCRATCH
            ).ptr

        # Se pré-compilado (LM Head já capturado no grafo por model.py),
        # compute_logits() reaproveita em vez de recompilar -- só é chamado
        # de fato quando o caminho eager ainda está ativo (fallback sem HIP
        # Graph, ou algum uso direto fora do loop principal de generate()).
        self._kernel_info = kernel_info

        # Fase I (Batched Decode): buffer [batch_size, vocab_size] alocado sob
        # demanda na primeira chamada de compute_logits_batch (não sabemos o
        # batch_size real até lá).
        self._logits_buffer_batch = None
        self._logits_buffer_batch_size = 0

        print(f"LMHead inicializado: vocab_size={self.vocab_size}, hidden_size={self.hidden_size}")
    
    def _resolve_vocab_size(self, metadata: dict) -> int:
        """Resolve vocab_size (focado na forma real do peso GGUF)"""
        # 1. Forma real do tensor (mais seguro para evitar mismatch de MatMul)
        tensor_info = self.model.parser.tensors.get('output.weight') or self.model.parser.tensors.get('token_embd.weight')
        emb_shape = tensor_info.get('shape') if tensor_info else None
        if emb_shape:
            return emb_shape[0]
            
        # 2. Configurações (GGUF metadata)
        vocab_size = self.config.vocab_size
        if vocab_size > 0:
            return vocab_size
            
        # 3. Tokenizer
        if self.tokenizer is not None:
            return getattr(self.tokenizer, 'vocab_size', 151936)
            
        print("Não foi possível determinar vocab_size dinamicamente. Usando fallback: 151936")
        return 151936
    
    def _validate_weight_shape(self):
        """Valida que o weight tem shape correto para evitar Mismatch/Segfault"""
        weight_name = 'output.weight' if 'output.weight' in self.model.tensor_mapping else 'token_embd.weight'
        tensor_info = self.model.parser.tensors.get(weight_name)
        weight_shape = tensor_info.get('shape') if tensor_info else None
        
        if weight_shape is None:
            raise ValueError(f"Weight shape not found for {weight_name}")
        
        expected_shape = (self.vocab_size, self.hidden_size)
        if weight_shape != expected_shape:
            raise ValueError(
                f"LM head weight shape mismatch: "
                f"expected {expected_shape}, got {weight_shape}"
            )
            
    def compute_logits(self, hidden_states_ptr: int, seq_len: int) -> int:
        """
        Computa logits para a última posição da sequência.
        
        Args:
            hidden_states_ptr: Ponteiro para (seq_len, hidden_size) FP16
            seq_len: Comprimento da sequência
        
        Returns:
            Ponteiro para logits (vocab_size,) FP32
        """
        # Pega peso do LM head (pode ser tied com embeddings!)
        lm_head_name = 'output.weight'
        lm_head_ptr = self.model.tensor_mapping.get(lm_head_name)
        if lm_head_ptr is None:
            # Tied embeddings: usa o mesmo peso do embedding
            lm_head_name = 'token_embd.weight'
            lm_head_ptr = self.model.tensor_mapping.get(lm_head_name)

        lm_head_val = lm_head_ptr.ptr if hasattr(lm_head_ptr, 'ptr') else lm_head_ptr

        # Otimização autoregressiva: só computa para a última posição (economiza 99% do compute)
        # 2 bytes por fp16 element
        last_hidden_ptr = hidden_states_ptr + (seq_len - 1) * self.hidden_size * 2

        if self._kernel_info is not None:
            # Já resolvido por model.py antes da captura do grafo (Fase 2) --
            # evita recompilar/recarregar o mesmo kernel à toa. Só chega
            # aqui de fato se o caminho de chamada não for o grafo (ex.:
            # fallback eager), já que o loop principal de generate() não
            # invoca compute_logits() quando o LM Head já está no grafo.
            kernel = self._kernel_info['kernel']
        else:
            # Fase D.1: o lm_head é o maior GEMV puro do modelo (vocab=151936 x
            # hidden=1536, ~466MB em FP16). Se o peso ficou cru em Q6_K (tied
            # embeddings, ver is_raw_q6k_weight) ou Q8_0 (tied embeddings do
            # Granite, ver is_raw_q8_0_weight), usamos o gemv_* dequant
            # in-kernel correspondente. Senão, FP16 coalescido.
            from vte.compiler.qwen_mapper import is_raw_q6k_weight
            from vte.compiler.granite_mapper import is_raw_q8_0_weight
            tensor_info = self.model.parser.tensors.get(lm_head_name, {})
            if is_raw_q6k_weight(lm_head_name, tensor_info):
                template = "gemv_q6k"
            elif is_raw_q8_0_weight(lm_head_name, tensor_info):
                template = "gemv_q8_0"
            else:
                template = "gemv_coalesced"

            mod, kernel = self.model.executor.codegen.load_kernel_safe(
                self.hip, template, self.hip.get_gpu_architecture(), f"{template}_kernel",
                hidden_size=self.hidden_size,
                tile_size=256
            )

        # Args: input, weight, output, batch, seq, in_features, out_features, bias, residual, residual_scale
        # O LM head não tem bias/residual -> ambos nullptr. O slot de
        # residual_scale é reaproveitado para aplicar o logit_scale do
        # Granite (residual=nullptr => total = dot_product * residual_scale,
        # exatamente logits/logit_scale -- ver _capture_lm_head em
        # hip_graph_executor.py para a mesma lógica e a fonte confirmada).
        logit_scale = self.model.metadata.get('logit_scale', 1.0) or 1.0
        args = [
            ctypes.c_void_p(last_hidden_ptr),
            ctypes.c_void_p(lm_head_val),
            ctypes.c_void_p(self.logits_buffer),
            ctypes.c_int(1),                    # batch
            ctypes.c_int(1),                    # seq (só última posição)
            ctypes.c_int(self.hidden_size),     # in_features
            ctypes.c_int(self.vocab_size),      # out_features
            ctypes.c_void_p(0),                 # bias (nullptr)
            ctypes.c_void_p(0),                 # residual (nullptr) — sem epilogue no lm_head
            ctypes.c_float(1.0 / logit_scale),
        ]

        # 1 bloco por neurônio de saída (vocab), 64 threads dividindo K.
        block_size = 64
        grid_size = self.vocab_size

        prof = getattr(self.hip, '_profiler', None)
        if prof is not None and prof.enabled:
            prof.set_category("LMHead")

        self.hip.launch_kernel(
            function=kernel,
            args=args,
            grid=(grid_size, 1, 1),
            block=(block_size, 1, 1),
            shared_mem=0,
            expected_args=10
        )

        return self.logits_buffer

    def compute_logits_batch(self, hidden_states_ptr: int, batch_size: int) -> int:
        """
        Computa logits para `batch_size` sequências simultaneamente.

        Args:
            hidden_states_ptr: Ponteiro para (batch_size, hidden_size) FP16 —
                cada linha já é a ÚNICA posição da sequência (decode: seq=1).
            batch_size: número de sequências no batch.

        Returns:
            Ponteiro para logits (batch_size, vocab_size) FP16.
        """
        lm_head_name = 'output.weight'
        lm_head_ptr = self.model.tensor_mapping.get(lm_head_name)
        if lm_head_ptr is None:
            lm_head_name = 'token_embd.weight'
            lm_head_ptr = self.model.tensor_mapping.get(lm_head_name)
        lm_head_val = lm_head_ptr.ptr if hasattr(lm_head_ptr, 'ptr') else lm_head_ptr

        from vte.compiler.qwen_mapper import is_raw_q6k_weight
        from vte.compiler.granite_mapper import is_raw_q8_0_weight
        tensor_info = self.model.parser.tensors.get(lm_head_name, {})
        if is_raw_q6k_weight(lm_head_name, tensor_info):
            template = "gemv_q6k"
        elif is_raw_q8_0_weight(lm_head_name, tensor_info):
            template = "gemv_q8_0"
        else:
            template = "gemv_coalesced"

        mod, kernel = self.model.executor.codegen.load_kernel_safe(
            self.hip, template, self.hip.get_gpu_architecture(), f"{template}_kernel",
            hidden_size=self.hidden_size, tile_size=256
        )

        if self._logits_buffer_batch is None or self._logits_buffer_batch_size < batch_size:
            self._logits_buffer_batch = self.allocator.allocate(
                size=self.vocab_size * batch_size * 2, tag="logits_output_batch", region=MemoryRegion.SCRATCH
            ).ptr
            self._logits_buffer_batch_size = batch_size

        logit_scale = self.model.metadata.get('logit_scale', 1.0) or 1.0
        args = [
            ctypes.c_void_p(hidden_states_ptr),
            ctypes.c_void_p(lm_head_val),
            ctypes.c_void_p(self._logits_buffer_batch),
            ctypes.c_int(batch_size),           # batch
            ctypes.c_int(1),                    # seq
            ctypes.c_int(self.hidden_size),
            ctypes.c_int(self.vocab_size),
            ctypes.c_void_p(0),
            ctypes.c_void_p(0),
            ctypes.c_float(1.0 / logit_scale),
        ]

        block_size = 64
        # grid = (out_features, batch*seq_len, 1) — mesma geometria de
        # _coalesced_gemv_dims (gemv_coalesced/gemv_q6k já suportam batch).
        self.hip.launch_kernel(
            function=kernel,
            args=args,
            grid=(self.vocab_size, batch_size, 1),
            block=(block_size, 1, 1),
            shared_mem=0,
            expected_args=10
        )

        return self._logits_buffer_batch
