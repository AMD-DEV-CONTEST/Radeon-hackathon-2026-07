from __future__ import annotations

from functools import lru_cache

import numpy as np
import torch

from colorgraph.domain.grade_graph import ColorSpace

SONY_SLOG3_SGAMUT3CINE = "sony_slog3_sgamut3cine"
DJI_DLOG_DGAMUT = "dji_dlog_dgamut"
DJI_MAVIC3_DLOG_REC709 = "dji_mavic3_dlog_rec709_v1"
SUPPORTED_LOG_PROFILES = frozenset(
    {
        SONY_SLOG3_SGAMUT3CINE,
        DJI_DLOG_DGAMUT,
        DJI_MAVIC3_DLOG_REC709,
    }
)

# Sony's S-Log3 technical summary and the ACES reference CSC both define
# S-Gamut3.Cine from these D65 chromaticities. Generate the D65-to-D65 matrix
# from that source data instead of maintaining hand-copied coefficients.
#
# Sony: https://pro.sony/s3/cms-static-content/uploadfile/06/1237494271406.pdf
# ACES: https://github.com/aces-aswf/aces-input-and-colorspaces/blob/main/sony/
#       CSC.Sony.SLog3_SGamut3Cine_to_ACES.ctl
SONY_SGAMUT3CINE_PRIMARIES = (
    (0.766, 0.275),
    (0.225, 0.800),
    (0.089, -0.087),
)
REC709_PRIMARIES = (
    (0.640, 0.330),
    (0.300, 0.600),
    (0.150, 0.060),
)
ACES_AP1_PRIMARIES = (
    (0.713, 0.293),
    (0.165, 0.830),
    (0.128, 0.044),
)
D65_WHITE = (0.3127, 0.3290)
ACES_WHITE = (0.32168, 0.33767)
CAT02 = np.asarray(
    [
        [0.7328, 0.4296, -0.1624],
        [-0.7036, 1.6975, 0.0061],
        [0.0030, 0.0136, 0.9834],
    ],
    dtype=np.float64,
)
BRADFORD = np.asarray(
    [
        [0.8951, 0.2664, -0.1614],
        [-0.7502, 1.7135, 0.0367],
        [0.0389, -0.0685, 1.0296],
    ],
    dtype=np.float64,
)
CAT16 = np.asarray(
    [
        [0.401288, 0.650173, -0.051461],
        [-0.250268, 1.204414, 0.045854],
        [-0.002079, 0.048952, 0.953127],
    ],
    dtype=np.float64,
)


def _rgb_to_xyz_matrix(
    primaries: tuple[tuple[float, float], ...],
    white: tuple[float, float],
) -> np.ndarray:
    primary_xyz = np.asarray(
        [[x / y, 1.0, (1.0 - x - y) / y] for x, y in primaries],
        dtype=np.float64,
    ).T
    white_x, white_y = white
    white_xyz = np.asarray(
        [white_x / white_y, 1.0, (1.0 - white_x - white_y) / white_y],
        dtype=np.float64,
    )
    scales = np.linalg.solve(primary_xyz, white_xyz)
    return primary_xyz * scales


def _xy_to_xyz(white: tuple[float, float]) -> np.ndarray:
    white_x, white_y = white
    return np.asarray(
        [white_x / white_y, 1.0, (1.0 - white_x - white_y) / white_y],
        dtype=np.float64,
    )


def _cat02_adaptation_matrix(
    source_white: tuple[float, float],
    destination_white: tuple[float, float],
) -> np.ndarray:
    if source_white == destination_white:
        return np.identity(3, dtype=np.float64)
    source_lms = CAT02 @ _xy_to_xyz(source_white)
    destination_lms = CAT02 @ _xy_to_xyz(destination_white)
    return np.linalg.solve(CAT02, np.diag(destination_lms / source_lms) @ CAT02)


