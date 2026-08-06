from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

import numpy as np
import PyOpenColorIO as ocio
import torch

Aces2DisplayEncoding = Literal["srgb", "rec1886"]
ACES2_GPU_IMPLEMENTATION = "colorgraph.aces2-output-transform20-torch/v1"
_ACES2065_1 = "ACES2065-1"
_ACESCG = "ACEScg"
_ACESCCT = "ACEScct"
_LINEAR_REC709 = "Linear Rec.709 (sRGB)"
_SRGB = "sRGB Encoded Rec.709 (sRGB)"
_SLOG3 = "S-Log3 S-Gamut3.Cine"
_DLOG = "D-Log D-Gamut"

_AP0_TO_AP1 = (
    (1.4514393161456653, -0.2365107468937402, -0.2149285692519253),
    (-0.07655377339602057, 1.1762296998335731, -0.09967592643755223),
    (0.008316148425697719, -0.006032449791021028, 0.9977163013653234),
)
_AP1_TO_AP0 = (
    (0.6954522413574519, 0.14067869647029416, 0.16386906217225405),
    (0.044794563372037716, 0.8596711184564216, 0.0955343181715404),
    (-0.005525882558113544, 0.0040252103059786595, 1.0015006722521349),
)


@dataclass(frozen=True, slots=True)
class _Aces2CpuResources:
    reach: torch.Tensor
    cusp: torch.Tensor
    cusp_hues: torch.Tensor


@dataclass(frozen=True, slots=True)
class _Aces2DeviceResources:
    reach: torch.Tensor
    cusp: torch.Tensor
    cusp_hues: torch.Tensor


def _matrix(image: torch.Tensor, values: tuple[tuple[float, ...], ...]) -> torch.Tensor:
    matrix = image.new_tensor(values)
    return torch.einsum("ij,bjhw->bihw", matrix, image)


def _to_aces2065_1(image: torch.Tensor, source: str) -> torch.Tensor:
    if source == _ACES2065_1:
        return image
    if source == _ACESCG:
        return _matrix(image, _AP1_TO_AP0)
    if source == _LINEAR_REC709:
        return _matrix(
            image,
            (
                (0.4396329819194919, 0.3829886981515535, 0.1773783199289555),
                (0.08977644295884223, 0.813439428748978, 0.0967841282921771),
                (0.017541170383172787, 0.11154655330238722, 0.8709122763144425),
            ),
        )
    if source == _SRGB:
        linear = torch.where(
            image > 0.0392857157,
            torch.pow(torch.clamp_min(0.947867274 * image + 0.0521326996, 0.0), 2.4000001),
            image * 0.077380158,
        )
        return _to_aces2065_1(linear, _LINEAR_REC709)
    if source == _ACESCCT:
        linear_ap1 = torch.where(
            image > 0.155251175,
            torch.pow(2.0, (image - 0.5547945205479452) * 17.5200005),
            (image - 0.0729055703) * 0.0948745236,
        )
        return _matrix(linear_ap1, _AP1_TO_AP0)
    if source == _SLOG3:
        linear = torch.where(
            image > 0.167360976,
            0.189999998
            * (
                torch.pow(
                    10.0,
                    (image - 0.410557184750733) * 3.91204596,
                )
                - 0.0526315789473684
            ),
            (image - 0.0928641111) * 0.151013061,
        )
        return _matrix(
            linear,
            (
                (0.638788667185978, 0.272351433711262, 0.0888598991027595),
                (-0.00391590602528224, 1.0880732308973999, -0.0841573248721177),
                (-0.0299072021239151, -0.0264325799101947, 1.0563397820341101),
            ),
        )
    if source == _DLOG:
        linear = torch.where(
            image > 0.138583958,
            1.0109179
            * (
                torch.pow(
                    10.0,
                    (image - 0.58455504907396) * 3.89616013,
                )
                - 0.0108
            ),
            (image - 0.0929045379) * 0.165956274,
        )
        return _matrix(
            linear,
            (
                (0.691279245585754, 0.214382527745956, 0.0943382266682902),
                (0.0662224037667752, 1.0116160801876, -0.0778384839543733),
                (-0.0172985410341745, -0.0773788501012682, 1.0946773911354399),
            ),
        )
    raise ValueError(f"unsupported native GPU OCIO input space: {source!r}")


