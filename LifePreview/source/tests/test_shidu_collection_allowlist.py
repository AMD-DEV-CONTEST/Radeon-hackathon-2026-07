from __future__ import annotations

import importlib.util
import inspect
import sys
import types
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.testclient import TestClient

from creative_hub.shidu.collection_gateway import (
    COLLECTION_ROUTE,
    CollectionGateway,
)


ROOT = Path(__file__).resolve().parents[1]


class FakeDouyinWebCrawler:
    calls: list[tuple[str, int, int]] = []
    loaded_cookie = "sessionid=server-side-only"
    returned_video_count = 1

    async def get_douyin_headers(self) -> dict:
        return {"headers": {"Cookie": self.loaded_cookie}}

    async def fetch_user_collection_videos(
        self, cookie: str, cursor: int, count: int
    ) -> dict:
        self.calls.append((cookie, cursor, count))
        return {
            "collection_id": "douyin-personal-collection",
            "aweme_list": [
                {
                    "aweme_id": f"739000000000000000{index}",
                    "item_title": "公开视频标题",
                    "desc": "公开描述",
                    "author": {"sec_uid": "must-not-escape"},
                    "private_blob": self.loaded_cookie,
                }
                for index in range(1, self.returned_video_count + 1)
            ],
            "cursor": 777,
            "has_more": True,
            "credential": self.loaded_cookie,
        }


def _load_app() -> tuple[types.ModuleType, TestClient]:
    endpoint_router = APIRouter()

    async def allowed_endpoint() -> dict[str, bool]:
        return {"ok": True}

    for route_path, method in {
        "/fetch_one_video": "GET",
        "/fetch_user_post_videos": "GET",
        "/handler_user_profile": "GET",
        "/fetch_video_comments": "GET",
        "/fetch_video_comment_replies": "GET",
        "/get_sec_user_id": "GET",
        "/get_all_sec_user_id": "POST",
        "/get_aweme_id": "GET",
        "/get_all_aweme_id": "POST",
    }.items():
        endpoint_router.add_api_route(route_path, allowed_endpoint, methods=[method])

    async def collection_source(cookie: str, max_cursor: int = 0, counts: int = 20):
        raise AssertionError("the caller-cookie collection route must never be invoked")

    collection_source.__module__ = "app.api.endpoints.douyin_web"
    collection_source.__globals__["DouyinWebCrawler"] = FakeDouyinWebCrawler
    endpoint_router.add_api_route(
        "/fetch_user_collection_videos", collection_source, methods=["GET"]
    )

    fake_modules = {
        "app": types.ModuleType("app"),
        "app.api": types.ModuleType("app.api"),
        "app.api.endpoints": types.ModuleType("app.api.endpoints"),
        "app.api.endpoints.douyin_web": types.ModuleType(
            "app.api.endpoints.douyin_web"
        ),
        "upstream_cookie_control": types.ModuleType("upstream_cookie_control"),
    }
    fake_modules["app.api.endpoints.douyin_web"].router = endpoint_router
    fake_modules["upstream_cookie_control"].create_control_router = (
        lambda _path: APIRouter()
    )
    fake_modules["upstream_cookie_control"].read_secret_file = lambda _path: "token"

    async def load_cookie_state(_path: object) -> bool:
        return True

    def authorize(request, _path: object) -> None:
        if request.headers.get("authorization") != "Bearer internal-token":
            raise HTTPException(status_code=401, detail="authentication required")

    fake_modules["upstream_cookie_control"].load_cookie_state = load_cookie_state
    fake_modules["upstream_cookie_control"]._authorize = authorize

    previous = {name: sys.modules.get(name) for name in fake_modules}
    sys.modules.update(fake_modules)
    try:
        entrypoint_path = ROOT / "deploy/upstream_douyin_app.py"
        spec = importlib.util.spec_from_file_location(
            "task4_collection_app", entrypoint_path
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        client = TestClient(module.app)
    finally:
        for name, old_module in previous.items():
            if old_module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = old_module
    return module, client


def test_collection_wrapper_exposes_no_cookie_parameter_or_callable_argument() -> None:
    module, client = _load_app()
    schema = client.get("/openapi.json").json()
    parameters = schema["paths"][COLLECTION_ROUTE]["get"]["parameters"]
    endpoint = next(
        route.endpoint
        for route in module.build_shidu_collection_router().routes
        if getattr(route, "path", None) == COLLECTION_ROUTE
    )

    assert all(item["name"].lower() != "cookie" for item in parameters)
    assert "cookie" not in inspect.signature(endpoint).parameters
    assert "cookie" not in inspect.signature(CollectionGateway.list_videos).parameters


def test_collection_wrapper_is_authenticated_bounded_and_field_allowlisted() -> None:
    FakeDouyinWebCrawler.calls.clear()
    _module, client = _load_app()

    assert client.get(COLLECTION_ROUTE).status_code == 401
    assert (
        client.get(
            f"{COLLECTION_ROUTE}?page=-1&count=20",
            headers={"Authorization": "Bearer internal-token"},
        ).status_code
        == 422
    )
    assert (
        client.get(
            f"{COLLECTION_ROUTE}?page=0&count=51",
            headers={"Authorization": "Bearer internal-token"},
        ).status_code
        == 422
    )

    response = client.get(
        f"{COLLECTION_ROUTE}?page=7&count=2",
        headers={"Authorization": "Bearer internal-token"},
    )

    assert response.status_code == 200
    assert response.json() == [
        {
            "video_id": "7390000000000000001",
            "public_title": "公开视频标题",
            "public_description": "公开描述",
            "collection_id": "douyin-personal-collection",
        }
    ]
    assert FakeDouyinWebCrawler.calls == [
        (FakeDouyinWebCrawler.loaded_cookie, 7, 2)
    ]
    assert "server-side-only" not in response.text


def test_collection_gateway_uses_only_the_fixed_non_comment_route() -> None:
    assert COLLECTION_ROUTE == "/internal/shidu/collection-videos"
    assert "comment" not in COLLECTION_ROUTE


def test_collection_wrapper_fails_closed_when_upstream_exceeds_requested_count() -> None:
    FakeDouyinWebCrawler.returned_video_count = 2
    try:
        _module, client = _load_app()
        response = client.get(
            f"{COLLECTION_ROUTE}?page=0&count=1",
            headers={"Authorization": "Bearer internal-token"},
        )
        assert response.status_code == 502
        assert response.json() == {"detail": "collection upstream unavailable"}
    finally:
        FakeDouyinWebCrawler.returned_video_count = 1
