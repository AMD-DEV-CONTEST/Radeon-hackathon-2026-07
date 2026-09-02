from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from pathlib import Path

import cv2
import numpy as np
import torch

from colorgraph.config import settings
from colorgraph.domain.grade_graph import GradeGraph, MaskAsset
from colorgraph.grading.mask_integrity import (
    MASK_ASSET_SCHEMA,
    SUPPORTED_MASK_ASSET_SCHEMAS,
    MissingFramePolicy,
    inspect_mask_sequence,
    inspect_mask_video,
)

_TOKEN = re.compile(
    r"\s*(?:(AND|OR|NOT)\b|([A-Za-z_][A-Za-z0-9_.:-]*)|([()]))",
    re.IGNORECASE,
)
_PRECEDENCE = {"OR": 1, "AND": 2, "NOT": 3}


class _FfmpegMaskDecoder:
    def __init__(
        self,
        path: Path,
        *,
        width: int,
        height: int,
        fps: float,
        bit_depth: int,
    ) -> None:
        self.path = path
        self.width = width
        self.height = height
        self.fps = fps
        self.bit_depth = bit_depth
        self.output_pixel_format = "gray16le" if bit_depth > 8 else "gray"
        self.bytes_per_sample = 2 if bit_depth > 8 else 1
        self.frame_bytes = width * height * self.bytes_per_sample
        self.process: subprocess.Popen[bytes] | None = None
        self.position = 0

    def _start(self, frame_index: int) -> None:
        self.close()
        command = [
            settings.ffmpeg_binary,
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{frame_index / self.fps:.9f}",
            "-i",
            str(self.path),
            "-map",
            "0:v:0",
            "-an",
            "-sn",
            "-dn",
            "-f",
            "rawvideo",
            "-pix_fmt",
            self.output_pixel_format,
            "pipe:1",
        ]
        self.process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        if self.process.stdout is None:
            self.close()
            raise RuntimeError(f"could not open raw mask decoder for {self.path}")
        self.position = frame_index

    def _read_raw_frame(self) -> bytes:
        if self.process is None or self.process.stdout is None:
            raise RuntimeError("raw mask decoder is not running")
        payload = bytearray()
        while len(payload) < self.frame_bytes:
            chunk = self.process.stdout.read(self.frame_bytes - len(payload))
            if not chunk:
                break
            payload.extend(chunk)
        if len(payload) != self.frame_bytes:
            raise RuntimeError(
                f"raw mask decoder stopped at frame {self.position} for {self.path}"
            )
        self.position += 1
        return bytes(payload)

    def read(self, frame_index: int) -> np.ndarray:
        if self.process is None or frame_index < self.position:
            self._start(frame_index)
        while self.position < frame_index:
            self._read_raw_frame()
        payload = self._read_raw_frame()
        if self.bytes_per_sample == 2:
            frame = np.frombuffer(payload, dtype="<u2").reshape(
                self.height,
                self.width,
            )
            return frame.astype(np.float32) / 65535.0
        frame = np.frombuffer(payload, dtype=np.uint8).reshape(
            self.height,
            self.width,
        )
        return frame.astype(np.float32) / 255.0

    def close(self) -> None:
        process = self.process
        self.process = None
        if process is None:
            return
        if process.stdout is not None:
            process.stdout.close()
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)


def composite_mask_key(node_id: str) -> str:
    return f"__composite__:{node_id}"


def mask_expression_operands(expression: str) -> set[str]:
    """Return operands from the small, deliberately non-Turing-complete mask DSL."""

    return {
        token
        for token in _tokenize(expression)
        if token not in _PRECEDENCE and token not in {"(", ")"}
    }


def validate_mask_expression(expression: str) -> set[str]:
    """Validate the non-Turing-complete mask DSL without loading mask pixels."""

    postfix = _to_postfix(_tokenize(expression))
    depth = 0
    for token in postfix:
        if token == "NOT":
            if depth < 1:
                raise ValueError("NOT requires one mask operand")
        elif token in {"AND", "OR"}:
            if depth < 2:
                raise ValueError(f"{token} requires two mask operands")
            depth -= 1
        else:
            depth += 1
    if depth != 1:
        raise ValueError("invalid mask expression")
    return {
        token
        for token in postfix
        if token not in _PRECEDENCE and token not in {"(", ")"}
    }


