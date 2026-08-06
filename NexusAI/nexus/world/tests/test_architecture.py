from nexus.world.architecture import infer_architecture
from nexus.world.context import extract_context

def test_medieval_architecture():
 a=infer_architecture(extract_context("A medieval stone castle and timber village."))
 assert a.style.value=="medieval"
 assert {"stone","timber"}<=set(a.materials)
