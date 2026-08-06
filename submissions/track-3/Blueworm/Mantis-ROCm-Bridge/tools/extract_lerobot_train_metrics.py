#!/usr/bin/env python3
"""Bounded, read-only parser for raw LeRobot 0.4.4 ACT training logs.

The running AMD ACT evidence workflow captures LeRobot 0.4.4 training output to
a log file.  LeRobot writes one tqdm progress snapshot per optimization step,
separated by carriage returns, and interleaves Python ``INFO`` log lines.  A
single captured snapshot looks like::

    step:700 smpl:6K ep:5 epch:1.18 loss:2.186 grdn:72.235 \\
    lr:1.0e-05 updt_s:0.193 data_s:0.115

This tool extracts those snapshots into ordered metric records and emits three
artifacts: a CSV table, a JSON summary receipt, and a PNG loss-vs-step plot.

Design rules (matching the sibling audit CLIs):

* **Read-only.**  The input log is read once and never modified; no network, no
  GPU, no LeRobot import.
* **Bounded parsing.**  Only fully-formed snapshots (all nine fields) become
  records.  tqdm carriage-return rewrites and ``INFO`` lines glued onto a
  snapshot are handled by splitting on ``\\r``/``\\n`` and searching each
  segment.  Duplicate steps resolve deterministically to the **last complete**
  record, and records are returned in strictly increasing ``step`` order.
* **Humanized step resolution.**  The ``step`` token may be humanized
  (``2K``) or a plain integer.  When a complete record shares a segment with a
  preceding tqdm progress numerator (``1800/60000 [...]``), that exact
  numerator is the record's step; otherwise the token is expanded exactly
  (``2K`` -> 2000) and a fractional expansion fails closed.
* **Fail closed.**  If no complete record is found, or any complete record
  carries a non-finite numeric value (``nan``/``inf``), parsing raises
  ``MetricsParseError`` and the CLI writes nothing.
* **Refuse to overwrite.**  Any pre-existing ``--csv`` / ``--json`` / ``--png``
  output aborts the CLI before any work is done.
* **Lightweight parsing.**  Everything except PNG rendering uses only the
  standard library; ``matplotlib`` is imported lazily inside :func:`write_png`
  so the unit-tested parse path stays dependency-free.
* **No convergence claim.**  The JSON carries an explicit claim boundary: it
  extracts raw log metrics only and makes no claim about training convergence,
  learned-policy quality, or task success.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterator


SCHEMA_VERSION = 1
LEROBOT_LOG_FORMAT_VERSION = "0.4.4"

# CSV column order is part of the public contract for downstream consumers.
CSV_FIELDS: tuple[str, ...] = (
    "step",
    "samples_text",
    "episode",
    "epoch",
    "loss",
    "grad_norm",
    "lr",
    "update_s",
    "data_s",
)


class MetricsParseError(ValueError):
    """Raised when a log cannot be parsed into finite metric records.

    Covers the two fail-closed conditions: zero complete records, or a
    non-finite numeric value in a complete record.
    """


# A numeric token that Python's ``float`` always accepts once matched:
# integers, decimals, scientific notation, and the special inf/infinity/nan
# spellings (case-insensitive via the compiled IGNORECASE flag).  ``infinity``
# is listed before ``inf`` so a longer spelling is not truncated.
_NUMBER = r"[+-]?(?:infinity|inf|nan|(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)"
# Samples carry an optional thousands/millions/billions suffix, e.g. ``6K``.
_SAMPLES = r"\d+(?:\.\d+)?[KMB]?"
# Step may be a plain integer (``1800``) or a humanized count carrying an
# optional K/M/B suffix (``2K``, ``1.8K``, ``1M``, ``1.5B``).  LeRobot
# humanizes the running step once it is large enough, so the raw token is not
# always an integer; the suffix is expanded deterministically in
# :func:`_resolve_step`.
_HUMANIZED = r"\d+(?:\.\d+)?[KMB]?"
_INT = r"\d+"

# A tqdm progress bar packs ``numerator/denominator`` followed by an
# elapsed/remaining-time bracket, e.g. ``1800/60000 [09:34<4:50:23]``.  The
# trailing ``[`` is the discriminator that marks the pair as a tqdm bar rather
# than an incidental ``a/b`` (a date, a ratio) elsewhere in the text.
_TQDM_PROGRESS = re.compile(r"(?P<num>\d+)\s*/\s*\d+\s*\[")

# A complete record requires all nine fields in LeRobot's fixed order.  The
# pattern is searched (not anchored) so leading ``INFO`` text or trailing tqdm
# residue on the same segment does not prevent a match.
_RECORD = re.compile(
    r"step:(?P<step>" + _HUMANIZED + r")"
    r"\s+smpl:(?P<samples_text>" + _SAMPLES + r")"
    r"\s+ep:(?P<episode>" + _INT + r")"
    r"\s+epch:(?P<epoch>" + _NUMBER + r")"
    r"\s+loss:(?P<loss>" + _NUMBER + r")"
    r"\s+grdn:(?P<grad_norm>" + _NUMBER + r")"
    r"\s+lr:(?P<lr>" + _NUMBER + r")"
    r"\s+updt_s:(?P<update_s>" + _NUMBER + r")"
    r"\s+data_s:(?P<data_s>" + _NUMBER + r")",
    re.IGNORECASE,
)

# tqdm rewrites the progress bar in place using ``\r``; captured logs therefore
# pack many snapshots into one ``\n``-delimited line.  Split on either so each
# snapshot becomes its own segment.
_SEGMENT_SPLIT = re.compile(r"[\r\n]")
# Strip ANSI colour escapes defensively; logs captured through a pty may carry
# them even though a redirected file normally does not.
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


@dataclass(frozen=True)
class MetricRecord:
    """One fully-parsed, finite training snapshot.

    Numeric fields hold parsed ``float``/``int`` values for computation; the
    ``*_text`` twins preserve the original token so the CSV can render values
    such as ``lr:1.0e-05`` faithfully rather than via float reformatting.
    """

    step: int
    samples_text: str
    episode: int
    epoch: float
    loss: float
    grad_norm: float
    lr: float
    update_s: float
    data_s: float
    epoch_text: str
    loss_text: str
    grad_norm_text: str
    lr_text: str
    update_s_text: str
    data_s_text: str

    def as_csv_row(self) -> dict[str, Any]:
        """Return the record as a CSV-row dict keyed by :data:`CSV_FIELDS`."""
        return {
            "step": self.step,
            "samples_text": self.samples_text,
            "episode": self.episode,
            "epoch": self.epoch_text,
            "loss": self.loss_text,
            "grad_norm": self.grad_norm_text,
            "lr": self.lr_text,
            "update_s": self.update_s_text,
            "data_s": self.data_s_text,
        }


def _iter_segments(text: str) -> Iterator[str]:
    """Yield ANSI-stripped, non-empty log segments split on ``\\r``/``\\n``."""
    for raw in _SEGMENT_SPLIT.split(text):
        segment = _ANSI.sub("", raw).strip()
        if segment:
            yield segment


def _finite_float(token: str, field: str) -> float:
    """Parse ``token`` and fail closed if it is not finite.

    The regex guarantees ``token`` parses with ``float``; the only remaining
    rejection is a non-finite value (``nan``/``inf``).
    """
    value = float(token)
    if not math.isfinite(value):
        raise MetricsParseError(
            f"non-finite numeric value for {field!r}: {token!r}"
        )
    return value


# K/M/B -> exact integer scale factors for humanized step expansion.  Decimal
# keeps the expansion exact so a value like ``1.8K`` never drifts on float
# rounding.
_STEP_SCALE = {
    "K": Decimal(1000),
    "M": Decimal(1_000_000),
    "B": Decimal(1_000_000_000),
}


def _tqdm_step_override(segment: str, match: re.Match[str]) -> int | None:
    """Return the nearest tqdm progress numerator preceding ``match``.

    tqdm rewrites a single bar in place, so a captured segment often packs the
    bar's exact ``numerator/denominator`` immediately before the humanized
    metric block (``... 1800/60000 [...] ... step:2K ...``).  That numerator is
    the authoritative per-step count and is more precise than the rounded
    ``2K`` token, so when one is present it wins.  Only numerators that precede
    the record on the same segment are considered; the nearest (last) one wins.
    """
    last: int | None = None
    for progress in _TQDM_PROGRESS.finditer(segment[: match.start()]):
        last = int(progress.group("num"))
    return last


def _expand_step(token: str) -> int:
    """Expand a humanized step token to an int, failing closed on fractions.

    ``2K`` -> 2000, ``1.8K`` -> 1800, ``1M``/``1.5B`` likewise; a plain integer
    is returned unchanged.  ``Decimal`` is used so the expansion is exact; any
    token whose expansion is not a whole number (e.g. ``1.5`` with no suffix or
    ``1.2345K``) fails closed rather than being silently truncated.
    """
    upper = token.upper()
    scale = _STEP_SCALE.get(upper[-1])
    mantissa = upper[:-1] if scale is not None else upper
    value = Decimal(mantissa) * scale if scale is not None else Decimal(mantissa)
    if value % 1 != 0:
        raise MetricsParseError(
            f"step token 'step:{token}' expands to a non-integer step: {value}"
        )
    return int(value)


def _resolve_step(segment: str, match: re.Match[str]) -> int:
    """Resolve a matched record's step: tqdm numerator overrides humanized token."""
    override = _tqdm_step_override(segment, match)
    if override is not None:
        return override
    return _expand_step(match.group("step"))