def apply_ocio_color_space_gpu(
    image: torch.Tensor,
    source: str,
    destination: str,
) -> torch.Tensor:
    """Execute every color-space pair used by the v3 renderer as torch ops."""

    if image.ndim != 4 or image.shape[1] != 3:
        raise ValueError("OCIO tensors must use NCHW layout with three RGB channels")
    working = image.float()
    if source == destination:
        return working
    aces2065_1 = _to_aces2065_1(working, source)
    if destination == _ACES2065_1:
        return aces2065_1
    if destination == _ACESCG:
        return _matrix(aces2065_1, _AP0_TO_AP1)
    raise ValueError(
        f"unsupported native GPU OCIO destination space: {destination!r}"
    )


@lru_cache(maxsize=4)
def _extract_cpu_resources(
    processor_cache_id: str,
    processor: ocio.Processor,
) -> _Aces2CpuResources:
    del processor_cache_id
    descriptor = ocio.GpuShaderDesc.CreateShaderDesc()
    descriptor.setLanguage(ocio.GPU_LANGUAGE_GLSL_4_0)
    processor.getDefaultGPUProcessor().extractGpuShaderInfo(descriptor)
    textures = {texture.textureName: texture for texture in descriptor.getTextures()}
    try:
        reach_texture = textures["ocio_reach_m_table_0"]
        cusp_texture = textures["ocio_gamut_cusp_table_0"]
    except KeyError as exc:
        raise RuntimeError("the frozen ACES 2 GPU processor textures changed") from exc
    reach_values = np.asarray(reach_texture.getValues(), dtype=np.float32)
    cusp_values = np.asarray(cusp_texture.getValues(), dtype=np.float32)
    if reach_values.shape != (363,) or cusp_values.shape != (1089,):
        raise RuntimeError("the frozen ACES 2 GPU processor texture shape changed")

    shader = descriptor.getShaderText()
    match = re.search(
        r"ocio_gamut_cusp_table_0_hues_array\[363\]\s*=\s*"
        r"float\[363\]\((.*?)\);",
        shader,
        flags=re.DOTALL,
    )
    if match is None:
        raise RuntimeError("the frozen ACES 2 GPU processor hue table changed")
    hue_values = np.fromstring(
        match.group(1).replace("f", "").replace(",", " "),
        sep=" ",
        dtype=np.float32,
    )
    if hue_values.shape != (363,):
        raise RuntimeError("the frozen ACES 2 GPU processor hue table shape changed")
    return _Aces2CpuResources(
        reach=torch.from_numpy(reach_values.copy()),
        cusp=torch.from_numpy(cusp_values.reshape(363, 3).copy()),
        cusp_hues=torch.from_numpy(hue_values.copy()),
    )


@lru_cache(maxsize=16)
def _device_resources(
    processor_cache_id: str,
    processor: ocio.Processor,
    device_value: str,
) -> _Aces2DeviceResources:
    cpu = _extract_cpu_resources(processor_cache_id, processor)
    device = torch.device(device_value)
    return _Aces2DeviceResources(
        reach=cpu.reach.to(device=device),
        cusp=cpu.cusp.to(device=device),
        cusp_hues=cpu.cusp_hues.to(device=device),
    )


def _reach_sample(resources: _Aces2DeviceResources, hue: torch.Tensor) -> torch.Tensor:
    base = torch.floor(hue).to(torch.long)
    low = (base + 1).clamp(0, resources.reach.shape[0] - 1)
    high = (low + 1).clamp(0, resources.reach.shape[0] - 1)
    fraction = hue - base
    return torch.lerp(resources.reach[low], resources.reach[high], fraction)


def _cusp_sample(resources: _Aces2DeviceResources, hue: torch.Tensor) -> torch.Tensor:
    high = torch.searchsorted(resources.cusp_hues, hue.contiguous(), right=False)
    high = high.clamp(1, resources.cusp_hues.shape[0] - 2)
    low = high - 1
    denominator = resources.cusp_hues[high] - resources.cusp_hues[low]
    fraction = ((hue - resources.cusp_hues[low]) / denominator).unsqueeze(-1)
    low_values = resources.cusp[low]
    high_values = resources.cusp[high]
    return torch.lerp(low_values, high_values, fraction).permute(0, 3, 1, 2)


