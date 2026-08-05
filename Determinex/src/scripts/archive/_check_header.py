import struct
gguf = '/workspace/outputs/determinex-engineer-v9/determinex-engineer-v9.gguf'
with open(gguf, 'rb') as f:
    magic = f.read(4)
    version = struct.unpack('<I', f.read(4))[0]
    n_tensors = struct.unpack('<Q', f.read(8))[0]
    n_kv = struct.unpack('<Q', f.read(8))[0]
print(f'Magic   : {magic}')
print(f'Version : {version}')
print(f'Tensors : {n_tensors}')
print(f'KV pairs: {n_kv}')
print('HEADER: OK' if magic == b'GGUF' else 'HEADER: CORRUPT')