def chromatic_adaptation_matrix(
    source_white: tuple[float, float],
    destination_white: tuple[float, float],
    *,
    method: str = "cat16",
) -> np.ndarray:
    """Return a full-adaptation XYZ matrix using CAT16 or Bradford."""
    if method == "cat16":
        cone_response = CAT16
    elif method == "bradford":
        cone_response = BRADFORD
    else:
        raise ValueError("chromatic adaptation method must be 'cat16' or 'bradford'")
    if source_white == destination_white:
        return np.identity(3, dtype=np.float64)
    source_lms = cone_response @ _xy_to_xyz(source_white)
    destination_lms = cone_response @ _xy_to_xyz(destination_white)
    return np.linalg.solve(
        cone_response,
        np.diag(destination_lms / source_lms) @ cone_response,
    )


def _rgb_to_rgb_matrix(
    source_primaries: tuple[tuple[float, float], ...],
    destination_primaries: tuple[tuple[float, float], ...],
    *,
    source_white: tuple[float, float] = D65_WHITE,
    destination_white: tuple[float, float] = D65_WHITE,
) -> tuple[tuple[float, ...], ...]:
    source_to_xyz = _rgb_to_xyz_matrix(source_primaries, source_white)
    destination_to_xyz = _rgb_to_xyz_matrix(destination_primaries, destination_white)
    adaptation = _cat02_adaptation_matrix(source_white, destination_white)
    matrix = np.linalg.solve(destination_to_xyz, adaptation @ source_to_xyz)
    return tuple(tuple(float(value) for value in row) for row in matrix)


SONY_SGAMUT3CINE_TO_REC709 = _rgb_to_rgb_matrix(
    SONY_SGAMUT3CINE_PRIMARIES,
    REC709_PRIMARIES,
)
REC709_TO_SONY_SGAMUT3CINE = _rgb_to_rgb_matrix(
    REC709_PRIMARIES,
    SONY_SGAMUT3CINE_PRIMARIES,
)
LINEAR_REC709_TO_ACES_AP1 = _rgb_to_rgb_matrix(
    REC709_PRIMARIES,
    ACES_AP1_PRIMARIES,
    source_white=D65_WHITE,
    destination_white=ACES_WHITE,
)
ACES_AP1_TO_LINEAR_REC709 = _rgb_to_rgb_matrix(
    ACES_AP1_PRIMARIES,
    REC709_PRIMARIES,
    source_white=ACES_WHITE,
    destination_white=D65_WHITE,
)
ACES_AP1_TO_XYZ = _rgb_to_xyz_matrix(ACES_AP1_PRIMARIES, ACES_WHITE)
XYZ_TO_ACES_AP1 = np.linalg.inv(ACES_AP1_TO_XYZ)
ACES_AP1_LUMA = tuple(float(value) for value in ACES_AP1_TO_XYZ[1])

# DJI D-Log / D-Gamut Whitepaper, revision 2017-09-29.
DJI_DGAMUT_TO_REC709 = (
    (1.6746, -0.5797, -0.0949),
    (-0.0981, 1.3340, -0.2359),
    (-0.0410, -0.2430, 1.2840),
)
REC709_TO_DJI_DGAMUT = (
    (0.6163, 0.2857, 0.0980),
    (0.0505, 0.7990, 0.1505),
    (0.0292, 0.1604, 0.8104),
)


def _planckian_xy(cct_kelvin: float) -> tuple[float, float]:
    if not 1667.0 <= cct_kelvin <= 25000.0:
        raise ValueError("CCT must be between 1667 K and 25000 K")
    temperature = float(cct_kelvin)
    if temperature <= 4000.0:
        x = (
            -0.2661239e9 / temperature**3
            - 0.2343580e6 / temperature**2
            + 0.8776956e3 / temperature
            + 0.179910
        )
    else:
        x = (
            -3.0258469e9 / temperature**3
            + 2.1070379e6 / temperature**2
            + 0.2226347e3 / temperature
            + 0.240390
        )
    if temperature <= 2222.0:
        y = -1.1063814 * x**3 - 1.34811020 * x**2 + 2.18555832 * x - 0.20219683
    elif temperature <= 4000.0:
        y = -0.9549476 * x**3 - 1.37418593 * x**2 + 2.09137015 * x - 0.16748867
    else:
        y = 3.0817580 * x**3 - 5.87338670 * x**2 + 3.75112997 * x - 0.37001483
    return float(x), float(y)