def _tone_scale(j: torch.Tensor) -> torch.Tensor:
    a = 0.0323680267 * torch.pow(torch.abs(j) * 0.00999999978, 0.879464149)
    y = torch.pow((27.1299992 * a) / (1.0 - a), 2.3809523809523809)
    f = 1.04710376 * torch.pow(y / (y + 0.73009213709383403), 1.14999998)
    y_tone_scaled = torch.clamp_min(f * f / (f + 0.0399999991), 0.0)
    f_l_y = torch.pow(0.79370057210326195 * y_tone_scaled, 0.42)
    j_tone_scaled = 100.0 * torch.pow(
        (f_l_y / (27.1299992 + f_l_y)) * 30.8946857,
        1.13705599,
    )
    return torch.sign(j) * j_tone_scaled


def _toe(
    value: torch.Tensor,
    limit: torch.Tensor,
    k1_input: torch.Tensor,
    k2_input: torch.Tensor,
) -> torch.Tensor:
    k2 = torch.clamp_min(k2_input, 0.001)
    k1 = torch.sqrt(k1_input * k1_input + k2 * k2)
    k3 = (limit + k1) / (limit + k2)
    curved = 0.5 * (
        k3 * value
        - k1
        + torch.sqrt(
            (k3 * value - k1) * (k3 * value - k1)
            + 4.0 * k2 * k3 * value
        )
    )
    return torch.where(value > limit, value, curved)


def _focus_gain(j: torch.Tensor, cusp_j: torch.Tensor) -> torch.Tensor:
    threshold = torch.lerp(cusp_j, cusp_j.new_full((), 100.0), 0.3)
    gain = (100.0 - threshold) / torch.clamp_min(100.0 - j, 0.0001)
    gain = torch.log10(gain)
    return torch.where(j > threshold, gain * gain + 1.0, torch.ones_like(j))


def _solve_j_intersect(
    j: torch.Tensor,
    m: torch.Tensor,
    focus_j: torch.Tensor,
    slope_gain: torch.Tensor,
) -> torch.Tensor:
    m_scaled = m / slope_gain
    a = m_scaled / focus_j
    lower_b = 1.0 - m_scaled
    lower_c = -j
    lower_root = torch.sqrt(lower_b * lower_b - 4.0 * a * lower_c)
    lower = -2.0 * lower_c / (lower_b + lower_root)

    upper_b = -(1.0 + m_scaled + 100.0 * a)
    upper_c = 100.0 * m_scaled + j
    upper_root = torch.sqrt(upper_b * upper_b - 4.0 * a * upper_c)
    upper = -2.0 * upper_c / (upper_b - upper_root)
    return torch.where(j < focus_j, lower, upper)


def _gamut_boundary_intersection(
    cusp_j: torch.Tensor,
    cusp_m: torch.Tensor,
    gamma_top_inverse: torch.Tensor,
    j_intersect_source: torch.Tensor,
    j_intersect_cusp: torch.Tensor,
    slope: torch.Tensor,
) -> torch.Tensor:
    lower = (
        j_intersect_cusp
        * torch.pow(j_intersect_source / j_intersect_cusp, 0.877192974)
        / (cusp_j / cusp_m - slope)
    )
    upper = (
        cusp_m
        * (100.0 - j_intersect_cusp)
        * torch.pow(
            (100.0 - j_intersect_source) / (100.0 - j_intersect_cusp),
            gamma_top_inverse,
        )
        / (slope * cusp_m + 100.0 - cusp_j)
    )
    smoothing = 0.119999997 * cusp_m
    weight = torch.clamp_min(smoothing - torch.abs(lower - upper), 0.0) / smoothing
    return torch.minimum(lower, upper) - weight.pow(3) * smoothing / 6.0


def _remap_m(
    m: torch.Tensor,
    gamut_boundary_m: torch.Tensor,
    reach_boundary_m: torch.Tensor,
) -> torch.Tensor:
    boundary_ratio = gamut_boundary_m / reach_boundary_m
    proportion = torch.clamp_min(boundary_ratio, 0.75)
    threshold = proportion * gamut_boundary_m
    m_offset = m - threshold
    gamut_offset = gamut_boundary_m - threshold
    reach_offset = reach_boundary_m - threshold
    scale = reach_offset / (reach_offset / gamut_offset - 1.0)
    remapped = threshold + scale * (m_offset / scale) / (1.0 + m_offset / scale)
    return torch.where((proportion >= 1.0) | (m <= threshold), m, remapped)


