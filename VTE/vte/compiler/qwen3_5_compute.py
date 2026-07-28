"""
Construtor de Grafo de Operações para Qwen 3.5 2B -- arquitetura HÍBRIDA.

Diferente de QwenComputeGraphBuilder (vte/compiler/qwen_compute.py, NÃO
tocado por este arquivo -- isolamento pedido explicitamente), aqui cada
camada tem uma sequência de nós DIFERENTE dependendo do seu tipo real
(`layer_types` do config.json, confirmado: 6 camadas `full_attention` nos
índices fixos 3,7,11,15,19,23; as outras 18 são `linear_attention`/Gated
DeltaNet). Não é um "a cada N genérico" -- os índices são hardcoded porque
é exatamente isso que o modelo real usa.
"""
from typing import Dict, List
from vte.compiler.ir import IRGraph, IRNode, NodeType
from vte.compiler.qwen3_5_mapper import (
    QWEN35_FULL_ATTENTION_LAYERS,
    QWEN35_DEFAULT_LAYERS,
    QWEN35_DEFAULT_HEAD_COUNT,
    QWEN35_DEFAULT_HEAD_COUNT_KV,
    QWEN35_DEFAULT_HEAD_DIM,
    QWEN35_DEFAULT_FFN,
    QWEN35_LINEAR_NUM_HEADS,
    QWEN35_LINEAR_HEAD_K_DIM,
    QWEN35_LINEAR_HEAD_V_DIM,
    QWEN35_LINEAR_KEY_DIM,
    QWEN35_LINEAR_VALUE_DIM,
    QWEN35_CONV_DIM,
    is_full_attention_layer,
)
import logging

logger = logging.getLogger("VTE.Qwen35ComputeGraph")