def _xy_to_uv1960(white: tuple[float, float]) -> tuple[float, float]:
    x, y = white
    denominator = -2.0 * x + 12.0 * y + 3.0
    return 4.0 * x / denominator, 6.0 * y / denominator


def _uv1960_to_xy(white: tuple[float, float]) -> tuple[float, float]:
    u, v = white
    denominator = 2.0 * u - 8.0 * v + 4.0
    return 3.0 * u / denominator, 2.0 * v / denominator


def cct_duv_to_xy(cct_kelvin: float, duv: float = 0.0) -> tuple[float, float]:
    """Approximate a CCT/Duv white point in CIE xy via the 1960 UCS."""
    cct = max(1667.0, min(25000.0, float(cct_kelvin)))
    base_uv = np.asarray(_xy_to_uv1960(_planckian_xy(cct)), dtype=np.float64)
    lower = max(1667.0, cct - 10.0)
    upper = min(25000.0, cct + 10.0)
    lower_uv = np.asarray(_xy_to_uv1960(_planckian_xy(lower)), dtype=np.float64)
    upper_uv = np.asarray(_xy_to_uv1960(_planckian_xy(upper)), dtype=np.float64)
    tangent = upper_uv - lower_uv
    tangent /= np.linalg.norm(tangent)
    normal = np.asarray([-tangent[1], tangent[0]], dtype=np.float64)
    if normal[1] < 0:
        normal *= -1
    adjusted = base_uv + normal * max(-0.05, min(0.05, float(duv)))
    return _uv1960_to_xy((float(adjusted[0]), float(adjusted[1])))


def grading_white_point(
    temperature: float,
    tint: float,
) -> tuple[float, float]:
    """Map normalized grading controls to an explicit CCT/Duv white point."""
    temperature = max(-1.0, min(1.0, float(temperature)))
    tint = max(-1.0, min(1.0, float(tint)))
    if temperature == 0.0 and tint == 0.0:
        return ACES_WHITE

    base_cct = 6000.0
    target_mired = 1e6 / base_cct + temperature * 60.0
    target_cct = max(2500.0, min(20000.0, 1e6 / target_mired))
    target_locus = cct_duv_to_xy(target_cct, -tint * 0.02)
    target_uv = np.asarray(_xy_to_uv1960(target_locus), dtype=np.float64)
    base_locus_uv = np.asarray(
        _xy_to_uv1960(cct_duv_to_xy(base_cct)),
        dtype=np.float64,
    )
    aces_uv = np.asarray(_xy_to_uv1960(ACES_WHITE), dtype=np.float64)
    shifted = aces_uv + target_uv - base_locus_uv
    return _uv1960_to_xy((float(shifted[0]), float(shifted[1])))


@lru_cache(maxsize=1024)
def _acescg_white_balance_matrix(
    temperature: float,
    tint: float,
    method: str,
) -> tuple[tuple[float, ...], ...]:
    target_white = grading_white_point(temperature, tint)
    adaptation = chromatic_adaptation_matrix(
        ACES_WHITE,
        target_white,
        method=method,
    )
    matrix = XYZ_TO_ACES_AP1 @ adaptation @ ACES_AP1_TO_XYZ
    return tuple(tuple(float(value) for value in row) for row in matrix)


def _as_fp32(image: torch.Tensor) -> torch.Tensor:
    return image if image.dtype in {torch.float32, torch.float64} else image.float()


def srgb_to_linear(image: torch.Tensor) -> torch.Tensor:
    image = _as_fp32(image)
    return torch.where(
        image <= 0.04045,
        image / 12.92,
        ((image + 0.055) / 1.055).pow(2.4),
    )