def _tokenize(expression: str) -> list[str]:
    tokens: list[str] = []
    position = 0
    while position < len(expression):
        match = _TOKEN.match(expression, position)
        if match is None:
            if expression[position:].strip() == "":
                break
            raise ValueError(
                f"invalid mask expression near {expression[position : position + 20]!r}"
            )
        operator, operand, parenthesis = match.groups()
        tokens.append(operator.upper() if operator else operand or parenthesis)
        position = match.end()
    if not tokens:
        raise ValueError("mask expression cannot be empty")
    return tokens


def _to_postfix(tokens: list[str]) -> list[str]:
    output: list[str] = []
    operators: list[str] = []
    for token in tokens:
        if token not in _PRECEDENCE and token not in {"(", ")"}:
            output.append(token)
            continue
        if token == "(":
            operators.append(token)
            continue
        if token == ")":
            while operators and operators[-1] != "(":
                output.append(operators.pop())
            if not operators:
                raise ValueError("unbalanced mask expression parentheses")
            operators.pop()
            continue
        while (
            operators
            and operators[-1] != "("
            and (
                _PRECEDENCE[operators[-1]] > _PRECEDENCE[token]
                or (_PRECEDENCE[operators[-1]] == _PRECEDENCE[token] and token != "NOT")
            )
        ):
            output.append(operators.pop())
        operators.append(token)
    while operators:
        operator = operators.pop()
        if operator == "(":
            raise ValueError("unbalanced mask expression parentheses")
        output.append(operator)
    return output


def evaluate_mask_expression(
    expression: str,
    masks: Mapping[str, torch.Tensor],
    aliases: Mapping[str, str] | None = None,
) -> torch.Tensor:
    """Evaluate fuzzy AND/OR/NOT over mask tensors.

    Operands can be mask asset IDs or semantic targets. AND uses minimum,
    OR uses maximum, and NOT inverts the normalized mask.
    """

    resolved_aliases = aliases or {}
    stack: list[torch.Tensor] = []
    for token in _to_postfix(_tokenize(expression)):
        if token == "NOT":
            if not stack:
                raise ValueError("NOT requires one mask operand")
            stack.append(1.0 - stack.pop())
        elif token in {"AND", "OR"}:
            if len(stack) < 2:
                raise ValueError(f"{token} requires two mask operands")
            right = stack.pop()
            left = stack.pop()
            if left.shape != right.shape:
                raise ValueError(
                    f"mask expression operands have different shapes: "
                    f"{tuple(left.shape)} and {tuple(right.shape)}"
                )
            stack.append(
                torch.minimum(left, right) if token == "AND" else torch.maximum(left, right)
            )
        else:
            asset_id = resolved_aliases.get(token, token)
            if asset_id not in masks:
                raise ValueError(f"mask expression references unknown asset or target {token!r}")
            stack.append(masks[asset_id].clamp(0, 1))
    if len(stack) != 1:
        raise ValueError("invalid mask expression")
    return stack[0].clamp(0, 1)


