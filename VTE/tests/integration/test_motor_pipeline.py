import pytest
import time
from multiprocessing import Pipe
from vte.core.motor import InferenceEngine
from vte.core.ipc import UIMsgPrompt, MotorMsgToken

def test_inference_pipeline_structural():
    """
    Testa se o pipeline estrutural da Fase 4 funciona:
    Tokenizador -> Prefill -> Decode -> Sampler -> IPC Flush
    """
    from vte.bridge.dll_discovery import find_hip_dll
    if find_hip_dll() is None:
        pytest.skip("AMD HIP SDK não encontrado, pulando teste estrutural da pipeline.")
        
    parent_conn, child_conn = Pipe()
    engine = InferenceEngine(child_conn)
    
    class MockTokenizer:
        # O motor formata a mensagem no chat template antes de gerar; o mock
        # só precisa devolver algo (passthrough basta para o teste estrutural).
        def apply_chat_template(self, user_message, system=None, enable_thinking=False):
            return user_message

    class MockModel:
        tokenizer = MockTokenizer()

        def generate(self, prompt, max_tokens):
            for i in range(max_tokens):
                yield f"tok_{i}"

    engine.model = MockModel()
    
    engine.generate("Olá, como você está?", max_tokens=3)
    
    tokens_received = []
    while parent_conn.poll(0.1):
        msg = parent_conn.recv()
        if isinstance(msg, MotorMsgToken):
            tokens_received.append(msg.text)
            
    assert len(tokens_received) > 0

    assert any("tok_" in t for t in tokens_received) or any("V" in t for t in tokens_received)
