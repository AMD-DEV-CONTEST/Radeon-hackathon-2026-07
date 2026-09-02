from pycalc.analysis import normalize
from pycalc.report import summary_text


def test_summary_includes_all_values():
    values = list(range(10))
    text = summary_text(values, title="Demo")
    normalized = [str(value) for value in normalize(values)]
    for item in normalized:
        assert item in text
    assert text.startswith("# Demo")
