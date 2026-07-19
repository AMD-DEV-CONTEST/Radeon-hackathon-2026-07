from dataclasses import dataclass, field
from typing import List, Tuple
from vte.compiler.ir import IRGraph, IRNode
from vte.bridge.logger import get_logger

logger = get_logger(__name__)

@dataclass
class FusionCandidate:
    pattern: str
    nodes: List[IRNode]
    vgpr_usage: int
    shared_mem_usage: int
    has_bank_conflict_risk: bool
    estimated_speedup: float
    is_safe: bool = True
    safety_notes: List[str] = field(default_factory=list)

class FusionAnalyzer:
    """Analisa o IR graph e identifica padrões fusíveis para arquitetura RDNA3."""
    
    FUSION_PATTERNS = [
        {
            'name': 'rmsnorm_matmul_rope',
            'ops': ['rmsnorm', 'matmul', 'rope'],
            'max_vgpr': 96,
            'max_shared_mem': 32 * 1024,
        },
    ]

    def analyze(self, ir_graph: IRGraph) -> List[FusionCandidate]:
        candidates = []
        
        for pattern in self.FUSION_PATTERNS:
            matches = self._find_pattern_matches(ir_graph, pattern['ops'])
            
            for match in matches:
                vgpr_estimate = self._estimate_vgpr_usage(match)
                shared_mem, has_bank_conflict = self._estimate_shared_memory(match)
                
                is_safe = True
                safety_notes = []
                
                if vgpr_estimate > pattern['max_vgpr']:
                    is_safe = False
                    safety_notes.append(f"VGPR {vgpr_estimate} > {pattern['max_vgpr']}")
                    
                if shared_mem > pattern['max_shared_mem']:
                    is_safe = False
                    safety_notes.append(f"SharedMem {shared_mem} > {pattern['max_shared_mem']}")
                    
                if vgpr_estimate > 96:
                    safety_notes.append("Risco de register spilling se exceder 96 VGPRs")
                    
                if has_bank_conflict:
                    safety_notes.append("Risco de bank conflicts na LDS")
                
                speedup = self._estimate_speedup(match, vgpr_estimate, shared_mem)
                
                candidates.append(FusionCandidate(
                    pattern=pattern['name'],
                    nodes=match,
                    vgpr_usage=vgpr_estimate,
                    shared_mem_usage=shared_mem,
                    has_bank_conflict_risk=has_bank_conflict,
                    estimated_speedup=speedup,
                    is_safe=is_safe,
                    safety_notes=safety_notes
                ))
                
        safe_candidates = [c for c in candidates if c.is_safe]
        safe_candidates.sort(key=lambda c: c.estimated_speedup, reverse=True)
        return safe_candidates

    def _find_pattern_matches(self, graph: IRGraph, ops: List[str]) -> List[List[IRNode]]:
        """
        Encontra cadeias lineares produtor->consumidor que seguem exatamente a
        sequência de op_types pedida, navegando pelas dependências REAIS de
        dados (output_tensor -> input_tensors), não pela ordem de inserção do
        grafo.

        Exige fan-out == 1 em cada elo (o output do nó N só pode ter UM
        consumidor direto, que precisa ser o próximo op do padrão). Isso é
        proposital: a infraestrutura atual de fusão (IRNode/mega_kernel) só
        suporta um único output_tensor por nó fundido. Um RMSNorm cujo
        resultado alimenta vários MatMuls em paralelo (como as projeções
        Q/K/V separadas do Qwen2.5) não é uma cadeia linear fundível com essa
        infraestrutura — fundir aqui exigiria um kernel de múltiplas saídas,
        que não existe hoje. Por isso, corretamente, nenhum candidato é
        encontrado para esse caso, em vez de arriscar aplicar uma fusão que a
        infraestrutura não consegue executar corretamente.
        """
        all_nodes = list(graph.nodes.values())

        def direct_consumers(tensor_name: str) -> List[IRNode]:
            return [n for n in all_nodes if tensor_name in n.input_tensors]

        matches = []
        for start_node in all_nodes:
            if start_node.op_type != ops[0] or getattr(start_node, 'is_fused', False):
                continue

            chain = [start_node]
            valid = True
            for expected_op in ops[1:]:
                producer = chain[-1]
                consumers = direct_consumers(producer.output_tensor)
                if len(consumers) != 1 or getattr(consumers[0], 'is_fused', False) or consumers[0].op_type != expected_op:
                    valid = False
                    break
                chain.append(consumers[0])

            if valid:
                matches.append(chain)

        return matches

    def _estimate_vgpr_usage(self, nodes: List[IRNode]) -> int:
        base_vgprs = 0
        for node in nodes:
            if node.op_type == 'rmsnorm':
                base_vgprs += 8
            elif node.op_type == 'matmul':
                base_vgprs += 16
            elif node.op_type == 'rope':
                base_vgprs += 8
                
        overhead = 18
        total_vgprs = base_vgprs + overhead
        return int(total_vgprs * 1.2)

    def _estimate_shared_memory(self, nodes: List[IRNode]) -> Tuple[int, bool]:
        total_shared_mem = 0
        has_bank_conflict_risk = False
        
        for node in nodes:
            if node.op_type == 'rmsnorm':
                mem_needed = node.shape[-1] * 2
                total_shared_mem += mem_needed
                if mem_needed % 32 == 0:
                    has_bank_conflict_risk = True
            elif node.op_type == 'matmul':
                tile_size = node.tile_size[0] * node.tile_size[1] * 2
                total_shared_mem += tile_size * 2
                
        return total_shared_mem, has_bank_conflict_risk

    def _estimate_speedup(self, nodes: List[IRNode], vgprs: int, lds: int) -> float:

        speedup = float(len(nodes)) * 0.6
        if vgprs > 64: 
            speedup -= 0.1
        return speedup