def _record_from_match(segment: str, match: re.Match[str]) -> MetricRecord:
    g = match.group
    return MetricRecord(
        step=_resolve_step(segment, match),
        samples_text=g("samples_text"),
        episode=int(g("episode")),
        epoch=_finite_float(g("epoch"), "epoch"),
        loss=_finite_float(g("loss"), "loss"),
        grad_norm=_finite_float(g("grad_norm"), "grad_norm"),
        lr=_finite_float(g("lr"), "lr"),
        update_s=_finite_float(g("update_s"), "update_s"),
        data_s=_finite_float(g("data_s"), "data_s"),
        epoch_text=g("epoch"),
        loss_text=g("loss"),
        grad_norm_text=g("grad_norm"),
        lr_text=g("lr"),
        update_s_text=g("update_s"),
        data_s_text=g("data_s"),
    )


def parse_metrics(text: str) -> list[MetricRecord]:
    """Parse raw LeRobot training-log text into ordered metric records.

    Fully-formed snapshots are collected in file order; for each ``step`` the
    **last complete** snapshot wins, and the result is sorted by ``step``
    ascending.  Fails closed (:class:`MetricsParseError`) when no complete
    record is found or any complete record carries a non-finite value.
    """
    if not isinstance(text, str):
        raise MetricsParseError(
            f"expected str log text, got {type(text).__name__}"
        )

    by_step: dict[int, MetricRecord] = {}
    for segment in _iter_segments(text):
        for match in _RECORD.finditer(segment):
            record = _record_from_match(segment, match)
            by_step[record.step] = record  # last complete record wins

    records = sorted(by_step.values(), key=lambda record: record.step)
    if not records:
        raise MetricsParseError("no metric records found in training log")
    return records


