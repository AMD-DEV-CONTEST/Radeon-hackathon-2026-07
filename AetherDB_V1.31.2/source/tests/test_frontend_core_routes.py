import services.database_registry as registry
from app.dependencies.auth import ADMIN_API_KEY, USER_API_KEY
from main import app
from services.db import close_connection, get_db, init_db
from tests.asgi_client import asgi_request


def configure_runtime(tmp_path, monkeypatch):
    root = tmp_path / "runtime"
    monkeypatch.setattr(registry, "REGISTRY_PATH", str(root / "registry.db"))
    monkeypatch.setattr(registry, "DATABASES_ROOT", str(root / "databases"))
    monkeypatch.setattr(registry, "OLD_DB_PATH", str(root / "missing.db"))
    registry.init_registry()
    init_db()


def test_legacy_home_page_renders_with_current_starlette(tmp_path, monkeypatch):
    configure_runtime(tmp_path, monkeypatch)

    status, body = asgi_request(app, "GET", "/")

    assert status == 200
    assert "<!DOCTYPE html>" in body
    assert "世界观数据库管理系统 V1.31.2" in body
    close_connection()


def test_entity_collection_route_supports_pagination_and_filters(tmp_path, monkeypatch):
    configure_runtime(tmp_path, monkeypatch)
    db = get_db()
    db.executemany(
        "INSERT INTO entities(entity_id,entity_type,title,content,book_id,is_active) VALUES (?,?,?,?,?,?)",
        [
            ("CHAR_A", "character", "阿岚", "北境守卫", "book-a", 1),
            ("LOC_A", "location", "北境长城", "雪山关隘", "book-a", 1),
            ("CHAR_OLD", "character", "旧角色", "不应返回", "book-a", 0),
            ("CHAR_B", "character", "别卷角色", "另一本作品", "book-b", 1),
        ],
    )
    db.execute(
        "INSERT INTO relations(source_id,target_id,relation_type,book_id) VALUES (?,?,?,?)",
        ("CHAR_A", "LOC_A", "guards", "book-a"),
    )
    db.commit()
    db.close()

    assert asgi_request(app, "GET", "/api/entity")[0] == 401
    status, payload = asgi_request(
        app,
        "GET",
        "/api/entity",
        headers={"X-API-Key": USER_API_KEY},
        params={"book_id": "book-a", "entity_type": "character", "limit": 20},
    )
    assert status == 200
    assert payload["total"] == 1
    assert payload["entities"][0]["entity_id"] == "CHAR_A"
    assert payload["entities"][0]["relation_count"] == 1
    assert payload["results"] == payload["entities"]
    close_connection()


def test_chapter_write_routes_accept_json_without_breaking_query_compatibility(tmp_path, monkeypatch):
    configure_runtime(tmp_path, monkeypatch)
    user = {"X-API-Key": USER_API_KEY}
    admin = {"X-API-Key": ADMIN_API_KEY}

    status, created = asgi_request(
        app,
        "POST",
        "/api/books/default/chapters",
        headers=user,
        json_body={"title": "JSON 创建章节", "volume_id": "VOL_1"},
    )
    assert status == 200
    chapter_id = created["chapter_id"]

    status, saved = asgi_request(
        app,
        "PUT",
        f"/api/chapters/{chapter_id}",
        headers=admin,
        json_body={"title": "正式标题", "content": "正式正文" * 40, "status": "draft"},
    )
    assert status == 200
    assert saved["word_count"] == len("正式正文" * 40)

    assert asgi_request(
        app,
        "POST",
        f"/api/chapters/{chapter_id}/autosave",
        headers=user,
        params={"content": "兼容旧调用", "title": "旧调用标题"},
    )[0] == 200

    status, chapter = asgi_request(app, "GET", f"/api/chapters/{chapter_id}", headers=user)
    assert status == 200
    assert chapter["chapter"]["title"] == "旧调用标题"
    assert chapter["chapter"]["content"] == "兼容旧调用"
    close_connection()
