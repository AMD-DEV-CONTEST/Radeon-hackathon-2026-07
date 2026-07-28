import struct
from pathlib import Path
from typing import Optional, Set

_FIXED_SIZES = {0: 1, 1: 1, 2: 2, 3: 2, 4: 4, 5: 4, 6: 4, 7: 1, 10: 8, 11: 8, 12: 8}
_FIXED_FORMATS = {
    0: "<B", 1: "<b", 2: "<H", 3: "<h", 4: "<I", 5: "<i",
    6: "<f", 7: "<?", 10: "<Q", 11: "<q", 12: "<d",
}
STRING_TYPE = 8
ARRAY_TYPE = 9


def _read_string(f) -> str:
    length = struct.unpack("<Q", f.read(8))[0]
    return f.read(length).decode("utf-8", errors="replace")


def _read_value(f, vtype: int):
    if vtype in _FIXED_FORMATS:
        return struct.unpack(_FIXED_FORMATS[vtype], f.read(_FIXED_SIZES[vtype]))[0]
    if vtype == STRING_TYPE:
        return _read_string(f)
    if vtype == ARRAY_TYPE:
        atype = struct.unpack("<I", f.read(4))[0]
        alen = struct.unpack("<Q", f.read(8))[0]
        return [_read_value(f, atype) for _ in range(alen)]
    raise ValueError(f"Tipo de valor GGUF desconhecido: {vtype}")


def _skip_value(f, vtype: int):
    if vtype in _FIXED_SIZES:
        f.read(_FIXED_SIZES[vtype])
    elif vtype == STRING_TYPE:
        _read_string(f)
    elif vtype == ARRAY_TYPE:
        atype = struct.unpack("<I", f.read(4))[0]
        alen = struct.unpack("<Q", f.read(8))[0]
        for _ in range(alen):
            _skip_value(f, atype)
    else:
        raise ValueError(f"Tipo de valor GGUF desconhecido: {vtype}")


def read_gguf_metadata(path: str | Path, wanted_keys: Optional[Set[str]] = None) -> dict:
    """Lê os pares chave/valor do header GGUF, extraindo apenas `wanted_keys` (ou todos, se None)."""
    result = {}
    with open(path, "rb") as f:
        f.read(4)   # magic
        f.read(4)   # version
        f.read(8)   # tensor_count
        kv_count = struct.unpack("<Q", f.read(8))[0]

        for _ in range(kv_count):
            key = _read_string(f)
            vtype = struct.unpack("<I", f.read(4))[0]

            if wanted_keys is not None and key not in wanted_keys:
                _skip_value(f, vtype)
                continue

            result[key] = _read_value(f, vtype)

    return result
