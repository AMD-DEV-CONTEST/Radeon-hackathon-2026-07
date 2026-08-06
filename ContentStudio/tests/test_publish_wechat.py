from pathlib import Path

from content_studio.publish.wechat import WeChatPublisher, WeChatError


class FakeResp:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json = json_data or {}
    def json(self):
        return self._json


class FakeHttp:
    def __init__(self):
        self.posts = []
        self.gets = []
        self._seq_post = []
        self._seq_get = []
    def queue_post(self, resp):
        self._seq_post.append(resp)
    def queue_get(self, resp):
        self._seq_get.append(resp)
    def post(self, url, **kw):
        self.posts.append((url, kw))
        return self._seq_post.pop(0) if self._seq_post else FakeResp(200, {})
    def get(self, url, **kw):
        self.gets.append((url, kw))
        return self._seq_get.pop(0) if self._seq_get else FakeResp(200, {})


def _img(path: Path):
    path.write_bytes(b"\xff\xd8\xff\xe0" + b"0" * 16)  # 假 JPEG
    return str(path)


def test_token_cached_between_calls(tmp_path):
    h = FakeHttp()
    h.queue_get(FakeResp(200, {"access_token": "TOK", "expires_in": 7200}))
    pub = WeChatPublisher("id", "secret", http=h)
    assert pub.get_access_token() == "TOK"
    assert pub.get_access_token() == "TOK"      # 第二次不重新请求
    assert len(h.gets) == 1


def test_token_refreshed_after_expiry():
    h = FakeHttp()
    h.queue_get(FakeResp(200, {"access_token": "T1", "expires_in": 0}))
    h.queue_get(FakeResp(200, {"access_token": "T2", "expires_in": 7200}))
    pub = WeChatPublisher("id", "secret", http=h)
    assert pub.get_access_token() == "T1"
    assert pub.get_access_token() == "T2"
    assert len(h.gets) == 2


def test_publish_article_full_flow(tmp_path):
    h = FakeHttp()
    h.queue_get(FakeResp(200, {"access_token": "TOK", "expires_in": 7200}))   # token
    h.queue_post(FakeResp(200, {"url": "http://img/1"}))                       # body img
    h.queue_post(FakeResp(200, {"media_id": "COVER"}))                         # cover
    h.queue_post(FakeResp(200, {"media_id": "DRAFT"}))                         # draft
    pub = WeChatPublisher("id", "secret", http=h)
    cover = _img(tmp_path / "c.jpg")
    body = [_img(tmp_path / "b.jpg")]
    media_id = pub.publish_article("标题", "摘要", "<p>正文</p>", cover, body)
    assert media_id == "DRAFT"
    # draft/add 的 body 含正文与图片 url
    draft_call = [c for c in h.posts if "draft/add" in c[0]][0]
    article = draft_call[1]["json"]["articles"][0]
    assert article["title"] == "标题"
    assert article["thumb_media_id"] == "COVER"
    assert "http://img/1" in article["content"]


def test_errcode_raises():
    h = FakeHttp()
    h.queue_get(FakeResp(200, {"errcode": 40013, "errmsg": "invalid appid"}))
    pub = WeChatPublisher("id", "secret", http=h)
    try:
        pub.get_access_token()
        assert False, "应抛错"
    except WeChatError as e:
        assert "40013" in str(e)


def test_40001_refreshes_and_retries(tmp_path):
    h = FakeHttp()
    h.queue_get(FakeResp(200, {"access_token": "BAD", "expires_in": 7200}))   # 首 token
    h.queue_post(FakeResp(200, {"errcode": 40001, "errmsg": "invalid credential"}))  # body img 失败
    h.queue_get(FakeResp(200, {"access_token": "GOOD", "expires_in": 7200}))  # 刷新
    h.queue_post(FakeResp(200, {"url": "http://img/1"}))                       # body img 重试成功
    h.queue_post(FakeResp(200, {"media_id": "COVER"}))
    h.queue_post(FakeResp(200, {"media_id": "DRAFT"}))
    pub = WeChatPublisher("id", "secret", http=h)
    cover = _img(tmp_path / "c.jpg")
    body = [_img(tmp_path / "b.jpg")]
    assert pub.publish_article("T", "S", "<p>x</p>", cover, body) == "DRAFT"
