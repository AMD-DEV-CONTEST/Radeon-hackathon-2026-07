# ROCm Model Compatibility Matrix

> Version: AetherDB V1.31.2  
> Runtime target: ROCm 7.2.4 competition image  
> Important: a supported code path or installed package is not hardware evidence.

## Native Trusted Packages

| Package | Runtime | Expected probe | Competition status in this workspace |
|---|---|---|---|
| `aetherdb.bge-m3` | `rocm_migraphx` | Two multilingual texts, 1024-dimensional normalized embeddings | Contract complete; W7900 probe required |
| `aetherdb.bge-vl-base` | `rocm_pytorch` | Image/text feature extraction, 512-dimensional normalization | Contract complete; weights and W7900 probe required |
| `aetherdb.kandinsky-2-2` | `rocm_pytorch` | Bounded real generated image, output digest and dimensions | Contract complete; weights and W7900 probe required |

BGE-M3 remains the default AetherDB-owned multilingual text embedding model.
The competition image installs `onnxruntime_migraphx==1.23.2` from AMD's pinned
ROCm 7.2.4 package index and preserves the official PyTorch ROCm runtime for
BGE-VL and Kandinsky.

## Evidence Levels

```text
package installed
!= Worker loaded
!= platform ROCm verified
!= model VERIFIED_ROCM
!= multi-model coexistence verified
```

- Platform evidence proves device access and one real framework calculation.
- Model evidence is created only by the isolated Worker probe and is tied to
  package version, manifest digest, device fingerprint and backend.
- Coexistence evidence is a separate pairwise benchmark for shared leases.
- Expired or mismatched evidence is ignored by the Resource Scheduler.

## CUDA Compatibility

Ordinary deployments retain `cuda` in all applicable trusted manifests.
NVIDIA evidence must be collected independently as `VERIFIED_CUDA` against the
exact device fingerprint and package. A ROCm result never proves CUDA support,
and the competition profile deliberately blocks CUDA while
`REQUIRE_ROCM=true`.

## User-Owned Models

User-trained or otherwise arbitrary models are not restricted to the trusted
catalog. They can be discovered through the user's external Ollama/Provider,
remain disabled until explicit capability confirmation, and then participate
in unique model routing.

They do not:

- execute inside AetherDB native Workers;
- create native `VERIFIED_ROCM` evidence;
- replace AetherDB-owned BGE-M3;
- bypass permission, privacy, fallback or author-approval rules;
- make AetherDB responsible for their weights or runtime.

## Audio and Video

No default native audio model is selected, so there is no audio ROCm claim.
Video derivation remains a conditional NO-GO and has no ROCm execution path.

## Required Real Hardware Evidence

For each demonstrated package, retain only a bounded private report containing:

- package ID, version and manifest digest;
- backend and Worker adapter;
- AMD device fingerprint and driver/runtime versions;
- probe operation, elapsed time, memory counters and output digest;
- verification timestamp and optional expiry;
- no prompts, source text, media bytes, API keys, local paths or model weights.

The private report must not enter Git, a public release archive or the GPT
project overview.
