"""
Construtor de Grafo de Operações para Qwen2.5-1.5B.

Este módulo constrói o grafo de EXECUÇÃO (não de memória).
Define a sequência de operações e suas dependências.
"""

from typing import Dict, List
from vte.compiler.ir import IRGraph, IRNode, NodeType
import logging

logger = logging.getLogger("VTE.ComputeGraph")

class QwenComputeGraphBuilder:
    """Constrói grafo de operações para Qwen2.5"""
    
    def __init__(self, metadata: dict):
        self.num_layers = metadata.get('block_count', 28)
        self.num_heads = metadata.get('attention.head_count', 16)
        self.num_kv_heads = metadata.get('attention.head_count_kv', 2)
        self.hidden_size = metadata.get('embedding_length', 1536)
        self.head_dim = metadata.get('attention.key_length', 96)
        # Estrutura do bloco transformer (RMSNorm -> QKV -> RoPE -> GQA ->
        # residual -> RMSNorm -> SwiGLU FFN -> residual) é a MESMA para
        # qualquer arquitetura Llama-like (Qwen2, Granite) -- só os números
        # de entrada mudam, por isso este builder é compartilhado (não
        # duplicado por arquitetura). ffn_size era literal 8960 (Qwen) em
        # 4 lugares abaixo; parametrizado para não quebrar arquiteturas com
        # FFN de outro tamanho (Granite = 8192).
        self.ffn_size = metadata.get('feed_forward_length', 8960)
        
    def build_compute_graph(self) -> IRGraph:
        """
        Constrói grafo completo de operações do Qwen2.5.
        
        Estrutura por camada:
        1. RMSNorm (attention norm)
        2. MatMul (QKV projection)
        3. RoPE (rotary embeddings)
        4. GQA Attention
        5. MatMul (output projection)
        6. Residual Add
        7. RMSNorm (FFN norm)
        8. MatMul (gate projection)
        9. MatMul (up projection)
        10. SiLU + Element-wise Mul (SwiGLU)
        11. MatMul (down projection)
        12. Residual Add
        """
        graph = IRGraph()
        
        # Input embedding
        input_node = IRNode(
            name="input",
            op_type=NodeType.INPUT,
            input_tensors=[],
            output_tensor="input_embeddings",
            shape=(1, -1, self.hidden_size),  # (batch, seq, hidden)
            dtype="f16"
        )
        graph.add_node(input_node)
        
        current_input = "input_embeddings"
        
        # Constrói cada camada
        for layer_idx in range(self.num_layers):
            layer_nodes = self._build_layer(layer_idx, current_input)
            
            for node in layer_nodes:
                graph.add_node(node)
            
            # Output da camada é input da próxima
            current_input = f"blk.{layer_idx}.output"
        
        # Output Norm
        output_norm = IRNode(
            name="output_norm",
            op_type=NodeType.RMSNORM,
            input_tensors=[current_input, "output_norm.weight"],
            output_tensor="output_norm.output",
            shape=(1, -1, self.hidden_size),
            dtype="f16"
        )
        graph.add_node(output_norm)
        
        # Output final
        output_node = IRNode(
            name="output",
            op_type=NodeType.OUTPUT,
            input_tensors=["output_norm.output"],
            output_tensor="logits",
            shape=(1, -1, self.hidden_size),
            dtype="f16"
        )
        graph.add_node(output_node)
        
        logger.info(f"Compute graph construído: {len(graph.nodes)} operações")
        return graph
    
    def _build_layer(self, layer_idx: int, input_tensor: str) -> List[IRNode]:
        """Constrói operações de uma camada"""
        nodes = []
        
        # 1. RMSNorm (attention norm)
        attn_norm = IRNode(
            name=f"blk.{layer_idx}.attn_norm",
            op_type=NodeType.RMSNORM,
            input_tensors=[input_tensor, f"blk.{layer_idx}.attn_norm.weight"],
            output_tensor=f"blk.{layer_idx}.attn_norm.output",
            shape=(1, -1, self.hidden_size),
            dtype="f16"
        )
        nodes.append(attn_norm)
        
        # 2. MatMuls (Q, K, V separados)
        q_proj = IRNode(
            name=f"blk.{layer_idx}.q_proj",
            op_type=NodeType.MATMUL,
            input_tensors=[attn_norm.output_tensor, f"blk.{layer_idx}.attn_q.weight"],
            output_tensor=f"blk.{layer_idx}.q_proj.output",
            shape=(1, -1, self.num_heads * self.head_dim),
            dtype="f16"
        )
        nodes.append(q_proj)
        
        k_proj = IRNode(
            name=f"blk.{layer_idx}.k_proj",
            op_type=NodeType.MATMUL,
            input_tensors=[attn_norm.output_tensor, f"blk.{layer_idx}.attn_k.weight"],
            output_tensor=f"blk.{layer_idx}.k_proj.output",
            shape=(1, -1, self.num_kv_heads * self.head_dim),
            dtype="f16"
        )
        nodes.append(k_proj)
        
        v_proj = IRNode(
            name=f"blk.{layer_idx}.v_proj",
            op_type=NodeType.MATMUL,
            input_tensors=[attn_norm.output_tensor, f"blk.{layer_idx}.attn_v.weight"],
            output_tensor=f"blk.{layer_idx}.v_proj.output",
            shape=(1, -1, self.num_kv_heads * self.head_dim),
            dtype="f16"
        )
        nodes.append(v_proj)
        
        # 3. RoPE (rotary embeddings)
        rope = IRNode(
            name=f"blk.{layer_idx}.rope",
            op_type=NodeType.ROPE,
            input_tensors=[
                q_proj.output_tensor,
                k_proj.output_tensor,
                "rope_freqs"  # Pré-computado (não mais usado diretamente pelo kernel, mas mantido na assinatura)
            ],
            output_tensor=f"blk.{layer_idx}.rope.output", # Dummy (in-place operation on Q and K)
            shape=(1, -1, (self.num_heads + self.num_kv_heads) * self.head_dim),
            dtype="f16"
        )
        nodes.append(rope)
        
        # 4. GQA Attention
        attention = IRNode(
            name=f"blk.{layer_idx}.attention",
            op_type=NodeType.ATTENTION,
            input_tensors=[
                q_proj.output_tensor,  # In-place modificado pelo RoPE
                k_proj.output_tensor,  # In-place modificado pelo RoPE
                v_proj.output_tensor
            ],
            output_tensor=f"blk.{layer_idx}.attention.output",
            shape=(1, -1, self.num_heads * self.head_dim),
            dtype="f16"
        )
        nodes.append(attention)
        
        # 5. MatMul (output projection)
        attn_out = IRNode(
            name=f"blk.{layer_idx}.attn_output",
            op_type=NodeType.MATMUL,
            input_tensors=[
                attention.output_tensor,
                f"blk.{layer_idx}.attn_output.weight"
            ],
            output_tensor=f"blk.{layer_idx}.attn_output.output",
            shape=(1, -1, self.hidden_size),
            dtype="f16"
        )
        nodes.append(attn_out)
        
        # 6. Residual Add
        residual1 = IRNode(
            name=f"blk.{layer_idx}.residual_1",
            op_type=NodeType.ADD,
            input_tensors=[input_tensor, attn_out.output_tensor],
            output_tensor=f"blk.{layer_idx}.residual_1.output",
            shape=(1, -1, self.hidden_size),
            dtype="f16"
        )
        nodes.append(residual1)
        
        # 7. RMSNorm (FFN norm)
        ffn_norm = IRNode(
            name=f"blk.{layer_idx}.ffn_norm",
            op_type=NodeType.RMSNORM,
            input_tensors=[
                residual1.output_tensor,
                f"blk.{layer_idx}.ffn_norm.weight"
            ],
            output_tensor=f"blk.{layer_idx}.ffn_norm.output",
            shape=(1, -1, self.hidden_size),
            dtype="f16"
        )
        nodes.append(ffn_norm)
        
        # 8. MatMul (gate projection)
        gate_proj = IRNode(
            name=f"blk.{layer_idx}.gate_proj",
            op_type=NodeType.MATMUL,
            input_tensors=[
                ffn_norm.output_tensor,
                f"blk.{layer_idx}.ffn_gate.weight"
            ],
            output_tensor=f"blk.{layer_idx}.gate_proj.output",
            shape=(1, -1, self.ffn_size),  # intermediate_size
            dtype="f16"
        )
        nodes.append(gate_proj)
        
        # 9. MatMul (up projection)
        up_proj = IRNode(
            name=f"blk.{layer_idx}.up_proj",
            op_type=NodeType.MATMUL,
            input_tensors=[
                ffn_norm.output_tensor,
                f"blk.{layer_idx}.ffn_up.weight"
            ],
            output_tensor=f"blk.{layer_idx}.up_proj.output",
            shape=(1, -1, self.ffn_size),
            dtype="f16"
        )
        nodes.append(up_proj)
        
        # 10. SwiGLU (SiLU + Element-wise Mul)
        swiglu = IRNode(
            name=f"blk.{layer_idx}.swiglu",
            op_type=NodeType.SWIGLU,
            input_tensors=[
                gate_proj.output_tensor,
                up_proj.output_tensor
            ],
            output_tensor=f"blk.{layer_idx}.swiglu.output",
            shape=(1, -1, self.ffn_size),
            dtype="f16"
        )
        nodes.append(swiglu)
        
        # 11. MatMul (down projection)
        down_proj = IRNode(
            name=f"blk.{layer_idx}.down_proj",
            op_type=NodeType.MATMUL,
            input_tensors=[
                swiglu.output_tensor,
                f"blk.{layer_idx}.ffn_down.weight"
            ],
            output_tensor=f"blk.{layer_idx}.down_proj.output",
            shape=(1, -1, self.hidden_size),
            dtype="f16"
        )
        nodes.append(down_proj)
        
        # 12. Residual Add
        residual2 = IRNode(
            name=f"blk.{layer_idx}.residual_2",
            op_type=NodeType.ADD,
            input_tensors=[residual1.output_tensor, down_proj.output_tensor],
            output_tensor=f"blk.{layer_idx}.output",
            shape=(1, -1, self.hidden_size),
            dtype="f16"
        )
        nodes.append(residual2)
        
        return nodes