def summarize(
    records: list[MetricRecord], *, source: Path | None = None
) -> dict[str, Any]:
    """Build the JSON summary receipt for ``records``.

    Includes the required step/loss boundaries, the minimum-loss location, and
    an explicit no-convergence claim boundary.  Deterministic: on equal losses
    the smallest step wins.
    """
    if not records:
        # Defensive: parse_metrics already guards this, but summarize is a
        # public entry point so it must fail closed too.
        raise MetricsParseError("cannot summarize an empty record list")

    # Tie-break by step (records are step-sorted, so index order == step order).
    min_index = min(
        range(len(records)), key=lambda i: (records[i].loss, records[i].step)
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "lerobot_log_format_version": LEROBOT_LOG_FORMAT_VERSION,
        "record_count": len(records),
        "first_step": records[0].step,
        "last_step": records[-1].step,
        "first_loss": records[0].loss,
        "last_loss": records[-1].loss,
        "min_loss": records[min_index].loss,
        "min_loss_step": records[min_index].step,
        "csv_fields": list(CSV_FIELDS),
        "source_log": str(source) if source is not None else None,
        "records": [record.as_csv_row() for record in records],
        "claim_boundary": {
            "convergence_claimed": False,
            "statement": (
                "NO CONVERGENCE CLAIM. This receipt extracts raw LeRobot "
                "training-log metrics (loss, gradient norm, learning rate, "
                "per-step timings) only. It makes no claim about training "
                "convergence, learned-policy quality, generalization, task "
                "success, hardware, GPU, AMD, ROCm, or closed-loop behavior."
            ),
        },
    }


