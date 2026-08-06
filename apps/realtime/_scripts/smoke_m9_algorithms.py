"""M9.3 smoke test — algorithm catalog + server-side recommendation.

Verifies that:
  * GET  /api/v1/trainings/algorithms          returns the full catalog with
    mlp_baseline + vision_mlp_baseline (local) and act + smolvla + pi0 + pi05
    (qualia, marked ``requires_cloud: true``) all present.
  * GET  /api/v1/trainings/algorithms/recommend picks the right algorithm
    for the three classic personas:
        - no camera, few episodes   → mlp_baseline  (local)
        - camera, few episodes      → vision_mlp_baseline (local)
        - camera, many episodes     → smolvla       (cloud, may be unavailable)

The endpoints require auth, so we log in (or register) a throwaway account
the same way smoke_m8_vision_train.py does.
"""
from __future__ import annotations

import os
import sys
import time
import uuid

import httpx

API_URL = os.environ.get("API_URL", "http://localhost:8000")


def _strip_proxy_env() -> None:
    for k in (
        "http_proxy",
        "https_proxy",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "all_proxy",
        "ALL_PROXY",
    ):
        os.environ.pop(k, None)


def _login_or_register(client: httpx.Client) -> str:
    email = f"smoke_m93_{uuid.uuid4().hex[:8]}@botversex.dev"
    password = "smoke-password-123!"
    username = f"smoke_m93_{int(time.time())}"

    r = client.post(
        f"{API_URL}/api/v1/auth/register",
        json={"email": email, "password": password, "username": username},
    )
    if r.status_code not in (200, 201):
        raise RuntimeError(f"register failed {r.status_code}: {r.text[:300]}")
    return r.json()["access_token"]


def main() -> None:
    _strip_proxy_env()
    with httpx.Client(timeout=10.0, trust_env=False) as client:
        token = _login_or_register(client)
        headers = {"Authorization": f"Bearer {token}"}

        # --- Catalog --------------------------------------------------------
        r = client.get(f"{API_URL}/api/v1/trainings/algorithms", headers=headers)
        assert r.status_code == 200, f"/algorithms {r.status_code}: {r.text[:200]}"
        body = r.json()
        algos = body.get("algorithms", [])
        ids = {a["id"] for a in algos}
        print(f"algorithms: {sorted(ids)}")
        for required in ("mlp_baseline", "vision_mlp_baseline", "act", "smolvla", "pi0", "pi05"):
            assert required in ids, f"{required} missing from catalog"
        cloud_ids = {a["id"] for a in algos if a.get("requires_cloud")}
        assert cloud_ids == {"act", "smolvla", "pi0", "pi05"}, f"unexpected cloud set {cloud_ids}"
        print(f"cloud algos (requires_cloud=true): {sorted(cloud_ids)}")
        print(f"qualia_configured: {body.get('qualia_configured')}")

        # --- Recommender: 3 personas ---------------------------------------
        personas = [
            # (label, has_camera, episode_count, expected_top_candidates)
            ("no-cam / few",       False, 3,  {"mlp_baseline"}),
            ("no-cam / many",      False, 40, {"act", "mlp_baseline"}),   # act only if qualia configured
            ("cam / few",          True,  3,  {"vision_mlp_baseline"}),
            ("cam / medium",       True,  10, {"vision_mlp_baseline"}),
            ("cam / lots",         True,  50, {"pi05", "smolvla", "vision_mlp_baseline"}),
        ]
        for label, has_cam, ep, expected in personas:
            r = client.get(
                f"{API_URL}/api/v1/trainings/algorithms/recommend",
                params={"has_camera": str(has_cam).lower(), "episode_count": ep},
                headers=headers,
            )
            assert r.status_code == 200, f"recommend {r.status_code}: {r.text[:200]}"
            rec = r.json()["recommended"]
            pick = rec["id"]
            print(f"  persona={label:22s} -> {pick:22s} ({rec.get('backend')})  reason={rec['reason']!r}")
            assert pick in expected, (
                f"persona {label}: got {pick!r}, expected one of {expected}"
            )

    print("\n=== M9.3 SMOKE: PASS ===")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as e:
        print(f"ASSERT FAIL: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)