def _gamut_compress(
    jmh: torch.Tensor,
    cusp: torch.Tensor,
    reach_max_m: torch.Tensor,
) -> torch.Tensor:
    j, m, hue = jmh.unbind(dim=1)
    cusp_j, cusp_m, gamma_top_inverse = cusp.unbind(dim=1)
    focus_j = torch.lerp(
        cusp_j,
        cusp_j.new_full((), 34.096539),
        torch.minimum(
            torch.ones_like(cusp_j),
            1.3 - cusp_j / 100.0,
        ),
    )
    slope_gain = 135.0 * _focus_gain(j, cusp_j)
    intersect_source = _solve_j_intersect(j, m, focus_j, slope_gain)
    gamut_slope = torch.where(
        intersect_source < focus_j,
        intersect_source,
        100.0 - intersect_source,
    )
    gamut_slope = (
        gamut_slope
        * (intersect_source - focus_j)
        / (focus_j * slope_gain)
    )
    intersect_cusp = _solve_j_intersect(
        cusp_j,
        cusp_m,
        focus_j,
        slope_gain,
    )
    gamut_boundary_m = _gamut_boundary_intersection(
        cusp_j,
        cusp_m,
        gamma_top_inverse,
        intersect_source,
        intersect_cusp,
        gamut_slope,
    )
    reach_boundary_m = (
        100.0
        * torch.pow(intersect_source / 100.0, 0.879464149)
        / (100.0 / reach_max_m - gamut_slope)
    )
    remapped_m = _remap_m(m, gamut_boundary_m, reach_boundary_m)
    remapped_j = intersect_source + remapped_m * gamut_slope
    compressed = torch.stack((remapped_j, remapped_m, hue), dim=1)
    no_chroma = torch.stack((j, torch.zeros_like(m), hue), dim=1)
    invalid = (m <= 0.0) | (j > 100.0) | (gamut_boundary_m <= 0.0)
    return torch.where(invalid.unsqueeze(1), no_chroma, compressed)


