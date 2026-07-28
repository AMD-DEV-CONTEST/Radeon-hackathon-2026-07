import pytest
from vte.compiler.ir import IRGraph, IRNode, QuantizationInfo
from vte.compiler.fusion_analyzer import FusionAnalyzer, FusionCandidate
from vte.compiler.fusion_applier import FusionApplier

def test_fusion_analyzer_finds_pattern():
    """Testa que analyzer encontra padrão rmsnorm+matmul+rope"""
    graph = IRGraph()
    
    q_info = QuantizationInfo(type="f16", block_size=1, has_scales=False, has_mins=False)
    
    n1 = IRNode("rmsnorm_1", (128,), 1, 0, 100, q_info, op_type="rmsnorm", output_tensor="t1")
    n2 = IRNode("matmul_1", (128,), 1, 0, 100, q_info, op_type="matmul", input_tensors=["t1"], output_tensor="t2")
    n3 = IRNode("rope_1", (128,), 1, 0, 100, q_info, op_type="rope", input_tensors=["t2"], output_tensor="t3")
    
    graph.add_node(n1)
    graph.add_node(n2)
    graph.add_node(n3)
    
    analyzer = FusionAnalyzer()
    candidates = analyzer.analyze(graph)
    
    assert len(candidates) == 1
    assert candidates[0].pattern == 'rmsnorm_matmul_rope'
    assert candidates[0].is_safe

def test_fusion_analyzer_rejects_unsafe():
    """Testa que analyzer rejeita fusões se o limite VGPR estourar"""
    graph = IRGraph()
    q_info = QuantizationInfo(type="f16", block_size=1, has_scales=False, has_mins=False)
    
    n1 = IRNode("rmsnorm_1", (128,), 1, 0, 100, q_info, op_type="rmsnorm", output_tensor="t1")
    n2 = IRNode("matmul_1", (128,), 1, 0, 100, q_info, op_type="matmul", input_tensors=["t1"], output_tensor="t2")
    n3 = IRNode("matmul_2", (128,), 1, 0, 100, q_info, op_type="matmul", input_tensors=["t2"], output_tensor="t3")
    n4 = IRNode("matmul_3", (128,), 1, 0, 100, q_info, op_type="matmul", input_tensors=["t3"], output_tensor="t4")
    n5 = IRNode("rope_1", (128,), 1, 0, 100, q_info, op_type="rope", input_tensors=["t4"], output_tensor="t5")
    
    for n in [n1, n2, n3, n4, n5]: graph.add_node(n)
    
    analyzer = FusionAnalyzer()
    
    analyzer.FUSION_PATTERNS.append({
        'name': 'insane_fusion',
        'ops': ['rmsnorm', 'matmul', 'matmul', 'matmul', 'rope'],
        'max_vgpr': 96,
        'max_shared_mem': 32 * 1024
    })
    
    candidates = analyzer.analyze(graph)
    
    assert len(candidates) == 0
    insane_candidates = [c for c in candidates if c.pattern == 'insane_fusion']
    assert len(insane_candidates) == 0

def test_fusion_applier_hides_nodes():
    """Testa que applier cria o MegaKernel e marca is_fused=True nos originais"""
    graph = IRGraph()
    q_info = QuantizationInfo(type="f16", block_size=1, has_scales=False, has_mins=False)
    
    n1 = IRNode("rmsnorm_1", (128,), 1, 0, 100, q_info, op_type="rmsnorm", output_tensor="t1")
    n2 = IRNode("matmul_1", (128,), 1, 0, 100, q_info, op_type="matmul", input_tensors=["t1"], output_tensor="t2")
    n3 = IRNode("rope_1", (128,), 1, 0, 100, q_info, op_type="rope", input_tensors=["t2"], output_tensor="t3")
    
    graph.add_node(n1)
    graph.add_node(n2)
    graph.add_node(n3)
    
    analyzer = FusionAnalyzer()
    applier = FusionApplier()
    
    candidates = analyzer.analyze(graph)
    fused_graph = applier.apply(graph, candidates)
    
    assert fused_graph.nodes["rmsnorm_1"].is_fused == True
    assert "fused_rmsnorm_matmul_rope_rmsnorm_1" in fused_graph.nodes
    
    mega_node = fused_graph.nodes["fused_rmsnorm_matmul_rope_rmsnorm_1"]
    assert mega_node.op_type == "mega_kernel"
    assert len(mega_node.original_nodes) == 3
