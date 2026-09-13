import pytest


@pytest.mark.asyncio
async def test_register_then_login(client):
    register_resp = await client.post(
        "/api/v1/auth/register",
        json={"email": "sre@aegis.dev", "password": "supersecret1", "full_name": "SRE One", "role": "sre"},
    )
    assert register_resp.status_code == 201
    assert register_resp.json()["role"] == "sre"

    login_resp = await client.post(
        "/api/v1/auth/login", json={"email": "sre@aegis.dev", "password": "supersecret1"}
    )
    assert login_resp.status_code == 200
    token = login_resp.json()["access_token"]
    assert token

    me_resp = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_resp.status_code == 200
    assert me_resp.json()["email"] == "sre@aegis.dev"


@pytest.mark.asyncio
async def test_login_wrong_password_rejected(client):
    await client.post(
        "/api/v1/auth/register",
        json={"email": "user@aegis.dev", "password": "correcthorse1", "full_name": "U", "role": "viewer"},
    )
    resp = await client.post("/api/v1/auth/login", json={"email": "user@aegis.dev", "password": "wrongpass"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_duplicate_registration_conflicts(client):
    payload = {"email": "dup@aegis.dev", "password": "supersecret1", "full_name": "Dup", "role": "viewer"}
    first = await client.post("/api/v1/auth/register", json=payload)
    assert first.status_code == 201
    second = await client.post("/api/v1/auth/register", json=payload)
    assert second.status_code == 409