def linear_to_srgb(image: torch.Tensor) -> torch.Tensor:
    image = _as_fp32(image)
    safe = image.clamp_min(0)
    return torch.where(
        image <= 0.0031308,
        image * 12.92,
        1.055 * safe.pow(1 / 2.4) - 0.055,
    )


def bt709_oetf_to_linear(image: torch.Tensor) -> torch.Tensor:
    """Decode a scene-referred BT.709 OETF signal to scene-linear Rec.709."""
    image = _as_fp32(image)
    safe = ((image + 0.099) / 1.099).clamp_min(0)
    return torch.where(
        image < 0.081,
        image / 4.5,
        safe.pow(1 / 0.45),
    )


def linear_to_bt709_oetf(image: torch.Tensor) -> torch.Tensor:
    """Encode scene-linear Rec.709 with the ITU-R BT.709 OETF."""
    image = _as_fp32(image)
    safe = image.clamp_min(0)
    return torch.where(
        image < 0.018,
        image * 4.5,
        1.099 * safe.pow(0.45) - 0.099,
    )


def rec1886_to_linear(image: torch.Tensor) -> torch.Tensor:
    """Decode normalized BT.1886 display RGB with zero black level."""
    image = _as_fp32(image)
    return image.sign() * image.abs().pow(2.4)


def linear_to_rec1886(image: torch.Tensor) -> torch.Tensor:
    """Encode normalized display-linear RGB with the inverse BT.1886 EOTF."""
    image = _as_fp32(image)
    return image.sign() * image.abs().pow(1 / 2.4)


def acescg_to_acescct(image: torch.Tensor) -> torch.Tensor:
    """Encode scene-linear ACEScg/AP1 values as ACEScct without changing primaries."""
    image = _as_fp32(image)
    safe = image.clamp_min(torch.finfo(image.dtype).tiny)
    return torch.where(
        image <= 0.0078125,
        image * 10.5402377416545 + 0.0729055341958355,
        (torch.log2(safe) + 9.72) / 17.52,
    )


def acescct_to_acescg(image: torch.Tensor) -> torch.Tensor:
    """Decode ACEScct to scene-linear ACEScg/AP1 without changing primaries."""
    image = _as_fp32(image)
    encoded_break = 0.155251141552511
    return torch.where(
        image <= encoded_break,
        (image - 0.0729055341958355) / 10.5402377416545,
        torch.pow(2.0, image * 17.52 - 9.72),
    )


def linear_rec709_to_acescct(image: torch.Tensor) -> torch.Tensor:
    """Convert scene-linear Rec.709 D65 to ACEScct AP1 (D60)."""
    image = _as_fp32(image)
    matrix = image.new_tensor(LINEAR_REC709_TO_ACES_AP1)
    linear_ap1 = torch.einsum("ij,bjhw->bihw", matrix, image)
    return acescg_to_acescct(linear_ap1)


def acescct_to_linear_rec709(image: torch.Tensor) -> torch.Tensor:
    """Convert ACEScct AP1 (D60) to scene-linear Rec.709 D65."""
    linear_ap1 = acescct_to_acescg(image)
    matrix = linear_ap1.new_tensor(ACES_AP1_TO_LINEAR_REC709)
    return torch.einsum("ij,bjhw->bihw", matrix, linear_ap1)


def slog3_to_linear_rec709(image: torch.Tensor) -> torch.Tensor:
    """Decode full-range Sony S-Log3/S-Gamut3.Cine to scene-linear Rec.709 D65.

    The result is scene-linear working RGB, not display Rec.709 or sRGB. Values
    outside the nominal 0..1 code range are intentionally preserved.
    """
    image = _as_fp32(image)
    code = image
    cut = 171.2102946929 / 1023.0
    linear_sgamut = torch.where(
        code >= cut,
        torch.pow(10.0, (code * 1023.0 - 420.0) / 261.5) * 0.19 - 0.01,
        (code * 1023.0 - 95.0) * 0.01125 / (171.2102946929 - 95.0),
    )
    matrix = image.new_tensor(SONY_SGAMUT3CINE_TO_REC709)
    return torch.einsum("ij,bjhw->bihw", matrix, linear_sgamut)


