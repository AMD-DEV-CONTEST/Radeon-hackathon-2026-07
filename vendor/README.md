# Bundled inference sources

FastAgentFactory carries complete, reproducible source trees for all native inference servers used by the deployment:

- `llama.cpp-official`: unchanged baseline source at revision `f955e394bf94e01e5e36186d13c985727e5ef5b5`.
- `llama.cpp-amd`: AMD optimization source tree based on the same revision.
- `stable-diffusion.cpp`: image inference source at revision `833369da848e8e2f960fe1896a825e3a08ef9733`, including all recursive submodule contents required by CMake.

The AMD tree currently contains the same compute implementation as the official tree. It is built into a separately named binary and reported as `optimization_status=placeholder`. Future AMD/HIP kernel work belongs only in `llama.cpp-amd`; the official tree remains the reproducible benchmark baseline.

Both bundled source trees include llama.cpp's build-info templates but intentionally do not carry nested `.git` directories. Deployment passes the pinned upstream revision and build number to CMake explicitly, so `llama-server --version` remains deterministic after source synchronization.

All source trees retain their upstream license and attribution files. Deployment validates their pinned revision markers, synchronizes them to the inference host, and builds them there without requiring the inference host to access GitHub.

Image inference is not an AMD kernel optimization target in this repository. `stable-diffusion.cpp` is bundled only to make deployment reproducible on restricted networks; AMD kernel experiments remain isolated to `llama.cpp-amd`.