def apply_aces2_output_transform(
    image_aces2065_1: torch.Tensor,
    *,
    processor: ocio.Processor,
    encoding: Aces2DisplayEncoding,
) -> torch.Tensor:
    """Execute the frozen OCIO ACES 2 SDR GPU shader as native torch ops."""

    if image_aces2065_1.ndim != 4 or image_aces2065_1.shape[1] != 3:
        raise ValueError("ACES 2 tensors must use NCHW layout with three RGB channels")
    image = image_aces2065_1.float()
    resources = _device_resources(
        processor.getCacheID(),
        processor,
        str(image.device),
    )

    # These constants are transcribed from the official OCIO 2.5 GPU shader
    # generated by studio-config-v4.0.0_aces-v2.0_ocio-v2.5.
    rgb = _matrix(image, _AP0_TO_AP1).clamp(0.0, 1024.0)
    rgb = _matrix(
        rgb,
        (
            (0.6954522413574518, 0.14067869647029416, 0.16386906217225403),
            (0.04479456337203763, 0.8596711184564216, 0.09553431817154036),
            (-0.005525882558113544, 0.004025210305978659, 1.0015006722521349),
        ),
    )

    lms = _matrix(
        rgb,
        (
            (0.445181042, 0.34964928, -0.00112973212),
            (0.123734146, 0.613643706, 0.0563228019),
            (0.0117007261, 0.0280607939, 0.753939033),
        ),
    )
    f_l = torch.pow(torch.abs(lms), 0.419999987)
    rgb_a = torch.sign(lms) * f_l / (27.1299992 + f_l)
    aab = _matrix(
        rgb_a,
        (
            (20.25881, 10.129405, 0.506470263),
            (15480.0, -16887.2734, 1407.27271),
            (1720.0, 1720.0, -3440.0),
        ),
    )
    a, opponent_a, opponent_b = aab.unbind(dim=1)
    valid = a > 0.0
    j = 100.0 * torch.pow(torch.clamp_min(a, 0.0), 1.13705599)
    m = torch.sqrt(opponent_a * opponent_a + opponent_b * opponent_b)
    hue = torch.rad2deg(torch.atan2(opponent_b, opponent_a)).remainder(360.0)
    j = torch.where(valid, j, torch.zeros_like(j))
    m = torch.where(valid, m, torch.zeros_like(m))
    hue = torch.where(valid & (opponent_a != 0.0), hue, torch.zeros_like(hue))

    cosine = torch.cos(torch.deg2rad(hue))
    sine = torch.sin(torch.deg2rad(hue))
    tone_scaled_j = _tone_scale(j)
    reach_max_m = _reach_sample(resources, hue)
    nonzero_chroma = m != 0.0
    normalized_j = tone_scaled_j / 100.0
    shadow_j = torch.clamp_min(1.0 - normalized_j, 0.0)
    cosine2 = 2.0 * cosine * cosine - 1.0
    sine2 = 2.0 * cosine * sine
    cosine3 = 4.0 * cosine.pow(3) - 3.0 * cosine
    sine3 = 3.0 * sine - 4.0 * sine.pow(3)
    m_normalization = (
        cosine * 11.341321604032515
        + cosine2 * 16.469863649185896
        + cosine3 * 7.8842182208776475
        + sine * 14.665187919584513
        + sine2 * -6.372578035440444
        + sine3 * 9.19412770544529
        + 77.1330515473938
    )
    limit = torch.pow(normalized_j, 0.879464149) * reach_max_m / m_normalization
    safe_j = torch.where(j == 0.0, torch.ones_like(j), j)
    compressed_m = m * torch.pow(tone_scaled_j / safe_j, 0.879464149)
    compressed_m = compressed_m / m_normalization
    compressed_m = limit - _toe(
        limit - compressed_m,
        limit - 0.001,
        shadow_j * 1.29999995,
        torch.sqrt(normalized_j * normalized_j + 0.00499999989),
    )
    compressed_m = _toe(
        compressed_m,
        limit,
        normalized_j * 2.4000001,
        shadow_j,
    )
    compressed_m = compressed_m * m_normalization
    compressed_m = torch.where(nonzero_chroma, compressed_m, m)
    jmh = torch.stack((tone_scaled_j, compressed_m, hue), dim=1)

    cusp = _cusp_sample(resources, hue)
    jmh = _gamut_compress(jmh, cusp, reach_max_m)
    j, m, _ = jmh.unbind(dim=1)
    aab = torch.stack(
        (
            torch.pow(j * 0.00999999978, 0.879464149),
            m * cosine,
            m * sine,
        ),
        dim=1,
    )
    rgb_a = _matrix(
        aab,
        (
            (0.0323680267, 2.07657631e-05, 1.3260621e-05),
            (0.0323680267, -4.10250432e-05, -1.20174373e-05),
            (0.0323680267, -1.01296409e-05, -0.000290076074),
        ),
    )
    rgb_a_limited = torch.minimum(
        torch.abs(rgb_a),
        rgb_a.new_full((), 0.99000001),
    )
    lms = torch.sign(rgb_a) * torch.pow(
        27.1299992 * rgb_a_limited / (1.0 - rgb_a_limited),
        2.38095236,
    )
    output = _matrix(
        lms,
        (
            (7.45048571, -6.1301837, -0.0603808537),
            (-1.4750675, 3.11835742, -0.383369029),
            (0.0106288502, -0.31857267, 1.56786489),
        ),
    ).clamp(0.0, 1.0)

    if encoding == "rec1886":
        return torch.sign(output) * torch.pow(torch.abs(output), 1.0 / 2.4)
    if encoding != "srgb":
        raise ValueError(f"unsupported ACES 2 display encoding: {encoding}")
    absolute = torch.abs(output)
    encoded = torch.where(
        absolute > 0.00303993467,
        torch.pow(absolute, 0.416666657) * 1.05499995 - 0.0549999997,
        absolute * 12.9232101,
    )
    return torch.sign(output) * encoded


def clear_aces2_gpu_caches() -> None:
    _device_resources.cache_clear()
    _extract_cpu_resources.cache_clear()