def linear_rec709_to_slog3(image: torch.Tensor) -> torch.Tensor:
    """Encode scene-linear Rec.709 D65 RGB as full-range S-Log3/S-Gamut3.Cine."""
    image = _as_fp32(image)
    inverse_matrix = image.new_tensor(REC709_TO_SONY_SGAMUT3CINE)
    linear_sgamut = torch.einsum("ij,bjhw->bihw", inverse_matrix, image)
    cut = 0.01125
    safe = linear_sgamut.clamp_min(-0.009999)
    return torch.where(
        linear_sgamut >= cut,
        (420.0 + torch.log10((safe + 0.01) / 0.19) * 261.5) / 1023.0,
        (linear_sgamut * (171.2102946929 - 95.0) / 0.01125 + 95.0) / 1023.0,
    )


def dlog_dgamut_to_linear_rec709(image: torch.Tensor) -> torch.Tensor:
    """Decode DJI D-Log / D-Gamut into linear Rec.709 working RGB.

    The transfer function and matrix are the analytical transform published in
    DJI's D-Log / D-Gamut whitepaper. This is an input color transform, not a
    display-look LUT.
    """

    image = _as_fp32(image)
    code = image.clamp(0, 1)
    linear_dgamut = torch.where(
        code <= 0.14,
        (code - 0.0929) / 6.025,
        (torch.pow(10.0, 3.89616 * code - 2.27752) - 0.0108) / 0.9892,
    )
    matrix = image.new_tensor(DJI_DGAMUT_TO_REC709)
    return torch.einsum("ij,bjhw->bihw", matrix, linear_dgamut)


def linear_rec709_to_dlog_dgamut(image: torch.Tensor) -> torch.Tensor:
    """Encode linear Rec.709 RGB into DJI D-Log / D-Gamut."""

    image = _as_fp32(image)
    inverse_matrix = image.new_tensor(REC709_TO_DJI_DGAMUT)
    linear_dgamut = torch.einsum("ij,bjhw->bihw", inverse_matrix, image)
    safe_log_argument = (linear_dgamut * 0.9892 + 0.0108).clamp_min(1e-12)
    return torch.where(
        linear_dgamut <= 0.0078,
        6.025 * linear_dgamut + 0.0929,
        torch.log10(safe_log_argument) * 0.256663 + 0.584555,
    )


def log_to_linear_rec709(
    image: torch.Tensor,
    source_log_profile: str | None,
) -> torch.Tensor:
    if source_log_profile == SONY_SLOG3_SGAMUT3CINE:
        return slog3_to_linear_rec709(image)
    if source_log_profile == DJI_DLOG_DGAMUT:
        return dlog_dgamut_to_linear_rec709(image)
    if source_log_profile == DJI_MAVIC3_DLOG_REC709:
        from colorgraph.grading.lut import apply_cube_lut
        from colorgraph.grading.official_luts import (
            ensure_dji_mavic3_dlog_to_rec709_lut,
        )

        display_rec709 = apply_cube_lut(
            image,
            ensure_dji_mavic3_dlog_to_rec709_lut(),
            interpolation="trilinear",
        )
        return rec1886_to_linear(display_rec709)
    supported = ", ".join(sorted(SUPPORTED_LOG_PROFILES))
    raise ValueError(f"unsupported source log profile; expected one of: {supported}")


def linear_rec709_to_log(
    image: torch.Tensor,
    destination_log_profile: str | None,
) -> torch.Tensor:
    if destination_log_profile == SONY_SLOG3_SGAMUT3CINE:
        return linear_rec709_to_slog3(image)
    if destination_log_profile == DJI_DLOG_DGAMUT:
        return linear_rec709_to_dlog_dgamut(image)
    if destination_log_profile == DJI_MAVIC3_DLOG_REC709:
        raise ValueError(
            "DJI Mavic 3 D-Log output is unavailable because the official LUT has no inverse"
        )
    supported = ", ".join(sorted(SUPPORTED_LOG_PROFILES))
    raise ValueError(f"unsupported destination log profile; expected one of: {supported}")


