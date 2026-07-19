import pytest
from pathlib import Path
from vte.compiler.sanitizer import GGUFSanitizer
from vte.bridge.errors import HIPSafetyError

@pytest.fixture
def mock_gguf_file(tmp_path):

    p = tmp_path / "Qwen2.5-1.5B-Instruct-Q4_K_M.gguf"
    
    import struct
    with open(p, "wb") as f:
        f.write(b"GGUF")
        f.write(struct.pack("<I", 3))
        f.write(struct.pack("<Q", 100))
        f.write(struct.pack("<Q", 4))
        
        def write_string(s):
            b = s.encode('utf-8')
            f.write(struct.pack("<Q", len(b)))
            f.write(b)
            
        def write_kv(key, vtype, pack_fmt, *args):
            write_string(key)
            f.write(struct.pack("<I", vtype))
            if vtype == 8:
                write_string(args[0])
            else:
                f.write(struct.pack(pack_fmt, *args))
                
        write_kv("general.architecture", 8, "", "qwen2")

        write_kv("qwen2.context_length", 4, "<I", 32768)

        write_kv("qwen2.embedding_length", 4, "<I", 1536)

        write_kv("qwen2.block_count", 4, "<I", 28)
        
    return p

def test_missing_file():
    sanitizer = GGUFSanitizer("Model/missing.gguf")
    with pytest.raises(HIPSafetyError, match="não encontrado"):
        sanitizer.validate()

def test_truncated_file_rejected(tmp_path):
    """Filename is no longer part of validation (model discovery resolves
    variants by block_count + file size now, see
    GGUFSanitizer._validate_metadata_consistency) -- a mismatched name alone
    is not rejected. What must still fail loudly is a file too short to
    contain a real GGUF header, regardless of its name."""
    p = tmp_path / "wrong_name.gguf"
    p.write_bytes(b"GGUF")
    sanitizer = GGUFSanitizer(p)
    with pytest.raises(HIPSafetyError, match="Erro de struct lendo GGUF"):
        sanitizer.validate()

def test_size_out_of_bounds(mock_gguf_file, monkeypatch):
    import vte.config as config
    monkeypatch.setattr(config, "ALLOWED_MODEL_SIZE_MIN", 1000)
    sanitizer = GGUFSanitizer(mock_gguf_file)
    with pytest.raises(HIPSafetyError, match="fora do esperado"):
        sanitizer.validate()

def test_invalid_magic(mock_gguf_file, monkeypatch):
    import vte.config as config
    monkeypatch.setattr(config, "ALLOWED_MODEL_SIZE_MIN", 10)
    with open(mock_gguf_file, "r+b") as f:
        f.write(b"BAD!")
    sanitizer = GGUFSanitizer(mock_gguf_file)

    monkeypatch.setattr(sanitizer, "_validate_or_generate_hash", lambda: True)
    with pytest.raises(HIPSafetyError, match="Magic number inválido"):
        sanitizer.validate()

def test_invalid_metadata_consistency(mock_gguf_file, monkeypatch):
    import vte.config as config
    monkeypatch.setattr(config, "ALLOWED_MODEL_SIZE_MIN", 10)
    
    sanitizer = GGUFSanitizer(mock_gguf_file)
    monkeypatch.setattr(sanitizer, "_validate_or_generate_hash", lambda profile: True)

    import struct
    with open(mock_gguf_file, "r+b") as f:
        f.seek(8)
        f.write(struct.pack("<Q", 1001))

    with pytest.raises(HIPSafetyError, match="excessivo"):
        sanitizer.validate()

def test_valid_mock_flow(mock_gguf_file, monkeypatch):
    import vte.config as config
    monkeypatch.setattr(config, "ALLOWED_MODEL_SIZE_MIN", 10)

    sanitizer = GGUFSanitizer(mock_gguf_file)
    monkeypatch.setattr(sanitizer, "_validate_or_generate_hash", lambda profile: True)
    
    assert sanitizer.validate() is True
    assert sanitizer.header.architecture == "qwen2"
    assert sanitizer.header.block_count == 28
    assert sanitizer.header.embedding_length == 1536
    assert sanitizer.header.context_length == 32768
