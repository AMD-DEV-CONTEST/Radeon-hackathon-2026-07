import pytest
from vte.compiler.codegen import CodegenEngine, get_kernel_cache_path, _sanitize_var
from vte.bridge.errors import HIPSafetyError

def test_codegen_sanitization():
    """Garante que injeção de código C++ é bloqueada"""
    
    assert _sanitize_var(16) == "16"
    assert _sanitize_var(1.5) == "1.5"
    
    assert _sanitize_var("my_kernel_1") == "my_kernel_1"
    
    with pytest.raises(HIPSafetyError, match="insegura bloqueada"):
        _sanitize_var("my_kernel; system('rm -rf /');")
        
    with pytest.raises(HIPSafetyError, match="insegura bloqueada"):
        _sanitize_var("16; //")

def test_codegen_cache_invalidation():
    """Garante que mudar parâmetros gera hash diferente"""
    code_v1 = "void kernel() { int tile = 16; }"
    code_v2 = "void kernel() { int tile = 32; }"
    
    path1 = get_kernel_cache_path(code_v1, "gfx1100")
    path2 = get_kernel_cache_path(code_v2, "gfx1100")
    
    assert path1 != path2, "Cache não invalidou com mudança de parâmetro"
    assert "kernel_" in path1
    assert path1.endswith(".hsaco")
    assert "gfx1100" in path1

def test_codegen_engine_compile_rmsnorm():
    """Garante que o template rmsnorm.hip.template é carregado, renderizado e compilado"""
    engine = CodegenEngine()

    # Verifica a renderização diretamente (independente de qualquer arquivo de
    # log no disco, que pode ter sobras de outras execuções/tile_sizes e
    # tornaria o teste dependente de ordem de glob() não-determinística).
    rendered_code = engine.render_template("rmsnorm", tile_size=16)
    assert "#define BLOCK_SIZE 16" in rendered_code
    assert "__shfl_down" in rendered_code

    hsaco_path = engine.compile_kernel("rmsnorm", arch="gfx1100", tile_size=16)

    assert "kernel_" in hsaco_path
    assert hsaco_path.endswith(".hsaco")

    import os
    assert os.path.exists(hsaco_path)

def test_parse_vgpr_usage():
    engine = CodegenEngine()
    
    mock_output_1 = "remark: fused_rmsnorm_matmul_rope.hip:10:5: vgpr_count: 98, sgpr_count: 32"
    assert engine._parse_vgpr_usage(mock_output_1) == 98
    
    mock_output_2 = "ISA Info:\nVGPRs: 115\nSGPRs: 44"
    assert engine._parse_vgpr_usage(mock_output_2) == 115
    
    mock_output_3 = "Compilação bem sucedida."
    assert engine._parse_vgpr_usage(mock_output_3) == -1

def test_mega_kernel_sanitization():
    engine = CodegenEngine()
    
    template_code = "int size = {{ block_size }}; float offsets[] = {{ arr }};"
    
    test_template_name = "test_mega"
    test_template_path = engine.templates_dir / f"{test_template_name}.hip.template"
    test_template_path.parent.mkdir(parents=True, exist_ok=True)
    with open(test_template_path, "w") as f:
        f.write(template_code)
        
    try:

        rendered = engine.render_template(
            test_template_name, 
            is_mega_kernel=True, 
            block_size=128, 
            arr=[1, 2.5, 3]
        )
        assert "int size = 128;" in rendered
        assert "float offsets[] = {1, 2.5, 3};" in rendered
    finally:
        test_template_path.unlink()
