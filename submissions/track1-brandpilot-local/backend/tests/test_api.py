from uuid import uuid4

def create_with_asset(client, payload, image_bytes):
    project = client.post("/projects", json=payload).json()
    upload = client.post(f"/projects/{project['project_id']}/assets", files={"file":("private-name.png",image_bytes,"image/png")})
    assert upload.status_code == 201
    return project

def test_health_and_system_info(client):
    assert client.get("/health").json() == {"status":"ok","service":"brandpilot-backend","mode":"mock"}
    info = client.get("/system-info").json()
    assert info["gpu_connected"] is False and info["rocm_available"] is False and info["device"] is None

def test_project_creation_and_invalid_id(client, payload):
    response = client.post("/projects", json=payload)
    assert response.status_code == 201
    assert response.json()["configuration"]["product_name"] == "Test Product"
    assert client.get("/projects/not-a-uuid").status_code == 404
    assert client.get(f"/projects/{uuid4()}").status_code == 404

def test_valid_and_invalid_upload(client, payload, image_bytes):
    project = client.post("/projects", json=payload).json()
    valid = client.post(f"/projects/{project['project_id']}/assets", files={"file":("unsafe name.png",image_bytes,"image/png")})
    assert valid.status_code == 201
    assert "unsafe" not in valid.json()["storage_name"]
    invalid = client.post(f"/projects/{project['project_id']}/assets", files={"file":("fake.png",b"not an image","image/png")})
    assert invalid.status_code == 400

def test_oversized_upload(client, payload):
    project = client.post("/projects", json=payload).json()
    response = client.post(f"/projects/{project['project_id']}/assets", files={"file":("large.png",b"x"*(10*1024*1024+1),"image/png")})
    assert response.status_code == 413


def test_authenticated_cors_preflight_is_explicit(client):
    response = client.options(
        "/projects",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    methods = response.headers["access-control-allow-methods"]
    assert all(method in methods for method in ("GET", "POST", "PATCH", "OPTIONS"))
    headers = response.headers["access-control-allow-headers"].lower()
    assert "authorization" in headers
    assert "content-type" in headers
    assert response.headers["access-control-allow-origin"] != "*"


def test_unknown_cors_origin_is_denied(client):
    preflight = client.options(
        "/projects",
        headers={
            "Origin": "https://unknown.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert preflight.status_code == 400
    assert "access-control-allow-origin" not in preflight.headers
    actual = client.get("/health", headers={"Origin": "https://unknown.example"})
    assert "access-control-allow-origin" not in actual.headers

def test_generation_review_edit_and_regenerate(client, payload, image_bytes):
    project = create_with_asset(client,payload,image_bytes)
    generated = client.post(f"/projects/{project['project_id']}/generate")
    assert generated.status_code == 200
    results = generated.json()["results"]
    assert [r["style"] for r in results] == ["Luxury","Minimal Studio","Lifestyle","Promotional Sale"]
    assert all("without AMD Radeon inference" in r["disclosure"] for r in results)
    result = results[0]
    reviewed = client.post(f"/projects/{project['project_id']}/results/{result['result_id']}/review",json={"status":"approved","note":"Ready"})
    assert reviewed.json()["human_review_status"] == "approved"
    edited = client.patch(f"/projects/{project['project_id']}/results/{result['result_id']}",json={"headline":"Updated headline","caption":"Updated caption","call_to_action":"Explore"})
    assert edited.json()["headline"] == "Updated headline"
    regenerated = client.post(f"/projects/{project['project_id']}/results/{result['result_id']}/regenerate")
    assert regenerated.json()["revision"] == 2
    assert "without AMD Radeon inference" in regenerated.json()["disclosure"]
