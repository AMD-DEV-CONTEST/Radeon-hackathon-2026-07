import struct
from pathlib import Path
from vte.bridge.errors import HIPSafetyError
from vte.bridge.logger import get_logger

logger = get_logger(__name__)

class GGUFParser:
    def __init__(self, model_path: str | Path):
        self.path = Path(model_path)
        self.file_size = self.path.stat().st_size
        self.tensors = {}
        self.tensor_data_offset = 0

    def parse_tensors(self, header) -> dict:
        """Extrai as informações (shape, type, offset) dos tensores do arquivo GGUF."""
        logger.info(f"Iniciando parser GGUF para extrair {header.tensor_count} tensores.")
        
        try:
            with open(self.path, "rb") as f:

                f.read(4)
                f.read(4)
                f.read(8)
                kv_count = struct.unpack("<Q", f.read(8))[0]
                
                self._skip_kv_pairs(f, kv_count)
                
                for _ in range(header.tensor_count):
                    name = self._read_string(f)
                    
                    n_dims = struct.unpack("<I", f.read(4))[0]
                    shape = []
                    for _ in range(n_dims):
                        shape.append(struct.unpack("<Q", f.read(8))[0])
                        
                    dtype = struct.unpack("<I", f.read(4))[0]
                    offset = struct.unpack("<Q", f.read(8))[0]
                    
                    shape = tuple(reversed(shape))
                    
                    self.tensors[name] = {
                        "name": name,
                        "shape": shape,
                        "dtype": dtype,
                        "offset": offset,
                        "size": self._calculate_tensor_size(shape, dtype)
                    }
                
                current_pos = f.tell()
                alignment = 32
                padding = (alignment - (current_pos % alignment)) % alignment
                self.tensor_data_offset = current_pos + padding
                
                for name, t_info in self.tensors.items():
                    t_info["offset"] = self.tensor_data_offset + t_info["offset"]
                    self._validate_tensor_bounds(t_info, self.file_size)
                    
                self._detect_tied_embeddings()
                
        except struct.error as e:
            raise HIPSafetyError(f"Erro no struct lendo tensores GGUF: {e}")
            
        return self.tensors

    def _read_string(self, f) -> str:
        length = struct.unpack("<Q", f.read(8))[0]
        if length > 65536:
             raise HIPSafetyError(f"Nome do tensor ou string excessivamente longa: {length} bytes")
        return f.read(length).decode('utf-8', errors='replace')

    def _skip_kv_pairs(self, f, kv_count: int):

        def skip_value(vtype: int):
            sizes = {0:1, 1:1, 2:2, 3:2, 4:4, 5:4, 6:4, 7:1, 10:8, 11:8, 12:8}
            if vtype in sizes:
                f.read(sizes[vtype])
            elif vtype == 8:
                self._read_string(f)
            elif vtype == 9:
                 atype = struct.unpack("<I", f.read(4))[0]
                 alen = struct.unpack("<Q", f.read(8))[0]
                 for _ in range(alen):
                     skip_value(atype)
            else:
                 raise HIPSafetyError(f"Tipo de valor GGUF não suportado no Parser: {vtype}")
                 
        for _ in range(kv_count):
            self._read_string(f)
            vtype = struct.unpack("<I", f.read(4))[0]
            skip_value(vtype)

    def _calculate_tensor_size(self, shape: tuple, dtype: int) -> int:
        """Calcula o tamanho em bytes dependendo do tipo da quantização.

        Fonte única de verdade: `ggml_types.block_size_bytes`, que reusa a
        tabela canônica `gguf.GGML_QUANT_SIZES` em vez de uma cópia
        hardcoded aqui -- essa cópia tinha um bug real (Q8_K usava 272
        bytes/bloco, o valor certo é 292) que nunca se manifestou por
        nenhum tensor Q8_K real ter sido carregado ainda. Fail-fast em
        dtype desconhecido (era um fallback silencioso `elements*2` antes
        -- a mesma classe de suposição silenciosa que corrompeu o
        carregamento do Qwen2.5 0.5B em Q5_0 até virar crash em outro
        lugar)."""
        import math
        from vte.compiler.ggml_types import block_size_bytes
        elements = math.prod(shape)
        return block_size_bytes(dtype, elements)

    def _validate_tensor_bounds(self, tensor_info: dict, file_size: int):
        """Barreira de segurança: Garante que o tensor existe fisicamente no arquivo"""
        offset = tensor_info['offset']
        size = tensor_info['size']
        
        if size < 0 or offset < 0:
            raise HIPSafetyError(f"Tensor {tensor_info['name']} com offset/size negativo.")
            
        if offset + size > file_size:
            raise HIPSafetyError(
                f"Tensor {tensor_info['name']} excede o tamanho do arquivo. "
                f"Offset: {offset}, Size: {size}, FileSize: {file_size}. "
                f"Arquivo GGUF corrompido ou malicioso."
            )

    def _detect_tied_embeddings(self):
        """Identifica Tied Embeddings (token_embd.weight == output.weight) para economizar memória"""
        if "token_embd.weight" in self.tensors and "output.weight" in self.tensors:
            t_emb = self.tensors["token_embd.weight"]
            t_out = self.tensors["output.weight"]
            
            if t_emb["offset"] == t_out["offset"]:
                logger.info("Tied Embeddings detectado. Aliasing 'output.weight' para economizar VRAM.")
                t_out["is_tied"] = True
                t_out["tied_to"] = "token_embd.weight"

    def _validate_qwen25_shapes(self, metadata: dict):
        """Valida que shapes correspondem ao Qwen2.5-1.5B (GGUF Mapeado)."""
        hidden_size = metadata.get('embedding_length', 1536)
        num_heads = 16
        num_kv_heads = 2
        head_dim = 128
        intermediate_size = 8960
        
        vocab_size = 151936
        
        expected_shapes = {
            'token_embd.weight': (vocab_size, hidden_size),
            'blk.0.attn_q.weight': (num_heads * head_dim, hidden_size),
            'blk.0.attn_k.weight': (num_kv_heads * head_dim, hidden_size),
            'blk.0.attn_v.weight': (num_kv_heads * head_dim, hidden_size),
            'blk.0.attn_output.weight': (hidden_size, num_heads * head_dim),
            'blk.0.ffn_gate.weight': (intermediate_size, hidden_size),
            'blk.0.ffn_up.weight': (intermediate_size, hidden_size),
            'blk.0.ffn_down.weight': (hidden_size, intermediate_size),
        }
        
        for tensor_name, expected_shape in expected_shapes.items():
            if tensor_name in self.tensors:
                actual_shape = self.tensors[tensor_name]['shape']
                if actual_shape != expected_shape:
                    raise HIPSafetyError(
                        f"Shape incorreto para {tensor_name}: "
                        f"{actual_shape} (esperado: {expected_shape})"
                    )
