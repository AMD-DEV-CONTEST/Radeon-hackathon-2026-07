# Dual-algorithm architecture

## External seam

`snap_images(image, config, device=None)` is the only processing interface.
Callers provide a ComfyUI-compatible tensor and receive a list of tensors. The
interface owns device selection, input layout normalization, configuration
validation, batch iteration, and output normalization.

`pixel_snapper_node.py` is the ComfyUI adapter at this seam. It contains node
metadata and translates widget values into `SnapConfig`; it does not implement
image processing. CPU, CUDA, and ROCm are not separate adapters. `SnapConfig`
selects an algorithm inside the core without creating a second public API.

## Algorithm contract

`optimized` and `legacy_exact` serve different, explicit contracts:

| Algorithm | Contract | Execution model |
|---|---|---|
| `optimized` | Maximum parallelism and stable new semantics | Fully device-resident tensor pipeline |
| `legacy_exact` | Byte-identical output to canonical version 0.4 | Hybrid NumPy control/reduction plus GPU distance assignment and cell voting |

The compatibility algorithm is tested against commit
`58f4c8be28b1378ceb229b284ced7c4c4ef74abb`. Matching dimensions alone is
insufficient: every RGB channel must match.

## Optimized device invariant

After `_normalize_image_batch` selects a device, all image data, palettes,
profiles, cut tensors, vote keys, and outputs remain on that device. Scalar
transfers are limited to decisions whose result changes tensor shapes:

- convergence of K-Means iterations;
- existence and median spacing of detected peaks;
- resolved output grid dimensions.

There is no full-image host transfer in the optimized processing path. This
invariant is what makes that implementation native to PyTorch ROCm rather than
a CPU algorithm launched from an AMD-capable application.

## Palette quantization

An RGB pixel is packed into one 24-bit integer. `torch.unique` produces unique
colors, inverse pixel mapping, and frequency weights on-device. Weighted
K-Means++ therefore works on `U` unique colors instead of `N` pixels, where
`U <= N` and generated pixel art normally has `U << N` after source encoding.

Nearest-centroid assignments use the identity

`||x-c||² = ||x||² + ||c||² - 2 x cᵀ`.

The matrix product reaches rocBLAS through PyTorch on ROCm. Points are tiled so
the distance matrix contains at most 16 million elements. The asymptotic work
remains `O(U*K*I)`, but peak distance storage is bounded independently of image
size.

Cluster sums and masses use `index_add_`; no color cluster is accumulated in a
Python loop. Empty clusters retain their previous centroid.

## Grid recovery

Quantized RGB is projected to grayscale and differentiated two pixels apart.
Row and column absolute gradients are reduced into one-dimensional profiles.

Peak discovery consists of thresholding, strict local-maximum detection, and
one-dimensional max-pool suppression. X and Y estimates resolve to a shared
step unless only one axis contains evidence.

For each expected grid boundary, every candidate inside its search window is
gathered in one tensor. The strongest candidate passes a profile-relative
strength threshold; otherwise the uniform target is retained. A cumulative-max
projection produces strictly increasing boundaries while preserving their
count. This replaces the former stateful walker whose next search depended on
the previous cut and therefore serialized the axis.

## Cell voting

`torch.bucketize` maps source rows and columns to grid cells. Each source pixel
becomes a composite `(cell, palette_label)` vote key. Device-side unique
reduction counts the keys, and `scatter_reduce_(amax)` selects the modal color
for every cell concurrently.

Scores encode count first and packed RGB second. Equal counts therefore choose
the lexicographically smallest RGB value, matching the deterministic tie rule
of the earlier NumPy implementation without depending on K-Means label order.

The cell vote path is `O(N log N)` under the sorting implementation used by
`torch.unique`, with linear-size intermediate tensors. It avoids allocating a
`cell_count * palette_size` dense histogram, which would be prohibitive for a
1x grid on a megapixel image.

## Legacy-exact compatibility path

Several version 0.4 details are observable algorithm behavior rather than mere
implementation choices:

- NumPy `default_rng` supplies the PCG64 K-Means++ random sequence.
- K-Means sums use ordered float32 `np.add.at`; parallel atomic accumulation
  changes rounding and can change pixels at cluster boundaries.
- Grayscale profiles use NumPy float64 arithmetic.
- The serial walker changes its next target from the previous selected cut.
- Stabilization and tie behavior determine the final grid dimensions.

The exact mode therefore keeps those order-sensitive operations on CPU. The
selected accelerator computes full-pixel K-Means distances and assignments,
then performs all grid-cell votes in parallel. The quantized frame is moved
back to the device for final resampling, and the public output always remains
on the requested device.

This boundary is intentional. A fully parallel centroid reduction was tested
and rejected for this mode because floating-point association changed a small
number of output channels by one. Reproducing those sums on GPU would require a
strictly ordered reduction and would erase most of the useful parallelism.

## ROCm semantics

PyTorch ROCm intentionally reuses `torch.cuda`; HIP devices are represented as
`torch.device("cuda")`. The implementation checks availability through the
standard PyTorch interface and identifies the platform through
`torch.version.hip`. No CUDA source, custom extension, or warp-size assumption
appears in the core.

Operations used by the core are standard PyTorch tensor primitives with ROCm
implementations: unique reduction, matrix multiplication, index addition,
pooling, gather, bucketize, and scatter reduction. The exact path additionally
uses elementwise distance kernels and tiled argmin assignment.

## Benchmark discipline

GPU kernels launch asynchronously. A valid benchmark must synchronize before
starting and after completing each measured call. It must also include at least
one warm-up call so runtime initialization and kernel loading are not charged to
the steady-state measurement.

Report the following together:

- PyTorch version and `torch.version.hip`;
- GPU model and ROCm version;
- input dimensions and batch size;
- palette size, pixel-size mode, and iteration limit;
- median of multiple synchronized runs;
- output dimensions, because grid density changes cell-voting work.

CPU measurements validate behavior and provide a fallback baseline. They are
not evidence of AMD GPU throughput; ROCm performance claims require execution
on the target AMD hardware.
