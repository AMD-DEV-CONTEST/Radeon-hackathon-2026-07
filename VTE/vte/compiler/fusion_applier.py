from typing import List
from vte.compiler.ir import IRGraph, IRNode
from vte.compiler.fusion_analyzer import FusionCandidate
from vte.bridge.memory import MemoryRegion
from vte.bridge.logger import get_logger

logger = get_logger(__name__)

class FusionApplier:
    """Aplica fusões de forma segura ocultando nós originais em IRGraph."""
    
    def apply(self, ir_graph: IRGraph, candidates: List[FusionCandidate]) -> IRGraph:
        """Retorna novo graph (mutado) com fusões aplicadas."""
        
        for candidate in candidates:
            if all(node.name in ir_graph.nodes for node in candidate.nodes):
                mega_node = self._create_mega_kernel_node(candidate)
                
                for node in candidate.nodes:
                    node.is_fused = True
                    node.fused_into = mega_node.name
                    
                ir_graph.add_node(mega_node)
                
                ir_graph.rewire_edges(candidate.nodes, mega_node)
                
                logger.info(f"Fusão aplicada: {len(candidate.nodes)} nós -> {mega_node.name}")
                
        return ir_graph

    def _create_mega_kernel_node(self, candidate: FusionCandidate) -> IRNode:
        combined_inputs = set()
        for node in candidate.nodes:
            combined_inputs.update(node.input_tensors)
            
        intermediate_tensors = set()
        for node in candidate.nodes[:-1]:
            intermediate_tensors.add(node.output_tensor)
            
        external_inputs = combined_inputs - intermediate_tensors
        final_output = candidate.nodes[-1].output_tensor
        
        return IRNode(
            name=f"fused_{candidate.pattern}_{candidate.nodes[0].name}",
            shape=candidate.nodes[-1].shape,
            dtype=candidate.nodes[-1].dtype,
            offset=candidate.nodes[0].offset,
            size=sum(n.size for n in candidate.nodes),
            quant_info=candidate.nodes[0].quant_info,
            op_type="mega_kernel",
            input_tensors=list(external_inputs),
            output_tensor=final_output,
            memory_region=MemoryRegion.ACTIVATIONS,
            estimated_flops=sum(n.estimated_flops for n in candidate.nodes),
            tile_size=candidate.nodes[0].tile_size,
            original_nodes=candidate.nodes
        )