def _explicit_color_space(value: ColorSpace | str) -> ColorSpace:
    try:
        color_space = value if isinstance(value, ColorSpace) else ColorSpace(value)
    except ValueError as exc:
        raise ValueError(f"unknown color space: {value!r}") from exc
    if color_space == ColorSpace.REC709:
        raise ValueError(
            "ambiguous legacy color space 'rec709'; use 'bt709_oetf', 'rec1886', or 'srgb'"
        )
    return color_space


def convert_color_space(
    image: torch.Tensor,
    source: ColorSpace | str,
    destination: ColorSpace | str,
    *,
    source_log_profile: str | None = None,
    destination_log_profile: str | None = None,
) -> torch.Tensor:
    """Convert between explicit RGB encodings through scene-linear Rec.709.

    The legacy ``rec709`` enum is intentionally rejected because v1 projects
    used it to mean sRGB. Renderer v1 owns that compatibility behavior.
    """
    image = _as_fp32(image)
    source_space = _explicit_color_space(source)
    destination_space = _explicit_color_space(destination)
    if source_space == destination_space:
        if source_space == ColorSpace.LOG and (
            source_log_profile is None or source_log_profile != destination_log_profile
        ):
            raise ValueError("log-to-log identity requires one matching explicit profile")
        return image

    if source_space == ColorSpace.LINEAR_REC709:
        linear = image
    elif source_space == ColorSpace.SRGB:
        linear = srgb_to_linear(image)
    elif source_space == ColorSpace.BT709_OETF:
        linear = bt709_oetf_to_linear(image)
    elif source_space == ColorSpace.REC1886:
        linear = rec1886_to_linear(image)
    elif source_space == ColorSpace.ACESCCT:
        linear = acescct_to_linear_rec709(image)
    elif source_space == ColorSpace.LOG:
        linear = log_to_linear_rec709(image, source_log_profile)
    else:  # pragma: no cover - enum exhaustiveness guard
        raise ValueError(f"unsupported source color space: {source_space.value}")

    if destination_space == ColorSpace.LINEAR_REC709:
        return linear
    if destination_space == ColorSpace.SRGB:
        return linear_to_srgb(linear)
    if destination_space == ColorSpace.BT709_OETF:
        return linear_to_bt709_oetf(linear)
    if destination_space == ColorSpace.REC1886:
        return linear_to_rec1886(linear)
    if destination_space == ColorSpace.ACESCCT:
        return linear_rec709_to_acescct(linear)
    if destination_space == ColorSpace.LOG:
        return linear_rec709_to_log(linear, destination_log_profile)
    raise ValueError(f"unsupported destination color space: {destination_space.value}")


def luminance(image: torch.Tensor) -> torch.Tensor:
    image = _as_fp32(image)
    weights = image.new_tensor([0.2126, 0.7152, 0.0722]).view(1, 3, 1, 1)
    return (image * weights).sum(dim=1, keepdim=True)


def apply_exposure(image: torch.Tensor, stops: float) -> torch.Tensor:
    image = _as_fp32(image)
    return image * (2.0**stops)


def apply_cdl(
    image: torch.Tensor,
    *,
    slope: tuple[float, float, float] = (1.0, 1.0, 1.0),
    offset: tuple[float, float, float] = (0.0, 0.0, 0.0),
    power: tuple[float, float, float] = (1.0, 1.0, 1.0),
) -> torch.Tensor:
    image = _as_fp32(image)
    slope_tensor = image.new_tensor(slope).view(1, 3, 1, 1)
    offset_tensor = image.new_tensor(offset).view(1, 3, 1, 1)
    power_tensor = image.new_tensor(power).view(1, 3, 1, 1).clamp(0.1, 10)
    return (image * slope_tensor + offset_tensor).clamp_min(0).pow(power_tensor)