def write_csv(records: list[MetricRecord], path: Path) -> None:
    """Write ``records`` to ``path`` as CSV with :data:`CSV_FIELDS` columns."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for record in records:
            writer.writerow(record.as_csv_row())


def write_json(summary: dict[str, Any], path: Path) -> None:
    """Write ``summary`` to ``path`` as pretty, sorted JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(summary, indent=2, sort_keys=True) + "\n"
    path.write_text(rendered, encoding="utf-8")


def write_png(records: list[MetricRecord], path: Path) -> None:
    """Render a loss-vs-step PNG.

    ``matplotlib`` is imported here and only here, keeping the parse path
    dependency-free.  The ``Agg`` backend is selected before ``pyplot`` so the
    render works headless.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    path.parent.mkdir(parents=True, exist_ok=True)
    figure, axis = plt.subplots(figsize=(8.0, 5.0))
    axis.plot(
        [record.step for record in records],
        [record.loss for record in records],
        marker="o",
        markersize=3,
        linewidth=1.2,
    )
    axis.set_xlabel("training step")
    axis.set_ylabel("loss")
    axis.set_title("LeRobot ACT training loss vs step")
    axis.grid(True, alpha=0.3)
    figure.tight_layout()
    figure.savefig(path, dpi=120)
    plt.close(figure)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Extract LeRobot 0.4.4 ACT training metrics to CSV/JSON/PNG.",
    )
    parser.add_argument("log", type=Path, help="path to the raw training log")
    parser.add_argument("--csv", type=Path, required=True, help="output CSV path")
    parser.add_argument("--json", type=Path, required=True, help="output JSON path")
    parser.add_argument("--png", type=Path, required=True, help="output PNG path")
    args = parser.parse_args(argv)

    # Refuse to overwrite ANY output before reading or parsing anything.
    for output in (args.csv, args.json, args.png):
        if output.exists():
            parser.error(f"refusing to overwrite existing output: {output}")

    try:
        text = args.log.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        print(f"error: cannot read input log {args.log}: {exc}", file=sys.stderr)
        return 1

    try:
        records = parse_metrics(text)
    except MetricsParseError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    summary = summarize(records, source=args.log)
    write_csv(records, args.csv)
    write_json(summary, args.json)
    write_png(records, args.png)

    print(
        f"extracted {len(records)} records "
        f"(step {records[0].step}..{records[-1].step}; "
        f"loss {records[0].loss}..{records[-1].loss}; "
        f"min {summary['min_loss']} @ step {summary['min_loss_step']}) -> "
        f"{args.csv}, {args.json}, {args.png}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