class Qwen3_5ComputeGraphBuilder:
    """Constrói o grafo de operações do Qwen 3.5, ramificando por camada."""

    def __init__(self, metadata: dict):
        self.num_layers = metadata.get('block_count', QWEN35_DEFAULT_LAYERS)
        self.num_heads = metadata.get('attention.head_count', QWEN35_DEFAULT_HEAD_COUNT)
        self.num_kv_heads = metadata.get('attention.head_count_kv', QWEN35_DEFAULT_HEAD_COUNT_KV)
        self.hidden_size = metadata.get('embedding_length', 2048)
        self.head_dim = metadata.get('attention.key_length', QWEN35_DEFAULT_HEAD_DIM)
        self.ffn_size = metadata.get('feed_forward_length', QWEN35_DEFAULT_FFN)

    def build_compute_graph(self) -> IRGraph:
        graph = IRGraph()

        input_node = IRNode(
            name="input", op_type=NodeType.INPUT, input_tensors=[],
            output_tensor="input_embeddings", shape=(1, -1, self.hidden_size), dtype="f16",
        )
        graph.add_node(input_node)

        current_input = "input_embeddings"
        for layer_idx in range(self.num_layers):
            if is_full_attention_layer(layer_idx):
                layer_nodes = self._build_full_attention_layer(layer_idx, current_input)
            else:
                layer_nodes = self._build_linear_attention_layer(layer_idx, current_input)
            for node in layer_nodes:
                graph.add_node(node)
            current_input = f"blk.{layer_idx}.output"

        output_norm = IRNode(
            name="output_norm", op_type=NodeType.RMSNORM,
            input_tensors=[current_input, "output_norm.weight"],
            output_tensor="output_norm.output", shape=(1, -1, self.hidden_size), dtype="f16",
        )
        graph.add_node(output_norm)

        output_node = IRNode(
            name="output", op_type=NodeType.OUTPUT, input_tensors=["output_norm.output"],
            output_tensor="logits", shape=(1, -1, self.hidden_size), dtype="f16",
        )
        graph.add_node(output_node)

        logger.info(f"Compute graph (Qwen3.5 híbrido) construído: {len(graph.nodes)} operações "
                    f"({len(QWEN35_FULL_ATTENTION_LAYERS)} camadas full_attention, "
                    f"{self.num_layers - len(QWEN35_FULL_ATTENTION_LAYERS)} linear_attention)")
        return graph

    def _build_full_attention_layer(self, layer_idx: int, input_tensor: str) -> List[IRNode]:
        """RMSNorm -> {q_proj(largura DUPLA), k_proj, v_proj} -> {q_norm,
        k_norm} (RMSNorm por-head) -> RoPE -> Attention -> gate sigmoide ->
        attn_output -> residual -> RMSNorm -> Gate/Up -> SwiGLU -> down_proj
        -> residual.

        Achado real (não documentação de terceiros): Qwen3_5Attention
        real (modeling_qwen3_5.py) NÃO é um Llama-attention comum --
        q_proj tem largura `num_heads*head_dim*2` (confirmado no GGUF:
        attn_q.weight out_features=4096, não 2048), dividida (torch.chunk)
        em [query(head_dim) | gate(head_dim)] POR HEAD (intercalado, não
        metade-metade do buffer inteiro). query_states/key_states passam
        por RMSNorm por-head (q_norm/k_norm, pesos blk.N.attn_q_norm/
        attn_k_norm.weight) ANTES do RoPE -- diferente de Qwen2.5/Granite,
        que não têm esse passo. Depois da atenção, a saída é multiplicada
        por sigmoid(gate) antes do o_proj. Sem isso, a saída da camada
        ficava ~9x maior que a referência real (Fase 0) e sem NaN mas
        numericamente errada.

        Nomes de norm: o GGUF do Qwen3.5 usa `attn_norm`/`post_attention_norm`
        (não `ffn_norm` como Qwen2.5/Granite) -- confirmado via gguf.GGUFReader
        na camada 3 real."""
        nodes = []

        attn_norm = IRNode(
            name=f"blk.{layer_idx}.attn_norm", op_type=NodeType.RMSNORM,
            input_tensors=[input_tensor, f"blk.{layer_idx}.attn_norm.weight"],
            output_tensor=f"blk.{layer_idx}.attn_norm.output",
            shape=(1, -1, self.hidden_size), dtype="f16",
        )
        nodes.append(attn_norm)

        # Largura DUPLA (query + gate intercalados por head, ver docstring
        # da função) -- não self.num_heads*self.head_dim.
        q_proj = IRNode(
            name=f"blk.{layer_idx}.q_proj", op_type=NodeType.MATMUL,
            input_tensors=[attn_norm.output_tensor, f"blk.{layer_idx}.attn_q.weight"],
            output_tensor=f"blk.{layer_idx}.q_proj.output",
            shape=(1, -1, self.num_heads * self.head_dim * 2), dtype="f16",
        )
        nodes.append(q_proj)

        k_proj = IRNode(
            name=f"blk.{layer_idx}.k_proj", op_type=NodeType.MATMUL,
            input_tensors=[attn_norm.output_tensor, f"blk.{layer_idx}.attn_k.weight"],
            output_tensor=f"blk.{layer_idx}.k_proj.output",
            shape=(1, -1, self.num_kv_heads * self.head_dim), dtype="f16",
        )
        nodes.append(k_proj)

        v_proj = IRNode(
            name=f"blk.{layer_idx}.v_proj", op_type=NodeType.MATMUL,
            input_tensors=[attn_norm.output_tensor, f"blk.{layer_idx}.attn_v.weight"],
            output_tensor=f"blk.{layer_idx}.v_proj.output",
            shape=(1, -1, self.num_kv_heads * self.head_dim), dtype="f16",
        )
        nodes.append(v_proj)

        # q_norm/k_norm: RMSNorm por-head, extraem a parte "query" do
        # buffer intercalado do q_proj (o gate fica pra depois, lido
        # direto do q_proj.output cru em SIGMOID_GATE_MUL) e escrevem em
        # buffers CONTÍGUOS -- formato que o kernel de RoPE já espera, sem
        # nenhuma mudança nele.
        q_norm = IRNode(
            name=f"blk.{layer_idx}.q_norm", op_type=NodeType.PER_HEAD_RMSNORM,
            input_tensors=[q_proj.output_tensor, f"blk.{layer_idx}.attn_q_norm.weight"],
            output_tensor=f"blk.{layer_idx}.q_norm.output",
            shape=(1, -1, self.num_heads * self.head_dim), dtype="f16",
        )
        nodes.append(q_norm)

        k_norm = IRNode(
            name=f"blk.{layer_idx}.k_norm", op_type=NodeType.PER_HEAD_RMSNORM,
            input_tensors=[k_proj.output_tensor, f"blk.{layer_idx}.attn_k_norm.weight"],
            output_tensor=f"blk.{layer_idx}.k_norm.output",
            shape=(1, -1, self.num_kv_heads * self.head_dim), dtype="f16",
        )
        nodes.append(k_norm)

        # RoPE modifica q_norm.output/k_norm.output IN-PLACE (mesmo padrão
        # já usado pro Qwen2.5/Granite -- rope.output nominal não é escrito
        # de verdade, ver rope.hip.template).
        rope = IRNode(
            name=f"blk.{layer_idx}.rope", op_type=NodeType.ROPE,
            input_tensors=[q_norm.output_tensor, k_norm.output_tensor, "rope_freqs"],
            output_tensor=f"blk.{layer_idx}.rope.output",
            shape=(1, -1, (self.num_heads + self.num_kv_heads) * self.head_dim), dtype="f16",
        )
        nodes.append(rope)

        attention = IRNode(
            name=f"blk.{layer_idx}.attention", op_type=NodeType.ATTENTION,
            input_tensors=[q_norm.output_tensor, k_norm.output_tensor, v_proj.output_tensor],
            output_tensor=f"blk.{layer_idx}.attention.output",
            shape=(1, -1, self.num_heads * self.head_dim), dtype="f16",
        )
        nodes.append(attention)

        # attn_output_real = attention.output * sigmoid(gate), onde `gate`
        # é lido direto do q_proj.output cru (offset head_dim, stride
        # head_dim*2 por head) -- ver sigmoid_gate_mul.hip.template.
        gate_mul = IRNode(
            name=f"blk.{layer_idx}.gate_mul", op_type=NodeType.SIGMOID_GATE_MUL,
            input_tensors=[attention.output_tensor, q_proj.output_tensor],
            output_tensor=f"blk.{layer_idx}.gate_mul.output",
            shape=(1, -1, self.num_heads * self.head_dim), dtype="f16",
        )
        nodes.append(gate_mul)

        attn_out = IRNode(
            name=f"blk.{layer_idx}.attn_output", op_type=NodeType.MATMUL,
            input_tensors=[gate_mul.output_tensor, f"blk.{layer_idx}.attn_output.weight"],
            output_tensor=f"blk.{layer_idx}.attn_output.output",
            shape=(1, -1, self.hidden_size), dtype="f16",
        )
        nodes.append(attn_out)

        residual1 = IRNode(
            name=f"blk.{layer_idx}.residual_1", op_type=NodeType.ADD,
            input_tensors=[input_tensor, attn_out.output_tensor],
            output_tensor=f"blk.{layer_idx}.residual_1.output",
            shape=(1, -1, self.hidden_size), dtype="f16",
        )
        nodes.append(residual1)

        ffn_norm = IRNode(
            name=f"blk.{layer_idx}.post_attention_norm", op_type=NodeType.RMSNORM,
            input_tensors=[residual1.output_tensor, f"blk.{layer_idx}.post_attention_norm.weight"],
            output_tensor=f"blk.{layer_idx}.post_attention_norm.output",
            shape=(1, -1, self.hidden_size), dtype="f16",
        )
        nodes.append(ffn_norm)

        gate_proj = IRNode(
            name=f"blk.{layer_idx}.gate_proj", op_type=NodeType.MATMUL,
            input_tensors=[ffn_norm.output_tensor, f"blk.{layer_idx}.ffn_gate.weight"],
            output_tensor=f"blk.{layer_idx}.gate_proj.output",
            shape=(1, -1, self.ffn_size), dtype="f16",
        )
        nodes.append(gate_proj)

        up_proj = IRNode(
            name=f"blk.{layer_idx}.up_proj", op_type=NodeType.MATMUL,
            input_tensors=[ffn_norm.output_tensor, f"blk.{layer_idx}.ffn_up.weight"],
            output_tensor=f"blk.{layer_idx}.up_proj.output",
            shape=(1, -1, self.ffn_size), dtype="f16",
        )
        nodes.append(up_proj)

        swiglu = IRNode(
            name=f"blk.{layer_idx}.swiglu", op_type=NodeType.SWIGLU,
            input_tensors=[gate_proj.output_tensor, up_proj.output_tensor],
            output_tensor=f"blk.{layer_idx}.swiglu.output",
            shape=(1, -1, self.ffn_size), dtype="f16",
        )
        nodes.append(swiglu)

        down_proj = IRNode(
            name=f"blk.{layer_idx}.down_proj", op_type=NodeType.MATMUL,
            input_tensors=[swiglu.output_tensor, f"blk.{layer_idx}.ffn_down.weight"],
            output_tensor=f"blk.{layer_idx}.down_proj.output",
            shape=(1, -1, self.hidden_size), dtype="f16",
        )
        nodes.append(down_proj)

        residual2 = IRNode(
            name=f"blk.{layer_idx}.residual_2", op_type=NodeType.ADD,
            input_tensors=[residual1.output_tensor, down_proj.output_tensor],
            output_tensor=f"blk.{layer_idx}.output",
            shape=(1, -1, self.hidden_size), dtype="f16",
        )
        nodes.append(residual2)

        return nodes

    def _build_linear_attention_layer(self, layer_idx: int, input_tensor: str) -> List[IRNode]:
        """Gated DeltaNet. Confirmado em modeling_qwen3_5.py::
        Qwen3_5GatedDeltaNet.forward (ver plano): RMSNorm -> {in_proj_qkv,
        in_proj_z, in_proj_a, in_proj_b} em paralelo -> conv1d causal (só
        sobre mixed_qkv) -> recorrência (split de Q/K/V feito via ponteiro
        em kernel_arg_builder.py, não um nó de grafo) -> RMSNormGated ->
        out_proj -> residual -> (RMSNorm de FFN + SwiGLU comum, igual as
        camadas full_attention -- o FFN não muda entre os dois tipos de
        camada, só o bloco de "atenção" muda)."""
        nodes = []

        attn_norm = IRNode(
            name=f"blk.{layer_idx}.attn_norm", op_type=NodeType.RMSNORM,
            input_tensors=[input_tensor, f"blk.{layer_idx}.attn_norm.weight"],
            output_tensor=f"blk.{layer_idx}.attn_norm.output",
            shape=(1, -1, self.hidden_size), dtype="f16",
        )
        nodes.append(attn_norm)

        # in_proj_qkv (GGUF: attn_qkv.weight) -> mixed_qkv concatenado, ainda
        # sem conv1d/silu aplicado.
        qkv_proj = IRNode(
            name=f"blk.{layer_idx}.qkv_proj", op_type=NodeType.MATMUL,
            input_tensors=[attn_norm.output_tensor, f"blk.{layer_idx}.attn_qkv.weight"],
            output_tensor=f"blk.{layer_idx}.qkv_proj.output",
            shape=(1, -1, QWEN35_CONV_DIM), dtype="f16",
        )
        nodes.append(qkv_proj)

        # in_proj_z (GGUF: attn_gate.weight) -- gate de saída, usado só no
        # RMSNormGated final, não passa pelo conv1d.
        z_proj = IRNode(
            name=f"blk.{layer_idx}.z_proj", op_type=NodeType.MATMUL,
            input_tensors=[attn_norm.output_tensor, f"blk.{layer_idx}.attn_gate.weight"],
            output_tensor=f"blk.{layer_idx}.z_proj.output",
            shape=(1, -1, QWEN35_LINEAR_VALUE_DIM), dtype="f16",
        )
        nodes.append(z_proj)

        # in_proj_a / in_proj_b (GGUF: ssm_alpha.weight / ssm_beta.weight) --
        # saídas pequenas (1 escalar por head, num_heads=16), viram os
        # parâmetros a/b do gate de decaimento/beta dentro do kernel de
        # recorrência.
        a_proj = IRNode(
            name=f"blk.{layer_idx}.a_proj", op_type=NodeType.MATMUL,
            input_tensors=[attn_norm.output_tensor, f"blk.{layer_idx}.ssm_alpha.weight"],
            output_tensor=f"blk.{layer_idx}.a_proj.output",
            shape=(1, -1, QWEN35_LINEAR_NUM_HEADS), dtype="f16",
        )
        nodes.append(a_proj)

        b_proj = IRNode(
            name=f"blk.{layer_idx}.b_proj", op_type=NodeType.MATMUL,
            input_tensors=[attn_norm.output_tensor, f"blk.{layer_idx}.ssm_beta.weight"],
            output_tensor=f"blk.{layer_idx}.b_proj.output",
            shape=(1, -1, QWEN35_LINEAR_NUM_HEADS), dtype="f16",
        )
        nodes.append(b_proj)

        conv1d = IRNode(
            name=f"blk.{layer_idx}.conv1d", op_type=NodeType.CAUSAL_CONV1D,
            input_tensors=[qkv_proj.output_tensor],
            output_tensor=f"blk.{layer_idx}.conv1d.output",
            shape=(1, -1, QWEN35_CONV_DIM), dtype="f16",
        )
        nodes.append(conv1d)

        # LINEAR_ATTENTION: input_tensors = [mixed_qkv pós-conv1d, a, b] --
        # o split de Q/K/V acontece via ponteiro em
        # kernel_arg_builder.py::_build_linear_attention_args, não aqui.
        linear_attn = IRNode(
            name=f"blk.{layer_idx}.linear_attention", op_type=NodeType.LINEAR_ATTENTION,
            input_tensors=[conv1d.output_tensor, a_proj.output_tensor, b_proj.output_tensor],
            output_tensor=f"blk.{layer_idx}.linear_attention.output",
            shape=(1, -1, QWEN35_LINEAR_VALUE_DIM), dtype="f16",
        )
        nodes.append(linear_attn)

        # RMSNormGated: norm(core_attn_out) * silu(z) -- ver
        # rmsnorm_gated.hip.template. Uma linha por head (grid=num_heads),
        # não uma linha por token -- por isso o kernel recebe head_v_dim,
        # não value_dim inteiro.
        norm_gated = IRNode(
            name=f"blk.{layer_idx}.norm_gated", op_type=NodeType.RMSNORM_GATED,
            input_tensors=[linear_attn.output_tensor, z_proj.output_tensor],
            output_tensor=f"blk.{layer_idx}.norm_gated.output",
            shape=(1, -1, QWEN35_LINEAR_VALUE_DIM), dtype="f16",
        )
        nodes.append(norm_gated)

        out_proj = IRNode(
            name=f"blk.{layer_idx}.out_proj", op_type=NodeType.MATMUL,
            input_tensors=[norm_gated.output_tensor, f"blk.{layer_idx}.ssm_out.weight"],
            output_tensor=f"blk.{layer_idx}.out_proj.output",
            shape=(1, -1, self.hidden_size), dtype="f16",
        )
        nodes.append(out_proj)

        residual1 = IRNode(
            name=f"blk.{layer_idx}.residual_1", op_type=NodeType.ADD,
            input_tensors=[input_tensor, out_proj.output_tensor],
            output_tensor=f"blk.{layer_idx}.residual_1.output",
            shape=(1, -1, self.hidden_size), dtype="f16",
        )
        nodes.append(residual1)

        # FFN: idêntico ao das camadas full_attention (RMSNorm ->
        # Gate/Up -> SwiGLU -> down_proj -> residual) -- o FFN não muda
        # entre os dois tipos de camada.
        ffn_norm = IRNode(
            name=f"blk.{layer_idx}.post_attention_norm", op_type=NodeType.RMSNORM,
            input_tensors=[residual1.output_tensor, f"blk.{layer_idx}.post_attention_norm.weight"],
            output_tensor=f"blk.{layer_idx}.post_attention_norm.output",
            shape=(1, -1, self.hidden_size), dtype="f16",
        )
        nodes.append(ffn_norm)

        gate_proj = IRNode(
            name=f"blk.{layer_idx}.gate_proj", op_type=NodeType.MATMUL,
            input_tensors=[ffn_norm.output_tensor, f"blk.{layer_idx}.ffn_gate.weight"],
            output_tensor=f"blk.{layer_idx}.gate_proj.output",
            shape=(1, -1, self.ffn_size), dtype="f16",
        )
        nodes.append(gate_proj)

        up_proj = IRNode(
            name=f"blk.{layer_idx}.up_proj", op_type=NodeType.MATMUL,
            input_tensors=[ffn_norm.output_tensor, f"blk.{layer_idx}.ffn_up.weight"],
            output_tensor=f"blk.{layer_idx}.up_proj.output",
            shape=(1, -1, self.ffn_size), dtype="f16",
        )
        nodes.append(up_proj)

        swiglu = IRNode(
            name=f"blk.{layer_idx}.swiglu", op_type=NodeType.SWIGLU,
            input_tensors=[gate_proj.output_tensor, up_proj.output_tensor],
            output_tensor=f"blk.{layer_idx}.swiglu.output",
            shape=(1, -1, self.ffn_size), dtype="f16",
        )
        nodes.append(swiglu)

        down_proj = IRNode(
            name=f"blk.{layer_idx}.down_proj", op_type=NodeType.MATMUL,
            input_tensors=[swiglu.output_tensor, f"blk.{layer_idx}.ffn_down.weight"],
            output_tensor=f"blk.{layer_idx}.down_proj.output",
            shape=(1, -1, self.hidden_size), dtype="f16",
        )
        nodes.append(down_proj)

        residual2 = IRNode(
            name=f"blk.{layer_idx}.residual_2", op_type=NodeType.ADD,
            input_tensors=[residual1.output_tensor, down_proj.output_tensor],
            output_tensor=f"blk.{layer_idx}.output",
            shape=(1, -1, self.hidden_size), dtype="f16",
        )
        nodes.append(residual2)

        return nodes