def apply_asc_cdl(
    image: torch.Tensor,
    *,
    slope: tuple[float, float, float] = (1.0, 1.0, 1.0),
    offset: tuple[float, float, float] = (0.0, 0.0, 0.0),
    power: tuple[float, float, float] = (1.0, 1.0, 1.0),
    saturation: float = 1.0,
) -> torch.Tensor:
    """Apply ASC CDL in OCIO's no-clamp style, preserving negative SOP values."""
    if any(value <= 0 for value in power):
        raise ValueError("ASC CDL power values must be greater than zero")
    if saturation < 0:
        raise ValueError("ASC CDL saturation must be non-negative")
    image = _as_fp32(image)
    slope_tensor = image.new_tensor(slope).view(1, 3, 1, 1)
    offset_tensor = image.new_tensor(offset).view(1, 3, 1, 1)
    power_tensor = image.new_tensor(power).view(1, 3, 1, 1)
    sop = image * slope_tensor + offset_tensor
    powered = torch.where(sop <= 0, sop, sop.clamp_min(0).pow(power_tensor))
    if float(saturation) == 1.0:
        return powered
    luma = luminance(powered)
    return luma + (powered - luma) * float(saturation)


def apply_white_balance(
    image: torch.Tensor,
    temperature: float,
    tint: float,
) -> torch.Tensor:
    image = _as_fp32(image)
    temperature = max(-1.0, min(1.0, temperature))
    tint = max(-1.0, min(1.0, tint))
    gains = image.new_tensor(
        [
            1.0 + temperature * 0.12 + tint * 0.025,
            1.0 - abs(temperature) * 0.015 - tint * 0.05,
            1.0 - temperature * 0.12 + tint * 0.025,
        ]
    ).view(1, 3, 1, 1)
    return image * gains


def apply_acescg_white_balance(
    image: torch.Tensor,
    temperature: float,
    tint: float,
    *,
    method: str = "cat16",
) -> torch.Tensor:
    """Adapt ACEScg from D60 to a CCT/Duv grading white using CAT16/Bradford."""
    image = _as_fp32(image)
    clamped_temperature = max(-1.0, min(1.0, float(temperature)))
    clamped_tint = max(-1.0, min(1.0, float(tint)))
    if clamped_temperature == 0.0 and clamped_tint == 0.0:
        return image
    matrix_values = _acescg_white_balance_matrix(
        round(clamped_temperature, 6),
        round(clamped_tint, 6),
        method,
    )
    matrix = image.new_tensor(matrix_values)
    return torch.einsum("ij,bjhw->bihw", matrix, image)


def apply_contrast(image: torch.Tensor, amount: float) -> torch.Tensor:
    image = _as_fp32(image)
    amount = max(-0.85, min(1.5, amount))
    pivot = 0.18
    logarithmic = torch.log2(image.clamp_min(1e-6))
    adjusted = (logarithmic - torch.log2(image.new_tensor(pivot))) * (1.0 + amount) + torch.log2(
        image.new_tensor(pivot)
    )
    return torch.pow(2.0, adjusted)


def apply_saturation(image: torch.Tensor, amount: float) -> torch.Tensor:
    image = _as_fp32(image)
    gray = luminance(image)
    return gray + (image - gray) * (1.0 + max(-1.0, min(2.0, amount)))


def apply_highlights(image: torch.Tensor, amount: float) -> torch.Tensor:
    image = _as_fp32(image)
    amount = max(-1.0, min(1.0, amount))
    luma = luminance(image)
    highlight_mask = ((luma - 0.42) / 0.42).clamp(0, 1)
    highlight_mask = highlight_mask * highlight_mask * (3 - 2 * highlight_mask)
    return image * (1.0 + highlight_mask * amount * 0.45)


