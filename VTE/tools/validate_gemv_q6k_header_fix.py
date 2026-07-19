"""
Numeric correctness check for the header-coalescing change to
gemv_q6k_kernel (analogous to Thesis V6's gemv_q4k fix). Generates a real
random Q6_K weight matrix, computes the reference dot product via
vte/compiler/dequantizer.py's dequantize_q6_k (the kernel's own cited
reference), and compares against the actual GPU kernel output.
"""
import ctypes
import os
import sys

import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from vte.core.model import VTEModel
from vte.compiler.codegen import CodegenEngine
from vte.compiler.dequantizer import dequantize_q6_k

IN_FEATURES = 6144
OUT_FEATURES = 2048
N_SB = IN_FEATURES // 256
ROW_BYTES = N_SB * 210


def generate_real_q6_k_blocks(num_rows: int, row_bytes: int, seed: int) -> bytes:
    rng = np.random.RandomState(seed)
    blocks = bytearray(num_rows * row_bytes)
    n_sb = row_bytes // 210
    for r in range(num_rows):
        for sb in range(n_sb):
            offset = r * row_bytes + sb * 210
            # d menor que a faixa "generosa" original (0.001-0.5): com
            # sc int8 pleno (-128..127) e q ate 31, o produto d*sc*q podia
            # passar de ~2000 por peso -- somado sobre 6144 elementos,
            # estourava o range do fp16 (65504) e virava inf/NaN na
            # comparacao. Isto e um limite dos DADOS DE TESTE aleatorios,
            # nao um bug do kernel (as 5 primeiras amostras ja batiam
            # exatamente antes deste ajuste).
            d = rng.uniform(0.0005, 0.02)
            for i in range(128):
                blocks[offset + i] = rng.randint(0, 256)
            for i in range(64):
                blocks[offset + 128 + i] = rng.randint(0, 256)
            for i in range(16):
                blocks[offset + 192 + i] = rng.randint(0, 256)  # int8, qualquer byte pattern
            blocks[offset + 208:offset + 210] = np.array([d], dtype=np.float16).tobytes()
    return bytes(blocks)


def main():
    print(f"Shape: in_features={IN_FEATURES}, out_features={OUT_FEATURES}, n_sb={N_SB}, row_bytes={ROW_BYTES}")

    weight_bytes = generate_real_q6_k_blocks(OUT_FEATURES, ROW_BYTES, seed=42)
    total_weight_bytes = len(weight_bytes)
    assert total_weight_bytes == OUT_FEATURES * ROW_BYTES

    x_fp32 = np.random.RandomState(7).randn(IN_FEATURES).astype(np.float32)
    x_fp16 = x_fp32.astype(np.float16)
    x_fp16_as_fp32 = x_fp16.astype(np.float32)

    print("Computing CPU reference (dequantize_q6_k + dot product)...")
    W_ref = dequantize_q6_k(weight_bytes, OUT_FEATURES * IN_FEATURES).reshape(OUT_FEATURES, IN_FEATURES)
    ref_out = (W_ref @ x_fp16_as_fp32).astype(np.float16).astype(np.float32)

    model = VTEModel.from_pretrained("qwen3.5:2b-q6_k", use_hip_graph=False, enable_fusion=False)
    hip = model._hip
    arch = hip.get_gpu_architecture()

    x_block = hip.safe_malloc(x_fp16.nbytes, "val_x")
    w_block = hip.safe_malloc(total_weight_bytes, "val_w")
    out_block = hip.safe_malloc(OUT_FEATURES * 2, "val_out")
    hip.safe_memcpy_host_to_device(x_block, x_fp16.tobytes(), "val_x_h2d")
    hip.safe_memcpy_host_to_device(w_block, weight_bytes, "val_w_h2d")

    codegen = CodegenEngine()
    hsaco_path = codegen.compile_kernel("gemv_q6k", arch=arch, force_recompile=True)
    _, gemv_fn = hip.load_kernel(hsaco_path, "gemv_q6k_kernel")

    args = [
        x_block, w_block, out_block,
        ctypes.c_int(1), ctypes.c_int(1),
        ctypes.c_int(IN_FEATURES), ctypes.c_int(OUT_FEATURES),
        ctypes.c_void_p(0), ctypes.c_void_p(0), ctypes.c_float(1.0),
    ]
    hip.launch_kernel(gemv_fn, grid=(OUT_FEATURES, 1, 1), block=(64, 1, 1),
                       args=args, shared_mem=0, expected_args=10)
    hip.synchronize()

    out_bytes = bytearray(OUT_FEATURES * 2)
    hip.safe_memcpy_device_to_host(out_bytes, out_block, "output")
    gpu_out = np.frombuffer(out_bytes, dtype=np.float16).astype(np.float32)

    max_diff = np.max(np.abs(ref_out - gpu_out))
    mean_diff = np.mean(np.abs(ref_out - gpu_out))
    rel_diff = np.max(np.abs(ref_out - gpu_out) / (np.abs(ref_out) + 1e-3))

    print(f"\nMax abs diff: {max_diff:.6f}")
    print(f"Mean abs diff: {mean_diff:.6f}")
    print(f"Max relative diff: {rel_diff:.6f}")
    print(f"Reference sample [0:5]: {ref_out[:5]}")
    print(f"GPU sample       [0:5]: {gpu_out[:5]}")

    # Limiar RELATIVO, nao absoluto: a magnitude de saida do Q6_K (int8
    # scales, ate 127) fica bem maior que a do Q4_K (6-bit scales, ate 63)
    # -- um limiar absoluto calibrado pro Q4_K falharia aqui so por causa
    # da escala, nao por um erro real. 1% relativo e generoso o bastante
    # pra cobrir ruido normal de ordem de acumulacao fp16, mas apertado o
    # bastante pra pegar um bug real de layout/formula.
    if rel_diff < 0.01:
        print("\nPASSED: gemv_q6k_kernel output matches the dequantize_q6_k reference.")
        return True
    else:
        print("\nFAILED: gemv_q6k_kernel output diverges from reference.")
        return False


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
