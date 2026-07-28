"""
Discrete Parameterized Transformation Catalog and Schema Validator.
Defines static, safe, bounded parameter configurations for HIP kernels. The catalog targets gemv_q4k's unroll pragma, the one dimension tunable from the template alone without a structural C++ rewrite.

A BLOCK_SIZE dimension used to live here and was removed after direct
verification that it could not work: gemv_q4k's launch geometry is fixed
at 64 threads by GEMV_COALESCED_BLOCK in VTE's
vte/core/fallback_executor.py, and the template only ever READS it
(`int bs = blockDim.x;`). Rewriting the template's
`__shared__ float warp_sums[32]` therefore changed no thread count at
all; it only resized an already over-provisioned array, so every
"block size" measurement was really measuring the unroll change next to
it. It was also latently unsafe: the validator accepted BLOCK_SIZE=32,
which rendered `warp_sums[1]` while 64 real threads (2 warps) still
wrote `warp_sums[warp]`, an out-of-bounds shared-memory write. Restoring
a real block-size dimension means making GEMV_COALESCED_BLOCK itself
parameterizable, not editing the template.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class ParameterizedTransformation:
    kernel_name: str
    transformation_id: str
    params: Dict[str, Any]
    description: str


VALID_UNROLL_FACTORS = (1, 2, 4, 8, 16)


class CatalogValidator:
    @staticmethod
    def validate_params(params: Dict[str, Any]) -> bool:
        # Any key other than UNROLL_FACTOR is rejected rather than ignored:
        # silently accepting an unknown knob is how the removed BLOCK_SIZE
        # dimension went unnoticed for so long (see the module docstring).
        unknown = set(params) - {"UNROLL_FACTOR"}
        if unknown:
            return False

        unroll = params.get("UNROLL_FACTOR", 1)
        if not isinstance(unroll, int) or unroll not in VALID_UNROLL_FACTORS:
            return False
        return True


class TransformationCatalog:
    def __init__(self):
        self._catalog: Dict[str, List[ParameterizedTransformation]] = {
            "gemv_q4k": [
                ParameterizedTransformation(
                    kernel_name="gemv_q4k",
                    transformation_id="base",
                    params={"UNROLL_FACTOR": 1},
                    description="Default production configuration (compiler-managed unroll)",
                ),
                ParameterizedTransformation(
                    kernel_name="gemv_q4k",
                    transformation_id="unroll_2",
                    params={"UNROLL_FACTOR": 2},
                    description="Conservative explicit unroll(2), lowest register-pressure variant",
                ),
                ParameterizedTransformation(
                    kernel_name="gemv_q4k",
                    transformation_id="unroll_4",
                    params={"UNROLL_FACTOR": 4},
                    description="Explicit unroll(4) trading register pressure for ILP",
                ),
                ParameterizedTransformation(
                    kernel_name="gemv_q4k",
                    transformation_id="unroll_8",
                    params={"UNROLL_FACTOR": 8},
                    description="Aggressive unroll(8) for ILP saturation",
                ),
            ]
        }

    def get_transformations_for_kernel(self, kernel_name: str) -> List[ParameterizedTransformation]:
        return self._catalog.get(kernel_name, [])

    def get_default_transformation(self, kernel_name: str) -> Optional[ParameterizedTransformation]:
        items = self.get_transformations_for_kernel(kernel_name)
        return items[0] if items else None