def apply_tone_curve(
    image: torch.Tensor,
    *,
    shadows: float = 0.0,
    midtones: float = 0.0,
    highlights: float = 0.0,
) -> torch.Tensor:
    image = _as_fp32(image)
    luma = luminance(image).clamp(0, 1)
    shadow_weight = (1 - luma / 0.5).clamp(0, 1).square()
    highlight_weight = ((luma - 0.5) / 0.5).clamp(0, 1).square()
    midtone_weight = (1 - torch.abs(luma - 0.5) * 2).clamp(0, 1).square()
    gain = (
        1
        + shadow_weight * max(-1.0, min(1.0, shadows)) * 0.35
        + midtone_weight * max(-1.0, min(1.0, midtones)) * 0.25
        + highlight_weight * max(-1.0, min(1.0, highlights)) * 0.35
    )
    return image * gain


def aces_ap1_luminance(image: torch.Tensor) -> torch.Tensor:
    image = _as_fp32(image)
    weights = image.new_tensor(ACES_AP1_LUMA).view(1, 3, 1, 1)
    return (image * weights).sum(dim=1, keepdim=True)


def _acescct_code_value(linear_value: float) -> float:
    if linear_value <= 0.0078125:
        return linear_value * 10.5402377416545 + 0.0729055341958355
    return float((np.log2(linear_value) + 9.72) / 17.52)


def apply_acescct_contrast(image: torch.Tensor, amount: float) -> torch.Tensor:
    """Apply contrast linearly around 18% gray in the ACEScct log encoding."""
    image = _as_fp32(image)
    slope = 1.0 + max(-0.85, min(1.5, float(amount)))
    pivot = image.new_tensor(_acescct_code_value(0.18))
    return pivot + (image - pivot) * slope


def apply_acescct_saturation(image: torch.Tensor, amount: float) -> torch.Tensor:
    """Adjust chroma in ACEScct using AP1 luminance coefficients."""
    image = _as_fp32(image)
    luma = aces_ap1_luminance(image)
    scale = 1.0 + max(-1.0, min(2.0, float(amount)))
    return luma + (image - luma) * scale


def apply_acescct_highlights(image: torch.Tensor, amount: float) -> torch.Tensor:
    """Adjust highlight exposure in ACEScct while preserving channel differences."""
    image = _as_fp32(image)
    amount = max(-1.0, min(1.0, float(amount)))
    luma = aces_ap1_luminance(image)
    start = image.new_tensor(_acescct_code_value(0.36))
    end = image.new_tensor(_acescct_code_value(4.0))
    weight = ((luma - start) / (end - start)).clamp(0, 1)
    weight = weight * weight * (3.0 - 2.0 * weight)
    return image + weight * amount * 0.08


def apply_acescct_tone(
    image: torch.Tensor,
    *,
    shadows: float = 0.0,
    midtones: float = 0.0,
    highlights: float = 0.0,
) -> torch.Tensor:
    """Apply region-weighted exposure offsets in the ACEScct log encoding."""
    image = _as_fp32(image)
    luma = aces_ap1_luminance(image)
    black = image.new_tensor(_acescct_code_value(0.005))
    white = image.new_tensor(_acescct_code_value(4.0))
    position = ((luma - black) / (white - black)).clamp(0, 1)
    shadow_weight = (1.0 - position).square()
    highlight_weight = position.square()
    midtone_weight = (1.0 - torch.abs(position * 2.0 - 1.0)).clamp(0, 1).square()
    offset = (
        shadow_weight * max(-1.0, min(1.0, float(shadows))) * 0.06
        + midtone_weight * max(-1.0, min(1.0, float(midtones))) * 0.05
        + highlight_weight * max(-1.0, min(1.0, float(highlights))) * 0.06
    )
    return image + offset


def soft_clip_highlights(
    image: torch.Tensor,
    *,
    threshold: float = 0.78,
) -> torch.Tensor:
    """Legacy v1/v2 display roll-off; renderer v3 uses the ACES 2 ODT."""
    image = _as_fp32(image)
    positive = image.clamp_min(0)
    headroom = 1.0 - threshold
    rolled = threshold + headroom * (1 - torch.exp(-(positive - threshold).clamp_min(0) / headroom))
    return torch.where(positive <= threshold, positive, rolled)
