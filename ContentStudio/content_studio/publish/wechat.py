"""公众号草稿箱：token / 正文图 / 封面素材 / 建草稿。"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

import httpx

from content_studio.core.pipeline import weave_images


class WeChatError(Exception):
    pass


class WeChatPublisher:
    BASE = "https://api.weixin.qq.com/cgi-bin"

    def __init__(self, app_id: str, app_secret: str, http: Any = None, sleeper: Callable[[float], None] = time.sleep):
        self.app_id = app_id
        self.app_secret = app_secret
        self._sleep = sleeper
        self._http = http if http is not None else httpx.Client(timeout=30)
        self._token: str | None = None
        self._token_expires = 0.0

    @staticmethod
    def _check(r) -> dict:
        if r.status_code != 200:
            raise WeChatError(f"HTTP {r.status_code}")
        data = r.json()
        if data.get("errcode"):
            raise WeChatError(f"{data.get('errcode')} {data.get('errmsg')}")
        return data

    def _invalidate(self) -> None:
        self._token = None
        self._token_expires = 0.0

    def get_access_token(self) -> str:
        if self._token and time.time() < self._token_expires - 300:
            return self._token
        r = self._http.get(f"{self.BASE}/token", params={
            "grant_type": "client_credential",
            "appid": self.app_id,
            "secret": self.app_secret,
        })
        data = self._check(r)
        if "access_token" not in data:
            raise WeChatError(f"无 access_token: {data}")
        self._token = data["access_token"]
        self._token_expires = time.time() + int(data.get("expires_in", 7200))
        return self._token

    def _tokened(self, path: str) -> tuple[str, dict]:
        return f"{self.BASE}/{path}", {"access_token": self.get_access_token()}

    def _retry(self, fn: Callable[[], Any]) -> Any:
        try:
            return fn()
        except WeChatError as e:
            if "40001" in str(e):
                self._invalidate()
                return fn()
            raise

    def upload_body_image(self, path: str | Path) -> str:
        p = Path(path)
        def do():
            url, params = self._tokened("media/uploadimg")
            with p.open("rb") as f:
                files = {"media": (p.name, f, "image/jpeg")}
                return self._check(self._http.post(url, params=params, files=files))["url"]
        return self._retry(do)

    def upload_cover_material(self, path: str | Path) -> str:
        p = Path(path)
        def do():
            url, params = self._tokened("material/add_material")
            params = dict(params); params["type"] = "image"
            with p.open("rb") as f:
                files = {"media": (p.name, f, "image/jpeg")}
                return self._check(self._http.post(url, params=params, files=files))["media_id"]
        return self._retry(do)

    def create_draft(self, article: dict) -> str:
        def do():
            url, params = self._tokened("draft/add")
            return self._check(self._http.post(url, params=params, json={"articles": [article]}))["media_id"]
        return self._retry(do)

    def publish_article(self, title: str, digest: str, body_html: str,
                        cover_path: str | Path, body_image_paths: list[str] | None = None) -> str:
        body_image_paths = body_image_paths or []
        urls = [self.upload_body_image(p) for p in body_image_paths]
        thumb = self.upload_cover_material(cover_path)
        content = weave_images(body_html or "", urls)
        article = {
            "title": title,
            "author": "Content Studio",
            "digest": digest or "",
            "content": content,
            "thumb_media_id": thumb,
            "need_open_comment": 0,
            "only_fans_can_comment": 0,
        }
        return self.create_draft(article)
