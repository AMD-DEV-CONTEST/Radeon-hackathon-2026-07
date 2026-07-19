import pytest
from vte.compiler.ir import IRGraph, IRNode, QuantizationInfo
from vte.compiler.fusion_analyzer import FusionAnalyzer
from vte.compiler.fusion_applier import FusionApplier
from vte.core.fallback_executor import FallbackExecutor
from vte.bridge.hip_runtime import HIPRuntime
from vte.bridge.memory import SlabAllocator, MemoryRegion
from vte.compiler.qwen_mapper import ActivationArena
from vte.bridge.errors import HIPSafetyError

def test_fallback_executor_hides_fused_nodes():
    """
    Testa que nós originais marcados is_fused=True pela FusionApplier NÃO são
    despachados individualmente pelo FallbackExecutor (mesmo comportamento já
    existente no HIPGraphExecutor).

    Nota: o dispatch real do nó "mega_kernel" resultante da fusão (e um
    eventual rollback automático em caso de falha) não está implementado —
    o kernel fundido (fused_rmsnorm_matmul_rope.hip.template) é hoje um
    stub incompleto (sem RMSNorm/MatMul/RoPE reais, sem escrita de saída),
    e nenhum padrão de fusão é sequer aplicável ao Qwen2.5 na prática (ver
    FusionAnalyzer — o RMSNorm alimenta 3 MatMuls em paralelo, não uma
    cadeia linear). Por isso este teste verifica apenas o contrato que
    realmente existe hoje: nós fundidos somem do dispatch individual.
    """

    graph = IRGraph()
    q_info = QuantizationInfo(type="f16", block_size=1, has_scales=False, has_mins=False)

    n1 = IRNode("blk.0.rmsnorm", (128,), 1, 0, 100, q_info, op_type="rmsnorm",
                input_tensors=["x0", "rmsnorm.weight"], output_tensor="t1")
    n2 = IRNode("blk.0.matmul", (128,), 1, 0, 100, q_info, op_type="matmul",
                input_tensors=["t1", "matmul.weight"], output_tensor="t2")
    n3 = IRNode("blk.0.rope", (128,), 1, 0, 100, q_info, op_type="rope",
                input_tensors=["t2", "t2", "rope_freqs"], output_tensor="t3")

    for n in [n1, n2, n3]: graph.add_node(n)

    analyzer = FusionAnalyzer()
    candidates = analyzer.analyze(graph)
    applier = FusionApplier()
    fused_graph = applier.apply(graph, candidates)

    from vte.bridge.dll_discovery import find_hip_dll
    if find_hip_dll() is None:
        pytest.skip("AMD HIP SDK não encontrado, pulando validação que exige load da DLL física.")

    hip = HIPRuntime()
    hip.initialize()
    allocator = SlabAllocator(hip, 8 * 1024 * 1024)
    allocator.initialize()
    arena_block = allocator.allocate(1024 * 1024, "TEST_ARENA", MemoryRegion.ACTIVATIONS)
    arena = ActivationArena(arena_block)

    # Ponteiros VRAM reais (não-nulos) para cada tensor referenciado pelo grafo
    # sintético, evitando lançar kernels reais na GPU com argumentos nulos.
    tensor_mapping = {}
    for name in ["x0", "rmsnorm.weight", "matmul.weight", "rope_freqs", "t1", "t2", "t3"]:
        tensor_mapping[name] = allocator.allocate(128 * 2, f"TEST_{name}", MemoryRegion.ACTIVATIONS).ptr

    assert len(candidates) == 1, "Cadeia linear rmsnorm->matmul->rope deveria ser detectada como fusível"
    fused_node_name = "fused_rmsnorm_matmul_rope_blk.0.rmsnorm"
    assert fused_graph.nodes[fused_node_name].op_type == "mega_kernel"
    for original_name in ["blk.0.rmsnorm", "blk.0.matmul", "blk.0.rope"]:
        assert fused_graph.nodes[original_name].is_fused is True
        assert fused_graph.nodes[original_name].fused_into == fused_node_name

    executor = FallbackExecutor(hip, allocator, arena, fused_graph, tensor_mapping=tensor_mapping)

    executor.execute_layer(0, 128)

    # Os nós originais foram fundidos: não devem aparecer no dispatch individual.
    assert "blk.0.rmsnorm" not in executor.context.executed_nodes
    assert "blk.0.matmul" not in executor.context.executed_nodes
    assert "blk.0.rope" not in executor.context.executed_nodes
