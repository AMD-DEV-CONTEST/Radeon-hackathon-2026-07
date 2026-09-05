from __future__ import annotations

from pathlib import Path

import pandas as pd

from ...exceptions import ValidationError
from ..dataset_inspection import detect_source_format
from ..storage.models import DatasetSourceFormat
from ..tabular import load_pandas_frame_with_schema


def load_dataset(path: Path) -> pd.DataFrame:
    source_format = detect_source_format(path)
    if source_format is DatasetSourceFormat.UNKNOWN:
        raise ValidationError(f"Unsupported dataset format '{path.suffix}'.")
    return load_pandas_frame_with_schema(path, source_format, preserve_types=True).frame


def load_holdout_frame(path: Path) -> pd.DataFrame:
    return pd.read_pickle(path)
