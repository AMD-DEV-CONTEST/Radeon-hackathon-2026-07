# character-workshop/tests/test_image_gen_mock.py
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.image_gen import generate_portrait
from src.llm_role import generate_character


def test_mock_portrait(tmp_path):
    card = generate_character("A Matter warrior with red hair", affinity_pref="Matter", mock=True)
    out = tmp_path / "p.png"
    path = generate_portrait(card, out_path=out, ref_image=None, mock=True)
    assert path.exists()
    im = Image.open(path)
    assert im.size[0] > 64
