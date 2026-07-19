import pytest
import struct
from vte.compiler.gguf_parser import GGUFParser
from vte.bridge.errors import HIPSafetyError

@pytest.fixture
def fake_gguf(tmp_path):
    p = tmp_path / "fake.gguf"
    with open(p, "wb") as f:

        f.write(b"GGUF")
        f.write(struct.pack("<I", 3))
        f.write(struct.pack("<Q", 1))
        f.write(struct.pack("<Q", 0))
        
        name = "tok_embd.weight"
        f.write(struct.pack("<Q", len(name)))
        f.write(name.encode('utf-8'))
        f.write(struct.pack("<I", 1))
        f.write(struct.pack("<Q", 100))
        f.write(struct.pack("<I", 0))
        f.write(struct.pack("<Q", 0))
        
        f.write(b"\0" * 32)

        f.write(b"\1" * 400)
    return p

def test_parser_bounds_check(fake_gguf):
    parser = GGUFParser(fake_gguf)
    
    bad_info = {"name": "test", "offset": 1000, "size": 500}
    with pytest.raises(HIPSafetyError, match="excede o tamanho"):
        parser._validate_tensor_bounds(bad_info, file_size=1000)

def test_tied_embeddings_detection(fake_gguf):
    parser = GGUFParser(fake_gguf)
    parser.tensors = {
        "token_embd.weight": {"offset": 123},
        "output.weight": {"offset": 123}
    }
    parser._detect_tied_embeddings()
    assert parser.tensors["output.weight"].get("is_tied") is True
    assert parser.tensors["output.weight"].get("tied_to") == "token_embd.weight"

def test_shape_validation(fake_gguf):
    parser = GGUFParser(fake_gguf)
    parser.tensors = {
        "token_embd.weight": {"shape": (151936, 1536)}
    }

    parser._validate_qwen25_shapes({"embedding_length": 1536})
    
    parser.tensors["token_embd.weight"]["shape"] = (1000, 1000)
    with pytest.raises(HIPSafetyError, match="Shape incorreto"):
        parser._validate_qwen25_shapes({"embedding_length": 1536})
