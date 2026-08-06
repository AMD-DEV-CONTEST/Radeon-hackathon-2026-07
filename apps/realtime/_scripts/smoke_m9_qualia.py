"""M9.4 smoke test — real Qualia SDK integration.

End-to-end sanity check that we talk to Qualia Studio with the user's key and
can round-trip a real finetune job.

Covered:
  * POST /api/v1/trainings/qualia/validate     — key works, returns ok=true
  * GET  /api/v1/trainings/qualia/instances    — at least one instance visible
  * GET  /api/v1/trainings/qualia/defaults?alg=act  — algo defaults + cost estimate
  * POST /api/v1/trainings    (train_backend=qualia, algo=act, tiny run)
  * GET  /api/v1/trainings/{id}                 — status enriched with qualia_status
  * POST /api/v1/trainings/{id}/cancel         — cancel routes through SDK

Dataset used for the real submit: ``lerobot/pusht`` (public HF LeRobot demo).
We budget **0.5 hours on n3-RTX-A4000x1 (4 cr/h = 2 credits)** then cancel
immediately after submission so only a tiny queue-up cost is incurred.

Run with QUALIA_API_TOKEN already set in apps/api/.env (no need to pass it).
"""
from __future__ import annotations

import os
import sys
import time

import httpx

API_URL = os.environ.get("API_URL", "http://localhost:8000")


def _strip_proxy_env() -> None:
    for k in (
        "http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY",
        "all_proxy", "ALL_PROXY",
    ):
        os.environ.pop(k, None)


SMOKE_EMAIL = "smoke_m94@botversex.dev"
SMOKE_PASSWORD = "smoke-password-123!"


def _auth(client: httpx.Client) -> str:
    """Reuse a persistent smoke account so repeated runs don't hit the
    /auth/register rate limiter (3/hour).
    """
    r = client.post(
        f"{API_URL}/api/v1/auth/login",
        json={"email": SMOKE_EMAIL, "password": SMOKE_PASSWORD},
    )
    if r.status_code == 200:
        return r.json()["access_token"]
    # first run: try to register
    r = client.post(
        f"{API_URL}/api/v1/auth/register",
        json={
            "email": SMOKE_EMAIL,
            "password": SMOKE_PASSWORD,
            "username": f"smoke_m94_{int(time.time())}",
        },
    )
    if r.status_code in (200, 201):
        return r.json()["access_token"]
    raise RuntimeError(f"auth failed: register {r.status_code} {r.text[:200]}")


def main() -> None:
    _strip_proxy_env()
    with httpx.Client(timeout=60.0, trust_env=False) as client:
        token = _auth(client)
        headers = {"Authorization": f"Bearer {token}"}

        # ── 1. validate key ────────────────────────────────────────────────
        r = client.post(f"{API_URL}/api/v1/trainings/qualia/validate", headers=headers)
        assert r.status_code == 200, f"validate {r.status_code}: {r.text[:200]}"
        body = r.json()
        assert body.get("ok") is True, f"validate not ok: {body}"
        print(f"[1/6] validate_key -> {body['message']}")

        # ── 2. list instances ──────────────────────────────────────────────
        r = client.get(f"{API_URL}/api/v1/trainings/qualia/instances", headers=headers)
        assert r.status_code == 200, f"instances {r.status_code}"
        instances = r.json().get("instances", [])
        assert len(instances) >= 1, "expected >=1 instance"
        ids = [i["id"] for i in instances]
        print(f"[2/6] instances ({len(instances)}): {ids}")
        assert any(i.startswith("n3-RTX-A4000") for i in ids), (
            "A4000 (cheapest) not in list — API surface changed?"
        )

        # ── 3. algo defaults ───────────────────────────────────────────────
        r = client.get(
            f"{API_URL}/api/v1/trainings/qualia/defaults?algorithm=act",
            headers=headers,
        )
        assert r.status_code == 200, f"defaults {r.status_code}"
        defaults = r.json()
        print(f"[3/6] act defaults -> {defaults['defaults']} cost={defaults['cost_estimate']}")
        assert defaults["defaults"]["instance_type"].startswith("n3-RTX-A4000")

        # ── 4. real tiny ACT job ───────────────────────────────────────────
        # lerobot/pusht is HF's official LeRobot demo dataset — guaranteed to
        # exist. We set hours=0.5 to keep the queued cost bounded, then cancel
        # immediately in step 6.
        submit = {
            "dataset_id": "lerobot/pusht",
            "dataset_hf_id": "lerobot/pusht",
            "algo": "act",
            "train_backend": "qualia",
            "epochs": 1,
            "batch_size": 32,
            "lr": 1e-4,
            "hidden": 64,
            "instance_type": "n3-RTX-A4000x1",
            "hours": 0.5,
            # lerobot/pusht stores its image stream at observation.image
            # (flat, without the .images.<slot> prefix). Our CAMERA_MAPPING
            # has a dedicated "image" -> image_top entry for this legacy shape.
            "camera_keys": ["observation.image"],
        }
        r = client.post(f"{API_URL}/api/v1/trainings", json=submit, headers=headers)
        assert r.status_code == 201, f"create {r.status_code}: {r.text[:400]}"
        job = r.json()
        job_id = job["id"]
        hp = job.get("hparams") or {}
        qualia_job_id = hp.get("qualia_job_id")
        print(f"[4/6] submitted db_job_id={job_id} qualia_job_id={qualia_job_id} status={job['status']}")
        assert job["status"] in ("running", "queued"), f"unexpected post-submit status: {job['status']}"
        assert qualia_job_id, f"hparams.qualia_job_id missing — submission didn't round-trip. hparams={hp}"

        # ── 5. status enrichment ───────────────────────────────────────────
        r = client.get(f"{API_URL}/api/v1/trainings/{job_id}", headers=headers)
        assert r.status_code == 200
        enriched = r.json()
        assert "qualia_status" in enriched, "GET /{id} didn't enrich with qualia_status"
        qs = enriched["qualia_status"]
        print(f"[5/6] qualia_status.status={qs.get('status')} phase={qs.get('phase')!r}")

        # ── 6. cancel (stops the credit meter) ─────────────────────────────
        r = client.post(f"{API_URL}/api/v1/trainings/{job_id}/cancel", headers=headers)
        assert r.status_code == 200, f"cancel {r.status_code}: {r.text[:200]}"
        cancel_body = r.json()
        print(f"[6/6] cancel -> status={cancel_body.get('status')} qualia={cancel_body.get('qualia_cancel', {}).get('status')}")
        assert cancel_body.get("status") == "cancelled", f"cancel did not flip status: {cancel_body}"

    print("\n=== M9.4 SMOKE: PASS ===")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as e:
        print(f"ASSERT FAIL: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}")
        sys.exit(1)
