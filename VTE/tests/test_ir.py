import pytest
from vte.compiler.ir import IRGraph, IRNode, QuantizationInfo
from vte.bridge.errors import HIPSafetyError

def test_acyclic_validation_success():
    graph = IRGraph()
    q = QuantizationInfo("f32", 1, False, False)
    n1 = IRNode("A", (1,), 0, 0, 4, q, outputs=["B"])
    n2 = IRNode("B", (1,), 0, 4, 4, q, inputs=["A"])
    
    graph.add_node(n1)
    graph.add_node(n2)
    
    graph.validate_acyclic()

def test_acyclic_validation_cycle():
    graph = IRGraph()
    q = QuantizationInfo("f32", 1, False, False)

    n1 = IRNode("A", (1,), 0, 0, 4, q, outputs=["B"], inputs=["C"])
    n2 = IRNode("B", (1,), 0, 4, 4, q, outputs=["C"], inputs=["A"])
    n3 = IRNode("C", (1,), 0, 8, 4, q, outputs=["A"], inputs=["B"])
    
    graph.add_node(n1)
    graph.add_node(n2)
    graph.add_node(n3)
    
    with pytest.raises(HIPSafetyError, match="Ciclo detectado"):
        graph.validate_acyclic()
