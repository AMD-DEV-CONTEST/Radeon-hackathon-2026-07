#!/usr/bin/env python3
"""Verify the pinned Qwen3-32B BnB snapshot without loading model tensors."""

from __future__ import annotations

import collections
import hashlib
import json
import os
import socket
import struct
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ID = "unsloth/Qwen3-32B-bnb-4bit"
REVISION = "7f721e74a6a8cc9ee352f7e49303a2c1705f9083"
ENDPOINT = "https://hf-mirror.com"
EXPECTED_HOSTNAME = "u-7701-ae3eba8a"
EXPECTED_MACHINE_ID_SHA256 = "7c225d1717bb5f671c4bf071b1df172abdc72a50a3ed53e24de9ab724d35ad54"
EXPECTED_TOTAL_BYTES = 19_228_117_804
EXPECTED_HEADER_KEYS = 2_947
EXPECTED_PROJECTION_WEIGHTS = 448
EXPECTED_DTYPE_SUMMARY = {
    "BF16": {"bytes": 3_113_003_008, "tensors": 259},
    "F32": {"bytes": 8_105_984, "tensors": 1_344},
    "U8": {"bytes": 16_090_475_989, "tensors": 1_344},
}
ROOT = Path("/workspace/qwen36-agentic-sft")
MODEL = ROOT / "models" / "Qwen3-32B-bnb-4bit-7f721e74"
OUTPUT = ROOT / "artifacts" / "model-acquisition" / "qwen3-32b-bnb-7f721e74-verification.json"
ACQUISITION_RUN = ROOT / "runs" / "model-acquisition-qwen3-32b-7f721e74"
FILES: dict[str, dict[str, Any]] = {
    ".gitattributes": {"size": 1570, "git_blob": "52373fe24473b1aa44333d318f578ae6bf04b49b"},
    "README.md": {"size": 15910, "git_blob": "0b6662d261b2cd9a01e530fb24b29c0eb4e33283"},
    "added_tokens.json": {"size": 707, "git_blob": "b54f9135e44c1e81047e8d05cb027af8bc039eed"},
    "chat_template.jinja": {"size": 4673, "git_blob": "ba899982bb3df102af1c0e6979230dd568ae8b5e"},
    "config.json": {"size": 1330, "git_blob": "74380149cf47bb19f6d87b4aa4ff55b76d10b563"},
    "generation_config.json": {"size": 237, "git_blob": "ee3927bf194485dacaf1ce45a82559d8caa9770e"},
    "merges.txt": {"size": 1671853, "git_blob": "31349551d90c7606f325fe0f11bbb8bd5fa0d7c7"},
    "model-00001-of-00004.safetensors": {"size": 4942503285, "sha256": "8ae891023702413f05a85e3d20975a09505b8dcb9ae91fc457ea88d910e7d6b6"},
    "model-00002-of-00004.safetensors": {"size": 4963718184, "sha256": "1c15182c6cdc9a849e9ac36149b256e684a2f117242d5db5fea80b74bb8ffe2b"},
    "model-00003-of-00004.safetensors": {"size": 4982643947, "sha256": "d8edd9dbceafe1ee56280b935e2bc8273c615f22105a80a5f0cde5e04a0b734f"},
    "model-00004-of-00004.safetensors": {"size": 4323070149, "sha256": "9488e8b825458b051e55e0d6b4be3a514a0111db5f35399df097d31d55942604"},
    "model.safetensors.index.json": {"size": 275324, "git_blob": "9b679664d91bf9dce45aef9ec2a7fd81148ef04a"},
    "special_tokens_map.json": {"size": 614, "git_blob": "9b8043f10c758210957b050c77f14d6282f33a52"},
    "tokenizer.json": {"size": 11422654, "sha256": "aeb13307a71acd8fe81861d94ad54ab689df773318809eed3cbe794b4492dae4"},
    "tokenizer_config.json": {"size": 10534, "git_blob": "d1ec9a059c60eb505a3032106532f118f2ed5cc6"},
    "vocab.json": {"size": 2776833, "git_blob": "4783fe10ac3adce15ac8f358ef5462739852c569"},
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def git_blob_sha1(path: Path) -> str:
    size = path.stat().st_size
    digest = hashlib.sha1(f"blob {size}\0".encode("ascii"))
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_create(path: Path, value: object) -> None:
    require(not path.exists(), f"output already exists: {path}")
    payload = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    partial = path.with_name(f".{path.name}.partial")
    descriptor = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(partial, path)
        partial.unlink()
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except BaseException:
        try:
            partial.unlink()
        except FileNotFoundError:
            pass
        raise


def parse_headers() -> dict[str, Any]:
    dtype_summary: dict[str, dict[str, int]] = collections.defaultdict(lambda: {"bytes": 0, "tensors": 0})
    tensor_inventory: dict[str, dict[str, Any]] = {}
    projection_dtypes: collections.Counter[str] = collections.Counter()
    bf16: list[dict[str, Any]] = []
    shards: dict[str, dict[str, Any]] = {}
    for shard in sorted(MODEL.glob("*.safetensors")):
        with shard.open("rb") as handle:
            header_length = struct.unpack("<Q", handle.read(8))[0]
            require(header_length < 64 * 1024 * 1024, f"implausible header: {shard}")
            header = json.loads(handle.read(header_length))
        data_bytes = 0
        tensor_count = 0
        for name, metadata in header.items():
            if name == "__metadata__":
                continue
            start, end = metadata["data_offsets"]
            require(0 <= start <= end, f"invalid offsets: {name}")
            size = end - start
            dtype = metadata["dtype"]
            require(name not in tensor_inventory, f"duplicate tensor: {name}")
            tensor_inventory[name] = {
                "dtype": dtype,
                "shape": metadata["shape"],
                "bytes": size,
                "shard": shard.name,
            }
            dtype_summary[dtype]["bytes"] += size
            dtype_summary[dtype]["tensors"] += 1
            data_bytes += size
            tensor_count += 1
            if name.endswith(".weight") and any(
                component in name
                for component in (
                    ".self_attn.q_proj.",
                    ".self_attn.k_proj.",
                    ".self_attn.v_proj.",
                    ".self_attn.o_proj.",
                    ".mlp.gate_proj.",
                    ".mlp.up_proj.",
                    ".mlp.down_proj.",
                )
            ):
                projection_dtypes[dtype] += 1
            if dtype == "BF16":
                bf16.append({"name": name, "shape": metadata["shape"], "bytes": size})
        shards[shard.name] = {
            "header_bytes": header_length,
            "tensor_count": tensor_count,
            "tensor_data_bytes": data_bytes,
        }
    weight_map = json.loads((MODEL / "model.safetensors.index.json").read_text(encoding="utf-8"))["weight_map"]
    require(set(weight_map) == set(tensor_inventory), "weight index and safetensors headers differ")
    require(len(tensor_inventory) == EXPECTED_HEADER_KEYS, "tensor-key count drift")
    require(dict(dtype_summary) == EXPECTED_DTYPE_SUMMARY, "dtype storage inventory drift")
    require(sum(".experts." in name for name in tensor_inventory) == 0, "unexpected expert tensor")
    require(projection_dtypes == {"U8": EXPECTED_PROJECTION_WEIGHTS}, "projection quantization drift")
    largest_bf16 = sorted(bf16, key=lambda item: (item["bytes"], item["name"]), reverse=True)
    require(largest_bf16[0]["name"] == "model.embed_tokens.weight", "largest BF16 tensor drift")
    require(largest_bf16[1]["name"] == "lm_head.weight", "second-largest BF16 tensor drift")
    require(largest_bf16[0]["bytes"] == 1_555_824_640, "embedding storage drift")
    require(largest_bf16[1]["bytes"] == 1_555_824_640, "LM-head storage drift")
    require(max(item["bytes"] for item in largest_bf16[2:]) <= 10_240, "unexpected large BF16 tensor")
    return {
        "tensor_keys": len(tensor_inventory),
        "dtype_summary": dict(dtype_summary),
        "projection_weight_count": sum(projection_dtypes.values()),
        "projection_dtype_counts": dict(projection_dtypes),
        "expert_key_count": 0,
        "largest_bf16": largest_bf16[:12],
        "shards": shards,
    }


def validate_tokenizer() -> dict[str, Any]:
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(MODEL, local_files_only=True, trust_remote_code=False)
    require(len(tokenizer) == 151_669, "tokenizer vocabulary drift")
    template_sha256 = hashlib.sha256(tokenizer.chat_template.encode("utf-8")).hexdigest()
    require(template_sha256 == "96fd16d36fb085260f9eb1e717b2c4e6e8b9e75a5e6504f66c8d6b128d82784d", "chat template drift")
    tools = [
        {
            "type": "function",
            "function": {
                "name": "read",
                "description": "Read a file",
                "parameters": {
                    "type": "object",
                    "properties": {"file_path": {"type": "string"}},
                    "required": ["file_path"],
                },
            },
        }
    ]
    messages = [
        {"role": "user", "content": "Read /tmp/x"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "type": "function",
                    "function": {"name": "read", "arguments": {"file_path": "/tmp/x"}},
                }
            ],
        },
        {"role": "tool", "content": "ok"},
    ]
    rendered = tokenizer.apply_chat_template(
        messages,
        tools=tools,
        tokenize=False,
        add_generation_prompt=False,
        enable_thinking=False,
    )
    for marker in ("<tools>", "</tools>", "<tool_call>", "</tool_call>", "<tool_response>", "</tool_response>"):
        require(marker in rendered, f"tool marker missing: {marker}")
    require('"name": "read"' in rendered and '"file_path": "/tmp/x"' in rendered, "tool payload drift")
    return {
        "vocab_size": len(tokenizer),
        "chat_template_sha256": template_sha256,
        "tool_render_sha256": hashlib.sha256(rendered.encode("utf-8")).hexdigest(),
        "tool_markers_present": True,
    }


