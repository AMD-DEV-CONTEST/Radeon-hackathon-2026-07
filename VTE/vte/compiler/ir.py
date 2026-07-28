from dataclasses import dataclass, field
from typing import List, Dict, Set, Optional
from vte.bridge.errors import HIPSafetyError
from vte.bridge.logger import get_logger

from enum import Enum

logger = get_logger(__name__)

class NodeType(str, Enum):
    RMSNORM = "rmsnorm"
    MATMUL = "matmul"
    ROPE = "rope"
    ATTENTION = "attention"
    SWIGLU = "swiglu"
    ADD = "add"
    INPUT = "input"
    OUTPUT = "output"
    EMBEDDING = "embedding"
    # Gated DeltaNet (Qwen3.5 "linear_attention" layers) -- recorrência
    # linear com estado persistente, ver vte/compiler/qwen3_5_mapper.py e
    # docs internas do plano em andamento. Isolado das arquiteturas
    # existentes: nenhum node type acima é afetado por esta adição.
    CAUSAL_CONV1D = "causal_conv1d"
    LINEAR_ATTENTION = "linear_attention"
    # RMSNorm + gate multiplicativo (Qwen3_5RMSNormGated:
    # norm(x)*weight*silu(gate)) -- kernel isolado, não estende o RMSNORM
    # comum usado por Qwen2.5/Granite.
    RMSNORM_GATED = "rmsnorm_gated"
    # Qwen3.5 full_attention: RMSNorm aplicado por-HEAD (não na linha
    # inteira, ao contrário do RMSNORM comum) -- q_norm/k_norm reais do
    # Qwen3.5Attention (modeling_qwen3_5.py), aplicados a Q/K logo após
    # q_proj/k_proj e ANTES do RoPE. Isolado do RMSNORM comum.
    PER_HEAD_RMSNORM = "per_head_rmsnorm"
    # Qwen3.5 full_attention: gate sigmoide multiplicando a saída da
    # atenção antes do o_proj (attn_output = attn_out * sigmoid(gate),
    # onde `gate` vem da segunda metade do q_proj, mesmo padrão de split
    # intercalado por-head que o mixed_qkv do Gated DeltaNet usa).
    SIGMOID_GATE_MUL = "sigmoid_gate_mul"

@dataclass
class QuantizationInfo:
    type: str
    block_size: int
    has_scales: bool
    has_mins: bool

@dataclass
class IRNode:
    name: str
    shape: tuple
    dtype: int | str = 0
    offset: int = 0
    size: int = 0
    quant_info: Optional[QuantizationInfo] = None

    op_type: str = "undefined"
    input_tensors: List[str] = field(default_factory=list)
    output_tensor: str = ""
    memory_region: int = 2
    estimated_flops: int = 0
    tile_size: tuple = (16, 16)
    
    is_fused: bool = False
    fused_into: Optional[str] = None
    original_nodes: Optional[list['IRNode']] = None
    
    is_tied: bool = False
    tied_to: str = ""
    inputs: List[str] = field(default_factory=list)
    outputs: List[str] = field(default_factory=list)

@dataclass
class FusedGateUpProjNode(IRNode):
    """Nó especial que funde gate_proj e up_proj numa única MatMul."""
    gate_name: str = ""
    up_name: str = ""

class IRGraph:
    def __init__(self):
        self.nodes: Dict[str, IRNode] = {}
        self.node_count = 0

    def add_node(self, node: IRNode):
        if node.name in self.nodes:
            raise HIPSafetyError(f"Nó duplicado no Grafo IR: {node.name}")
        self.nodes[node.name] = node
        self.node_count += 1
        
    def rewire_edges(self, old_nodes: List[IRNode], new_mega_node: IRNode):
        """Redireciona as arestas e esconde nós fundidos da validação topológica principal."""
        pass
        
    def topological_sort(self) -> List[IRNode]:
        """Versão que retorna os próprios nós para análise."""
        return list(self.nodes.values())

    def validate_acyclic(self):
        """Garante que o grafo não tem dependências cíclicas (Kahn's algorithm)."""
        logger.info("Iniciando validação Topológica (Cycle Detection) no Grafo IR.")
        
        in_degree = {name: 0 for name in self.nodes}
        for node in self.nodes.values():
            for out_node in node.outputs:
                if out_node in in_degree:
                    in_degree[out_node] += 1
                    
        queue = [name for name, deg in in_degree.items() if deg == 0]
        visited_count = 0
        
        while queue:
            curr = queue.pop(0)
            visited_count += 1
            for out_node in self.nodes[curr].outputs:
                if out_node in in_degree:
                    in_degree[out_node] -= 1
                    if in_degree[out_node] == 0:
                        queue.append(out_node)
                        
        if visited_count != self.node_count:
            raise HIPSafetyError(
                f"Ciclo detectado no Grafo IR! Arquivo corrompido ou malicioso. "
                f"Nós visitados: {visited_count}, Total: {self.node_count}"
            )
            
        logger.info("Validação Topológica completa. Grafo é um DAG acíclico válido.")
