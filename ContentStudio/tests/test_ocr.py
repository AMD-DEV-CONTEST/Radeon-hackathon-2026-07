from content_studio.core import ocr


def test_extract_text_init_failure_returns_empty():
    def bad_init(): raise RuntimeError("no paddle")
    assert ocr.extract_text(["a.png"], initializer=bad_init) == ""


def test_extract_text_collects_lines_via_initializer():
    class FakeOCR:
        def ocr(self, path, cls=True):
            return [[[[0, 0], [1, 1]], ("识别的文字A", 0.9)]]
    def good_init(): return FakeOCR()
    out = ocr.extract_text(["a.png"], initializer=good_init)
    assert "识别的文字A" in out


def test_extract_text_skips_failing_image_but_keeps_good(monkeypatch):
    class FakeOCR:
        def __init__(self): self.first = True
        def ocr(self, path, cls=True):
            if self.first:
                self.first = False
                raise RuntimeError("boom")
            return [[[[0, 0], [1, 1]], ("好的文字", 0.9)]]
    def good_init(): return FakeOCR()
    out = ocr.extract_text(["a.png", "b.png"], initializer=good_init)
    assert "好的文字" in out


def test_extract_text_collects_paddleocr3x_dict_shape():
    # paddleocr 3.x：predict 返回的列表里直接是含 rec_texts 的 dict
    class FakeOCR3x:
        def predict(self, path):
            return [{"rec_texts": ["三零文字甲", "三零文字乙"]}]
    def good_init(): return FakeOCR3x()
    out = ocr.extract_text(["a.png"], initializer=good_init)
    assert "三零文字甲" in out
    assert "三零文字乙" in out