def main() -> None:
    require(socket.gethostname() == EXPECTED_HOSTNAME, "remote hostname mismatch")
    machine_id_hash = hashlib.sha256(Path("/etc/machine-id").read_bytes()).hexdigest()
    require(machine_id_hash == EXPECTED_MACHINE_ID_SHA256, "remote machine-id mismatch")
    require(MODEL.is_dir() and not MODEL.is_symlink(), "model root is missing or a symlink")
    actual_names = {path.name for path in MODEL.iterdir() if path.is_file()}
    require(actual_names == set(FILES), "top-level file set drift")
    require((MODEL / ".cache").is_dir(), "download metadata cache missing before verification")
    require(sum(spec["size"] for spec in FILES.values()) == EXPECTED_TOTAL_BYTES, "expected-byte arithmetic drift")
    local_hashes: dict[str, str] = {}
    for name, contract in FILES.items():
        path = MODEL / name
        require(path.is_file() and not path.is_symlink(), f"missing or symlinked file: {name}")
        require(path.stat().st_size == contract["size"], f"size mismatch: {name}")
        local_sha256 = sha256_file(path)
        local_hashes[name] = local_sha256
        if "sha256" in contract:
            require(local_sha256 == contract["sha256"], f"LFS SHA256 mismatch: {name}")
        else:
            require(git_blob_sha1(path) == contract["git_blob"], f"Git blob mismatch: {name}")
    require(sum((MODEL / name).stat().st_size for name in FILES) == EXPECTED_TOTAL_BYTES, "local-byte total drift")
    config = json.loads((MODEL / "config.json").read_text(encoding="utf-8"))
    require(config["architectures"] == ["Qwen3ForCausalLM"], "architecture drift")
    require(config["model_type"] == "qwen3", "model type drift")
    require(config["num_hidden_layers"] == 64, "layer count drift")
    require(config["hidden_size"] == 5120 and config["intermediate_size"] == 25600, "model dimensions drift")
    require(config["vocab_size"] == 151936, "config vocabulary drift")
    quant = config["quantization_config"]
    require(quant["load_in_4bit"] is True and quant["load_in_8bit"] is False, "quantization mode drift")
    require(quant["bnb_4bit_quant_type"] == "nf4", "quantization type drift")
    require(quant["bnb_4bit_use_double_quant"] is True, "double-quant drift")
    require(quant["bnb_4bit_compute_dtype"] == "bfloat16", "compute dtype drift")
    require(quant["bnb_4bit_quant_storage"] == "uint8", "quant storage drift")
    require(quant["quant_method"] == "bitsandbytes", "quant method drift")
    header_audit = parse_headers()
    tokenizer_audit = validate_tokenizer()
    launch_path = ACQUISITION_RUN / "launch.json"
    status_path = ACQUISITION_RUN / "final_status.json"
    launch = json.loads(launch_path.read_text(encoding="utf-8"))
    status = json.loads(status_path.read_text(encoding="utf-8"))
    require(launch["revision"] == REVISION and launch["endpoint"] == ENDPOINT, "launch provenance drift")
    require(status["status"] == "DOWNLOADED_NOT_YET_VERIFIED", "download status drift")
    require(status["revision"] == REVISION and status["endpoint"] == ENDPOINT, "download provenance drift")
    result = {
        "schema_version": "qwen3_32b_bnb_snapshot_verification.v1",
        "status": "PASS",
        "verified_at_utc": utc_now(),
        "repo_id": REPO_ID,
        "revision": REVISION,
        "download_endpoint": ENDPOINT,
        "model_path": str(MODEL),
        "model_files": len(FILES),
        "model_bytes": EXPECTED_TOTAL_BYTES,
        "hostname": EXPECTED_HOSTNAME,
        "machine_id_sha256": machine_id_hash,
        "file_sha256": local_hashes,
        "header_audit": header_audit,
        "tokenizer_audit": tokenizer_audit,
        "acquisition": {
            "launch_path": str(launch_path),
            "launch_sha256": sha256_file(launch_path),
            "final_status_path": str(status_path),
            "final_status_sha256": sha256_file(status_path),
        },
        "verification_script": {
            "path": str(Path(__file__).resolve()),
            "sha256": sha256_file(Path(__file__).resolve()),
        },
    }
    atomic_create(OUTPUT, result)
    print(json.dumps({"status": "PASS", "output": str(OUTPUT), "sha256": sha256_file(OUTPUT)}, sort_keys=True))


if __name__ == "__main__":
    main()
