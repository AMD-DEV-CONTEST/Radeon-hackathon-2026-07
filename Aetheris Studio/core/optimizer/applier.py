"""
Deterministic Parameter Transformation Applier.
Applies UNROLL_FACTOR transformations to cloned HIP kernel templates using direct C++ source text substitution on the actual pragma in the template, not on non-existent Jinja-style placeholders.

The BLOCK_SIZE substitution that used to live here (rewriting
`__shared__ float warp_sums[N]`) was removed: it never changed the real
launch geometry and was latently unsafe. See core/optimizer/catalog.py's
module docstring for the full finding.
"""

from pathlib import Path
from core.optimizer.catalog import CatalogValidator, ParameterizedTransformation


class TransformationApplier:
    def apply(self, template_path: Path, transformation: ParameterizedTransformation) -> str:
        if not CatalogValidator.validate_params(transformation.params):
            raise ValueError(f"Invalid parameter configuration for transformation: {transformation.transformation_id}")

        with open(template_path, "r", encoding="utf-8") as f:
            code = f.read()

        unroll_factor = transformation.params.get("UNROLL_FACTOR")

        rendered_code = code
        if unroll_factor is not None and unroll_factor > 1:
            # Deliberately anchored to the bare pragma so re-applying to an
            # already-transformed file is a no-op rather than producing
            # "#pragma unroll 4 8".
            rendered_code = rendered_code.replace(
                '#pragma unroll\n',
                f'#pragma unroll {unroll_factor}\n',
            )

        return rendered_code