class GraphMaskResolver:
    """Load only complete, declared frame-addressed mask assets.

    Missing frames are errors by default. ``hold_last`` must be selected
    explicitly by the caller and never converts missing or corrupt data into
    an all-zero grade mask.
    """

    def __init__(
        self,
        graph: GradeGraph,
        *,
        missing_frame_policy: MissingFramePolicy | str = MissingFramePolicy.ERROR,
        verify_storage: bool = True,
        sequence_decode_workers: int | None = None,
        include_unreferenced_assets: bool = False,
    ) -> None:
        self.graph = graph
        self.verify_storage = verify_storage
        worker_count = (
            min(4, os.cpu_count() or 1)
            if sequence_decode_workers is None
            else sequence_decode_workers
        )
        if worker_count <= 0:
            raise ValueError("sequence_decode_workers must be positive")
        self._decode_executor = (
            ThreadPoolExecutor(
                max_workers=worker_count,
                thread_name_prefix="colorgraph-mask-decode",
            )
            if worker_count > 1
            else None
        )
        self._captures: dict[str, cv2.VideoCapture] = {}
        self._raw_video_decoders: dict[str, _FfmpegMaskDecoder] = {}
        self._capture_positions: dict[str, int] = {}
        self._inspected_assets: set[str] = set()
        try:
            self.missing_frame_policy = MissingFramePolicy(missing_frame_policy)
        except ValueError as exc:
            raise ValueError(
                "missing_frame_policy must be 'error' or 'hold_last'"
            ) from exc

        asset_ids = [asset.id for asset in graph.masks]
        if len(asset_ids) != len(set(asset_ids)):
            raise ValueError("mask asset ids must be unique")
        alias_candidates: dict[str, set[str]] = {}
        for asset in graph.masks:
            metadata_target = asset.metadata.get("target")
            if metadata_target is not None and metadata_target != asset.target:
                raise ValueError(
                    f"mask asset {asset.id!r} metadata target "
                    f"{metadata_target!r} does not match {asset.target!r}"
                )
            declared_aliases = asset.metadata.get("target_aliases", [])
            if not isinstance(declared_aliases, list) or not all(
                isinstance(alias, str) and alias
                for alias in declared_aliases
            ):
                raise ValueError(
                    f"mask asset {asset.id!r} target_aliases must be a string list"
                )
            for alias in {asset.id, asset.target, *declared_aliases}:
                alias_candidates.setdefault(alias, set()).add(asset.id)

        directly_referenced_ids = {
            node.spatial_scope.mask_asset_id
            for node in graph.nodes
            if node.enabled and node.spatial_scope.mask_asset_id
        }
        known_ids = set(asset_ids)
        unknown_ids = directly_referenced_ids - known_ids
        if unknown_ids:
            raise ValueError(
                f"grade graph references unknown mask assets: {sorted(unknown_ids)}"
            )
        referenced_ids = set(directly_referenced_ids)
        self._composites = {
            composite_mask_key(node.id): node.spatial_scope.expression
            for node in graph.nodes
            if node.enabled and node.spatial_scope.expression
        }
        expression_aliases: dict[str, str] = {}
        for expression in self._composites.values():
            for operand in mask_expression_operands(expression):
                if operand in known_ids:
                    referenced_ids.add(operand)
                    continue
                candidates = alias_candidates.get(operand, set())
                if not candidates:
                    unknown_ids.add(operand)
                    continue
                if len(candidates) == 1:
                    resolved_id = next(iter(candidates))
                else:
                    active_candidates = candidates & directly_referenced_ids
                    if len(active_candidates) != 1:
                        raise ValueError(
                            f"mask expression alias {operand!r} is ambiguous across "
                            f"assets {sorted(candidates)}; reference an exact asset "
                            "id or directly select exactly one matching asset"
                        )
                    resolved_id = next(iter(active_candidates))
                expression_aliases[operand] = resolved_id
                referenced_ids.add(resolved_id)
        if unknown_ids:
            raise ValueError(
                f"grade graph references unknown mask assets: {sorted(unknown_ids)}"
            )
        if include_unreferenced_assets:
            referenced_ids.update(asset_ids)
        self.assets = {
            asset.id: asset
            for asset in graph.masks
            if asset.id in referenced_ids
        }
        self._aliases: dict[str, str] = {}
        for alias, candidates in alias_candidates.items():
            selected_candidates = candidates & referenced_ids
            if alias not in known_ids and len(selected_candidates) == 1:
                self._aliases[alias] = next(iter(selected_candidates))
        self._aliases.update(expression_aliases)
        for asset in self.assets.values():
            self._validate_asset_metadata(asset)

    def _validate_asset_metadata(self, asset: MaskAsset) -> None:
        metadata = asset.metadata
        schema = metadata.get("schema")
        if schema not in SUPPORTED_MASK_ASSET_SCHEMAS:
            raise ValueError(
                f"mask asset {asset.id!r} lacks a supported integrity "
                "metadata; regenerate the mask"
            )
        if schema == MASK_ASSET_SCHEMA:
            storage = metadata.get("storage")
            if not isinstance(storage, dict):
                raise ValueError(
                    f"mask asset {asset.id!r} lacks v3 storage metadata"
                )
            bit_depth = storage.get("bit_depth")
            sample_dtype = storage.get("sample_dtype")
            if bit_depth not in {8, 16}:
                raise ValueError(
                    f"mask asset {asset.id!r} bit_depth must be 8 or 16"
                )
            expected_dtype = "uint16" if bit_depth == 16 else "uint8"
            if sample_dtype != expected_dtype:
                raise ValueError(
                    f"mask asset {asset.id!r} sample_dtype must be "
                    f"{expected_dtype!r}"
                )
            if storage.get("sequence_format") != "png":
                raise ValueError(
                    f"mask asset {asset.id!r} sequence_format must be 'png'"
                )
            preferred_decode = storage.get("preferred_decode")
            if preferred_decode not in {"sequence", "video_ffmpeg"}:
                raise ValueError(
                    f"mask asset {asset.id!r} preferred_decode must be "
                    "'sequence' or 'video_ffmpeg'"
                )
            expected_video_format = "gray16le" if bit_depth == 16 else "gray"
            if storage.get("video_pixel_format") != expected_video_format:
                raise ValueError(
                    f"mask asset {asset.id!r} video_pixel_format must be "
                    f"{expected_video_format!r}"
                )
        if asset.frame_count is None or asset.frame_count <= 0:
            raise ValueError(f"mask asset {asset.id!r} has no positive frame_count")
        metadata_frame_count = metadata.get("frame_count")
        if metadata_frame_count != asset.frame_count:
            raise ValueError(
                f"mask asset {asset.id!r} frame_count metadata "
                f"{metadata_frame_count!r} does not match {asset.frame_count}"
            )
        if (
            self.graph.media.frame_count > 0
            and asset.frame_count != self.graph.media.frame_count
        ):
            raise ValueError(
                f"mask asset {asset.id!r} has {asset.frame_count} frames; "
                f"project media has {self.graph.media.frame_count}"
            )
        width = metadata.get("width")
        height = metadata.get("height")
        fps = metadata.get("fps")
        if (
            not isinstance(width, int)
            or isinstance(width, bool)
            or width <= 0
            or not isinstance(height, int)
            or isinstance(height, bool)
            or height <= 0
        ):
            raise ValueError(
                f"mask asset {asset.id!r} has invalid width/height metadata"
            )
        if not isinstance(fps, int | float) or isinstance(fps, bool) or fps <= 0:
            raise ValueError(f"mask asset {asset.id!r} has invalid fps metadata")
        tolerance = max(0.01, self.graph.media.fps * 0.001)
        if abs(float(fps) - self.graph.media.fps) > tolerance:
            raise ValueError(
                f"mask asset {asset.id!r} fps {fps} does not match "
                f"project fps {self.graph.media.fps}"
            )
        aliases = metadata.get("target_aliases")
        if (
            not isinstance(aliases, list)
            or asset.id not in aliases
            or asset.target not in aliases
        ):
            raise ValueError(
                f"mask asset {asset.id!r} must declare both id and target aliases"
            )
        if metadata.get("target") != asset.target:
            raise ValueError(
                f"mask asset {asset.id!r} target metadata does not match the asset"
            )
        sequence_checksum = metadata.get("sequence_sha256")
        sequence_required = (
            schema != MASK_ASSET_SCHEMA
            or metadata["storage"].get("preferred_decode") == "sequence"
        )
        if sequence_required and (
            not isinstance(sequence_checksum, str)
            or not re.fullmatch(r"[0-9a-f]{64}", sequence_checksum)
        ):
            raise ValueError(
                f"mask asset {asset.id!r} has no valid sequence_sha256"
            )
        video_path = metadata.get("video_path")
        if (
            schema == MASK_ASSET_SCHEMA
            and metadata["storage"].get("preferred_decode") == "video_ffmpeg"
            and (not isinstance(video_path, str) or not video_path)
        ):
            raise ValueError(
                f"mask asset {asset.id!r} video_ffmpeg storage has no video_path"
            )
        if video_path:
            video_checksum = metadata.get("video_sha256")
            if not isinstance(video_checksum, str) or not re.fullmatch(
                r"[0-9a-f]{64}",
                video_checksum,
            ):
                raise ValueError(
                    f"mask asset {asset.id!r} has no valid video_sha256"
                )

    @staticmethod
    def _frame_path(asset: MaskAsset, frame_index: int) -> Path:
        root = Path(asset.path)
        pattern = str(asset.metadata.get("file_pattern", "{frame_index:06d}.png"))
        try:
            filename = pattern.format(frame_index=frame_index)
        except (IndexError, KeyError, ValueError) as exc:
            raise ValueError(
                f"invalid mask file pattern for {asset.id}: {pattern}"
            ) from exc
        return root / filename

    def _inspect_asset_storage(self, asset: MaskAsset) -> None:
        if asset.id in self._inspected_assets:
            return
        frame_count = int(asset.frame_count or 0)
        width = int(asset.metadata["width"])
        height = int(asset.metadata["height"])
        fps = float(asset.metadata["fps"])
        prefers_video = (
            asset.metadata.get("schema") == MASK_ASSET_SCHEMA
            and asset.metadata["storage"].get("preferred_decode") == "video_ffmpeg"
        )
        if not prefers_video:
            inspect_mask_sequence(
                asset.path,
                expected_frame_count=frame_count,
                expected_width=width,
                expected_height=height,
                expected_bit_depth=(
                    int(asset.metadata["storage"]["bit_depth"])
                    if asset.metadata.get("schema") == MASK_ASSET_SCHEMA
                    else None
                ),
                expected_sha256=str(asset.metadata["sequence_sha256"]),
                missing_frame_policy=self.missing_frame_policy,
            )
        video_value = asset.metadata.get("video_path")
        if video_value:
            inspect_mask_video(
                str(video_value),
                expected_frame_count=frame_count,
                expected_width=width,
                expected_height=height,
                expected_fps=fps,
                expected_pixel_format=(
                    str(asset.metadata["storage"]["video_pixel_format"])
                    if asset.metadata.get("schema") == MASK_ASSET_SCHEMA
                    else None
                ),
                expected_sha256=str(asset.metadata["video_sha256"]),
            )
        self._inspected_assets.add(asset.id)

    def _sequence_frame_path(self, asset: MaskAsset, frame_index: int) -> Path:
        requested = self._frame_path(asset, frame_index)
        if requested.is_file():
            return requested
        if self.missing_frame_policy == MissingFramePolicy.ERROR:
            raise FileNotFoundError(
                f"mask asset {asset.id!r} is missing frame {frame_index}: {requested}"
            )
        for previous_index in range(frame_index - 1, -1, -1):
            previous = self._frame_path(asset, previous_index)
            if previous.is_file():
                return previous
        raise FileNotFoundError(
            f"mask asset {asset.id!r} cannot hold frame {frame_index}; "
            "no earlier frame exists"
        )

    def load_batch(
        self,
        frame_indices: list[int],
        *,
        device: torch.device | str | None = None,
        non_blocking: bool = True,
    ) -> dict[str, torch.Tensor]:
        if not frame_indices:
            return {}
        loaded: dict[str, torch.Tensor] = {}
        for asset_id, asset in self.assets.items():
            frame_count = int(asset.frame_count or 0)
            invalid_indices = [
                index
                for index in frame_indices
                if index < 0 or index >= frame_count
            ]
            if invalid_indices:
                raise IndexError(
                    f"mask asset {asset_id!r} frame indices are outside "
                    f"0..{frame_count - 1}: {invalid_indices}"
                )
            if self.verify_storage:
                self._inspect_asset_storage(asset)
            video_value = asset.metadata.get("video_path")
            preferred_decode = (
                asset.metadata["storage"].get("preferred_decode")
                if (
                    asset.metadata.get("schema") == MASK_ASSET_SCHEMA
                    and isinstance(asset.metadata.get("storage"), dict)
                )
                else None
            )
            if video_value and preferred_decode == "video_ffmpeg":
                loaded[asset_id] = self._load_ffmpeg_video_batch(
                    asset,
                    Path(str(video_value)),
                    frame_indices,
                )
                continue
            prefer_sequence = (
                asset.metadata.get("schema") == MASK_ASSET_SCHEMA
                and isinstance(asset.metadata.get("storage"), dict)
                and preferred_decode == "sequence"
            )
            if video_value and not prefer_sequence:
                loaded[asset_id] = self._load_video_batch(
                    asset_id,
                    Path(str(video_value)),
                    frame_indices,
                )
                continue
            expected_shape = (
                int(asset.metadata["height"]),
                int(asset.metadata["width"]),
            )
            expected_bit_depth = (
                int(asset.metadata["storage"]["bit_depth"])
                if asset.metadata.get("schema") == MASK_ASSET_SCHEMA
                else None
            )

            def decode(
                frame_index: int,
                current_asset: MaskAsset = asset,
                current_shape: tuple[int, int] = expected_shape,
                current_bit_depth: int | None = expected_bit_depth,
            ) -> np.ndarray:
                path = self._sequence_frame_path(current_asset, frame_index)
                frame = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
                if frame is None:
                    raise RuntimeError(
                        f"could not decode mask frame {frame_index} from {path}"
                    )
                if frame.ndim != 2:
                    raise ValueError(
                        f"mask frame {path} must be single-channel; "
                        f"got shape {frame.shape}"
                    )
                if frame.shape != current_shape:
                    raise ValueError(
                        f"mask frame {path} has shape {frame.shape}; "
                        f"expected {current_shape}"
                    )
                if frame.dtype == np.uint8:
                    bit_depth = 8
                    maximum = 255.0
                elif frame.dtype == np.uint16:
                    bit_depth = 16
                    maximum = 65535.0
                else:
                    raise ValueError(
                        f"mask frame {path} uses unsupported dtype {frame.dtype}"
                    )
                if current_bit_depth is not None and bit_depth != current_bit_depth:
                    raise ValueError(
                        f"mask frame {path} bit depth {bit_depth} does not match "
                        f"declared {current_bit_depth}"
                    )
                return frame.astype(np.float32) / maximum

            frames = (
                list(self._decode_executor.map(decode, frame_indices))
                if self._decode_executor is not None and len(frame_indices) > 1
                else [decode(frame_index) for frame_index in frame_indices]
            )
            loaded[asset_id] = torch.from_numpy(np.stack(frames))
        for composite_id, expression in self._composites.items():
            loaded[composite_id] = evaluate_mask_expression(
                expression,
                loaded,
                self._aliases,
            )
        if device is not None:
            target = torch.device(device)
            for asset_id, tensor in loaded.items():
                source = (
                    tensor.pin_memory()
                    if target.type == "cuda" and not tensor.is_pinned()
                    else tensor
                )
                loaded[asset_id] = source.to(
                    device=target,
                    non_blocking=non_blocking,
                )
        return loaded

    def _load_ffmpeg_video_batch(
        self,
        asset: MaskAsset,
        video_path: Path,
        frame_indices: list[int],
    ) -> torch.Tensor:
        decoder = self._raw_video_decoders.get(asset.id)
        if decoder is None:
            decoder = _FfmpegMaskDecoder(
                video_path,
                width=int(asset.metadata["width"]),
                height=int(asset.metadata["height"]),
                fps=float(asset.metadata["fps"]),
                bit_depth=int(asset.metadata["storage"]["bit_depth"]),
            )
            self._raw_video_decoders[asset.id] = decoder
        frames = [decoder.read(frame_index) for frame_index in frame_indices]
        return torch.from_numpy(np.stack(frames))

    def _load_video_batch(
        self,
        asset_id: str,
        video_path: Path,
        frame_indices: list[int],
    ) -> torch.Tensor:
        capture = self._captures.get(asset_id)
        if capture is None:
            capture = cv2.VideoCapture(str(video_path))
            if not capture.isOpened():
                raise RuntimeError(f"could not open mask video {video_path}")
            self._captures[asset_id] = capture
            self._capture_positions[asset_id] = 0
        first = frame_indices[0]
        if self._capture_positions[asset_id] != first:
            capture.set(cv2.CAP_PROP_POS_FRAMES, first)
            self._capture_positions[asset_id] = first
        expected_shape = (
            int(self.assets[asset_id].metadata["height"]),
            int(self.assets[asset_id].metadata["width"]),
        )
        frames: list[np.ndarray] = []
        for frame_index in frame_indices:
            if self._capture_positions[asset_id] != frame_index:
                capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
            success, frame = capture.read()
            if not success:
                raise RuntimeError(
                    f"could not decode frame {frame_index} from {video_path}"
                )
            if frame.ndim == 3:
                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            if frame.shape != expected_shape:
                raise ValueError(
                    f"decoded mask frame {frame_index} has shape {frame.shape}; "
                    f"expected {expected_shape}"
                )
            frames.append(frame.astype(np.float32) / 255.0)
            self._capture_positions[asset_id] = frame_index + 1
        return torch.from_numpy(np.stack(frames))

    def close(self) -> None:
        for capture in self._captures.values():
            capture.release()
        self._captures.clear()
        self._capture_positions.clear()
        for decoder in self._raw_video_decoders.values():
            decoder.close()
        self._raw_video_decoders.clear()
        executor = self._decode_executor
        if executor is not None:
            executor.shutdown(wait=True, cancel_futures=True)
            self._decode_executor = None

    def __del__(self) -> None:
        with suppress(Exception):
            self.close()
