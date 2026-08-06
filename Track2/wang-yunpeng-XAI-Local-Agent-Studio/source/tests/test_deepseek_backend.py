"""DeepSeekBackend 测试：离线（monkeypatch _post），不联网、不触及真实 key。"""

import math
import os
import unittest
from unittest import mock

from core.deepseek_backend import DeepSeekBackend
from core.model_backend import ModelResponse


def fake_out(text, logprobs=None):
    choice = {"message": {"content": text}, "logprobs": logprobs}
    return {"choices": [choice]}


class TestDeepSeekBackend(unittest.TestCase):
    def _backend(self):
        b = DeepSeekBackend(api_key="sk-test-dummy", model="deepseek-chat")
        return b

    def test_complete_returns_content(self):
        b = self._backend()
        b._post = lambda payload: fake_out("你好，这是 DeepSeek 的回答")
        self.assertEqual(b.complete("你好"), "你好，这是 DeepSeek 的回答")

    def test_complete_with_confidence_shape(self):
        b = self._backend()
        b._post = lambda payload: fake_out("答案", logprobs={"content": [
            {"logprob": math.log(0.9)}, {"logprob": math.log(0.8)}
        ]})
        r = b.complete_with_confidence("问题")
        self.assertIsInstance(r, ModelResponse)
        self.assertEqual(r.text, "答案")
        self.assertGreaterEqual(r.confidence, 0.0)
        self.assertLessEqual(r.confidence, 1.0)

    def test_missing_key_raises(self):
        with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": ""}):
            with self.assertRaises(RuntimeError):
                DeepSeekBackend(api_key=None)

    def test_confidence_from_logprobs(self):
        b = self._backend()
        # 高置信 token（logprob≈0）→ 置信接近 1
        b._post = lambda payload: fake_out("x", logprobs={"content": [{"logprob": -0.01}]})
        r = b.complete_with_confidence("q")
        self.assertGreater(r.confidence, 0.9)

    def test_logprobs_unsupported_degrades(self):
        b = self._backend()
        # _post 对 logprobs 请求抛错 → 降级返回文本，置信 0.5
        def side(payload):
            if payload.get("logprobs"):
                raise RuntimeError("logprobs not supported")
            return fake_out("降级回答")
        b._post = side
        r = b.complete_with_confidence("q")
        self.assertEqual(r.text, "降级回答")
        self.assertEqual(r.confidence, 0.5)


if __name__ == "__main__":
    unittest.main()
